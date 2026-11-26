"""Generate viral YouTube Shorts job.json specs using Google Gemini API (Free Tier)."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent


class SceneSpec(BaseModel):
    index: int = Field(description="1-based scene number")
    speaker: Literal["host", "guest"] = Field(
        default="host",
        description="On-screen & voice presenter for this scene ('host' for hook/bridge/CTA, 'guest' for expert science insight)",
    )
    clip_file: str = Field(description="Relative clip path, e.g. clips/scene_01.mp4")
    narration: str = Field(description="Punchy spoken sentence for this scene (8-18 words)")
    flow_prompt: str = Field(
        description=(
            "Ultra-crisp photorealistic CGI/cinematic visualization of the scientific phenomenon or action "
            "(no podcast studio/microphone, because Host/Guest appear in the bottom presenter panel), "
            "ending with 'no text, no watermark'"
        )
    )
    stock_query: str = Field(
        description="2-4 word English keyword query for free stock B-roll (NASA/Wikimedia/Pexels/Pixabay)"
    )
    source_citation: str = Field(
        default="",
        description="Primary scientific source or physical law supporting this scene's claim",
    )
    transition: Literal[
        "auto", "smoothleft", "zoomin", "dissolve", "wipeup", "circleopen"
    ] = Field(default="auto", description="FFmpeg xfade transition entering this scene")


class ShortJobSpec(BaseModel):
    niche: str = Field(description="Content niche slug, e.g. science_human_limits")
    language: Literal["en", "vi"] = Field(default="en")
    category_id: str = Field(default="28", description="YouTube category ID (28=Science & Tech)")
    contains_synthetic_media: bool = Field(default=True)
    voice: str = Field(default="en-US-AndrewMultilingualNeural")
    voices: dict[str, str] = Field(
        default_factory=lambda: {
            "host": "en-US-AndrewMultilingualNeural",
            "guest": "en-US-AvaMultilingualNeural",
        }
    )
    voice_rate: str = Field(default="+6%")
    character_setting_bible: str = Field(
        description="Shared visual anchor (character appearance, environment, color palette, lighting)"
    )
    title: str = Field(description="Curiosity-driven YouTube Shorts title <= 70 characters")
    description: str = Field(
        description="2-3 sentence hook + comment-bait CTA question + relevant hashtags including #Shorts"
    )
    tags: list[str] = Field(description="6-10 high-relevance SEO tags")
    scenes: list[SceneSpec] = Field(description="5 to 7 fast-paced scenes totaling ~30-48 seconds")


def slugify(text: str) -> str:
    """Convert arbitrary topic text into a filesystem-safe job ID."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return cleaned[:48] or "short_job"


