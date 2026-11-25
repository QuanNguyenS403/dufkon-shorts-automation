"""End-to-end YouTube Shorts pipeline runner (audio -> assemble -> immediate YouTube schedule)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from assemble_short import assemble_short  # noqa: E402
from fetch_media import fetch_missing_media  # noqa: E402
from generate_audio import build_audio_and_captions  # noqa: E402
from schedule_batch import schedule_and_upload_immediately  # noqa: E402


def print_flow_prompts(job_path: Path) -> None:
    """Print copy-ready Google Flow 9:16 prompts and exact target clip filenames."""
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job_dir = job_path.parent
    print(f"\n=== GOOGLE FLOW PROMPTS ({job.get('id', job_dir.name)}) ===")
    print("Settings in Google Flow: Aspect Ratio = 9:16 (Portrait)\n")
    for scene in job.get("scenes", []):
        idx = scene["index"]
        target = job_dir / scene["clip_file"]
        print(f"[Scene {idx}] Save to: {target}")
        print(f"Narration: {scene['narration']}")
        print(f"Prompt   : {scene['flow_prompt']}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YouTube Shorts automation pipeline for a job.")
    parser.add_argument("--job", type=Path, required=True, help="Path to job.json")
    parser.add_argument(
        "--stage",
        choices=["prompts", "audio", "assemble", "upload", "all"],
        default="all",
        help="Pipeline stage to run",
    )
    parser.add_argument("--bgm", type=Path, default=None, help="Optional background music file")
    parser.add_argument(
        "--presenter-layout",
        choices=["random", "fullscreen", "hybrid", "split"],
        default=None,
        help="Presenter layout mode override (random, fullscreen, hybrid, split)",
    )
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    parser.add_argument("--publish-at", type=str, default=None, help="ISO 8601 publish time (auto-picked if omitted)")
    parser.add_argument(
        "--no-auto-schedule",
        action="store_true",
        help="Skip automatic YouTube upload & scheduling right after assembly",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate upload payload without uploading")
    args = parser.parse_args()

    job_path = args.job.resolve()
    job_dir = job_path.parent
    job = json.loads(job_path.read_text(encoding="utf-8"))
    repo_root = SCRIPTS_DIR.parent

    if args.stage == "prompts":
        print_flow_prompts(job_path)
        return

    if args.stage in ("audio", "all"):
        manifest = asyncio.run(build_audio_and_captions(job_path, layout_override=args.presenter_layout))
        print(f"[1/3] Audio & captions OK ({manifest['total_duration']:.2f}s, layout={manifest.get('presenter_layout')})")

    if args.stage in ("assemble", "all"):
        fetch_missing_media(job_path, source="auto", overwrite=False)
        final_mp4 = assemble_short(
            job_path,
            bgm_path=args.bgm.resolve() if args.bgm else None,
            presenter_layout=args.presenter_layout,
        )
        print(f"[2/3] Assembly OK: {final_mp4}")
    else:
        final_mp4 = repo_root / "output" / f"{job.get('id', job_dir.name)}_shorts.mp4"

    # Immediately schedule on YouTube after assembly (unless explicitly disabled) so no produced Short is ever orphaned
    if args.stage in ("upload", "all") or (args.stage == "assemble" and not args.no_auto_schedule):
        receipt = schedule_and_upload_immediately(
            job_path=job_path,
            final_mp4=final_mp4,
            publish_at=args.publish_at,
            dry_run=args.dry_run,
        )
        if receipt and receipt.get("video_id"):
            print(f"[3/3] Scheduled Short ID: {receipt['video_id']} -> publishAt={receipt.get('publish_at')}")


if __name__ == "__main__":
    main()

