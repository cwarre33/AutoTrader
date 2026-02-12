"""Trade execution via Alpaca paper trading."""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

from config import config


def _get_trading_client() -> TradingClient:
    """Create a TradingClient with paper=True always."""
    return TradingClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
        paper=True,  # Always paper trading
    )


def get_current_price(ticker: str) -> float | None:
    """Get the latest quote price for a ticker."""
    try:
        client = StockHistoricalDataClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )
        request = StockLatestQuoteRequest(symbol_or_symbols=ticker)
        quotes = client.get_stock_latest_quote(request)
        quote = quotes[ticker]
        # Use ask price, fall back to bid
        price = quote.ask_price if quote.ask_price > 0 else quote.bid_price
        return float(price)
    except Exception as e:
        print(f"[trader] Error getting price for {ticker}: {e}")
        return None


def execute_buy(ticker: str, qty: int) -> dict:
    """Execute a market buy order. Returns order info dict."""
    try:
        client = _get_trading_client()
        order_request = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(order_request)
        return {
            "status": "submitted",
            "order_id": str(order.id),
            "symbol": order.symbol,
            "qty": str(order.qty),
            "side": "buy",
        }
    except Exception as e:
        print(f"[trader] Error executing buy for {ticker}: {e}")
        return {"status": "error", "error": str(e)}


def execute_sell(ticker: str, qty: int) -> dict:
    """Execute a market sell order. Returns order info dict."""
    try:
        client = _get_trading_client()
        order_request = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(order_request)
        return {
            "status": "submitted",
            "order_id": str(order.id),
            "symbol": order.symbol,
            "qty": str(order.qty),
            "side": "sell",
        }
    except Exception as e:
        print(f"[trader] Error executing sell for {ticker}: {e}")
        return {"status": "error", "error": str(e)}


def get_account_info() -> dict:
    """Get account summary info."""
    try:
        client = _get_trading_client()
        account = client.get_account()
        return {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "status": account.status.value if hasattr(account.status, 'value') else str(account.status),
        }
    except Exception as e:
        print(f"[trader] Error getting account info: {e}")
        return {}


def get_positions() -> list[dict]:
    """Get all current positions."""
    try:
        client = _get_trading_client()
        positions = client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": str(p.qty),
                "market_value": float(p.market_value),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in positions
        ]
    except Exception as e:
        print(f"[trader] Error getting positions: {e}")
        return []
