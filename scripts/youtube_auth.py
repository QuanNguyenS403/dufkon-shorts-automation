"""OAuth 2.0 authentication and channel-lock verification for YouTube Data API v3."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent.parent
POLICY_PATH = BASE_DIR / "config" / "channel_policy.json"
DEFAULT_CLIENT_SECRETS = BASE_DIR / "secrets" / "client_secrets.json"
DEFAULT_TOKEN_PATH = BASE_DIR / "secrets" / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def load_policy(policy_path: Path = POLICY_PATH) -> dict[str, Any]:
    """Load channel policy configuration."""
    with policy_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_policy(policy: dict[str, Any], policy_path: Path = POLICY_PATH) -> None:
    """Persist updated channel policy configuration."""
    with policy_path.open("w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2, ensure_ascii=False)
        f.write("\n")


def get_credentials(
    client_secrets_path: Path = DEFAULT_CLIENT_SECRETS,
    token_path: Path = DEFAULT_TOKEN_PATH,
) -> Credentials:
    """Load cached OAuth credentials or run local browser OAuth flow."""
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if os.getenv("CI", "").lower() == "true":
            raise RuntimeError(
                "Missing or invalid YouTube OAuth refresh token in CI environment. "
                "Refresh secrets/token.json locally and update YOUTUBE_TOKEN_JSON secret."
            )
        if not client_secrets_path.exists():
            raise FileNotFoundError(
                f"Missing OAuth client secrets at {client_secrets_path}. "
                "Download Desktop App OAuth JSON from Google Cloud Console and save it there."
            )
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise ImportError(
                "Missing 'google-auth-oauthlib'. Install with: pip install -r requirements.txt"
            ) from exc

        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_authenticated_youtube_service(
    client_secrets_path: Path = DEFAULT_CLIENT_SECRETS,
    token_path: Path = DEFAULT_TOKEN_PATH,
    verify_lock: bool = True,
) -> tuple[Any, dict[str, Any]]:
    """Build YouTube API client and verify the authenticated channel matches policy."""
    creds = get_credentials(client_secrets_path=client_secrets_path, token_path=token_path)
    youtube = build("youtube", "v3", credentials=creds)

    response = youtube.channels().list(part="snippet,statistics,status", mine=True).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError(
            "Authenticated Google account has no YouTube channel yet. "
            "Create a channel at https://www.youtube.com/create_channel first."
        )

    channel = items[0]
    channel_id = channel["id"]
    channel_title = channel.get("snippet", {}).get("title", "")

    if verify_lock:
        policy = load_policy()
        lock = policy.get("account_lock", {})
        expected_id = lock.get("channel_id", "")
        if lock.get("enforce_channel_id_match") and expected_id and channel_id != expected_id:
            raise PermissionError(
                f"Channel lock mismatch: authenticated '{channel_title}' ({channel_id}), "
                f"but policy requires '{lock.get('channel_title')}' ({expected_id})."
            )

    return youtube, channel


def main() -> None:
    parser = argparse.ArgumentParser(description="Authenticate and verify YouTube channel lock.")
    parser.add_argument(
        "--bind-channel",
        action="store_true",
        help="Lock config/channel_policy.json to the currently authenticated YouTube channel.",
    )
    args = parser.parse_args()

    _, channel = get_authenticated_youtube_service(verify_lock=not args.bind_channel)
    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    status = channel.get("status", {})

    print(f"Channel ID   : {channel['id']}")
    print(f"Channel Title: {snippet.get('title', '')}")
    print(f"Custom URL   : {snippet.get('customUrl', '')}")
    print(f"Subscribers  : {stats.get('subscriberCount', '0')}")
    print(f"Videos       : {stats.get('videoCount', '0')}")
    print(f"Long Uploads : {status.get('longUploadsStatus', 'unknown')}")

    if args.bind_channel:
        policy = load_policy()
        policy["account_lock"]["channel_id"] = channel["id"]
        policy["account_lock"]["channel_title"] = snippet.get("title", "")
        policy["account_lock"]["enforce_channel_id_match"] = True
        save_policy(policy)
        print("Locked channel_policy.json to this channel.")


if __name__ == "__main__":
    main()
