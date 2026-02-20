"""Central config: watchlist, paths, env validation."""
import json
import os
import sys
from pathlib import Path

# Workspace root (parent of lib/)
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = WORKSPACE_ROOT / "config"
LOGS_DIR = WORKSPACE_ROOT / "logs"
WATCHLIST_PATH = CONFIG_DIR / "watchlist.json"

# Decisions log retention: keep this many days (None = no rotation)
DECISIONS_RETENTION_DAYS = 90


def validate_env():
    """Ensure required env vars are set. Exits with message if not."""
    required = ["ALPACA_API_KEY", "ALPACA_SECRET_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Missing required env: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)


def load_watchlist():
    """Load watchlist groups from config. Falls back to default if file missing."""
    default = [
        ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOG", "AMD", "INTC", "BA"],
        ["DIS", "NFLX", "JPM", "V", "MA", "UNH", "XOM", "CVX", "PFE", "KO"],
        ["WMT", "COST", "HD", "CRM", "ORCL", "AVGO", "MU", "QCOM", "SOFI", "PLTR"],
        ["HOOD", "IBIT", "TQQQ"],
    ]
    if not WATCHLIST_PATH.exists():
        return default
    try:
        with open(WATCHLIST_PATH, "r") as f:
            data = json.load(f)
        return data.get("groups", default)
    except (json.JSONDecodeError, OSError):
        return default
