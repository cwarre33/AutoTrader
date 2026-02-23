import json, subprocess, os, sys, datetime, math

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f'Error running {cmd}:', result.stderr, file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # Might be plain output; return raw
        return result.stdout.strip()

def get_account():
    return run_cmd('python tools/alpaca_tool.py account')

def get_positions():
    data = run_cmd('python tools/alpaca_tool.py positions')
    return data if isinstance(data, list) else []

def sell(ticker, qty):
    return run_cmd(f'python tools/alpaca_tool.py sell {ticker} {qty}')

def get_bars(tickers):
    tickers_str=','.join(tickers)
    return run_cmd(f'python tools/alpaca_tool.py bars {tickers_str} --days 30')

def get_snapshot(ticker):
    return run_cmd(f'python tools/alpaca_tool.py snapshot {ticker}')

def get_actions(ticker):
    return run_cmd(f'python tools/alpaca_tool.py actions {ticker}')

def compute_rsi(closes):
    gains=[]; losses=[]
    for i in range(1,len(closes)):
        change=closes[i]-closes[i-1]
        gains.append(max(change,0))
        losses.append(abs(min(change,0)))
    if len(gains)<14:
        return None
    avg_gain=sum(gains[:14])/14
    avg_loss=sum(losses[:14])/14
    if avg_loss==0:
        return 100.0
    rs=avg_gain/avg_loss
    rsi=100- (100/(1+rs))
    # smooth subsequent if needed not needed for final
    return rsi

def load_decision_log():
    path='logs/decisions.jsonl'
    if not os.path.exists(path):
        return []
    entries=[]
    with open(path) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except:
                continue
    return entries

def append_log(entry):
    os.makedirs('logs', exist_ok=True)
    with open('logs/decisions.jsonl','a') as f:
        f.write(json.dumps(entry)+'\n')

def main():
    now=datetime.datetime.utcnow().isoformat()+'Z'
    account=get_account()
    equity=float(account.get('equity',0)) if account else 0
    positions=get_positions()
    # Stop-loss sell
    actions=[]
    for pos in positions:
        if float(pos.get('unrealized_plpc',0)) < -0.08:
            ticker=pos['ticker']
            qty=pos['qty']
            sell_res=sell(ticker, qty)
            actions.append({'type':'stoploss','ticker':ticker,'qty':qty,'result':sell_res})
            append_log({"timestamp":now,"action":"sell","ticker":ticker,"shares":qty,"price":pos.get('current_price'),"reason":"stoploss","portfolio_value":equity})
    # Build watchlist
    watchlist=["AAPL","MSFT","NVDA","TSLA","AMZN","META","GOOG","AMD","INTC","BA",
               "DIS","NFLX","JPM","V","MA","UNH","XOM","CVX","PFE","KO",
               "WMT","COST","HD","CRM","ORCL","AVGO","MU","QCOM","SOFI","PLTR"]
    # Get bars in three batches as per skill
    batches=[watchlist[:10],watchlist[10:20],watchlist[20:]]
    rsi_signals={}
    for batch in batches:
        bars=get_bars(batch)
        if not bars:
            continue
        for ticker in batch:
            data=bars.get(ticker)
            if not data:
                continue
            closes=[float(day['close']) for day in data]
            rsi=compute_rsi(closes)
            if rsi is None:
                continue
            rsi_signals[ticker]=rsi
    # Determine buy candidates
    decision_log=load_decision_log()
    bought=[]
    for ticker,rsi in rsi_signals.items():
        # Skip if already hold
        if any(p['ticker']==ticker for p in positions):
            continue
        # Simple buy rule
        if rsi<20:
            alloc=0.05*equity
        elif rsi<30:
            alloc=0.03*equity
        else:
            continue
        snap=get_snapshot(ticker)
        price=float(snap.get('latest_trade_price'))
        if not price or price<=0:
            continue
        shares=int(alloc//price)
        if shares<=0:
            continue
        # Execute buy
        buy_res=run_cmd(f'python tools/alpaca_tool.py buy {ticker} {shares}')
        bought.append({'ticker':ticker,'shares':shares,'price':price,'rsi':rsi})
        append_log({"timestamp":now,"action":"buy","ticker":ticker,"shares":shares,"price":price,"rsi":rsi,"portfolio_value":equity})
    # Summary
    summary={"equity":equity,"actions":actions,"bought":bought,"rsi_signals":sorted(rsi_signals.items(), key=lambda x:x[1])[:3]}
    print(json.dumps(summary))

if __name__=='__main__':
    main()
