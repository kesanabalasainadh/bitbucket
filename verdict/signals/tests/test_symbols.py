"""TDD for symbol mapping. CMC keys on the base *symbol*, so pairs like
'BNB/USDT' must be split before any quote/technical call (a classic CMC bug)."""
from __future__ import annotations

from verdict.signals.symbols import base_symbol, split_pair


def test_split_pair_splits_base_and_quote():
    assert split_pair("BNB/USDT") == ("BNB", "USDT")


def test_split_pair_uppercases_and_strips_whitespace():
    assert split_pair("  bnb / usdt  ") == ("BNB", "USDT")


def test_split_pair_bare_symbol_has_no_quote():
    assert split_pair("BNB") == ("BNB", None)


def test_base_symbol_returns_base_only():
    assert base_symbol("CAKE/USDT") == "CAKE"


def test_base_symbol_lowercases_input():
    assert base_symbol("btc") == "BTC"
