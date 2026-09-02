"""Trade Ledger page: every order this deployment has placed.

The run logs hold the reasoning; the ledger holds what reached the broker.
This page joins them, so a decision can be read next to the order it produced
and the fill that came back.
"""

from dash import dcc, html

from webui.components.app_shell import empty_state, kpi_tile, page_header, panel
from webui.utils.charts import STATIC_CONFIG, empty_figure


def create_ledger_page():
    return html.Div(
        [
            page_header(
                "Trade Ledger",
                "Every order placed, the rule that caused it, and what the broker did with it",
            ),
            html.Div(
                [
                    kpi_tile("Entries", "ledger-kpi-entries", icon="fa-arrow-right-to-bracket",
                             tone="neutral", sub_id="ledger-kpi-entries-sub"),
                    kpi_tile("Exits", "ledger-kpi-exits", icon="fa-arrow-right-from-bracket",
                             tone="neutral", sub_id="ledger-kpi-exits-sub"),
                    kpi_tile("Symbols Traded", "ledger-kpi-symbols", icon="fa-tags",
                             tone="neutral", sub_id="ledger-kpi-symbols-sub"),
                    kpi_tile("Recorded Runs", "ledger-kpi-runs", icon="fa-file-lines",
                             tone="opt", sub_id="ledger-kpi-runs-sub"),
                ],
                className="kpi-grid",
            ),
            panel(
                "Why Positions Were Closed",
                [
                    html.Div(
                        "Exit orders grouped by the rule that fired. A desk closing "
                        "mostly on stops is telling you something different from one "
                        "closing mostly on targets.",
                        className="chart-caption",
                    ),
                    dcc.Graph(
                        id="ledger-reasons-chart",
                        figure=empty_figure("No exits recorded yet"),
                        config=STATIC_CONFIG,
                        style={"height": "240px"},
                    ),
                ],
                icon="fa-diagram-successor",
                actions=html.Span(id="ledger-store-path", className="text-faint",
                                  style={"fontSize": "11px"}),
            ),
            panel(
                "Order History",
                html.Div(id="ledger-table", children=empty_state(
                    "fa-receipt", "No orders recorded yet",
                    "Entries and exits are appended here as they are submitted",
                )),
                icon="fa-list-check",
                flush=True,
                actions=html.Div(
                    [
                        html.Button(
                            [html.I(className="fas fa-rotate"), " Reconcile fills"],
                            id="ledger-reconcile-btn",
                            className="seg-btn",
                            n_clicks=0,
                            title="Ask the broker what became of orders with no terminal status",
                        ),
                    ],
                    className="panel-action-group",
                ),
            ),
            panel(
                "Recorded Runs",
                html.Div(id="ledger-runs", children=empty_state(
                    "fa-folder-open", "No run logs found",
                    "Every completed analysis is written under eval_results/",
                )),
                icon="fa-folder-tree",
                flush=True,
            ),
            dcc.Interval(id="ledger-interval", interval=20000, n_intervals=0),
        ]
    )
