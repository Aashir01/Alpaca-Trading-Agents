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


class TestExecutorPricing(unittest.TestCase):
    """The limit price must come from live quotes, never from the model."""

    def _plan(self, expected_credit_debit):
        return {
            "strategy": "long_call",
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
            "market_quotes": {"AAPL250117C00150000": {"bid": 2.50, "ask": 2.60}},
        }

    @patch("tradingagents.execution.options_executor.get_alpaca_trading_client")
    @patch("tradingagents.execution.options_executor.AlpacaUtils")
    @patch("tradingagents.execution.options_executor.get_safety_guard")
    def test_hallucinated_estimate_does_not_price_the_order(
        self, mock_guard_get, mock_alpaca, mock_client_get
    ):
        mock_alpaca.get_account_info.return_value = {
            "equity": 100000.0, "buying_power": 100000.0, "cash": 50000.0,
        }
        mock_alpaca.get_positions_data.return_value = []
        mock_client = MagicMock()
        submitted = MagicMock()
        submitted.id = "order-999"
        mock_client.submit_order.return_value = submitted
        mock_client_get.return_value = mock_client
        mock_guard_get.return_value = MagicMock(check_order=MagicMock(return_value=None))

        # The model claims $99.99/share; the real mid is 2.55.
        result = submit_options_plan(self._plan(99.99), final_action="BUY", qty=1)

        self.assertTrue(result["submitted"], result.get("error"))
        order_request = mock_client.submit_order.call_args[0][0]
        self.assertEqual(order_request.limit_price, 2.55)
        self.assertEqual(result["limit_price"], 2.55)
        self.assertEqual(result["model_estimate"], 99.99)

    @patch("tradingagents.execution.options_executor.get_alpaca_trading_client")
    @patch("tradingagents.execution.options_executor.AlpacaUtils")
    @patch("tradingagents.execution.options_executor.get_safety_guard")
    def test_missing_model_estimate_still_prices_from_quotes(
        self, mock_guard_get, mock_alpaca, mock_client_get
    ):
        mock_alpaca.get_account_info.return_value = {
            "equity": 100000.0, "buying_power": 100000.0, "cash": 50000.0,
        }
        mock_alpaca.get_positions_data.return_value = []
        mock_client = MagicMock()
        submitted = MagicMock()
        submitted.id = "order-1000"
        mock_client.submit_order.return_value = submitted
        mock_client_get.return_value = mock_client
        mock_guard_get.return_value = MagicMock(check_order=MagicMock(return_value=None))

        result = submit_options_plan(self._plan(None), final_action="BUY", qty=1)

        self.assertTrue(result["submitted"], result.get("error"))
        self.assertEqual(mock_client.submit_order.call_args[0][0].limit_price, 2.55)

    @patch("tradingagents.execution.options_executor.get_alpaca_trading_client")
    @patch("tradingagents.execution.options_executor.AlpacaUtils")
    @patch("tradingagents.execution.options_executor.get_safety_guard")
    def test_credit_spread_limit_price_is_positive(
        self, mock_guard_get, mock_alpaca, mock_client_get
    ):
        """A net credit is negative internally; Alpaca needs a positive limit."""
        mock_alpaca.get_account_info.return_value = {
            "equity": 100000.0, "buying_power": 100000.0, "cash": 50000.0,
        }
        mock_alpaca.get_positions_data.return_value = []
        mock_client = MagicMock()
        submitted = MagicMock()
        submitted.id = "order-1001"
        mock_client.submit_order.return_value = submitted
        mock_client_get.return_value = mock_client
        mock_guard_get.return_value = MagicMock(check_order=MagicMock(return_value=None))

        plan = {
            "strategy": "bull_put_spread",
            "symbol": "AAPL",
            "direction": "bullish",
            "legs": [
                {"symbol": "SHORTP", "side": "sell", "ratio_qty": 1, "strike": 150.0,
                 "expiry": "2025-01-17", "option_type": "put"},
                {"symbol": "LONGP", "side": "buy", "ratio_qty": 1, "strike": 145.0,
                 "expiry": "2025-01-17", "option_type": "put"},
            ],
            "rationale": "high IV bullish credit spread",
            "expected_credit_debit": -1.50,
            "market_quotes": {
                "SHORTP": {"bid": 3.00, "ask": 3.10},
                "LONGP": {"bid": 1.00, "ask": 1.10},
            },
        }
        result = submit_options_plan(plan, final_action="BUY", qty=1)

        self.assertTrue(result["submitted"], result.get("error"))
        order_request = mock_client.submit_order.call_args[0][0]
        self.assertGreater(order_request.limit_price, 0)
        # Net credit per share = 3.05 - 1.05 = 2.00.
        self.assertEqual(order_request.limit_price, 2.00)
        self.assertEqual(order_request.order_class.value, "mleg")


if __name__ == "__main__":
    unittest.main()
