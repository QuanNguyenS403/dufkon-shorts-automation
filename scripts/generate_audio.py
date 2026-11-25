"""Generate scene-aligned voiceover and viral word-highlighted .ass captions via edge-tts."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
if hasattr(subprocess, "CREATE_NO_WINDOW") and not getattr(subprocess.run, "_no_window", False):
    _orig_subprocess_run = subprocess.run

    def _run_no_window(*args, **kwargs):
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        return _orig_subprocess_run(*args, **kwargs)

    _run_no_window._no_window = True
    subprocess.run = _run_no_window
from pathlib import Path
from typing import Any

import edge_tts

DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
DEFAULT_GUEST_VOICE = "en-US-AvaMultilingualNeural"
DEFAULT_RATE = "+6%"
WORDS_PER_CHUNK = 3
REPO_ROOT = Path(__file__).resolve().parent.parent


def probe_duration(media_path: Path) -> float:
    """Return media duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp H:MM:SS.cs."""
    total_cs = max(0, int(round(seconds * 100)))
    hours = total_cs // 360000
    rem = total_cs % 360000
    minutes = rem // 6000
    rem %= 6000
    secs = rem // 100
    cs = rem % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def escape_ass_text(text: str) -> str:
    """Escape characters that have special meaning in ASS dialogue lines."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def chunk_word_events(
    word_events: list[dict[str, Any]],
    words_per_chunk: int = WORDS_PER_CHUNK,
) -> list[dict[str, Any]]:
    """Group WordBoundary events into punchy 2-3 word chunks retaining per-word timings."""
    chunks: list[dict[str, Any]] = []
    i = 0
    while i < len(word_events):
        group = word_events[i : i + words_per_chunk]
        clean_words: list[dict[str, Any]] = []
        for w in group:
            w_start = float(w["start"])
            w_end = max(w_start + 0.08, float(w["end"]))
            clean_words.append(
                {
                    "text": str(w["text"]).strip().upper(),
                    "start": w_start,
                    "end": w_end,
                }
            )
        text = " ".join(w["text"] for w in clean_words).strip()
        start = clean_words[0]["start"]
        end = max(start + 0.18, clean_words[-1]["end"])
        chunks.append({"text": text, "start": start, "end": end, "words": clean_words})
        i += words_per_chunk
    return chunks


def build_fallback_word_events(text: str, duration: float) -> list[dict[str, Any]]:
    """Estimate word timing evenly when a voice omits WordBoundary events."""
    words = [w for w in text.split() if w.strip()]
    if not words or duration <= 0:
        return []
    step = duration / len(words)
    return [
        {"text": w, "start": idx * step, "end": (idx + 1) * step}
        for idx, w in enumerate(words)
    ]


async def synthesize_scene(
    text: str,
    out_mp3: Path,
    voice: str,
    rate: str,
    max_retries: int = 3,
) -> tuple[float, list[dict[str, Any]]]:
    """Synthesize a single scene narration MP3 and capture WordBoundary timings with voice & offline fallback."""
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    word_events: list[dict[str, Any]] = []

    fallback_voices = [voice]
    if "Ava" in voice or "Female" in voice or "HoaiMy" in voice:
        fallback_voices.extend(["en-US-JennyNeural", "en-US-AriaNeural"])
    else:
        fallback_voices.extend(["en-US-GuyNeural", "en-US-BrianNeural"])
    # Deduplicate preserving order
    voice_candidates = list(dict.fromkeys(fallback_voices))

    for attempt in range(1, max_retries + 1):
        cand_voice = voice_candidates[(attempt - 1) % len(voice_candidates)]
        word_events = []
        try:
            communicate = edge_tts.Communicate(
                text=text, voice=cand_voice, rate=rate, boundary="WordBoundary"
            )
            with out_mp3.open("wb") as audio_file:
                async for chunk in communicate.stream():
                    ctype = chunk.get("type")
                    if ctype == "audio":
                        audio_file.write(chunk["data"])
                    elif ctype == "WordBoundary":
                        offset_sec = float(chunk["offset"]) / 10_000_000.0
                        dur_sec = float(chunk["duration"]) / 10_000_000.0
                        word_events.append(
                            {
                                "text": str(chunk["text"]),
                                "start": offset_sec,
                                "end": offset_sec + max(dur_sec, 0.12),
                            }
                        )
            actual_duration = probe_duration(out_mp3)
            if not word_events:
                word_events = build_fallback_word_events(text, actual_duration)
            return actual_duration, word_events
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < max_retries:
                await asyncio.sleep(1.5 * attempt)

    # Offline Windows System.Speech fallback so production never stalls when Edge-TTS is unreachable
    try:
        tmp_wav = out_mp3.with_suffix(".offline.wav")
        safe_text = text.replace("'", "''")
        ps_cmd = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Rate = 1; $s.SetOutputToWaveFile('{tmp_wav}'); "
            f"$s.Speak('{safe_text}'); $s.Dispose()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, check=True)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(tmp_wav), "-c:a", "libmp3lame", "-q:a", "2", str(out_mp3)],
            capture_output=True,
            check=True,
        )
        tmp_wav.unlink(missing_ok=True)
        actual_duration = probe_duration(out_mp3)
        return actual_duration, build_fallback_word_events(text, actual_duration)
    except Exception:
        pass

    raise RuntimeError(f"edge-tts failed after {max_retries} attempts: {last_err}") from last_err


