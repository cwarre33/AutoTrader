"""Virtual portfolio tracker for simulated balance mode.

Maintains a JSON file that tracks positions, cash, and P&L independently
from the real Alpaca account. This lets the dashboard show how the bot
performs on a small simulated balance (e.g. $100) while the real paper
account has $100K.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger("autotrader.sim")

SIM_FILE = Path(__file__).resolve().parent.parent / "logs" / "sim_portfolio.json"


def _load() -> dict:
    if SIM_FILE.exists():
        try:
            return json.loads(SIM_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict):
    SIM_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIM_FILE.write_text(json.dumps(data, indent=2))


def init(starting_balance: float):
    """Initialize or reset the sim portfolio with a starting balance."""
    data = _load()
    if not data or data.get("starting_balance") != starting_balance:
        data = {
            "starting_balance": starting_balance,
            "cash": starting_balance,
            "positions": {},
            "realized_pl": 0.0,
            "trades": [],
        }
        _save(data)
        logger.info("SIM: initialized portfolio with $%.2f", starting_balance)
    return data


def get_portfolio() -> dict:
    """Return the current sim portfolio state."""
    return _load()


def record_buy(ticker: str, notional: float, price: float, timestamp: str):
    """Record a notional buy in the sim portfolio."""
    data = _load()
    if not data:
        return
    if notional > data.get("cash", 0):
        logger.warning("SIM: buy %s $%.2f exceeds cash $%.2f, capping",
                       ticker, notional, data["cash"])
        notional = data["cash"]
    if notional <= 0:
        return
    shares = notional / price if price > 0 else 0
    positions = data.get("positions", {})
    if ticker in positions:
        old = positions[ticker]
        old_shares = old["shares"]
        old_cost = old["avg_entry"] * old_shares
        new_shares = old_shares + shares
        new_avg = (old_cost + notional) / new_shares if new_shares > 0 else price
        positions[ticker] = {
            "shares": round(new_shares, 6),
            "avg_entry": round(new_avg, 4),
            "notional_cost": round(old.get("notional_cost", old_cost) + notional, 2),
        }
    else:
        positions[ticker] = {
            "shares": round(shares, 6),
            "avg_entry": round(price, 4),
            "notional_cost": round(notional, 2),
        }
    data["cash"] = round(data.get("cash", 0) - notional, 2)
    data["positions"] = positions
    data.setdefault("trades", []).append({
        "timestamp": timestamp, "action": "buy", "ticker": ticker,
        "notional": round(notional, 2), "shares": round(shares, 6),
        "price": round(price, 4),
    })
    _save(data)


def record_sell(ticker: str, qty: float, price: float, timestamp: str):
    """Record a sell in the sim portfolio. qty = share count to sell."""
    data = _load()
    if not data:
        return
    positions = data.get("positions", {})
    if ticker not in positions:
        return
    pos = positions[ticker]
    sell_qty = min(qty, pos["shares"])
    if sell_qty <= 0:
        return
    proceeds = sell_qty * price
    cost_basis = sell_qty * pos["avg_entry"]
    pl = proceeds - cost_basis
    data["realized_pl"] = round(data.get("realized_pl", 0) + pl, 2)
    data["cash"] = round(data.get("cash", 0) + proceeds, 2)
    remaining = pos["shares"] - sell_qty
    if remaining < 0.0001:
        del positions[ticker]
    else:
        positions[ticker] = {
            "shares": round(remaining, 6),
            "avg_entry": pos["avg_entry"],
            "notional_cost": round(
                pos.get("notional_cost", 0) * (remaining / pos["shares"]), 2),
        }
    data["positions"] = positions
    data.setdefault("trades", []).append({
        "timestamp": timestamp, "action": "sell", "ticker": ticker,
        "shares": round(sell_qty, 6), "price": round(price, 4),
        "pl": round(pl, 2),
    })
    _save(data)


def get_summary(current_prices: dict) -> dict:
    """Build a summary with live prices for the dashboard.

    current_prices: {ticker: current_price}
    Returns dict with equity, cash, positions, P&L, etc.
    """
    data = _load()
    if not data:
        return {}
    starting = data.get("starting_balance", 0)
    cash = data.get("cash", 0)
    realized_pl = data.get("realized_pl", 0)
    positions = data.get("positions", {})
    holdings = []
    total_market_value = 0
    total_unrealized = 0
    for ticker, pos in positions.items():
        cur_price = current_prices.get(ticker, pos["avg_entry"])
        shares = pos["shares"]
        mv = shares * cur_price
        cost = shares * pos["avg_entry"]
        unrealized = mv - cost
        plpc = (cur_price / pos["avg_entry"] - 1) if pos["avg_entry"] > 0 else 0
        total_market_value += mv
        total_unrealized += unrealized
        holdings.append({
            "ticker": ticker,
            "shares": round(shares, 4),
            "avg_entry": pos["avg_entry"],
            "current_price": cur_price,
            "market_value": round(mv, 2),
            "unrealized_pl": round(unrealized, 2),
            "unrealized_plpc": round(plpc, 4),
            "cost_basis": round(cost, 2),
        })
    equity = cash + total_market_value
    total_pl = equity - starting
    return {
        "starting_balance": starting,
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "market_value": round(total_market_value, 2),
        "unrealized_pl": round(total_unrealized, 2),
        "realized_pl": realized_pl,
        "total_pl": round(total_pl, 2),
        "total_pl_pct": round(total_pl / starting * 100, 2) if starting > 0 else 0,
        "positions": sorted(holdings, key=lambda x: -x["market_value"]),
        "position_count": len(holdings),
        "exposure_pct": round(total_market_value / equity * 100, 1) if equity > 0 else 0,
        "trades": data.get("trades", [])[-20:],
    }
