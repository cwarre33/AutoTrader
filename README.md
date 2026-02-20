---
title: AutoTrader
emoji: 📈
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# AutoTrader - Autonomous Paper Trading Bot

AI-powered paper trading bot that scans high-volume stocks, analyzes them with RSI and news sentiment via LLM reasoning, and executes paper trades on Alpaca.

## Features

- **Stock Scanner**: Identifies top 50 most active stocks by volume
- **Technical Analysis**: RSI (14-period) using Wilder's smoothing
- **News Sentiment**: Fetches recent headlines via Alpaca News API
- **LLM Reasoning**: Uses Llama 3.3 70B via HF Inference API for analysis
- **Paper Trading**: Executes trades on Alpaca paper trading
- **Risk Management**: 5% max position size, confidence threshold
- **Dashboard**: Real-time Gradio UI with account summary, positions, and trade history
- **Scheduling**: Automatic scans every 15 minutes during market hours

## Required Secrets

| Secret | Description |
|--------|-------------|
| `ALPACA_API_KEY` | Alpaca paper trading API key |
| `ALPACA_SECRET_KEY` | Alpaca paper trading secret key |
| `HF_TOKEN` | Hugging Face token (for Inference API) |

## Local Development

```bash
cp .env.example .env
# Fill in your API keys in .env
pip install -r requirements.txt
python app.py
```

Dashboard will be available at `http://localhost:7860`.

## Architecture (refactor)

- **Single scan entrypoint**: `workspace/scan_autotrader.py` — used by cron and HEARTBEAT; uses shared lib (in-process Alpaca client, retries, logging).
- **Shared lib** (`workspace/lib/`): `config` (watchlist, env validation), `alpaca_client` (get_account, get_positions, get_bars, get_snapshot, buy, sell with retries), `rsi`, `decisions` (log, retention, outcomes, daily review).
- **Watchlist**: `workspace/config/watchlist.json` — single source of ticker groups.
- **Self-improvement**: Each scan appends to `logs/outcomes.jsonl` and `logs/daily_review.jsonl`; `logs/decisions.jsonl` is rotated (90-day retention). See `workspace/SELF_IMPROVEMENT.md`.
- **Health**: `GET /api/health` checks Alpaca connectivity.
- **Discord**: Set `DISCORD_BOT_TOKEN` in `.env`; do not store the token in `openclaw-config/openclaw.json`. See `DISCORD.md`.

## Test before market open

1. **Health check**: Start the stack, then `curl http://localhost:5050/api/health` (or open in browser). Should return `{"alpaca":"ok", "equity": ...}`.
2. **Scan dry run**: From repo root, `docker compose exec openclaw-gateway python /home/node/.openclaw/workspace/scan_autotrader.py` (uses container env; will hit Alpaca).
3. **Discord**: Ensure Message Content Intent is ON and `DISCORD_BOT_TOKEN` is in `.env`; restart gateway after any config change.
