"""Dashboard page: the at-a-glance view of account, exposure, and agents.

Layout only. Every number and every chart here is filled by
``dashboard_callbacks`` from live Alpaca data plus in-process agent state, so
nothing on this page is a placeholder that quietly stays stale.

The reading order is the order a trader actually asks the questions in: how
much do I have (KPIs), how did it get there (equity curve), what is it in
(allocation and exposure), which of it is working (position P/L), what is the
desk doing about it (pipeline, decisions, orders).
"""

from dash import dcc, html

from webui.components.app_shell import (
    empty_state,
    kpi_tile,
    page_header,
    panel,
    segmented,
)
from webui.utils.charts import STATIC_CONFIG, empty_figure

EQUITY_RANGES = ["1D", "1W", "1M", "3M", "1Y"]


def create_dashboard_page():
    return html.Div(
        [
            page_header(
                "Dashboard",
                "Live account, exposure, and agent activity across the trading desk",
            ),
            # --- KPI row ---------------------------------------------------
            html.Div(
                [
                    kpi_tile("Portfolio Equity", "kpi-equity", icon="fa-sack-dollar",
                             tone="neutral", delta_id="kpi-equity-delta",
                             spark_id="kpi-equity-spark"),
                    kpi_tile("Day P/L", "kpi-daypl", icon="fa-arrow-trend-up",
                             tone="neutral", sub_id="kpi-daypl-sub"),
                    kpi_tile("Open P/L", "kpi-openpl", icon="fa-chart-line",
                             tone="neutral", sub_id="kpi-openpl-sub"),
                    kpi_tile("Buying Power", "kpi-bp", icon="fa-wallet",
                             tone="neutral", sub_id="kpi-bp-sub"),
                    kpi_tile("Gross Exposure", "kpi-exposure", icon="fa-scale-balanced",
                             tone="neutral", sub_id="kpi-exposure-sub"),
                    kpi_tile("Options Positions", "kpi-options", icon="fa-layer-group",
                             tone="opt", sub_id="kpi-options-sub"),
                ],
                className="kpi-grid",
            ),
            # --- Equity curve + allocation ---------------------------------
            html.Div(
                [
                    html.Div(
                        panel(
                            "Equity Curve",
                            [
                                html.Div(id="dash-equity-summary", className="chart-caption"),
                                dcc.Graph(
                                    id="dash-equity-chart",
                                    figure=empty_figure("Loading portfolio history…"),
                                    config=STATIC_CONFIG,
                                    className="graph-fill",
                                    style={"minHeight": "300px"},
                                ),
                            ],
                            icon="fa-chart-area",
                            actions=segmented(
                                "equity-range", EQUITY_RANGES, active="1M"
                            ),
                        ),
                        className="split-col grow-2",
                    ),
                    html.Div(
                        panel(
                            "Portfolio Allocation",
                            [
                                dcc.Graph(
                                    id="dash-allocation-chart",
                                    figure=empty_figure("Loading allocation…"),
                                    config=STATIC_CONFIG,
                                    style={"height": "290px"},
                                ),
                                html.Div("Book composition", className="chart-caption mt"),
                                dcc.Graph(
                                    id="dash-exposure-chart",
                                    figure=empty_figure("Loading exposure…"),
                                    config=STATIC_CONFIG,
                                    style={"height": "132px"},
                                ),
                            ],
                            icon="fa-chart-pie",
                        ),
                        className="split-col",
                    ),
                ],
                className="split-row",
            ),
            # --- Position P/L + agent pipeline ------------------------------
            html.Div(
                [
                    html.Div(
                        panel(
                            "Unrealized P/L by Position",
                            dcc.Graph(
                                id="dash-pl-chart",
                                figure=empty_figure("Loading positions…"),
                                config=STATIC_CONFIG,
                                style={"height": "340px"},
                            ),
                            icon="fa-ranking-star",
                            actions=html.Span(id="dash-pl-summary", className="text-faint",
                                              style={"fontSize": "11.5px"}),
                        ),
                        className="split-col",
                    ),
                    html.Div(
                        panel(
                            "Agent Pipeline",
                            html.Div(
                                id="dash-pipeline",
                                style={"maxHeight": "340px", "overflowY": "auto"},
                                children=empty_state(
                                    "fa-robot", "No run in progress",
                                    "Start an analysis to watch the agent team work",
                                ),
                            ),
                            icon="fa-diagram-project",
                            actions=html.Span(id="dash-pipeline-status"),
                        ),
                        className="split-col",
                    ),
                ],
                className="split-row",
            ),
            # --- Positions -------------------------------------------------
            panel(
                "Open Positions",
                html.Div(id="dash-positions", children=empty_state(
                    "fa-wallet", "No open positions",
                    "Positions opened by the agents will appear here",
                )),
                icon="fa-wallet",
                flush=True,
                actions=html.Span(id="dash-positions-count", className="text-faint",
                                  style={"fontSize": "11.5px"}),
            ),
            # --- Options overlay + recent decisions ------------------------
            html.Div(
                [
                    html.Div(
                        panel(
                            "Options Overlay",
                            html.Div(id="dash-options", children=empty_state(
                                "fa-layer-group", "Options overlay disabled",
                                "Set OPTIONS_TRADING_ENABLED=True to arm the desk",
                            )),
                            icon="fa-layer-group",
                        ),
                        className="split-col",
                    ),
                    html.Div(
                        panel(
                            "Latest Decisions",
                            html.Div(id="dash-decisions", children=empty_state(
                                "fa-gavel", "No decisions yet",
                                "Final risk-adjusted calls will be listed here",
                            )),
                            icon="fa-gavel",
                            flush=True,
                        ),
                        className="split-col",
                    ),
                ],
                className="split-row",
            ),
            # --- Decision history ------------------------------------------
            panel(
                "Decision History",
                [
                    html.Div(
                        "Completed runs per trading day, by final signal — read from "
                        "the persisted run logs, so it reflects what the desk actually decided.",
                        className="chart-caption",
                    ),
                    dcc.Graph(
                        id="dash-signal-chart",
                        figure=empty_figure("Loading decision history…"),
                        config=STATIC_CONFIG,
                        style={"height": "250px"},
                    ),
                ],
                icon="fa-clock-rotate-left",
                actions=html.Span(id="dash-signal-summary", className="text-faint",
                                  style={"fontSize": "11.5px"}),
            ),
            # --- Recent orders ---------------------------------------------
            panel(
                "Recent Orders",
                html.Div(id="dash-orders", children=empty_state(
                    "fa-receipt", "No recent orders",
                    "Orders submitted to Alpaca will appear here",
                )),
                icon="fa-receipt",
                flush=True,
            ),
        ]
    )
