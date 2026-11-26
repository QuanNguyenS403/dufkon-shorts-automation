"""SQLite WAL state, lease, rights, QC, and idempotent publication ledger for Dufkon Shorts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "dufkon.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    handle TEXT NOT NULL,
    expected_email TEXT NOT NULL,
    mission_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    series TEXT NOT NULL DEFAULT 'extreme_science',
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'IDEA',
    script_hash TEXT,
    render_hash TEXT,
    qc_score INTEGER,
    qc_status TEXT,
    contains_synthetic_media INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    scene_index INTEGER NOT NULL,
    speaker TEXT NOT NULL,
    narration TEXT NOT NULL,
    flow_prompt TEXT,
    stock_query TEXT,
    source_citation TEXT,
    duration_s REAL,
    UNIQUE(episode_id, revision, scene_index)
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL,
    scene_index INTEGER NOT NULL,
    source_provider TEXT NOT NULL,
    source_url TEXT,
    author TEXT,
    license_name TEXT,
    commercial_allowed INTEGER NOT NULL DEFAULT 1,
    attribution_text TEXT,
    checksum_sha256 TEXT,
    local_path TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    input_hash TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_until TEXT,
    heartbeat_at TEXT,
    retry_at TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS qc_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    render_hash TEXT,
    score INTEGER NOT NULL,
    decision TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT NOT NULL,
    session_uri TEXT,
    video_id TEXT,
    desired_privacy TEXT NOT NULL,
    actual_privacy TEXT,
    publish_at_utc TEXT,
    status TEXT NOT NULL,
    uploaded_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(channel_id, episode_id)
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    window_label TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    UNIQUE(video_id, window_label, fetched_at)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_db_path(db_path: Path | None = None) -> Path:
    if db_path is not None:
        return db_path
    env_path = os.getenv("DUFKON_DB_PATH", "").strip()
    return Path(env_path) if env_path else DEFAULT_DB_PATH


@contextmanager
def get_conn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    target = resolve_db_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> Path:
    target = resolve_db_path(db_path)
    with get_conn(target) as conn:
        conn.executescript(SCHEMA_SQL)
    return target


def compute_script_hash(job: dict[str, Any]) -> str:
    canonical = {
        "title": job.get("title", ""),
        "description": job.get("description", ""),
        "scenes": [
            {
                "index": s.get("index"),
                "speaker": s.get("speaker"),
                "narration": s.get("narration", ""),
                "stock_query": s.get("stock_query", ""),
            }
            for s in job.get("scenes", [])
        ],
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_file_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def record_event(
    episode_id: str,
    event_type: str,
    payload: dict[str, Any],
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO events (episode_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (episode_id, event_type, json.dumps(payload, ensure_ascii=False), utc_now_iso()),
        )


def acquire_job_lease(
    episode_id: str,
    stage: str,
    owner: str,
    ttl_seconds: int = 900,
    input_hash: str | None = None,
    db_path: Path | None = None,
) -> bool:
    """Atomically acquire or renew an exclusive lease for an episode job."""
    init_db(db_path)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    until_iso = (now + timedelta(seconds=ttl_seconds)).isoformat()
    job_id = f"{episode_id}:{stage}"

    with get_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT lease_owner, lease_until, attempt FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()

        if row is None:
            conn.execute(
                """
                INSERT INTO jobs (job_id, episode_id, stage, input_hash, attempt, lease_owner, lease_until, heartbeat_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (job_id, episode_id, stage, input_hash, owner, until_iso, now_iso, now_iso),
            )
            conn.execute("COMMIT")
            return True

        existing_owner = row["lease_owner"]
        existing_until = row["lease_until"]
        lease_active = False
        if existing_owner and existing_owner != owner and existing_until:
            try:
                lease_active = datetime.fromisoformat(existing_until) > now
            except ValueError:
                lease_active = False

        if lease_active:
            conn.execute("ROLLBACK")
            return False

        conn.execute(
            """
            UPDATE jobs
            SET input_hash = COALESCE(?, input_hash),
                attempt = attempt + 1,
                lease_owner = ?,
                lease_until = ?,
                heartbeat_at = ?,
                updated_at = ?
            WHERE job_id = ?
            """,
            (input_hash, owner, until_iso, now_iso, now_iso, job_id),
        )
        conn.execute("COMMIT")
        return True


