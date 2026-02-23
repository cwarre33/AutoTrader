"""Generate portfolio charts from Alpaca data."""
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autotrader.chart")


def equity_chart_png(equity_data: dict, width: int = 800, height: int = 400) -> Optional[bytes]:
    """
    Generate an equity curve PNG from portfolio history.
    equity_data: dict with timestamp[], equity[], profit_loss_pct[]
    Returns PNG bytes or None on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        logger.warning("matplotlib not installed, cannot generate chart")
        return None

    timestamps = equity_data.get("timestamp") or []
    equity = equity_data.get("equity") or []
    if not timestamps or not equity or len(timestamps) != len(equity):
        logger.warning("Insufficient portfolio history data for chart")
        return None

    # Convert Unix timestamps to datetime
    dates = [datetime.utcfromtimestamp(ts) for ts in timestamps]

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    ax.plot(dates, equity, color="#5865F2", linewidth=2, label="Equity")
    ax.fill_between(dates, equity, alpha=0.2, color="#5865F2")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=45)
    ax.set_ylabel("Equity ($)")
    ax.set_title("AutoTrader Portfolio — Equity Curve")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
