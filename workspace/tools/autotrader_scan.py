import json, subprocess, os, sys, datetime, math

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f'Command failed: {cmd}\n{result.stderr}', file=sys.stderr)
        return None
    return result.stdout.strip()

def get_json_output(cmd):
    out = run_cmd(cmd)
    if out is None:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        print(f'Failed to parse JSON from command: {cmd}\nOutput: {out}', file=sys.stderr)
        return None

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
    for i in range(period+1, len(closes)):
        change = closes[i] - closes[i-1]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def main():
    # Ensure logs directory
    os.makedirs('logs', exist_ok=True)
    decision_log_path = 'logs/decisions.jsonl'
    # 1. Account
    account = get_json_output('python tools/alpaca_tool.py account')
    if not account:
        return
    equity = float(account.get('equity', 0))
    buying_power = float(account.get('buying_power', 0))
    # 2. Positions
    positions = get_json_output('python tools/alpaca_tool.py positions') or []
    # Map ticker -> position dict
    pos_map = {p['ticker']: p for p in positions}
    # 3. Stop-loss check
    for ticker, pos in list(pos_map.items()):
        plpc = float(pos.get('unrealized_plpc', 0))
        if plpc < -0.08:
            qty = int(pos.get('qty', 0))
            if qty > 0:
                sell_res = get_json_output(f'python tools/alpaca_tool.py sell {ticker} {qty}')
                decision = {
                    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
                    'action': 'sell',
                    'ticker': ticker,
                    'reason': 'stop-loss',
                    'shares': qty,
                    'price': None,
                    'rsi': None,
                    'portfolio_value': equity
                }
                with open(decision_log_path, 'a') as f:
                    f.write(json.dumps(decision) + '\n')
                # remove from map
                pos_map.pop(ticker, None)
    # 4. Get bars for watchlist groups
    groups = [
        "AAPL,MSFT,NVDA,TSLA,AMZN,META,GOOG,AMD,INTC,BA",
        "DIS,NFLX,JPM,V,MA,UNH,XOM,CVX,PFE,KO",
        "WMT,COST,HD,CRM,ORCL,AVGO,MU,QCOM,SOFI,PLTR"
    ]
    bars_data = {}
    for grp in groups:
        cmd = f'python tools/alpaca_tool.py bars {grp} --days 30'
        res = get_json_output(cmd)
        if res:
            bars_data.update(res)
    # 5. Compute RSI for each ticker
    rsi_map = {}
    for ticker, bars in bars_data.items():
        # Ensure sorted by date ascending
        bars_sorted = sorted(bars, key=lambda x: x['date'])
        closes = [float(b['close']) for b in bars_sorted]
        rsi = compute_rsi(closes)
        if rsi is not None:
            rsi_map[ticker] = rsi
    # 6. Prepare decisions list
    decisions = []
    # Helper to log decision
    def log_decision(dec):
        with open(decision_log_path, 'a') as f:
            f.write(json.dumps(dec) + '\n')
    # 7. Process sell signals for existing positions
    for ticker, pos in list(pos_map.items()):
        qty = int(pos.get('qty', 0))
        if qty == 0:
            continue
        rsi = rsi_map.get(ticker)
        # Get snapshot price
        snap = get_json_output(f'python tools/alpaca_tool.py snapshot {ticker}')
        price = float(snap.get('latest_trade_price', 0)) if snap else None
        # Determine sell action
        sell_qty = 0
        reason = None
        if rsi is not None:
            if rsi > 75:
                sell_qty = qty
                reason = 'strong sell RSI'>75
            elif rsi >= 60:
                sell_qty = qty // 2
                reason = 'partial sell RSI 60-75'
        # Additional: check news bearish (skip for simplicity)
        if sell_qty > 0:
            sell_res = get_json_output(f'python tools/alpaca_tool.py sell {ticker} {sell_qty}')
            dec = {
                'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
                'action': 'sell',
                'ticker': ticker,
                'reason': reason,
                'shares': sell_qty,
                'price': price,
                'rsi': rsi,
                'portfolio_value': equity
            }
            log_decision(dec)
            # update position map
            remaining = qty - sell_qty
            if remaining <= 0:
                pos_map.pop(ticker, None)
    # 8. Buy signals for tickers not held
    # Determine current number of positions
    current_positions = len(pos_map)
    max_positions = 10
    for ticker, rsi in rsi_map.items():
        if ticker in pos_map:
            continue
        if rsi >= 30:
            continue
        # Get snapshot price
        snap = get_json_output(f'python tools/alpaca_tool.py snapshot {ticker}')
        if not snap:
            continue
        price = float(snap.get('latest_trade_price', 0))
        if price <= 0:
            continue
        # Determine allocation percent
        if rsi < 20:
            alloc_pct = 0.05
            confidence = 'strong'
        else:
            alloc_pct = 0.025
            confidence = 'moderate'
        # Ensure not exceed max positions
        if current_positions >= max_positions:
            break
        allocation = equity * alloc_pct
        shares = math.floor(allocation / price)
        if shares <= 0:
            continue
        # Execute buy
        buy_res = get_json_output(f'python tools/alpaca_tool.py buy {ticker} {shares}')
        dec = {
            'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
            'action': 'buy',
            'ticker': ticker,
            'confidence': confidence,
            'rsi': rsi,
            'shares': shares,
            'price': price,
            'portfolio_value': equity
        }
        log_decision(dec)
        current_positions += 1
    # 9. Summary output
    # Re-fetch account for final values
    final_account = get_json_output('python tools/alpaca_tool.py account') or {}
    portfolio_val = final_account.get('equity')
    daily_pl = float(final_account.get('unrealized_pl', 0)) if 'unrealized_pl' in final_account else 0
    # Gather top 3 RSI signals (lowest RSI among watchlist)
    sorted_rsi = sorted(rsi_map.items(), key=lambda x: x[1])[:3]
    top_signal_str = ', '.join([f"{t}:{r:.1f}" for t,r in sorted_rsi])
    summary = f"Portfolio value: ${portfolio_val}, Daily P&L: ${daily_pl:.2f}. Top RSI signals: {top_signal_str}."
    print(summary)

if __name__ == '__main__':
    main()
