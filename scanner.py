"""Alpaca screener: fetch top tickers by volume."""

from alpaca.data.historical import ScreenerClient
from alpaca.data.requests import MostActivesRequest

from config import config


def scan_top_tickers() -> list[str]:
    """Return up to SCAN_TOP_N most active tickers by volume."""
    try:
        client = ScreenerClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )

        request = MostActivesRequest(top=config.SCAN_TOP_N, by="volume")
        response = client.get_most_actives(request)

        tickers = [item.symbol for item in response.most_actives]
        print(f"[scanner] Found {len(tickers)} active tickers")
        return tickers

    except Exception as e:
        print(f"[scanner] Error scanning tickers: {e}")
        return []
