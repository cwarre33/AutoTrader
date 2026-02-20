# Self-Improvement Loop

AutoTrader records outcomes and daily summaries so the agent can reflect and adapt.

## What gets recorded

- **`logs/decisions.jsonl`** — Every buy/sell/hold with timestamp, ticker, reason, RSI, price. Retention: 90 days (older lines rotated out).
- **`logs/outcomes.jsonl`** — Resolved outcomes (e.g. sell reason, P&L%) for closed positions; used to learn what worked.
- **`logs/daily_review.jsonl`** — One line per scan with date, equity, daily_pl, trade counts, position count. Lets you see trends over time.

## How to use it

1. **When asked "how are we doing?" or "what have we learned?"** — Read the last 20–30 lines of `logs/daily_review.jsonl` and recent `logs/outcomes.jsonl`; summarize performance and which reasons (e.g. profit-take-half vs stop-loss) are appearing.
2. **When considering strategy changes** — Read `logs/decisions.jsonl` and `logs/outcomes.jsonl` for the last 5–10 trading days; look for repeated losses on a ticker or reason, and avoid those.
3. **Heartbeat / cron** — No extra step required; the scan already appends to outcomes and daily_review. Optionally, once per day, you can add a reflection note (e.g. in `memory/YYYY-MM-DD.md`) with one line: "Trading: X trades, equity $Y, main outcome: ..."

## Rules

- Do not delete or edit past lines in `decisions.jsonl`, `outcomes.jsonl`, or `daily_review.jsonl`; append only.
- Use this data to answer user questions and to suggest small, conservative tweaks (e.g. "we've been stopped out on TICKER a lot; consider skipping it for a few days").
