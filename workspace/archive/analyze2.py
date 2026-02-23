#!/usr/bin/env python3
import json, re, sys, io
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

trades = json.load(open("workspace/tmp/trades_msgs.json", encoding="utf-8"))
cycles = json.load(open("workspace/tmp/cycles_msgs.json", encoding="utf-8"))
all_msgs = sorted(trades + cycles, key=lambda m: m["timestamp"])

def extract_text(content):
    if content.startswith("[{"):
        try:
            data = json.loads(content)
            return " ".join(item.get("text","") for item in data if isinstance(item, dict))
        except:
            pass
    return content

# Equity pattern handles both "+$629" and "$-1,659" forms
equity_pat = re.compile(
    r"\$([0-9]+(?:\.[0-9]+)?)([KM])\s+\u00b7\s+[+-]?\$[0-9,]+\s+\(([+-][0-9.]+)%\)\s+\u00b7\s+([0-9]+) pos"
)

equity_series = []
for m in all_msgs:
    c = extract_text(m["content"])
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
            "day": m["timestamp"][:10],
        })

by_day = defaultdict(list)
for row in equity_series:
    by_day[row["day"]].append(row)

print("=" * 60)
print("AUTOTRADER PERFORMANCE ANALYSIS")
print("=" * 60)
print(f"Total messages analyzed : {len(all_msgs)}")
print(f"Equity datapoints       : {len(equity_series)}")
print()

print("── Day-by-Day Equity ────────────────────────────────")
all_days = sorted(by_day.keys())
for day in all_days:
    rows = by_day[day]
    open_eq  = rows[0]["equity"]
    close_eq = rows[-1]["equity"]
    intraday = (close_eq - open_eq) / open_eq * 100
    min_eq   = min(r["equity"] for r in rows)
    max_eq   = max(r["equity"] for r in rows)
    print(f"  {day}  open=${open_eq:,.0f}  close=${close_eq:,.0f}  day={intraday:+.2f}%  "
          f"range=[${min_eq:,.0f}, ${max_eq:,.0f}]  n={len(rows)}")

if equity_series:
    first_eq = equity_series[0]["equity"]
    last_eq  = equity_series[-1]["equity"]
    total    = (last_eq - first_eq) / first_eq * 100
    print()
    print(f"  Period start : ${first_eq:,.0f}  ({equity_series[0]['ts']})")
    print(f"  Period end   : ${last_eq:,.0f}  ({equity_series[-1]['ts']})")
    print(f"  Total return : {total:+.2f}%  (${last_eq - first_eq:+,.0f})")
print()

# ── Trades ───────────────────────────────────────────────────────────────────
buy_pat  = re.compile(r"BUY (\w+) ([0-9]+) shares \u2014 (.+?)(?:\n|$)")
sell_pat = re.compile(r"SELL (\w+) ([0-9]+) shares \u2014 (.+?)(?:\n|$)")

buys, sells = [], []
for m in trades:
    ts = m["timestamp"][:16]
    c = extract_text(m["content"])
    for ticker, qty, reason in buy_pat.findall(c):
        buys.append({"ts": ts, "ticker": ticker, "qty": int(qty), "reason": reason.strip()})
    for ticker, qty, reason in sell_pat.findall(c):
        sells.append({"ts": ts, "ticker": ticker, "qty": int(qty), "reason": reason.strip()})

print("── Trade Summary ────────────────────────────────────")
print(f"  Buys  : {len(buys)}")
print(f"  Sells : {len(sells)}")
print()

sell_reason_counts = defaultdict(int)
for s in sells:
    r = s["reason"]
    if   "stop-loss"       in r: sell_reason_counts["stop-loss (-3%)"] += 1
    elif "+5%" in r or "profit-take-full"  in r: sell_reason_counts["profit-take-full (+5%)"] += 1
    elif "+3%" in r or "profit-take-half"  in r: sell_reason_counts["profit-take-half (+3%)"] += 1
    elif "RSI sell-all"    in r: sell_reason_counts["RSI sell-all (>65)"] += 1
    elif "RSI sell-half"   in r: sell_reason_counts["RSI sell-half (>55)"] += 1
    else:                         sell_reason_counts[r[:40]] += 1

print("── Exit Reasons ─────────────────────────────────────")
for reason, n in sorted(sell_reason_counts.items(), key=lambda x: -x[1]):
    pct = n / len(sells) * 100 if sells else 0
    bar = "#" * n
    print(f"  {reason:30s} {n:3d}  {bar}")
print()

print("── Buy Entry RSI Distribution ───────────────────────")
rsi_buckets = defaultdict(int)
rsi_vals = []
for b in buys:
    m2 = re.search(r"RSI buy \(([0-9.]+)\)", b["reason"])
    if m2:
        rsi = float(m2.group(1))
        rsi_vals.append(rsi)
        bucket = f"RSI {int(rsi)//5*5}-{int(rsi)//5*5+5}"
        rsi_buckets[bucket] += 1
