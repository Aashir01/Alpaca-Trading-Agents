"""
webui/components/status_panel.py - Live run status for the Analysis page.

Every component id here is targeted by ``status_callbacks``; only the framing
changed, from a Bootstrap card to the app's own panel and stat row.
"""

from dash import html

from webui.components.app_shell import panel


def _stat(label, value_id, icon):
    return html.Div(
        [
            html.Div(
                [html.I(className=f"fas {icon}"), label],
                className="stat-label",
            ),
            html.Div("0", id=value_id, className="stat-value"),
        ],
        className="stat",
    )


def create_status_panel():
    """Create the status panel for the web UI."""
    body = [
        html.Div(id="status-table"),
        html.Div(
            [
                _stat("Tool calls", "tool-calls-text", "fa-screwdriver-wrench"),
                _stat("LLM calls", "llm-calls-text", "fa-brain"),
                _stat("Reports", "reports-text", "fa-file-lines"),
            ],
            className="stat-row",
        ),
        html.Div(
            "⏸️ Updates paused until analysis starts",
            id="refresh-status",
            className="text-faint run-status-line",
        ),
    ]
    return panel("Analysis Status", body, icon="fa-signal")
