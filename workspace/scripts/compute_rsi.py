import json, sys, math
import sys

data = json.load(sys.stdin)
results = {}
for ticker, bars in data.items():
    closes = [float(b['close']) for b in bars]
    if len(closes) < 15:
        continue
    # compute changes
    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]
    # first 14 periods
    avg_gain = sum(gains[:14]) / 14
    avg_loss = sum(losses[:14]) / 14
    rsi_vals = []
    # first RSI
    if avg_loss == 0:
        rsi = 100
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    rsi_vals.append(rsi)
    # subsequent
    for i in range(14, len(gains)):
        gain = gains[i]
        loss = losses[i]
        avg_gain = (avg_gain * 13 + gain) / 14
        avg_loss = (avg_loss * 13 + loss) / 14
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        rsi_vals.append(rsi)
    results[ticker] = rsi_vals[-1]
print(json.dumps(results))
