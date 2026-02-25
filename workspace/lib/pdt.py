"""Pattern Day Trader (PDT) protection for accounts under $25K.

FINRA rule: accounts under $25K are limited to 3 day trades in any rolling
5-business-day window. A "day trade" is opening and closing the same symbol
on the same calendar day.

This module tracks day trades in a JSONL file and exposes helpers to check
whether a new buy or sell would trigger a day trade, and whether the PDT
limit has been reached.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("autotrader.pdt")

_PDT_FILE = Path(__file__).resolve().parent.parent / "logs" / "pdt_trades.jsonl"
PDT_LIMIT = 3
PDT_WINDOW_DAYS = 5
PDT_EQUITY_THRESHOLD = 25_000


def is_pdt_restricted(equity: float) -> bool:
    """True if the account is subject to PDT rules (equity < $25K)."""
    return equity < PDT_EQUITY_THRESHOLD


def _load_recent_trades() -> list:
    """Load day-trade records from the last PDT_WINDOW_DAYS."""
    if not _PDT_FILE.exists():
        return []
    cutoff = (datetime.utcnow() - timedelta(days=PDT_WINDOW_DAYS + 2)).strftime("%Y-%m-%d")
    records = []
    for line in _PDT_FILE.read_text(encoding="utf-8").strip().splitlines():
        try:
            rec = json.loads(line)
            if rec.get("date", "") >= cutoff:
                records.append(rec)
        except json.JSONDecodeError:
            continue
    return records


def count_day_trades() -> int:
    """Count day trades in the rolling 5-business-day window."""
    records = _load_recent_trades()
    cutoff = datetime.utcnow() - timedelta(days=PDT_WINDOW_DAYS + 2)
    count = 0
    for rec in records:
        try:
            dt = datetime.strptime(rec["date"], "%Y-%m-%d")
            if dt >= cutoff:
                count += 1
        except (KeyError, ValueError):
            continue
    return count


def day_trades_remaining() -> int:
    """How many day trades are still allowed in the current window."""
    return max(0, PDT_LIMIT - count_day_trades())


def would_be_day_trade(ticker: str, side: str, today: str,
                       todays_decisions: list) -> bool:
    """Check if executing this trade would create a day trade.

    A day trade occurs when you buy AND sell the same ticker on the same day.
    - If side="sell" and there's a buy for this ticker today → day trade
    - If side="buy" and there's a sell for this ticker today → day trade
    """
    opposite = "buy" if side == "sell" else "sell"
    for d in todays_decisions:
        same_ticker = d.get("ticker") == ticker
        opp_side = d.get("action") == opposite
        same_day = d.get("timestamp", "")[:10] == today
        if same_ticker and opp_side and same_day:
            return True
    return False


def record_day_trade(ticker: str, today: str):
    """Record that a day trade occurred."""
    _PDT_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {"date": today, "ticker": ticker,
             "timestamp": datetime.utcnow().isoformat() + "Z"}
    with open(_PDT_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    logger.warning("PDT: recorded day trade for %s (total: %d/%d in window)",
                   ticker, count_day_trades(), PDT_LIMIT)


def cleanup_old_records():
    """Remove records older than the PDT window."""
    if not _PDT_FILE.exists():
        return
    cutoff = (datetime.utcnow() - timedelta(days=PDT_WINDOW_DAYS + 2)).strftime("%Y-%m-%d")
    lines = _PDT_FILE.read_text(encoding="utf-8").strip().splitlines()
    kept = [ln for ln in lines
            if ln.strip() and json.loads(ln).get("date", "") >= cutoff]
    if len(kept) < len(lines):
        _PDT_FILE.write_text("\n".join(kept) + ("\n" if kept else ""))
