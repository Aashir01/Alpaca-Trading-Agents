"""The MCP submission path in options_executor.

The transport is patched throughout: these tests must never reach a broker.
"""

import unittest
from unittest.mock import MagicMock, patch

from tradingagents.execution import options_executor
from tradingagents.mcp_client import AlpacaMCPError


def _proposal(legs):
    p = MagicMock()
    p.symbol = "AAPL"
    p.legs = legs
    return p


def _leg(symbol, side, ratio=1):
    leg = MagicMock()
    leg.symbol = symbol
    leg.side = side
    leg.ratio_qty = ratio
    return leg


class TestMCPArguments(unittest.TestCase):
    def test_multi_leg_sends_legs_and_no_parent_symbol(self):
        """Alpaca rejects an mleg order that also carries a parent symbol."""
        proposal = _proposal([
            _leg("AAPL260909C00300000", "buy"),
            _leg("AAPL260909C00307500", "sell"),
        ])
        with patch.object(options_executor, "call_alpaca_tool",
                          return_value={"id": "abc-123"}) as call:
            order_id = options_executor._submit_via_mcp(proposal, 2, 5.87, False)
        self.assertEqual(order_id, "abc-123")
        args = call.call_args[0][1]
        self.assertNotIn("symbol", args)
        self.assertNotIn("side", args)
        self.assertEqual(args["order_class"], "mleg")
        self.assertEqual(args["qty"], "2")
        self.assertEqual(args["limit_price"], "5.87")
        self.assertEqual(args["time_in_force"], "day")
        self.assertEqual(len(args["legs"]), 2)
        # The tool takes strings, including ratio_qty.
        for leg in args["legs"]:
            self.assertIsInstance(leg["ratio_qty"], str)
            self.assertIn(leg["side"], ("buy", "sell"))

    def test_single_leg_sends_symbol_and_scaled_qty(self):
        proposal = _proposal([_leg("AAPL260909C00300000", "buy", ratio=2)])
        with patch.object(options_executor, "call_alpaca_tool",
                          return_value={"id": "single-1"}) as call:
            options_executor._submit_via_mcp(proposal, 3, 1.25, True)
        args = call.call_args[0][1]
        self.assertEqual(args["symbol"], "AAPL260909C00300000")
        self.assertEqual(args["side"], "buy")
        self.assertEqual(args["qty"], "6")          # 3 units x ratio 2
        self.assertNotIn("legs", args)

    def test_missing_order_id_is_a_failure(self):
        """Never report a submitted trade the broker did not acknowledge."""
        proposal = _proposal([_leg("AAPL260909C00300000", "buy")])
        with patch.object(options_executor, "call_alpaca_tool",
                          return_value={"status": "queued"}):
            with self.assertRaises(AlpacaMCPError):
                options_executor._submit_via_mcp(proposal, 1, 1.0, True)

    def test_order_id_read_from_nested_result(self):
        proposal = _proposal([_leg("AAPL260909C00300000", "buy")])
        with patch.object(options_executor, "call_alpaca_tool",
                          return_value={"result": {"id": "nested-9"}}):
            self.assertEqual(
                options_executor._submit_via_mcp(proposal, 1, 1.0, True), "nested-9"
            )


if __name__ == "__main__":
    unittest.main()
