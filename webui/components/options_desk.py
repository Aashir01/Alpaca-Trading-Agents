"""Options Desk page.

Surfaces the part of the system a judge most wants to interrogate: what the
model proposed, what the deterministic gate recomputed from live quotes, and
what actually reached the broker. The gate's numbers are shown next to the
model's own estimate so the separation between the two is visible, not claimed.
"""

from dash import dcc, html

from webui.components.app_shell import empty_state, kpi_tile, page_header, panel
from webui.utils.charts import STATIC_CONFIG, empty_figure


def create_options_page():
    return html.Div(
        [
            page_header(
                "Options Desk",
                "Defined-risk options overlay: proposals, risk-gate verdicts, and live exposure",
            ),
            html.Div(
                [
                    kpi_tile("Overlay Status", "opt-kpi-status", icon="fa-power-off",
                             tone="neutral", sub_id="opt-kpi-status-sub"),
                    kpi_tile("Max Loss / Trade", "opt-kpi-maxloss", icon="fa-shield-halved",
                             tone="neutral", sub_id="opt-kpi-maxloss-sub"),
                    kpi_tile("Open Contracts", "opt-kpi-contracts", icon="fa-layer-group",
                             tone="opt", sub_id="opt-kpi-contracts-sub"),
                    kpi_tile("Options P/L", "opt-kpi-pl", icon="fa-chart-line",
                             tone="neutral", sub_id="opt-kpi-pl-sub"),
                ],
                className="kpi-grid",
            ),
            html.Div(
                [
                    html.Div(
                        panel(
                            "Current Proposal",
                            html.Div(
                                dcc.Markdown(
                                    id="opt-proposal",
                                    children=(
                                        "No options proposal yet.\n\n"
                                        "The Options Strategist runs between the Trader and the "
                                        "risk debate on every analysis when the overlay is enabled."
                                    ),
                                    className="dash-markdown",
                                ),
                                style={"maxHeight": "440px", "overflowY": "auto"},
                            ),
                            icon="fa-lightbulb",
                            actions=html.Span(id="opt-proposal-symbol", className="text-faint",
                                              style={"fontSize": "11.5px"}),
                        ),
                        className="split-col",
                    ),
                    html.Div(
                        [
                            panel(
                                "Risk Gate Verdict",
                                html.Div(id="opt-gate", children=empty_state(
                                    "fa-shield-halved", "No verdict yet",
                                    "Every leg is re-priced from live bid/ask before approval",
                                )),
                                icon="fa-shield-halved",
                            ),
                            panel(
                                "Active Gate Rules",
                                html.Div(id="opt-rules"),
                                icon="fa-list-check",
                            ),
                        ],
                        className="split-col stack",
                    ),
                ],
                className="split-row",
            ),
            # The payoff curve is the proposal made checkable: it is drawn from
            # the legs and the *gate's* recomputed net premium, so the shape on
            # screen is the risk the deterministic gate actually priced, not
            # the model's own claim about it.
            panel(
                "Payoff at Expiry",
                [
                    html.Div(
                        "Profit and loss across underlying price, computed from the "
                        "proposed legs and the risk gate's re-priced net premium.",
                        className="chart-caption",
                    ),
                    dcc.Graph(
                        id="opt-payoff-chart",
                        figure=empty_figure("No approved structure yet"),
                        config=STATIC_CONFIG,
                        style={"height": "320px"},
                    ),
                ],
                icon="fa-chart-area",
                actions=html.Span(id="opt-payoff-summary", className="text-faint",
                                  style={"fontSize": "11.5px"}),
            ),
            panel(
                "Open Options Positions",
                html.Div(id="opt-positions", children=empty_state(
                    "fa-layer-group", "No open options positions",
                    "Approved multi-leg orders will appear here once filled",
                )),
                icon="fa-layer-group",
                flush=True,
            ),
            panel(
                "Expiry Runway",
                [
                    html.Div(
                        "Days to expiry per open contract — theta is the clock every "
                        "defined-risk structure runs against.",
                        className="chart-caption",
                    ),
                    dcc.Graph(
                        id="opt-dte-chart",
                        figure=empty_figure("No open option contracts"),
                        config=STATIC_CONFIG,
                        style={"height": "220px"},
                    ),
                ],
                icon="fa-hourglass-half",
            ),
            panel(
                "Implied Volatility History",
                html.Div(id="opt-iv-history"),
                icon="fa-wave-square",
                actions=html.Span(
                    "IV rank needs history to mean anything",
                    className="text-faint",
                    style={"fontSize": "11.5px"},
                ),
            ),
        ]
    )
