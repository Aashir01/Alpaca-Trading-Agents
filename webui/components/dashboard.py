"""Dashboard page: the at-a-glance view of account, exposure, and agents.

Layout only. Every number here is filled by ``dashboard_callbacks`` from live
Alpaca data plus in-process agent state, so nothing on this page is a
placeholder that quietly stays stale.
"""

from dash import dcc, html

from webui.components.app_shell import empty_state, kpi_tile, page_header, panel


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
                             tone="neutral", delta_id="kpi-equity-delta"),
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
            # --- Allocation + agent pipeline -------------------------------
            html.Div(
                [
                    html.Div(
                        panel(
                            "Portfolio Allocation",
                            dcc.Graph(
                                id="dash-allocation-chart",
                                config={"displayModeBar": False},
                                style={"height": "400px"},
                            ),
                            icon="fa-chart-pie",
                        ),
                        className="split-col",
                    ),
                    html.Div(
                        panel(
                            "Agent Pipeline",
                            html.Div(
                                id="dash-pipeline",
                                style={"maxHeight": "400px", "overflowY": "auto"},
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
