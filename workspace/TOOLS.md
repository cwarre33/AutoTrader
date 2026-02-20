# Available Trading Tools

## Scan (Primary Entrypoint)

**Always use `scan_autotrader.py`** for portfolio scans (heartbeat, cron, Discord):

```bash
python scan_autotrader.py
```

Run from workspace root. Path: `workspace/scan_autotrader.py` (NOT `workspace/tools/scan_autotrader.py`).

---

## Alpaca CLI (tools/alpaca_tool.py)

You have access to the Alpaca paper trading API via a Python CLI wrapper. All commands return JSON.

## Usage

All commands run via: `python tools/alpaca_tool.py <command> [args]`

Environment variables `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, and `ALPACA_PAPER_TRADE` are pre-configured.

## Commands

### `account` — Get account info
```bash
python tools/alpaca_tool.py account
```
Returns: equity, buying_power, cash, portfolio_value, day_trade_count

### `positions` — List all open positions
```bash
python tools/alpaca_tool.py positions
```
Returns: array of {ticker, qty, avg_entry, current_price, unrealized_pl, unrealized_plpc, market_value}

### `bars` — Get historical daily bars (for RSI calculation)
```bash
python tools/alpaca_tool.py bars AAPL,MSFT,NVDA --days 30
```
Returns: object with ticker keys, each containing array of {date, open, high, low, close, volume}

### `snapshot` — Get current price snapshot
```bash
python tools/alpaca_tool.py snapshot AAPL
```
Returns: {ticker, latest_trade_price, latest_trade_time, minute_bar, daily_bar}

### `buy` — Place a market buy order
```bash
python tools/alpaca_tool.py buy AAPL 10
```
Returns: {status, order_id, symbol, qty, side, type}

### `sell` — Place a market sell order
```bash
python tools/alpaca_tool.py sell AAPL 10
```
Returns: {status, order_id, symbol, qty, side, type}

### `actions` — Get recent news/corporate actions
```bash
python tools/alpaca_tool.py actions AAPL
```
Returns: array of {headline, source, created_at, summary}

## Important Notes

- All orders are PAPER TRADING only
- Orders are market orders with day time-in-force
- Bar data is daily timeframe
- Always check account balance before placing orders
