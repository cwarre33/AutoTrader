import json, math, sys, os

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    # Calculate initial avg gain/loss
    gains = []
    losses = []
    for i in range(1, period+1):
        change = closes[i] - closes[i-1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    # Wilder smoothing
    for i in range(period+1, len(closes)):
        change = closes[i] - closes[i-1]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = (avg_gain * (period-1) + gain) / period
        avg_loss = (avg_loss * (period-1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def main():
    data = {}
    # load all JSON files in tools directory matching bar_data*.json
    for fname in os.listdir('tools'):
        if fname.startswith('bar_data') and fname.endswith('.json'):
            with open(os.path.join('tools', fname)) as f:
                part = json.load(f)
                data.update(part)
    results = {}
    for ticker, bars in data.items():
        # sort by date just in case
        bars = sorted(bars, key=lambda b: b['date'])
        closes = [float(b['close']) for b in bars]
        rsi = compute_rsi(closes)
        results[ticker] = rsi
    # output
    json.dump(results, sys.stdout)

if __name__ == '__main__':
    main()