def build_fallback_job_spec(
    topic: str,
    niche: str = "extreme_science",
    language: str = "en",
    num_scenes: int = 5,
) -> ShortJobSpec:
    """Create a high-quality, scientifically structured job spec when API quotas or 503 errors occur."""
    clean_topic = topic.strip().strip('"').strip("'")
    keywords = [
        w.lower().strip(".,?!:;()")
        for w in clean_topic.split()
        if len(w) > 3 and w.lower() not in ("what", "happens", "when", "your", "does", "with", "into", "from")
    ]
    kw1 = keywords[0] if len(keywords) > 0 else "physics"
    kw2 = keywords[1] if len(keywords) > 1 else "science"
    core_q = clean_topic.rstrip("?!. ")

    # Pre-crafted high-impact scenarios for curated topics
    if "black hole" in clean_topic.lower():
        return ShortJobSpec(
            niche=niche,
            language=language,
            category_id="28",
            contains_synthetic_media=True,
            character_setting_bible="Deep cosmic void, dramatic accretion disc glow, high-contrast astrophysical phenomenon",
            title="What Happens If You Fall Into a Black Hole? #Shorts",
            description="What happens if you cross the event horizon of a supermassive black hole? From spaghettification to freezing in time forever. Would you dare take the plunge? Let us know in the comments! #Shorts #Space #Science #BlackHole",
            tags=["black hole", "space science", "astronomy", "spaghettification", "event horizon", "physics", "shorts"],
            scenes=[
                SceneSpec(
                    index=1,
                    speaker="host",
                    clip_file="clips/scene_01.mp4",
                    narration="What actually happens to your body if you fall into a real black hole?",
                    flow_prompt="Massive supermassive black hole with glowing golden accretion disk bending light and space in deep cosmos, no text, no watermark",
                    stock_query="black hole space",
                ),
                SceneSpec(
                    index=2,
                    speaker="guest",
                    clip_file="clips/scene_02.mp4",
                    narration="As you approach the event horizon, gravitational tidal forces pull far harder on your feet than your head.",
                    flow_prompt="Extreme gravitational lensing bending starfield around dark cosmic sphere, no text, no watermark",
                    stock_query="gravitational lensing",
                ),
                SceneSpec(
                    index=3,
                    speaker="host",
                    clip_file="clips/scene_03.mp4",
                    narration="This difference stretches your body into a microscopic stream of atoms, a violent process called spaghettification!",
                    flow_prompt="Luminous stream of plasma and matter being pulled into dark cosmic vortex, no text, no watermark",
                    stock_query="black hole matter",
                ),
                SceneSpec(
                    index=4,
                    speaker="guest",
                    clip_file="clips/scene_04.mp4",
                    narration="To an outside observer, time dilates so severely you seem to freeze at the horizon forever as light fades to black.",
                    flow_prompt="Glowing horizon of warped light and infinite darkness with stars bending at the boundary of reality, no text, no watermark",
                    stock_query="event horizon space",
                ),
                SceneSpec(
                    index=5,
                    speaker="host",
                    clip_file="clips/scene_05.mp4",
                    narration="Inside the central singularity, all known laws of physics collapse completely. Would you look back?",
                    flow_prompt="Hypothetical singularity at center of spacetime rupture with brilliant bursts of quantum energy, no text, no watermark",
                    stock_query="deep space singularity",
                ),
            ],
        )

    # Universal structured science fallback
    return ShortJobSpec(
        niche=niche,
        language=language,
        category_id="28",
        contains_synthetic_media=True,
        character_setting_bible="High-contrast scientific phenomenon, vivid cinematic lighting, ultra-sharp detail",
        title=f"{core_q}? #Shorts"[:70],
        description=f"Exploring the extreme physics behind {core_q}. Would our world survive? Leave your thoughts in the comments! #Shorts #Science #Physics #{kw1.title()}",
        tags=[kw1, kw2, "science", "physics", "mindblowing", "space", "facts", "shorts"],
        scenes=[
            SceneSpec(
                index=1,
                speaker="host",
                clip_file="clips/scene_01.mp4",
                narration=f"What would actually happen to our reality if {core_q.lower()}?",
                flow_prompt=f"Dramatic cinematic visualization of {clean_topic} in photorealistic detail with dynamic lighting, no text, no watermark",
                stock_query=f"{kw1} {kw2}",
            ),
            SceneSpec(
                index=2,
                speaker="guest",
                clip_file="clips/scene_02.mp4",
                narration="The scientific physics behind this are far more devastating than most people realize.",
                flow_prompt="Scientific cross section and macro physical forces unleashing extreme energy, no text, no watermark",
                stock_query=f"{kw1} science",
            ),
            SceneSpec(
                index=3,
                speaker="host",
                clip_file="clips/scene_03.mp4",
                narration="In less than three seconds, the cascading pressure and thermal shift would reach catastrophic levels!",
                flow_prompt="Extreme shockwave expanding across atmosphere and landscape with intense particle discharge, no text, no watermark",
                stock_query=f"{kw1} energy",
            ),
            SceneSpec(
                index=4,
                speaker="guest",
                clip_file="clips/scene_04.mp4",
                narration="Fundamental molecular equilibrium breaks down, permanently altering the surrounding environment forever.",
                flow_prompt="Microscopic atomic lattice fracturing under immense gravitational and electromagnetic forces, no text, no watermark",
                stock_query=f"{kw2} space",
            ),
            SceneSpec(
                index=5,
                speaker="host",
                clip_file="clips/scene_05.mp4",
                narration="Could human technology ever prevent an event like this? Tell us what you think below!",
                flow_prompt="Vast cosmic vista with stars shining brightly against deep nebula space, no text, no watermark",
                stock_query=f"{kw1} space",
            ),
        ],
    )


