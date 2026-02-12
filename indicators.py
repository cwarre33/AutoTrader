"""RSI calculation using pure pandas (Wilder's smoothing, no ta-lib)."""

from datetime import datetime, timedelta

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import config


def _compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using Wilder's smoothing method."""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # Wilder's smoothing (exponential moving average with alpha=1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def get_rsi_for_ticker(ticker: str) -> float | None:
    """Fetch 45 days of daily bars from Alpaca and return the latest RSI value."""
    try:
        client = StockHistoricalDataClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )

        end = datetime.now()
        start = end - timedelta(days=45)

        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )

        bars = client.get_stock_bars(request)
        bar_list = bars[ticker]

        if len(bar_list) < config.RSI_PERIOD + 1:
            return None

        closes = pd.Series([bar.close for bar in bar_list])
        rsi = _compute_rsi(closes, config.RSI_PERIOD)
        return float(rsi.iloc[-1])

    except Exception as e:
        print(f"[indicators] Error computing RSI for {ticker}: {e}")
        return None
