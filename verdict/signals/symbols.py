"""
verdict.signals.symbols — pair/symbol mapping helpers.

CMC quote, technical and derivative endpoints key on a base *symbol* (e.g. ``BNB``),
not a market pair (``BNB/USDT``). Splitting consistently in one place avoids the
classic "passed BNB/USDT to a quote call" bug.
"""
from __future__ import annotations

from typing import Optional


def split_pair(pair: str) -> tuple[str, Optional[str]]:
    """``'BNB/USDT' -> ('BNB', 'USDT')``; a bare ``'BNB' -> ('BNB', None)``.

    Uppercases and strips whitespace so callers can pass loose user input.
    """
    s = pair.strip().upper()
    if "/" in s:
        base, _, quote = s.partition("/")
        return base.strip(), (quote.strip() or None)
    return s, None


def base_symbol(pair: str) -> str:
    """The base symbol CMC keys on, e.g. ``base_symbol('BNB/USDT') == 'BNB'``."""
    return split_pair(pair)[0]
