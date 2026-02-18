#!/usr/bin/env python3
"""Aggressive RSI mean-reversion scanner.

Strategy: Buy dips hard, take profits fast, cut losses early.
- Buy:  RSI < 40 → 10% equity, RSI < 30 → 15% equity, RSI < 20 → 20% equity
- Sell: RSI > 65 → sell all, RSI > 55 → sell half
- Profit-take: +5% unrealized → sell all, +3% → sell half
- Stop-loss: -3% unrealized → sell all
- No max position limit (deploy capital aggressively)
"""
import subprocess, json, os, sys, datetime, math

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f'Command failed: {cmd}\n{result.stderr}', file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip()

def get_account():
    return run_cmd('python tools/alpaca_tool.py account')

def get_positions():
    return run_cmd('python tools/alpaca_tool.py positions') or []

def sell_position(ticker, qty):
    return run_cmd(f'python tools/alpaca_tool.py sell {ticker} {qty}')

def buy_position(ticker, qty):
    return run_cmd(f'python tools/alpaca_tool.py buy {ticker} {qty}')

def get_bars(tickers):
    tickers_str = ','.join(tickers)
    return run_cmd(f'python tools/alpaca_tool.py bars {tickers_str} --days 30')

def get_snapshot(ticker):
    return run_cmd(f'python tools/alpaca_tool.py snapshot {ticker}')

def compute_rsi(close_prices, period=14):
    if len(close_prices) < period+1:
        return None
    gains = []
    losses = []
    for i in range(1, period+1):
        change = close_prices[i] - close_prices[i-1]
        gains.append(max(change,0))
        losses.append(abs(min(change,0)))
    avg_gain = sum(gains)/period
    avg_loss = sum(losses)/period
    for i in range(period+1, len(close_prices)):
        change = close_prices[i] - close_prices[i-1]
        gain = max(change,0)
        loss = abs(min(change,0))
        avg_gain = (avg_gain*(period-1) + gain)/period
        avg_loss = (avg_loss*(period-1) + loss)/period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))

def log_decision(entry):
    os.makedirs('logs', exist_ok=True)
    with open('logs/decisions.jsonl','a') as f:
        f.write(json.dumps(entry)+'\n')

