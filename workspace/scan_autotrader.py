#!/usr/bin/env python3
"""RSI mean-reversion scanner (v2 — improved risk management).

Key changes from v1:
- Max exposure capped at 100% equity (no margin)
- Max 12 concurrent positions
- Tighter RSI entry: only < 25 (was < 30), with SMA/volume/momentum confirmation
- Wider profit targets: +8% full / +4% half (was +4% / +2%) — let winners run
- Tighter stop-loss: -3% (was -4%) — cut losers faster
- Trailing stop: lock in gains once +5% reached (trail at -2% from peak)
- Position sizing: 5-8% equity (was 10-15%)
- Circuit breaker at -2% daily (was -3%)
"""
import json
import logging
import math
import sys
from datetime import datetime

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import validate_env, load_watchlist
from lib.alpaca_client import get_account, get_positions, get_bars, get_snapshot, buy, sell, get_portfolio_history
from lib.rsi import compute_rsi, compute_sma, avg_volume, rsi_turning_up
from lib.decisions import log_decision, load_recent_decisions, rotate_decisions_log, log_outcome, append_daily_review
from lib.config import LOGS_DIR

try:
    from lib.discord_post import post_trades, update_dashboard, update_chart
except ImportError:
    def post_trades(_):
        return False

    def update_dashboard(_):
        return False

    def update_chart(*a, **k):
        return False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("autotrader")

# ── Strategy parameters (v2) ────────────────────────────────────────────────
# Risk management
MAX_EXPOSURE_PCT = 1.00        # Max 100% equity deployed (no margin)
MAX_POSITIONS = 12             # Hard cap on concurrent positions
ALLOC_STRONG = 0.08            # RSI < 15: 8% of equity per position
ALLOC_NORMAL = 0.05            # RSI < 25: 5% of equity per position
BUY_BUFFER = 0.97              # Reserve 3% of BP for slippage

# Entry filters
RSI_BUY_THRESHOLD = 25         # Only buy below this RSI (was 30)
RSI_STRONG_THRESHOLD = 15      # Larger allocation below this
SMA_PERIOD = 50                # Price must be near SMA(50) to buy (uptrend filter)
VOLUME_SPIKE_RATIO = 1.2       # Recent volume must be 1.2x the 20-day avg

# Exit — profit taking
PROFIT_TAKE_FULL_PCT = 0.08    # +8% → sell entire position (was +4%)
PROFIT_TAKE_HALF_PCT = 0.04    # +4% → sell half (was +2%)
TRAILING_ACTIVATE_PCT = 0.05   # Activate trailing stop once +5% reached
TRAILING_STOP_PCT = 0.02       # Trail -2% from peak once activated

# Exit — stop loss
STOP_LOSS_PCT = -0.03          # -3% → sell all (was -4%)

# RSI-based exits
RSI_SELL_ALL = 70              # RSI > 70 → sell all (was 65)
RSI_SELL_HALF = 60             # RSI > 60 → sell half (was 55)

# Circuit breaker
DAILY_DRAWDOWN_HALT = -0.02    # Halt buys if down >2% intraday (was -3%)

_COOLDOWN_FILE = LOGS_DIR / "cooldown.json"
_PEAK_FILE = LOGS_DIR / "trailing_peaks.json"


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


def _load_peaks() -> dict:
    """Load trailing-stop peak prices {ticker: peak_price}."""
    if not _PEAK_FILE.exists():
        return {}
    try:
        return json.loads(_PEAK_FILE.read_text())
    except Exception:
        return {}


def _save_peaks(peaks: dict):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _PEAK_FILE.write_text(json.dumps(peaks))


