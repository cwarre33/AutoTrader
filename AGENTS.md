# AGENTS.md

## Cursor Cloud specific instructions

### Architecture

AutoTrader is an AI-powered paper trading bot built on OpenClaw (Node.js agent gateway). It has two main services:

| Service | Port | How to run |
|---------|------|-----------|
| **openclaw-gateway** (Docker) | 18789 | `docker compose up -d openclaw-gateway` |
| **Flask dashboard** (host) | 5050 | `python3 dashboard.py` |

The gateway runs inside Docker and hosts the trading agent, Discord bot, and cron scheduler. The Flask dashboard runs on the host and communicates with the gateway via `docker exec`.

### Starting services

1. Ensure Docker daemon is running: `sudo dockerd &>/tmp/dockerd.log &` (wait ~3s for startup)
2. Build the image if needed: `docker compose build`
3. Start gateway: `docker compose up -d openclaw-gateway`
4. Start dashboard: `python3 dashboard.py &>/tmp/dashboard.log &`

### OpenClaw config (gotcha)

The `openclaw-config/` directory is gitignored and must be initialized on first run. If the gateway fails with "Missing config", run:
```
sudo chown -R 1000:1000 openclaw-config
mkdir -p openclaw-config/agents/main/sessions openclaw-config/credentials openclaw-config/cron/runs
docker run --rm -v $(pwd)/openclaw-config:/home/node/.openclaw -e HOME=/home/node --user 1000:1000 autotrader-openclaw:latest node dist/index.js config set gateway.mode local
docker run --rm -v $(pwd)/openclaw-config:/home/node/.openclaw -e HOME=/home/node --user 1000:1000 autotrader-openclaw:latest node dist/index.js config set gateway.auth.token "$OPENCLAW_GATEWAY_TOKEN"
```

### Required secrets (as env vars)

- `OPENCLAW_GATEWAY_TOKEN` - gateway auth token
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` - Alpaca paper trading (required for all trading functionality)
- `DISCORD_BOT_TOKEN` - Discord bot (optional but used for posting)
- `OPENAI_API_KEY` - LLM fallback (optional)
- `DISCORD_DASHBOARD_WEBHOOK_URL` / `DISCORD_TRADES_WEBHOOK_URL` - Discord webhooks (optional)

The `.env` file must be created from `.env.example` with actual values before starting services.

### Running the scanner

From host: `docker exec autotrader-gateway python /home/node/.openclaw/workspace/scan_autotrader.py`

The scanner uses the v2 strategy with exposure caps, trailing stops, and multi-signal entry filters.
Key parameters are defined at the top of `workspace/scan_autotrader.py` for easy tuning.

### Lint

```bash
flake8 --max-line-length=200 --exclude=__pycache__ dashboard.py workspace/scan_autotrader.py workspace/lib/ workspace/tools/alpaca_tool.py
```
Note: pre-existing style issues exist (tabs in `alpaca_tool.py`, E402 in `scan_autotrader.py` due to `sys.path` manipulation).

### Testing

No automated test suite exists. Verify by:
1. `curl http://localhost:5050/api/health` - should return `{"alpaca": "ok", ...}`
2. `curl http://localhost:5050/api/account` - should return account JSON
3. Run a scan: `docker exec autotrader-gateway python /home/node/.openclaw/workspace/scan_autotrader.py`

### Alpaca key rotation caveat

If Alpaca API keys are regenerated, the `.env` file must be regenerated and the gateway restarted (`docker compose down && docker compose up -d openclaw-gateway`). The `alpaca_client.py` module caches clients at module level, so a container restart is required for key changes to take effect.

### Live trading mode

Set `GATEWAY_MODE=live` in `.env` to enable live-trading safeguards:

- **PDT protection** (`lib/pdt.py`): Tracks day trades in `logs/pdt_trades.jsonl`. Accounts under $25K are limited to 3 day trades per 5-business-day window. Stop-losses always execute (capital protection overrides PDT). Profit-taking and RSI sells are PDT-checked.
- **Expensive stock handling**: Stocks where allocation rounds to 0 shares are skipped with a log message instead of erroring.
- All strategy parameters are at the top of `workspace/scan_autotrader.py` for easy tuning.

To switch to live: change `ALPACA_PAPER_TRADE` to `False` in docker-compose.yml and set `GATEWAY_MODE=live` in `.env`. Start during off-hours so you can watch the first scans.

### Docker in Cloud VM

Docker requires `fuse-overlayfs` storage driver and `iptables-legacy` in the Cursor Cloud VM (nested container environment). The daemon config at `/etc/docker/daemon.json` must set `"storage-driver": "fuse-overlayfs"`.
