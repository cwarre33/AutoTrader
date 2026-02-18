import json, subprocess, sys, math

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print('Error', result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()

def get_json(cmd):
    return json.loads(run_cmd(cmd))

def compute_rsi(closes, period=14):
    if len(closes) < period+1:
        return None
    gains = []
    losses = []
    for i in range(1, period+1):
        change = closes[i] - closes[i-1]
        gains.append(max(change,0))
        losses.append(abs(min(change,0)))
    avg_gain = sum(gains)/period
    avg_loss = sum(losses)/period
    for i in range(period+1, len(closes)):
        change = closes[i] - closes[i-1]
        gain = max(change,0)
        loss = abs(min(change,0))
        avg_gain = (avg_gain*(period-1)+gain)/period
        avg_loss = (avg_loss*(period-1)+loss)/period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))

watchlists = [
    "AAPL,MSFT,NVDA,TSLA,AMZN,META,GOOG,AMD,INTC,BA",
    "DIS,NFLX,JPM,V,MA,UNH,XOM,CVX,PFE,KO",
    "WMT,COST,HD,CRM,ORCL,AVGO,MU,QCOM,SOFI,PLTR"
]
all_bars = {}
for wl in watchlists:
    bars = get_json(f'python tools/alpaca_tool.py bars {wl} --days 30')
    all_bars.update(bars)

rsi_list = []
for ticker, bars in all_bars.items():
    closes = [float(b['close']) for b in bars]
    rsi = compute_rsi(closes)
    if rsi is not None:
        rsi_list.append((ticker, rsi))

# sort by lowest RSI (oversold) and highest RSI (overbought)
low = sorted(rsi_list, key=lambda x: x[1])[:5]
high = sorted(rsi_list, key=lambda x: x[1], reverse=True)[:5]
print('Low RSI:', low)
print('High RSI:', high)
