"""FFmpeg preprocessor and validator for YouTube Shorts (9:16) and standard Videos (16:9)."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024  # YouTube API 2 MB limit
MIN_THUMBNAIL_WIDTH = 640


@dataclass
class VideoInfo:
    width: int
    height: int
    duration: float
    video_codec: str
    has_audio: bool


def probe_video(input_path: Path) -> VideoInfo:
    """Inspect video stream dimensions, duration, and audio presence via ffprobe."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,width,height:format=duration",
        "-of",
        "json",
        str(input_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise ValueError(f"No video stream found in {input_path}")

    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    duration = float(data.get("format", {}).get("duration", 0.0))

    return VideoInfo(
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        duration=duration,
        video_codec=str(video_stream.get("codec_name", "")),
        has_audio=has_audio,
    )


def build_scale_filter(target_w: int, target_h: int, fit: str) -> str:
    """Build FFmpeg video filter to fit target resolution cleanly."""
    if fit == "crop":
        return (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},setsar=1"
        )
    return (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    )


def convert_video(
    input_path: Path,
    output_path: Path,
    mode: str,
    fit: str = "pad",
    max_duration: float | None = None,
) -> VideoInfo:
    """Convert input media into YouTube-ready Shorts (1080x1920) or Video (1920x1080) MP4."""
    info = probe_video(input_path)
    target_w, target_h = (1080, 1920) if mode == "shorts" else (1920, 1080)

    if mode == "shorts" and max_duration is None:
        max_duration = 60.0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = build_scale_filter(target_w, target_h, fit)

    cmd = ["ffmpeg", "-y", "-i", str(input_path)]
    if max_duration is not None and info.duration > max_duration:
        cmd.extend(["-t", str(max_duration)])

    cmd.extend(
        [
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if info.has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000"])
    else:
        cmd.extend(["-an"])

    cmd.extend(["-movflags", "+faststart", str(output_path)])
    subprocess.run(cmd, check=True)
    return probe_video(output_path)


def validate_thumbnail(thumb_path: Path) -> tuple[int, int, int]:
    """Validate thumbnail image size and dimensions against YouTube API limits."""
    if not thumb_path.exists():
        raise FileNotFoundError(f"Thumbnail not found: {thumb_path}")

    size_bytes = thumb_path.stat().st_size
    if size_bytes > MAX_THUMBNAIL_BYTES:
        raise ValueError(f"Thumbnail exceeds 2 MB limit ({size_bytes} bytes): {thumb_path}")

    with Image.open(thumb_path) as img:
        width, height = img.size

    if width < MIN_THUMBNAIL_WIDTH:
        raise ValueError(f"Thumbnail width {width}px is below recommended minimum {MIN_THUMBNAIL_WIDTH}px.")

    return width, height, size_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare and validate videos/thumbnails for YouTube.")
    parser.add_argument("--input", type=Path, help="Source video path")
    parser.add_argument("--output", type=Path, help="Output MP4 path")
    parser.add_argument("--mode", choices=["shorts", "video"], default="shorts", help="Target format")
    parser.add_argument("--fit", choices=["pad", "crop"], default="pad", help="Aspect-ratio fitting method")
    parser.add_argument("--max-duration", type=float, default=None, help="Optional max duration in seconds")
    parser.add_argument("--check-thumbnail", type=Path, default=None, help="Validate thumbnail image file")
    args = parser.parse_args()

    if args.check_thumbnail:
        w, h, size_b = validate_thumbnail(args.check_thumbnail)
        print(f"Thumbnail OK: {w}x{h}, {size_b / 1024:.1f} KB")

    if args.input:
        if not args.output:
            suffix = "_shorts.mp4" if args.mode == "shorts" else "_youtube.mp4"
            args.output = Path("output") / f"{args.input.stem}{suffix}"
        out_info = convert_video(
            input_path=args.input,
            output_path=args.output,
            mode=args.mode,
            fit=args.fit,
            max_duration=args.max_duration,
        )
        print(
            f"Prepared {args.mode}: {args.output} "
            f"({out_info.width}x{out_info.height}, {out_info.duration:.2f}s, codec={out_info.video_codec})"
        )


if __name__ == "__main__":
    main()
