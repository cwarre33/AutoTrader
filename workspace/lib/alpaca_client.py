"""In-process Alpaca client with retries and structured logging."""
import logging
import os
import time
from datetime import datetime, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame

logger = logging.getLogger("autotrader")

# Retry config
MAX_ATTEMPTS = 3
RETRY_DELAY_SEC = 2.0

def _get_clients():
    api_key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    paper = os.environ.get("ALPACA_PAPER_TRADE", "True").lower() in ("true", "1", "yes")
    if not api_key or not secret:
        raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
    trading = TradingClient(api_key, secret, paper=paper)
    data = StockHistoricalDataClient(api_key, secret)
    return trading, data


def _retry(fn, *args, **kwargs):
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            logger.warning("Attempt %s/%s failed: %s", attempt, MAX_ATTEMPTS, e)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SEC)
    raise last_err


_trading = None
_data = None


def _trading_client():
    global _trading, _data
    if _trading is None:
        _trading, _data = _get_clients()
    return _trading


def _data_client():
    global _trading, _data
    if _data is None:
        _trading, _data = _get_clients()
    return _data


def get_account():
    """Return account dict: equity, buying_power, cash, etc."""
    def _():
        acct = _trading_client().get_account()
        return {
            "equity": float(acct.equity),
            "buying_power": float(acct.buying_power),
            "cash": float(acct.cash),
            "portfolio_value": float(acct.portfolio_value),
        }
    return _retry(_)


def get_positions():
    """Return list of position dicts."""
    def _():
        positions = _trading_client().get_all_positions()
        return [
            {
                "ticker": p.symbol,
                "qty": int(p.qty),
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "market_value": float(p.market_value),
            }
            for p in positions
        ]
    return _retry(_)


def get_bars(tickers, days=30):
    """Return dict ticker -> list of bar dicts (date, open, high, low, close, volume). Sorted by date asc."""
    if not tickers:
        return {}
    tickers = [t.strip().upper() for t in tickers]
    end = datetime.now()
    start = end - timedelta(days=days)

    def _():
        req = StockBarsRequest(
            symbol_or_symbols=tickers,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed="iex",
        )
        bars = _data_client().get_stock_bars(req)
        result = {}
        data_keys = list(bars.data.keys()) if hasattr(bars.data, "keys") else []
        for ticker in tickers:
            bar_list = None
            if ticker in bars.data:
                bar_list = bars.data[ticker]
            else:
                for k in data_keys:
                    if isinstance(k, str) and k.upper() == ticker.upper():
                        bar_list = bars.data[k]
                        break
            if bar_list is not None:
                arr = [
                    {
                        "date": b.timestamp.isoformat(),
                        "open": float(b.open),
                        "high": float(b.high),
                        "low": float(b.low),
                        "close": float(b.close),
                        "volume": b.volume,
                    }
                    for b in bar_list
                ]
                arr.sort(key=lambda x: x["date"])
                result[ticker] = arr
            else:
                result[ticker] = []
        return result
    return _retry(_)


def get_snapshot(ticker):
    """Return dict with latest_trade_price, etc."""
    def _():
        req = StockSnapshotRequest(symbol_or_symbols=[ticker.upper()], feed="iex")
        snaps = _data_client().get_stock_snapshot(req)
        s = snaps.get(ticker.upper())
        if not s:
            return {}
        return {
            "ticker": ticker.upper(),
            "latest_trade_price": float(s.latest_trade.price) if s.latest_trade else None,
            "latest_trade_time": s.latest_trade.timestamp.isoformat() if s.latest_trade else None,
        }
    return _retry(_)


def get_snapshots_batch(tickers):
    """Fetch snapshots for multiple tickers in one request."""
    if not tickers:
        return {}
    tickers = [t.strip().upper() for t in tickers]

    def _():
        req = StockSnapshotRequest(symbol_or_symbols=tickers, feed="iex")
        snaps = _data_client().get_stock_snapshot(req)
        result = {}
        for t in tickers:
            s = snaps.get(t)
            if s:
                result[t] = {
                    "ticker": t,
                    "latest_trade_price": float(s.latest_trade.price) if s.latest_trade else None,
                }
        return result
    return _retry(_)


def buy(symbol, qty):
    """Place market buy. Return order info dict."""
    def _():
        req = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = _trading_client().submit_order(req)
        return {"status": "submitted", "order_id": str(order.id), "symbol": order.symbol, "qty": int(order.qty), "side": "buy"}
    return _retry(_)


def sell(symbol, qty):
    """Place market sell. Return order info dict."""
    def _():
        req = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = _trading_client().submit_order(req)
        return {"status": "submitted", "order_id": str(order.id), "symbol": order.symbol, "qty": int(order.qty), "side": "sell"}
    return _retry(_)
