"""Assemble Google Flow / free-media 9:16 clips, voiceover, SFX, ducked BGM, transitions, and viral captions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
if hasattr(subprocess, "CREATE_NO_WINDOW") and not getattr(subprocess.run, "_no_window", False):
    _orig_subprocess_run = subprocess.run

    def _run_no_window(*args, **kwargs):
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        return _orig_subprocess_run(*args, **kwargs)

    _run_no_window._no_window = True
    subprocess.run = _run_no_window
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audio_fx import master_short_audio, synthesize_ambient_bed  # noqa: E402
from prep_video import probe_video  # noqa: E402
from youtube_auth import load_policy  # noqa: E402

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
SPLIT_TOP_HEIGHT = 1220
SPLIT_BOT_HEIGHT = 700
TARGET_FPS = 30
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
AUTO_TRANSITIONS = ["smoothleft", "zoomin", "dissolve", "wipeup", "circleopen"]


def resolve_scene_media(job_dir: Path, clip_rel: str) -> Path | None:
    """Resolve clip path, falling back to same-stem video or image extension if present."""
    candidate = job_dir / clip_rel
    if candidate.exists():
        return candidate
    stem = candidate.with_suffix("")
    for ext in (*VIDEO_EXTS, *IMAGE_EXTS):
        alt = stem.with_suffix(ext)
        if alt.exists():
            return alt
    return None


def find_missing_clips(job_dir: Path, timeline: dict[str, Any]) -> list[tuple[int, Path]]:
    """Return list of (scene_index, expected_clip_path) for missing clip files."""
    missing: list[tuple[int, Path]] = []
    for scene in timeline.get("scenes", []):
        rel = str(scene["clip_file"])
        if resolve_scene_media(job_dir, rel) is None:
            missing.append((int(scene["index"]), job_dir / rel))
    return missing


def detect_leading_black_offset(
    src_media: Path,
    target_duration: float,
    total_duration: float,
) -> float:
    """Detect and return a safe seek offset (in seconds) past a leading black intro."""
    if total_duration <= target_duration + 0.5:
        return 0.0
    probe_window = min(30.0, max(5.0, total_duration - target_duration))
    cmd = [
        "ffmpeg",
        "-t",
        f"{probe_window:.2f}",
        "-i",
        str(src_media),
        "-vf",
        "blackdetect=d=0.5:pix_th=0.10",
        "-an",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    for m in re.finditer(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", res.stderr):
        b_start = float(m.group(1))
        b_end = float(m.group(2))
        if b_start <= 0.25 and b_end >= 0.5:
            candidate = b_end + 0.35
            if total_duration - candidate >= target_duration:
                return round(candidate, 3)
            return round(max(0.0, total_duration - target_duration), 3)
    return 0.0


def normalize_scene_clip(
    src_media: Path,
    dst_clip: Path,
    target_duration: float,
    start_offset: float | None = None,
    target_w: int = TARGET_WIDTH,
    target_h: int = TARGET_HEIGHT,
    sharpen_cas: float = 0.45,
) -> None:
    """Convert video or image to sharp 30fps MP4 with exact dimensions, duration, and clarity."""
    dst_clip.parent.mkdir(parents=True, exist_ok=True)
    is_image = src_media.suffix.lower() in IMAGE_EXTS
    cas_filter = f"cas={sharpen_cas:.2f}," if sharpen_cas > 0 else ""

    if is_image:
        frames = max(1, int(round(target_duration * TARGET_FPS)))
        vf = (
            f"scale={target_w * 2}:{target_h * 2}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={target_w * 2}:{target_h * 2},"
            f"zoompan=z='min(zoom+0.0012,1.14)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={target_w}x{target_h}:fps={TARGET_FPS},"
            f"eq=contrast=1.05:saturation=1.08:brightness=0.01,{cas_filter}setsar=1,format=yuv420p"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(src_media),
            "-t",
            f"{target_duration:.3f}",
            "-vf",
            vf,
            "-an",
            "-r",
            str(TARGET_FPS),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "15",
            "-pix_fmt",
            "yuv420p",
            str(dst_clip),
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return

    info = probe_video(src_media)
    offset = (
        float(start_offset)
        if start_offset is not None
        else detect_leading_black_offset(src_media, target_duration, info.duration)
    )
    if offset > 0:
        print(f"Skipping leading black frames in {src_media.name}: seeking to {offset:.2f}s")

    cmd = ["ffmpeg", "-y"]
    if info.duration < target_duration:
        cmd.extend(["-stream_loop", "-1"])
    elif offset > 0:
        cmd.extend(["-ss", f"{offset:.3f}"])
    cmd.extend(["-i", str(src_media), "-t", f"{target_duration:.3f}"])

    vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd+full_chroma_int,"
        f"crop={target_w}:{target_h},fps={TARGET_FPS},"
        f"eq=contrast=1.05:saturation=1.08:brightness=0.01,{cas_filter}setsar=1,format=yuv420p"
    )
    cmd.extend(
        [
            "-vf",
            vf,
            "-an",
            "-r",
            str(TARGET_FPS),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "15",
            "-pix_fmt",
            "yuv420p",
            str(dst_clip),
        ]
    )
    subprocess.run(cmd, capture_output=True, check=True)


def select_presenter_clip(
    speaker: str,
    presenters_dir: Path,
    pair_mode: str = "real_camera",
) -> Path:
    """Select a natural presenter clip from assets/presenters/pool based on speaker and pair mode."""
    pool_dir = presenters_dir / "pool"
    host_real = pool_dir / "host_real_scientist.mp4"
    guest_real = pool_dir / "guest_real_astrophysicist.mp4"
    host_studio = pool_dir / "host_studio_natural.mp4"
    guest_studio = pool_dir / "guest_studio_natural.mp4"

    is_guest = speaker.lower() == "guest"
    if pair_mode == "real_camera":
        cand = guest_real if is_guest else host_real
    elif pair_mode == "mixed_real_first":
        cand = guest_studio if is_guest else host_real
    else:
        cand = guest_studio if is_guest else host_studio

    if cand.exists():
        return cand
    for fallback in (host_real, guest_real, host_studio, guest_studio):
        if fallback.exists():
            return fallback
    return presenters_dir / ("guest_talking.mp4" if is_guest else "host_talking.mp4")


def resolve_bold_font_filter() -> str:
    """Return a cross-platform FFmpeg drawtext font option for Windows and Linux."""
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for font_path in candidates:
        if font_path.exists():
            escaped = str(font_path).replace("\\", "/").replace(":", "\\:")
            return f"fontfile='{escaped}'"
    return "font='Sans'"


def render_presenter_segment(
    src: Path,
    seg_path: Path,
    dur: float,
    speaker: str,
    idx_pos: int,
) -> Path:
    """Render a 1080x700 presenter segment with natural skin tones and subtle lower-third divider."""
    is_guest = speaker.lower() == "guest"
    badge_text = "EXPERT" if is_guest else "HOST"
    accent = "0xF59E0B" if is_guest else "0x38BDF8"
    badge_w = 136 if is_guest else 104

    info = probe_video(src)
    is_prebuilt_panel = info.width == TARGET_WIDTH and info.height == SPLIT_BOT_HEIGHT
    font_opt = resolve_bold_font_filter()

    overlay_ui = (
        f"drawbox=x=0:y=0:w={TARGET_WIDTH}:h=3:color=0xE2E8F0@0.65:t=fill,"
        f"drawbox=x=24:y=18:w={badge_w}:h=38:color=0x0F172A@0.78:t=fill,"
        f"drawbox=x=24:y=18:w=5:h=38:color={accent}@0.95:t=fill,"
        f"drawtext={font_opt}:text='{badge_text}':x=40:y=27:fontsize=21:fontcolor=0xF8FAFC,"
        "setsar=1,format=yuv420p"
    )

    if is_prebuilt_panel:
        vf = f"fps={TARGET_FPS},{overlay_ui}"
    else:
        vf = (
            f"scale={TARGET_WIDTH}:{SPLIT_BOT_HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd,"
            f"crop={TARGET_WIDTH}:{SPLIT_BOT_HEIGHT}:(iw-{TARGET_WIDTH})/2:(ih-{SPLIT_BOT_HEIGHT})*0.24,"
            f"fps={TARGET_FPS},eq=contrast=0.98:saturation=0.92,{overlay_ui}"
        )

    max_seek = max(0.5, info.duration - 1.0)
    loop_seek = (idx_pos * 1.1) % max_seek
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-ss",
            f"{loop_seek:.2f}",
            "-i",
            str(src),
            "-t",
            f"{dur:.3f}",
            "-vf",
            vf,
            "-an",
            "-r",
            str(TARGET_FPS),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "15",
            "-pix_fmt",
            "yuv420p",
            str(seg_path),
        ],
        capture_output=True,
        check=True,
    )
    return seg_path


def stitch_with_xfade(
    norm_clips: list[Path],
    scene_durations: list[float],
    scene_transitions: list[str],
    trans_dur: float,
    dst_video: Path,
) -> None:
    """Stitch normalized clips with FFmpeg xfade transitions keeping exact total duration."""
    if len(norm_clips) == 1 or trans_dur <= 0:
        concat_txt = dst_video.parent / "video_concat.txt"
        concat_txt.write_text("".join(f"file '{p.name}'\n" for p in norm_clips), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(dst_video)],
            capture_output=True,
            check=True,
        )
        return

    inputs: list[str] = []
    filter_parts: list[str] = []
    for idx, clip in enumerate(norm_clips):
        inputs.extend(["-i", str(clip)])
        filter_parts.append(f"[{idx}:v]settb=AVTB,fps={TARGET_FPS},format=yuv420p[v{idx}]")

    cum_dur = scene_durations[0]
    prev_label = "[v0]"
    for idx in range(1, len(norm_clips)):
        t_name = scene_transitions[idx]
        if not t_name or t_name == "auto":
            t_name = AUTO_TRANSITIONS[(idx - 1) % len(AUTO_TRANSITIONS)]
        offset = max(0.0, cum_dur - trans_dur)
        out_label = "[vout]" if idx == len(norm_clips) - 1 else f"[vx{idx}]"
        filter_parts.append(
            f"{prev_label}[v{idx}]xfade=transition={t_name}:duration={trans_dur:.3f}:offset={offset:.3f}{out_label}"
        )
        prev_label = out_label
        cum_dur += scene_durations[idx]

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-r",
            str(TARGET_FPS),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(dst_video),
        ],
        capture_output=True,
        check=True,
    )


def assemble_short(
    job_path: Path,
    bgm_path: Path | None = None,
    enable_sfx: bool | None = None,
    enable_progress_bar: bool | None = None,
    transition_duration: float | None = None,
    presenter_layout: str | None = None,
) -> Path:
    """Assemble final 1080x1920 YouTube Short MP4 with flexible/random presenter layout, transitions, SFX, and captions."""
    import asyncio
    from generate_audio import build_audio_and_captions, resolve_job_presenter_plan

    job_dir = job_path.parent
    repo_root = SCRIPTS_DIR.parent
    build_dir = job_dir / "build"
    timeline_path = build_dir / "timeline.json"

    plan = resolve_job_presenter_plan(job_path, layout_override=presenter_layout)
    job = json.loads(job_path.read_text(encoding="utf-8"))

    if not timeline_path.exists() or presenter_layout is not None:
        asyncio.run(build_audio_and_captions(job_path, layout_override=plan["layout"]))

    policy = load_policy()
    prod = policy.get("production_defaults", {})
    trans_dur = float(
        transition_duration if transition_duration is not None else prod.get("transition_duration", 0.25)
    )
    use_sfx = bool(enable_sfx if enable_sfx is not None else prod.get("enable_sfx", True))
    use_bar = bool(
        enable_progress_bar if enable_progress_bar is not None else prod.get("enable_progress_bar", True)
    )
    bgm_vol = float(prod.get("bgm_volume", 0.16))
    sfx_vol = float(prod.get("sfx_volume", 0.35))
    target_lufs = float(prod.get("loudness_lufs", -14.0))
    sharpen_cas = float(prod.get("sharpen_cas", 0.45))
    video_crf = int(prod.get("video_crf", 15))
    video_preset = str(prod.get("video_preset", "slow"))

    presenters_dir = repo_root / "assets" / "presenters"
    pair_mode = str(plan.get("pair", "real_camera"))
    scene_flags = plan.get("scene_flags", [])

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    missing = find_missing_clips(job_dir, timeline)
    if missing:
        lines = [f"  - Scene {idx}: {path}" for idx, path in missing]
        raise FileNotFoundError(
            "Missing scene media. Generate clips in Google Flow or run scripts/fetch_media.py:\n"
            + "\n".join(lines)
        )

    scenes = timeline["scenes"]
    scene_durs = [float(s["duration"]) for s in scenes]
    scene_transitions = [str(s.get("transition", prod.get("transition_type", "auto"))) for s in scenes]

    total_dur = float(timeline["total_duration"])
    if total_dur > 60.0:
        raise ValueError(f"Short duration {total_dur:.2f}s exceeds 60s YouTube Shorts limit.")

    if len(scenes) >= 2 and trans_dur > 0:
        trans_dur = min(trans_dur, min(scene_durs) * 0.35)
    else:
        trans_dur = 0.0

    print(
        f"🎭 [Layout] Mode='{plan['layout']}' | Presenter Pair='{pair_mode}' | "
        f"Scenes with Presenter={[i + 1 for i, f in enumerate(scene_flags) if f]}"
    )

    norm_clips: list[Path] = []
    for idx_pos, scene in enumerate(scenes):
        idx = int(scene["index"])
        src_media = resolve_scene_media(job_dir, str(scene["clip_file"]))
        assert src_media is not None
        # Add trans_dur overlap to clips after scene 0 so xfade preserves exact total_dur
        clip_dur = scene_durs[idx_pos] + (trans_dur if idx_pos > 0 else 0.0)
        norm_clip = build_dir / f"norm_scene_{idx:02d}.mp4"
        job_scene = next((s for s in job.get("scenes", []) if int(s.get("index", -1)) == idx), {})
        start_offset = job_scene.get("start_offset")
        show_pres = bool(
            scene_flags[idx_pos]
            if idx_pos < len(scene_flags)
            else scene.get("show_presenter", False)
        )

        if show_pres:
            top_clip = build_dir / f"top_scene_{idx:02d}.mp4"
            normalize_scene_clip(
                src_media,
                top_clip,
                clip_dur,
                start_offset=start_offset,
                target_w=TARGET_WIDTH,
                target_h=SPLIT_TOP_HEIGHT,
                sharpen_cas=sharpen_cas,
            )
            speaker = str(scene.get("speaker", "host")).lower()
            pres_src = select_presenter_clip(speaker, presenters_dir, pair_mode=pair_mode)
            bot_clip = build_dir / f"presenter_scene_{idx:02d}.mp4"
            render_presenter_segment(pres_src, bot_clip, clip_dur, speaker=speaker, idx_pos=idx_pos)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(top_clip),
                    "-i",
                    str(bot_clip),
                    "-filter_complex",
                    "[0:v][1:v]vstack=inputs=2,setsar=1,format=yuv420p[v]",
                    "-map",
                    "[v]",
                    "-an",
                    "-r",
                    str(TARGET_FPS),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "15",
                    "-pix_fmt",
                    "yuv420p",
                    str(norm_clip),
                ],
                capture_output=True,
                check=True,
            )
        else:
            normalize_scene_clip(
                src_media,
                norm_clip,
                clip_dur,
                start_offset=start_offset,
                target_w=TARGET_WIDTH,
                target_h=TARGET_HEIGHT,
                sharpen_cas=sharpen_cas,
            )
        norm_clips.append(norm_clip)

    stitched_video = build_dir / "stitched_video.mp4"
    stitch_with_xfade(norm_clips, scene_durs, scene_transitions, trans_dur, stitched_video)

    voiceover_wav = job_dir / str(timeline["voiceover_file"])
    bed_wav = build_dir / "ambient_bed.wav"
    if bgm_path and bgm_path.exists():
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(bgm_path),
                "-t",
                f"{total_dur:.3f}",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(bed_wav),
            ],
            capture_output=True,
            check=True,
        )
    else:
        synthesize_ambient_bed(total_dur, bed_wav)

    transition_times = [float(s["start"]) for s in scenes[1:]]
    mixed_wav = build_dir / "mixed_audio.wav"
    master_short_audio(
        voiceover_wav=voiceover_wav,
        bed_wav=bed_wav,
        total_duration=total_dur,
        transition_times=transition_times,
        build_dir=build_dir,
        out_wav=mixed_wav,
        bgm_volume=bgm_vol,
        sfx_volume=sfx_vol,
        enable_sfx=use_sfx,
        target_lufs=target_lufs,
    )

    job_id = str(job.get("id", job_dir.name))
    output_dir = repo_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_mp4 = output_dir / f"{job_id}_shorts.mp4"

    # Run inside job_dir so relative path build/captions.ass works cleanly on Windows
    if use_bar:
        vf_complex = (
            f"color=c=0x00E5FF@0.90:s={TARGET_WIDTH}x6:r={TARGET_FPS}:d={total_dur:.3f}[bar];"
            f"[0:v]ass=build/captions.ass[vcap];"
            f"[vcap][bar]overlay=x='-W+(W*t/{total_dur:.3f})':y=0:shortest=1[vout]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "build/stitched_video.mp4",
            "-i",
            "build/mixed_audio.wav",
            "-filter_complex",
            vf_complex,
            "-map",
            "[vout]",
            "-map",
            "1:a:0",
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "build/stitched_video.mp4",
            "-i",
            "build/mixed_audio.wav",
            "-vf",
            "ass=build/captions.ass",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
        ]

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            video_preset,
            "-crf",
            str(video_crf),
            "-profile:v",
            "high",
            "-level",
            "4.2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-shortest",
            "-movflags",
            "+faststart",
            str(final_mp4),
        ]
    )
    subprocess.run(cmd, cwd=str(job_dir), capture_output=True, check=True)

    out_info = probe_video(final_mp4)
    print(
        f"Assembled Short OK: {final_mp4} "
        f"({out_info.width}x{out_info.height}, {out_info.duration:.2f}s, layout={plan['layout']}, audio={out_info.has_audio})"
    )
    return final_mp4


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble final 1080x1920 YouTube Short and immediately schedule on YouTube.")
    parser.add_argument("--job", type=Path, required=True, help="Path to job.json")
    parser.add_argument("--bgm", type=Path, default=None, help="Optional background music track")
    parser.add_argument(
        "--presenter-layout",
        choices=["random", "fullscreen", "hybrid", "split"],
        default=None,
        help="Presenter appearance mode (default: policy 'random')",
    )
    parser.add_argument("--no-sfx", action="store_true", help="Disable transition/hook SFX")
    parser.add_argument("--no-progress-bar", action="store_true", help="Disable top retention progress bar")
    parser.add_argument("--transition-duration", type=float, default=None, help="xfade duration in seconds")
    parser.add_argument(
        "--no-auto-schedule",
        action="store_true",
        help="Do not automatically upload & schedule on YouTube right after assembly",
    )
    parser.add_argument("--dry-run", action="store_true", help="Dry-run the immediate YouTube schedule check")
    args = parser.parse_args()

    job_path = args.job.resolve()
    final_mp4 = assemble_short(
        job_path,
        bgm_path=args.bgm.resolve() if args.bgm else None,
        enable_sfx=False if args.no_sfx else None,
        enable_progress_bar=False if args.no_progress_bar else None,
        transition_duration=args.transition_duration,
        presenter_layout=args.presenter_layout,
    )
    if not args.no_auto_schedule:
        from schedule_batch import schedule_and_upload_immediately

        schedule_and_upload_immediately(job_path=job_path, final_mp4=final_mp4, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