def trim_audio_silence(src_mp3: Path, dst_wav: Path) -> float:
    """Trim leading dead air lightly and convert scene audio to 48kHz stereo WAV."""
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src_mp3),
        "-af",
        "silenceremove=start_periods=1:start_silence=0.02:start_threshold=-45dB",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(dst_wav),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return probe_duration(dst_wav)


def _normalize_chunk_word_spans(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    """Make word start/end spans contiguous across the chunk window to avoid flicker."""
    words = chunk.get("words") or []
    if not words:
        return []
    c_start = float(chunk["start"])
    c_end = max(c_start + 0.12, float(chunk["end"]))
    normalized: list[dict[str, Any]] = []
    for idx, w in enumerate(words):
        w_start = c_start if idx == 0 else max(c_start, float(w["start"]))
        if idx + 1 < len(words):
            next_start = max(w_start + 0.05, float(words[idx + 1]["start"]))
            w_end = min(c_end, next_start)
        else:
            w_end = c_end
        if w_end <= w_start:
            w_end = w_start + 0.05
        normalized.append({"text": str(w["text"]), "start": w_start, "end": w_end})
    # Snap adjacent boundaries strictly
    for idx in range(len(normalized) - 1):
        normalized[idx]["end"] = normalized[idx + 1]["start"]
    normalized[-1]["end"] = max(normalized[-1]["start"] + 0.05, c_end)
    return normalized


def has_presenter_assets() -> bool:
    """Return True if presenter clips exist in assets/presenters or assets/presenters/pool."""
    pdir = REPO_ROOT / "assets" / "presenters"
    pool_dir = pdir / "pool"
    if pool_dir.exists() and any(pool_dir.glob("*.mp4")):
        return True
    return (pdir / "host_talking.mp4").exists() and (pdir / "guest_talking.mp4").exists()


def resolve_job_presenter_plan(
    job_path: Path,
    layout_override: str | None = None,
) -> dict[str, Any]:
    """Determine and persist whether this video (and which scenes) show a human presenter.

    Modes supported:
      - 'fullscreen': No human presenter panel (100% 9:16 visual B-roll).
      - 'hybrid': Presenter appears flexibly only on selected anchor scenes (e.g. Hook Scene 1
                  and optionally final CTA scene), while middle science scenes expand to full 9:16.
      - 'split': Presenter appears across all scenes.
      - 'random' (default): Randomly picks 'fullscreen', 'hybrid', or 'split' using policy weights,
                  and randomly selects from the natural presenter pool (real camera or natural studio).
    """
    import random
    from youtube_auth import load_policy

    policy = load_policy()
    prod = policy.get("production_defaults", {})
    job = json.loads(job_path.read_text(encoding="utf-8"))
    scenes = job.get("scenes", [])

    if not has_presenter_assets():
        for s in scenes:
            s["show_presenter"] = False
        return {"layout": "fullscreen", "pair": "none", "scene_flags": [False] * len(scenes)}

    requested = (
        layout_override
        or job.get("presenter_layout")
        or prod.get("presenter_layout", "random")
    ).strip().lower()

    # Reuse already-resolved random choice for this job unless explicitly overridden
    resolved_layout = job.get("resolved_presenter_layout")
    if layout_override and layout_override != "random":
        resolved_layout = layout_override
    elif requested in ("fullscreen", "hybrid", "split"):
        resolved_layout = requested
    elif not resolved_layout or resolved_layout not in ("fullscreen", "hybrid", "split"):
        weights_cfg = prod.get("presenter_random_weights", {"fullscreen": 0.40, "hybrid": 0.40, "split": 0.20})
        modes = ["fullscreen", "hybrid", "split"]
        w_vals = [float(weights_cfg.get(m, 0.33)) for m in modes]
        resolved_layout = random.choices(modes, weights=w_vals, k=1)[0]

    # Pick natural presenter pair ('real_camera', 'natural_studio', or 'mixed_real_first')
    presenter_pair = job.get("presenter_pair")
    if not presenter_pair:
        presenter_pair = random.choice(["real_camera", "mixed_real_first", "natural_studio"])

    scene_flags: list[bool] = []
    total_scenes = len(scenes)
    for idx, scene in enumerate(scenes):
        if "show_presenter" in scene and layout_override is None and job.get("resolved_presenter_layout") == resolved_layout:
            flag = bool(scene["show_presenter"])
        elif resolved_layout == "fullscreen":
            flag = False
        elif resolved_layout == "split":
            flag = True
        else:
            # 'hybrid': show presenter on Scene 1 (Hook) and randomly on either final CTA scene or Scene 3
            if idx == 0:
                flag = True
            elif idx == total_scenes - 1:
                flag = random.choice([True, False])
            else:
                flag = False
        scene["show_presenter"] = flag
        scene_flags.append(flag)

    job["resolved_presenter_layout"] = resolved_layout
    job["presenter_pair"] = presenter_pair
    job_path.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "layout": resolved_layout,
        "pair": presenter_pair,
        "scene_flags": scene_flags,
    }


