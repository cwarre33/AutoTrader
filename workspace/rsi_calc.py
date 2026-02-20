import json
import math

# RSI calculation function
def calculate_rsi(prices, period=14):
    """Calculate RSI from price data"""
    if len(prices) < period + 1:
        return None
    
    gains = []
    losses = []
    
    # Calculate price changes
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    # Calculate RSI
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_rsi_for_all(data):
    """Calculate RSI for all tickers in data dict"""
    results = {}
    for ticker, bars in data.items():
        if bars and len(bars) >= 15:
            # Extract closing prices (most recent first)
            closes = [bar['close'] for bar in bars]
            # Reverse to chronological order (oldest first)
            closes.reverse()
            
            rsi = calculate_rsi(closes)
            if rsi is not None:
                results[ticker] = rsi
            else:
                results[ticker] = "Insufficient data"
        else:
            results[ticker] = "No data"
    return results

if __name__ == "__main__":
    import sys
    # In Docker/non-TTY, stdin may be unavailable (OSError, or /dev/stdin not a device)
    try:
        data = json.load(sys.stdin)
    except (OSError, IOError, ValueError) as e:
        if "No such device" in str(e) or "Bad file descriptor" in str(e) or "Expecting value" in str(e):
            sys.exit(0)  # No usable stdin; used as library only
        raise

    results = calculate_rsi_for_all(data)
    
    # Print results
    print("RSI (14-day) values:")
    for ticker, rsi in sorted(results.items()):
        if isinstance(rsi, (int, float)):
            status = "OVERSOLD (<30)" if rsi < 30 else "OVERBOUGHT (>70)" if rsi > 70 else "NEUTRAL"
            print(f"{ticker}: {rsi:.2f} - {status}")
        else:
            print(f"{ticker}: {rsi}")