def generate_short_job(
    topic: str,
    job_id: str | None = None,
    language: str = "en",
    niche: str = "science_human_limits",
    model: str = "gemini-3.5-flash",
    num_scenes: int = 5,
    allow_fallback: bool = False,
) -> Path:
    """Call Gemini Interactions API (Free Tier) to produce a complete job.json."""
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing GEMINI_API_KEY in environment or d:\\Youtube\\.env.\n"
            "Get a 100% free key at https://aistudio.google.com/apikey and set GEMINI_API_KEY=... in .env"
        )

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=120000))
    if language == "vi":
        voice = "vi-VN-NamMinhNeural"
        voices = {"host": "vi-VN-NamMinhNeural", "guest": "vi-VN-HoaiMyNeural"}
    else:
        voice = "en-US-AndrewMultilingualNeural"
        voices = {"host": "en-US-AndrewMultilingualNeural", "guest": "en-US-AvaMultilingualNeural"}

    prompt = f"""Design a high-retention viral YouTube Short about: "{topic}"
Target language: {language} (use natural spoken {language} for narration, title, description; keep flow_prompt and stock_query in English).
Niche: {niche}
Scene count: exactly {num_scenes} scenes.

Retention, Host/Guest Dialogue & Visual Clarity Rules:
1. Structure as a fast-paced Host + Expert Guest conversation: alternate `speaker` naturally (e.g. Scene 1="host" hook, Scene 2="guest" scientific reveal, Scene 3="host" escalation, Scene 4="guest" mind-blowing consequence, Scene 5="host" payoff/CTA).
2. Scene 1 MUST be an instant 2-3 second pattern-interrupt Hook that creates an open curiosity loop.
3. Keep total spoken narration brisk (~75-110 words total, ~30-45 seconds) with zero filler.
4. `flow_prompt` MUST depict the vivid scientific phenomenon, 3D anatomy, cosmic event, or dramatic visual subject directly (do NOT put podcast microphones or studio hosts in `flow_prompt`, because the Host & Guest appear in a dedicated split-screen presenter panel below). Maintain consistent color palette and lighting from `character_setting_bible`, with sharp focus, high-contrast rim lighting, and end each `flow_prompt` with `no text, no watermark`.
5. Set `clip_file` to `clips/scene_01.mp4` ... `clips/scene_{num_scenes:02d}.mp4`.
6. Final scene must deliver a payoff and lead into a comment-driving CTA in `description`.
7. Use `voice` = "{voice}", `voices` = {json.dumps(voices)}, and `voice_rate` = "+6%".
8. NEVER use generic AI clichés ("In today's video", "Have you ever wondered", "Buckle up", "cascading pressure and thermal shift", "fundamental molecular equilibrium breaks down"). Cite concrete physical mechanisms and numbers in `source_citation`."""

    import concurrent.futures

    interaction = None
    last_exc: Exception | None = None
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            client.interactions.create,
            model=model,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": ShortJobSpec.model_json_schema(),
            },
        )
        interaction = future.result(timeout=120.0)
    except Exception as exc:  # noqa: BLE001
        last_exc = exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if interaction is None:
        if not allow_fallback:
            raise RuntimeError(
                f"GEMINI_UNAVAILABLE ({repr(last_exc)}): Generic fallback is blocked by Dufkon QC policy."
            )
        print(f"[Warn] Gemini API models unavailable ({repr(last_exc)}). Using explicit --allow-fallback...")
        spec = build_fallback_job_spec(topic=topic, niche=niche, language=language, num_scenes=num_scenes)
    else:
        spec = ShortJobSpec.model_validate_json(interaction.output_text)

    resolved_id = job_id or slugify(topic)
    job_dir = REPO_ROOT / "jobs" / resolved_id
    (job_dir / "clips").mkdir(parents=True, exist_ok=True)
    job_path = job_dir / "job.json"

    payload = {"id": resolved_id, **spec.model_dump()}
    payload["voice"] = voice
    payload["voices"] = voices
    payload["voice_rate"] = "+6%"
    job_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return job_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a viral YouTube Short job.json via Gemini Free Tier.")
    parser.add_argument("--topic", type=str, required=True, help="Short topic or hook idea")
    parser.add_argument("--job-id", type=str, default=None, help="Optional folder name under jobs/")
    parser.add_argument("--language", choices=["en", "vi"], default="en")
    parser.add_argument("--niche", type=str, default="science_human_limits")
    parser.add_argument("--model", type=str, default="gemini-3.5-flash")
    parser.add_argument("--scenes", type=int, default=5)
    parser.add_argument("--allow-fallback", action="store_true", help="Allow structured fallback only for offline testing")
    args = parser.parse_args()

    out_path = generate_short_job(
        topic=args.topic,
        job_id=args.job_id,
        language=args.language,
        niche=args.niche,
        model=args.model,
        num_scenes=args.scenes,
        allow_fallback=args.allow_fallback,
    )
    print(f"Generated job spec: {out_path}")


if __name__ == "__main__":
    main()
