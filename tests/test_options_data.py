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

    def test_iv_rank_and_percentile_are_different_statistics(self):
        """A single spike gives a low rank and a high percentile.

        They were once the same number reported twice, which hid exactly this
        case - the one where selling premium on a "high IV" reading is wrong.
        """
        history = [0.20, 0.21, 0.22, 0.23, 0.90]
        rank, percentile = options_data.compute_iv_rank(0.25, history)
        # 0.25 sits near the bottom of the 0.20-0.90 range...
        self.assertLess(rank, 10.0)
        # ...but is still higher than 4 of the 5 observations.
        self.assertGreater(percentile, 0.75)
        self.assertNotAlmostEqual(rank / 100.0, percentile)

    def test_select_atm_iv_prefers_the_strike_nearest_spot(self):
        """ATM IV must not be "the first contract that happens to have an IV"."""

        def q(symbol, strike, option_type, iv, expiry=date(2025, 1, 17)):
            return options_data.OptionQuote(
                symbol=symbol, underlying="AAPL", expiry=expiry, strike=strike,
                option_type=option_type, bid=1.0, ask=1.1, last=None, volume=None,
                open_interest=None, iv=iv, delta=None, gamma=None, theta=None,
                vega=None, underlying_price=None,
            )

        # Deep OTM wing listed first, true ATM later - the skewed wing IV (0.95)
        # must not be mistaken for ATM.
        chain = [
            q("W", 250.0, "call", 0.95),
            q("C", 150.0, "call", 0.30),
            q("P", 150.0, "put", 0.34),
        ]
        atm = options_data._select_atm_iv(chain, spot=150.0)
        self.assertAlmostEqual(atm, 0.32)  # mean of the ATM call and put

    def test_select_atm_iv_without_spot_falls_back_to_median(self):
        """With no spot we cannot know the money, so do not pick arbitrarily."""

        def q(iv):
            return options_data.OptionQuote(
                symbol="X", underlying="AAPL", expiry=None, strike=None,
                option_type="call", bid=1.0, ask=1.1, last=None, volume=None,
                open_interest=None, iv=iv, delta=None, gamma=None, theta=None,
                vega=None, underlying_price=None,
            )

        self.assertEqual(options_data._select_atm_iv([q(0.2), q(0.3), q(0.9)], spot=None), 0.3)

    def test_fetch_spot_uses_the_normalized_quote_dict(self):
        """Regression: this used to treat the quote response as a DataFrame."""
        with patch.object(
            options_data.AlpacaUtils,
            "get_latest_quote",
            return_value={"bid_price": 149.0, "ask_price": 151.0},
        ):
            self.assertEqual(options_data._fetch_spot("AAPL"), 150.0)

    def test_fetch_spot_returns_none_on_empty_quote(self):
        with patch.object(options_data.AlpacaUtils, "get_latest_quote", return_value={}):
            self.assertIsNone(options_data._fetch_spot("AAPL"))

    def test_fetch_hv_20_passes_a_timeframe_object(self):
        """Regression: a "1Day" string was passed where a TimeFrame is required."""
        from alpaca.data.timeframe import TimeFrame

        client = MagicMock()
        client.get_stock_bars.side_effect = AssertionError("stop after capturing the request")
        with patch.object(options_data, "get_alpaca_stock_client", return_value=client):
            options_data._fetch_hv_20("AAPL")

        request = client.get_stock_bars.call_args[0][0]
        self.assertIsInstance(request.timeframe, TimeFrame)

    def test_market_context_reports_iv_history_depth(self):
        client = MagicMock()
        client.get_option_chain.return_value = {
            "AAPL250117C00150000": MockSnapshot(bid=2.5, ask=2.6, iv=0.35),
        }
        with patch.object(options_data, "_fetch_spot", return_value=150.0), \
             patch.object(options_data, "_fetch_hv_20", return_value=22.0), \
             patch.object(options_data, "_fetch_days_to_earnings", return_value=None), \
             patch.object(options_data, "save_iv_history"), \
             patch.object(
                 options_data,
                 "load_iv_history",
                 return_value={"2025-01-01": 0.25, "2025-01-02": 0.30},
             ):
            ctx, _ = options_data.get_options_market_context(
                "AAPL", spot=150.0, trade_date="2025-01-10", client=client
            )
        self.assertEqual(ctx.iv_history_days, 2)

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
