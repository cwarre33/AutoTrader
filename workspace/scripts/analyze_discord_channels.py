#!/usr/bin/env python3
"""
Analyze AutoTrader Discord channels for message bleeding and cleanup.

Fetches messages from all channels, classifies content types, and reports:
- Messages in wrong channels (channel merging)
- Malformed content (raw JSON, fragmented agent output)
- Duplicate or redundant messages
- Cleanup recommendations

Usage:
  python scripts/analyze_discord_channels.py
  python scripts/analyze_discord_channels.py --limit 200
  python scripts/analyze_discord_channels.py --fetch-only  # Save JSON, skip analysis
"""
import argparse
import io
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# Force UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

workspace = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(workspace))

from scripts.read_discord import CHANNEL_ALIASES, fetch_all, _load_env

# Expected content per channel
CHANNEL_PURPOSE = {
    "trades": ["trade_execution"],      # BUY/SELL only
    "cycles": ["cycle_summary"],        # 📊 equity · No trades / Sold/Bought
    "dashboard": ["dashboard"],        # Single dashboard message
    "charts": ["chart_image"],         # Portfolio chart
    "primary": ["chat", "agent"],      # Human chat, @mentions, agent replies
}

# Content type classifiers
def classify_content(content: str, author: str) -> str:
    """Classify message content type."""
    if not content or not content.strip():
        return "empty"
    # Raw JSON / malformed agent output
    if content.strip().startswith("[{") or content.strip().startswith("[{"):
        return "malformed_json"
    if "'type': 'text'" in content or (content and '{"type' in content[:30]):
        return "malformed_json"
    # Trade executions
    if re.search(r"(🔴|🔴)\s*SELL\s+\w+\s+\d+\s+shares", content):
        return "trade_execution"
    if re.search(r"(🟢|🟢)\s*BUY\s+\w+\s+\d+\s+shares", content):
        return "trade_execution"
    if re.search(r"SELL\s+\w+\s+\d+\s+shares", content):
        return "trade_execution"
    if re.search(r"BUY\s+\w+\s+\d+\s+shares", content):
        return "trade_execution"
    # Cycle summary
    if re.search(r"\$[0-9.]+[KM]\s+·\s+.*positions", content) and "No trades" in content or "Sold:" in content or "Bought:" in content:
        return "cycle_summary"
    if "No trades this cycle" in content and "Watching:" in content:
        return "cycle_summary"
    if "Sold:" in content or "Bought:" in content:
        return "cycle_summary"
    # Dashboard
    if "**📊 AutoTrader Dashboard**" in content or "**Holdings:**" in content:
        return "dashboard"
    # Chart (image attachment)
    if "📈 Portfolio equity" in content or "equity.png" in content:
        return "chart_image"
    # Exec errors
    if "Exec:" in content and "failed:" in content:
        return "exec_error"
    # Human chat
    if content.startswith("<@") or content.startswith("@"):
        return "chat"
    if author not in ("AutoTrader", "Spidey Bot") and len(content) < 500:
        return "chat"
    # Agent response (fragmented)
    if author in ("AutoTrader", "Spidey Bot") and len(content) < 100 and not re.search(r"\$[0-9]", content):
        return "agent_fragment"
    # Agent response
    if author in ("AutoTrader", "Spidey Bot") and ("I'll" in content or "I understand" in content or "Scheduled" in content):
        return "agent"
    return "unknown"


def extract_text(content: str) -> str:
    """Extract plain text from malformed JSON content."""
    if not content or not content.strip().startswith("[{"):
        return content
    try:
        data = json.loads(content)
        if isinstance(data, list):
            parts = []
            for item in data:
                if isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return " ".join(parts)
    except Exception:
        pass
    return content


