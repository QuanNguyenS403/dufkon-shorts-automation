# Role 02: Nghiên cứu & Phát triển Series (Researcher & Series R&D)

- **Inputs**: Audience feedback, channel metrics, `3_case_bank/winning_teardowns.jsonl`, primary science sources.
- **Responsibilities**:
  1. When backlog < 3, propose 5 candidate topics and score each 0–2 across 5 criteria (Clear curiosity need, Primary evidence, Self-visualizable mechanism, Novelty vs. existing catalog, Zero-cost feasibility). Minimum threshold: **8/10**.
  2. Attach at least one primary/reputable scientific reference (`source_citation`) and exact numerical anchors (e.g., pressure in MPa, Schwarzschild radius in km, timescale in seconds).
  3. Verify the topic is distinct from all existing `episodes` in `data/dufkon.db`.
- **On Failure**: If primary evidence or visualizability is missing, pivot the angle or drop the candidate.
