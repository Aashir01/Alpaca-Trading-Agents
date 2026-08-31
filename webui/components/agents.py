"""The Agents page: who is in the pipeline, what each one does, and the prompt
it runs on.

The roster below is the real graph order, and every ``prompts`` entry names
templates that exist on disk. The editor loads and saves those files directly,
so a change made here retunes the next run rather than describing it.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from webui.components.app_shell import page_header, panel

# (display name, icon, one-line role, prompt templates in the order they fire)
AGENT_TEAMS = [
    (
        "Analyst Team",
        "fa-magnifying-glass-chart",
        "Five analysts work the same bar in parallel, each with its own tools.",
        [
            ("Market Analyst", "fa-chart-line",
             "Trend, momentum and levels from live Alpaca bars and indicators.",
             ["analysts/market_system", "analysts/market_intro_with_brief",
              "analysts/market_final_recommendation"]),
            ("Social Analyst", "fa-comments",
             "Sustained sentiment shifts, filtered for multi-day signal.",
             ["analysts/social_system", "analysts/social_final_recommendation"]),
            ("News Analyst", "fa-newspaper",
             "Headlines with multi-day impact; intraday noise is discarded.",
             ["analysts/news_system", "analysts/news_final_recommendation"]),
            ("Fundamentals Analyst", "fa-building-columns",
             "Earnings, guidance and insider activity via Finnhub.",
             ["analysts/fundamentals_system", "analysts/fundamentals_final_recommendation"]),
            ("Macro Analyst", "fa-globe",
             "Rates and macro releases from FRED, scoped to the holding period.",
             ["analysts/macro_system", "analysts/macro_final_recommendation",
              "analysts/macro_general_fallback"]),
        ],
    ),
    (
        "Research Team",
        "fa-scale-balanced",
        "A bull and a bear argue the evidence; a manager adjudicates.",
        [
            ("Bull Researcher", "fa-arrow-trend-up",
             "Builds the long case and rebuts the bear directly.",
             ["researchers/bull_researcher"]),
            ("Bear Researcher", "fa-arrow-trend-down",
             "Builds the short case and rebuts the bull directly.",
             ["researchers/bear_researcher"]),
            ("Research Manager", "fa-gavel",
             "Picks the better-supported side on evidence quality, not volume.",
             ["managers/research_manager"]),
        ],
    ),
    (
        "Trading Team",
        "fa-briefcase",
        "Turns the research verdict into a sized, executable plan.",
        [
            ("Trader", "fa-user-tie",
             "Writes entry, invalidation and target as a concrete plan. "
             "TRADING_HORIZON swaps its persona: swing by default, or the "
             "intraday day-trader and scalper prompts below.",
             ["trader/trader_system", "trader/day_trader", "trader/scalper",
              "trader/trader_user_plan", "trader/trader_final_decision",
              "trader/trader_context"]),
            ("Options Strategist", "fa-layer-group",
             "Expresses the view as a defined-risk options structure.",
             ["trader/options_strategy"]),
        ],
    ),
    (
        "Risk Management",
        "fa-shield-halved",
        "Three stances stress the plan, then a judge sizes it or stands aside.",
        [
            ("Risky Analyst", "fa-fire",
             "Argues the aggressive case and attacks excess caution.",
             ["risk/aggressive_debator", "risk/aggressive_context"]),
            ("Safe Analyst", "fa-life-ring",
             "Argues capital preservation and challenges the risky case.",
             ["risk/conservative_debator", "risk/conservative_context"]),
            ("Neutral Analyst", "fa-scale-unbalanced",
             "Weighs both sides and tests the plan against the middle case.",
             ["risk/neutral_debator", "risk/neutral_context"]),
            ("Portfolio Manager", "fa-clipboard-check",
             "The final judge: sizes the position or argues for standing aside.",
             ["managers/risk_manager"]),
        ],
    ),
]

ALL_AGENTS = [agent for _, _, _, agents in AGENT_TEAMS for agent in agents]
AGENT_PROMPTS = {name: prompts for name, _, _, prompts in ALL_AGENTS}
AGENT_ROLES = {name: role for name, _, role, _ in ALL_AGENTS}


def _agent_card(name, icon, role, prompts):
    count = len(prompts)
    return html.Button(
        [
            html.Div(
                [
                    html.Span(html.I(className="fa-solid " + icon), className="agent-card-icon"),
                    html.Span(className="agent-dot", id={"type": "agent-dot", "agent": name}),
                ],
                className="agent-card-top",
            ),
            html.Div(name, className="agent-card-name"),
            html.Div(role, className="agent-card-role"),
            html.Div(
                [
                    html.Span(
                        str(count) + (" prompts" if count != 1 else " prompt"),
                        className="agent-card-meta",
                    ),
                    html.Span(
                        "idle",
                        className="agent-card-state",
                        id={"type": "agent-state", "agent": name},
                    ),
                ],
                className="agent-card-foot",
            ),
        ],
        id={"type": "agent-card", "agent": name},
        className="agent-card",
        n_clicks=0,
    )


def _team_block(title, icon, blurb, agents):
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="fa-solid " + icon + " agent-team-icon"),
                    html.Div(
                        [
                            html.H6(title, className="agent-team-title"),
                            html.Small(blurb, className="agent-team-blurb"),
                        ],
                        className="agent-team-text",
                    ),
                    html.Span(str(len(agents)), className="agent-team-count"),
                ],
                className="agent-team-head",
            ),
            html.Div([_agent_card(*agent) for agent in agents], className="agent-grid"),
        ],
        className="agent-team",
    )


def _editor():
    return html.Div(
        [
            html.Div(
                [
                    html.Div("No agent selected", id="agent-editor-name",
                             className="agent-editor-name"),
                    html.Div(
                        "Pick an agent on the left to load the prompt it runs on.",
                        id="agent-editor-role",
                        className="agent-editor-role",
                    ),
                ],
                className="agent-editor-head",
            ),
            dbc.Select(
                id="agent-prompt-select",
                options=[],
                value=None,
                className="config-select agent-prompt-select",
            ),
            dcc.Textarea(
                id="agent-prompt-text",
                className="agent-prompt-text",
                value="",
                spellCheck=False,
                placeholder="The selected prompt loads here.",
            ),
            html.Div(
                [
                    dbc.Button(
                        [html.I(className="fa-solid fa-floppy-disk me-2"), "Save prompt"],
                        id="agent-prompt-save",
                        color="primary",
                        className="agent-save-btn",
                        disabled=True,
                        n_clicks=0,
                    ),
                    html.Span(id="agent-prompt-status", className="agent-prompt-status"),
                ],
                className="agent-editor-foot",
            ),
        ],
        className="agent-editor",
    )


def create_agents_page():
    """Pipeline roster on the left, prompt editor on the right."""
    return [
        page_header(
            "Agents",
            "The fourteen agents in the graph, their live state, and the prompt each one runs on",
        ),
        html.Div(
            [
                html.Div(
                    [
                        panel(
                            "Pipeline",
                            html.Div(
                                [_team_block(*team) for team in AGENT_TEAMS],
                                className="agent-teams",
                            ),
                            icon="fa-diagram-project",
                            actions=html.Span(
                                "Click an agent to read or edit its prompt",
                                className="agent-hint",
                            ),
                        )
                    ],
                    className="split-col stack",
                ),
                html.Div([panel("Prompt", _editor(), icon="fa-pen-to-square")],
                         className="split-col stack"),
            ],
            className="split-row",
        ),
        dcc.Store(id="agent-selected", data=None),
        dcc.Interval(id="agents-interval", interval=2000, n_intervals=0),
    ]
