"""Batch-build ready Short jobs, immediately schedule newly produced Shorts, and sync YouTube ledger."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from assemble_short import assemble_short, resolve_scene_media  # noqa: E402
from generate_audio import build_audio_and_captions  # noqa: E402
from prep_video import probe_video  # noqa: E402
from upload_video import upload_from_job  # noqa: E402
from youtube_auth import get_authenticated_youtube_service, load_policy  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent
LEDGER_JSON_PATH = REPO_ROOT / "PRODUCTION_LEDGER.json"
SCHEDULE_MD_PATH = REPO_ROOT / "PRODUCTION_SCHEDULE.md"


def parse_tz_offset(offset_str: str) -> timezone:
    """Parse '+07:00' or '-05:00' into a datetime.timezone."""
    sign = -1 if offset_str.strip().startswith("-") else 1
    hh, mm = offset_str.strip().lstrip("+-").split(":")
    return timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))


def fetch_live_youtube_videos(max_results: int = 50) -> dict[str, dict[str, Any]]:
    """Query YouTube Data API v3 for live channel video statuses and statistics."""
    try:
        youtube, _ = get_authenticated_youtube_service(verify_lock=True)
        search_resp = youtube.search().list(
            part="id",
            forMine=True,
            type="video",
            order="date",
            maxResults=max_results,
        ).execute()
        video_ids = [
            item["id"]["videoId"]
            for item in search_resp.get("items", [])
            if item.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return {}
        videos_resp = youtube.videos().list(
            part="snippet,statistics,status,contentDetails",
            id=",".join(video_ids),
        ).execute()
        return {v["id"]: v for v in videos_resp.get("items", [])}
    except Exception as exc:
        print(f"[Warn] Could not fetch live YouTube videos list: {exc}")
        return {}


def collect_taken_slots(jobs_dir: Path, include_live_youtube: bool = True) -> set[int]:
    """Collect epoch-minute timestamps already booked by local receipts and live YouTube API."""
    taken: set[int] = set()
    now_utc = datetime.now(timezone.utc)
    for receipt_path in jobs_dir.glob("*/upload_receipt.json"):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if receipt.get("published_immediately"):
            continue
        pub_raw = receipt.get("publish_at")
        if not pub_raw:
            continue
        try:
            dt = datetime.fromisoformat(str(pub_raw).replace("Z", "+00:00")).astimezone(timezone.utc)
            if dt > now_utc:
                taken.add(int(dt.timestamp()) // 60)
        except ValueError:
            continue

    if include_live_youtube:
        live_videos = fetch_live_youtube_videos()
        for v in live_videos.values():
            pub_raw = v.get("status", {}).get("publishAt")
            if not pub_raw:
                continue
            try:
                dt = datetime.fromisoformat(str(pub_raw).replace("Z", "+00:00")).astimezone(timezone.utc)
                if dt > now_utc:
                    taken.add(int(dt.timestamp()) // 60)
            except ValueError:
                continue

    return taken


def generate_publish_slots(
    count: int,
    daily_slots: list[str],
    tz_offset: str,
    min_hours_ahead: int = 2,
    start_date: str | None = None,
    taken_slots: set[int] | None = None,
) -> list[str]:
    """Generate sorted ISO 8601 publishAt timestamps for upcoming unbooked daily slots."""
    tz = parse_tz_offset(tz_offset)
    now = datetime.now(tz)
    earliest = now + timedelta(hours=min_hours_ahead)
    base_day = (
        datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz)
        if start_date
        else now.replace(hour=0, minute=0, second=0, microsecond=0)
    )
    booked = set(taken_slots) if taken_slots else set()

    slots: list[str] = []
    day_offset = 0
    while len(slots) < count:
        day = base_day + timedelta(days=day_offset)
        for hm in sorted(daily_slots):
            hh, mm = hm.split(":")
            candidate = day.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            cand_min = int(candidate.astimezone(timezone.utc).timestamp()) // 60
            if candidate >= earliest and cand_min not in booked:
                slots.append(candidate.isoformat())
                booked.add(cand_min)
                if len(slots) >= count:
                    break
        day_offset += 1
    return slots


def is_job_media_ready(job_dir: Path, job: dict[str, Any]) -> bool:
    """Return True if every scene in job.json has a resolved video or image file."""
    for scene in job.get("scenes", []):
        if resolve_scene_media(job_dir, str(scene["clip_file"])) is None:
            return False
    return True


def sync_production_ledger() -> dict[str, Any]:
    """Cross-verify all local jobs, output MP4s, upload receipts, and live YouTube API state."""
    policy = load_policy()
    tz_offset = str(policy.get("schedule_defaults", {}).get("timezone_offset", "+07:00"))
    tz = parse_tz_offset(tz_offset)
    now_local = datetime.now(tz)

    jobs_dir = REPO_ROOT / "jobs"
    output_dir = REPO_ROOT / "output"
    live_videos = fetch_live_youtube_videos()

    prev_metrics: dict[str, dict[str, Any]] = {}
    if LEDGER_JSON_PATH.exists():
        try:
            prev_ledger = json.loads(LEDGER_JSON_PATH.read_text(encoding="utf-8"))
            prev_metrics = {
                str(v["job_id"]): v
                for v in prev_ledger.get("videos", [])
                if v.get("job_id")
            }
        except Exception:
            prev_metrics = {}

    records: list[dict[str, Any]] = []
    unscheduled_orphans: list[str] = []
    future_scheduled_count = 0

    for job_path in sorted(jobs_dir.glob("*/job.json")):
        job_dir = job_path.parent
        job_id = job_dir.name
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except Exception:
            job = {"id": job_id, "title": job_id}

        receipt_path = job_dir / "upload_receipt.json"
        receipt: dict[str, Any] = {}
        if receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except Exception:
                receipt = {}

        final_mp4 = output_dir / f"{job_id}_shorts.mp4"
        mp4_exists = final_mp4.exists()
        prev_rec = prev_metrics.get(job_id, {})
        mp4_size_mb = (
            round(final_mp4.stat().st_size / (1024 * 1024), 2)
            if mp4_exists
            else float(receipt.get("mp4_size_mb") or prev_rec.get("mp4_size_mb") or 0.0)
        )
        mp4_duration_s = float(receipt.get("mp4_duration_s") or prev_rec.get("mp4_duration_s") or 0.0)
        if mp4_exists:
            try:
                mp4_duration_s = round(probe_video(final_mp4).duration, 2)
            except Exception:
                pass
        mp4_rendered = mp4_exists or bool(receipt.get("video_id") and (mp4_size_mb > 0 or mp4_duration_s > 0))

        video_id = receipt.get("video_id")
        live_info = live_videos.get(video_id, {}) if video_id else {}
        live_status = live_info.get("status", {})
        live_stats = live_info.get("statistics", {})

        privacy_status = live_status.get("privacyStatus") or receipt.get("privacy_status") or (
            "private" if receipt.get("publish_at") else "unscheduled"
        )
        publish_at_raw = live_status.get("publishAt") or receipt.get("publish_at")
        publish_at_local_str = None
        is_future_scheduled = False

        if publish_at_raw:
            try:
                dt_local = datetime.fromisoformat(str(publish_at_raw).replace("Z", "+00:00")).astimezone(tz)
                publish_at_local_str = dt_local.isoformat()
                if dt_local > now_local:
                    is_future_scheduled = True
                    future_scheduled_count += 1
            except ValueError:
                publish_at_local_str = str(publish_at_raw)

        if not video_id:
            unscheduled_orphans.append(job_id)
            state_label = "ORPHAN_UNSCHEDULED"
        elif privacy_status == "public":
            state_label = "PUBLIC_LIVE"
        elif is_future_scheduled:
            state_label = "SCHEDULED_ON_YOUTUBE"
        else:
            state_label = privacy_status.upper()

        records.append(
            {
                "job_id": job_id,
                "title": job.get("title", ""),
                "mp4_rendered": mp4_rendered,
                "mp4_path": str(final_mp4) if mp4_exists else None,
                "mp4_size_mb": mp4_size_mb,
                "mp4_duration_s": mp4_duration_s,
                "video_id": video_id,
                "youtube_url": f"https://www.youtube.com/shorts/{video_id}" if video_id else None,
                "state": state_label,
                "privacy_status": privacy_status,
                "publish_at_local": publish_at_local_str,
                "uploaded_at": receipt.get("uploaded_at"),
                "views": int(live_stats.get("viewCount", 0)) if live_stats else 0,
                "likes": int(live_stats.get("likeCount", 0)) if live_stats else 0,
                "comments": int(live_stats.get("commentCount", 0)) if live_stats else 0,
            }
        )

    # Sort chronologically: public first by upload time, then scheduled by publish_at_local, then unscheduled
    records.sort(
        key=lambda r: (
            0 if r["state"] == "PUBLIC_LIVE" else (1 if r["state"] == "SCHEDULED_ON_YOUTUBE" else 2),
            r.get("publish_at_local") or r.get("uploaded_at") or "",
            r["job_id"],
        )
    )

    daily_slots = sorted(list(policy.get("schedule_defaults", {}).get("daily_slots", ["19:00"])))
    slots_per_day = max(1, len(daily_slots))
    buffer_days_equiv = round(future_scheduled_count / slots_per_day, 1)

    ledger = {
        "updated_at": now_local.isoformat(),
        "channel_id": policy.get("account_lock", {}).get("channel_id"),
        "channel_title": policy.get("account_lock", {}).get("channel_title"),
        "daily_slots": daily_slots,
        "timezone_offset": tz_offset,
        "total_jobs": len(records),
        "total_rendered_mp4": sum(1 for r in records if r["mp4_rendered"]),
        "total_uploaded_to_youtube": sum(1 for r in records if r["video_id"]),
        "public_live_count": sum(1 for r in records if r["state"] == "PUBLIC_LIVE"),
        "future_scheduled_slots": future_scheduled_count,
        "future_scheduled_buffer_days": buffer_days_equiv,
        "unscheduled_orphan_jobs": unscheduled_orphans,
        "videos": records,
    }
    LEDGER_JSON_PATH.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines = [
        f"# BẢNG ĐỐI CHIẾU SẢN XUẤT & LỊCH ĐĂNG YOUTUBE SHORTS ({ledger['channel_title']})",
        "",
        f"- **Cập nhật lần cuối:** `{ledger['updated_at']}`",
        f"- **Kênh YouTube:** `{ledger['channel_title']}` (`{ledger['channel_id']}`)",
        f"- **Khung giờ đăng cố định:** `{', '.join(ledger['daily_slots'])}` hàng ngày (`{slots_per_day} video/ngày`, Múi giờ `{tz_offset}`)",
        f"- **Tổng số Job đã tạo:** `{ledger['total_jobs']}` | **Đã Render MP4:** `{ledger['total_rendered_mp4']}` | **Đã Upload & Lên lịch:** `{ledger['total_uploaded_to_youtube']}`",
        f"- **Số video đã Công khai (Public):** `{ledger['public_live_count']}` | **Quỹ dự trữ đã hẹn giờ:** `{future_scheduled_count} video ({buffer_days_equiv} ngày)`",
        f"- **Số video bỏ sót chưa lên lịch (Orphans):** `{len(unscheduled_orphans)}` ({', '.join(unscheduled_orphans) if unscheduled_orphans else 'Không có - 0% bỏ sót'})",
        "",
        "| STT | Mã Job (`job_id`) | Video ID | Trạng thái YouTube | Lịch phát sóng (`+07:00`) | Thời lượng / Size | Views / Likes | Tiêu đề |",
        "| :-: | :--- | :--- | :--- | :--- | :---: | :---: | :--- |",
    ]
    for idx, rec in enumerate(records, start=1):
        vid = f"[`{rec['video_id']}`]({rec['youtube_url']})" if rec["video_id"] else "❌ Chưa upload"
        sched_str = rec["publish_at_local"] or (rec["uploaded_at"][:19] + " (Đăng ngay)" if rec["uploaded_at"] else "Chưa hẹn giờ")
        dur_size = f"{rec['mp4_duration_s']}s / {rec['mp4_size_mb']} MB" if rec["mp4_rendered"] else "Chưa render"
        metrics = f"{rec['views']} views / {rec['likes']} likes"
        md_lines.append(
            f"| {idx} | `{rec['job_id']}` | {vid} | **{rec['state']}** | `{sched_str}` | {dur_size} | {metrics} | {rec['title']} |"
        )

    SCHEDULE_MD_PATH.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return ledger


def schedule_and_upload_immediately(
    job_path: Path,
    final_mp4: Path | None = None,
    publish_at: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """Immediately upload a newly produced Short to YouTube with the next available publishAt slot."""
    job_path = job_path.resolve()
    job_dir = job_path.parent
    receipt_path = job_dir / "upload_receipt.json"

    if receipt_path.exists() and not dry_run:
        try:
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
            if existing.get("video_id"):
                print(
                    f"[Auto-Schedule] {job_dir.name} already scheduled on YouTube "
                    f"(video_id={existing['video_id']}, publish_at={existing.get('publish_at')})."
                )
                return existing
        except Exception:
            pass

    job = json.loads(job_path.read_text(encoding="utf-8"))
    job_id = str(job.get("id", job_dir.name))
    video_file = final_mp4 or (REPO_ROOT / "output" / f"{job_id}_shorts.mp4")
    if not video_file.exists():
        raise FileNotFoundError(f"Cannot schedule {job_id}: rendered video missing at {video_file}")

    policy = load_policy()
    sched = policy.get("schedule_defaults", {})
    daily_slots = list(sched.get("daily_slots", ["19:00"]))
    tz_offset = str(sched.get("timezone_offset", "+07:00"))
    min_hours = int(sched.get("min_hours_ahead", 2))

    if not publish_at:
        taken_slots = collect_taken_slots(REPO_ROOT / "jobs", include_live_youtube=True)
        publish_at = generate_publish_slots(
            count=1,
            daily_slots=daily_slots,
            tz_offset=tz_offset,
            min_hours_ahead=min_hours,
            taken_slots=taken_slots,
        )[0]

    upload_payload = {
        "mode": "shorts",
        "video_path": str(video_file),
        "title": job["title"],
        "description": job.get("description", ""),
        "tags": job.get("tags", []),
        "language": job.get("language", "en"),
        "category_id": job.get("category_id", "28"),
        "privacy_status": "private",
        "publish_at": publish_at,
        "contains_synthetic_media": bool(job.get("contains_synthetic_media", True)),
    }

    print(f"🚀 [Immediate Auto-Schedule] Uploading {job_id} -> YouTube publishAt={publish_at}")
    video_id = upload_from_job(upload_payload, dry_run=dry_run)
    if dry_run:
        return {"job_id": job_id, "video_id": "dry_run_id", "publish_at": publish_at}

    if video_id:
        mp4_size_mb = round(video_file.stat().st_size / (1024 * 1024), 2) if video_file.exists() else 0.0
        try:
            mp4_duration_s = round(probe_video(video_file).duration, 2)
        except Exception:
            mp4_duration_s = 0.0
        receipt = {
            "job_id": job_id,
            "video_id": video_id,
            "title": job["title"],
            "video_path": str(video_file),
            "mp4_size_mb": mp4_size_mb,
            "mp4_duration_s": mp4_duration_s,
            "publish_at": publish_at,
            "privacy_status": "private",
            "uploaded_at": datetime.now(parse_tz_offset(tz_offset)).isoformat(),
        }
        receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
        sync_production_ledger()
        print(f"✅ [Immediate Auto-Schedule] Locked {job_id} -> Video ID: {video_id} @ {publish_at}")
        return receipt

    return None


def run_batch(
    dry_run: bool = False,
    bgm_path: Path | None = None,
    start_date: str | None = None,
    limit: int | None = None,
) -> None:
    """Find ready un-uploaded jobs, build Shorts if needed, and immediately schedule each upon completion."""
    policy = load_policy()
    sched = policy.get("schedule_defaults", {})
    limits = policy.get("rate_limits", {})

    max_per_run = int(limit if limit is not None else limits.get("max_uploads_per_run", 5))
    min_delay = int(limits.get("min_delay_seconds_between_uploads", 120))
    daily_slots = list(sched.get("daily_slots", ["19:00"]))
    tz_offset = str(sched.get("timezone_offset", "+07:00"))
    min_hours = int(sched.get("min_hours_ahead", 2))

    jobs_dir = REPO_ROOT / "jobs"
    candidates: list[Path] = []
    for job_path in sorted(jobs_dir.glob("*/job.json")):
        job_dir = job_path.parent
        receipt_path = job_dir / "upload_receipt.json"
        if receipt_path.exists():
            try:
                if json.loads(receipt_path.read_text(encoding="utf-8")).get("video_id"):
                    continue
            except Exception:
                pass
        job = json.loads(job_path.read_text(encoding="utf-8"))
        final_mp4 = REPO_ROOT / "output" / f"{job.get('id', job_dir.name)}_shorts.mp4"
        if final_mp4.exists() or is_job_media_ready(job_dir, job):
            candidates.append(job_path)
        else:
            print(f"[Skip] {job_dir.name}: waiting for missing clips.")

    candidates = candidates[:max_per_run]
    if not candidates:
        print("No ready un-uploaded jobs found.")
        sync_production_ledger()
        return

    taken_slots = collect_taken_slots(jobs_dir, include_live_youtube=True)
    slots = generate_publish_slots(
        len(candidates),
        daily_slots=daily_slots,
        tz_offset=tz_offset,
        min_hours_ahead=min_hours,
        start_date=start_date,
        taken_slots=taken_slots,
    )

    for idx, (job_path, publish_at) in enumerate(zip(candidates, slots)):
        job = json.loads(job_path.read_text(encoding="utf-8"))
        job_id = str(job.get("id", job_path.parent.name))
        final_mp4 = REPO_ROOT / "output" / f"{job_id}_shorts.mp4"

        if not final_mp4.exists():
            asyncio.run(build_audio_and_captions(job_path))
            final_mp4 = assemble_short(job_path, bgm_path=bgm_path)

        print(f"\n[{idx + 1}/{len(candidates)}] {job_id} -> publishAt={publish_at}")
        receipt = schedule_and_upload_immediately(
            job_path=job_path,
            final_mp4=final_mp4,
            publish_at=publish_at,
            dry_run=dry_run,
        )
        if receipt and not dry_run and idx + 1 < len(candidates):
            print(f"Waiting {min_delay}s per rate_limits...")
            time.sleep(min_delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ready jobs, schedule Shorts uploads, and sync ledger.")
    parser.add_argument("--dry-run", action="store_true", help="Build & print scheduled payloads without uploading")
    parser.add_argument("--sync-only", action="store_true", help="Only sync PRODUCTION_LEDGER.json and PRODUCTION_SCHEDULE.md with YouTube API")
    parser.add_argument("--bgm", type=Path, default=None, help="Optional background music track")
    parser.add_argument("--start-date", type=str, default=None, help="Optional YYYY-MM-DD start date")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs in this batch")
    args = parser.parse_args()

    if args.sync_only:
        ledger = sync_production_ledger()
        print(
            f"✅ Synced ledger: {ledger['total_uploaded_to_youtube']}/{ledger['total_jobs']} jobs on YouTube | "
            f"Future Buffer: {ledger['future_scheduled_buffer_days']} days | "
            f"Orphans: {len(ledger['unscheduled_orphan_jobs'])}"
        )
        return

    run_batch(
        dry_run=args.dry_run,
        bgm_path=args.bgm.resolve() if args.bgm else None,
        start_date=args.start_date,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()

