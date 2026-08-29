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


class TestCollateralizedRiskReporting(unittest.TestCase):
    """A cash-secured put used to report a max loss of exactly zero."""

    def _account(self, equity=100_000.0, buying_power=100_000.0):
        return {"equity": equity, "buying_power": buying_power, "positions": []}

    def _csp(self, strike=50.0):
        return OptionsStrategyProposal(
            strategy=OptionsStrategy.CASH_SECURED_PUT,
            symbol="AAPL",
            direction="bullish",
            legs=[
                OptionsLeg(
                    symbol="CSP",
                    side="sell",
                    ratio_qty=1,
                    strike=strike,
                    expiry="2025-01-17",
                    option_type="put",
                )
            ],
            rationale="high IV, willing to own",
        )

    def test_csp_reports_a_real_worst_case(self):
        result = evaluate_strategy(
            self._csp(strike=50.0),
            qty=1,
            account=self._account(),
            chain={"CSP": {"bid": 1.90, "ask": 2.10}},
        )
        # Assignment at zero, less the $2.00/share credit: (50 - 2) * 100.
        self.assertAlmostEqual(result.max_loss_usd, 4800.0)
        self.assertGreater(result.max_loss_usd, 0.0)

    def test_csp_is_sized_off_the_stressed_move_not_the_to_zero_loss(self):
        """The to-zero figure is honest but would veto every CSP ever written."""
        result = evaluate_strategy(
            self._csp(strike=50.0),
            qty=1,
            account=self._account(),
            chain={"CSP": {"bid": 1.90, "ask": 2.10}},
            max_loss_pct=2.0,
            stress_move_pct=20.0,
        )
        # A 20% adverse move on a $50 strike is $10/share, less $2 credit = $800.
        self.assertAlmostEqual(result.stress_loss_usd, 800.0)
        self.assertLess(result.stress_loss_usd, result.max_loss_usd)
        self.assertTrue(result.approved, result.reasons)

    def test_oversized_csp_is_still_vetoed(self):
        result = evaluate_strategy(
            self._csp(strike=500.0),
            qty=1,
            account=self._account(equity=100_000.0, buying_power=1_000_000.0),
            chain={"CSP": {"bid": 1.90, "ask": 2.10}},
            max_loss_pct=2.0,
            stress_move_pct=20.0,
        )
        # 20% of a $500 strike is $100/share = $9,800 > 2% of $100k.
        self.assertFalse(result.approved)
        self.assertTrue(any("exceeds" in r for r in result.reasons), result.reasons)

    def test_debit_vertical_risk_is_the_net_debit(self):
        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.BULL_CALL_SPREAD,
            symbol="AAPL",
            direction="bullish",
            legs=[
                OptionsLeg(symbol="LONG", side="buy", ratio_qty=1, strike=150.0,
                           expiry="2025-01-17", option_type="call"),
                OptionsLeg(symbol="SHORT", side="sell", ratio_qty=1, strike=155.0,
                           expiry="2025-01-17", option_type="call"),
            ],
            rationale="moderate bullish conviction, mid IV",
        )
        result = evaluate_strategy(
            proposal,
            qty=1,
            account=self._account(),
            chain={"LONG": {"bid": 3.00, "ask": 3.10}, "SHORT": {"bid": 1.00, "ask": 1.10}},
        )
        # Net debit per share = 3.05 - 1.05 = 2.00 -> $200 per spread.
        self.assertAlmostEqual(result.max_loss_usd, 200.0)
        self.assertAlmostEqual(result.stress_loss_usd, 200.0)
        self.assertTrue(result.approved, result.reasons)


if __name__ == "__main__":
    unittest.main()
