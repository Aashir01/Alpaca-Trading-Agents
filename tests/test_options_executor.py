"""Tests for options_executor.py.

Uses mocked Alpaca trading client and safety guard.
"""

import unittest
from unittest.mock import MagicMock, patch

from tradingagents.execution.options_executor import submit_options_plan


class TestOptionsExecutor(unittest.TestCase):
    def _plan(self, strategy="long_call", expected_credit_debit=2.55):
        return {
            "strategy": strategy,
            "symbol": "AAPL",
            "direction": "bullish",
            "legs": [
                {
                    "symbol": "AAPL250117C00150000",
                    "side": "buy",
                    "ratio_qty": 1,
                    "strike": 150.0,
                    "expiry": "2025-01-17",
                    "option_type": "call",
                }
            ],
            "rationale": "test",
            "max_loss_estimate": 255.0,
            "expected_credit_debit": expected_credit_debit,
            "iv_rank_used": 45.0,
            "days_to_earnings": 15,
            "market_quotes": {"AAPL250117C00150000": {"bid": 2.50, "ask": 2.60}},
        }

    @patch("tradingagents.execution.options_executor.get_alpaca_trading_client")
    @patch("tradingagents.execution.options_executor.AlpacaUtils")
    @patch("tradingagents.execution.options_executor.get_safety_guard")
    def test_long_call_submission(self, mock_guard_get, mock_alpaca, mock_client_get):
        mock_alpaca.get_account_info.return_value = {
            "equity": 100000.0,
            "buying_power": 100000.0,
            "cash": 50000.0,
        }
        mock_alpaca.get_positions_data.return_value = []

        mock_client = MagicMock()
        submitted = MagicMock()
        submitted.id = "order-123"
        mock_client.submit_order.return_value = submitted
        mock_client_get.return_value = mock_client

        guard = MagicMock()
        guard.check_order.return_value = None
        mock_guard_get.return_value = guard

        result = submit_options_plan(
            self._plan(),
            final_action="BUY",
            qty=1,
        )
        if not result["submitted"]:
            print("DEBUG result:", result)
        self.assertTrue(result["submitted"])
        self.assertEqual(result["order_id"], "order-123")

        # Verify the broker received a simple option limit order with one leg.
        args = mock_client.submit_order.call_args
        order_request = args[0][0]
        self.assertEqual(order_request.order_class.value, "simple")
        self.assertEqual(order_request.symbol, "AAPL250117C00150000")
        self.assertEqual(order_request.limit_price, 2.55)

    @patch("tradingagents.execution.options_executor.AlpacaUtils")
    def test_direction_mismatch_veto(self, mock_alpaca):
        mock_alpaca.get_account_info.return_value = {
            "equity": 100000.0,
            "buying_power": 100000.0,
            "cash": 50000.0,
        }
        mock_alpaca.get_positions_data.return_value = []

        result = submit_options_plan(
            self._plan(),
            final_action="SELL",
            qty=1,
        )
        self.assertFalse(result["submitted"])
        self.assertIn("does not match", result["error"])

    @patch("tradingagents.execution.options_executor.AlpacaUtils")
    def test_missing_quotes_veto(self, mock_alpaca):
        mock_alpaca.get_account_info.return_value = {
            "equity": 100000.0,
            "buying_power": 100000.0,
            "cash": 50000.0,
        }
        mock_alpaca.get_positions_data.return_value = []

        plan = self._plan()
        plan["market_quotes"] = {}
        result = submit_options_plan(plan, final_action="BUY", qty=1)
        self.assertFalse(result["submitted"])
        self.assertIn("Missing or invalid quotes", result["error"])


if __name__ == "__main__":
    unittest.main()
