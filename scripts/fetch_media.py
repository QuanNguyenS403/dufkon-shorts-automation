"""Fetch free vertical B-roll (NASA & Wikimedia zero-key + Pexels & Pixabay free-key) for missing scenes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
import subprocess

HTTP_HEADERS = {"User-Agent": "YoutubeShortsAutomation/1.0 (https://dufkon.com; contact@dufkon.com)"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}


def _is_valid_media(file_path: Path) -> bool:
    if not file_path.exists() or file_path.stat().st_size < 1024:
        return False
    if file_path.suffix.lower() in VIDEO_EXTS:
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return res.returncode == 0 and float(res.stdout.strip()) > 0
        except Exception:
            return False
    return True


def _existing_media(job_dir: Path, clip_rel: str) -> Path | None:
    candidate = job_dir / clip_rel
    if _is_valid_media(candidate):
        return candidate
    stem = candidate.with_suffix("")
    for ext in (*VIDEO_EXTS, *IMAGE_EXTS):
        alt = stem.with_suffix(ext)
        if _is_valid_media(alt):
            return alt
    return None


def _download_file(url: str, dst_path: Path, headers: dict[str, str] | None = None) -> Path:
    import urllib.parse

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    safe_url = urllib.parse.quote(url, safe=":/%?=&")
    with requests.get(safe_url, headers=headers or HTTP_HEADERS, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with dst_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=262144):
                if chunk:
                    f.write(chunk)
    return dst_path


def search_pexels(query: str, api_key: str) -> tuple[str, str] | None:
    """Return (media_url, ext) from Pexels portrait video or photo search."""
    headers = {"Authorization": api_key, **HTTP_HEADERS}
    v_resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers=headers,
        params={"query": query, "orientation": "portrait", "per_page": 5},
        timeout=15,
    )
    if v_resp.ok:
        for video in v_resp.json().get("videos", []):
            files = sorted(
                video.get("video_files", []),
                key=lambda x: abs(int(x.get("height", 0)) - 1920),
            )
            for vf in files:
                if vf.get("file_type") == "video/mp4" and vf.get("link"):
                    return str(vf["link"]), ".mp4"
    p_resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers=headers,
        params={"query": query, "orientation": "portrait", "per_page": 3},
        timeout=15,
    )
    if p_resp.ok:
        for photo in p_resp.json().get("photos", []):
            src = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("original")
            if src:
                return str(src), ".jpg"
    return None


def search_pixabay(query: str, api_key: str) -> tuple[str, str] | None:
    """Return (media_url, ext) from Pixabay free video or photo search."""
    v_resp = requests.get(
        "https://pixabay.com/api/videos/",
        headers=HTTP_HEADERS,
        params={"key": api_key, "q": query, "per_page": 5},
        timeout=15,
    )
    if v_resp.ok:
        for hit in v_resp.json().get("hits", []):
            videos = hit.get("videos", {})
            for tier in ("medium", "large", "small"):
                url = videos.get(tier, {}).get("url")
                if url:
                    return str(url), ".mp4"
    p_resp = requests.get(
        "https://pixabay.com/api/",
        headers=HTTP_HEADERS,
        params={"key": api_key, "q": query, "image_type": "photo", "orientation": "vertical", "per_page": 5},
        timeout=15,
    )
    if p_resp.ok:
        for hit in p_resp.json().get("hits", []):
            url = hit.get("largeImageURL")
            if url:
                return str(url), ".jpg"
    return None


def search_nasa(query: str) -> tuple[str, str] | None:
    """Return (media_url, ext) from NASA Image and Video Library (zero API key)."""
    for media_type in ("video", "image"):
        resp = requests.get(
            "https://images-api.nasa.gov/search",
            headers=HTTP_HEADERS,
            params={"q": query, "media_type": media_type, "page_size": 5},
            timeout=15,
        )
        if not resp.ok:
            continue
        items = resp.json().get("collection", {}).get("items", [])
        for item in items:
            href = item.get("href")
            if not href:
                continue
            manifest = requests.get(href, headers=HTTP_HEADERS, timeout=15)
            if not manifest.ok:
                continue
            urls = manifest.json()
            if media_type == "video":
                mp4 = (
                    next((u for u in urls if isinstance(u, str) and "~small.mp4" in u.lower()), None)
                    or next((u for u in urls if isinstance(u, str) and "~mobile.mp4" in u.lower()), None)
                    or next((u for u in urls if isinstance(u, str) and "~medium.mp4" in u.lower()), None)
                    or next((u for u in urls if isinstance(u, str) and "~large.mp4" in u.lower()), None)
                    or next((u for u in urls if isinstance(u, str) and u.lower().endswith(".mp4")), None)
                )
                if mp4:
                    try:
                        import urllib.parse

                        safe_u = urllib.parse.quote(mp4, safe=":/%?=&")
                        h = requests.head(safe_u, headers=HTTP_HEADERS, allow_redirects=True, timeout=5)
                        cl = int(h.headers.get("content-length", 0))
                        if cl > 65_000_000:
                            continue
                    except Exception:
                        pass
                    return mp4, ".mp4"
            else:
                img = next(
                    (u for u in urls if isinstance(u, str) and "~orig" in u and u.lower().endswith((".jpg", ".png"))),
                    None,
                ) or next((u for u in urls if isinstance(u, str) and u.lower().endswith((".jpg", ".png"))), None)
                if img:
                    ext = ".png" if img.lower().endswith(".png") else ".jpg"
                    return img, ext
    return None


def search_wikimedia(query: str) -> tuple[str, str] | None:
    """Return (media_url, ext) from Wikimedia Commons API (zero API key)."""
    resp = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        headers=HTTP_HEADERS,
        params={
            "action": "query",
            "generator": "search",
            "gsrnamespace": 6,
            "gsrsearch": query,
            "gsrlimit": 8,
            "prop": "imageinfo",
            "iiprop": "url|mime|size",
            "format": "json",
        },
        timeout=15,
    )
    if not resp.ok:
        return None
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = str(info.get("mime", ""))
        url = str(info.get("url", ""))
        if mime in ("image/jpeg", "image/png") and url:
            return url, ".png" if mime == "image/png" else ".jpg"
    return None


def derive_query(scene: dict[str, Any]) -> str:
    """Choose explicit stock_query or derive concise keywords from narration."""
    if scene.get("stock_query"):
        return str(scene["stock_query"]).strip()
    words = [w.strip(".,!?;:\"'—") for w in str(scene.get("narration", "")).split()]
    keywords = [w for w in words if len(w) > 3][:4]
    return " ".join(keywords) or "outer space astronaut"


def fetch_missing_media(
    job_path: Path,
    source: str = "auto",
    overwrite: bool = False,
) -> list[Path]:
    """Fetch free media into missing clips/scene_XX.* targets for a job."""
    load_dotenv(REPO_ROOT / ".env")
    pexels_key = os.getenv("PEXELS_API_KEY", "").strip()
    pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()

    job_dir = job_path.parent
    job = json.loads(job_path.read_text(encoding="utf-8"))
    downloaded: list[Path] = []

    for scene in job.get("scenes", []):
        rel = str(scene["clip_file"])
        existing = _existing_media(job_dir, rel)
        if existing and not overwrite:
            print(f"[Scene {scene['index']}] Keep existing: {existing}")
            continue

        query = derive_query(scene)
        result: tuple[str, str] | None = None
        used_source = ""
        matched_query = query

        order = (
            [source]
            if source != "auto"
            else ["pexels", "pixabay", "nasa", "wikimedia"]
        )

        # Multi-tier query relaxation so no scene is ever left without media
        query_candidates = [query]
        words = [w.strip() for w in query.split() if len(w.strip()) > 2]
        if len(words) > 2:
            query_candidates.append(" ".join(words[:2]))
        job_topic = str(job.get("title", "")).lower()
        if job_topic:
            topic_words = [w for w in job_topic.split() if len(w) > 3 and w not in ("what", "happens", "when", "your", "does", "with")][:3]
            if topic_words:
                query_candidates.append(" ".join(topic_words))
        query_candidates.extend(["deep space galaxy", "universe cosmos", "astronomy space"])

        for candidate_q in query_candidates:
            for src in order:
                if src == "pexels" and pexels_key:
                    result = search_pexels(candidate_q, pexels_key)
                elif src == "pixabay" and pixabay_key:
                    result = search_pixabay(candidate_q, pixabay_key)
                elif src == "nasa":
                    result = search_nasa(candidate_q)
                elif src == "wikimedia":
                    result = search_wikimedia(candidate_q)
                if result:
                    used_source = src
                    matched_query = candidate_q
                    break
            if result:
                break

        if not result:
            print(f"[Scene {scene['index']}] No free match for queries: {query_candidates[:2]}")
            continue

        url, ext = result
        dst = (job_dir / rel).with_suffix(ext)
        _download_file(url, dst)
        print(f"[Scene {scene['index']}] Downloaded from {used_source} (q='{matched_query}') -> {dst}")
        downloaded.append(dst)

    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch free stock/public-domain media for missing Short scenes.")
    parser.add_argument("--job", type=Path, required=True, help="Path to job.json")
    parser.add_argument(
        "--source",
        choices=["auto", "pexels", "pixabay", "nasa", "wikimedia"],
        default="auto",
        help="Preferred free media source",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing scene clips")
    args = parser.parse_args()

    fetch_missing_media(args.job.resolve(), source=args.source, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
