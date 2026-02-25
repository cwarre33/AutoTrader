"""RSI(14) with Wilder smoothing + helpers for trend/momentum confirmation.
Expects closes sorted by date ascending."""


def compute_rsi(close_prices, period=14):
    """
    Compute RSI from list of close prices (oldest first).
    Returns None if not enough data.
    """
    if not close_prices or len(close_prices) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, period + 1):
        change = close_prices[i] - close_prices[i - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(close_prices)):
        change = close_prices[i] - close_prices[i - 1]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_rsi_series(close_prices, period=14):
    """Return list of RSI values aligned to close_prices (None-padded for early bars)."""
    n = len(close_prices) if close_prices else 0
    if n < period + 1:
        return [None] * n
    result = [None] * (period + 1)
    gains = []
    losses = []
    for i in range(1, period + 1):
        change = close_prices[i] - close_prices[i - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        result[-1] = 100.0
    else:
        result[-1] = 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, n):
        change = close_prices[i] - close_prices[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + abs(min(change, 0))) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            result.append(100 - (100 / (1 + avg_gain / avg_loss)))
    return result


def compute_sma(close_prices, period=50):
    """Simple moving average. Returns None if not enough data."""
    if not close_prices or len(close_prices) < period:
        return None
    return sum(close_prices[-period:]) / period


def avg_volume(bars, period=20):
    """Average volume over last `period` bars. bars = list of bar dicts with 'volume'."""
    if not bars or len(bars) < period:
        return None
    vols = [b.get("volume", 0) for b in bars[-period:]]
    return sum(vols) / period


def rsi_turning_up(close_prices, period=14):
    """True if current RSI > prior-day RSI (momentum turning up)."""
    series = compute_rsi_series(close_prices, period)
    if len(series) < 2:
        return False
    cur = series[-1]
    prev = series[-2]
    if cur is None or prev is None:
        return False
    return cur > prev
