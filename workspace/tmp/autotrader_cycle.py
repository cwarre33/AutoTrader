#!/usr/bin/env python3
"""Aggressive autotrader cycle (tmp entry point).

Same strategy as scan_autotrader.py:
- Buy:  RSI < 40 → 10%, RSI < 30 → 15%, RSI < 20 → 20% equity
- Sell: RSI > 65 → all, RSI > 55 → half
- Profit-take: +5% → all, +3% → half
- Stop-loss: -3% → dump
"""
import json, os, subprocess, sys, datetime, math

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f'Command failed: {cmd}\n{result.stderr}', file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()

def get_json_output(cmd):
    out = run_cmd(cmd)
    return json.loads(out)

def append_decision(entry):
    os.makedirs('logs', exist_ok=True)
    with open('logs/decisions.jsonl', 'a') as f:
        f.write(json.dumps(entry) + '\n')

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
        avg_gain = (avg_gain * (period-1) + gain) / period
        avg_loss = (avg_loss * (period-1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))

def main():
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now_str = now_dt.isoformat().replace('+00:00','Z')
    account = get_json_output('python tools/alpaca_tool.py account')
    equity = float(account.get('equity',0))
    buying_power = float(account.get('buying_power',0))
    positions = get_json_output('python tools/alpaca_tool.py positions')
    pos_map = {p['ticker']: p for p in positions}
    actions = []

    # === PHASE 1: Stop-loss and profit-taking ===
    for ticker in list(pos_map.keys()):
        pos = pos_map[ticker]
        plpc = float(pos.get('unrealized_plpc', 0))
        qty = int(pos.get('qty', 0))
        if qty <= 0:
            continue

        # Tight stop-loss: -3%
        if plpc < -0.03:
            get_json_output(f'python tools/alpaca_tool.py sell {ticker} {qty}')
            actions.append({'action':'sell','ticker':ticker,'shares':qty,'reason':'stop-loss -3%','plpc':plpc})
            append_decision({"timestamp":now_str,"action":"sell","ticker":ticker,"shares":qty,
                             "reason":"stop-loss -3%","plpc":plpc,"price":float(pos.get('current_price',0))})
            del pos_map[ticker]
            continue

        # Profit-take: +5% sell all
        if plpc >= 0.05:
            get_json_output(f'python tools/alpaca_tool.py sell {ticker} {qty}')
            actions.append({'action':'sell','ticker':ticker,'shares':qty,'reason':'profit-take +5%','plpc':plpc})
            append_decision({"timestamp":now_str,"action":"sell","ticker":ticker,"shares":qty,
                             "reason":"profit-take +5%","plpc":plpc,"price":float(pos.get('current_price',0))})
            del pos_map[ticker]
            continue

        # Profit-take: +3% sell half
        if plpc >= 0.03:
            half = qty // 2
            if half > 0:
                get_json_output(f'python tools/alpaca_tool.py sell {ticker} {half}')
                actions.append({'action':'sell','ticker':ticker,'shares':half,'reason':'profit-take +3% half','plpc':plpc})
                append_decision({"timestamp":now_str,"action":"sell","ticker":ticker,"shares":half,
                                 "reason":"profit-take +3% half","plpc":plpc,"price":float(pos.get('current_price',0))})

    # === PHASE 2: RSI scan ===
    watchlist = "AAPL,MSFT,NVDA,TSLA,AMZN,META,GOOG,AMD,INTC,BA,DIS,NFLX,JPM,V,MA,UNH,XOM,CVX,PFE,KO,WMT,COST,HD,CRM,ORCL,AVGO,MU,QCOM,SOFI,PLTR,HOOD,IBIT,TQQQ"
    bars_data = get_json_output(f"python tools/alpaca_tool.py bars {watchlist} --days 30")

    rsi_map = {}
    for ticker, bars in bars_data.items():
        closes = [float(b['close']) for b in bars]
        rsi = compute_rsi(closes)
        if rsi is not None:
            rsi_map[ticker] = rsi

    for ticker, rsi in rsi_map.items():
        if ticker in pos_map:
            # RSI sell rules
            pos = pos_map[ticker]
            qty = int(pos.get('qty',0))
            if rsi > 65:
                get_json_output(f'python tools/alpaca_tool.py sell {ticker} {qty}')
                actions.append({'action':'sell','ticker':ticker,'shares':qty,'reason':f'RSI sell-all ({rsi:.1f})'})
                append_decision({"timestamp":now_str,"action":"sell","ticker":ticker,"shares":qty,
                                 "reason":f"RSI sell-all ({rsi:.1f})","rsi":rsi,"price":float(pos.get('current_price',0))})
                pos_map.pop(ticker,None)
            elif rsi > 55:
                half = qty//2
                if half > 0:
                    get_json_output(f'python tools/alpaca_tool.py sell {ticker} {half}')
                    actions.append({'action':'sell','ticker':ticker,'shares':half,'reason':f'RSI sell-half ({rsi:.1f})'})
                    append_decision({"timestamp":now_str,"action":"sell","ticker":ticker,"shares":half,
                                     "reason":f"RSI sell-half ({rsi:.1f})","rsi":rsi,"price":float(pos.get('current_price',0))})
            continue

        # Aggressive buy rules
        if rsi < 20:
            alloc_pct = 0.20
        elif rsi < 30:
            alloc_pct = 0.15
        elif rsi < 40:
            alloc_pct = 0.10
        else:
            continue

        snap = get_json_output(f'python tools/alpaca_tool.py snapshot {ticker}')
        price = float(snap.get('latest_trade_price',0))
        if price <= 0:
            continue
        shares = math.floor(equity * alloc_pct / price)
        if shares <= 0:
            continue

        # Check news for bearish signals
        try:
            news = get_json_output(f'python tools/alpaca_tool.py actions {ticker}')
            if isinstance(news, list):
                bearish = any('downgrade' in (item.get('headline','') if isinstance(item,dict) else str(item)).lower()
                              or 'lawsuit' in (item.get('headline','') if isinstance(item,dict) else str(item)).lower()
                              for item in news)
                if bearish:
                    continue
        except:
            pass

        get_json_output(f'python tools/alpaca_tool.py buy {ticker} {shares}')
        actions.append({'action':'buy','ticker':ticker,'shares':shares,'reason':f'RSI {rsi:.1f} buy','price':price})
        append_decision({"timestamp":now_str,"action":"buy","ticker":ticker,"shares":shares,
                         "rsi":rsi,"price":price,"allocation_pct":alloc_pct})

    summary = {'timestamp':now_str,'equity':equity,'buying_power':buying_power,
               'actions':actions,'rsi_sample':dict(list(rsi_map.items())[:10])}
    print(json.dumps(summary))

if __name__=='__main__':
    main()
