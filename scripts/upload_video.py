"""Resumable YouTube upload automation for Shorts and standard Videos (single-channel locked)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from prep_video import probe_video, validate_thumbnail  # noqa: E402
from qc_gate import validate_job_for_publish  # noqa: E402
from youtube_auth import get_authenticated_youtube_service, load_policy  # noqa: E402

RETRIABLE_STATUS_CODES = {500, 502, 503, 504}


def build_request_body(job: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Build YouTube videos.insert metadata payload from job and channel policy."""
    defaults = policy.get("upload_defaults", {})
    mode = job.get("mode", "video")
    title = str(job["title"]).strip()
    description = str(job.get("description", "")).strip()

    if mode == "shorts" and "#shorts" not in f"{title} {description}".lower():
        description = f"{description}\n\n#Shorts".strip()

    publish_at = job.get("publish_at")
    privacy = "private" if publish_at else job.get("privacy_status", defaults.get("default_privacy_status", "private"))

    status_block: dict[str, Any] = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": bool(job.get("made_for_kids", defaults.get("made_for_kids", False))),
        "containsSyntheticMedia": bool(
            job.get("contains_synthetic_media", defaults.get("contains_synthetic_media", False))
        ),
    }
    if publish_at:
        status_block["publishAt"] = publish_at

    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": list(job.get("tags", [])),
            "categoryId": str(job.get("category_id", defaults.get("default_category_id", "22"))),
            "defaultLanguage": str(job.get("language", defaults.get("default_language", "vi"))),
        },
        "status": status_block,
    }


def validate_media_for_mode(video_path: Path, mode: str, policy: dict[str, Any]) -> None:
    """Ensure local video satisfies technical constraints before calling YouTube API."""
    info = probe_video(video_path)
    if mode == "shorts":
        if info.height < info.width:
            raise ValueError(
                f"Shorts must be vertical or square (got {info.width}x{info.height}). "
                "Run prep_video.py --mode shorts first."
            )
        max_sec = float(policy.get("upload_defaults", {}).get("shorts_max_duration_seconds", 60))
        if info.duration > max_sec + 0.5:
            raise ValueError(
                f"Shorts duration {info.duration:.2f}s exceeds configured limit {max_sec:.0f}s."
            )


def execute_resumable_upload(request: Any, max_retries: int = 5) -> dict[str, Any]:
    """Execute a resumable Google API upload with exponential backoff on 5xx errors."""
    response = None
    retry = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"Upload progress: {int(status.progress() * 100)}%")
        except HttpError as err:
            if err.resp.status in RETRIABLE_STATUS_CODES and retry < max_retries:
                retry += 1
                sleep_seconds = 2 ** retry
                print(f"Transient HTTP {err.resp.status}, retrying in {sleep_seconds}s...")
                time.sleep(sleep_seconds)
            else:
                raise
    return response


def upload_from_job(job: dict[str, Any], dry_run: bool = False) -> str | None:
    """Validate and upload a video or Short defined by a job dictionary."""
    policy = load_policy()
    video_path = Path(job["video_path"])
    mode = job.get("mode", "video")
    thumbnail_path = Path(job["thumbnail_path"]) if job.get("thumbnail_path") else None

    validate_media_for_mode(video_path, mode=mode, policy=policy)
    if thumbnail_path:
        validate_thumbnail(thumbnail_path)

    job_dir_raw = job.get("job_dir")
    if job_dir_raw:
        validate_job_for_publish(Path(job_dir_raw), video_path)
    elif mode == "shorts":
        inferred_job_dir = REPO_ROOT / "jobs" / video_path.stem.removesuffix("_shorts")
        if (inferred_job_dir / "job.json").exists():
            validate_job_for_publish(inferred_job_dir, video_path)

    body = build_request_body(job, policy)

    if dry_run:
        print("DRY RUN OK. Payload:")
        print(json.dumps(body, indent=2, ensure_ascii=False))
        return None

    youtube, channel = get_authenticated_youtube_service(verify_lock=True)
    print(f"Authenticated channel: {channel['snippet']['title']} ({channel['id']})")

    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True)
    insert_req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    result = execute_resumable_upload(insert_req)
    video_id = result["id"]
    print(f"Uploaded successfully: https://www.youtube.com/watch?v={video_id}")

    if thumbnail_path and mode != "shorts":
        thumb_media = MediaFileUpload(str(thumbnail_path))
        youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
        print(f"Custom thumbnail attached for video {video_id}")

    return video_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload YouTube Shorts or Videos safely.")
    parser.add_argument("--job", type=Path, help="Path to JSON upload job file")
    parser.add_argument("--video", type=Path, help="Path to video MP4 file")
    parser.add_argument("--mode", choices=["shorts", "video"], default="shorts")
    parser.add_argument("--title", type=str, help="Video title (max 100 chars)")
    parser.add_argument("--description", type=str, default="", help="Video description")
    parser.add_argument("--tags", type=str, default="", help="Comma-separated tags")
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    parser.add_argument("--publish-at", type=str, default=None, help="ISO 8601 publish time (forces private)")
    parser.add_argument("--thumbnail", type=Path, default=None, help="Thumbnail image path (for standard videos)")
    parser.add_argument("--synthetic-media", action="store_true", help="Mark AI-generated/altered media disclosure")
    parser.add_argument("--dry-run", action="store_true", help="Validate files and print payload without uploading")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.job:
        with args.job.open("r", encoding="utf-8") as f:
            job = json.load(f)
    else:
        if not args.video or not args.title:
            raise SystemExit("Provide either --job <file.json> or both --video and --title.")
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        job = {
            "mode": args.mode,
            "video_path": str(args.video),
            "title": args.title,
            "description": args.description,
            "tags": tags,
            "privacy_status": args.privacy,
            "publish_at": args.publish_at,
            "thumbnail_path": str(args.thumbnail) if args.thumbnail else None,
            "contains_synthetic_media": args.synthetic_media,
        }

    upload_from_job(job, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
