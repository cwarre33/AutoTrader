"""Gradio dashboard + APScheduler (HF Space entrypoint)."""

import threading
from datetime import datetime

import gradio as gr
import pandas as pd
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from main import run_scan_cycle
from trader import get_account_info, get_positions
from logger import read_trade_log

# Global state
_scheduler = None
_bot_status = "Stopped"
_last_scan_time = "Never"
_last_scan_stats = {}
_scan_lock = threading.Lock()


def _run_scheduled_scan():
    """Run a scan cycle (called by scheduler)."""
    global _bot_status, _last_scan_time, _last_scan_stats
    _bot_status = "Running scan..."
    try:
        with _scan_lock:
            stats = run_scan_cycle()
            _last_scan_stats = stats
            _last_scan_time = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d %H:%M:%S ET")
            _bot_status = "Running (scheduled)"
    except Exception as e:
        _bot_status = f"Error: {e}"
        print(f"[app] Scheduled scan error: {e}")


def _start_scheduler():
    """Start the APScheduler with a cron trigger for market hours."""
    global _scheduler, _bot_status
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    trigger = CronTrigger(
        day_of_week="mon-fri",
        hour=f"{config.MARKET_OPEN_HOUR}-{config.MARKET_CLOSE_HOUR - 1}",
        minute=f"*/{ config.SCAN_INTERVAL_MINUTES}",
        timezone=pytz.timezone("US/Eastern"),
    )
    _scheduler.add_job(_run_scheduled_scan, trigger, id="scan_cycle", replace_existing=True)
    _scheduler.start()
    _bot_status = "Running (scheduled)"
    print("[app] Scheduler started - scans every 15 min during market hours")


def get_dashboard_data():
    """Gather all dashboard data and return as tuple for Gradio."""
    # Account info
    account = get_account_info()
    if account:
        account_md = f"""### Account Summary
| Metric | Value |
|--------|-------|
| **Equity** | ${account.get('equity', 0):,.2f} |
| **Cash** | ${account.get('cash', 0):,.2f} |
| **Buying Power** | ${account.get('buying_power', 0):,.2f} |
| **Portfolio Value** | ${account.get('portfolio_value', 0):,.2f} |
| **Status** | {account.get('status', 'N/A')} |"""
    else:
        account_md = "### Account Summary\n*Unable to fetch account info. Check API keys.*"

    # Positions
    positions = get_positions()
    if positions:
        positions_df = pd.DataFrame(positions)
        positions_df.columns = [
            "Symbol", "Qty", "Market Value", "Avg Entry", "Current Price", "Unrealized P/L", "Unrealized P/L %"
        ]
    else:
        positions_df = pd.DataFrame(columns=["Symbol", "Qty", "Market Value", "Avg Entry", "Current Price", "Unrealized P/L", "Unrealized P/L %"])

    # Trade history
    trade_history = read_trade_log(last_n=100)

    # Bot status
    status_md = f"""### Bot Status
| | |
|---|---|
| **Status** | {_bot_status} |
| **Last Scan** | {_last_scan_time} |
| **Tickers Scanned** | {_last_scan_stats.get('tickers_scanned', 0)} |
| **Trades Executed** | {_last_scan_stats.get('trades_executed', 0)} |
| **Holds** | {_last_scan_stats.get('holds', 0)} |
| **Errors** | {_last_scan_stats.get('errors', 0)} |"""

    return account_md, positions_df, trade_history, status_md


def refresh_dashboard():
    """Refresh all dashboard panels."""
    return get_dashboard_data()


def manual_scan():
    """Trigger a manual scan cycle."""
    global _bot_status, _last_scan_time, _last_scan_stats
    _bot_status = "Running manual scan..."

    try:
        with _scan_lock:
            stats = run_scan_cycle()
            _last_scan_stats = stats
            _last_scan_time = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d %H:%M:%S ET")
            _bot_status = "Idle (manual scan complete)"
    except Exception as e:
        _bot_status = f"Error: {e}"

    return get_dashboard_data()


def build_app() -> gr.Blocks:
    """Build and return the Gradio app."""
    with gr.Blocks(title="AutoTrader - Paper Trading Bot") as app:
        gr.Markdown("# AutoTrader - Autonomous Paper Trading Bot")
        gr.Markdown("AI-powered paper trading using RSI, news sentiment, and LLM reasoning.")

        with gr.Row():
            with gr.Column(scale=1):
                account_display = gr.Markdown("Loading...")
            with gr.Column(scale=1):
                status_display = gr.Markdown("Loading...")

        gr.Markdown("### Current Positions")
        positions_table = gr.Dataframe(
            headers=["Symbol", "Qty", "Market Value", "Avg Entry", "Current Price", "Unrealized P/L", "Unrealized P/L %"],
            interactive=False,
        )

        gr.Markdown("### Trade History (Last 100)")
        trade_table = gr.Dataframe(interactive=False)

        with gr.Row():
            refresh_btn = gr.Button("Refresh Dashboard", variant="secondary")
            scan_btn = gr.Button("Run Manual Scan", variant="primary")

        refresh_btn.click(
            fn=refresh_dashboard,
            outputs=[account_display, positions_table, trade_table, status_display],
        )

        scan_btn.click(
            fn=manual_scan,
            outputs=[account_display, positions_table, trade_table, status_display],
        )

        # Load initial data on app start
        app.load(
            fn=refresh_dashboard,
            outputs=[account_display, positions_table, trade_table, status_display],
        )

    return app


if __name__ == "__main__":
    # Validate config
    missing = config.validate()
    if missing:
        print(f"[app] WARNING: Missing config values: {', '.join(missing)}")
        print("[app] Set these as environment variables or HF Space secrets.")
        print("[app] Starting dashboard in limited mode (no trading)...")
    else:
        # Start scheduler only if all keys are present
        _start_scheduler()

    app = build_app()
    app.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())
