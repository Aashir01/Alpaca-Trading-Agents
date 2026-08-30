"""The orders table must survive a multi-leg options order.

An mleg order carries Asset/Side as None -- the legs hold them, not the parent.
`order.get("Side", "")` still returns None when the key exists and is null, so
the whole table failed to render as soon as one options spread was on the
account: "Error rendering orders table: 'NoneType' object has no attribute
'lower'".
"""

import unittest

from webui.components.alpaca_account import render_orders_table_body


class TestOrdersTableRendering(unittest.TestCase):
    def _order(self, **overrides):
        base = {
            "Asset": "NVDA", "Side": "buy", "Status": "filled",
            "Order Type": "market", "Avg. Fill Price": "218.62",
            "Qty": "2", "Filled Qty": "2",
        }
        base.update(overrides)
        return base

    def test_multi_leg_order_with_null_fields_renders(self):
        rows = render_orders_table_body([self._order(Asset=None, Side=None)])
        self.assertTrue(rows)

    def test_null_status_renders(self):
        rows = render_orders_table_body([self._order(Status=None)])
        self.assertTrue(rows)

    def test_ordinary_order_still_renders(self):
        rows = render_orders_table_body([self._order()])
        self.assertTrue(rows)

    def test_mixed_orders_render_together(self):
        rows = render_orders_table_body(
            [self._order(Asset=None, Side=None, Status="accepted"), self._order()]
        )
        self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()
