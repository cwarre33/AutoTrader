#!/usr/bin/env python3
"""Analyze Discord message history to evaluate AutoTrader strategy performance."""
import json
import re
import sys
import io
from collections import defaultdict
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

trades_msgs = json.load(open("workspace/tmp/trades_msgs.json", encoding="utf-8"))
cycles_msgs = json.load(open("workspace/tmp/cycles_msgs.json", encoding="utf-8"))

all_msgs = sorted(trades_msgs + cycles_msgs, key=lambda m: m["timestamp"])
print(f"Total messages: {len(all_msgs)}")
print(f"  Trades channel: {len(trades_msgs)}")
print(f"  Cycles channel: {len(cycles_msgs)}")
print(f"Date range: {all_msgs[0]['timestamp'][:16]} --> {all_msgs[-1]['timestamp'][:16]}")
print()

# ── 1. Parse equity series ──────────────────────────────────────────────────
# Format: "$92.0K · $-1,659 (-1.80%) · 20 positions"
equity_pat = re.compile(
    r"\$([0-9]+(?:\.[0-9]+)?)([KM])\s+\u00b7\s+\$[+-]?[0-9,]+\s+\(([+-][0-9.]+)%\)\s+\u00b7\s+([0-9]+) pos"
)

equity_series = []
for m in all_msgs:
    c = m["content"]
    hit = equity_pat.search(c)
    if hit:
        mult = 1000 if hit.group(2) == "K" else 1_000_000
        equity = float(hit.group(1)) * mult
        pl_pct = float(hit.group(3))
        positions = int(hit.group(4))
        equity_series.append({
            "ts": m["timestamp"][:16],
            "equity": equity,
            "pl_pct": pl_pct,
            "positions": positions,
        })

print(f"Equity datapoints: {len(equity_series)}")
if equity_series:
    first = equity_series[0]
    last = equity_series[-1]
    total_change = last["equity"] - first["equity"]
    total_pct = (total_change / first["equity"]) * 100
    print(f"Starting equity : ${first['equity']:,.0f}  ({first['ts']})")
    print(f"Ending equity   : ${last['equity']:,.0f}  ({last['ts']})")
    print(f"Total P&L       : ${total_change:+,.0f} ({total_pct:+.2f}%)")
    print()

    # Daily breakdown
    by_day = defaultdict(list)
    for row in equity_series:
        by_day[row["ts"][:10]].append(row)
    print("── Daily Equity Summary ──────────────────────────────")
    for day in sorted(by_day):
        day_rows = by_day[day]
        open_eq = day_rows[0]["equity"]
        close_eq = day_rows[-1]["equity"]
        day_pct = (close_eq - open_eq) / open_eq * 100
        min_pl = min(r["pl_pct"] for r in day_rows)
        max_pl = max(r["pl_pct"] for r in day_rows)
        print(f"  {day}  open=${open_eq:,.0f}  close=${close_eq:,.0f}  day={day_pct:+.2f}%  pl_range=[{min_pl:+.2f}%, {max_pl:+.2f}%]  cycles={len(day_rows)}")
    print()

# ── 2. Parse individual trades ──────────────────────────────────────────────
buy_pat  = re.compile(r"BUY (\w+) ([0-9]+) shares \u2014 (.+?)(?:\n|$)")
sell_pat = re.compile(r"SELL (\w+) ([0-9]+) shares \u2014 (.+?)(?:\n|$)")

buys = []
sells = []
for m in trades_msgs:
    ts = m["timestamp"][:16]
    c = m["content"]
    for ticker, qty, reason in buy_pat.findall(c):
        buys.append({"ts": ts, "ticker": ticker, "qty": int(qty), "reason": reason.strip()})
    for ticker, qty, reason in sell_pat.findall(c):
        sells.append({"ts": ts, "ticker": ticker, "qty": int(qty), "reason": reason.strip()})

print(f"── Trade Executions ──────────────────────────────────")
print(f"  Total buys : {len(buys)}")
print(f"  Total sells: {len(sells)}")
print()

# Sell reason breakdown
sell_reasons = defaultdict(int)
for s in sells:
    reason = s["reason"]
    if "stop-loss" in reason:
        sell_reasons["stop-loss"] += 1
    elif "profit-take-full" in reason or "+5%" in reason:
        sell_reasons["profit-take-full"] += 1
    elif "profit-take-half" in reason or "+3%" in reason:
        sell_reasons["profit-take-half"] += 1
    elif "RSI sell-all" in reason:
        sell_reasons["RSI sell-all"] += 1
    elif "RSI sell-half" in reason:
        sell_reasons["RSI sell-half"] += 1
    else:
        sell_reasons[reason[:40]] += 1

