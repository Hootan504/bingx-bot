"""Financial utilities for the trading bot.

This module provides helper functions to compute realised and unrealised
profit/loss (PnL) from trade history and to perform simple stress tests.
These functions operate on the SQLite trade history database and are
intended for basic accounting and risk evaluation. They do not reflect
all nuances of derivatives trading (fees, funding, slippage) but offer
frameworks for extension.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def compute_realised_pnl(db_path: Path) -> float:
    """Compute realised PnL from the trades table.

    This function iterates over the trades table, pairing entries and exits
    by FIFO. For each complete trade (entry and exit), it calculates the
    PnL as (exit_price - entry_price) * amount for long positions or
    (entry_price - exit_price) * amount for short positions. Partially
    filled or unmatched trades are ignored. Fees and funding are not
    included. Returns the sum of realised PnL.
    """
    realised: float = 0.0
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT ts, side, amount, price FROM trades WHERE ok=1 AND dry_run=0 ORDER BY ts ASC"
        )
        trades: List[Tuple[int, str, float, float]] = [
            (row["ts"], row["side"], float(row["amount"] or 0), float(row["price"] or 0))
            for row in cur.fetchall()
        ]
        conn.close()
        # Build a simple position stack: push on buy/long, pop on sell/short
        stack: List[Tuple[str, float, float]] = []  # (side, amount, price)
        for _, side, qty, price in trades:
            if side == "buy":
                stack.append((side, qty, price))
            elif side == "sell" and stack:
                # Match against earliest buy
                entry_side, entry_qty, entry_price = stack.pop(0)
                filled_qty = min(qty, entry_qty)
                pnl = (price - entry_price) * filled_qty
                realised += pnl
                # If partial fill, push remaining portion back to stack
                if entry_qty > filled_qty:
                    stack.insert(0, (entry_side, entry_qty - filled_qty, entry_price))
        return realised
    except Exception:
        return realised


def stress_test_price_shock(prices: List[float], shock_pct: float) -> List[float]:
    """Apply a uniform price shock to a series of prices.

    Given a list of prices and a shock percentage (e.g. -0.1 for a -10%
    shock), return a new list where each price is multiplied by (1 + shock_pct).
    This can be used to simulate sudden market moves for scenario analysis.
    """
    try:
        factor = 1.0 + shock_pct
        return [p * factor for p in prices]
    except Exception:
        return prices.copy()


def compute_unrealised_pnl(db_path: Path, price_map: Dict[str, float]) -> float:
    """Compute unrealised PnL based on open positions and current prices.

    Arguments:
        db_path: Path to the SQLite database containing the trades table.
        price_map: Mapping of symbol -> current mark price.

    Returns the sum of unrealised PnL for all open positions. A positive
    value indicates potential profit; negative indicates a potential loss.
    Note: This simple implementation assumes each trade entry opens a
    position and each exit closes it completely, pairing by FIFO. Partial
    fills are not handled separately and fees/funding are ignored.
    """
    unrealised: float = 0.0
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT symbol, side, amount, price, ok, dry_run FROM trades ORDER BY ts ASC"
        )
        rows = cur.fetchall()
        conn.close()
        # Build position stacks per symbol
        stacks: Dict[str, List[Tuple[str, float, float]]] = {}
        for row in rows:
            if not row['ok'] or row['dry_run']:
                continue
            sym = row['symbol'] or ''
            side = (row['side'] or '').lower()
            qty = float(row['amount'] or 0)
            price = float(row['price'] or 0)
            if qty <= 0:
                continue
            stacks.setdefault(sym, [])
            if side == 'buy':
                stacks[sym].append(('buy', qty, price))
            elif side == 'sell':
                # Match against existing buys
                stack = stacks[sym]
                remain = qty
                i = 0
                while i < len(stack) and remain > 0:
                    entry_side, entry_qty, entry_price = stack[i]
                    take = min(entry_qty, remain)
                    # reduce the entry position
                    entry_qty -= take
                    remain -= take
                    # update stack entry
                    if entry_qty <= 0:
                        stack.pop(i)
                        # do not increment i; we removed this entry
                        continue
                    else:
                        stack[i] = (entry_side, entry_qty, entry_price)
                    i += 1
                # if sell exceeds buy positions, ignore remainder
        # Compute unrealised PnL from open positions
        for sym, stack in stacks.items():
            price = price_map.get(sym)
            if price is None:
                continue
            for entry_side, qty, entry_price in stack:
                if qty <= 0:
                    continue
                if entry_side == 'buy':
                    unrealised += (price - entry_price) * qty
                elif entry_side == 'sell':
                    unrealised += (entry_price - price) * qty
        return unrealised
    except Exception:
        return unrealised


def equity_curve(db_path: Path) -> List[Tuple[int, float]]:
    """Compute the cumulative equity curve based on trade history.

    The equity starts at zero and each realised PnL from a closing trade
    is added to the running total. The returned list contains tuples
    (timestamp, equity). Equity updates occur whenever a position is
    closed. Unrealised PnL is not included.
    """
    curve: List[Tuple[int, float]] = []
    equity: float = 0.0
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT ts, side, amount, price, symbol, ok, dry_run FROM trades ORDER BY ts ASC"
        )
        rows = cur.fetchall()
        conn.close()
        # Position stacks per symbol
        stacks: Dict[str, List[Tuple[str, float, float, int]]] = {}
        for row in rows:
            if not row['ok'] or row['dry_run']:
                continue
            ts = int(row['ts'] or 0)
            sym = row['symbol'] or ''
            side = (row['side'] or '').lower()
            qty = float(row['amount'] or 0)
            price = float(row['price'] or 0)
            if qty <= 0:
                continue
            stacks.setdefault(sym, [])
            if side == 'buy':
                stacks[sym].append(('buy', qty, price, ts))
            elif side == 'sell':
                remain = qty
                stack = stacks[sym]
                i = 0
                while i < len(stack) and remain > 0:
                    entry_side, entry_qty, entry_price, entry_ts = stack[i]
                    take = min(entry_qty, remain)
                    # compute PnL for the closed portion
                    pnl = (price - entry_price) * take
                    equity += pnl
                    # record equity point at this timestamp
                    curve.append((ts, equity))
                    # update stacks
                    entry_qty -= take
                    remain -= take
                    if entry_qty <= 0:
                        stack.pop(i)
                        continue
                    else:
                        stack[i] = (entry_side, entry_qty, entry_price, entry_ts)
                    i += 1
                # ignore sells beyond open positions
        return curve
    except Exception:
        return curve