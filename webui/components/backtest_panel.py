"""
webui/components/backtest_panel.py - Walk-forward backtest dashboard panel

Replays the decisions already recorded under eval_results/ against
historical prices (zero LLM cost) and reports the TradingAgents-paper
metric set: cumulative/annualized return, Sharpe ratio, max drawdown,
plus win rate, per walk-forward window and for the full period.

Controls and results are two panels: the controls are a short form that
should not scroll away, and the results only exist after a run.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from webui.components.app_shell import panel
from webui.utils.charts import STATIC_CONFIG, empty_figure


def _field(label, control, width="1fr"):
    return html.Div(
        [html.Label(label, className="field-label"), control],
        className="field",
        style={"flex": f"1 1 {width}"},
    )


def create_backtest_panel():
    """Create the backtest panels for the web UI."""
    controls = html.Div(
        [
            _field(
                "Symbol",
                dbc.Input(
                    id="backtest-symbol-input",
                    type="text",
                    placeholder="e.g. AAPL or BTC/USD",
                    debounce=True,
                ),
                width="180px",
            ),
            _field("Start date", dbc.Input(id="backtest-start-date", type="date"), "150px"),
            _field("End date", dbc.Input(id="backtest-end-date", type="date"), "150px"),
            _field(
                "Window (bars)",
                dbc.Input(id="backtest-window-bars", type="number", value=63, min=2, step=1),
                "120px",
            ),
            _field(
                "Slippage",
                dbc.Select(
                    id="backtest-slippage-model",
                    options=[
                        {"label": "Fixed (5 bps)", "value": "fixed"},
                        {"label": "Volatility-scaled", "value": "volatility"},
                        {"label": "None (frictionless)", "value": "none"},
                    ],
                    value="fixed",
                ),
                "170px",
            ),
            _field(
                "Direction",
                dbc.Switch(id="backtest-allow-shorts", label="Allow shorts", value=False),
                "140px",
            ),
            _field(
                " ",
                dbc.Button(
                    [html.I(className="fas fa-play me-2"), "Run Backtest"],
                    id="backtest-run-btn",
                    color="primary",
                    className="w-100",
                ),
                "160px",
            ),
        ],
        className="field-row",
    )

    teach_row = html.Div(
        [
            dbc.Button(
                [html.I(className="fas fa-graduation-cap me-2"), "Teach Memory"],
                id="backtest-teach-btn",
                color="secondary",
                outline=True,
                size="sm",
            ),
            html.Div(
                "Injects one dated lesson per recorded decision (with its realized "
                "next-open return) into the persistent agent memories — idempotent, "
                "zero LLM cost.",
                className="panel-blurb",
                style={"marginBottom": "0"},
            ),
        ],
        className="teach-row",
    )

    setup = panel(
        "Walk-Forward Backtest",
        [
            html.Div(
                "Replays this deployment's recorded agent decisions on historical "
                "prices — signals execute at the next bar's open (no lookahead).",
                className="panel-blurb",
            ),
            controls,
            teach_row,
            dcc.Loading(
                id="backtest-teach-loading",
                type="default",
                children=html.Div(id="backtest-teach-status", className="panel-notice"),
            ),
        ],
        icon="fa-flask",
    )

    results = panel(
        "Results",
        dcc.Loading(
            id="backtest-loading",
            type="default",
            children=html.Div(
                [
                    html.Div(id="backtest-status", className="panel-notice"),
                    html.Div(id="backtest-metrics", className="mb-3"),
                    html.Div(
                        dcc.Graph(
                            id="backtest-equity-graph",
                            figure=empty_figure("No backtest run yet"),
                            config=STATIC_CONFIG,
                            style={"height": "320px", "width": "100%"},
                        ),
                        id="backtest-graph-container",
                        style={"display": "none"},
                    ),
                    html.Div(id="backtest-windows-table"),
                ]
            ),
        ),
        icon="fa-chart-line",
    )

    return html.Div([setup, results])