def _total_market_value(positions):
    return sum(float(p.get("market_value", 0)) for p in positions)


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
    positions = get_positions()

    cooldown_tickers = _load_cooldown(today)
    if cooldown_tickers:
        logger.info("Cooldown active today for: %s", ", ".join(sorted(cooldown_tickers)))

    peaks = _load_peaks()

    # Daily loss circuit breaker (tighter: -2%)
    todays_decisions = [d for d in load_recent_decisions(limit=500)
                        if d.get("timestamp", "")[:10] == today]
    day_open_equity = (float(todays_decisions[0].get("portfolio_value", equity))
                       if todays_decisions else equity)
    day_drawdown = ((equity - day_open_equity) / day_open_equity
                    if day_open_equity > 0 else 0)
    buys_halted = day_drawdown <= DAILY_DRAWDOWN_HALT
    if buys_halted:
        logger.warning(
            "Circuit breaker: portfolio down %.2f%% today — no new buys",
            day_drawdown * 100)

    buy_candidates = []
    sell_candidates = []
    groups = load_watchlist()
    all_rsi = {}

    # === PHASE 1: Stop-loss, trailing stop, and profit-taking ===
    for pos in positions:
        ticker = pos["ticker"]
        qty = int(pos["qty"])
        available_qty = pos.get("available_qty", qty)
        plpc = float(pos.get("unrealized_plpc", 0) or 0)
        cur_price = float(pos.get("current_price", 0))

        if available_qty <= 0:
            logger.warning("Skipping %s: %d shares held by open orders", ticker, qty)
            continue

        # Update trailing-stop peak tracker
        if plpc >= TRAILING_ACTIVATE_PCT:
            prev_peak = peaks.get(ticker, cur_price)
            peaks[ticker] = max(prev_peak, cur_price)
        elif ticker in peaks and plpc < 0:
            del peaks[ticker]

        # Hard stop-loss: -3%
        if plpc < STOP_LOSS_PCT:
            sell_qty = min(qty, available_qty)
            sell(ticker, sell_qty)
            sell_candidates.append((ticker, sell_qty, 0, "stop-loss"))
            log_decision({"timestamp": now, "action": "sell", "ticker": ticker,
                          "shares": sell_qty,
                          "reason": f"stop-loss {STOP_LOSS_PCT * 100:.0f}%",
                          "plpc": plpc, "price": cur_price,
                          "portfolio_value": equity})
            log_outcome({"timestamp": now, "ticker": ticker, "action": "sell",
                         "reason": "stop-loss", "plpc": plpc, "shares": sell_qty})
            cooldown_tickers.add(ticker)
            _save_cooldown(today, cooldown_tickers)
            peaks.pop(ticker, None)
            logger.info("STOP-LOSS %s at %.2f%%, added to cooldown", ticker, plpc * 100)
            continue

        # Trailing stop: price dropped >2% from tracked peak
        if ticker in peaks and cur_price > 0:
            peak = peaks[ticker]
            drop_from_peak = (cur_price - peak) / peak
            if drop_from_peak < -TRAILING_STOP_PCT:
                sell_qty = min(qty, available_qty)
                sell(ticker, sell_qty)
                reason = f"trailing-stop (peak ${peak:.2f}, now ${cur_price:.2f})"
                sell_candidates.append((ticker, sell_qty, 0, reason))
                log_decision({"timestamp": now, "action": "sell", "ticker": ticker,
                              "shares": sell_qty, "reason": reason, "plpc": plpc,
                              "price": cur_price, "portfolio_value": equity})
                log_outcome({"timestamp": now, "ticker": ticker, "action": "sell",
                             "reason": "trailing-stop", "plpc": plpc, "shares": sell_qty})
                peaks.pop(ticker, None)
                logger.info("TRAILING-STOP %s: peak=$%.2f now=$%.2f (%.1f%% from peak)",
                            ticker, peak, cur_price, drop_from_peak * 100)
                continue

        # Profit-take full: +8%
        if plpc >= PROFIT_TAKE_FULL_PCT:
            sell_qty = min(qty, available_qty)
            sell(ticker, sell_qty)
            sell_candidates.append((ticker, sell_qty, 0, "profit-take-full"))
            log_decision({"timestamp": now, "action": "sell", "ticker": ticker,
                          "shares": sell_qty,
                          "reason": f"profit-take +{PROFIT_TAKE_FULL_PCT * 100:.0f}%",
                          "plpc": plpc, "price": cur_price,
                          "portfolio_value": equity})
            log_outcome({"timestamp": now, "ticker": ticker, "action": "sell",
                         "reason": "profit-take-full", "plpc": plpc, "shares": sell_qty})
            peaks.pop(ticker, None)
            continue

        # Profit-take half: +4%
        if plpc >= PROFIT_TAKE_HALF_PCT:
            sell_qty = min(qty // 2, available_qty)
            if sell_qty > 0:
                sell(ticker, sell_qty)
                sell_candidates.append((ticker, sell_qty, 0, "profit-take-half"))
                log_decision({"timestamp": now, "action": "sell", "ticker": ticker,
                              "shares": sell_qty,
                              "reason": f"profit-take +{PROFIT_TAKE_HALF_PCT * 100:.0f}% half",
                              "plpc": plpc, "price": cur_price,
                              "portfolio_value": equity})
                log_outcome({"timestamp": now, "ticker": ticker, "action": "sell",
                             "reason": "profit-take-half", "plpc": plpc,
                             "shares": sell_qty})

    _save_peaks(peaks)
    positions = get_positions()
    held_tickers = {p["ticker"] for p in positions}

    # === PHASE 2: RSI-based sells and buys ===
    acct = get_account()
    remaining_bp = float(acct.get("buying_power", 0)) if acct else 0
    current_exposure = _total_market_value(positions)
    n_positions = len(positions)

    for tickers in groups:
        bars_data = get_bars(tickers, days=60)
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
                    logger.warning("Skipping RSI sell %s: %d shares held by open orders",
                                   ticker, qty)
                    continue
                sell_qty = 0
                reason = ""
                if rsi > RSI_SELL_ALL:
                    sell_qty = min(qty, available_qty)
                    reason = f"RSI sell-all ({rsi:.1f})"
                elif rsi > RSI_SELL_HALF:
                    sell_qty = min(qty // 2, available_qty)
                    reason = f"RSI sell-half ({rsi:.1f})"
                if sell_qty > 0:
                    sell(ticker, sell_qty)
                    sell_candidates.append((ticker, sell_qty, rsi, reason))
                    log_decision({"timestamp": now, "action": "sell", "ticker": ticker,
                                  "shares": sell_qty, "reason": reason, "rsi": rsi,
                                  "price": pos.get("current_price"),
                                  "portfolio_value": equity})
                    log_outcome({"timestamp": now, "ticker": ticker, "action": "sell",
                                 "reason": reason, "rsi": rsi, "shares": sell_qty})
            else:
                # ── Entry filters (all must pass) ──
                if rsi >= RSI_BUY_THRESHOLD:
                    continue
                if ticker in cooldown_tickers:
                    logger.info("Skipping buy %s: on stop-loss cooldown today", ticker)
                    continue
                if buys_halted:
                    logger.info("Skipping buy %s: circuit breaker active", ticker)
                    continue
                if n_positions >= MAX_POSITIONS:
                    logger.info("Skipping buy %s: at max %d positions",
                                ticker, MAX_POSITIONS)
                    continue
                if current_exposure >= equity * MAX_EXPOSURE_PCT:
                    logger.info("Skipping buy %s: exposure %.1f%% >= %.0f%% cap",
                                ticker, current_exposure / equity * 100,
                                MAX_EXPOSURE_PCT * 100)
                    continue

                # SMA trend filter: only buy dips in uptrends
                sma = compute_sma(close_prices, SMA_PERIOD)
                cur_close = close_prices[-1] if close_prices else 0
                if sma and cur_close < sma * 0.97:
                    logger.info("Skipping buy %s: price $%.2f below SMA50 $%.2f (downtrend)",
                                ticker, cur_close, sma)
                    continue

                # Volume confirmation: above-average volume on the dip
                vol_avg = avg_volume(bars, 20)
                last_vol = bars[-1].get("volume", 0) if bars else 0
                if vol_avg and last_vol < vol_avg * VOLUME_SPIKE_RATIO:
                    logger.info("Skipping buy %s: volume %d < %.0f (need %.1fx avg)",
                                ticker, last_vol, vol_avg * VOLUME_SPIKE_RATIO,
                                VOLUME_SPIKE_RATIO)
                    continue

                # RSI momentum: must be turning up (not still falling)
                if not rsi_turning_up(close_prices):
                    logger.info("Skipping buy %s: RSI %.1f still falling", ticker, rsi)
                    continue

                # ── Sizing ──
                alloc_pct = ALLOC_STRONG if rsi < RSI_STRONG_THRESHOLD else ALLOC_NORMAL
                max_new_exposure = equity * MAX_EXPOSURE_PCT - current_exposure
                if max_new_exposure <= 0:
                    continue
                snapshot = get_snapshot(ticker)
                price = (float(snapshot.get("latest_trade_price", 0))
                         if isinstance(snapshot, dict) else 0)
                if price <= 0:
                    continue
                acct = get_account()
                fresh_bp = float(acct.get("buying_power", 0)) if acct else 0
                buying_power = min(remaining_bp, fresh_bp) * BUY_BUFFER
                target_cost = equity * alloc_pct
                target_cost = min(target_cost, max_new_exposure, buying_power)
                if target_cost <= 0:
                    continue
                shares = math.floor(target_cost / price)
                if shares < 1:
                    logger.warning("Skipping buy %s: can't afford 1 share ($%.2f)",
                                   ticker, price)
                    continue

                buy(ticker, shares)
                cost_actual = shares * price
                remaining_bp = max(0, remaining_bp - cost_actual)
                current_exposure += cost_actual
                n_positions += 1
                buy_candidates.append((ticker, shares, rsi, f"RSI buy ({rsi:.1f})"))
                log_decision({"timestamp": now, "action": "buy", "ticker": ticker,
                              "shares": shares, "rsi": rsi, "price": price,
                              "allocation_pct": alloc_pct, "portfolio_value": equity,
                              "filters": {
                                  "sma50": round(sma, 2) if sma else None,
                                  "vol_ratio": round(last_vol / vol_avg, 2) if vol_avg else None,
                              }})
                log_outcome({"timestamp": now, "ticker": ticker, "action": "buy",
                             "reason": f"RSI {rsi:.1f}", "shares": shares, "price": price})

    # === Summary (notification-friendly) ===
    final_account = get_account()
    final_positions = get_positions()
    final_equity = float(final_account.get("equity", 0)) if final_account else equity
    daily_pl = sum(float(p.get("unrealized_pl", 0) or 0) for p in final_positions)
    n_pos = len(final_positions)
    exposure = _total_market_value(final_positions)
    exposure_pct = (exposure / final_equity * 100) if final_equity > 0 else 0

    eq_str = (f"${final_equity / 1_000_000:.1f}M" if final_equity >= 1_000_000
              else f"${final_equity / 1_000:.1f}K")
    pl_sign = "+" if daily_pl >= 0 else ""
    pl_pct = (daily_pl / final_equity * 100) if final_equity > 0 else 0

    sold_str = ("Sold: " + ", ".join(f"{t} {q}" for t, q, _, _ in sell_candidates)
                if sell_candidates else "")
    bought_str = ("Bought: " + ", ".join(f"{t} {q}" for t, q, _, _ in buy_candidates)
                  if buy_candidates else "")
    action_str = (" · ".join(filter(None, [sold_str, bought_str]))
                  if (sell_candidates or buy_candidates) else "No trades this cycle.")

    if sell_candidates or buy_candidates:
        trades_lines = []
        for t, q, r, reason in sell_candidates:
            trades_lines.append(f"🔴 SELL {t} {q} shares — {reason}")
        for t, q, r, reason in buy_candidates:
            trades_lines.append(f"🟢 BUY {t} {q} shares — {reason}")
        if post_trades("\n".join(trades_lines)):
            logger.info("Posted %d trades to Discord",
                        len(sell_candidates) + len(buy_candidates))
        else:
            logger.warning("Failed to post trades to Discord")

    lines = [
        f"📊 {eq_str} · {pl_sign}${daily_pl:,.0f} ({pl_sign}{pl_pct:.2f}%)"
        f" · {n_pos} positions · {exposure_pct:.0f}% deployed",
        action_str,
    ]
    held = {p["ticker"] for p in final_positions}
    watches = sorted([(t, r) for t, r in all_rsi.items() if t not in held and r < 35],
                     key=lambda x: x[1])[:3]
    lines.append("Watching: " + ", ".join(f"{t} RSI {r:.0f}" for t, r in watches)
                 if watches else "No oversold signals. Holding.")
    if buys_halted:
        lines.append(f"CIRCUIT BREAKER: down {day_drawdown * 100:.1f}% today — buys halted")
    if cooldown_tickers:
        lines.append(f"Cooldown: {', '.join(sorted(cooldown_tickers))}")
    print("\n".join(lines))

    decisions_today = [d for d in load_recent_decisions(limit=500)
                       if d.get("timestamp", "")[:10] == today]
    append_daily_review({
        "date": today,
        "equity": final_equity,
        "daily_pl": daily_pl,
        "trades": len([d for d in decisions_today if d.get("action") in ("buy", "sell")]),
        "buys": len([d for d in decisions_today if d.get("action") == "buy"]),
        "sells": len([d for d in decisions_today if d.get("action") == "sell"]),
        "positions": n_pos,
        "exposure_pct": round(exposure_pct, 1),
    })
    rotate_decisions_log()
    logger.debug("Scan complete: equity=%s positions=%s trades=%s exposure=%.0f%%",
                 eq_str, n_pos, len(sell_candidates) + len(buy_candidates), exposure_pct)

    # Update Discord dashboard
    dashboard_lines = [
        "**📊 AutoTrader Dashboard (v2)**",
        f"Equity: {eq_str} · P&L: {pl_sign}${daily_pl:,.0f} ({pl_sign}{pl_pct:.2f}%)",
        f"Positions: {n_pos} · Exposure: {exposure_pct:.0f}%",
        "",
        "**Holdings:**",
    ]
    for p in sorted(final_positions, key=lambda x: -float(x.get("market_value", 0))):
        mv = float(p.get("market_value", 0))
        plpc = float(p.get("unrealized_plpc", 0) or 0)
        sign = "+" if plpc >= 0 else ""
        dashboard_lines.append(f"• {p['ticker']}: ${mv:,.0f} ({sign}{plpc * 100:.1f}%)")
    if watches:
        dashboard_lines.append("")
        watch_str = ", ".join(f"{t} RSI {r:.0f}" for t, r in watches)
        dashboard_lines.append(f"**Watching (RSI<35):** {watch_str}")
    dashboard_lines.append("")
    dashboard_lines.append(f"_Updated {now[:19].replace('T', ' ')} UTC_")
    try:
        if update_dashboard("\n".join(dashboard_lines)):
            logger.info("Updated Discord dashboard")
        else:
            logger.warning("Failed to update Discord dashboard")
    except Exception as e:
        logger.warning("Dashboard update error: %s", e)

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
