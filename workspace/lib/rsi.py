"""Single canonical RSI(14) with Wilder smoothing. Expects closes sorted by date ascending."""

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
