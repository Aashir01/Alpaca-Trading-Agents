"""
webui/components/cost_panel.py - LLM cost monitoring panel

Attributes LLM spend from the persisted run logs to analyses, days,
symbols, and models, next to each symbol's realized returns — so cost
without benefit is visible at a glance. Estimates are an upper bound
(cache-read discounts are not recorded) and unknown models are surfaced
as unpriced tokens rather than guessed.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from webui.components.app_shell import panel
from webui.utils.charts import STATIC_CONFIG, empty_figure


def create_cost_panel():
    """Create the LLM cost panel for the web UI."""
    actions = dbc.Button(
        [html.I(className="fas fa-rotate me-2"), "Refresh"],
        id="cost-refresh-btn",
        color="primary",
        size="sm",
    )

    body = [
        html.Div(
            "Estimated spend from recorded token usage — attributed per day, symbol, "
            "and model, against realized returns. Prices are estimates (override via "
            "llm_pricing_per_million); cache discounts are not tracked, so this is an "
            "upper bound.",
            className="panel-blurb",
        ),
        dcc.Loading(
            id="cost-loading",
            type="default",
            children=html.Div(
                [
                    html.Div(id="cost-summary-cards", className="mb-3"),
                    html.Div(
                        dcc.Graph(
                            id="cost-daily-graph",
                            figure=empty_figure("No recorded LLM spend yet"),
                            config=STATIC_CONFIG,
                            style={"height": "260px", "width": "100%"},
                        ),
                        id="cost-graph-container",
                        style={"display": "none"},
                    ),
                    html.Div(id="cost-symbol-table", className="mb-2"),
                    html.Div(id="cost-model-table"),
                ]
            ),
        ),
    ]

    return panel("LLM Cost Monitor", body, icon="fa-coins", actions=actions)
