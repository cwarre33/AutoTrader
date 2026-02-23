#!/usr/bin/env python3
"""RSI mean-reversion scanner. Single entrypoint; uses shared lib."""
import json
import logging
import math
import sys
from datetime import datetime
from pathlib import Path

# Run from workspace root so lib is importable
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import validate_env, load_watchlist
from lib.alpaca_client import get_account, get_positions, get_bars, get_snapshot, get_snapshots_batch, buy, sell, get_portfolio_history
from lib.rsi import compute_rsi
from lib.decisions import log_decision, load_recent_decisions, rotate_decisions_log, log_outcome, append_daily_review
from lib.config import LOGS_DIR

try:
    from lib.discord_post import post_trades, update_dashboard, update_chart
except ImportError:
    post_trades = lambda _: False
    update_dashboard = lambda _: False
    update_chart = lambda *a, **k: False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("autotrader")

# ── Strategy parameters ──────────────────────────────────────────────────────
# Buy:        RSI < 20 → 15% equity | RSI < 30 → 10% equity
#             (RSI 30-40 tier removed — too loose, never bounced to profit)
# Sell RSI:   RSI > 65 → sell all   | RSI > 55 → sell half
# Profit-take: +4% → sell all       | +2% → sell half
# Stop-loss:  -4% → sell all  (widened from -3% to avoid normal volatility stops)
# Daily loss circuit breaker: halt new buys if portfolio down >3% from day open
# Stop-loss cooldown: after a stop-loss, skip that ticker for the rest of the day

_COOLDOWN_FILE = LOGS_DIR / "cooldown.json"


def _load_cooldown(today: str) -> set:
    """Load tickers on stop-loss cooldown today. Resets automatically on new day."""
    if not _COOLDOWN_FILE.exists():
        return set()
    try:
        data = json.loads(_COOLDOWN_FILE.read_text())
        if data.get("date") == today:
            return set(data.get("tickers", []))
    except Exception:
        pass
    return set()


def _save_cooldown(today: str, tickers: set):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _COOLDOWN_FILE.write_text(json.dumps({"date": today, "tickers": sorted(tickers)}))


