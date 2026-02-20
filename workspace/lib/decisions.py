"""Decision logging, retention, and self-improvement outcomes."""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .config import LOGS_DIR, DECISIONS_RETENTION_DAYS

logger = logging.getLogger("autotrader")
DECISIONS_PATH = LOGS_DIR / "decisions.jsonl"
OUTCOMES_PATH = LOGS_DIR / "outcomes.jsonl"
REVIEW_PATH = LOGS_DIR / "daily_review.jsonl"


def log_decision(entry):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_recent_decisions(limit=200, since_date=None):
    """Load most recent decisions (newest last in list). Optionally filter since_date (date string YYYY-MM-DD)."""
    if not DECISIONS_PATH.exists():
        return []
    lines = DECISIONS_PATH.read_text(encoding="utf-8").strip().splitlines()
    decisions = []
    for line in reversed(lines[-limit:]):
        try:
            d = json.loads(line)
            if since_date and d.get("timestamp", "")[:10] < since_date:
                continue
            decisions.append(d)
        except json.JSONDecodeError:
            continue
    return list(reversed(decisions))


def rotate_decisions_log():
    """Keep only last DECISIONS_RETENTION_DAYS. Call periodically (e.g. daily)."""
    if DECISIONS_RETENTION_DAYS is None or not DECISIONS_PATH.exists():
        return
    cutoff = (datetime.utcnow() - timedelta(days=DECISIONS_RETENTION_DAYS)).strftime("%Y-%m-%d")
    lines = DECISIONS_PATH.read_text(encoding="utf-8").strip().splitlines()
    kept = [ln for ln in lines if ln.strip() and ln.strip()[:26].split("Z")[0][:10] >= cutoff]
    if len(kept) < len(lines):
        DECISIONS_PATH.write_text("\n".join(kept) + ("\n" if kept else ""))
        logger.info("Rotated decisions log: kept %s lines since %s", len(kept), cutoff)


def log_outcome(entry):
    """Append an outcome (e.g. resolved P&L for a closed position) for self-improvement."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTCOMES_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def append_daily_review(summary_dict):
    """Append one line to daily_review.jsonl for agent/self-improvement loop."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    summary_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"
    with open(REVIEW_PATH, "a") as f:
        f.write(json.dumps(summary_dict) + "\n")
