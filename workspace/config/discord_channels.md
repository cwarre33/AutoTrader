# Discord Channel Setup

## Current Channels

| Channel | ID | Purpose |
|---------|-----|---------|
| Primary | `1474502611393581267` | Agent @mentions, general chat |
| Trades | `1474503672951079024` | Trade executions only (buy/sell) |
| Cycles | `1474503699903680756` | Scan cycle summaries (every run) |
| Dashboard | `1474505225866969098` | Single message, updated each cycle with equity, positions, P&L |
| Charts | (optional) | Portfolio equity curve chart — use `DISCORD_CHARTS_CHANNEL_ID` or defaults to primary |

## Channel Bleeding Fix (message merging)

If cycle summaries, agent chat, or malformed JSON appear in the **trades** channel:

1. **Cron routing**: In `openclaw-config/cron/jobs.json`, set `delivery.to` for the scan job to `channel:1474503699903680756` (cycles), **not** trades. The scan prints cycle summaries to stdout; cron delivers that output. It must go to cycles.

2. **Agent channel**: Ensure the agent/gateway listens to **primary** (`1474502611393581267`), not trades. Human @mentions and agent replies belong in primary.

3. **Malformed messages**: Run `python scripts/cleanup_discord_malformed.py --dry-run` to list, then without `--dry-run` to delete raw JSON/agent output bugs.

4. **Analysis**: Run `python scripts/analyze_discord_channels.py` to check for message bleeding across channels.

5. **"channels unresolved" in gateway logs**: The bot cannot resolve channel IDs to names. Ensure the bot has **View Channel**, **Read Message History**, **Send Messages** in all channels. Re-invite the bot with correct permissions if needed.

## Portfolio Chart (equity curve visual)

To post an equity curve chart from Alpaca to Discord:

```bash
python scripts/post_portfolio_chart.py
```

- **Channel**: Uses `DISCORD_CHARTS_CHANNEL_ID` (default: dashboard channel)
- **Period**: `CHART_PERIOD` env (default: `1M` for 1 month)
- **Timeframe**: `CHART_TIMEFRAME` env (default: `1D` for daily)

Add to cron for periodic charts, or run manually. Requires `matplotlib` (in Docker image).

## Dashboard Setup (static, one message)

**If you get 403/1010 from the bot API** (common in Docker), use a webhook instead:

1. In Discord: right-click the dashboard channel → **Edit Channel** → **Integrations** → **Webhooks** → **New Webhook**
2. Name it (e.g. "AutoTrader Dashboard"), copy the **Webhook URL**
3. Add to `.env`: `DISCORD_DASHBOARD_WEBHOOK_URL=https://discord.com/api/webhooks/...`
4. Restart the gateway.

Webhooks bypass the bot API and avoid Cloudflare 1010. The scan edits the same message each cycle.

**Alternative (bot API):** Set `DISCORD_DASHBOARD_CHANNEL_ID` and add the channel to openclaw.json. May fail with 403/1010 in Docker.

## Adding More Channels (e.g. trades, cycles)

When you create additional channels:

1. **Create the channel** in Discord and copy its ID (right-click → Copy ID).

2. **Add to OpenClaw config** (`openclaw-config/openclaw.json`):
   ```json
   "channels": {
     "1474502611393581267": {"allow": true, "requireMention": false},
     "TRADES_CHANNEL_ID": {"allow": true, "requireMention": false},
     "CYCLES_CHANNEL_ID": {"allow": true, "requireMention": false}
   }
   ```
   (Add under `guilds["1473759045197500516"].channels`)

3. **Route cron jobs** by updating `delivery.to` in `openclaw-config/cron/jobs.json`:
   - `"to": "channel:1474502611393581267"` for cycle summaries
   - `"to": "channel:TRADES_CHANNEL_ID"` for a trades-only job (would need a separate scan/tool that only runs when trades occur)

4. **Restart gateway** after config changes.

## Splitting Trades vs Cycles

Right now, one cron job posts the full scan output (including trades) to one channel. To split:

- **Option A**: Create two cron jobs with different payloads — one runs `scan_autotrader.py` and posts to cycles channel; a second could run a "trades only" script that parses `logs/decisions.jsonl` and posts new trades to the trades channel.
- **Option B**: Modify `scan_autotrader.py` to optionally post to Discord via webhook/API — one message to trades channel when trades happen, one to cycles channel for the summary. (Requires adding Discord webhook or bot posting logic to the script.)
