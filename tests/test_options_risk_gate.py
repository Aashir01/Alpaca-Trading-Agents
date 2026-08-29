"""Tests for the options risk gate.

All tests are offline and use synthetic quotes/account snapshots.
"""

import unittest

from tradingagents.agents.options_risk_gate import (
    OptionsStrategy,
    evaluate_strategy,
    reconcile_direction,
)
from tradingagents.agents.schemas import OptionsLeg, OptionsStrategyProposal


def _leg(symbol, side="buy", ratio_qty=1, strike=None, option_type=None):
    return OptionsLeg(
        symbol=symbol,
        side=side,
        ratio_qty=ratio_qty,
        strike=strike,
        expiry="2025-01-17",
        option_type=option_type,
    )


class TestOptionsRiskGate(unittest.TestCase):
    def _account(self, equity=100_000.0, buying_power=100_000.0, positions=None):
        return {"equity": equity, "buying_power": buying_power, "positions": positions or []}

    def _chain(self, **prices):
        """Build a quote map from symbol -> (bid, ask) or pre-built dict."""
        chain = {}
        for symbol, value in prices.items():
            if isinstance(value, tuple):
                chain[symbol] = {"bid": value[0], "ask": value[1]}
            else:
                chain[symbol] = value
        return chain

    def test_none_strategy_always_approved(self):
        proposal = OptionsStrategyProposal(strategy=OptionsStrategy.NONE, symbol="AAPL", direction="neutral")
        result = evaluate_strategy(proposal, qty=1, account=self._account(), chain={})
        self.assertTrue(result.approved)
        self.assertIn("'none'; no options trade required", result.reasons[0])

    def test_missing_leg_quote_veto(self):
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.LONG_CALL,
            symbol="AAPL",
            direction="bullish",
            legs=[_leg("AAPL250117C00150000", strike=150.0, option_type="call")],
        )
        result = evaluate_strategy(proposal, qty=1, account=self._account(), chain={})
        self.assertFalse(result.approved)
        self.assertTrue(any("Missing or invalid quotes" in r for r in result.reasons))

    def test_wide_spread_veto(self):
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.LONG_CALL,
            symbol="AAPL",
            direction="bullish",
            legs=[_leg("AAPL250117C00150000", strike=150.0, option_type="call")],
        )
        chain = self._chain(AAPL250117C00150000=(1.00, 10.00))
        result = evaluate_strategy(proposal, qty=1, account=self._account(), chain=chain, max_spread_pct=20.0)
        self.assertFalse(result.approved)
        self.assertTrue(any("spread too wide" in r for r in result.reasons))

    def test_long_call_max_loss_within_budget(self):
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.LONG_CALL,
            symbol="AAPL",
            direction="bullish",
            legs=[_leg("AAPL250117C00150000", strike=150.0, option_type="call")],
        )
        chain = self._chain(AAPL250117C00150000=(2.50, 2.60))
        result = evaluate_strategy(proposal, qty=1, account=self._account(), chain=chain)
        self.assertTrue(result.approved)
        self.assertIsNotNone(result.max_loss_usd)
        # mid = 2.55, max loss per spread ~ 255 dollars
        self.assertAlmostEqual(result.max_loss_usd, 255.0, places=0)

    def test_long_call_exceeds_loss_budget(self):
        # Mid = 5000 per contract => too much for 2% of 100k equity.
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.LONG_CALL,
            symbol="AAPL",
            direction="bullish",
            legs=[_leg("AAPL250117C00150000", strike=150.0, option_type="call")],
        )
        chain = self._chain(AAPL250117C00150000=(50.00, 50.00))
        result = evaluate_strategy(proposal, qty=1, account=self._account(equity=100_000.0), chain=chain)
        if result.approved:
            print("DEBUG result:", result)
        self.assertFalse(result.approved)
        self.assertTrue(any("exceeds" in r and "of equity" in r for r in result.reasons))

    def test_bull_put_spread_approved(self):
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.BULL_PUT_SPREAD,
            symbol="AAPL",
            direction="bullish",
            legs=[
                _leg("AAPL250117P00140000", side="sell", strike=140.0, option_type="put"),
                _leg("AAPL250117P00130000", side="buy", strike=130.0, option_type="put"),
            ],
        )
        # Net credit ~ 2.345 per share => width - credit = 10 - 2.345, max loss per contract = 765.5.
        chain = self._chain(
            AAPL250117P00140000=(2.50, 2.60),
            AAPL250117P00130000=(0.20, 0.21),
        )
        result = evaluate_strategy(proposal, qty=1, account=self._account(), chain=chain)
        self.assertTrue(result.approved)
        self.assertAlmostEqual(result.max_loss_usd, 765.5, places=0)

    def test_unhedged_short_leg_veto(self):
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.BULL_PUT_SPREAD,
            symbol="AAPL",
            direction="bullish",
            legs=[
                _leg("AAPL250117P00140000", side="sell", strike=140.0, option_type="put"),
            ],
        )
        chain = self._chain(AAPL250117P00140000=(2.50, 2.60))
        result = evaluate_strategy(proposal, qty=1, account=self._account(), chain=chain)
        self.assertFalse(result.approved)
        self.assertTrue(any("unhedged" in r for r in result.reasons))

    def test_csp_insufficient_buying_power(self):
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.CASH_SECURED_PUT,
            symbol="AAPL",
            direction="bullish",
            legs=[
                _leg("AAPL250117P00140000", side="sell", strike=140.0, option_type="put"),
            ],
        )
        chain = self._chain(AAPL250117P00140000=(2.50, 2.60))
        account = self._account(equity=100_000.0, buying_power=5_000.0)
        result = evaluate_strategy(proposal, qty=1, account=account, chain=chain)
        self.assertFalse(result.approved)
        self.assertTrue(any("buying power" in r.lower() for r in result.reasons))

    def test_reconcile_direction_matches(self):
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.LONG_CALL, symbol="AAPL", direction="bullish"
        )
        ok, _ = reconcile_direction(proposal, "BUY")
        self.assertTrue(ok)

    def test_reconcile_direction_mismatch(self):
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.LONG_PUT, symbol="AAPL", direction="bearish"
        )
        ok, reason = reconcile_direction(proposal, "BUY")
        self.assertFalse(ok)
        self.assertIn("does not match", reason)


if __name__ == "__main__":
    unittest.main()
