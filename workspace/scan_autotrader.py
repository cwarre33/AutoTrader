#!/usr/bin/env python3
"""RSI mean-reversion scanner (v3 — live-trading ready).

Strategy features:
- Max exposure capped at 100% equity (no margin)
- Max 12 concurrent positions, dust cleanup, add-to-winners
- RSI entry < 30 with SMA/volume/momentum confirmation
- Profit targets: +8% full / +4% half, trailing stop at +5%/-2%
- Stop-loss at -3%, circuit breaker at -2% daily

Live-trading safeguards (GATEWAY_MODE=live):
- PDT protection: tracks day trades, blocks at 3/5-day limit (accounts < $25K)
- Skips expensive tickers when allocation rounds to 0 shares
- Logs every order with reason for auditability
"""
import json
import logging
import sys
from datetime import datetime

import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env if key vars not set (cron subprocess may not inherit full Docker env)
if not os.environ.get("SIMULATED_BALANCE") or not os.environ.get("GATEWAY_MODE"):
    for _p in [
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]:
        if _p.exists():
            try:
                for _line in _p.read_text().splitlines():
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _, _v = _line.partition("=")
                        _k = _k.strip()
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v.strip().strip('"').strip("'")
            except (OSError, UnicodeDecodeError):
                pass
            break

from lib.config import validate_env, load_watchlist
from lib.alpaca_client import get_account, get_positions, get_bars, buy_notional, sell, get_portfolio_history
from lib.rsi import compute_rsi, compute_sma, avg_volume, rsi_turning_up
from lib.decisions import log_decision, load_recent_decisions, rotate_decisions_log, log_outcome, append_daily_review
from lib.config import LOGS_DIR
from lib.pdt import (is_pdt_restricted, count_day_trades, day_trades_remaining,
                     would_be_day_trade, record_day_trade, cleanup_old_records)

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

# ── Mode: paper vs live ──────────────────────────────────────────────────────
# Set GATEWAY_MODE=live in .env to enable PDT protection + extra safeguards
LIVE_MODE = os.environ.get("GATEWAY_MODE", "paper").lower() == "live"

# Simulated balance: cap the bot's usable equity (0 = use actual account equity)
# Set SIMULATED_BALANCE=100 in .env to test as if you only have $100
SIMULATED_BALANCE = float(os.environ.get("SIMULATED_BALANCE", "0"))

# ── Strategy parameters (v3) ────────────────────────────────────────────────
# Risk management
MAX_EXPOSURE_PCT = 1.00        # Max 100% equity deployed (no margin)
MAX_POSITIONS = 12             # Hard cap on concurrent positions
ALLOC_STRONG = 0.08            # RSI < 15: 8% of equity per position
ALLOC_NORMAL = 0.05            # RSI < 25: 5% of equity per position
BUY_BUFFER = 0.97              # Reserve 3% of BP for slippage
DUST_THRESHOLD_PCT = 0.005     # Auto-sell positions < 0.5% of portfolio

# Entry filters
RSI_BUY_THRESHOLD = 30         # Buy below this RSI (widened from 25 — was too tight)
RSI_STRONG_THRESHOLD = 20      # Larger allocation below this
SMA_PERIOD = 20                # SMA(20) — short enough for IEX data availability
VOLUME_SPIKE_RATIO = 0.8       # Volume >= 80% of 20-day avg (IEX underreports volume)
MIN_BARS_FOR_SMA = 20          # Skip SMA filter if fewer bars available

# Add-to-winners: deploy idle cash into best existing positions
ADD_TO_WINNERS_CASH_PCT = 0.40  # Trigger when cash > 40% of equity
ADD_TO_WINNER_MIN_PLPC = 0.02  # Position must be +2% or better
ADD_TO_WINNER_ALLOC = 0.04     # Add 4% equity per top-up
ADD_TO_WINNER_MAX_PCT = 0.15   # Don't grow any position beyond 15% of portfolio

# Exit — profit taking
PROFIT_TAKE_FULL_PCT = 0.08    # +8% → sell entire position
PROFIT_TAKE_HALF_PCT = 0.04    # +4% → sell half
TRAILING_ACTIVATE_PCT = 0.05   # Activate trailing stop once +5% reached
TRAILING_STOP_PCT = 0.02       # Trail -2% from peak once activated

