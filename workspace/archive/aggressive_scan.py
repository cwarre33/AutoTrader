#!/usr/bin/env python3
"""
DEPRECATED: Use scan_autotrader.py instead.

This script is kept for backward compatibility. It now delegates to scan_autotrader.py
which uses the shared lib/ (in-process Alpaca, retries, proper RSI). aggressive_scan.py
previously used tools/alpaca_tool.py + rsi_calc.py which fails in Docker (stdin unavailable).
"""
import os
import sys

# Run from workspace root so lib is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Delegate to canonical scan
import scan_autotrader
scan_autotrader.main()
