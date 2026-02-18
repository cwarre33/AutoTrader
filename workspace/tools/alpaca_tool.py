#!/usr/bin/env python3
"""Alpaca trading wrapper for OpenClaw bash_tool integration.

Usage:
	python alpaca_tool.py account
	python alpaca_tool.py positions
	python alpaca_tool.py bars AAPL,MSFT,NVDA --days 30
	python alpaca_tool.py snapshot AAPL
	python alpaca_tool.py buy AAPL 10
	python alpaca_tool.py sell AAPL 10
	python alpaca_tool.py actions AAPL
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame

API_KEY = os.environ["ALPACA_API_KEY"]
SECRET_KEY = os.environ["ALPACA_SECRET_KEY"]
PAPER = os.environ.get("ALPACA_PAPER_TRADE", "True").lower() in ("true", "1", "yes")

trading = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
data = StockHistoricalDataClient(API_KEY, SECRET_KEY)


def cmd_account():
	acct = trading.get_account()
	print(json.dumps({
		"equity": str(acct.equity),
		"buying_power": str(acct.buying_power),
		"cash": str(acct.cash),
		"portfolio_value": str(acct.portfolio_value),
		"day_trade_count": acct.daytrade_count,
		"pattern_day_trader": acct.pattern_day_trader,
	}, indent=2))


def cmd_positions():
	positions = trading.get_all_positions()
	result = []
	for p in positions:
		result.append({
			"ticker": p.symbol,
			"qty": str(p.qty),
			"avg_entry": str(p.avg_entry_price),
			"current_price": str(p.current_price),
			"unrealized_pl": str(p.unrealized_pl),
			"unrealized_plpc": str(p.unrealized_plpc),
			"market_value": str(p.market_value),
		})
	print(json.dumps(result, indent=2))


def cmd_bars(symbols: str, days: int = 30):
	tickers = [s.strip().upper() for s in symbols.split(",")]
	end = datetime.now()
	start = end - timedelta(days=days)
	req = StockBarsRequest(
		symbol_or_symbols=tickers,
		timeframe=TimeFrame.Day,
		start=start,
		end=end,
		feed="iex",
	)
	bars = data.get_stock_bars(req)
	result = {}
	for ticker in tickers:
		if ticker in bars.data:
			result[ticker] = [
				{
					"date": b.timestamp.isoformat(),
					"open": str(b.open),
					"high": str(b.high),
					"low": str(b.low),
					"close": str(b.close),
					"volume": b.volume,
				}
				for b in bars.data[ticker]
			]
	print(json.dumps(result, indent=2))


def cmd_snapshot(symbol: str):
	req = StockSnapshotRequest(symbol_or_symbols=[symbol.upper()], feed="iex")
	snaps = data.get_stock_snapshot(req)
	s = snaps[symbol.upper()]
	print(json.dumps({
		"ticker": symbol.upper(),
		"latest_trade_price": str(s.latest_trade.price) if s.latest_trade else None,
		"latest_trade_time": s.latest_trade.timestamp.isoformat() if s.latest_trade else None,
		"minute_bar": {
			"close": str(s.minute_bar.close),
			"volume": s.minute_bar.volume,
		} if s.minute_bar else None,
		"daily_bar": {
			"open": str(s.daily_bar.open),
			"high": str(s.daily_bar.high),
			"low": str(s.daily_bar.low),
			"close": str(s.daily_bar.close),
			"volume": s.daily_bar.volume,
		} if s.daily_bar else None,
	}, indent=2))


def cmd_buy(symbol: str, qty: int):
	req = MarketOrderRequest(
		symbol=symbol.upper(),
		qty=qty,
		side=OrderSide.BUY,
		time_in_force=TimeInForce.DAY,
	)
	order = trading.submit_order(req)
	print(json.dumps({
		"status": "submitted",
		"order_id": str(order.id),
		"symbol": order.symbol,
		"qty": str(order.qty),
		"side": "buy",
		"type": order.type.value,
	}, indent=2))


def cmd_sell(symbol: str, qty: int):
	req = MarketOrderRequest(
		symbol=symbol.upper(),
		qty=qty,
		side=OrderSide.SELL,
		time_in_force=TimeInForce.DAY,
	)
	order = trading.submit_order(req)
	print(json.dumps({
		"status": "submitted",
		"order_id": str(order.id),
		"symbol": order.symbol,
		"qty": str(order.qty),
		"side": "sell",
		"type": order.type.value,
	}, indent=2))


def cmd_actions(symbol: str):
	"""Get recent corporate actions (via trading API news endpoint)."""
	try:
		from alpaca.data.historical.news import NewsClient
		from alpaca.data.requests import NewsRequest
		news_client = NewsClient(API_KEY, SECRET_KEY)
		req = NewsRequest(symbols=[symbol.upper()], limit=5)
		news = news_client.get_news(req)
		result = [
			{
				"headline": n.headline,
				"source": n.source,
				"created_at": n.created_at.isoformat(),
				"summary": n.summary[:200] if n.summary else None,
			}
			for n in news.news
		]
		print(json.dumps(result, indent=2))
	except Exception as e:
		print(json.dumps({"error": str(e), "note": "News API may require different import path"}))


def main():
	parser = argparse.ArgumentParser(description="Alpaca trading CLI")
	sub = parser.add_subparsers(dest="command", required=True)

	sub.add_parser("account", help="Get account info")
	sub.add_parser("positions", help="List all positions")

	p_bars = sub.add_parser("bars", help="Get historical bars")
	p_bars.add_argument("symbols", help="Comma-separated tickers")
	p_bars.add_argument("--days", type=int, default=30, help="Number of days")

	p_snap = sub.add_parser("snapshot", help="Get stock snapshot")
	p_snap.add_argument("symbol", help="Ticker symbol")

	p_buy = sub.add_parser("buy", help="Place market buy order")
	p_buy.add_argument("symbol", help="Ticker symbol")
	p_buy.add_argument("qty", type=int, help="Number of shares")

	p_sell = sub.add_parser("sell", help="Place market sell order")
	p_sell.add_argument("symbol", help="Ticker symbol")
	p_sell.add_argument("qty", type=int, help="Number of shares")

	p_actions = sub.add_parser("actions", help="Get news/corporate actions")
	p_actions.add_argument("symbol", help="Ticker symbol")

	args = parser.parse_args()

	cmds = {
		"account": lambda: cmd_account(),
		"positions": lambda: cmd_positions(),
		"bars": lambda: cmd_bars(args.symbols, args.days),
		"snapshot": lambda: cmd_snapshot(args.symbol),
		"buy": lambda: cmd_buy(args.symbol, args.qty),
		"sell": lambda: cmd_sell(args.symbol, args.qty),
		"actions": lambda: cmd_actions(args.symbol),
	}
	cmds[args.command]()


if __name__ == "__main__":
	main()
