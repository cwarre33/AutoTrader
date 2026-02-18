# AutoTrader Heartbeat Checklist — AGGRESSIVE MODE

On every heartbeat, check the following:

1. **Is it market hours?** (Mon-Fri, 9:30 AM - 4:00 PM Eastern Time)
   - If NO: respond HEARTBEAT_OK
   - If YES: continue to step 2

2. **Run the aggressive trading scan** using `python scan_autotrader.py`:
   - This script handles ALL logic: stop-losses, profit-taking, RSI buys/sells
   - **Stop-loss**: -3% unrealized → sell all immediately
   - **Profit-take**: +5% → sell all, +3% → sell half
   - **RSI sell**: > 65 → sell all, > 55 → sell half
   - **RSI buy**: < 20 → 20% equity, < 30 → 15% equity, < 40 → 10% equity
   - No max position limit — deploy capital aggressively
   - Log all decisions to logs/decisions.jsonl

3. **Emergency check**: If any position has > 3% loss, sell immediately even outside a full scan

4. **Always report**: After running, give a brief summary of actions taken and current portfolio state
