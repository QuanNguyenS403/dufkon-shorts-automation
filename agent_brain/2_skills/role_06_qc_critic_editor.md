# Role 06: Biên tập kiểm định (QC Critic Editor)

- **Inputs**: `job.json`, `media_manifest.json`, rendered MP4, `1_knowledge/persona_profile.yaml`, `4_learned_rules/do_not_repeat.yaml`.
- **Responsibilities**:
  1. Run automated + rubric checks (`scripts/qc_gate.py`) scoring 0–100:
     - **Hook (25 pts)**: Concrete paradox/question in Scene 1, no AI throat-clearing.
     - **Originality / No AI Slop (25 pts)**: 0 `banned_phrases`, 0 generic fallback lines, distinct from prior episodes.
     - **Scientific Specificity (20 pts)**: Topic-title alignment, concrete numbers/mechanisms, `source_citation` where required.
     - **Format & Persona (15 pts)**: Host/Guest alternation, 75–115 words, <=70 char title, `#Shorts` tag.
     - **Compliance & Technical (15 pts)**: Valid 1080×1920 MP4 <=60s, audio present, `media_manifest.json` rights clear, `contains_synthetic_media` set.
  2. Return `PASS` (`>= 80`), `REWORK` (with exact scene/reason, max 2 loops), or `DROP`.
  3. Any edit to script or assets invalidates prior `PASS` (`render_hash` / `script_hash` mismatch).
