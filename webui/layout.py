"""Layout for the TradingAgents WebUI.

Assembles the application shell (sidebar + top bar) around a set of page
containers. Pages are hidden rather than unmounted, so every component ID the
existing callbacks depend on stays in the DOM on every page.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc

from webui.components.alpaca_account import render_alpaca_account_section
from webui.components.api_config_modal import create_api_config_modal, create_config_button
from webui.components.app_shell import (
    create_sidebar,
    create_topbar,
    page_container,
    page_header,
    panel,
)
from webui.components.backtest_panel import create_backtest_panel
from webui.components.chart_panel import create_chart_panel
from webui.components.config_panel import create_config_panel
from webui.components.cost_panel import create_cost_panel
from webui.components.dashboard import create_dashboard_page
from webui.components.decision_panel import create_decision_panel
from webui.components.options_desk import create_options_page
from webui.components.reports_panel import create_reports_panel
from webui.components.safety_panel import create_safety_panel
from webui.components.status_panel import create_status_panel
from webui.config.constants import REFRESH_INTERVALS


def create_intervals():
    """Auto-refresh intervals, kept at their original ids and cadences."""
    return [
        # Fast refresh for critical updates during analysis
        dcc.Interval(
            id="refresh-interval",
            interval=REFRESH_INTERVALS["fast"],
            n_intervals=0,
            disabled=True,  # Start disabled, only enable when analysis is running
        ),
        # Medium refresh for reports and non-critical updates
        dcc.Interval(
            id="medium-refresh-interval",
            interval=REFRESH_INTERVALS["medium"],
            n_intervals=0,
            disabled=True,
        ),
        # Slow refresh for account data
        dcc.Interval(
            id="slow-refresh-interval",
            interval=REFRESH_INTERVALS["slow"],
            n_intervals=0,
            disabled=False,  # Always enabled for account data
        ),
        # Dashboard/topbar refresh: account context stays current on every page.
        dcc.Interval(id="dashboard-interval", interval=15000, n_intervals=0, disabled=False),
    ]


def create_stores():
    """Client-side stores for state management."""
    from webui.utils.storage import (
        create_api_keys_store_component,
        create_storage_store_component,
    )

    return [
        dcc.Store(id="app-store"),
        dcc.Store(id="chart-store", data={"last_symbol": None, "selected_period": "1y"}),
        dcc.Store(id="active-page-store", data="dashboard"),
        create_storage_store_component(),
        create_api_keys_store_component(),
    ]


# The prompt modal is opened from inside rendered report HTML, which can only
# talk to Dash by clicking a real button. This bridges that message to the
# matching hidden button.
_PROMPT_BRIDGE_JS = """
window.addEventListener('message', function(event) {
    if (!event.data || event.data.type !== 'showPrompt') { return; }
    const reportType = event.data.reportType;
    const buttons = document.querySelectorAll('[id*="show-prompt-"]');
    for (const button of buttons) {
        const id = button.getAttribute('id');
        if (id && id.includes(reportType)) { button.click(); return; }
    }
    console.log('No prompt button found for:', reportType);
});
"""


def _analysis_page():
    # The shell's own grid classes are used instead of the Bootstrap grid:
    # Bootstrap is loaded from a CDN, and the layout should not collapse when
    # that CDN is slow, blocked, or unavailable offline.
    return [
        page_header("Run Analysis", "Configure the agent team and launch a run"),
        html.Div(
            [
                html.Div(create_config_panel(), className="split-col stack"),
                html.Div(
                    [create_chart_panel(), create_status_panel(), create_decision_panel()],
                    className="split-col stack",
                ),
            ],
            className="split-row",
        ),
    ]


def _agents_page():
    from webui.components.agents import create_agents_page

    return create_agents_page()


def _reports_page():
    return [
        page_header("Agent Reports", "Full audit trail for every agent in the pipeline"),
        create_reports_panel(),
    ]


def _positions_page():
    return [
        page_header("Positions & Orders", "Live Alpaca positions, orders, and account detail"),
        panel(
            "Awaiting approval",
            html.Div(id="pending-trades-body"),
            icon="fa-user-shield",
            actions=html.Span(
                "Shown when the run is set to human-in-the-loop",
                className="agent-hint",
            ),
        ),
        dcc.Interval(id="pending-trades-interval", interval=2000, n_intervals=0),
        dbc.Card(dbc.CardBody([render_alpaca_account_section()])),
    ]


def _backtest_page():
    return [
        page_header("Backtest", "Replay strategies over historical data"),
        create_backtest_panel(),
    ]


def _settings_page():
    # The API-key button lives here, not in the top bar: the dashboard's empty
    # states point a first-run user to Settings, so this is where they expect
    # to land. It also keeps `open-api-config-btn` mounted exactly once.
    return [
        page_header("Settings", "Safety guardrails, API keys, and cost tracking"),
        panel(
            "API Credentials",
            html.Div(
                [
                    html.P(
                        "Alpaca, LLM provider, and market-data keys. Keys are stored in "
                        "your browser and written to the running session only.",
                        className="text-dim",
                        style={"fontSize": "13px", "marginBottom": "13px"},
                    ),
                    create_config_button(),
                ]
            ),
            icon="fa-key",
        ),
        create_safety_panel(),
        create_cost_panel(),
    ]


def create_main_layout():
    """Build the full application layout."""
    pages = html.Div(
        [
            page_container("dashboard", create_dashboard_page(), visible=True),
            page_container("analysis", _analysis_page()),
            page_container("agents", _agents_page()),
            page_container("reports", _reports_page()),
            page_container("options", create_options_page()),
            page_container("positions", _positions_page()),
            page_container("backtest", _backtest_page()),
            page_container("settings", _settings_page()),
        ],
        className="app-content",
    )

    return html.Div(
        [
            *create_intervals(),
            *create_stores(),
            create_api_config_modal(),
            html.Script(_PROMPT_BRIDGE_JS),
            create_sidebar(),
            html.Div([create_topbar(), pages], className="app-main"),
        ],
        className="app-shell",
    )
