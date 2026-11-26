# Role 01: Điều phối sản xuất (Producer Coordinator)

- **Inputs**: `channel_mission.yaml`, episode backlog, SQLite `jobs` & `publications` tables, API quota status.
- **Responsibilities**:
  1. Enforce `max_publications_per_day: 2` (`02:00`, `19:00` `+07:00`) and `batch_limit` across sweep + new production combined.
  2. Acquire an exclusive SQLite lease (`acquire_job_lease`) before processing any episode; release or expire stale leases cleanly.
  3. Enforce `incremental_cash_cap_vnd_per_month: 0` (free-tier Gemini + zero-cost Edge-TTS/NASA/Wikimedia/Pexels/Pixabay + local FFmpeg).
  4. Never allow generic fallback scripts or un-QC'd MP4s to enter `READY` or `UPLOADING`.
- **On Failure**: Transition transient errors to `RETRY_AT` with backoff; quarantine repeated failures; exit non-zero if an entire cycle produces 0 valid progress.
