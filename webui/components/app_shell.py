"""Application shell: sidebar navigation, top bar, and page framing.

The shell replaces a single ~18,000px scroll with a navigable app. Pages are
*hidden*, never unmounted: every pre-existing callback targets component IDs
that must stay in the DOM, so switching pages toggles `display` rather than
rebuilding the tree. That keeps the entire existing callback surface working
untouched while giving the app real navigation.
"""

from dash import dcc, html

# (page id, icon, label, badge id or None)
NAV_ITEMS = [
    ("dashboard", "fa-chart-pie", "Dashboard", None),
    ("analysis", "fa-robot", "Run Analysis", "nav-badge-analysis"),
    ("agents", "fa-people-group", "Agents", None),
    ("reports", "fa-file-lines", "Agent Reports", None),
    ("options", "fa-layer-group", "Options Desk", "nav-badge-options"),
    ("positions", "fa-wallet", "Positions & Orders", None),
    ("backtest", "fa-flask", "Backtest", None),
    ("settings", "fa-sliders", "Settings", None),
]

PAGE_META = {
    "dashboard": ("Dashboard", "Live account, exposure, and agent activity"),
    "analysis": ("Run Analysis", "Configure the agent team and launch a run"),
    "agents": ("Agents", "The agent roster, live state, and editable prompts"),
    "reports": ("Agent Reports", "Full audit trail for every agent in the pipeline"),
    "options": ("Options Desk", "Defined-risk options overlay and risk-gate verdicts"),
    "positions": ("Positions & Orders", "Live Alpaca positions, orders, and account detail"),
    "backtest": ("Backtest", "Replay strategies over historical data"),
    "settings": ("Settings", "Safety guardrails, API keys, and cost tracking"),
}


def create_sidebar():
    """Left navigation rail."""
    nav_buttons = []
    for page_id, icon, label, badge_id in NAV_ITEMS:
        children = [html.I(className=f"fas {icon}"), html.Span(label)]
        if badge_id:
            children.append(html.Span("", id=badge_id, className="nav-badge"))
        nav_buttons.append(
            html.Button(
                children,
                id={"type": "nav-link", "page": page_id},
                className="nav-item-btn active" if page_id == "dashboard" else "nav-item-btn",
                n_clicks=0,
            )
        )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(html.I(className="fas fa-bolt"), className="sidebar-brand-mark"),
                    html.Div(
                        [
                            html.Div("AlpacaAgent", className="sidebar-brand-name"),
                            html.Div("Options Alpha", className="sidebar-brand-sub"),
                        ],
                        className="sidebar-brand-text",
                    ),
                ],
                className="sidebar-brand",
            ),
            html.Div("Workspace", className="sidebar-section"),
            html.Div(nav_buttons, className="sidebar-nav"),
            html.Div(
                html.Div(id="sidebar-status", children=_status_placeholder()),
                className="sidebar-footer",
            ),
        ],
        className="app-sidebar",
    )


def _status_placeholder():
    return html.Div(
        [html.Span(className="dot"), html.Span("Idle")],
        className="pill pill-closed",
    )


def create_topbar():
    """Sticky top bar carrying live account context on every page."""
    return html.Div(
        [
            html.Div(id="topbar-title", className="topbar-title", children="Dashboard"),
            html.Div(className="topbar-spacer"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Equity", className="topbar-metric-label"),
                            html.Div("—", id="topbar-equity", className="topbar-metric-value"),
                        ],
                        className="topbar-metric",
                    ),
                    html.Div(
                        [
                            html.Div("Day P/L", className="topbar-metric-label"),
                            html.Div("—", id="topbar-daypl", className="topbar-metric-value"),
                        ],
                        className="topbar-metric",
                    ),
                    html.Div(
                        [
                            html.Div("Buying Power", className="topbar-metric-label"),
                            html.Div("—", id="topbar-bp", className="topbar-metric-value"),
                        ],
                        className="topbar-metric optional",
                    ),
                    html.Div(id="topbar-market", children=_market_placeholder()),
                    html.Div(id="topbar-mode"),
                    html.Button(
                        html.I(className="fas fa-rotate"),
                        id="refresh-btn",
                        className="icon-btn",
                        title="Refresh status",
                        n_clicks=0,
                    ),
                ],
                className="topbar-metrics",
            ),
        ],
        className="app-topbar",
    )


