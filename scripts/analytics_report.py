"""Fetch channel and recent video performance metrics via YouTube Data API v3 (readonly)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from youtube_auth import get_authenticated_youtube_service  # noqa: E402


def print_channel_report(max_videos: int = 10) -> None:
    """Print channel overview and recent uploaded videos' statistics."""
    youtube, channel = get_authenticated_youtube_service(verify_lock=True)
    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})

    print(f"=== CHANNEL: {snippet.get('title', '')} ({channel['id']}) ===")
    print(
        f"Subscribers: {stats.get('subscriberCount', '0')} | "
        f"Total Views: {stats.get('viewCount', '0')} | "
        f"Videos: {stats.get('videoCount', '0')}\n"
    )

    search_resp = youtube.search().list(
        part="id",
        forMine=True,
        type="video",
        order="date",
        maxResults=max_videos,
    ).execute()
    video_ids = [item["id"]["videoId"] for item in search_resp.get("items", []) if item.get("id", {}).get("videoId")]
    if not video_ids:
        print("No uploaded videos found on this channel yet.")
        return

    videos_resp = youtube.videos().list(
        part="snippet,statistics,status,contentDetails",
        id=",".join(video_ids),
    ).execute()

    for v in videos_resp.get("items", []):
        v_snip = v.get("snippet", {})
        v_stat = v.get("statistics", {})
        v_status = v.get("status", {})
        pub_at = v_status.get("publishAt") or v_snip.get("publishedAt", "")
        print(
            f"- {v['id']} | {v_status.get('privacyStatus', '')} | {pub_at}\n"
            f"  Title   : {v_snip.get('title', '')}\n"
            f"  Metrics : views={v_stat.get('viewCount', 0)}, likes={v_stat.get('likeCount', 0)}, "
            f"comments={v_stat.get('commentCount', 0)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Show YouTube channel and recent video analytics.")
    parser.add_argument("--max-videos", type=int, default=10, help="Number of recent videos to display")
    args = parser.parse_args()
    print_channel_report(max_videos=args.max_videos)


if __name__ == "__main__":
    main()