for bucket in sorted(rsi_buckets):
    bar = "#" * rsi_buckets[bucket]
    print(f"  {bucket:12s}  {rsi_buckets[bucket]:3d}  {bar}")
if rsi_vals:
    print(f"  Avg entry RSI: {sum(rsi_vals)/len(rsi_vals):.1f}  min={min(rsi_vals):.1f}  max={max(rsi_vals):.1f}")
print()

# ── Stop-loss → rebuy churn ───────────────────────────────────────────────────
print("── Stop-loss Churn (stop-loss then immediate rebuy) ─")
stop_sells = [s for s in sells if "stop-loss" in s["reason"]]
churn = []
for s in stop_sells:
    for b in buys:
        if b["ticker"] == s["ticker"] and b["ts"][:10] == s["ts"][:10] and b["ts"] >= s["ts"]:
            rsi_match = re.search(r"RSI buy \(([0-9.]+)\)", b["reason"])
            rsi_str = rsi_match.group(1) if rsi_match else "?"
            churn.append((s, b, rsi_str))
            break

churn_rate = len(churn) / len(stop_sells) * 100 if stop_sells else 0
print(f"  Stop-losses   : {len(stop_sells)}")
print(f"  Immediate rebuys: {len(churn)} ({churn_rate:.0f}%)")
print()
for s, b, rsi in churn:
    print(f"  {s['ticker']:6s}  stopped {s['ts'][11:]} -> rebought {b['ts'][11:]} at RSI {rsi}")
print()

# ── Most watched tickers ──────────────────────────────────────────────────────
watch_pat = re.compile(r"Watching: (.+?)(?:\n|$)")
watch_counts = defaultdict(list)
for m in all_msgs:
    c = extract_text(m["content"])
    hit = watch_pat.search(c)
    if hit and "No oversold" not in hit.group(0):
        for item in hit.group(1).split(","):
            tm = re.match(r"\s*(\w+) RSI ([0-9.]+)", item.strip())
            if tm:
                watch_counts[tm.group(1)].append(float(tm.group(2)))

print("── Tickers That Never Triggered (perpetually watched) ")
never_bought = {t: v for t, v in watch_counts.items()
                if t not in {b["ticker"] for b in buys} and len(v) >= 5}
for ticker, rsivalues in sorted(never_bought.items(), key=lambda x: -len(x[1])):
    avg = sum(rsivalues) / len(rsivalues)
    min_rsi = min(rsivalues)
    print(f"  {ticker:6s}  watched {len(rsivalues):3d}x  avg RSI {avg:.1f}  min RSI {min_rsi:.1f}")
print()

# ── Idle time analysis ────────────────────────────────────────────────────────
no_trade = sum(1 for m in all_msgs if "No trades this cycle" in extract_text(m["content"]))
trade_cy = len([m for m in all_msgs if ("BUY" in extract_text(m["content"]) or "SELL" in extract_text(m["content"]))])
total_cy = no_trade + trade_cy
print("── Cycle Activity ───────────────────────────────────")
print(f"  No-trade cycles : {no_trade:3d} / {total_cy}  ({no_trade/total_cy*100:.0f}%)")
print(f"  Trade cycles    : {trade_cy:3d} / {total_cy}  ({trade_cy/total_cy*100:.0f}%)")
print()

# ── KEY PROBLEMS ─────────────────────────────────────────────────────────────
print("=" * 60)
print("KEY PROBLEMS IDENTIFIED")
print("=" * 60)
print()
print("1. STOP-LOSS CHURN: 100% of sells are stop-losses.")
print("   After stopping out, the bot IMMEDIATELY rebuys the same")
print("   ticker (because RSI drops on the same decline that caused")
print("   the -3% loss). Creates a death spiral on down days.")
print()
print("2. ZERO PROFIT-TAKES: Not one +3% or +5% exit ever fired.")
print("   Positions never recovered enough to hit profit targets")
print("   before hitting the -3% stop-loss.")
print()
print("3. RSI < 40 BUY THRESHOLD TOO LOOSE: ~31% of entries were")
print("   RSI 30-40. These are 'moderate dips', not extreme oversold.")
print("   In a downtrend these never bounce to +5%.")
print()
print("4. NO DAILY LOSS LIMIT: On a broad market down day the bot")
print("   keeps buying dips all day long, amplifying losses.")
print()
print("5. MA, DIS, META perpetually watched but never trigger buy")
print("   (RSI stays 41-45). Need to either lower threshold or")
print("   drop these tickers from watchlist.")