def main():
    now = datetime.datetime.utcnow().isoformat()+'Z'
    account = get_account()
    if not account:
        print('Failed to get account')
        return
    equity = float(account.get('equity',0))
    buying_power = float(account.get('buying_power',0))
    positions = get_positions()

    buy_candidates = []
    sell_candidates = []

    # === PHASE 1: Aggressive stop-loss and profit-taking on existing positions ===
    for pos in positions:
        ticker = pos['ticker']
        qty = int(pos['qty'])
        plpc = float(pos.get('unrealized_plpc',0) or 0)

        # Tight stop-loss: -3% → dump everything
        if plpc < -0.03:
            sell_res = sell_position(ticker, qty)
            sell_candidates.append((ticker, qty, 0, 'stop-loss'))
            log_decision({"timestamp":now,"action":"sell","ticker":ticker,"shares":qty,
                          "reason":"stop-loss -3%","plpc":plpc,"price":pos.get('current_price'),"portfolio_value":equity})
            continue

        # Profit-take: +5% → sell all
        if plpc >= 0.05:
            sell_res = sell_position(ticker, qty)
            sell_candidates.append((ticker, qty, 0, 'profit-take-full'))
            log_decision({"timestamp":now,"action":"sell","ticker":ticker,"shares":qty,
                          "reason":"profit-take +5%","plpc":plpc,"price":pos.get('current_price'),"portfolio_value":equity})
            continue

        # Profit-take: +3% → sell half
        if plpc >= 0.03:
            sell_qty = qty // 2
            if sell_qty > 0:
                sell_res = sell_position(ticker, sell_qty)
                sell_candidates.append((ticker, sell_qty, 0, 'profit-take-half'))
                log_decision({"timestamp":now,"action":"sell","ticker":ticker,"shares":sell_qty,
                              "reason":"profit-take +3% half","plpc":plpc,"price":pos.get('current_price'),"portfolio_value":equity})

    # Refresh positions after sells
    positions = get_positions()
    held_tickers = {p['ticker'] for p in positions}

    # === PHASE 2: RSI-based sells and buys ===
    groups = [
        ["AAPL","MSFT","NVDA","TSLA","AMZN","META","GOOG","AMD","INTC","BA"],
        ["DIS","NFLX","JPM","V","MA","UNH","XOM","CVX","PFE","KO"],
        ["WMT","COST","HD","CRM","ORCL","AVGO","MU","QCOM","SOFI","PLTR"],
        ["HOOD","IBIT","TQQQ"]
    ]
    all_rsi = {}  # for compact summary

    for tickers in groups:
        bars_data = get_bars(tickers)
        if not bars_data:
            continue
        for ticker in tickers:
            if ticker not in bars_data:
                continue
            bars = bars_data[ticker]
            close_prices = [float(b['close']) for b in bars]
            rsi = compute_rsi(close_prices)
            if rsi is None:
                continue
            all_rsi[ticker] = rsi

            if ticker in held_tickers:
                # RSI sell rules (aggressive)
                pos = next((p for p in positions if p['ticker']==ticker), None)
                if not pos:
                    continue
                qty = int(pos['qty'])
                sell_qty = 0
                reason = ''
                if rsi > 65:
                    sell_qty = qty
                    reason = f'RSI sell-all ({rsi:.1f})'
                elif rsi > 55:
                    sell_qty = qty // 2
                    reason = f'RSI sell-half ({rsi:.1f})'

                if sell_qty > 0:
                    sell_res = sell_position(ticker, sell_qty)
                    sell_candidates.append((ticker, sell_qty, rsi, reason))
                    log_decision({"timestamp":now,"action":"sell","ticker":ticker,"shares":sell_qty,
                                  "reason":reason,"rsi":rsi,"price":pos.get('current_price'),"portfolio_value":equity})
            else:
                # Aggressive buy rules
                if rsi < 20:
                    alloc_pct = 0.20  # 20% equity for deeply oversold
                elif rsi < 30:
                    alloc_pct = 0.15  # 15% equity for oversold
                elif rsi < 40:
                    alloc_pct = 0.10  # 10% equity for dipping
                else:
                    continue

                snapshot = get_snapshot(ticker)
                price = float(snapshot.get('latest_trade_price', 0)) if isinstance(snapshot, dict) else 0
                if price <= 0:
                    continue
                allocation = equity * alloc_pct
                shares = math.floor(allocation / price)
                if shares < 1:
                    continue
                buy_res = buy_position(ticker, shares)
                buy_candidates.append((ticker, shares, rsi, f'RSI buy ({rsi:.1f})'))
                log_decision({"timestamp":now,"action":"buy","ticker":ticker,"shares":shares,
                              "rsi":rsi,"price":price,"allocation_pct":alloc_pct,"portfolio_value":equity})

    # === Compact summary (notification-friendly) ===
    final_account = get_account()
    final_positions = get_positions()
    final_equity = float(final_account.get('equity', 0)) if final_account else equity
    daily_pl = float(final_account.get('unrealized_pl', 0)) if final_account and 'unrealized_pl' in final_account else 0
    n_pos = len(final_positions)

    # Abbreviate equity for small screens (98.4K, 1.2M)
    if final_equity >= 1_000_000:
        eq_str = f"${final_equity/1_000_000:.1f}M"
    else:
        eq_str = f"${final_equity/1_000:.1f}K"
    pl_sign = "+" if daily_pl >= 0 else ""
    pl_pct = (daily_pl / final_equity * 100) if final_equity > 0 else 0

    lines = []
    # Line 1: equity, P&L, position count
    lines.append(f"📊 {eq_str} · {pl_sign}${daily_pl:,.0f} ({pl_sign}{pl_pct:.2f}%) · {n_pos} positions")

    # Line 2: actions or "no trades"
    if sell_candidates or buy_candidates:
        parts = []
        if sell_candidates:
            parts.append("Sold: " + ", ".join(f"{t} {q}" for t, q, _, _ in sell_candidates))
        if buy_candidates:
            parts.append("Bought: " + ", ".join(f"{t} {q}" for t, q, _, _ in buy_candidates))
        lines.append(" · ".join(parts))
    else:
        lines.append("No trades this cycle.")

    # Line 3: one-line context (best watch or status)
    held = {p['ticker'] for p in final_positions}
    watches = [(t, r) for t, r in all_rsi.items() if t not in held and r < 45]
    watches.sort(key=lambda x: x[1])
    if watches:
        top = watches[:3]
        line3 = "Watching: " + ", ".join(f"{t} RSI {r:.0f}" for t, r in top)
        lines.append(line3)
    else:
        lines.append("No oversold signals. Holding.")

    print("\n".join(lines))

if __name__=="__main__":
    main()
