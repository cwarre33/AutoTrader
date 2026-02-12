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
