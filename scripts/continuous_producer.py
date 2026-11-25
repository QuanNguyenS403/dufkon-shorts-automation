"""Continuous YouTube Shorts production and scheduling daemon.

Maintains a rolling buffer of scheduled Shorts on the Dufkon channel.
Falls back seamlessly to public-domain NASA/Wikimedia archives, Edge-TTS voices,
and AI topic generation so production never stops.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

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
from fetch_media import fetch_missing_media  # noqa: E402
from generate_audio import build_audio_and_captions  # noqa: E402
from generate_job import generate_short_job, slugify  # noqa: E402
from schedule_batch import (  # noqa: E402
    collect_taken_slots,
    generate_publish_slots,
    parse_tz_offset,
    schedule_and_upload_immediately,
    sync_production_ledger,
)
from youtube_auth import load_policy  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent
JOBS_DIR = REPO_ROOT / "jobs"
OUTPUT_DIR = REPO_ROOT / "output"
DAEMON_LOG_PATH = REPO_ROOT / "producer_daemon.log"

load_dotenv(REPO_ROOT / ".env")


def log_daemon(msg: str) -> None:
    """Print message and append timestamped UTF-8 entry to producer_daemon.log."""
    print(msg, flush=True)
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with DAEMON_LOG_PATH.open("a", encoding="utf-8") as lf:
            lf.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

CURATED_TOPIC_QUEUE = [
    {
        "id": "batch_05_black_hole_fall",
        "topic": "What Happens If You Fall Into a Black Hole? (Spaghettification & Time Freeze)",
    },
    {
        "id": "batch_06_absolute_zero",
        "topic": "What Happens When Matter Reaches Absolute Zero? (Superfluids & Quantum Freezing)",
    },
    {
        "id": "batch_07_neutron_star",
        "topic": "What If A Teaspoon of Neutron Star Landed On Earth? (Massive Gravitational Impact)",
    },
    {
        "id": "batch_08_rogue_planet",
        "topic": "What If A Rogue Planet Entered Our Solar System? (Gravitational Catastrophe)",
    },
    {
        "id": "batch_09_lightning_strike",
        "topic": "What Actually Happens When Lightning Strikes An Airplane? (Faraday Shielding)",
    },
    {
        "id": "batch_10_magnetar_burst",
        "topic": "The Deadliest Star In The Universe: What A Magnetar Would Do To Earth",
    },
    {
        "id": "batch_11_oxygen_vanish",
        "topic": "What If All Oxygen Disappeared For Just 5 Seconds? (Concrete Collapse & Dark Sky)",
    },
    {
        "id": "batch_12_earth_core_cools",
        "topic": "What If The Earth's Core Suddenly Froze Solid? (Loss of Magnetic Shield)",
    },
    {
        "id": "batch_13_speed_of_light_needle",
        "topic": "What If A Sewing Needle Hit Earth At 99% The Speed Of Light? (Relativistic Impact)",
    },
    {
        "id": "batch_14_jupiter_swallows_earth",
        "topic": "What Would You See If You Fell Inside Jupiter's Atmosphere? (Metallic Hydrogen Ocean)",
    },
    {
        "id": "batch_15_sun_becomes_black_hole",
        "topic": "What If The Sun Instantly Turned Into A Black Hole Of The Same Mass?",
    },
    {
        "id": "batch_16_ocean_drains_mariana",
        "topic": "What If A 10-Meter Drain Opened At The Bottom Of The Mariana Trench?",
    },
    {
        "id": "batch_17_gamma_ray_burst",
        "topic": "What If A Gamma-Ray Burst Hit Earth From 1,000 Light-Years Away?",
    },
    {
        "id": "batch_18_gravity_doubles",
        "topic": "What If Earth's Gravity Suddenly Doubled Right Now? (Structural & Human Collapse)",
    },
    {
        "id": "batch_19_venus_terraforming",
        "topic": "What Happens To A Human Body On Venus Without A Spacesuit? (Crushed & Melted In 1 Second)",
    },
    {
        "id": "batch_20_false_vacuum_decay",
        "topic": "The Scariest Theory In Physics: What Is False Vacuum Decay? (Deleting Reality At Light Speed)",
    },
    {
        "id": "batch_21_supervolcano_yellowstone",
        "topic": "What If Yellowstone Supervolcano Erupted At Full Category 8 Power Today?",
    },
    {
        "id": "batch_22_time_stops_1_minute",
        "topic": "What Would Actually Happen According To Physics If Time Stopped For Everyone Except You?",
    },
    {
        "id": "batch_23_earth_rings_saturn",
        "topic": "What If Earth Had Giant Ice Rings Like Saturn? (Sky View & Meteor Storms)",
    },
    {
        "id": "batch_24_antimatter_gram",
        "topic": "What If Just One Gram Of Antimatter Touched The Ground In Your City?",
    },
    {
        "id": "batch_25_titan_methane_rain",
        "topic": "What Is It Like To Stand In A Liquid Methane Rainstorm On Saturn's Moon Titan?",
    },
]


def count_booked_future_days(tz_offset: str = "+07:00") -> tuple[int, datetime | None]:
    """Return (count of future booked slots, latest scheduled datetime)."""
    tz = parse_tz_offset(tz_offset)
    now = datetime.now(tz)
    booked_dts: list[datetime] = []

    for receipt_path in JOBS_DIR.glob("*/upload_receipt.json"):
        try:
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("published_immediately"):
            continue
        pub_raw = data.get("publish_at")
        if not pub_raw:
            continue
        try:
            dt = datetime.fromisoformat(str(pub_raw).replace("Z", "+00:00")).astimezone(tz)
            if dt > now:
                booked_dts.append(dt)
        except ValueError:
            continue

    if not booked_dts:
        return 0, None
    booked_dts.sort()
    return len(booked_dts), booked_dts[-1]


def has_valid_upload_receipt(job_dir: Path) -> bool:
    """Return True only if the job has been uploaded/scheduled and has a valid YouTube video_id."""
    receipt_path = job_dir / "upload_receipt.json"
    if not receipt_path.exists():
        return False
    try:
        data = json.loads(receipt_path.read_text(encoding="utf-8"))
        return bool(data.get("video_id"))
    except Exception:
        return False


def discover_next_topic() -> tuple[str, str]:
    """Find any unscheduled existing job first (zero orphan guarantee), then next curated or dynamic topic."""
    # 1. Zero-orphan priority: check if any existing job folder lacks a valid upload_receipt.json
    for job_path in sorted(JOBS_DIR.glob("*/job.json")):
        job_dir = job_path.parent
        if not has_valid_upload_receipt(job_dir):
            try:
                job_data = json.loads(job_path.read_text(encoding="utf-8"))
                topic_title = str(job_data.get("title") or job_dir.name)
            except Exception:
                topic_title = job_dir.name
            print(f"🔎 [Zero-Orphan Recovery] Found existing unscheduled job '{job_dir.name}'. Scheduling it first!")
            return job_dir.name, topic_title

    uploaded_job_ids = {p.name for p in JOBS_DIR.iterdir() if p.is_dir() and has_valid_upload_receipt(p)}

    for item in CURATED_TOPIC_QUEUE:
        if item["id"] not in uploaded_job_ids:
            return item["id"], item["topic"]

    # Fallback to dynamic Gemini generation if curated list is fully exhausted
    print("[Producer] Curated topics exhausted. Generating fresh viral topic...")
    topic_text = ""
    try:
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            client = genai.Client(api_key=api_key)
            resp = client.interactions.create(
                model="gemini-3.5-flash",
                input=(
                    "Suggest ONE mind-bending, viral scientific 'what-if' or extreme physics question for YouTube Shorts. "
                    "Output ONLY the question as a single plain text line, e.g. 'What if Earth had rings like Saturn?'"
                ),
            )
            topic_text = resp.output_text.strip().strip('"').strip("'")
    except Exception as exc:
        print(f"[Warn] Dynamic topic generation fallback: {exc}")

    if not topic_text:
        dynamic_pool = [
            "What If Earth Had Rings Like Saturn?",
            "What If You Traveled At 99% The Speed Of Light?",
            "What If A Hypernova Exploded Near Earth?",
            "What If The Mariana Trench Emptied Into The Earth's Mantle?",
            "What If The Sun Suddenly Doubled In Size?",
            "What If All Oceans Froze Solid Overnight?",
            "What If Humans Had Biological Sonar Like Bats?",
        ]
        topic_text = dynamic_pool[len(uploaded_job_ids) % len(dynamic_pool)]

    job_id = f"batch_{len(uploaded_job_ids) + 1:02d}_{slugify(topic_text)[:28]}"
    return job_id, topic_text


def cleanup_job_intermediates(job_dir: Path) -> None:
    """Remove temporary clips/ and build/ directories once a job is uploaded to YouTube."""
    if not has_valid_upload_receipt(job_dir):
        return
    for sub in ("clips", "build"):
        target = job_dir / sub
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def produce_and_schedule_single_job(
    job_id: str,
    topic: str,
    dry_run: bool = False,
    bgm_path: Path | None = None,
) -> str | None:
    """Execute end-to-end production for one Short job and immediately schedule it on YouTube."""
    job_dir = JOBS_DIR / job_id
    job_path = job_dir / "job.json"

    print(f"\n=======================================================")
    print(f"🎬 [PRODUCER] Starting Job: {job_id}")
    print(f"📖 Topic: {topic}")
    print(f"=======================================================")

    # 1. Generate or Load Job Spec
    if not job_path.exists():
        print("[Step 1/5] Generating job spec with Gemini Free Tier...")
        generate_short_job(topic=topic, job_id=job_id, language="en", niche="extreme_science")
    else:
        print("[Step 1/5] Existing job spec found.")

    job = json.loads(job_path.read_text(encoding="utf-8"))

    # 2. Audio & Captions Synthesis
    manifest_path = job_dir / "build" / "audio_manifest.json"
    if not manifest_path.exists():
        print("[Step 2/5] Synthesizing dual-speaker Edge-TTS voices & synchronized karaoke captions...")
        asyncio.run(build_audio_and_captions(job_path))
    else:
        print("[Step 2/5] Audio & captions already exist.")

    # 3. Media Acquisition with Multi-Tier Fallback
    print("[Step 3/5] Verifying visual assets (NASA -> Wikimedia -> Stock)...")
    fetch_missing_media(job_path, source="auto", overwrite=False)

    for scene in job.get("scenes", []):
        rel = str(scene["clip_file"])
        if resolve_scene_media(job_dir, rel) is None:
            raise RuntimeError(f"Failed to acquire visual media for scene {scene['index']} ({rel})")

    # 4. Assembly & Video Rendering
    final_mp4 = OUTPUT_DIR / f"{job_id}_shorts.mp4"
    if not final_mp4.exists():
        print(f"[Step 4/5] Assembling 1080x1920 Short (Lanczos + CAS 0.45 + Split-Screen Presenters)...")
        final_mp4 = assemble_short(job_path, bgm_path=bgm_path)
    else:
        print(f"[Step 4/5] Master Short video already rendered: {final_mp4}")

    # 5. Immediate YouTube Scheduling & Ledger Update
    print("[Step 5/5] Immediately uploading & scheduling on YouTube (Dufkon)...")
    receipt = schedule_and_upload_immediately(
        job_path=job_path,
        final_mp4=final_mp4,
        dry_run=dry_run,
    )
    if receipt and receipt.get("video_id"):
        if not dry_run:
            cleanup_job_intermediates(job_dir)
        return str(receipt["video_id"])
    return None


def sweep_unscheduled_ready_outputs(dry_run: bool = False, min_delay: int = 120) -> int:
    """Immediately upload & schedule any already-rendered Short MP4 that lacks an upload_receipt.json."""
    scheduled = 0
    for job_path in sorted(JOBS_DIR.glob("*/job.json")):
        job_dir = job_path.parent
        if has_valid_upload_receipt(job_dir):
            continue
        final_mp4 = OUTPUT_DIR / f"{job_dir.name}_shorts.mp4"
        if final_mp4.exists():
            print(f"⚡ [Zero-Orphan Sweep] Found rendered MP4 without YouTube schedule: {final_mp4.name}")
            receipt = schedule_and_upload_immediately(job_path=job_path, final_mp4=final_mp4, dry_run=dry_run)
            if receipt and receipt.get("video_id"):
                scheduled += 1
                if not dry_run:
                    time.sleep(min_delay)
    return scheduled


def run_producer_cycle(
    target_buffer_days: int = 7,
    batch_limit: int = 3,
    dry_run: bool = False,
    bgm_path: Path | None = None,
) -> int:
    """Sweep any unscheduled outputs first, then produce & immediately schedule new Shorts until buffer is full."""
    policy = load_policy()
    sched = policy.get("schedule_defaults", {})
    tz_offset = sched.get("timezone_offset", "+07:00")
    daily_slots = list(sched.get("daily_slots", ["19:00"]))
    slots_per_day = max(1, len(daily_slots))
    target_slots = target_buffer_days * slots_per_day
    limits = policy.get("rate_limits", {})
    min_delay = int(limits.get("min_delay_seconds_between_uploads", 120))

    # Always sweep any rendered-but-unscheduled MP4 first so zero source is ever orphaned
    swept = sweep_unscheduled_ready_outputs(dry_run=dry_run, min_delay=min_delay)

    booked_count, latest_dt = count_booked_future_days(tz_offset)
    log_daemon(
        f"📊 [STATUS] Current Buffer: {booked_count}/{target_slots} scheduled Shorts "
        f"({slots_per_day} slots/day: {', '.join(sorted(daily_slots))} | Latest: {latest_dt.isoformat() if latest_dt else 'None'})."
    )

    deficit = target_slots - booked_count
    if deficit <= 0:
        log_daemon(f"✨ Buffer is fully stocked ({booked_count} >= {target_slots} slots / {target_buffer_days} days). Syncing ledger...")
        sync_production_ledger()
        return swept

    to_produce = min(deficit, batch_limit)
    log_daemon(f"🚀 Buffer deficit: {deficit} slot(s). Producing & immediately scheduling {to_produce} new Short(s) in this cycle...")

    produced = swept
    for idx in range(to_produce):
        job_id, topic = discover_next_topic()
        try:
            vid = produce_and_schedule_single_job(
                job_id=job_id,
                topic=topic,
                dry_run=dry_run,
                bgm_path=bgm_path,
            )
            if vid:
                produced += 1
                log_daemon(f"✅ Scheduled {job_id} -> Video ID: {vid}")
                if idx + 1 < to_produce and not dry_run:
                    log_daemon(f"⏳ Cooling down for {min_delay}s per YouTube API rate limit...")
                    time.sleep(min_delay)
        except Exception as exc:
            log_daemon(f"❌ Error producing {job_id}: {exc}")
            import traceback

            traceback.print_exc()
            continue

    sync_production_ledger()
    return produced


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuous YouTube Shorts automated production loop.")
    parser.add_argument("--target-buffer-days", type=int, default=7, help="Minimum days of scheduled buffer")
    parser.add_argument("--batch-limit", type=int, default=3, help="Max videos to produce per cycle")
    parser.add_argument("--loop", action="store_true", help="Run indefinitely in a continuous loop")
    parser.add_argument("--interval", type=int, default=3600, help="Seconds between loop checks (default: 3600s)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without uploading")
    parser.add_argument("--bgm", type=Path, default=None, help="Optional background music file")
    args = parser.parse_args()

    print("🤖 YouTube Shorts Continuous Production Daemon Started.")
    print(f"🎯 Target Buffer: {args.target_buffer_days} days | Mode: {'Infinite Loop' if args.loop else 'Single Pass'}\n")

    while True:
        try:
            run_producer_cycle(
                target_buffer_days=args.target_buffer_days,
                batch_limit=args.batch_limit,
                dry_run=args.dry_run,
                bgm_path=args.bgm.resolve() if args.bgm else None,
            )
        except Exception as err:
            print(f"⚠️ Unexpected error in producer cycle: {err}")

        if not args.loop:
            break

        print(f"\n💤 Sleeping for {args.interval}s until next check...")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
