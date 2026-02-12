"""Risk management: position sizing, paper-trading guard, duplicate checks."""

import math

from alpaca.trading.client import TradingClient

from config import config


def _get_trading_client() -> TradingClient:
    return TradingClient(
        api_key=config.ALPACA_API_KEY,
        secret_key=config.ALPACA_SECRET_KEY,
        paper=True,
    )


def validate_paper_trading() -> bool:
    """Confirm we are in paper trading mode. Returns True if safe."""
    if not config.ALPACA_PAPER:
        raise RuntimeError("FATAL: ALPACA_PAPER is not True. Refusing to trade.")
    # Verify the endpoint is paper by checking the base URL via the client
    return True


def calculate_position_size(
    equity: float,
    price: float,
    allocation_fraction: float,
) -> int:
    """Calculate whole shares, capped at MAX_POSITION_PCT of equity * allocation_fraction."""
    if price <= 0 or equity <= 0:
        return 0
    max_dollar_amount = equity * config.MAX_POSITION_PCT * allocation_fraction
    shares = math.floor(max_dollar_amount / price)
    return max(shares, 0)


def check_existing_position(ticker: str) -> bool:
    """Return True if we already hold a position in this ticker."""
    try:
        client = _get_trading_client()
        positions = client.get_all_positions()
        held_symbols = {p.symbol for p in positions}
        return ticker in held_symbols
    except Exception as e:
        print(f"[validator] Error checking positions: {e}")
        # If we can't check, assume we have a position (be conservative)
        return True


def get_equity() -> float:
    """Get current account equity."""
    try:
        client = _get_trading_client()
        account = client.get_account()
        return float(account.equity)
    except Exception as e:
        print(f"[validator] Error getting equity: {e}")
        return 0.0
