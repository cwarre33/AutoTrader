# AutoTrader — Project Structure

Quick navigation for the codebase.

## Root

| Path | Purpose |
|------|---------|
| `workspace/` | Main app code, scripts, config |
| `openclaw-config/` | Agent/gateway config (Discord, cron, sessions) |
| `templates/` | Flask dashboard HTML |
| `dashboard.py` | Web UI for monitoring |
| `docker-compose.yml` | Gateway + CLI services |
| `Dockerfile` | OpenClaw + Python/Alpaca image |
| `README.md` | Setup, architecture |
| `DISCORD.md` | Discord troubleshooting |

## workspace/ — Core

| Path | Purpose |
|------|---------|
| `scan_autotrader.py` | **Main entrypoint** — RSI scan, trades, Discord posts |
| `lib/` | Shared library (Alpaca, RSI, decisions, Discord, chart) |
| `config/` | Watchlist, Discord message IDs, channel docs |
| `logs/` | decisions.jsonl, outcomes.jsonl, daily_review.jsonl |

## workspace/scripts/ — Utilities

| Script | Purpose |
|--------|---------|
| `read_discord.py` | Fetch messages from Discord channels |
| `analyze_discord_channels.py` | Check for message bleeding |
| `cleanup_discord_malformed.py` | Remove raw JSON / malformed messages |
| `post_portfolio_chart.py` | Post equity chart to Discord |
| `clear_discord_channel.py` | Clear a channel |
| `test_discord_post.py` | Test Discord posting |
| `cancel_order.py` | Cancel Alpaca order (list/cancel) |
| `check_order.py` | Check order status |

## workspace/tools/ — Agent CLI

| Path | Purpose |
|------|---------|
| `alpaca_tool.py` | Alpaca CLI (account, positions, bars, buy, sell) |

## workspace/skills/ — Agent Skills

| Path | Purpose |
|------|---------|
| `autotrader/SKILL.md` | Scan, RSI, trading skill definition |

## openclaw-config/

| Path | Purpose |
|------|---------|
| `openclaw.json` | Discord channels, models, agents |
| `cron/jobs.json` | Scheduled jobs (scan, cleanup) |
| `agents/main/sessions/` | Session transcripts |
| `cron/runs/` | Cron execution logs |

## workspace/archive/ — Deprecated (do not use)

Legacy RSI/scan implementations. See `archive/README.md`.

## workspace/tmp/ — Scratch

Discord analysis output, cached messages. Add to `.gitignore` if desired.
