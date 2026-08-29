"""Tests for the application shell, routing, and dashboard rendering.

Two classes of bug motivated these:

* A page container or panel action span that no callback can find. Dash reports
  that only as a console error in the browser, so it is invisible to a test
  suite that never builds the layout.
* Dashboard panels that look fine empty and break on real data, since the
  empty state is the only state anyone sees before a live account is attached.
"""

import unittest
from unittest.mock import patch

from dash import html

from webui.components.app_shell import NAV_ITEMS, kpi_tile, panel


def _collect_ids(node, found=None):
    found = found if found is not None else set()
    if isinstance(node, (list, tuple)):
        for child in node:
            _collect_ids(child, found)
        return found
    component_id = getattr(node, "id", None)
    if isinstance(component_id, str):
        found.add(component_id)
    children = getattr(node, "children", None)
    if children is not None:
        _collect_ids(children, found)
    return found


class AppShellTests(unittest.TestCase):
    def test_panel_keeps_an_empty_actions_placeholder(self):
        """An empty Dash component is falsy, so `if actions:` silently drops it.

        Placeholder spans that callbacks fill later must still be mounted, or
        the callback output has no target.
        """
        built = panel("Title", "body", actions=html.Span(id="placeholder-span"))
        self.assertIn("placeholder-span", _collect_ids(built))

    def test_kpi_tile_exposes_value_and_tile_ids(self):
        tile = kpi_tile("Equity", "kpi-test", delta_id="kpi-test-delta", sub_id="kpi-test-sub")
        ids = _collect_ids(tile)
        for expected in ("kpi-test", "kpi-test-delta", "kpi-test-sub", "kpi-test-tile"):
            self.assertIn(expected, ids)


class LayoutWiringTests(unittest.TestCase):
    """The layout must satisfy every callback that references a fixed id."""

    @classmethod
    def setUpClass(cls):
        from webui.layout import create_main_layout

        cls.layout_ids = _collect_ids(create_main_layout())

    def test_every_page_container_exists(self):
        for page_id, _icon, _label, _badge in NAV_ITEMS:
            self.assertIn(f"page-{page_id}", self.layout_ids)

    def test_shell_and_dashboard_targets_exist(self):
        required = [
            # Shell
            "topbar-title", "topbar-equity", "topbar-daypl", "topbar-bp",
            "topbar-market", "topbar-mode", "sidebar-status", "active-page-store",
            # Controls the pre-existing callbacks still listen to
            "refresh-btn", "open-api-config-btn",
            # Dashboard
            "kpi-equity", "kpi-daypl", "kpi-openpl", "kpi-bp", "kpi-exposure",
            "kpi-options", "dash-allocation-chart", "dash-pipeline",
            "dash-pipeline-status", "dash-positions", "dash-positions-count",
            "dash-options", "dash-decisions", "dash-orders",
            # Options desk
            "opt-kpi-status", "opt-kpi-maxloss", "opt-kpi-contracts", "opt-kpi-pl",
            "opt-proposal", "opt-proposal-symbol", "opt-gate", "opt-rules",
            "opt-positions", "opt-iv-history",
            # Intervals
            "dashboard-interval",
        ]
        missing = [component_id for component_id in required if component_id not in self.layout_ids]
        self.assertEqual(missing, [], f"layout is missing callback targets: {missing}")

    def test_no_duplicate_component_ids(self):
        from collections import Counter

        from webui.layout import create_main_layout

        seen = []

        def walk(node):
            if isinstance(node, (list, tuple)):
                for child in node:
                    walk(child)
                return
            component_id = getattr(node, "id", None)
            if isinstance(component_id, str):
                seen.append(component_id)
            children = getattr(node, "children", None)
            if children is not None:
                walk(children)

        walk(create_main_layout())
        duplicates = {k: v for k, v in Counter(seen).items() if v > 1}
        self.assertEqual(duplicates, {}, f"duplicate component ids: {duplicates}")

    def test_options_tab_is_present_in_reports(self):
        import dash_bootstrap_components as dbc

        from webui.components.reports_panel import create_reports_panel

        tab_ids = []

        def walk(node):
            if isinstance(node, (list, tuple)):
                for child in node:
                    walk(child)
                return
            if isinstance(node, dbc.Tab):
                tab_ids.append(node.tab_id)
            children = getattr(node, "children", None)
            if children is not None:
                walk(children)

        walk(create_reports_panel())
        self.assertIn("options-strategy", tab_ids)


class DashboardRenderingTests(unittest.TestCase):
    """Exercise the render helpers with real-shaped data, not just empties."""

    def setUp(self):
        from webui.callbacks import dashboard_callbacks

        self.module = dashboard_callbacks

    def test_parses_preformatted_position_money(self):
        self.assertEqual(self.module._parse_money("$1,234.56"), 1234.56)
        self.assertEqual(self.module._parse_money("-$50.00"), -50.0)
        self.assertEqual(self.module._parse_money("2.50%"), 2.5)
        self.assertEqual(self.module._parse_money(None), 0.0)
        self.assertEqual(self.module._parse_money("n/a"), 0.0)

    def test_identifies_occ_option_symbols(self):
        self.assertTrue(self.module._is_option_symbol("AAPL250117C00150000"))
        self.assertTrue(self.module._is_option_symbol("SPY250620P00400000"))
        self.assertFalse(self.module._is_option_symbol("AAPL"))
        self.assertFalse(self.module._is_option_symbol(""))
        self.assertFalse(self.module._is_option_symbol(None))

    def test_signed_money_formatting(self):
        self.assertEqual(self.module._signed_money(1234.5), "+$1,234.50")
        self.assertEqual(self.module._signed_money(-99), "-$99.00")
        self.assertEqual(self.module._signed_money(None), "—")

    def test_account_reports_not_connected_without_credentials(self):
        """Zeros are right for the risk gate and wrong for the UI."""
        with patch.object(self.module, "_alpaca_configured", return_value=False):
            info, error = self.module._account()
        self.assertIsNone(info)
        self.assertIn("not connected", error)


if __name__ == "__main__":
    unittest.main()
