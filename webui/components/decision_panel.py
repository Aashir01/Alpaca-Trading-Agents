"""
webui/components/decision_panel.py - Final decision summary for the Analysis page.

``decision-summary`` is filled by ``report_callbacks``; the surrounding frame is
the app's panel rather than a Bootstrap card, so it matches the rest of the desk.
"""

from dash import dcc, html

from webui.components.app_shell import panel


def create_decision_panel():
    """Create the decision summary panel for the web UI."""
    body = html.Div(
        dcc.Markdown(
            id="decision-summary",
            children="Run analysis to see the final decision summary",
            className="dash-markdown",
        ),
        className="decision-scroll",
    )
    return panel("Decision Summary", body, icon="fa-gavel")
