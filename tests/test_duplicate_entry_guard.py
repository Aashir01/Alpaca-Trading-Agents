"""Entries are idempotent per underlying and expiry.

Loop mode resubmitted the same spread every iteration. The limit sat away from
the market so none filled, and 21 identical iron condors accumulated as working
orders on one underlying overnight -- which would have filled together at 21x
the size the risk gate approved. The gate bounds a single position; it cannot
know how many times it has been asked the same question, so the check lives in
the submission path.
"""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from tradingagents.execution.options_executor import _existing_exposure


def _proposal(symbol="TSLA", leg_symbols=("TSLA260911C00360000",)):
    return SimpleNamespace(
        symbol=symbol,
        legs=[SimpleNamespace(symbol=s) for s in leg_symbols],
    )


def _position(symbol):
    return SimpleNamespace(symbol=symbol)


def _order(symbol=None, legs=()):
    return SimpleNamespace(
        symbol=symbol,
        legs=[SimpleNamespace(symbol=s) for s in legs] or None,
    )


class _Client:
    def __init__(self, positions=(), orders=()):
        self._positions = list(positions)
        self._orders = list(orders)

    def get_all_positions(self):
        return self._positions

    def get_orders(self, _request):
        return self._orders


class DuplicateEntryGuardTests(unittest.TestCase):
    def _check(self, proposal, client):
        with patch(
            "tradingagents.dataflows.alpaca_utils.get_alpaca_trading_client",
            return_value=client,
        ), patch(
            "tradingagents.execution.options_executor.get_alpaca_trading_client",
            return_value=client,
        ):
            return _existing_exposure(proposal)

    def test_a_clean_account_allows_the_entry(self):
        self.assertIsNone(self._check(_proposal(), _Client()))

    def test_an_open_position_on_the_same_expiry_blocks_it(self):
        client = _Client(positions=[_position("TSLA260911P00350000")])
        reason = self._check(_proposal(), client)
        self.assertIsNotNone(reason)
        self.assertIn("open position", reason)

    def test_an_unfilled_multi_leg_order_blocks_it(self):
        # This is the exact shape of the runaway: accepted, never filled.
        client = _Client(orders=[_order(legs=["TSLA260911C00360000",
                                              "TSLA260911C00370000"])])
        reason = self._check(_proposal(), client)
        self.assertIsNotNone(reason)
        self.assertIn("unfilled order", reason)

    def test_a_single_leg_order_blocks_it(self):
        client = _Client(orders=[_order(symbol="TSLA260911C00360000")])
        self.assertIsNotNone(self._check(_proposal(), client))

    def test_a_different_expiry_is_a_different_position(self):
        # Same name, later expiry: a genuinely separate trade, still allowed.
        client = _Client(positions=[_position("TSLA261016C00360000")])
        self.assertIsNone(self._check(_proposal(), client))

    def test_a_different_underlying_does_not_block(self):
        client = _Client(positions=[_position("NVDA260911C00215000")])
        self.assertIsNone(self._check(_proposal(), client))

    def test_equity_positions_are_ignored(self):
        client = _Client(positions=[_position("TSLA")])
        self.assertIsNone(self._check(_proposal(), client))

    def test_an_unreachable_broker_does_not_block_trading(self):
        # Refusing here would halt all order flow on a transient network blip.
        # The risk gate and the safety guard still stand in front of the trade.
        class Broken:
            def get_all_positions(self):
                raise RuntimeError("network")

            def get_orders(self, _request):
                raise RuntimeError("network")

        self.assertIsNone(self._check(_proposal(), Broken()))

    def test_a_proposal_without_parseable_legs_is_not_blocked(self):
        self.assertIsNone(self._check(_proposal(leg_symbols=("NOTANOCC",)), _Client()))

    def test_matching_is_case_insensitive_on_the_underlying(self):
        client = _Client(positions=[_position("TSLA260911C00360000")])
        self.assertIsNotNone(self._check(_proposal(symbol="tsla"), client))


class SubmitPathTests(unittest.TestCase):
    """The guard has to sit in submit_options_plan, not only in the loop."""

    def test_submit_returns_a_duplicate_record_without_calling_the_broker(self):
        from tradingagents.execution import options_executor

        plan = {
            "strategy": "bull_call_spread",
            "symbol": "TSLA",
            "direction": "bullish",
            "legs": [
                {"symbol": "TSLA260911C00360000", "side": "buy", "ratio_qty": 1,
                 "strike": 360.0, "expiry": "2026-09-11", "option_type": "call"},
                {"symbol": "TSLA260911C00370000", "side": "sell", "ratio_qty": 1,
                 "strike": 370.0, "expiry": "2026-09-11", "option_type": "call"},
            ],
        }
        with patch.object(
            options_executor, "_existing_exposure",
            return_value="an open position in TSLA 2026-09-11 already exists",
        ):
            result = options_executor.submit_options_plan(plan, final_action="BUY")

        self.assertFalse(result["submitted"])
        self.assertTrue(result.get("duplicate"))
        self.assertIn("Duplicate entry skipped", result["error"])
        # No gate result: the order never got far enough to be priced.
        self.assertIsNone(result["gate_result"])


if __name__ == "__main__":
    unittest.main()
