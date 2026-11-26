# Dufkon Shorts — 4-Layer AI Agent Brain

Architecture adapted from `agent_knowledge_and_skills.md` and `DUFKON_SHORTS_MASTER_PLAN.md` to eliminate generic AI slop, enforce scientific accuracy, track media rights, and continuously learn from YouTube Shorts performance.

## Directory Structure

```text
agent_brain/
├── 1_knowledge/            # Mission contract, science editorial rules, YouTube Shorts algorithms, persona
│   ├── channel_mission.yaml
│   ├── science_editorial_rules.md
│   ├── youtube_shorts_algorithms.md
│   └── persona_profile.yaml
├── 2_skills/               # 8-role operational SOPs (each role reads its skill before acting)
│   ├── role_01_producer_coordinator.md
│   ├── role_02_researcher_series_rd.md
│   ├── role_03_scriptwriter.md
│   ├── role_04_asset_producer.md
│   ├── role_05_editor_assembler.md
│   ├── role_06_qc_critic_editor.md
│   ├── role_07_publisher.md
│   └── role_08_analyst_strategist.md
├── 3_case_bank/            # Few-Shot RAG cards: winning human-craft teardowns & anti-patterns
│   ├── winning_teardowns.jsonl
│   └── anti_patterns.jsonl
└── 4_learned_rules/        # Weekly reflection loop outputs & hard blocklists
    ├── weekly_reflections.md
    └── do_not_repeat.yaml
```

## State Machine & Quality Gate

`IDEA -> SCRIPT -> ASSETS -> RENDER -> QC -> READY -> UPLOADING -> PROCESSING -> SCHEDULED/PUBLIC -> MEASURED`

- Any edit to narration or scene assets invalidates prior `PASS` QC results.
- `qc_gate.py` enforces the 100-point Critic Rubric (`>= 80` to `PASS`) before any upload path can execute.
- Generic fallback templates (`build_fallback_job_spec`) are **blocked** from production.