def main():
    validate_env()
    now = datetime.utcnow().isoformat() + "Z"
    today = now[:10]

    account = get_account()
    if not account:
        logger.error("Failed to get account")
        print("Failed to get account", file=sys.stderr)
        return
    equity = float(account.get("equity", 0))
    buying_power = float(account.get("buying_power", 0))
    positions = get_positions()

    # Load stop-loss cooldown (resets each day automatically)
    cooldown_tickers = _load_cooldown(today)
    if cooldown_tickers:
        logger.info("Cooldown active today for: %s", ", ".join(sorted(cooldown_tickers)))

    # Daily loss circuit breaker: track today's open equity from decisions log
    # Use today's first logged equity as the "open"; halt buys if down >3%
    todays_decisions = [d for d in load_recent_decisions(limit=500) if d.get("timestamp", "")[:10] == today]
    day_open_equity = float(todays_decisions[0].get("portfolio_value", equity)) if todays_decisions else equity
    day_drawdown = (equity - day_open_equity) / day_open_equity if day_open_equity > 0 else 0
    buys_halted = day_drawdown <= -0.03
    if buys_halted:
        logger.warning("Circuit breaker: portfolio down %.2f%% today — no new buys", day_drawdown * 100)

    buy_candidates = []
    sell_candidates = []
    groups = load_watchlist()
    all_rsi = {}

    # === PHASE 1: Stop-loss and profit-taking on existing positions ===
    for pos in positions:
        ticker = pos["ticker"]
        qty = int(pos["qty"])
        available_qty = pos.get("available_qty", qty)
        plpc = float(pos.get("unrealized_plpc", 0) or 0)

        if available_qty <= 0:
            logger.warning("Skipping %s: %d shares held by open orders", ticker, qty)
            continue

        if plpc < -0.04:
            sell_qty = min(qty, available_qty)
            sell(ticker, sell_qty)
            sell_candidates.append((ticker, sell_qty, 0, "stop-loss"))
            log_decision({"timestamp": now, "action": "sell", "ticker": ticker, "shares": sell_qty, "reason": "stop-loss -4%", "plpc": plpc, "price": pos.get("current_price"), "portfolio_value": equity})
            log_outcome({"timestamp": now, "ticker": ticker, "action": "sell", "reason": "stop-loss", "plpc": plpc, "shares": sell_qty})
            # Add to cooldown: prevent rebuy for rest of day
            cooldown_tickers.add(ticker)
            _save_cooldown(today, cooldown_tickers)
            logger.info("Added %s to cooldown after stop-loss", ticker)
            continue
        if plpc >= 0.04:
            sell_qty = min(qty, available_qty)
            sell(ticker, sell_qty)
            sell_candidates.append((ticker, sell_qty, 0, "profit-take-full"))
            log_decision({"timestamp": now, "action": "sell", "ticker": ticker, "shares": sell_qty, "reason": "profit-take +4%", "plpc": plpc, "price": pos.get("current_price"), "portfolio_value": equity})
            log_outcome({"timestamp": now, "ticker": ticker, "action": "sell", "reason": "profit-take-full", "plpc": plpc, "shares": sell_qty})
            continue
        if plpc >= 0.02:
            sell_qty = min(qty // 2, available_qty)
            if sell_qty > 0:
                sell(ticker, sell_qty)
                sell_candidates.append((ticker, sell_qty, 0, "profit-take-half"))
                log_decision({"timestamp": now, "action": "sell", "ticker": ticker, "shares": sell_qty, "reason": "profit-take +2% half", "plpc": plpc, "price": pos.get("current_price"), "portfolio_value": equity})
                log_outcome({"timestamp": now, "ticker": ticker, "action": "sell", "reason": "profit-take-half", "plpc": plpc, "shares": sell_qty})

    positions = get_positions()
    held_tickers = {p["ticker"] for p in positions}

    # === PHASE 2: RSI-based sells and buys ===
    # Track remaining buying power across buys in this cycle (orders may not settle instantly)
    acct = get_account()
    remaining_bp = float(acct.get("buying_power", 0)) if acct else 0
    BUY_BUFFER = 0.98  # Use 98% of BP to leave margin for slippage/fees

    for tickers in groups:
        bars_data = get_bars(tickers)
        if not bars_data:
            continue
        for ticker in tickers:
            if ticker not in bars_data:
                continue
            bars = bars_data[ticker]
            close_prices = [float(b["close"]) for b in bars]
            rsi = compute_rsi(close_prices)
            if rsi is None:
                continue
            all_rsi[ticker] = rsi

            if ticker in held_tickers:
                pos = next((p for p in positions if p["ticker"] == ticker), None)
                if not pos:
                    continue
                qty = int(pos["qty"])
                available_qty = pos.get("available_qty", qty)
                if available_qty <= 0:
                    logger.warning("Skipping RSI sell %s: %d shares held by open orders", ticker, qty)
                    continue
                sell_qty = 0
                reason = ""
                if rsi > 65:
                    sell_qty = min(qty, available_qty)
                    reason = f"RSI sell-all ({rsi:.1f})"
                elif rsi > 55:
                    sell_qty = min(qty // 2, available_qty)
                    reason = f"RSI sell-half ({rsi:.1f})"
                if sell_qty > 0:
                    sell(ticker, sell_qty)
                    sell_candidates.append((ticker, sell_qty, rsi, reason))
                    log_decision({"timestamp": now, "action": "sell", "ticker": ticker, "shares": sell_qty, "reason": reason, "rsi": rsi, "price": pos.get("current_price"), "portfolio_value": equity})
                    log_outcome({"timestamp": now, "ticker": ticker, "action": "sell", "reason": reason, "rsi": rsi, "shares": sell_qty})
            else:
                # Only buy extreme oversold (RSI < 30); RSI 30-40 tier removed
                # — analysis showed 100% of those entries stopped out without profit
                if rsi >= 30:
                    continue
                # Skip if on cooldown from earlier stop-loss today
                if ticker in cooldown_tickers:
                    logger.info("Skipping buy %s: on stop-loss cooldown today", ticker)
                    continue
                # Skip if daily loss circuit breaker is active
                if buys_halted:
                    logger.info("Skipping buy %s: circuit breaker active (down %.2f%% today)", ticker, day_drawdown * 100)
                    continue
                alloc_pct = 0.15 if rsi < 20 else 0.10
                snapshot = get_snapshot(ticker)
                price = float(snapshot.get("latest_trade_price", 0)) if isinstance(snapshot, dict) else 0
                if price <= 0:
                    continue
                # Use min of tracked remaining_bp and fresh API value (Spidey/others may use BP)
                acct = get_account()
                fresh_bp = float(acct.get("buying_power", 0)) if acct else 0
                buying_power = min(remaining_bp, fresh_bp) * BUY_BUFFER
                if buying_power <= 0:
                    logger.warning("Skipping buy %s: no buying power", ticker)
                    continue
                shares = math.floor(equity * alloc_pct / price)
                if shares < 1:
                    continue
                cost = shares * price
                if cost > buying_power:
                    shares = math.floor(buying_power / price)
                if shares < 1:
                    logger.warning("Skipping buy %s: insufficient buying power (%.2f)", ticker, buying_power)
                    continue
                buy(ticker, shares)
                cost_actual = shares * price
                remaining_bp = max(0, remaining_bp - cost_actual)
                buy_candidates.append((ticker, shares, rsi, f"RSI buy ({rsi:.1f})"))
                log_decision({"timestamp": now, "action": "buy", "ticker": ticker, "shares": shares, "rsi": rsi, "price": price, "allocation_pct": alloc_pct, "portfolio_value": equity})
                log_outcome({"timestamp": now, "ticker": ticker, "action": "buy", "reason": f"RSI {rsi:.1f}", "shares": shares, "price": price})

    # === Summary (notification-friendly) ===
    final_account = get_account()
    final_positions = get_positions()
    final_equity = float(final_account.get("equity", 0)) if final_account else equity
    daily_pl = sum(float(p.get("unrealized_pl", 0) or 0) for p in final_positions)
    n_pos = len(final_positions)

    eq_str = f"${final_equity/1_000_000:.1f}M" if final_equity >= 1_000_000 else f"${final_equity/1_000:.1f}K"
    pl_sign = "+" if daily_pl >= 0 else ""
    pl_pct = (daily_pl / final_equity * 100) if final_equity > 0 else 0

    sold_str = "Sold: " + ", ".join(f"{t} {q}" for t, q, _, _ in sell_candidates) if sell_candidates else ""
    bought_str = "Bought: " + ", ".join(f"{t} {q}" for t, q, _, _ in buy_candidates) if buy_candidates else ""
    action_str = " · ".join(filter(None, [sold_str, bought_str])) if (sell_candidates or buy_candidates) else "No trades this cycle."

    # Post trades to Discord trades channel when any executed
    if sell_candidates or buy_candidates:
        trades_lines = []
        for t, q, r, reason in sell_candidates:
            trades_lines.append(f"🔴 SELL {t} {q} shares — {reason}")
        for t, q, r, reason in buy_candidates:
            trades_lines.append(f"🟢 BUY {t} {q} shares — {reason}")
        if post_trades("\n".join(trades_lines)):
            logger.info("Posted %d trades to Discord", len(sell_candidates) + len(buy_candidates))
        else:
            logger.warning("Failed to post trades to Discord")
    lines = [
        f"📊 {eq_str} · {pl_sign}${daily_pl:,.0f} ({pl_sign}{pl_pct:.2f}%) · {n_pos} positions",
        action_str,
    ]
    held = {p["ticker"] for p in final_positions}
    watches = sorted([(t, r) for t, r in all_rsi.items() if t not in held and r < 35], key=lambda x: x[1])[:3]
    lines.append("Watching: " + ", ".join(f"{t} RSI {r:.0f}" for t, r in watches) if watches else "No oversold signals. Holding.")
    if buys_halted:
        lines.append(f"CIRCUIT BREAKER: down {day_drawdown*100:.1f}% today — buys halted")
    if cooldown_tickers:
        lines.append(f"Cooldown: {', '.join(sorted(cooldown_tickers))}")
    print("\n".join(lines))

    # Self-improvement: daily review and retention
    decisions_today = [d for d in load_recent_decisions(limit=500) if d.get("timestamp", "")[:10] == today]
    append_daily_review({
        "date": today,
        "equity": final_equity,
        "daily_pl": daily_pl,
        "trades": len([d for d in decisions_today if d.get("action") in ("buy", "sell")]),
        "buys": len([d for d in decisions_today if d.get("action") == "buy"]),
        "sells": len([d for d in decisions_today if d.get("action") == "sell"]),
        "positions": n_pos,
    })
    rotate_decisions_log()
    logger.debug("Scan complete: equity=%s positions=%s trades=%s", eq_str, n_pos, len(sell_candidates) + len(buy_candidates))

    # Update static dashboard with latest data (edits same message each cycle)
    dashboard_lines = [
        "**📊 AutoTrader Dashboard**",
        f"Equity: {eq_str} · P&L: {pl_sign}${daily_pl:,.0f} ({pl_sign}{pl_pct:.2f}%)",
        f"Positions: {n_pos}",
        "",
        "**Holdings:**",
    ]
    for p in sorted(final_positions, key=lambda x: -float(x.get("market_value", 0))):
        mv = float(p.get("market_value", 0))
        plpc = float(p.get("unrealized_plpc", 0) or 0)
        sign = "+" if plpc >= 0 else ""
        dashboard_lines.append(f"• {p['ticker']}: ${mv:,.0f} ({sign}{plpc*100:.1f}%)")
    if watches:
        dashboard_lines.append("")
        dashboard_lines.append("**Watching (RSI<35):** " + ", ".join(f"{t} RSI {r:.0f}" for t, r in watches))
    dashboard_lines.append("")
    dashboard_lines.append(f"_Updated {now[:19].replace('T', ' ')} UTC_")
    try:
        if update_dashboard("\n".join(dashboard_lines)):
            logger.info("Updated Discord dashboard")
        else:
            logger.warning("Failed to update Discord dashboard")
    except Exception as e:
        logger.warning("Dashboard update error: %s", e)

    # Post portfolio chart (same update logic as dashboard: replace message each cycle)
    try:
        from lib.chart import equity_chart_png
        hist = get_portfolio_history(period="1M", timeframe="1D")
        if hist.get("equity"):
            png = equity_chart_png(hist)
            if png and update_chart(png, content="📈 Portfolio equity — last 1M"):
                logger.info("Updated Discord chart")
            elif png:
                logger.warning("Failed to update Discord chart")
    except Exception as e:
        logger.warning("Chart update error: %s", e)


if __name__ == "__main__":
    main()
