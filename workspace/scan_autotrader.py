#!/usr/bin/env python3
"""Aggressive RSI mean-reversion scanner. Single entrypoint; uses shared lib."""
import logging
import math
import sys
from datetime import datetime

# Run from workspace root so lib is importable
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import validate_env, load_watchlist
from lib.alpaca_client import get_account, get_positions, get_bars, get_snapshot, get_snapshots_batch, buy, sell
from lib.rsi import compute_rsi
from lib.decisions import log_decision, load_recent_decisions, rotate_decisions_log, log_outcome, append_daily_review

try:
    from lib.discord_post import post_trades, update_dashboard
except ImportError:
    post_trades = lambda _: False
    update_dashboard = lambda _: False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("autotrader")

# Strategy: Buy dips hard, take profits fast, cut losses early.
# Buy:  RSI < 40 → 10% equity, RSI < 30 → 15% equity, RSI < 20 → 20% equity
# Sell: RSI > 65 → sell all, RSI > 55 → sell half
# Profit-take: +5% unrealized → sell all, +3% → sell half
# Stop-loss: -3% unrealized → sell all


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

    buy_candidates = []
    sell_candidates = []
    groups = load_watchlist()
    all_rsi = {}

    # === PHASE 1: Stop-loss and profit-taking on existing positions ===
    for pos in positions:
        ticker = pos["ticker"]
        qty = int(pos["qty"])
        plpc = float(pos.get("unrealized_plpc", 0) or 0)

        if plpc < -0.03:
            sell(ticker, qty)
            sell_candidates.append((ticker, qty, 0, "stop-loss"))
            log_decision({"timestamp": now, "action": "sell", "ticker": ticker, "shares": qty, "reason": "stop-loss -3%", "plpc": plpc, "price": pos.get("current_price"), "portfolio_value": equity})
            log_outcome({"timestamp": now, "ticker": ticker, "action": "sell", "reason": "stop-loss", "plpc": plpc, "shares": qty})
            continue
        if plpc >= 0.05:
            sell(ticker, qty)
            sell_candidates.append((ticker, qty, 0, "profit-take-full"))
            log_decision({"timestamp": now, "action": "sell", "ticker": ticker, "shares": qty, "reason": "profit-take +5%", "plpc": plpc, "price": pos.get("current_price"), "portfolio_value": equity})
            log_outcome({"timestamp": now, "ticker": ticker, "action": "sell", "reason": "profit-take-full", "plpc": plpc, "shares": qty})
            continue
        if plpc >= 0.03:
            sell_qty = qty // 2
            if sell_qty > 0:
                sell(ticker, sell_qty)
                sell_candidates.append((ticker, sell_qty, 0, "profit-take-half"))
                log_decision({"timestamp": now, "action": "sell", "ticker": ticker, "shares": sell_qty, "reason": "profit-take +3% half", "plpc": plpc, "price": pos.get("current_price"), "portfolio_value": equity})
                log_outcome({"timestamp": now, "ticker": ticker, "action": "sell", "reason": "profit-take-half", "plpc": plpc, "shares": sell_qty})

    positions = get_positions()
    held_tickers = {p["ticker"] for p in positions}

    # === PHASE 2: RSI-based sells and buys ===
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
                sell_qty = 0
                reason = ""
                if rsi > 65:
                    sell_qty = qty
                    reason = f"RSI sell-all ({rsi:.1f})"
                elif rsi > 55:
                    sell_qty = qty // 2
                    reason = f"RSI sell-half ({rsi:.1f})"
                if sell_qty > 0:
                    sell(ticker, sell_qty)
                    sell_candidates.append((ticker, sell_qty, rsi, reason))
                    log_decision({"timestamp": now, "action": "sell", "ticker": ticker, "shares": sell_qty, "reason": reason, "rsi": rsi, "price": pos.get("current_price"), "portfolio_value": equity})
                    log_outcome({"timestamp": now, "ticker": ticker, "action": "sell", "reason": reason, "rsi": rsi, "shares": sell_qty})
            else:
                if rsi >= 40:
                    continue
                alloc_pct = 0.20 if rsi < 20 else 0.15 if rsi < 30 else 0.10
                snapshot = get_snapshot(ticker)
                price = float(snapshot.get("latest_trade_price", 0)) if isinstance(snapshot, dict) else 0
                if price <= 0:
                    continue
                shares = math.floor(equity * alloc_pct / price)
                if shares < 1:
                    continue
                buy(ticker, shares)
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
    watches = sorted([(t, r) for t, r in all_rsi.items() if t not in held and r < 45], key=lambda x: x[1])[:3]
    lines.append("Watching: " + ", ".join(f"{t} RSI {r:.0f}" for t, r in watches) if watches else "No oversold signals. Holding.")
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
        dashboard_lines.append("**Watching:** " + ", ".join(f"{t} RSI {r:.0f}" for t, r in watches))
    dashboard_lines.append("")
    dashboard_lines.append(f"_Updated {now[:19].replace('T', ' ')} UTC_")
    try:
        if update_dashboard("\n".join(dashboard_lines)):
            logger.info("Updated Discord dashboard")
        else:
            logger.warning("Failed to update Discord dashboard")
    except Exception as e:
        logger.warning("Dashboard update error: %s", e)


if __name__ == "__main__":
    main()
