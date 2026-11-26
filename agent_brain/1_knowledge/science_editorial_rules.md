# Science Editorial Rules (`1_knowledge/science_editorial_rules.md`)

1. **Zero Generic Fallback Slop**: Never use templated multi-purpose sentences (e.g., *"In less than three seconds, the cascading pressure and thermal shift..."*). If the LLM quota is exhausted, pause or use a pre-verified unique script — never generate generic filler.
2. **Topic-Script Fidelity**: Every scene's narration, `flow_prompt`, and `stock_query` must directly match the episode's exact physical premise. (Never reuse a "fall into a black hole" script for "Sun becomes a black hole of the same mass" — the Sun's Schwarzschild radius is ~3 km and Earth's orbit remains unchanged!).
3. **Distinguish Fact vs. Estimate**: Explicitly separate observed physical constants/laws from hypothetical extrapolations.
4. **One Core Question Per Short**: Each 25–45s Short answers one sharp question with a clear open loop at 0–3s, physical mechanism in the middle, and concrete payoff at the end.
5. **Source & Rights Traceability**: Every key scientific claim must reference a primary or reputable source (`source_citation`), and every visual asset must record its provider, URL, license, and commercial usability in `media_manifest.json`.
6. **No Irrelevant Fallback B-Roll**: Never fall back to `"deep space galaxy"` for terrestrial, biological, or ocean-trench topics.
