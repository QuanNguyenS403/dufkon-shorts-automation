# Role 04: Sản xuất tư liệu (Asset Producer)

- **Inputs**: Locked `job.json` scenes (`stock_query`, `flow_prompt`), `1_knowledge/science_editorial_rules.md`.
- **Responsibilities**:
  1. Prefer Dufkon-created diagrams/visualizations or domain-exact NASA/Wikimedia/Pexels/Pixabay assets.
  2. Record every downloaded asset in `jobs/<id>/media_manifest.json` (`source_provider`, `source_url`, `author`, `license_name`, `commercial_allowed`, `attribution_text`, `checksum_sha256`, `matched_query`).
  3. Never substitute unrelated `"deep space galaxy"` footage for non-space topics.
- **On Failure**: If rights are unresolved or no relevant visual exists, mark `HOLD_RIGHTS` or `REWORK` and replace only the missing scene asset.