# Exit — stop loss
STOP_LOSS_PCT = -0.03          # -3% → sell all

# RSI-based exits
RSI_SELL_ALL = 70              # RSI > 70 → sell all
RSI_SELL_HALF = 60             # RSI > 60 → sell half

# Circuit breaker
DAILY_DRAWDOWN_HALT = -0.02    # Halt buys if down >2% intraday

_COOLDOWN_FILE = LOGS_DIR / "cooldown.json"
_PEAK_FILE = LOGS_DIR / "trailing_peaks.json"
_CHART_TS_FILE = LOGS_DIR / "last_chart_post.txt"
CHART_INTERVAL_SEC = 1800     # Post chart at most once per 30 minutes


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


def _check_pdt(ticker, side, today, todays_decisions, pdt_active):
    """Return True if this trade is safe from PDT. False = blocked."""
    if not pdt_active:
        return True
    if not would_be_day_trade(ticker, side, today, todays_decisions):
        return True
    remaining = day_trades_remaining()
    if remaining <= 0:
        logger.warning("PDT BLOCKED %s %s: 0 day trades remaining", side.upper(), ticker)
        return False
    logger.warning("PDT: %s %s would use day trade (%d remaining)",
                   side.upper(), ticker, remaining)
    record_day_trade(ticker, today)
    return True


def _post_chart_throttled(now_iso):
    """Post equity chart to Discord, but at most once per CHART_INTERVAL_SEC."""
    import time as _time
    now_ts = _time.time()
    if _CHART_TS_FILE.exists():
        try:
            last_ts = float(_CHART_TS_FILE.read_text().strip())
            if now_ts - last_ts < CHART_INTERVAL_SEC:
                logger.debug("Chart post throttled (last %.0fs ago)",
                             now_ts - last_ts)
                return
        except (ValueError, OSError):
            pass
    try:
        from lib.chart import equity_chart_png
        hist = get_portfolio_history(period="1M", timeframe="1D")
        if hist.get("equity"):
            png = equity_chart_png(hist)
            if png and update_chart(png, content="📈 Portfolio — 1M"):
                LOGS_DIR.mkdir(parents=True, exist_ok=True)
                _CHART_TS_FILE.write_text(str(now_ts))
    except Exception as e:
        logger.warning("Chart error: %s", e)


