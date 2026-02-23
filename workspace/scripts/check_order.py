#!/usr/bin/env python3
import os
import sys
import json
from alpaca.trading.client import TradingClient

API_KEY = os.environ.get("ALPACA_API_KEY")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
PAPER = os.environ.get("ALPACA_PAPER_TRADE", "True").lower() in ("true", "1", "yes")

trading = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)

order_id = "c2f87f99-923c-455c-9446-dd595ca319e4"
try:
    order = trading.get_order_by_id(order_id)
    print(json.dumps({
        "id": str(order.id),
        "symbol": order.symbol,
        "qty": int(order.qty),
        "filled_qty": int(order.filled_qty) if order.filled_qty else 0,
        "side": order.side.value,
        "status": order.status.value,
        "type": order.type.value,
        "time_in_force": order.time_in_force.value
    }, indent=2))
except Exception as e:
    print(f"Error: {e}")