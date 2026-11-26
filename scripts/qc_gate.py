"""Independent 100-point Critic QC Gate for Dufkon YouTube Shorts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from db import compute_file_sha256, compute_script_hash, record_qc_result  # noqa: E402
from prep_video import probe_video  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent

DEFAULT_BANNED_PHRASES = [
    "in less than three seconds, the cascading pressure and thermal shift",
    "the scientific physics behind this are far more devastating",
    "fundamental molecular equilibrium breaks down",
    "could human technology ever prevent an event like this",
    "in today's video",
    "have you ever wondered",
    "buckle up",
    "let's dive in",
    "without further ado",
    "in this modern world",
    "mind-blowing journey",
    "perfect solution",
]


def _load_banned_phrases() -> list[str]:
    phrases = list(DEFAULT_BANNED_PHRASES)
    for rel in (
        "agent_brain/1_knowledge/persona_profile.yaml",
        "agent_brain/4_learned_rules/do_not_repeat.yaml",
    ):
        p = REPO_ROOT / rel
        if not p.exists():
            continue
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for key in ("banned_phrases", "blocked_fallback_signatures"):
                for item in data.get(key, []) or []:
                    s = str(item).strip().lower()
                    if s and s not in phrases:
                        phrases.append(s)
        except Exception:
            for line in p.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("- "):
                    val = stripped[2:].strip().strip('"').strip("'").lower()
                    if val and val not in phrases and " " in val:
                        phrases.append(val)
    return phrases


def _topic_alignment_ok(job_id: str, job: dict[str, Any]) -> tuple[bool, str]:
    """Catch severe topic/script mismatches (e.g. batch_15 sun-becomes-black-hole)."""
    title = str(job.get("title", "")).lower()
    narr = " ".join(str(s.get("narration", "")) for s in job.get("scenes", [])).lower()

    if "sun_becomes_black_hole" in job_id and "fall into a black hole" in title:
        return False, "Topic/script mismatch: job_id is sun_becomes_black_hole but title/script is 'Fall Into a Black Hole'."
    if "sun" in job_id and "sun" not in title and "sun" not in narr:
        return False, f"Topic/script mismatch: '{job_id}' does not mention 'sun' in title or narration."
    return True, ""


def _find_duplicate_narration(job_id: str, job: dict[str, Any], jobs_dir: Path) -> str | None:
    scenes = [str(s.get("narration", "")).strip().lower() for s in job.get("scenes", []) if s.get("narration")]
    if len(scenes) < 2:
        return None
    body_set = set(scenes[1:])
    for other_path in sorted(jobs_dir.glob("*/job.json")):
        if other_path.parent.name == job_id:
            continue
        try:
            other = json.loads(other_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        other_scenes = {
            str(s.get("narration", "")).strip().lower()
            for s in other.get("scenes", [])
            if s.get("narration")
        }
        overlap = body_set & other_scenes
        if len(overlap) >= 2:
            return other_path.parent.name
    return None


def evaluate_job_spec(
    job_dir: Path,
    video_path: Path | None = None,
    check_duplicates: bool = True,
) -> dict[str, Any]:
    """Score an episode 0-100 across 5 rubric dimensions and return PASS / REWORK / DROP."""
    job_path = job_dir / "job.json"
    if not job_path.exists():
        return {
            "decision": "DROP",
            "score": 0,
            "reasons": ["Missing job.json"],
            "script_hash": "",
            "render_hash": None,
            "fallback_detected": False,
        }

    job = json.loads(job_path.read_text(encoding="utf-8"))
    job_id = job_dir.name
    scenes = job.get("scenes", [])
    title = str(job.get("title", "")).strip()
    description = str(job.get("description", "")).strip()
    full_narr = " ".join(str(s.get("narration", "")) for s in scenes)
    full_narr_lower = full_narr.lower()
    word_count = len(full_narr.split())

    reasons: list[str] = []
    banned = _load_banned_phrases()
    matched_banned = [b for b in banned if b in full_narr_lower]
    fallback_detected = bool(matched_banned)

    # 1. Hook (25 pts)
    hook_score = 25
    if not scenes:
        hook_score = 0
        reasons.append("No scenes defined.")
    else:
        s1 = str(scenes[0].get("narration", "")).strip().lower()
        if len(s1.split()) < 5:
            hook_score -= 10
            reasons.append("Scene 1 hook is too short (<5 words).")
        if any(p in s1 for p in ("in today's video", "have you ever wondered", "let's dive in")):
            hook_score -= 15
            reasons.append("Scene 1 hook uses banned AI intro cliché.")

    # 2. Originality & No AI Slop / Fallback (25 pts)
    orig_score = 25
    if matched_banned:
        orig_score = 0
        reasons.append(f"Blocked fallback/banned phrase detected: '{matched_banned[0]}'")
    if check_duplicates:
        dup_id = _find_duplicate_narration(job_id, job, job_dir.parent)
        if dup_id:
            orig_score = min(orig_score, 5)
            reasons.append(f"Duplicate narration detected (>=2 scenes match '{dup_id}').")

    # 3. Scientific Specificity & Alignment (20 pts)
    sci_score = 20
    aligned, align_msg = _topic_alignment_ok(job_id, job)
    if not aligned:
        sci_score = 0
        reasons.append(align_msg)
    if len(scenes) < 4:
        sci_score = max(0, sci_score - 10)
        reasons.append(f"Too few scenes ({len(scenes)} < 4).")
    missing_queries = [s.get("index") for s in scenes if not str(s.get("stock_query", "")).strip()]
    if missing_queries:
        sci_score = max(0, sci_score - 5)
        reasons.append(f"Missing stock_query on scenes: {missing_queries}")

    # 4. Format & Persona (15 pts)
    fmt_score = 15
    if not title or len(title) > 75:
        fmt_score -= 5
        reasons.append(f"Title missing or too long ({len(title)} chars).")
    if "#shorts" not in f"{title} {description}".lower():
        fmt_score -= 3
        reasons.append("Missing #Shorts tag in title/description.")
    if word_count < 45 or word_count > 140:
        fmt_score -= 5
        reasons.append(f"Word count {word_count} outside target 45-140 range.")

    # 5. Compliance & Technical Media (15 pts)
    tech_score = 15
    render_hash: str | None = None
    manifest_path = job_dir / "media_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            unresolved = [
                a.get("scene_index")
                for a in manifest.get("assets", [])
                if not a.get("commercial_allowed", True)
            ]
            if unresolved:
                tech_score = 0
                reasons.append(f"Unresolved commercial rights on scenes: {unresolved}")
        except Exception:
            pass

    if video_path is not None:
        if not video_path.exists():
            tech_score = 0
            reasons.append(f"Rendered video missing: {video_path}")
        else:
            try:
                info = probe_video(video_path)
                if info.height < info.width:
                    tech_score = 0
                    reasons.append(f"Video is not vertical ({info.width}x{info.height}).")
                if info.duration > 60.5 or info.duration < 10.0:
                    tech_score = max(0, tech_score - 10)
                    reasons.append(f"Duration {info.duration:.2f}s outside 10-60s Shorts window.")
                render_hash = compute_file_sha256(video_path)
            except Exception as exc:
                tech_score = 0
                reasons.append(f"ffprobe failed: {exc}")

    total_score = max(0, min(100, hook_score + orig_score + sci_score + fmt_score + tech_score))

    if fallback_detected or not aligned or tech_score == 0:
        decision = "DROP" if fallback_detected else "REWORK"
    elif total_score >= 80:
        decision = "PASS"
    else:
        decision = "REWORK"

    return {
        "job_id": job_id,
        "decision": decision,
        "score": total_score,
        "reasons": reasons,
        "script_hash": compute_script_hash(job),
        "render_hash": render_hash,
        "fallback_detected": fallback_detected,
    }


def validate_job_for_publish(
    job_dir: Path,
    video_path: Path,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Hard gate called right before any YouTube upload. Raises ValueError if not PASS."""
    report = evaluate_job_spec(job_dir=job_dir, video_path=video_path, check_duplicates=True)
    report_path = job_dir / "qc_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        record_qc_result(
            episode_id=job_dir.name,
            revision=1,
            render_hash=report.get("render_hash"),
            score=int(report["score"]),
            decision=str(report["decision"]),
            reasons=list(report["reasons"]),
            db_path=db_path,
        )
    except Exception:
        pass

    if report["decision"] != "PASS":
        joined = "; ".join(report["reasons"]) or f"score={report['score']}"
        raise ValueError(f"QC_GATE_BLOCKED ({report['decision']}, score={report['score']}): {joined}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 100-point Critic QC Gate on Dufkon Shorts jobs.")
    parser.add_argument("--job", type=Path, help="Path to a specific job directory or job.json")
    parser.add_argument("--audit-all", action="store_true", help="Audit all jobs under jobs/")
    parser.add_argument("--db", type=Path, default=None, help="Optional SQLite DB path")
    args = parser.parse_args()

    if args.audit_all:
        jobs_dir = REPO_ROOT / "jobs"
        counts = {"PASS": 0, "REWORK": 0, "DROP": 0}
        for jp in sorted(jobs_dir.glob("*/job.json")):
            jdir = jp.parent
            mp4 = REPO_ROOT / "output" / f"{jdir.name}_shorts.mp4"
            res = evaluate_job_spec(jdir, video_path=mp4 if mp4.exists() else None)
            counts[res["decision"]] = counts.get(res["decision"], 0) + 1
            try:
                record_qc_result(
                    episode_id=jdir.name,
                    revision=1,
                    render_hash=res.get("render_hash"),
                    score=int(res["score"]),
                    decision=str(res["decision"]),
                    reasons=list(res["reasons"]),
                    db_path=args.db,
                )
            except Exception:
                pass
            summary_reason = res["reasons"][0] if res["reasons"] else "OK"
            print(f"{jdir.name:34} | {res['decision']:6} | {res['score']:3}/100 | {summary_reason}")
        print(f"\nSummary: PASS={counts['PASS']} | REWORK={counts['REWORK']} | DROP={counts['DROP']}")
        return

    if args.job:
        jdir = args.job.parent if args.job.name == "job.json" else args.job
        mp4 = REPO_ROOT / "output" / f"{jdir.name}_shorts.mp4"
        res = evaluate_job_spec(jdir, video_path=mp4 if mp4.exists() else None)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        if res["decision"] != "PASS":
            raise SystemExit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
