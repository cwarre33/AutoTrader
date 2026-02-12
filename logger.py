"""Thread-safe CSV logging of every trading decision."""

import csv
import os
import threading
from datetime import datetime, timezone

import pandas as pd

from config import config

_lock = threading.Lock()

HEADERS = [
    "timestamp",
    "ticker",
    "action",
    "confidence",
    "sentiment",
    "rsi",
    "reasoning",
    "shares",
    "price",
    "order_status",
    "order_id",
    "equity_at_time",
]


def _ensure_log_file():
    """Create log directory and CSV with headers if they don't exist."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    if not os.path.exists(config.TRADE_LOG_FILE):
        with open(config.TRADE_LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(HEADERS)


def log_decision(
    ticker: str,
    action: str,
    confidence: int,
    sentiment: str,
    rsi: float,
    reasoning: str,
    shares: int = 0,
    price: float = 0.0,
    order_status: str = "",
    order_id: str = "",
    equity_at_time: float = 0.0,
):
    """Append a single decision row to the trade log (thread-safe)."""
    with _lock:
        _ensure_log_file()
        with open(config.TRADE_LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                ticker,
                action,
                confidence,
                sentiment,
                round(rsi, 2) if rsi else "",
                reasoning,
                shares,
                round(price, 2) if price else "",
                order_status,
                order_id,
                round(equity_at_time, 2) if equity_at_time else "",
            ])


def read_trade_log(last_n: int = 100) -> pd.DataFrame:
    """Read the trade log CSV and return the last N rows as a DataFrame."""
    _ensure_log_file()
    try:
        df = pd.read_csv(config.TRADE_LOG_FILE)
        return df.tail(last_n)
    except (pd.errors.EmptyDataError, FileNotFoundError):
        return pd.DataFrame(columns=HEADERS)
