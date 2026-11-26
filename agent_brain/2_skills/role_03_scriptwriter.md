# Role 03: Biên kịch (Scriptwriter)

- **Inputs**: Approved topic brief, `1_knowledge/persona_profile.yaml`, `1_knowledge/science_editorial_rules.md`, top 3 cards from `3_case_bank/winning_teardowns.jsonl`.
- **Responsibilities**:
  1. Write a 5–7 scene Host/Guest dialogue totaling 75–115 spoken words (~28–45s):
     - Scene 1 (`host`): 2–3s pattern-interrupt Hook with an open curiosity loop.
     - Scene 2 (`guest`): Concrete physical mechanism + real numbers.
     - Scene 3 (`host`): Escalation or counter-intuitive twist.
     - Scene 4 (`guest`): Deepest consequence or scale comparison.
     - Scene 5 (`host`): Crisp payoff + comment-driving CTA.
  2. Attach `source_citation` to key scientific claims.
  3. Zero `banned_phrases` and zero generic fallback sentences.
- **On Failure**: Rewrite only the flagged scene or claim failing QC; max 2 rework loops before dropping.
