"""Orchestration loop: scan-analyze-trade cycle."""

from scanner import scan_top_tickers
from indicators import get_rsi_for_ticker
from news import fetch_headlines
from reasoning import analyze_ticker
from validator import (
    validate_paper_trading,
    calculate_position_size,
    check_existing_position,
    get_equity,
)
from trader import execute_buy, execute_sell, get_current_price
from logger import log_decision
from config import config


def run_scan_cycle() -> dict:
    """Execute one full scan-analyze-trade cycle. Returns summary stats."""
    print("[main] Starting scan cycle...")
    stats = {"tickers_scanned": 0, "trades_executed": 0, "errors": 0, "holds": 0}

    # Safety check
    validate_paper_trading()

    # Step 1: Scan top tickers
    tickers = scan_top_tickers()
    if not tickers:
        print("[main] No tickers found. Aborting cycle.")
        return stats

    equity = get_equity()
    if equity <= 0:
        print("[main] Could not retrieve equity. Aborting cycle.")
        return stats

    print(f"[main] Scanning {len(tickers)} tickers with equity ${equity:,.2f}")

    for ticker in tickers:
        try:
            stats["tickers_scanned"] += 1

            # Step 2: Gather data
            rsi = get_rsi_for_ticker(ticker)
            headlines = fetch_headlines(ticker)
            price = get_current_price(ticker)

            # Step 3: Analyze with LLM
            decision = analyze_ticker(ticker, rsi, headlines, price)

            print(
                f"[main] {ticker}: action={decision.action}, "
                f"confidence={decision.confidence}, sentiment={decision.sentiment}"
            )

            # Step 4: Execute if confidence is high enough
            if decision.confidence >= config.CONFIDENCE_THRESHOLD and decision.action in ("buy", "sell"):
                if decision.action == "buy":
                    # Check if already holding
                    if check_existing_position(ticker):
                        print(f"[main] {ticker}: already holding, skipping buy")
                        log_decision(
                            ticker=ticker,
                            action="hold (already held)",
                            confidence=decision.confidence,
                            sentiment=decision.sentiment,
                            rsi=rsi or 0.0,
                            reasoning=decision.reasoning,
                            equity_at_time=equity,
                        )
                        stats["holds"] += 1
                        continue

                    # Calculate position size
                    if price and price > 0:
                        shares = calculate_position_size(equity, price, decision.suggested_allocation)
                        if shares > 0:
                            result = execute_buy(ticker, shares)
                            log_decision(
                                ticker=ticker,
                                action="buy",
                                confidence=decision.confidence,
                                sentiment=decision.sentiment,
                                rsi=rsi or 0.0,
                                reasoning=decision.reasoning,
                                shares=shares,
                                price=price,
                                order_status=result.get("status", ""),
                                order_id=result.get("order_id", ""),
                                equity_at_time=equity,
                            )
                            stats["trades_executed"] += 1
                            print(f"[main] {ticker}: BUY {shares} shares @ ${price:.2f}")
                        else:
                            log_decision(
                                ticker=ticker,
                                action="hold (position too small)",
                                confidence=decision.confidence,
                                sentiment=decision.sentiment,
                                rsi=rsi or 0.0,
                                reasoning=decision.reasoning,
                                equity_at_time=equity,
                            )
                            stats["holds"] += 1

                elif decision.action == "sell":
                    # Only sell if we have a position
                    if not check_existing_position(ticker):
                        log_decision(
                            ticker=ticker,
                            action="hold (no position to sell)",
                            confidence=decision.confidence,
                            sentiment=decision.sentiment,
                            rsi=rsi or 0.0,
                            reasoning=decision.reasoning,
                            equity_at_time=equity,
                        )
                        stats["holds"] += 1
                        continue

                    # Sell entire position
                    from alpaca.trading.client import TradingClient
                    client = TradingClient(
                        api_key=config.ALPACA_API_KEY,
                        secret_key=config.ALPACA_SECRET_KEY,
                        paper=True,
                    )
                    try:
                        position = client.get_open_position(ticker)
                        sell_qty = int(float(str(position.qty)))
                        if sell_qty > 0:
                            result = execute_sell(ticker, sell_qty)
                            log_decision(
                                ticker=ticker,
                                action="sell",
                                confidence=decision.confidence,
                                sentiment=decision.sentiment,
                                rsi=rsi or 0.0,
                                reasoning=decision.reasoning,
                                shares=sell_qty,
                                price=price or 0.0,
                                order_status=result.get("status", ""),
                                order_id=result.get("order_id", ""),
                                equity_at_time=equity,
                            )
                            stats["trades_executed"] += 1
                            print(f"[main] {ticker}: SELL {sell_qty} shares")
                    except Exception as e:
                        print(f"[main] {ticker}: Error getting position for sell: {e}")
                        stats["errors"] += 1
            else:
                # Log hold decision
                log_decision(
                    ticker=ticker,
                    action="hold",
                    confidence=decision.confidence,
                    sentiment=decision.sentiment,
                    rsi=rsi or 0.0,
                    reasoning=decision.reasoning,
                    equity_at_time=equity,
                )
                stats["holds"] += 1

        except Exception as e:
            print(f"[main] Error processing {ticker}: {e}")
            stats["errors"] += 1

    print(
        f"[main] Cycle complete: {stats['tickers_scanned']} scanned, "
        f"{stats['trades_executed']} trades, {stats['holds']} holds, "
        f"{stats['errors']} errors"
    )
    return stats
