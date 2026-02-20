"""Post messages to Discord channels via bot token. Uses DISCORD_BOT_TOKEN."""
import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path

logger = logging.getLogger("autotrader.discord")

TRADES_CHANNEL_ID = os.environ.get("DISCORD_TRADES_CHANNEL_ID", "1474503672951079024")
CYCLES_CHANNEL_ID = os.environ.get("DISCORD_CYCLES_CHANNEL_ID", "1474503699903680756")
DASHBOARD_CHANNEL_ID = os.environ.get("DISCORD_DASHBOARD_CHANNEL_ID", "1474505225866969098")
DASHBOARD_WEBHOOK_URL = os.environ.get("DISCORD_DASHBOARD_WEBHOOK_URL", "")
TRADES_WEBHOOK_URL = os.environ.get("DISCORD_TRADES_WEBHOOK_URL", "")
BASE = "https://discord.com/api/v10"
DASHBOARD_STATE_FILE = Path(__file__).resolve().parent.parent / "config" / "dashboard_message_id.json"

# Load .env if token missing (cron subprocess may not inherit env)
def _ensure_env():
    if os.environ.get("DISCORD_BOT_TOKEN"):
        return
    for env_path in [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            break


def _headers():
    _ensure_env()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        return None
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (AutoTrader, 1.0)",
    }


def _post(channel_id: str, content: str) -> bool:
    """Post a message to a Discord channel. Returns True on success."""
    headers = _headers()
    if not headers:
        logger.warning("Discord: no token, skipping post to %s", channel_id)
        return False
    url = f"{BASE}/channels/{channel_id}/messages"
    data = json.dumps({"content": content[:2000]}).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except urllib.error.HTTPError as e:
        try:
            body = e.fp.read().decode() if e.fp else ""
        except Exception:
            body = ""
        logger.warning("Discord post failed to %s: %s %s", channel_id, e.code, body[:200])
        return False
    except Exception as e:
        logger.warning("Discord post failed to %s: %s", channel_id, e)
        return False


def _post_and_get_id(channel_id: str, content: str):
    """Post a message and return its ID, or None on failure."""
    headers = _headers()
    if not headers:
        return None
    url = f"{BASE}/channels/{channel_id}/messages"
    data = json.dumps({"content": content[:2000]}).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read().decode())
            return out.get("id")
    except urllib.error.HTTPError as e:
        try:
            body = e.fp.read().decode() if e.fp else ""
        except Exception:
            body = ""
        try:
            err = json.loads(body) if body else {}
        except json.JSONDecodeError:
            err = {"raw": body[:200]}
        logger.warning("Discord post (get id) failed to %s: %s %s", channel_id, e.code, err)
        return None
    except Exception as e:
        logger.warning("Discord post (get id) failed to %s: %s", channel_id, e)
        return None


def _edit(channel_id: str, message_id: str, content: str) -> bool:
    """Edit an existing message. Returns True on success."""
    headers = _headers()
    if not headers:
        return False
    url = f"{BASE}/channels/{channel_id}/messages/{message_id}"
    data = json.dumps({"content": content[:2000]}).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception as e:
        logger.warning("Discord edit failed %s/%s: %s", channel_id, message_id, e)
        return False


def post_trades(trades_text: str) -> bool:
    """Post trade execution summary. Prefers webhook if set."""
    _ensure_env()
    if TRADES_WEBHOOK_URL:
        return _webhook_post(TRADES_WEBHOOK_URL, trades_text) is not None
    return _post(TRADES_CHANNEL_ID, trades_text)


def post_cycles(cycles_text: str) -> bool:
    """Post cycle summary to the cycles channel."""
    return _post(CYCLES_CHANNEL_ID, cycles_text)


# Discord/Cloudflare blocks Python's default urllib User-Agent (Python-urllib/x.x)
_WEBHOOK_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "DiscordBot (AutoTrader, 1.0)",
}


def _webhook_post(webhook_url: str, content: str):
    """Post via webhook (bypasses bot API, avoids Cloudflare 1010)."""
    if not webhook_url or "discord.com/api/webhooks/" not in webhook_url:
        return None
    data = json.dumps({"content": content[:2000]}).encode()
    req = urllib.request.Request(webhook_url, data=data, headers=_WEBHOOK_HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read().decode())
            return out.get("id")
    except Exception as e:
        logger.warning("Webhook post failed: %s", e)
        return None


def _webhook_edit(webhook_url: str, message_id: str, content: str) -> bool:
    """Edit a webhook message. URL is base without /messages/xxx."""
    if not webhook_url or "discord.com/api/webhooks/" not in webhook_url:
        return False
    url = webhook_url.rstrip("/") + f"/messages/{message_id}"
    data = json.dumps({"content": content[:2000]}).encode()
    req = urllib.request.Request(url, data=data, headers=_WEBHOOK_HEADERS, method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception as e:
        logger.warning("Webhook edit failed: %s", e)
        return False


def update_dashboard(content: str) -> bool:
    """
    Update the dashboard channel via bot API only (same path as cycles channel).
    Edits the same message each cycle so the channel stays static.
    Webhook is not used — it creates duplicate messages when bot API already works.
    """
    _ensure_env()
    channel_id = os.environ.get("DISCORD_DASHBOARD_CHANNEL_ID", DASHBOARD_CHANNEL_ID) or DASHBOARD_CHANNEL_ID

    # Bot API (same path as cycles channel)
    if not channel_id:
        logger.warning("Dashboard: no channel ID configured")
        return False
    headers = _headers()
    if not headers:
        logger.warning("Dashboard: no bot token, skipping")
        return False

    # Try to edit existing message (state file persists message_id across runs)
    # Only use msg_id from bot state (channel_id), not webhook state (bot can't edit webhook msgs)
    msg_id = None
    if DASHBOARD_STATE_FILE.exists():
        try:
            state = json.loads(DASHBOARD_STATE_FILE.read_text())
            if state.get("channel_id") == channel_id:
                msg_id = state.get("message_id")
        except Exception:
            pass
    if msg_id:
        msg_id_str = str(msg_id)
        if _edit(channel_id, msg_id_str, content):
            return True
        logger.warning("Dashboard edit failed (msg %s), posting new", msg_id_str[:20])
        try:
            DASHBOARD_STATE_FILE.unlink()
        except Exception:
            pass

    # Post new message and save its ID for next cycle
    new_id = _post_and_get_id(channel_id, content)
    if new_id:
        DASHBOARD_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        DASHBOARD_STATE_FILE.write_text(json.dumps({
            "channel_id": channel_id,
            "message_id": str(new_id),
        }, indent=2))
        return True
    logger.warning("Dashboard post to channel %s failed", channel_id)
    return False
