"""Exit-manager arithmetic.

These pin the decisions that move money: when a structure is closed, when it
is left alone, and that a debit spread is not judged by a credit spread's
stop. The numbers in the iron-condor case are a real fill taken from a paper
account, so the grouping is checked against something the broker actually
produced rather than a hand-built fixture.
"""

import unittest
from datetime import date
from types import SimpleNamespace

from tradingagents.execution.position_manager import (
    evaluate_group,
    group_positions,
    parse_occ,
)

CONFIG = {
    "options_take_profit_pct": 0.35,
    "options_stop_loss_multiple": 1.5,
    "options_debit_stop_pct": 0.5,
    "options_close_dte": 21,
}


def _leg(symbol, qty, cost_basis, market_value):
    return SimpleNamespace(
        symbol=symbol,
        qty=qty,
        cost_basis=cost_basis,
        market_value=market_value,
        unrealized_pl=market_value - cost_basis,
    )


# A real TSLA iron condor: short the 360 call and 360 put, long the 370 call
# and 350 put, opened for a net $800 credit.
CONDOR = [
    _leg("TSLA260911C00360000", -1, -900, -915),
    _leg("TSLA260911C00370000", 1, 530, 520),
    _leg("TSLA260911P00350000", 1, 555, 525),
    _leg("TSLA260911P00360000", -1, -985, -975),
]


class ParseOccTests(unittest.TestCase):
    def test_parses_an_option_symbol(self):
        parsed = parse_occ("TSLA260911C00360000")
        self.assertEqual(parsed["root"], "TSLA")
        self.assertEqual(parsed["expiry"], date(2026, 9, 11))
        self.assertEqual(parsed["right"], "call")
        self.assertEqual(parsed["strike"], 360.0)

    def test_rejects_an_equity_symbol(self):
        # Equities carry broker-side brackets and must not be grouped here.
        self.assertIsNone(parse_occ("TSLA"))
        self.assertIsNone(parse_occ("BTC/USD"))


class GroupingTests(unittest.TestCase):
    def test_four_legs_group_into_one_structure(self):
        groups = group_positions(CONDOR)
        self.assertEqual(len(groups), 1)
        group = groups["TSLA:2026-09-11"]
        self.assertEqual(len(group["legs"]), 4)
        # Net credit of $800 taken in, currently worth -$845 to close.
        self.assertAlmostEqual(group["cost_basis"], -800.0)
        self.assertAlmostEqual(group["market_value"], -845.0)
        self.assertAlmostEqual(group["unrealized_pl"], -45.0)

    def test_different_expiries_stay_separate(self):
        legs = CONDOR + [_leg("TSLA261016C00400000", -1, -300, -280)]
        groups = group_positions(legs)
        self.assertEqual(set(groups), {"TSLA:2026-09-11", "TSLA:2026-10-16"})

    def test_equity_positions_are_ignored(self):
        groups = group_positions([_leg("AAPL", 10, 1000, 1100)])
        self.assertEqual(groups, {})


class CreditStructureTests(unittest.TestCase):
    """Net premium received: stop at a multiple of the credit."""

    def setUp(self):
        self.group = group_positions(CONDOR)["TSLA:2026-09-11"]
        self.today = date(2026, 9, 1)  # 10 days out is inside the DTE window

    def _at(self, unrealized_pl, today=None):
        group = dict(self.group, unrealized_pl=unrealized_pl)
        return evaluate_group(group, CONFIG, today=today or date(2026, 8, 1))

    def test_holds_a_small_loss(self):
        decision = self._at(-45.0)
        self.assertEqual(decision["action"], "hold")
        self.assertEqual(decision["structure"], "credit")

    def test_takes_profit_at_the_threshold(self):
        # 35% of the $800 credit is $280.
        self.assertEqual(self._at(279.0)["action"], "hold")
        decision = self._at(280.0)
        self.assertEqual(decision["action"], "close")
        self.assertIn("profit target", decision["reason"])

    def test_stops_out_at_the_multiple(self):
        # 1.5x the $800 credit is $1,200 of loss.
        self.assertEqual(self._at(-1199.0)["action"], "hold")
        decision = self._at(-1200.0)
        self.assertEqual(decision["action"], "close")
        self.assertIn("stop loss", decision["reason"])

    def test_stop_wins_over_profit_when_both_somehow_apply(self):
        # Only reachable from stale numbers, and then the loss is what matters.
        config = dict(CONFIG, options_take_profit_pct=-1.0)
        group = dict(self.group, unrealized_pl=-5000.0)
        decision = evaluate_group(group, config, today=date(2026, 8, 1))
        self.assertIn("stop loss", decision["reason"])

    def test_closes_on_time_before_expiry(self):
        decision = self._at(-45.0, today=self.today)
        self.assertEqual(decision["action"], "close")
        self.assertIn("time exit", decision["reason"])
        self.assertEqual(decision["dte"], 10)


