"""In-process Alpaca client with retries and structured logging."""
import logging
import os
import time
from datetime import datetime, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetPortfolioHistoryRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
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


def get_open_sell_qty_by_symbol():
    """Return dict of symbol -> total qty in open SELL orders. Used when qty_available is None."""
    def _():
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        orders = _trading_client().get_orders(req)
        out = {}
        for o in orders:
            if o.side == OrderSide.SELL and o.symbol:
                sym = o.symbol.upper()
                try:
                    qty_val = int(float(o.qty or 0) - float(o.filled_qty or 0))
                except (TypeError, ValueError):
                    qty_val = int(o.qty or 0)
                out[sym] = out.get(sym, 0) + max(0, qty_val)
        return out
    return _retry(_)


def get_positions():
    """Return list of position dicts with available_qty (excludes shares held by open orders)."""
    def _():
        positions = _trading_client().get_all_positions()
        sell_qty_by_symbol = get_open_sell_qty_by_symbol()
        result = []
        for p in positions:
            qty = int(p.qty)
            qty_avail = getattr(p, "qty_available", None)
            if qty_avail is not None and str(qty_avail).strip() != "":
                available_qty = int(float(qty_avail))
            else:
                held = sell_qty_by_symbol.get(p.symbol.upper(), 0)
                available_qty = max(0, qty - held)
            result.append({
                "ticker": p.symbol,
                "qty": qty,
                "available_qty": available_qty,
                "avg_entry": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "market_value": float(p.market_value),
            })
        return result
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
    """Place market buy by share quantity. Return order info dict."""
    def _():
        req = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = _trading_client().submit_order(req)
        return {"status": "submitted", "order_id": str(order.id),
                "symbol": order.symbol, "qty": float(order.qty), "side": "buy"}
    return _retry(_)


def buy_notional(symbol, dollar_amount):
    """Place market buy by dollar amount (fractional shares). Return order info dict."""
    def _():
        req = MarketOrderRequest(
            symbol=symbol.upper(),
            notional=round(dollar_amount, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = _trading_client().submit_order(req)
        return {"status": "submitted", "order_id": str(order.id),
                "symbol": order.symbol, "notional": round(dollar_amount, 2),
                "side": "buy"}
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
        return {"status": "submitted", "order_id": str(order.id),
                "symbol": order.symbol, "qty": float(order.qty), "side": "sell"}
    return _retry(_)


def get_portfolio_history(period="1M", timeframe="1D"):
    """
    Return portfolio history (equity curve) from Alpaca.
    period: e.g. "1D", "1W", "1M", "3M", "1A" (1 year)
    timeframe: "1Min", "5Min", "15Min", "1H", "1D"
    Returns dict with timestamp[], equity[], profit_loss[], profit_loss_pct[], base_value, timeframe.
    """
    def _():
        req = GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
        hist = _trading_client().get_portfolio_history(history_filter=req)
        return {
            "timestamp": list(hist.timestamp) if hist.timestamp else [],
            "equity": [float(e) for e in hist.equity] if hist.equity else [],
            "profit_loss": [float(p) for p in hist.profit_loss] if hist.profit_loss else [],
            "profit_loss_pct": [float(p) for p in hist.profit_loss_pct] if hist.profit_loss_pct else [],
            "base_value": float(hist.base_value) if hist.base_value else 0,
            "timeframe": hist.timeframe or timeframe,
        }
    return _retry(_)
