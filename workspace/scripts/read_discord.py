#!/usr/bin/env python3
"""
Read messages from Discord channels for AutoTrader analysis.

Usage:
  python scripts/read_discord.py --channel trades
  python scripts/read_discord.py --channel cycles --limit 100
  python scripts/read_discord.py --channel dashboard
  python scripts/read_discord.py --channel 1474503672951079024 --format json
  python scripts/read_discord.py --channel trades --before 1234567890123456789

Channels: trades, cycles, dashboard, charts, or a raw channel ID.
"""
import argparse
import io
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows so emoji and box chars don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Allow running from workspace root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CHANNEL_ALIASES = {
    "trades":    "1474503672951079024",
    "cycles":    "1474503699903680756",
    "dashboard": "1474505225866969098",
    "charts":    "1474502611393581267",
    "primary":   "1474502611393581267",
}

BASE = "https://discord.com/api/v10"


def _load_env():
    """Load .env from workspace or project root if token not set."""
    if os.environ.get("DISCORD_BOT_TOKEN"):
        return
    for env_path in [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
    ]:
        if env_path.exists() and env_path.stat().st_size > 0:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            break


def _headers():
    _load_env()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("ERROR: DISCORD_BOT_TOKEN not set. Add it to .env or export it.", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (AutoTrader, 1.0)",
    }


def fetch_messages(channel_id: str, limit: int = 50, before: str = None) -> list:
    """Fetch up to `limit` messages from a channel (newest first from Discord)."""
    headers = _headers()
    url = f"{BASE}/channels/{channel_id}/messages?limit={min(limit, 100)}"
    if before:
        url += f"&before={before}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.fp.read().decode() if e.fp else ""
        except Exception:
            pass
        print(f"ERROR: Discord API returned {e.code}: {body[:300]}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_all(channel_id: str, limit: int) -> list:
    """Fetch up to `limit` messages, paginating if needed (max 100 per request)."""
    messages = []
    before = None
    remaining = limit

    while remaining > 0:
        batch = fetch_messages(channel_id, min(remaining, 100), before)
        if not batch:
            break
        messages.extend(batch)
        remaining -= len(batch)
        if len(batch) < 100:
            break  # No more pages
        before = batch[-1]["id"]  # Oldest in this batch

    return messages


def format_timestamp(ts_str: str) -> str:
    """Convert Discord ISO timestamp to a readable local-ish string."""
    try:
        dt = datetime.fromisoformat(ts_str.rstrip("Z").replace("+00:00", ""))
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ts_str


def print_messages(messages: list, fmt: str):
    """Print messages in the requested format (chronological order)."""
    # Discord returns newest first; reverse for chronological display
    ordered = list(reversed(messages))

    if fmt == "json":
        # Compact but readable JSON with key fields
        out = []
        for m in ordered:
            out.append({
                "id": m.get("id"),
                "timestamp": m.get("timestamp"),
                "author": m.get("author", {}).get("username", "unknown"),
                "content": m.get("content", ""),
                "attachments": [a.get("url") for a in m.get("attachments", [])],
            })
        print(json.dumps(out, indent=2))
        return

    # Human-readable text format
    sep = "-" * 60
    for m in ordered:
        ts = format_timestamp(m.get("timestamp", ""))
        author = m.get("author", {}).get("username", "unknown")
        content = m.get("content", "").strip()
        attachments = m.get("attachments", [])

        print(sep)
        print(f"[{ts}] {author}")
        if content:
            print(content)
        for att in attachments:
            print(f"  [attachment: {att.get('filename', '?')} — {att.get('url', '')}]")
    if ordered:
        print(sep)
    print(f"\n{len(ordered)} message(s) shown.")


def main():
    parser = argparse.ArgumentParser(
        description="Read Discord channel messages for AutoTrader analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--channel", "-c",
        default="trades",
        help="Channel name (trades/cycles/dashboard/charts/primary) or raw channel ID. Default: trades",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=50,
        help="Max messages to fetch (default: 50, max: 500)",
    )
    parser.add_argument(
        "--before",
        default=None,
        help="Fetch messages before this message ID (for pagination)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json",
    )
    parser.add_argument(
        "--list-channels",
        action="store_true",
        help="List known channel aliases and exit",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Save JSON output to file instead of printing",
    )

    args = parser.parse_args()

    if args.list_channels:
        print("Known channel aliases:")
        for alias, cid in CHANNEL_ALIASES.items():
            print(f"  {alias:12s} → {cid}")
        return

    # Resolve channel
    channel_id = CHANNEL_ALIASES.get(args.channel, args.channel)
    if not channel_id.isdigit():
        print(f"ERROR: Unknown channel '{args.channel}'. Use --list-channels to see options.", file=sys.stderr)
        sys.exit(1)

    limit = max(1, min(args.limit, 500))

    if args.format == "text":
        alias_display = args.channel if args.channel != channel_id else channel_id
        print(f"Fetching up to {limit} messages from #{alias_display} ({channel_id})...\n")

    messages = fetch_all(channel_id, limit)

    if not messages:
        print("No messages found.")
        return

    if args.output:
        # Save compact JSON with key fields for analysis
        out_data = []
        for m in list(reversed(messages)):
            out_data.append({
                "id": m.get("id"),
                "timestamp": m.get("timestamp"),
                "author": m.get("author", {}).get("username", "unknown"),
                "content": m.get("content", ""),
                "attachments": [a.get("url") for a in m.get("attachments", [])],
            })
        Path(args.output).write_text(json.dumps(out_data, indent=2), encoding="utf-8")
        print(f"Saved {len(out_data)} messages to {args.output}", file=sys.stderr)
    else:
        print_messages(messages, args.format)


if __name__ == "__main__":
    main()
