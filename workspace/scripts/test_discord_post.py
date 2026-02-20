#!/usr/bin/env python3
"""Quick test: can we post to Discord? Run from repo root or workspace."""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Ensure we can import lib
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env if present (check cwd, workspace, repo root)
base = Path(__file__).resolve()
for env_path in [
    Path.cwd() / ".env",
    base.parent.parent / ".env",
    base.parent.parent.parent / ".env",
]:
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
        break

token = os.environ.get("DISCORD_BOT_TOKEN")
print("Token set:", "yes" if token else "NO")
if not token:
    sys.exit(1)

# Prefer webhook if set (bypasses 403/1010)
webhook_url = os.environ.get("DISCORD_DASHBOARD_WEBHOOK_URL", "").strip()
print("Webhook URL set:", "yes" if webhook_url else "NO")
if webhook_url and "discord.com/api/webhooks/" in webhook_url:
    print("Using webhook (bypasses bot API)")
    data = json.dumps({"content": "Test — Discord webhook check"}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "DiscordBot (AutoTrader, 1.0)"}
    req = urllib.request.Request(webhook_url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read().decode())
            print("Dashboard update: OK (webhook)")
            sys.exit(0)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.fp.read().decode() if e.fp else ""
        except Exception:
            pass
        try:
            err = json.loads(body) if body else {}
        except json.JSONDecodeError:
            err = {"raw": body[:300]}
        print("Dashboard update: FAILED (webhook)", e.code)
        print("Response:", err)
        sys.exit(1)

# Fallback: bot API
channel_id = "1474505225866969098"
url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
data = json.dumps({"content": "Test — Discord API check"}).encode()
req = urllib.request.Request(url, data=data, headers=headers, method="POST")
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        out = json.loads(r.read().decode())
        print("Dashboard update: OK (bot API)")
        print("Message ID:", out.get("id"))
        sys.exit(0)
except urllib.error.HTTPError as e:
    body = ""
    try:
        body = e.fp.read().decode() if e.fp else ""
    except Exception:
        pass
    try:
        err = json.loads(body) if body else {}
    except json.JSONDecodeError:
        err = {"raw": body[:500]}
    print("Dashboard update: FAILED")
    print("HTTP", e.code, err.get("message", err.get("raw", body)))
    print("Discord error code:", err.get("code", "?"))
    if err.get("code") == 50001:
        print("→ 50001 = Missing Access: bot may not be in the channel's server")
    elif err.get("code") == 50013:
        print("→ 50013 = Missing Permissions: check Send Messages, View Channel")
    elif err.get("code") == 10003:
        print("→ 10003 = Unknown Channel: wrong channel ID or bot has no access")
    sys.exit(1)
except Exception as e:
    print("Dashboard update: FAILED")
    print("Error:", e)
    sys.exit(1)
