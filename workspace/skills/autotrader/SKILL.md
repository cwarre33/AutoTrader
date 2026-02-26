---
name: autotrader
description: Autonomous paper trading bot — RSI mean-reversion strategy on US equities
trigger: cron
---

# AutoTrader — Trading Scan

**Run the scan script. Do not make manual trades.**

```bash
cd /home/node/.openclaw/workspace && /opt/alpaca-venv/bin/python scan_autotrader.py
```

The script handles everything:
- RSI signals, position sizing, stop-losses, profit-taking
- PDT protection (sub-$25K accounts: max 3 day trades per 5 days)
- Simulated $100 balance mode (set via SIMULATED_BALANCE env var)
- Discord reporting

**After running, post ONLY the script's stdout output. No commentary.**

If the script errors, post the error message verbatim.

Do NOT call `tools/alpaca_tool.py buy` or `sell` directly — all trading goes through `scan_autotrader.py`.