def main():
    parser = argparse.ArgumentParser(description="Analyze Discord channels for message bleeding")
    parser.add_argument("--limit", "-n", type=int, default=100, help="Messages per channel (default 100)")
    parser.add_argument("--fetch-only", action="store_true", help="Only fetch and save JSON, skip analysis")
    parser.add_argument("--data-dir", default=None, help="Data dir (default: workspace/tmp/discord_analysis)")
    args = parser.parse_args()

    _load_env()
    if not os.environ.get("DISCORD_BOT_TOKEN"):
        print("ERROR: DISCORD_BOT_TOKEN not set. Add to .env", file=sys.stderr)
        sys.exit(1)

    data_dir = Path(args.data_dir) if args.data_dir else Path(__file__).resolve().parent.parent / "tmp" / "discord_analysis"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Fetch all channels
    channel_data = {}
    for alias, cid in CHANNEL_ALIASES.items():
        if alias in ("charts", "primary") and cid == CHANNEL_ALIASES.get("primary"):
            continue  # Skip duplicate
        unique = set()
        for a, i in CHANNEL_ALIASES.items():
            if i == cid:
                unique.add(a)
        key = list(unique)[0] if len(unique) == 1 else f"{cid}"
        if key in channel_data:
            continue
        print(f"Fetching {alias} ({cid})...", file=sys.stderr)
        try:
            msgs = fetch_all(cid, args.limit)
            channel_data[alias] = msgs
            out_path = data_dir / f"{alias}_msgs.json"
            out_data = [{"id": m.get("id"), "timestamp": m.get("timestamp"), "author": m.get("author", {}).get("username", "unknown"), "content": m.get("content", ""), "attachments": [a.get("url") for a in m.get("attachments", [])]} for m in reversed(msgs)]
            out_path.write_text(json.dumps(out_data, indent=2), encoding="utf-8")
            print(f"  Saved {len(out_data)} messages to {out_path.name}", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            channel_data[alias] = []

    # Fetch primary (charts and primary share ID)
    if "primary" not in channel_data:
        cid = CHANNEL_ALIASES["primary"]
        print(f"Fetching primary/charts ({cid})...", file=sys.stderr)
        try:
            msgs = fetch_all(cid, args.limit)
            channel_data["primary"] = msgs
            out_path = data_dir / "primary_msgs.json"
            out_data = [{"id": m.get("id"), "timestamp": m.get("timestamp"), "author": m.get("author", {}).get("username", "unknown"), "content": m.get("content", ""), "attachments": [a.get("url") for a in m.get("attachments", [])]} for m in reversed(msgs)]
            out_path.write_text(json.dumps(out_data, indent=2), encoding="utf-8")
            print(f"  Saved {len(out_data)} messages to {out_path.name}", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            channel_data["primary"] = []

    if args.fetch_only:
        print("\nFetch complete. Skipping analysis.", file=sys.stderr)
        return

    # Analysis
    print("\n" + "=" * 70)
    print("DISCORD CHANNEL ANALYSIS — Message Bleeding & Cleanup")
    print("=" * 70)

    issues = []
    by_channel = defaultdict(lambda: defaultdict(list))

    for channel, msgs in channel_data.items():
        expected = CHANNEL_PURPOSE.get(channel, ["unknown"])
        for m in msgs:
            content = m.get("content", "")
            author = m.get("author", {}).get("username", "unknown") if isinstance(m.get("author"), dict) else "unknown"
            ctype = classify_content(content, author)
            by_channel[channel][ctype].append({"id": m.get("id"), "ts": m.get("timestamp", "")[:19], "preview": content[:80].replace("\n", " ")})

    # Report per channel
    for channel in sorted(channel_data.keys()):
        msgs = channel_data[channel]
        print(f"\n── #{channel} ({len(msgs)} messages) ───")
        expected = set(CHANNEL_PURPOSE.get(channel, []))
        for ctype, items in sorted(by_channel[channel].items(), key=lambda x: -len(x[1])):
            pct = len(items) / len(msgs) * 100 if msgs else 0
            ok = "✓" if ctype in expected or ctype in ("trade_execution", "cycle_summary", "dashboard", "chart_image", "chat", "agent") else "✗"
            wrong = " [WRONG CHANNEL]" if ctype not in expected and ctype in ("trade_execution", "cycle_summary", "chat", "agent", "agent_fragment", "exec_error") else ""
            print(f"  {ctype:20s} {len(items):4d} ({pct:5.1f}%) {ok}{wrong}")
            if ctype == "malformed_json" and items:
                print(f"    Example: {items[0]['preview'][:60]}...")
            if ctype == "agent_fragment" and items:
                print(f"    Example: {items[0]['preview'][:60]}...")

    # Cross-channel bleeding
    print("\n" + "=" * 70)
    print("CHANNEL MERGING BLEEDING (messages in wrong channel)")
    print("=" * 70)

    bleeding = []
    if "trades" in channel_data:
        for m in channel_data["trades"]:
            content = m.get("content", "")
            author = m.get("author", {}).get("username", "?") if isinstance(m.get("author"), dict) else "?"
            ctype = classify_content(content, author)
            if ctype in ("chat", "agent", "agent_fragment", "malformed_json", "cycle_summary", "exec_error"):
                bleeding.append(("trades", ctype, m.get("id"), content[:100]))
    if "cycles" in channel_data:
        for m in channel_data["cycles"]:
            content = m.get("content", "")
            author = m.get("author", {}).get("username", "?") if isinstance(m.get("author"), dict) else "?"
            ctype = classify_content(content, author)
            if ctype in ("chat", "agent", "agent_fragment", "malformed_json", "trade_execution"):
                bleeding.append(("cycles", ctype, m.get("id"), content[:100]))
    if "primary" in channel_data:
        for m in channel_data["primary"]:
            content = m.get("content", "")
            author = m.get("author", {}).get("username", "?") if isinstance(m.get("author"), dict) else "?"
            ctype = classify_content(content, author)
            if ctype in ("trade_execution", "cycle_summary") and author in ("AutoTrader", "Spidey Bot"):
                bleeding.append(("primary", ctype, m.get("id"), content[:100]))

    if bleeding:
        for ch, ctype, mid, preview in bleeding[:30]:
            print(f"\n  #{ch} has {ctype}: {preview[:70]}...")
        if len(bleeding) > 30:
            print(f"\n  ... and {len(bleeding) - 30} more")
    else:
        print("\n  No obvious bleeding detected.")

    # Malformed
    malformed = []
    for channel, msgs in channel_data.items():
        for m in msgs:
            content = m.get("content", "")
            if classify_content(content, "?") == "malformed_json":
                malformed.append((channel, m.get("id"), content[:80]))
    print("\n" + "=" * 70)
    print("MALFORMED MESSAGES (raw JSON / agent output bugs)")
    print("=" * 70)
    if malformed:
        print(f"\n  Found {len(malformed)} malformed messages.")
        for ch, mid, prev in malformed[:10]:
            print(f"    #{ch} {mid}: {prev[:50]}...")
    else:
        print("\n  None found.")

    # Recommendations
    print("\n" + "=" * 70)
    print("CLEANUP RECOMMENDATIONS")
    print("=" * 70)
    if bleeding or malformed:
        print("""
1. ROUTING FIX:
   - Trades channel: only trade executions (BUY/SELL). Move agent/cron to primary.
   - Cycles channel: only cycle summaries. Update cron to deliver scan output to cycles.
   - Primary: human chat + agent @mentions only.

2. CONFIG FIX:
   - In openclaw/cron: set delivery.to for scan output to channel:1474503699903680756 (cycles)
   - Ensure agent is in primary channel (1474502611393581267), not trades.

3. MALFORMED CONTENT:
   - Fix agent output: never send raw [{'type':'text','text':'...'}] — use plain text.
   - Consider deleting malformed messages in trades channel (see clear_discord_channel.py).

4. CHARTS vs PRIMARY:
   - Charts and primary share ID 1474502611393581267. If you want charts separate,
     create a dedicated #charts channel and set DISCORD_CHARTS_CHANNEL_ID.
""")
    else:
        print("\n  Channels look clean. No action needed.")
    print()


if __name__ == "__main__":
    main()
