# AutoTrader Heartbeat

On every heartbeat:

1. **Check market hours** (Mon-Fri 9:30 AM – 4:00 PM Eastern)
   - If outside market hours: respond `HEARTBEAT_OK` and stop.

2. **Run the scan once**:
   ```bash
   cd /home/node/.openclaw/workspace && /opt/alpaca-venv/bin/python scan_autotrader.py
   ```

3. **Post ONLY the script's stdout** to Discord. No added commentary, no headers.

4. **Do not run the scan more than once per heartbeat.** If the script is slow, wait for it.

Rules:
- Never call `tools/alpaca_tool.py buy` or `sell` manually
- Never repeat the scan if it already ran this heartbeat
- If the script errors, post the error and stop
