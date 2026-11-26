# Role 07: Xuất bản (Publisher)

- **Inputs**: `PASS` QC report matching current `script_hash` & `render_hash`, target `channel_id` (`UCVEH1Fr34ceSw4FY27i656A`), next available UTC slot.
- **Responsibilities**:
  1. Enforce **single-publisher lock** (only one active publisher writes schedules to YouTube).
  2. Run `qc_gate.validate_job_for_publish()` immediately before any `videos().insert` call.
  3. Record `UPLOADING` intent in `data/dufkon.db` (`publications` table, `UNIQUE(channel_id, episode_id)`) **before** starting upload.
  4. Verify OAuth channel ID matches `UCVEH1Fr34ceSw4FY27i656A`; use resumable upload with 5xx backoff.
  5. Save `video_id` immediately to both `upload_receipt.json` and `data/dufkon.db`.
- **On Failure**: If upload outcome is ambiguous (network drop after final chunk), transition to `RECONCILE` and query recent channel uploads — **never** blindly create a duplicate upload.
