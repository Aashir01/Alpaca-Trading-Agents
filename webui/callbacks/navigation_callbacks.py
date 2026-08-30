"""Sidebar navigation and page routing.

Routing toggles `display` on page containers instead of swapping children.
Unmounting would strip component IDs that ~300 existing callbacks target, and
Dash treats those as missing outputs; hiding keeps the whole tree alive.
"""

from dash import ALL, Input, Output, State, callback_context, html

from webui.components.app_shell import NAV_ITEMS, PAGE_META

PAGE_IDS = [item[0] for item in NAV_ITEMS]


def register_navigation_callbacks(app):
    @app.callback(
        [Output(f"page-{page_id}", "style") for page_id in PAGE_IDS]
        + [
            Output({"type": "nav-link", "page": ALL}, "className"),
            Output("topbar-title", "children"),
            Output("active-page-store", "data"),
        ],
        [Input({"type": "nav-link", "page": ALL}, "n_clicks")],
        [State("active-page-store", "data")],
    )
    def switch_page(_clicks, current):
        active = current or "dashboard"

        triggered = callback_context.triggered_id
        if isinstance(triggered, dict) and triggered.get("type") == "nav-link":
            active = triggered.get("page", active)
        if active not in PAGE_IDS:
            active = "dashboard"

        styles = [
            {"display": "block"} if page_id == active else {"display": "none"}
            for page_id in PAGE_IDS
        ]
        classes = [
            "nav-item-btn active" if page_id == active else "nav-item-btn"
            for page_id in PAGE_IDS
        ]
        title = PAGE_META.get(active, (active.title(), ""))[0]
        return (*styles, classes, title, active)

    @app.callback(
        Output("nav-badge-analysis", "children"),
        Output("nav-badge-analysis", "className"),
        Output("sidebar-status", "children"),
        [Input("dashboard-interval", "n_intervals"),
         Input("refresh-interval", "n_intervals")],
    )
    def update_run_badge(_a, _b):
        """Show how many symbols are mid-run, on every page."""
        from webui.utils.state import app_state

        running, complete = 0, 0
        for state in (app_state.symbol_states or {}).values():
            if state.get("analysis_running"):
                running += 1
            elif state.get("analysis_complete"):
                complete += 1

        if running:
            status = html.Div(
                [html.Span(className="dot dot-pulse"), html.Span(f"{running} running")],
                className="pill pill-warn",
            )
            return str(running), "nav-badge live", status

        if complete:
            status = html.Div(
                [html.Span(className="dot"), html.Span(f"{complete} complete")],
                className="pill pill-open",
            )
            return "", "nav-badge", status

        idle = html.Div(
            [html.Span(className="dot"), html.Span("Idle")], className="pill pill-closed"
        )
        return "", "nav-badge", idle
