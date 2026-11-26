# Role 05: Dựng hình & Âm thanh (Editor & Assembler)

- **Inputs**: Locked `job.json`, verified `media_manifest.json`, `config/channel_policy.json`.
- **Responsibilities**:
  1. Synthesize dual-speaker Edge-TTS (`Andrew` host, `Ava` guest at `+6%`) and word-level `.ass` captions.
  2. Assemble 1080×1920 H.264/AAC vertical Short (`-14.0 LUFS`, `CAS 0.45`, progress bar, presenter split/hybrid/fullscreen layout logged in metadata).
  3. Keep captions and visual labels outside YouTube Shorts UI overlays (bottom 25% & right-edge).
- **On Failure**: Rebuild only the failed scene or audio track from cache and re-run `qc_gate.py`.
