#!/usr/bin/env python3
import os
import sys
import json
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

API_KEY = os.environ.get("ALPACA_API_KEY")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
PAPER = os.environ.get("ALPACA_PAPER_TRADE", "True").lower() in ("true", "1", "yes")

trading = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)

def cancel_order(order_id):
    try:
        trading.cancel_order_by_id(order_id)
        print(f"Cancelled order {order_id}")
        return True
    except Exception as e:
        print(f"Failed to cancel order {order_id}: {e}")
        return False

def list_orders():
    orders = trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    result = []
    for o in orders:
        if o.status.value in ['open', 'accepted', 'new']:
            result.append({
                "id": str(o.id),
                "symbol": o.symbol,
                "qty": int(o.qty),
                "side": o.side.value,
                "status": o.status.value
            })
    return result

if __name__ == "__main__":
    # List open orders
    orders = list_orders()
    print("Open orders:", json.dumps(orders, indent=2))
    
    # Cancel ORCL orders
    for o in orders:
        if o["symbol"] == "ORCL":
            cancel_order(o["id"])