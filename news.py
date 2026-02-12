"""Alpaca News API: fetch recent headlines per ticker."""

from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest

from config import config


def fetch_headlines(ticker: str, limit: int = 10) -> list[str]:
    """Fetch the last N news headlines for a ticker (titles only)."""
    try:
        client = NewsClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )

        request = NewsRequest(symbols=ticker, limit=limit)
        news = client.get_news(request)

        articles = news.data.get("news", []) if isinstance(news.data, dict) else news.data
        headlines = [a["headline"] for a in articles if isinstance(a, dict) and "headline" in a]
        return headlines

    except Exception as e:
        print(f"[news] Error fetching headlines for {ticker}: {e}")
        return []
