#!/usr/bin/env python3
"""
Generate an equity curve chart from Alpaca portfolio history and post to Discord.
Run from workspace root: python scripts/post_portfolio_chart.py

Uses DISCORD_CHARTS_CHANNEL_ID (default: dashboard channel) and DISCORD_BOT_TOKEN.
"""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env from workspace or repo root
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

from lib.alpaca_client import get_portfolio_history
from lib.chart import equity_chart_png
from lib.discord_post import update_chart

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("chart")


def main():
    period = os.environ.get("CHART_PERIOD", "1M")
    timeframe = os.environ.get("CHART_TIMEFRAME", "1D")

    hist = get_portfolio_history(period=period, timeframe=timeframe)
    if not hist.get("equity"):
        logger.warning("No portfolio history data (account may be new)")
        return 1

    png = equity_chart_png(hist)
    if not png:
        logger.error("Failed to generate chart")
        return 1

    caption = f"📈 Portfolio equity — last {period}"
    if update_chart(png, content=caption):
        logger.info("Posted portfolio chart to Discord")
        return 0
    logger.error("Failed to post chart to Discord")
    return 1


if __name__ == "__main__":
    sys.exit(main())