def main():
    validate_env()
    now = datetime.utcnow().isoformat() + "Z"
    today = now[:10]

    account = get_account()
    if not account:
        logger.error("Failed to get account")
        print("Failed to get account", file=sys.stderr)
        return
    actual_equity = float(account.get("equity", 0))
    equity = SIMULATED_BALANCE if SIMULATED_BALANCE > 0 else actual_equity
    positions = get_positions()

    if SIMULATED_BALANCE > 0:
        logger.info("SIMULATED BALANCE: $%.2f (actual account: $%.2f)",
                    equity, actual_equity)

    # PDT protection (live mode, accounts < $25K)
    pdt_active = LIVE_MODE and is_pdt_restricted(equity)
    if LIVE_MODE:
        logger.info("LIVE MODE — PDT %s (equity $%.0f, %d day trades used)",
                    "ACTIVE" if pdt_active else "exempt (>$25K)",
                    equity, count_day_trades())
        cleanup_old_records()

    cooldown_tickers = _load_cooldown(today)
    if cooldown_tickers:
        logger.info("Cooldown active today for: %s", ", ".join(sorted(cooldown_tickers)))

    peaks = _load_peaks()

    # Daily loss circuit breaker (always uses actual equity, not simulated)
    todays_decisions = [d for d in load_recent_decisions(limit=500)
                        if d.get("timestamp", "")[:10] == today]
    day_open_equity = (float(todays_decisions[0].get("portfolio_value", actual_equity))
                       if todays_decisions else actual_equity)
    day_drawdown = ((actual_equity - day_open_equity) / day_open_equity
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

        # Profit-take full: +8% (PDT-checked — skip if it would waste a day trade)
        if plpc >= PROFIT_TAKE_FULL_PCT:
            if not _check_pdt(ticker, "sell", today, todays_decisions, pdt_active):
                continue
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

        # Profit-take half: +4% (PDT-checked)
        if plpc >= PROFIT_TAKE_HALF_PCT:
            if not _check_pdt(ticker, "sell", today, todays_decisions, pdt_active):
                continue
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

    # === PHASE 1b: Dust cleanup — sell tiny positions that can't be managed ===
    dust_threshold = equity * DUST_THRESHOLD_PCT
    for pos in positions:
        ticker = pos["ticker"]
        mv = float(pos.get("market_value", 0))
        qty = int(pos["qty"])
        available_qty = pos.get("available_qty", qty)
        if mv < dust_threshold and available_qty > 0 and qty > 0:
            plpc = float(pos.get("unrealized_plpc", 0) or 0)
            sell(ticker, min(qty, available_qty))
            sell_candidates.append((ticker, qty, 0, "dust-cleanup"))
            log_decision({"timestamp": now, "action": "sell", "ticker": ticker,
                          "shares": qty, "reason": "dust-cleanup (< 0.5% of portfolio)",
                          "plpc": plpc, "price": pos.get("current_price"),
                          "portfolio_value": equity})
            log_outcome({"timestamp": now, "ticker": ticker, "action": "sell",
                         "reason": "dust-cleanup", "plpc": plpc, "shares": qty})
            peaks.pop(ticker, None)
            logger.info("DUST-CLEANUP %s: $%.0f < $%.0f threshold", ticker, mv,
                        dust_threshold)

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
                    if not _check_pdt(ticker, "sell", today, todays_decisions,
                                      pdt_active):
                        continue
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

                # SMA trend filter: only buy dips in uptrends (skip if insufficient data)
                sma = None
                cur_close = close_prices[-1] if close_prices else 0
                if len(close_prices) >= MIN_BARS_FOR_SMA:
                    sma = compute_sma(close_prices, SMA_PERIOD)
                if sma and cur_close < sma * 0.95:
                    logger.info("Skipping buy %s: price $%.2f > 5%% below SMA%d $%.2f",
                                ticker, cur_close, SMA_PERIOD, sma)
                    continue

                # Volume confirmation: not abnormally low (IEX volume underreports)
                vol_avg = avg_volume(bars, 20)
                last_vol = bars[-1].get("volume", 0) if bars else 0
                if vol_avg and vol_avg > 0 and last_vol < vol_avg * VOLUME_SPIKE_RATIO:
                    logger.info("Skipping buy %s: volume %d < %.0f (%.1fx avg required)",
                                ticker, last_vol, vol_avg * VOLUME_SPIKE_RATIO,
                                VOLUME_SPIKE_RATIO)
                    continue

                # RSI momentum: must be turning up (not still falling)
                if not rsi_turning_up(close_prices):
                    logger.info("Skipping buy %s: RSI %.1f still falling", ticker, rsi)
                    continue

                # ── Sizing (notional / dollar-based for fractional share support) ──
                alloc_pct = ALLOC_STRONG if rsi < RSI_STRONG_THRESHOLD else ALLOC_NORMAL
                max_new_exposure = equity * MAX_EXPOSURE_PCT - current_exposure
                if max_new_exposure <= 0:
                    continue
                acct = get_account()
                fresh_bp = float(acct.get("buying_power", 0)) if acct else 0
                buying_power = min(remaining_bp, fresh_bp) * BUY_BUFFER
                notional = equity * alloc_pct
                notional = min(notional, max_new_exposure, buying_power)
                if notional < 1.0:
                    logger.info("Skipping buy %s: notional $%.2f too small", ticker,
                                notional)
                    continue
                if not _check_pdt(ticker, "buy", today, todays_decisions, pdt_active):
                    continue

                buy_notional(ticker, notional)
                remaining_bp = max(0, remaining_bp - notional)
                current_exposure += notional
                n_positions += 1
                buy_candidates.append((ticker, 0, rsi,
                                       f"RSI buy ${notional:.0f} ({rsi:.1f})"))
                log_decision({"timestamp": now, "action": "buy", "ticker": ticker,
                              "notional": round(notional, 2), "rsi": rsi,
                              "allocation_pct": alloc_pct, "portfolio_value": equity,
                              "filters": {
                                  "sma": round(sma, 2) if sma else None,
                                  "vol_ratio": round(last_vol / vol_avg, 2) if vol_avg else None,
                              }})
                log_outcome({"timestamp": now, "ticker": ticker, "action": "buy",
                             "reason": f"RSI {rsi:.1f}", "notional": round(notional, 2)})

    # === PHASE 3: Add to winners when cash is too high ===
    if not buys_halted:
        acct = get_account()
        cash_now = float(acct.get("cash", 0)) if acct else 0
        positions = get_positions()
        current_exposure = _total_market_value(positions)
        if cash_now > equity * ADD_TO_WINNERS_CASH_PCT:
            winners = [p for p in positions
                       if float(p.get("unrealized_plpc", 0) or 0) >= ADD_TO_WINNER_MIN_PLPC]
            winners.sort(key=lambda x: -float(x.get("unrealized_plpc", 0) or 0))
            for pos in winners[:3]:
                ticker = pos["ticker"]
                mv = float(pos.get("market_value", 0))
                if mv >= equity * ADD_TO_WINNER_MAX_PCT:
                    continue
                if current_exposure >= equity * MAX_EXPOSURE_PCT:
                    break
                price = float(pos.get("current_price", 0))
                if price <= 0:
                    continue
                notional = min(
                    equity * ADD_TO_WINNER_ALLOC,
                    equity * ADD_TO_WINNER_MAX_PCT - mv,
                    equity * MAX_EXPOSURE_PCT - current_exposure)
                if notional < 1.0:
                    continue
                buy_notional(ticker, notional)
                current_exposure += notional
                plpc = float(pos.get("unrealized_plpc", 0) or 0)
                buy_candidates.append((ticker, 0, 0,
                                       f"add-to-winner ${notional:.0f}"
                                       f" ({plpc * 100:+.1f}%)"))
                log_decision({"timestamp": now, "action": "buy", "ticker": ticker,
                              "notional": round(notional, 2),
                              "reason": f"add-to-winner (cash"
                                        f" {cash_now / equity * 100:.0f}%)",
                              "portfolio_value": equity})
                log_outcome({"timestamp": now, "ticker": ticker, "action": "buy",
                             "reason": "add-to-winner",
                             "notional": round(notional, 2)})
                logger.info("ADD-TO-WINNER %s: +$%.2f (was %+.1f%%)",
                            ticker, notional, plpc * 100)

    # === Summary & Discord output ===
    final_account = get_account()
    final_positions = get_positions()
    final_equity = float(final_account.get("equity", 0)) if final_account else equity
    actual_equity = final_equity
    daily_pl = sum(float(p.get("unrealized_pl", 0) or 0) for p in final_positions)
    n_pos = len(final_positions)
    exposure = _total_market_value(final_positions)
    # When simulated, use cap for display; otherwise actual equity
    display_equity = equity if SIMULATED_BALANCE > 0 else final_equity
    exposure_pct = (exposure / display_equity * 100) if display_equity > 0 else 0

    eq_str = (f"${display_equity / 1_000_000:.1f}M" if display_equity >= 1_000_000
              else f"${display_equity / 1_000:.1f}K" if display_equity >= 1_000
              else f"${display_equity:,.0f}")
    pl_sign = "+" if daily_pl >= 0 else ""
    pl_pct = (daily_pl / display_equity * 100) if display_equity > 0 else 0
    start_val = SIMULATED_BALANCE if SIMULATED_BALANCE > 0 else 100_000
    # When sim: show actual above cap; else normal all-time change
    from_start = (actual_equity - SIMULATED_BALANCE) if SIMULATED_BALANCE > 0 else (final_equity - start_val)
    from_sign = "+" if from_start >= 0 else ""
    status_line = (f"📊 {eq_str} ({from_sign}${from_start:,.0f})"
                   f" · {pl_sign}${daily_pl:,.0f} today"
                   f" · {n_pos} pos · {exposure_pct:.0f}%")

    held = {p["ticker"] for p in final_positions}
    watches = sorted([(t, r) for t, r in all_rsi.items() if t not in held and r < 35],
                     key=lambda x: x[1])[:3]

    had_trades = bool(sell_candidates or buy_candidates)

    # ── #trades channel: only when trades happened, with context ──
    if had_trades:
        trades_lines = []
        for t, q, r, reason in sell_candidates:
            pos = next((p for p in positions if p["ticker"] == t), None)
            plpc_str = ""
            if pos:
                plpc_str = f" ({float(pos.get('unrealized_plpc', 0)) * 100:+.1f}%)"
            trades_lines.append(f"🔴 SELL {t} ×{q}{plpc_str} — {reason}")
        for t, q, r, reason in buy_candidates:
            trades_lines.append(f"🟢 BUY {t} — {reason}")
        trades_lines.append(f"─\n{status_line}")
        post_trades("\n".join(trades_lines))

    # ── #cycles (stdout → OpenClaw): clean, no log lines ──
    # Always print status line for cron heartbeat monitoring
    cycle_lines = [status_line]
    if sell_candidates:
        sold_parts = []
        for t, q, _, reason in sell_candidates:
            short = reason.split("(")[0].strip().replace("profit-take-", "TP-")
            sold_parts.append(f"{t} ×{q} ({short})")
        cycle_lines.append("Sold: " + ", ".join(sold_parts))
    if buy_candidates:
        bought_parts = [f"{t} ({reason})" for t, _, _, reason in buy_candidates]
        cycle_lines.append("Bought: " + ", ".join(bought_parts))
    if buys_halted:
        cycle_lines.append(
            f"⚠ CIRCUIT BREAKER: down {day_drawdown * 100:.1f}% today")
    if watches:
        cycle_lines.append(
            "👀 " + ", ".join(f"{t} RSI {r:.0f}" for t, r in watches))
    print("\n".join(cycle_lines))

    # ── Self-improvement logging (always) ──
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

    # ── #dashboard: compact overview with risk alerts ──
    near_stop = [p for p in final_positions
                 if float(p.get("unrealized_plpc", 0) or 0) < -0.02]
    top_winners = sorted(final_positions,
                         key=lambda x: -float(x.get("unrealized_plpc", 0) or 0))[:5]
    if SIMULATED_BALANCE > 0:
        dash = [
            f"**📊 AutoTrader** — {eq_str} sim cap (actual ${actual_equity:,.0f})",
            f"P&L today: {pl_sign}${daily_pl:,.0f} ({pl_sign}{pl_pct:.1f}%)"
            f" · {n_pos} positions · {exposure_pct:.0f}% exposure",
        ]
    else:
        dash = [
            f"**📊 AutoTrader** — {eq_str} ({from_sign}${from_start:,.0f} all-time)",
            f"P&L today: {pl_sign}${daily_pl:,.0f} ({pl_sign}{pl_pct:.1f}%)"
            f" · {n_pos} positions · {exposure_pct:.0f}% exposure",
        ]
    if near_stop:
        alerts = []
        for p in sorted(near_stop, key=lambda x: float(x.get("unrealized_plpc", 0))):
            plpc = float(p.get("unrealized_plpc", 0)) * 100
            alerts.append(f"{p['ticker']} {plpc:.1f}%")
        dash.append(f"⚠ **Near stop-loss:** {', '.join(alerts)}")
    if top_winners:
        dash.append("")
        dash.append("**Top movers:**")
        for p in top_winners:
            mv = float(p.get("market_value", 0))
            plpc = float(p.get("unrealized_plpc", 0) or 0) * 100
            sign = "+" if plpc >= 0 else ""
            mv_str = f"${mv / 1000:.1f}K" if mv >= 1000 else f"${mv:.0f}"
            dash.append(f"• {p['ticker']} {mv_str} ({sign}{plpc:.1f}%)")
    if watches:
        watch_str = ", ".join(f"{t} RSI {r:.0f}" for t, r in watches)
        dash.append(f"\n👀 **Watching:** {watch_str}")
    if cooldown_tickers:
        dash.append(f"🚫 Cooldown: {', '.join(sorted(cooldown_tickers))}")
    dash.append(f"\n_Updated {now[11:16]} UTC_")
    try:
        update_dashboard("\n".join(dash))
    except Exception as e:
        logger.warning("Dashboard update error: %s", e)

    # ── #charts: throttled to once per 30 min ──
    _post_chart_throttled(now)


if __name__ == "__main__":
    main()