def _market_placeholder():
    return html.Span(
        [html.Span(className="dot"), html.Span("Market")],
        className="pill pill-closed",
    )


def page_container(page_id, children, visible=False):
    """Wrap a page so the router can show or hide it without unmounting."""
    return html.Div(
        children,
        id=f"page-{page_id}",
        # The page id is also a class so page-scoped CSS can target one page
        # without leaking its rules to the others.
        className=f"page page-{page_id}",
        style={"display": "block" if visible else "none"},
    )


def page_header(title, subtitle):
    return html.Div(
        [html.H2(title, className="page-title"), html.P(subtitle, className="page-sub")],
        className="page-head",
    )


def panel(title, body, icon=None, actions=None, flush=False, panel_id=None):
    """Standard panel: uppercase header strip over a bordered body."""
    head_children = [
        html.H3(
            ([html.I(className=f"fas {icon}")] if icon else []) + [title],
            className="panel-title",
        )
    ]
    # An empty Dash component is falsy (len() == 0), so test against None:
    # placeholder spans that callbacks fill later must still be mounted.
    if actions is not None:
        head_children.append(html.Div(actions, className="panel-actions"))

    kwargs = {"className": "panel"}
    if panel_id:
        kwargs["id"] = panel_id
    return html.Div(
        [
            html.Div(head_children, className="panel-head"),
            html.Div(body, className="panel-body flush" if flush else "panel-body"),
        ],
        **kwargs,
    )


def kpi_tile(label, value_id, icon=None, tone="neutral", delta_id=None, sub_id=None,
             sub=None, spark_id=None):
    """A single KPI tile. Values are filled by callbacks, not at build time.

    ``spark_id`` adds a chrome-free trend line under the number. It is a
    shape, not a readable series -- the axis it would need lives in the full
    equity curve below, so the sparkline carries no hover and no labels.
    """
    children = [
        html.Div(
            ([html.I(className=f"fas {icon}")] if icon else []) + [label],
            className="kpi-label",
        ),
        html.Div("—", id=value_id, className="kpi-value"),
    ]
    if delta_id:
        children.append(html.Div("", id=delta_id, className="kpi-delta"))
    if sub_id:
        children.append(html.Div(sub or "", id=sub_id, className="kpi-sub"))
    elif sub:
        children.append(html.Div(sub, className="kpi-sub"))
    if spark_id:
        from webui.utils.charts import STATIC_CONFIG, create_sparkline

        children.append(
            dcc.Graph(
                id=spark_id,
                figure=create_sparkline([]),
                config=STATIC_CONFIG,
                className="kpi-spark",
                style={"height": "38px"},
            )
        )
    return html.Div(children, className=f"kpi {tone}", id=f"{value_id}-tile")


def segmented(group_id, options, active=None):
    """A segmented control: one row of mutually exclusive range buttons.

    Buttons carry pattern-matching ids so a single callback can serve the whole
    group, and the active option is tracked in a ``dcc.Store`` beside them —
    which is what the callback reads, so the selection survives the periodic
    refresh that also redraws the chart.
    """
    active = active or (options[0] if options else None)
    return html.Div(
        [
            dcc.Store(id=f"{group_id}-store", data=active),
            html.Div(
                [
                    html.Button(
                        option,
                        id={"type": group_id, "value": option},
                        className="seg-btn active" if option == active else "seg-btn",
                        n_clicks=0,
                    )
                    for option in options
                ],
                id=f"{group_id}-buttons",
                className="segmented",
            ),
        ]
    )


def empty_state(icon, title, hint):
    return html.Div(
        [
            html.I(className=f"fas {icon}"),
            html.Div(title, className="empty-title"),
            html.Div(hint, className="empty-hint"),
        ],
        className="empty",
    )
