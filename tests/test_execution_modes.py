"""Human-in-the-loop must actually hold the trade back.

The whole point of approval mode is that a decision does not reach the broker
until a person says so, and that approving it twice cannot send it twice.
"""

import unittest

from webui.utils.state import AppState


class TestPendingTradeQueue(unittest.TestCase):
    def setUp(self):
        self.state = AppState()

    def test_staged_trade_is_held(self):
        self.state.stage_pending_trade("NVDA", "BUY", False, 4500)
        self.assertIn("NVDA", self.state.pending_trades)
        self.assertEqual(self.state.pending_trades["NVDA"]["decision"], "BUY")

    def test_taking_a_trade_removes_it(self):
        """Approving twice must not submit twice."""
        self.state.stage_pending_trade("NVDA", "BUY", False, 4500)
        self.assertIsNotNone(self.state.take_pending_trade("NVDA"))
        self.assertIsNone(self.state.take_pending_trade("NVDA"))

    def test_taking_an_unknown_symbol_is_safe(self):
        self.assertIsNone(self.state.take_pending_trade("NOPE"))

    def test_several_symbols_queue_independently(self):
        self.state.stage_pending_trade("NVDA", "BUY", False, 1000)
        self.state.stage_pending_trade("AAPL", "SELL", True, 2000)
        self.state.take_pending_trade("NVDA")
        self.assertEqual(list(self.state.pending_trades), ["AAPL"])

    def test_clear_empties_the_queue(self):
        self.state.stage_pending_trade("NVDA", "BUY", False, 1000)
        self.state.clear_pending_trades()
        self.assertEqual(self.state.pending_trades, {})


class TestExecutionModeDefault(unittest.TestCase):
    def test_default_is_approval_not_autonomous(self):
        """Unattended execution should be opt-in, never inherited."""
        import os

        from tradingagents.default_config import DEFAULT_CONFIG

        if os.getenv("EXECUTION_MODE"):
            self.skipTest("EXECUTION_MODE is set in this environment")
        self.assertEqual(DEFAULT_CONFIG["execution_mode"], "approval")


if __name__ == "__main__":
    unittest.main()
