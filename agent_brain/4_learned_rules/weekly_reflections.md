# Weekly Reflections (`4_learned_rules/weekly_reflections.md`)

## 2026-11-26 — Baseline Audit (A0)
- **Audit Finding 1 (P0)**: 12/20 existing jobs (`batch_06`–`batch_14`, `batch_16`–`batch_18`) used identical generic fallback sentences from `build_fallback_job_spec()`, and `batch_15_sun_becomes_black_hole` was misrouted to the falling-into-black-hole template. `batch_09_lightning_strike` went public on 2026-11-26 02:00 `+07:00`; 11 others remain scheduled on YouTube for owner review/re-upload, and `batch_18` was blocked before upload.
- **Audit Finding 2 (P0)**: `generate_job.py` ignored the `--model` CLI argument and hardcoded `gemini-3.5-flash` with an aggressive 8s timeout, causing frequent fallbacks.
- **Audit Finding 3 (P1)**: `fetch_media.py` lacked a rights/attribution `media_manifest.json` and fell back to `"deep space galaxy"` unconditionally.

## Weekly Reflection Prompt (Run Every Sunday 03:00 +07:00)
> You are the Dufkon YouTube Shorts Growth Analyst. Given the top 5 episodes by 7-day views/engagement and the bottom 5 episodes from `data/dufkon.db`:
> 1. Identify 3 common winning traits (hook structure, time-boxed stakes, presenter layout, visual specificity).
> 2. Identify 3 recurring failure modes and add concrete prevention rules to `4_learned_rules/do_not_repeat.yaml`.
> 3. Propose 3 distinct new topic angles for the next week's series.
