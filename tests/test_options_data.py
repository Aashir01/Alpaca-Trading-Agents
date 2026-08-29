"""Tests for options_data.py.

All tests use mocked Alpaca clients so they remain offline.
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from tradingagents.dataflows import options_data


class MockQuote:
    def __init__(self, bid, ask):
        self.bid_price = bid
        self.ask_price = ask


class MockGreeks:
    def __init__(self):
        self.delta = 0.5
        self.gamma = 0.05
        self.theta = -0.01
        self.vega = 0.1


class MockSnapshot:
    def __init__(self, bid=2.5, ask=2.6, iv=0.45):
        self.latest_quote = MockQuote(bid, ask)
        self.latest_trade = None
        self.greeks = MockGreeks()
        self.implied_volatility = iv


class TestOptionsData(unittest.TestCase):
    def test_compute_iv_rank_known_series(self):
        history = [0.20, 0.25, 0.30, 0.35, 0.40]
        rank, percentile = options_data.compute_iv_rank(0.30, history)
        self.assertEqual(rank, 50.0)
        self.assertEqual(percentile, 0.5)

    def test_compute_iv_rank_empty_history(self):
        rank, percentile = options_data.compute_iv_rank(0.30, [])
        self.assertIsNone(rank)
        self.assertIsNone(percentile)

    def test_get_option_chain_context_parses_and_sorts(self):
        client = MagicMock()
        client.get_option_chain.return_value = {
            "AAPL250117C00150000": MockSnapshot(bid=2.5, ask=2.6, iv=0.45),
            "AAPL250117P00150000": MockSnapshot(bid=2.3, ask=2.4, iv=0.46),
            "AAPL250117C00155000": MockSnapshot(bid=1.0, ask=1.1, iv=0.40),
        }

        quotes = options_data.get_option_chain_context(
            "AAPL", spot=153.0, dte_min=0, dte_max=100, client=client
        )
        self.assertEqual(len(quotes), 3)
        # Spot=153, so 155 (distance 2) is closer than 150 (distance 3).
        self.assertEqual(quotes[0].strike, 155.0)
        self.assertEqual(quotes[0].option_type, "call")
        self.assertEqual(quotes[0].iv, 0.40)
        self.assertEqual(quotes[0].delta, 0.5)

    def test_get_options_market_context_builds_iv_rank(self):
        client = MagicMock()
        client.get_option_chain.return_value = {
            "AAPL250117C00150000": MockSnapshot(bid=2.5, ask=2.6, iv=0.35),
        }
        with patch.object(
            options_data, "_fetch_spot", return_value=150.0
        ), patch.object(
            options_data, "_fetch_hv_20", return_value=22.0
        ), patch.object(
            options_data, "_fetch_days_to_earnings", return_value=15
        ), patch.object(
            options_data, "load_iv_history", return_value={"2025-01-01": 0.25, "2025-01-02": 0.30}
        ):
            ctx, chain_quotes = options_data.get_options_market_context(
                "AAPL", spot=150.0, trade_date="2025-01-10", client=client
            )
        self.assertEqual(ctx.symbol, "AAPL")
        self.assertEqual(ctx.spot, 150.0)
        self.assertEqual(ctx.atm_iv, 0.35)
        self.assertIsNotNone(ctx.iv_rank)
        self.assertEqual(ctx.hv_20, 22.0)
        self.assertEqual(ctx.days_to_earnings, 15)

    def test_option_symbol_parser(self):
        underlying, expiry, strike, option_type = options_data._parse_option_symbol(
            "AAPL250117C00150000"
        )
        self.assertEqual(underlying, "AAPL")
        self.assertEqual(expiry, date(2025, 1, 17))
        self.assertEqual(strike, 150.0)
        self.assertEqual(option_type, "call")


if __name__ == "__main__":
    unittest.main()