def release_job_lease(
    episode_id: str,
    stage: str,
    owner: str,
    last_error: str | None = None,
    retry_at: str | None = None,
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    job_id = f"{episode_id}:{stage}"
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET lease_owner = NULL,
                lease_until = NULL,
                last_error = ?,
                retry_at = ?,
                updated_at = ?
            WHERE job_id = ? AND (lease_owner = ? OR lease_owner IS NULL)
            """,
            (last_error, retry_at, utc_now_iso(), job_id, owner),
        )


def record_qc_result(
    episode_id: str,
    revision: int,
    render_hash: str | None,
    score: int,
    decision: str,
    reasons: list[str],
    policy_version: str = "2026-11-26.v1",
    reviewer: str = "qc_gate_v1",
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    now_iso = utc_now_iso()
    with get_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO qc_results (episode_id, revision, render_hash, score, decision, reasons_json, policy_version, reviewer, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode_id,
                revision,
                render_hash,
                score,
                decision,
                json.dumps(reasons, ensure_ascii=False),
                policy_version,
                reviewer,
                now_iso,
            ),
        )
        conn.execute(
            """
            UPDATE episodes
            SET qc_score = ?, qc_status = ?, render_hash = COALESCE(?, render_hash), updated_at = ?
            WHERE episode_id = ?
            """,
            (score, decision, render_hash, now_iso, episode_id),
        )
        conn.execute("COMMIT")


def upsert_publication_intent(
    channel_id: str,
    episode_id: str,
    revision: int,
    idempotency_key: str,
    desired_privacy: str,
    publish_at_utc: str | None,
    status: str = "UPLOADING",
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    now_iso = utc_now_iso()
    with get_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO publications (
                channel_id, episode_id, revision, idempotency_key,
                desired_privacy, publish_at_utc, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id, episode_id) DO UPDATE SET
                revision = excluded.revision,
                idempotency_key = excluded.idempotency_key,
                desired_privacy = excluded.desired_privacy,
                publish_at_utc = COALESCE(excluded.publish_at_utc, publications.publish_at_utc),
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (channel_id, episode_id, revision, idempotency_key, desired_privacy, publish_at_utc, status, now_iso),
        )
        conn.execute("COMMIT")


def finalize_publication(
    channel_id: str,
    episode_id: str,
    video_id: str,
    actual_privacy: str,
    status: str,
    uploaded_at: str | None = None,
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    now_iso = utc_now_iso()
    with get_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE publications
            SET video_id = ?, actual_privacy = ?, status = ?, uploaded_at = COALESCE(?, uploaded_at), updated_at = ?
            WHERE channel_id = ? AND episode_id = ?
            """,
            (video_id, actual_privacy, status, uploaded_at or now_iso, now_iso, channel_id, episode_id),
        )
        conn.execute(
            "UPDATE episodes SET state = ?, updated_at = ? WHERE episode_id = ?",
            (status, now_iso, episode_id),
        )
        conn.execute("COMMIT")