def write_ass_file(
    chunks: list[dict[str, Any]],
    ass_path: Path,
    style_mode: str = "viral_highlight",
    split_layout: bool = False,
) -> None:
    """Write a 1080x1920 Shorts-safe ASS subtitle file with per-scene split vs fullscreen positioning."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HookSplit,Arial Black,78,&H00FFFFFF,&H0000E5FF,&H00000000,&HB0000000,-1,0,0,0,100,100,1,0,1,7,3,2,65,65,665,1
Style: DefaultSplit,Arial Black,70,&H00FFFFFF,&H0000E5FF,&H00000000,&HB0000000,-1,0,0,0,100,100,1,0,1,6,3,2,65,65,665,1
Style: HookFull,Arial Black,78,&H00FFFFFF,&H0000E5FF,&H00000000,&HB0000000,-1,0,0,0,100,100,1,0,1,7,3,2,65,65,430,1
Style: DefaultFull,Arial Black,70,&H00FFFFFF,&H0000E5FF,&H00000000,&HB0000000,-1,0,0,0,100,100,1,0,1,6,3,2,65,65,430,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = [header]
    host_hex = "&H00FFE500&"     # Vibrant cyan (ASS BGR) for Host
    guest_hex = "&H0000D5FF&"    # Vibrant golden-amber (ASS BGR) for Guest Expert
    hook_hex = "&H0055FF00&"     # Bright lime-green for first 2 hook chunks
    base_hex = "&H00FFFFFF&"     # Crisp white

    for idx, chunk in enumerate(chunks):
        use_split_pos = bool(chunk.get("show_presenter", split_layout))
        if idx < 2:
            style = "HookSplit" if use_split_pos else "HookFull"
        else:
            style = "DefaultSplit" if use_split_pos else "DefaultFull"
        speaker = str(chunk.get("speaker", "host")).lower()
        speaker_hex = guest_hex if speaker == "guest" else host_hex
        highlight_color = hook_hex if idx < 2 else speaker_hex
        words = _normalize_chunk_word_spans(chunk)

        if style_mode != "viral_highlight" or not words:
            start_str = format_ass_time(float(chunk["start"]))
            end_str = format_ass_time(float(chunk["end"]))
            safe_text = escape_ass_text(str(chunk["text"]))
            styled = f"{{\\fscx92\\fscy92\\t(0,65,\\fscx103\\fscy103)}}{safe_text}"
            lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{styled}\n")
            continue

        for active_idx, active_w in enumerate(words):
            start_str = format_ass_time(active_w["start"])
            end_str = format_ass_time(active_w["end"])
            parts: list[str] = []
            for w_idx, w in enumerate(words):
                safe_w = escape_ass_text(w["text"])
                if w_idx == active_idx:
                    parts.append(f"{{\\c{highlight_color}}}{safe_w}{{\\c{base_hex}}}")
                else:
                    parts.append(f"{{\\c{base_hex}}}{safe_w}")
            pop_prefix = "{\\fscx94\\fscy94\\t(0,60,\\fscx102\\fscy102)}" if active_idx == 0 else ""
            dialogue_text = pop_prefix + " ".join(parts)
            lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{dialogue_text}\n")

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text("".join(lines), encoding="utf-8")


async def build_audio_and_captions(
    job_path: Path,
    style_mode: str = "viral_highlight",
    layout_override: str | None = None,
) -> dict[str, Any]:
    """Generate per-scene audio, concatenated narration, timing manifest, and .ass captions."""
    job_dir = job_path.parent
    plan = resolve_job_presenter_plan(job_path, layout_override=layout_override)
    job = json.loads(job_path.read_text(encoding="utf-8"))

    default_voice = str(job.get("voice", DEFAULT_VOICE))
    job_voices = job.get("voices") or {}
    voices_map = {
        "host": str(job_voices.get("host") or default_voice),
        "guest": str(job_voices.get("guest") or DEFAULT_GUEST_VOICE),
    }
    rate = str(job.get("voice_rate", DEFAULT_RATE))
    scenes = job.get("scenes", [])
    if not scenes:
        raise ValueError(f"No scenes found in {job_path}")

    build_dir = job_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    timeline_scenes: list[dict[str, Any]] = []
    all_chunks: list[dict[str, Any]] = []
    concat_list_lines: list[str] = []
    cursor = 0.0

    for idx, scene in enumerate(scenes, start=1):
        narration = str(scene["narration"]).strip()
        speaker = str(scene.get("speaker", "host")).lower()
        if speaker not in ("host", "guest"):
            speaker = "host"
        show_presenter = bool(scene.get("show_presenter", False))
        scene_voice = voices_map[speaker]
        raw_mp3 = build_dir / f"scene_{idx:02d}_raw.mp3"
        clean_wav = build_dir / f"scene_{idx:02d}.wav"

        raw_dur, word_events = await synthesize_scene(narration, raw_mp3, voice=scene_voice, rate=rate)
        clean_dur = trim_audio_silence(raw_mp3, clean_wav)

        trim_delta = max(0.0, raw_dur - clean_dur)
        shifted_words: list[dict[str, Any]] = []
        for w in word_events:
            w_start = max(0.0, float(w["start"]) - trim_delta)
            w_end = max(w_start + 0.08, float(w["end"]) - trim_delta)
            w_end = min(clean_dur, w_end)
            shifted_words.append(
                {
                    "text": w["text"],
                    "start": cursor + w_start,
                    "end": cursor + w_end,
                }
            )

        scene_chunks = chunk_word_events(shifted_words)
        for c_i in range(len(scene_chunks) - 1):
            if scene_chunks[c_i]["end"] > scene_chunks[c_i + 1]["start"]:
                scene_chunks[c_i]["end"] = scene_chunks[c_i + 1]["start"]
        if scene_chunks:
            scene_chunks[-1]["end"] = cursor + clean_dur
        for ch in scene_chunks:
            ch["speaker"] = speaker
            ch["show_presenter"] = show_presenter

        all_chunks.extend(scene_chunks)
        timeline_scenes.append(
            {
                "index": idx,
                "speaker": speaker,
                "show_presenter": show_presenter,
                "voice": scene_voice,
                "narration": narration,
                "audio_file": str(clean_wav.relative_to(job_dir)).replace("\\", "/"),
                "clip_file": str(scene["clip_file"]),
                "transition": str(scene.get("transition", "auto")),
                "start": round(cursor, 3),
                "duration": round(clean_dur, 3),
                "end": round(cursor + clean_dur, 3),
            }
        )
        concat_list_lines.append(f"file '{clean_wav.name}'\n")
        cursor += clean_dur

    concat_txt = build_dir / "audio_concat.txt"
    concat_txt.write_text("".join(concat_list_lines), encoding="utf-8")

    voiceover_wav = build_dir / "voiceover.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-c",
            "copy",
            str(voiceover_wav),
        ],
        capture_output=True,
        check=True,
    )

    any_split = any(plan["scene_flags"])
    ass_path = build_dir / "captions.ass"
    write_ass_file(all_chunks, ass_path, style_mode=style_mode, split_layout=any_split)

    manifest = {
        "job_id": job.get("id", job_dir.name),
        "voice": default_voice,
        "voices": voices_map,
        "voice_rate": rate,
        "caption_style": style_mode,
        "presenter_layout": plan["layout"],
        "presenter_pair": plan["pair"],
        "split_layout": any_split,
        "total_duration": round(cursor, 3),
        "voiceover_file": "build/voiceover.wav",
        "captions_file": "build/captions.ass",
        "scenes": timeline_scenes,
    }
    manifest_path = build_dir / "timeline.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate voiceover and viral kinetic captions for a Short job.")
    parser.add_argument("--job", type=Path, required=True, help="Path to job.json")
    parser.add_argument(
        "--caption-style",
        choices=["viral_highlight", "chunk"],
        default="viral_highlight",
        help="Subtitle animation style",
    )
    args = parser.parse_args()

    manifest = asyncio.run(build_audio_and_captions(args.job.resolve(), style_mode=args.caption_style))
    print(
        f"Audio & captions ready for {manifest['job_id']}: "
        f"{manifest['total_duration']:.2f}s across {len(manifest['scenes'])} scenes ({manifest['caption_style']})."
    )


if __name__ == "__main__":
    main()
