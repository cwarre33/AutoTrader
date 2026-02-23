#!/usr/bin/env python3
"""
Delete malformed messages from Discord channels.

Targets messages with raw JSON/agent output bugs like [{'type':'text','text':'...'}].
Uses DISCORD_BOT_TOKEN from .env. Requires Manage Messages permission.

Usage:
  python scripts/cleanup_discord_malformed.py --dry-run   # List only, no delete
  python scripts/cleanup_discord_malformed.py            # Delete malformed messages
  python scripts/cleanup_discord_malformed.py --channel trades --limit 200
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env
for env_path in [
    Path(__file__).resolve().parent.parent / ".env",
    Path(__file__).resolve().parent.parent.parent / ".env",
]:
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break

from scripts.read_discord import CHANNEL_ALIASES, fetch_all, _load_env

BASE = "https://discord.com/api/v10"


def is_malformed(content: str) -> bool:
    """Check if message has raw JSON / malformed agent output."""
    if not content or not content.strip():
        return False
    if content.strip().startswith("[{"):
        return True
    if "'type': 'text'" in content:
        return True
    if content and '{"type' in content[:30]:
        return True
    return False


def delete_message(channel_id: str, message_id: str, headers: dict) -> bool:
    import urllib.request
    import urllib.error
    url = f"{BASE}/channels/{channel_id}/messages/{message_id}"
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except urllib.error.HTTPError as e:
        print(f"  Failed to delete {message_id}: {e.code}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", "-c", default="trades", help="Channel to clean (trades/cycles/primary)")
    parser.add_argument("--limit", "-n", type=int, default=200, help="Messages to scan")
    parser.add_argument("--dry-run", action="store_true", help="List only, do not delete")
    args = parser.parse_args()

    _load_env()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("ERROR: DISCORD_BOT_TOKEN not set.", file=sys.stderr)
        sys.exit(1)

    channel_id = CHANNEL_ALIASES.get(args.channel, args.channel)
    if not channel_id.isdigit():
        print(f"ERROR: Unknown channel '{args.channel}'", file=sys.stderr)
        sys.exit(1)

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (AutoTrader, 1.0)",
    }

    print(f"Fetching up to {args.limit} messages from #{args.channel}...", file=sys.stderr)
    msgs = fetch_all(channel_id, args.limit)

    malformed = []
    for m in msgs:
        content = m.get("content", "")
        if is_malformed(content):
            malformed.append(m)

    print(f"Found {len(malformed)} malformed messages.", file=sys.stderr)
    if not malformed:
        return

    for m in malformed:
        preview = (m.get("content", "") or "")[:60].replace("\n", " ")
        print(f"  {m.get('id')}  {m.get('timestamp', '')[:19]}  {preview}...")

    if args.dry_run:
        print("\nDry run. Run without --dry-run to delete.", file=sys.stderr)
        return

    print(f"\nDeleting {len(malformed)} messages...", file=sys.stderr)
    deleted = 0
    for m in malformed:
        if delete_message(channel_id, m["id"], headers):
            deleted += 1
        time.sleep(0.3)  # Rate limit
    print(f"Deleted {deleted} messages.", file=sys.stderr)


if __name__ == "__main__":
    main()
