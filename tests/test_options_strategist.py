"""Tests for the Options Strategist node.

Uses mocked Alpaca account/positions and a fake structured LLM.
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from tradingagents.agents.options_strategist import create_options_strategist
from tradingagents.agents.schemas import OptionsLeg, OptionsStrategy, OptionsStrategyProposal
from tradingagents.dataflows.options_data import OptionQuote


class FakeStructuredLLM:
    def __init__(self, proposal):
        self.proposal = proposal

    def invoke(self, prompt):
        return self.proposal


class TestOptionsStrategist(unittest.TestCase):
    def _make_node(self, config=None, proposal=None):
        config = config or {}
        llm = MagicMock()
        node = create_options_strategist(llm, config)
        if proposal is not None:
            node.__self__._structured_llm = FakeStructuredLLM(proposal)
        return node

    @patch("tradingagents.agents.options_strategist.AlpacaUtils")
    def test_disabled_returns_no_plan(self, mock_alpaca):
        llm = MagicMock()
        node = create_options_strategist(llm, {"options_trading_enabled": False})
        state = {
            "company_of_interest": "AAPL",
            "recommended_action": "BUY",
            "trader_investment_plan": {"confidence": "high"},
            "trade_date": "2025-01-10",
        }
        result = node(state)
        self.assertIn("disabled", result["options_strategy_report"].lower())
        self.assertIsNone(result["options_trade_plan"])

    @patch("tradingagents.agents.options_strategist.AlpacaUtils")
    @patch("tradingagents.agents.options_strategist.get_option_chain_context")
    @patch("tradingagents.agents.options_strategist.get_options_market_context")
    @patch("tradingagents.agents.options_strategist.bind_structured")
    def test_bullish_long_call_plan(self, mock_bind, mock_ctx, mock_chain, mock_alpaca):
        mock_alpaca.get_account_info.return_value = {
            "equity": 100000.0,
            "buying_power": 100000.0,
            "cash": 50000.0,
        }
        mock_alpaca.get_positions_data.return_value = []

        from tradingagents.dataflows.options_data import OptionsMarketContext

        mock_ctx.return_value = (
            OptionsMarketContext(
                symbol="AAPL",
                spot=150.0,
                atm_iv=0.35,
                iv_rank=45.0,
                iv_percentile=0.45,
                hv_20=20.0,
                days_to_earnings=15,
                timestamp="2025-01-10T10:00:00",
            ),
            [],
        )
        mock_chain.return_value = [
            OptionQuote(
                symbol="AAPL250117C00150000",
                underlying="AAPL",
                expiry=date(2025, 1, 17),
                strike=150.0,
                option_type="call",
                bid=2.50,
                ask=2.60,
                last=None,
                volume=None,
                open_interest=None,
                iv=0.35,
                delta=0.5,
                gamma=0.05,
                theta=-0.01,
                vega=0.1,
                underlying_price=150.0,
            )
        ]

        proposal = OptionsStrategyProposal(
            strategy=OptionsStrategy.LONG_CALL,
            symbol="AAPL",
            direction="bullish",
            legs=[
                OptionsLeg(
                    symbol="AAPL250117C00150000",
                    side="buy",
                    ratio_qty=1,
                    strike=150.0,
                    expiry="2025-01-17",
                    option_type="call",
                )
            ],
            rationale="Low IV rank + strong bullish conviction.",
            max_loss_estimate=255.0,
            expected_credit_debit=2.55,
            iv_rank_used=45.0,
            days_to_earnings=15,
        )
        mock_bind.return_value = FakeStructuredLLM(proposal)

        llm = MagicMock()
        node = create_options_strategist(llm, {"options_trading_enabled": True})
        state = {
            "company_of_interest": "AAPL",
            "recommended_action": "BUY",
            "trader_investment_plan": {"confidence": "high"},
            "trade_date": "2025-01-10",
        }
        result = node(state)
        self.assertIn("LONG_CALL", result["options_strategy_report"].upper())
        self.assertIsNotNone(result["options_trade_plan"])
        self.assertEqual(result["options_trade_plan"]["strategy"], "long_call")


if __name__ == "__main__":
    unittest.main()
