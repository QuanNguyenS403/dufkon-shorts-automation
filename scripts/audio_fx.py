"""Procedural FFmpeg sound effects, sidechain ducking, and loudness mastering for Shorts."""

from __future__ import annotations

import subprocess
if hasattr(subprocess, "CREATE_NO_WINDOW") and not getattr(subprocess.run, "_no_window", False):
    _orig_subprocess_run = subprocess.run

    def _run_no_window(*args, **kwargs):
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        return _orig_subprocess_run(*args, **kwargs)

    _run_no_window._no_window = True
    subprocess.run = _run_no_window
from pathlib import Path


def synthesize_ambient_bed(duration: float, dst_wav: Path) -> None:
    """Generate a subtle warm deep-ambient drone bed via FFmpeg (zero external deps)."""
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    fade_out_start = max(0.2, duration - 1.2)
    af = (
        "lowpass=f=210,highpass=f=45,"
        f"volume=0.85,afade=t=in:st=0:d=0.8,afade=t=out:st={fade_out_start:.2f}:d=1.2"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anoisesrc=color=brown:sample_rate=48000:duration={duration:.3f}",
        "-af",
        af,
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(dst_wav),
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def synthesize_whoosh_sfx(dst_wav: Path, duration: float = 0.34) -> None:
    """Generate a crisp bandpass noise whoosh for scene transitions."""
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    peak = duration * 0.45
    fade_out = max(0.05, duration - peak)
    af = (
        "highpass=f=320,lowpass=f=2400,"
        f"afade=t=in:st=0:d={peak:.3f}:curve=qsin,"
        f"afade=t=out:st={peak:.3f}:d={fade_out:.3f}:curve=qsin,"
        "volume=0.70"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anoisesrc=color=pink:sample_rate=48000:duration={duration:.3f}",
        "-af",
        af,
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(dst_wav),
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def synthesize_hook_impact(dst_wav: Path, duration: float = 0.45) -> None:
    """Generate a subtle sub-bass hook impact at t=0s to grab viewer attention."""
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    af = (
        "lowpass=f=160,"
        f"afade=t=in:st=0:d=0.015,afade=t=out:st=0.04:d={max(0.1, duration - 0.04):.3f}:curve=exp,"
        "volume=0.80"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=72:sample_rate=48000:duration={duration:.3f}",
        "-af",
        af,
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(dst_wav),
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def build_sfx_track(
    total_duration: float,
    transition_times: list[float],
    build_dir: Path,
    dst_wav: Path,
) -> None:
    """Build a full-length stereo SFX track aligned to t=0 hook and scene transitions."""
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    hook_wav = build_dir / "sfx_hook.wav"
    whoosh_wav = build_dir / "sfx_whoosh.wav"
    synthesize_hook_impact(hook_wav)
    synthesize_whoosh_sfx(whoosh_wav)

    inputs: list[str] = [
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=channel_layout=stereo:sample_rate=48000:duration={total_duration:.3f}",
        "-i",
        str(hook_wav),
    ]
    filter_parts: list[str] = ["[1:a]adelay=0|0[s0]"]
    mix_labels: list[str] = ["[0:a]", "[s0]"]

    input_idx = 2
    for t_sec in transition_times:
        if t_sec <= 0.35 or t_sec >= total_duration - 0.25:
            continue
        delay_ms = max(0, int(round((t_sec - 0.16) * 1000)))
        inputs.extend(["-i", str(whoosh_wav)])
        lbl = f"[s{input_idx}]"
        filter_parts.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms}{lbl}")
        mix_labels.append(lbl)
        input_idx += 1

    filter_parts.append(
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=first:normalize=0[sfx_out]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[sfx_out]",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(dst_wav),
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def master_short_audio(
    voiceover_wav: Path,
    bed_wav: Path,
    total_duration: float,
    transition_times: list[float],
    build_dir: Path,
    out_wav: Path,
    bgm_volume: float = 0.16,
    sfx_volume: float = 0.35,
    enable_sfx: bool = True,
    target_lufs: float = -14.0,
) -> None:
    """Mix voiceover + ducked BGM + optional transition SFX and master to YouTube LUFS."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    inputs = ["-i", str(voiceover_wav), "-i", str(bed_wav)]
    filter_steps = [
        "[0:a]asplit=2[v_main][v_sc]",
        f"[1:a]volume={bgm_volume:.3f}[bgm_pre]",
        "[bgm_pre][v_sc]sidechaincompress=threshold=0.03:ratio=5:attack=15:release=220[bgm_ducked]",
    ]

    if enable_sfx:
        sfx_wav = build_dir / "sfx_track.wav"
        build_sfx_track(total_duration, transition_times, build_dir, sfx_wav)
        inputs.extend(["-i", str(sfx_wav)])
        filter_steps.append(f"[2:a]volume={sfx_volume:.3f}[sfx_scaled]")
        filter_steps.append(
            "[v_main][bgm_ducked][sfx_scaled]amix=inputs=3:duration=first:normalize=0,"
            f"loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11,alimiter=limit=0.95[out]"
        )
    else:
        filter_steps.append(
            "[v_main][bgm_ducked]amix=inputs=2:duration=first:normalize=0,"
            f"loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11,alimiter=limit=0.95[out]"
        )

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filter_steps),
        "-map",
        "[out]",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
