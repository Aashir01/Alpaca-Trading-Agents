"""
webui/components/safety_panel.py - Production safety layer status panel

Shows a green/red badge for every deterministic guard (kill switch,
pre-trade checks, circuit breakers, LLM budget) plus a kill-switch toggle
that halts all order flow immediately, regardless of agent decisions.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from webui.components.app_shell import panel


def create_safety_panel():
    """Create the safety guardrails panel for the web UI."""
    # The kill switch is the one control on this page that stops live order
    # flow, so it stays in the panel head where it is always reachable rather
    # than scrolling away with the guard list.
    actions = html.Div(
        [
            dbc.Button(
                [html.I(className="fas fa-hand me-2"), "Engage Kill Switch"],
                id="safety-kill-switch-btn",
                color="danger",
                size="sm",
            ),
            dbc.Button(
                "Release",
                id="safety-release-btn",
                color="secondary",
                outline=True,
                size="sm",
            ),
        ],
        className="panel-action-group",
    )

    body = [
        html.Div(
            "Deterministic pre-trade checks, circuit breakers, and a kill switch — "
            "enforced before any order reaches the broker, independent of agent decisions.",
            className="panel-blurb",
        ),
        html.Div(id="safety-action-status", className="panel-notice"),
        html.Div(id="safety-status-container"),
        dcc.Interval(id="safety-refresh-interval", interval=30_000, n_intervals=0),
    ]

    return panel("Safety Guardrails", body, icon="fa-shield-halved", actions=actions)
