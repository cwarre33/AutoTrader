#!/usr/bin/env python3
import json, subprocess, sys, math

def get_bars(ticker):
    try:
        out = subprocess.check_output(["python", "tools/alpaca_tool.py", "bars", ticker, "--days", "30"], cwd="/home/node/.openclaw/workspace", text=True)
        return json.loads(out)
    except Exception as e:
        print(f"Error fetching bars for {ticker}: {e}", file=sys.stderr)
        return []

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, period+1):
        change = closes[i] - closes[i-1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    # Continue for remaining data
    for i in range(period+1, len(closes)):
        change = closes[i] - closes[i-1]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
    return rsi

def main():
    watchlist = [
        "AAPL","MSFT","NVDA","TSLA","AMZN","META","GOOG","AMD","INTC","BA",
        "DIS","NFLX","JPM","V","MA","UNH","XOM","CVX","PFE","KO",
        "WMT","COST","HD","CRM","ORCL","AVGO","MU","QCOM","SOFI","PLTR"
    ]
    results = []
    for ticker in watchlist:
        data = get_bars(ticker)
        if not data:
            continue
        closes = [float(entry["close"]) for entry in data[ticker]]
        rsi = compute_rsi(closes)
        if rsi is not None:
            results.append((ticker, rsi))
    # sort by RSI ascending
    results.sort(key=lambda x: x[1])
    for t, r in results:
        print(f"{t}: {r:.2f}")

if __name__ == "__main__":
    main()
