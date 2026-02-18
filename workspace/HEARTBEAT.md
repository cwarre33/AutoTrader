# AutoTrader Heartbeat Checklist

On every heartbeat, check the following:

1. **Is it market hours?** (Mon-Fri, 9:30 AM - 4:00 PM Eastern Time)
   - If NO: respond HEARTBEAT_OK
   - If YES: continue to step 2

2. **Run a trading scan** using the autotrader skill:
   - Call `python workspace/tools/alpaca_tool.py account` to check equity
   - Call `python workspace/tools/alpaca_tool.py positions` to check holdings
   - Check for stop-loss triggers (unrealized_plpc < -0.08) and sell immediately if found
   - Scan the watchlist for RSI signals using `python workspace/tools/alpaca_tool.py bars`
   - Execute trades if rules are met
   - Log all decisions to workspace/logs/decisions.jsonl
   - Send a summary message to the user

3. **Emergency check**: If any position has > 8% loss, sell immediately even outside a full scan
