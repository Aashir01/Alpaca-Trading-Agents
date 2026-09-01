"""
webui/components/chart_panel.py - Price chart with symbol-based pagination

The panel keeps every component id the chart callbacks target -- the symbol
pager, the four period buttons, the manual refresh, the timestamp line and the
hidden ``chart-pagination`` the control callbacks drive -- and only changes the
skin, so it sits inside the app's panel system instead of beside it.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from webui.components.app_shell import panel
from webui.utils.charts import INTERACTIVE_CONFIG, create_welcome_chart

# (component id, label) for the range strip. Labels are the trader-facing
# spelling; the ids are what the existing callbacks match on.
PERIOD_BUTTONS = [
    ("period-1d", "1D"),
    ("period-1w", "1W"),
    ("period-1mo", "1M"),
    ("period-1y", "1Y"),
]


def create_symbol_pagination(pagination_id, max_symbols=1):
    """Symbol pager. Filled by the chart callbacks; ids are load-bearing."""
    return html.Div(
        id=f"{pagination_id}-container",
        children=html.Div(
            "No symbols available",
            className="text-faint",
            style={"padding": "8px", "fontSize": "12px"},
        ),
        className="symbol-pagination-container",
    )


def create_chart_panel():
    """Price and volume for the symbol currently under analysis."""
    range_strip = html.Div(
        [
            dbc.Button(label, id=button_id, className="seg-btn", n_clicks=0)
            for button_id, label in PERIOD_BUTTONS
        ],
        className="segmented",
    )

    body = [
        html.Div(
            [
                html.Div(create_symbol_pagination("chart-pagination"),
                         className="chart-toolbar-symbols"),
                html.Div(
                    [
                        range_strip,
                        html.Button(
                            html.I(className="fas fa-rotate"),
                            id="manual-chart-refresh",
                            className="icon-btn",
                            title="Reload this chart",
                            n_clicks=0,
                        ),
                    ],
                    className="chart-toolbar-actions",
                ),
            ],
            className="chart-toolbar",
        ),
        html.Div(
            [
                html.Span(id="current-symbol-display", className="chart-caption-value"),
                html.Span(id="chart-last-updated", className="text-faint"),
            ],
            className="chart-caption",
        ),
        dcc.Graph(
            id="chart-container",
            figure=create_welcome_chart(),
            config=INTERACTIVE_CONFIG,
            className="graph-fill",
            style={"minHeight": "420px", "width": "100%"},
        ),
        # The control callbacks drive the real dbc pagination; the visible
        # symbol buttons above are a skin over it, so it stays mounted.
        html.Div(
            dbc.Pagination(
                id="chart-pagination",
                max_value=1,
                fully_expanded=True,
                first_last=True,
                previous_next=True,
                className="d-none",
            ),
            style={"display": "none"},
        ),
    ]

    return panel("Price & Volume", body, icon="fa-chart-column")