print("── Sell Reasons ──────────────────────────────────────")
for reason, count in sorted(sell_reasons.items(), key=lambda x: -x[1]):
    pct = count / len(sells) * 100 if sells else 0
    print(f"  {reason:30s}  {count:3d}  ({pct:.0f}%)")
print()

# Buy reason breakdown (RSI levels)
print("── Buy RSI Levels at Entry ───────────────────────────")
rsi_buckets = {"RSI < 20": 0, "RSI 20-30": 0, "RSI 30-40": 0, "RSI 40+": 0}
rsi_vals = []
for b in buys:
    m = re.search(r"RSI buy \(([0-9.]+)\)", b["reason"])
    if m:
        rsi = float(m.group(1))
        rsi_vals.append(rsi)
        if rsi < 20:   rsi_buckets["RSI < 20"] += 1
        elif rsi < 30: rsi_buckets["RSI 20-30"] += 1
        elif rsi < 40: rsi_buckets["RSI 30-40"] += 1
        else:          rsi_buckets["RSI 40+"] += 1
for bucket, count in rsi_buckets.items():
    print(f"  {bucket:12s}  {count:3d}")
if rsi_vals:
    avg_rsi = sum(rsi_vals) / len(rsi_vals)
    print(f"  Avg entry RSI: {avg_rsi:.1f}")
print()

# ── 3. Stop-loss churn analysis ─────────────────────────────────────────────
# Look for same ticker: sell(stop-loss) then buy(RSI) within same day
stop_then_rebuy = []
for s in sells:
    if "stop-loss" not in s["reason"]:
        continue
    ticker = s["ticker"]
    sell_day = s["ts"][:10]
    # Find next buy of same ticker same day
    for b in buys:
        if b["ticker"] == ticker and b["ts"][:10] == sell_day and b["ts"] >= s["ts"]:
            stop_then_rebuy.append((s, b))
            break

print(f"── Stop-loss → Immediate Rebuy (same day) ────────────")
print(f"  Count: {len(stop_then_rebuy)}")
for s, b in stop_then_rebuy:
    b_rsi = re.search(r"RSI buy \(([0-9.]+)\)", b["reason"])
    rsi_str = b_rsi.group(1) if b_rsi else "?"
    print(f"  {s['ticker']:6s}  sold {s['ts'][11:]} ({s['reason'][:20]})  -> rebought {b['ts'][11:]} at RSI {rsi_str}")
print()

# ── 4. Watching signals (RSI < 45, not held) ────────────────────────────────
watch_pat = re.compile(r"Watching: (.+?)(?:\n|$)")
watch_counts = defaultdict(list)
for m in all_msgs:
    hit = watch_pat.search(m["content"])
    if hit and "No oversold" not in hit.group(0):
        items_str = hit.group(1)
        for item in items_str.split(","):
            item = item.strip()
            tm = re.match(r"(\w+) RSI ([0-9.]+)", item)
            if tm:
                watch_counts[tm.group(1)].append(float(tm.group(2)))

print("── Most Watched Tickers (appeared in Watching list) ──")
sorted_watches = sorted(watch_counts.items(), key=lambda x: -len(x[1]))
for ticker, rsivalues in sorted_watches[:15]:
    avg = sum(rsivalues) / len(rsivalues)
    print(f"  {ticker:6s}  appeared {len(rsivalues):3d}x  avg RSI {avg:.1f}")
print()

# ── 5. No-trade cycles ──────────────────────────────────────────────────────
no_trade = sum(1 for m in all_msgs if "No trades this cycle" in m["content"])
trade_cy = sum(1 for m in all_msgs if ("BUY" in m["content"] or "SELL" in m["content"]))
total_cy = no_trade + trade_cy
print(f"── Cycle Activity ────────────────────────────────────")
print(f"  No-trade cycles : {no_trade:3d}  ({no_trade/total_cy*100:.0f}%)" if total_cy else "")
print(f"  Trade cycles    : {trade_cy:3d}  ({trade_cy/total_cy*100:.0f}%)" if total_cy else "")
print()

# ── 6. Current positions at end ─────────────────────────────────────────────
# Find last message with position count
for row in reversed(equity_series):
    print(f"── Latest snapshot ({row['ts']}) ─────────────────────────")
    print(f"  Equity    : ${row['equity']:,.0f}")
    print(f"  P&L today : {row['pl_pct']:+.2f}%")
    print(f"  Positions : {row['positions']}")
    break
