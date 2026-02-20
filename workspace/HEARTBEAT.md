# AutoTrader Heartbeat Checklist — AGGRESSIVE MODE

**Tip:** Scans can take 30+ seconds. Prefer cron for scheduled scans to avoid blocking Discord. Use heartbeat for ad-hoc checks.

On every heartbeat, check the following:

1. **Is it market hours?** (Mon-Fri, 9:30 AM - 4:00 PM Eastern Time)
   - If NO: respond HEARTBEAT_OK
   - If YES: continue to step 2

2. **Run the aggressive trading scan** using `python scan_autotrader.py` (from workspace root; NOT aggressive_scan.py or tools/scan_autotrader.py):
   - This script handles ALL logic: stop-losses, profit-taking, RSI buys/sells
   - **Stop-loss**: -3% unrealized → sell all immediately
   - **Profit-take**: +5% → sell all, +3% → sell half
   - **RSI sell**: > 65 → sell all, > 55 → sell half
   - **RSI buy**: < 20 → 20% equity, < 30 → 15% equity, < 40 → 10% equity
   - No max position limit — deploy capital aggressively
   - Log all decisions to logs/decisions.jsonl

3. **Emergency check**: If any position has > 3% loss, sell immediately even outside a full scan

4. **Report format**: Post ONLY the script output. Do not add commentary, headers, or explanation. The script output is the report.