def migrate_from_jobs_dir(jobs_dir: Path | None = None, db_path: Path | None = None) -> int:
    """Import existing jobs/*/job.json and upload_receipt.json into SQLite idempotently."""
    init_db(db_path)
    target_jobs = jobs_dir or (REPO_ROOT / "jobs")
    policy_path = REPO_ROOT / "config" / "channel_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    lock = policy.get("account_lock", {})
    channel_id = str(lock.get("channel_id", "UCVEH1Fr34ceSw4FY27i656A"))

    now_iso = utc_now_iso()
    imported = 0

    with get_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO channels (channel_id, handle, expected_email, mission_version, config_json, updated_at)
            VALUES (?, '@dufkon', ?, '2026-11-26.v1', ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                config_json = excluded.config_json,
                updated_at = excluded.updated_at
            """,
            (
                channel_id,
                str(lock.get("expected_email", "dufkonltd@gmail.com")),
                json.dumps(policy, ensure_ascii=False),
                now_iso,
            ),
        )

        for job_path in sorted(target_jobs.glob("*/job.json")):
            job_dir = job_path.parent
            episode_id = job_dir.name
            job = json.loads(job_path.read_text(encoding="utf-8"))
            script_hash = compute_script_hash(job)
            receipt_path = job_dir / "upload_receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}

            video_id = receipt.get("video_id")
            state = "SCHEDULED" if (video_id and receipt.get("publish_at")) else ("PUBLIC" if video_id else "SCRIPT")

            conn.execute(
                """
                INSERT INTO episodes (
                    episode_id, channel_id, series, title, topic, revision, state,
                    script_hash, contains_synthetic_media, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id) DO UPDATE SET
                    title = excluded.title,
                    script_hash = excluded.script_hash,
                    state = CASE WHEN episodes.state IN ('PUBLIC', 'SCHEDULED', 'DROPPED') THEN episodes.state ELSE excluded.state END,
                    updated_at = excluded.updated_at
                """,
                (
                    episode_id,
                    channel_id,
                    str(job.get("niche", "extreme_science")),
                    str(job.get("title", episode_id)),
                    str(job.get("title", episode_id)),
                    state,
                    script_hash,
                    1 if job.get("contains_synthetic_media", True) else 0,
                    now_iso,
                    now_iso,
                ),
            )

            for scene in job.get("scenes", []):
                conn.execute(
                    """
                    INSERT INTO scenes (
                        episode_id, revision, scene_index, speaker, narration,
                        flow_prompt, stock_query, source_citation
                    ) VALUES (?, 1, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(episode_id, revision, scene_index) DO UPDATE SET
                        narration = excluded.narration,
                        stock_query = excluded.stock_query
                    """,
                    (
                        episode_id,
                        int(scene.get("index", 1)),
                        str(scene.get("speaker", "host")),
                        str(scene.get("narration", "")),
                        str(scene.get("flow_prompt", "")),
                        str(scene.get("stock_query", "")),
                        str(scene.get("source_citation", "")),
                    ),
                )

            if video_id:
                conn.execute(
                    """
                    INSERT INTO publications (
                        channel_id, episode_id, revision, idempotency_key, video_id,
                        desired_privacy, actual_privacy, publish_at_utc, status, uploaded_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(channel_id, episode_id) DO UPDATE SET
                        video_id = COALESCE(publications.video_id, excluded.video_id),
                        publish_at_utc = COALESCE(publications.publish_at_utc, excluded.publish_at_utc),
                        updated_at = excluded.updated_at
                    """,
                    (
                        channel_id,
                        episode_id,
                        f"{channel_id}:{episode_id}:rev1",
                        video_id,
                        str(receipt.get("privacy_status", "private")),
                        str(receipt.get("privacy_status", "private")),
                        receipt.get("publish_at"),
                        state,
                        receipt.get("uploaded_at"),
                        now_iso,
                    ),
                )
            imported += 1

        conn.execute("COMMIT")
    return imported


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize or migrate Dufkon Shorts SQLite WAL database.")
    parser.add_argument("--init", action="store_true", help="Initialize database schema")
    parser.add_argument("--migrate", action="store_true", help="Migrate existing jobs/* into SQLite")
    parser.add_argument("--db", type=Path, default=None, help="Optional SQLite DB path")
    args = parser.parse_args()

    if args.init or not args.migrate:
        p = init_db(args.db)
        print(f"Initialized SQLite WAL DB: {p}")
    if args.migrate:
        count = migrate_from_jobs_dir(db_path=args.db)
        print(f"Migrated {count} episode(s) into SQLite WAL DB.")


if __name__ == "__main__":
    main()
