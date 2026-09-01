"""Horizons must change what the trader reads and what it reasons over.

A day trader handed 1h/4h/1d bars cannot see an opening range, and a persona
that never reaches the prompt is decoration. Both halves are asserted here.
"""

import unittest

from tradingagents.dataflows.technical_brief import HORIZON_TIMEFRAMES, TIMEFRAMES
from tradingagents.prompts import load_prompt


class TestHorizonTimeframes(unittest.TestCase):
    def test_intraday_horizons_read_intraday_bars(self):
        for horizon in ("day", "scalp"):
            tfs = HORIZON_TIMEFRAMES[horizon]
            self.assertIn("5m", tfs, f"{horizon} cannot see 5-minute structure")
            self.assertNotIn("1d", tfs, f"{horizon} should not reason from daily bars")

    def test_swing_is_unchanged(self):
        self.assertEqual(HORIZON_TIMEFRAMES["swing"], ("1h", "4h", "1d"))

    def test_every_horizon_timeframe_is_fetchable(self):
        for horizon, tfs in HORIZON_TIMEFRAMES.items():
            for tf in tfs:
                self.assertIn(tf, TIMEFRAMES, f"{horizon} names an unfetchable timeframe {tf}")


class TestHorizonPersonas(unittest.TestCase):
    def test_personas_load_and_are_substantive(self):
        for name in ("trader/day_trader", "trader/scalper"):
            text = load_prompt(name)
            self.assertGreater(len(text), 800, f"{name} is too thin to steer behaviour")

    def test_day_trader_carries_its_setup_rules(self):
        text = load_prompt("trader/day_trader").lower()
        for token in ("opening range", "vwap", "relative volume", "dte"):
            self.assertIn(token, text, f"day trader prompt lost '{token}'")

    def test_scalper_states_the_latency_limit(self):
        """It must not claim a speed the system cannot deliver."""
        text = load_prompt("trader/scalper").lower()
        self.assertIn("minutes, not milliseconds", text)
        self.assertIn("never sell premium", text)

    def test_personas_are_selected_by_horizon(self):
        from tradingagents.agents.trader.trader import HORIZON_PERSONAS

        self.assertEqual(HORIZON_PERSONAS["day"], "trader/day_trader")
        self.assertEqual(HORIZON_PERSONAS["scalp"], "trader/scalper")
        self.assertNotIn("swing", HORIZON_PERSONAS)


if __name__ == "__main__":
    unittest.main()
