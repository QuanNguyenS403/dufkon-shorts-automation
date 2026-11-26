# YouTube Shorts Algorithms & YPP Rules (`1_knowledge/youtube_shorts_algorithms.md`)

## Retention & Format Mechanics
- **First 1.5–3.0 Seconds (Hook)**: Must present a concrete physical paradox, scale shock, or immediate consequence. Avoid generic throat-clearing ("Have you ever wondered...", "In today's video...").
- **Target Duration**: 25–45 seconds (75–115 spoken words at `+6%` Edge-TTS rate). Zero dead air, zero filler.
- **Visual Safe Zones (1080×1920)**: Keep captions and key diagram labels away from the bottom 25% (presenter/UI overlay) and right-edge action buttons.
- **Audio Clarity**: Loudness normalized to `-14.0 LUFS`, voice clearly above BGM (`bgm_volume: 0.16`), no clipped endings.

## Monetization & Policy Milestones
- **YPP Expanded Access**: 500 subscribers + 3 valid public uploads in 90 days + 3M eligible Shorts views in 90 days (or 3,000 watch hours).
- **YPP Shorts Ad Revenue Sharing**: 1,000 subscribers + 10M eligible Shorts views in 90 days (~111,111 eligible views/day across catalog).
- **Originality & Repetitiveness Policy**: Mass-produced, templated, or reused content without original editorial/visual contribution risks channel-wide YPP rejection. Every episode must be distinct in script, visual pairing, and scientific insight.
- **Synthetic Media Disclosure**: `containsSyntheticMedia` must be accurately set (`true` when AI-generated/synthetic visuals or voices require disclosure) and logged with rationale.