class DebitStructureTests(unittest.TestCase):
    """Net premium paid: a 1.5x stop could never fire, so a fraction is used."""

    def setUp(self):
        # Bull call spread bought for a net $320 debit.
        self.legs = [
            _leg("AAPL261016C00185000", 1, 800, 800),
            _leg("AAPL261016C00195000", -1, -480, -480),
        ]

    def _at(self, unrealized_pl):
        group = group_positions(self.legs)["AAPL:2026-10-16"]
        group = dict(group, unrealized_pl=unrealized_pl)
        return evaluate_group(group, CONFIG, today=date(2026, 8, 1))

    def test_identified_as_a_debit(self):
        decision = self._at(0.0)
        self.assertEqual(decision["structure"], "debit")
        self.assertAlmostEqual(decision["premium"], 320.0)

    def test_stops_at_half_the_premium_paid(self):
        # A credit-style 1.5x stop would want $480 of loss on a spread that
        # can only lose $320 -- it would never fire. Half the debit is $160.
        self.assertEqual(self._at(-159.0)["action"], "hold")
        decision = self._at(-160.0)
        self.assertEqual(decision["action"], "close")
        self.assertIn("stop loss", decision["reason"])

    def test_takes_profit_at_the_same_fraction(self):
        decision = self._at(112.0)  # 35% of $320
        self.assertEqual(decision["action"], "close")
        self.assertIn("profit target", decision["reason"])


class DegenerateInputTests(unittest.TestCase):
    def test_zero_premium_is_held_not_divided_by(self):
        group = {
            "key": "X:2026-10-16",
            "underlying": "X",
            "expiry": date(2026, 10, 16),
            "legs": [],
            "cost_basis": 0.0,
            "market_value": 0.0,
            "unrealized_pl": 0.0,
        }
        decision = evaluate_group(group, CONFIG, today=date(2026, 8, 1))
        self.assertEqual(decision["action"], "hold")
        self.assertEqual(decision["pl_pct_of_premium"], 0.0)

    def test_thresholds_of_zero_disable_their_exit(self):
        config = dict(CONFIG, options_take_profit_pct=0, options_stop_loss_multiple=0,
                      options_close_dte=0)
        group = group_positions(CONDOR)["TSLA:2026-09-11"]
        group = dict(group, unrealized_pl=100000.0)
        self.assertEqual(evaluate_group(group, config, today=date(2026, 8, 1))["action"], "hold")


class BreakerTests(unittest.TestCase):
    """The flatten trigger, which is the one path that can liquidate a book."""

    def _guard(self, **overrides):
        state = {"high_water_mark": overrides.pop("high_water_mark", 100000.0)}
        config = {
            "daily_loss_halt_pct": overrides.pop("daily_loss_halt_pct", 10.0),
            "max_drawdown_halt_pct": overrides.pop("max_drawdown_halt_pct", 15.0),
        }
        return SimpleNamespace(enabled=True, config=config, _state=state,
                               kill_switch_active=lambda: overrides.pop("kill", False))

    def _run(self, guard, account):
        import tradingagents.execution.position_manager as pm

        fake_safety = SimpleNamespace(get_safety_guard=lambda: guard)
        fake_utils = SimpleNamespace(AlpacaUtils=SimpleNamespace(
            get_account_info=lambda: account))
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict)             else __import__

        def fake_import(name, *args, **kwargs):
            if name == "tradingagents.safety":
                return fake_safety
            if name == "tradingagents.dataflows.alpaca_utils":
                return fake_utils
            return real_import(name, *args, **kwargs)

        import builtins
        original = builtins.__import__
        builtins.__import__ = fake_import
        try:
            return pm._tripped_breaker({})
        finally:
            builtins.__import__ = original

    def test_a_healthy_account_trips_nothing(self):
        self.assertIsNone(
            self._run(self._guard(), {"equity": 99000.0, "last_equity": 99500.0})
        )

    def test_an_engaged_kill_switch_does_not_flatten(self):
        # A kill switch is a halt on new exposure, not an instruction to
        # liquidate. It also used to be read as a property -- a bound method is
        # always truthy, so every run flattened the entire book.
        guard = self._guard(kill=True)
        self.assertIsNone(
            self._run(guard, {"equity": 99000.0, "last_equity": 99500.0})
        )

    def test_daily_loss_breaker_trips(self):
        reason = self._run(self._guard(), {"equity": 89000.0, "last_equity": 100000.0})
        self.assertIsNotNone(reason)
        self.assertIn("daily loss", reason)

    def test_drawdown_breaker_trips(self):
        reason = self._run(
            self._guard(high_water_mark=100000.0),
            {"equity": 84000.0, "last_equity": 84500.0},
        )
        self.assertIsNotNone(reason)
        self.assertIn("drawdown", reason)

    def test_an_unreadable_account_does_not_flatten(self):
        # get_account_info returns zeros when the broker call fails; reading
        # that as a 100% drawdown would liquidate the book on a network blip.
        self.assertIsNone(self._run(self._guard(), {"equity": 0.0, "last_equity": 0.0}))


if __name__ == "__main__":
    unittest.main()
