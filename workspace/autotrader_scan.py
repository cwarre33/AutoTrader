#!/usr/bin/env python3
"""Aggressive RSI mean-reversion scanner (alternate entry point).

Same strategy as scan_autotrader.py:
- Buy:  RSI < 40 → 10%, RSI < 30 → 15%, RSI < 20 → 20% equity
- Sell: RSI > 65 → all, RSI > 55 → half
- Profit-take: +5% → all, +3% → half
- Stop-loss: -3% → dump
"""
import json, subprocess, sys, os, datetime, math

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f'Error running {cmd}:', result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()

def get_json(cmd):
    out = run_cmd(cmd)
    return json.loads(out)

def compute_rsi(closes, period=14):
    if len(closes) < period+1:
        return None
    gains = []
    losses = []
    for i in range(1, period+1):
        change = closes[i] - closes[i-1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period+1, len(closes)):
        change = closes[i] - closes[i-1]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = (avg_gain * (period-1) + gain) / period
        avg_loss = (avg_loss * (period-1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def main():
    account = get_json('python tools/alpaca_tool.py account')
    positions = get_json('python tools/alpaca_tool.py positions')
    pos_dict = {p['ticker']: p for p in positions}
    equity = float(account['equity'])
    decisions = []

    # === PHASE 1: Stop-loss and profit-taking ===
    for ticker, pos in list(pos_dict.items()):
        plpc = float(pos['unrealized_plpc'])
        qty = int(pos['qty'])

        # Tight stop-loss: -3%
        if plpc < -0.03:
            get_json(f'python tools/alpaca_tool.py sell {ticker} {qty}')
            decisions.append({"timestamp": datetime.datetime.utcnow().isoformat(),
                "action": "sell", "ticker": ticker, "shares": qty,
                "reason": "stop-loss -3%", "plpc": plpc, "price": float(pos['current_price'])})
            del pos_dict[ticker]
            continue

        # Profit-take: +5% sell all
        if plpc >= 0.05:
            get_json(f'python tools/alpaca_tool.py sell {ticker} {qty}')
            decisions.append({"timestamp": datetime.datetime.utcnow().isoformat(),
                "action": "sell", "ticker": ticker, "shares": qty,
                "reason": "profit-take +5%", "plpc": plpc, "price": float(pos['current_price'])})
            del pos_dict[ticker]
            continue

        # Profit-take: +3% sell half
        if plpc >= 0.03:
            sell_qty = qty // 2
            if sell_qty > 0:
                get_json(f'python tools/alpaca_tool.py sell {ticker} {sell_qty}')
                decisions.append({"timestamp": datetime.datetime.utcnow().isoformat(),
                    "action": "sell", "ticker": ticker, "shares": sell_qty,
                    "reason": "profit-take +3% half", "plpc": plpc, "price": float(pos['current_price'])})

    # === PHASE 2: RSI scan ===
    watchlists = [
        "AAPL,MSFT,NVDA,TSLA,AMZN,META,GOOG,AMD,INTC,BA",
        "DIS,NFLX,JPM,V,MA,UNH,XOM,CVX,PFE,KO",
        "WMT,COST,HD,CRM,ORCL,AVGO,MU,QCOM,SOFI,PLTR",
        "HOOD,IBIT,TQQQ"
    ]
    all_bars = {}
    for wl in watchlists:
        bars = get_json(f'python tools/alpaca_tool.py bars {wl} --days 30')
        all_bars.update(bars)

    for ticker, bars in all_bars.items():
        closes = [float(b['close']) for b in bars]
        rsi = compute_rsi(closes)
        if rsi is None:
            continue

        if ticker in pos_dict:
            # RSI sell rules
            pos = pos_dict[ticker]
            qty = int(pos['qty'])
            if rsi > 65:
                get_json(f'python tools/alpaca_tool.py sell {ticker} {qty}')
                decisions.append({"timestamp": datetime.datetime.utcnow().isoformat(),
                    "action": "sell", "ticker": ticker, "shares": qty,
                    "reason": f"RSI sell-all ({rsi:.1f})", "rsi": rsi, "price": float(pos['current_price'])})
            elif rsi > 55:
                sell_qty = qty // 2
                if sell_qty > 0:
                    get_json(f'python tools/alpaca_tool.py sell {ticker} {sell_qty}')
                    decisions.append({"timestamp": datetime.datetime.utcnow().isoformat(),
                        "action": "sell", "ticker": ticker, "shares": sell_qty,
                        "reason": f"RSI sell-half ({rsi:.1f})", "rsi": rsi, "price": float(pos['current_price'])})
        else:
            # Aggressive buy rules
            if rsi < 20:
                alloc_pct = 0.20
            elif rsi < 30:
                alloc_pct = 0.15
            elif rsi < 40:
                alloc_pct = 0.10
            else:
                continue
            snap = get_json(f'python tools/alpaca_tool.py snapshot {ticker}')
            price = float(snap['latest_trade_price'])
            shares = math.floor(equity * alloc_pct / price)
            if shares <= 0:
                continue
            get_json(f'python tools/alpaca_tool.py buy {ticker} {shares}')
            decisions.append({"timestamp": datetime.datetime.utcnow().isoformat(),
                "action": "buy", "ticker": ticker, "shares": shares,
                "reason": f"RSI {rsi:.1f} buy", "rsi": rsi, "price": price, "alloc_pct": alloc_pct})

    # Log decisions
    log_path = 'logs/decisions.jsonl'
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a') as f:
        for d in decisions:
            f.write(json.dumps(d) + '\n')

    summary = {"portfolio_value": equity, "decisions": decisions, "num_trades": len(decisions)}
    print(json.dumps(summary))

if __name__ == '__main__':
    main()
