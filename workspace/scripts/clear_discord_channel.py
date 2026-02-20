#!/usr/bin/env python3
"""
Delete ALL messages from the AutoTrader Discord channel.
Uses DISCORD_BOT_TOKEN from .env.

Required bot permissions: View Channel, Read Message History, Manage Messages.
Re-invite the bot with these permissions if you get 403.

Usage:
  python scripts/clear_discord_channel.py
  # Or with explicit channel:
  CHANNEL_ID=123456 python scripts/clear_discord_channel.py
"""
import os
import sys
import time
from pathlib import Path

# Load .env from repo root
repo_root = Path(__file__).resolve().parents[2]
env_file = repo_root / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

CHANNEL_ID = os.environ.get("CHANNEL_ID", "1474502611393581267")
GUILD_ID = os.environ.get("GUILD_ID", "1473759045197500516")
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

if not TOKEN:
    print("Error: DISCORD_BOT_TOKEN not set. Add it to .env or set the env var.", file=sys.stderr)
    sys.exit(1)

BASE = "https://discord.com/api/v10"
HEADERS = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}


def get_messages(before=None):
    import urllib.request
    import json
    url = f"{BASE}/channels/{CHANNEL_ID}/messages?limit=100"
    if before:
        url += f"&before={before}"
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            if e.fp:
                body = e.fp.read().decode()
        except Exception:
            pass
        try:
            err = json.loads(body) if body else {}
            msg = err.get("message", body or str(e))
            code = err.get("code", "")
            raise RuntimeError(f"Discord API {e.code}: {msg} (code {code})") from e
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError(f"Discord API {e.code}: {body or str(e)}") from e


def delete_message(msg_id):
    import urllib.request
    url = f"{BASE}/channels/{CHANNEL_ID}/messages/{msg_id}"
    req = urllib.request.Request(url, method="DELETE", headers=HEADERS)
    with urllib.request.urlopen(req):
        pass


def bulk_delete(msg_ids):
    import urllib.request
    import json
    url = f"{BASE}/channels/{CHANNEL_ID}/messages/bulk-delete"
    data = json.dumps({"messages": msg_ids}).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req):
        pass


def main():
    from datetime import datetime, timezone

    print(f"Fetching messages from channel {CHANNEL_ID}...")
    all_msgs = []
    before = None
    while True:
        try:
            msgs = get_messages(before=before)
        except Exception as e:
            err_body = ""
            if hasattr(e, "read") and callable(getattr(e, "read", None)):
                try:
                    err_body = e.read().decode()
                except Exception:
                    pass
            print(f"Error fetching: {e}", file=sys.stderr)
            if err_body:
                print(err_body, file=sys.stderr)
            sys.exit(1)
        if not msgs:
            break
        all_msgs.extend(msgs)
        before = msgs[-1]["id"]
        print(f"  Fetched {len(all_msgs)} messages so far...")
        if len(msgs) < 100:
            break
        time.sleep(0.5)  # Rate limit

    if not all_msgs:
        print("Channel is already empty.")
        return

    # Discord bulk-delete only works for messages < 14 days old
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - (14 * 24 * 3600)
    bulk_ids = []
    individual_ids = []
    for m in all_msgs:
        ts = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).timestamp()
        if ts > cutoff:
            bulk_ids.append(m["id"])
        else:
            individual_ids.append(m["id"])

    print(f"\nDeleting {len(all_msgs)} messages ({len(bulk_ids)} bulk, {len(individual_ids)} individual)...")

    deleted = 0
    for i in range(0, len(bulk_ids), 100):
        batch = bulk_ids[i : i + 100]
        try:
            bulk_delete(batch)
            deleted += len(batch)
            print(f"  Bulk deleted {deleted}/{len(all_msgs)}")
        except Exception as e:
            print(f"  Bulk failed, falling back to individual: {e}", file=sys.stderr)
            for mid in batch:
                try:
                    delete_message(mid)
                    deleted += 1
                except Exception as e2:
                    print(f"  Failed {mid}: {e2}", file=sys.stderr)
                time.sleep(0.25)
        time.sleep(1.1)  # Rate limit

    for mid in individual_ids:
        try:
            delete_message(mid)
            deleted += 1
            if deleted % 50 == 0:
                print(f"  Deleted {deleted}/{len(all_msgs)}")
        except Exception as e:
            print(f"  Failed {mid}: {e}", file=sys.stderr)
        time.sleep(0.25)

    print(f"\nDone. Deleted {deleted} messages.")


if __name__ == "__main__":
    main()
