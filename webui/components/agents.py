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
    """One row in the roster rail.

    This was a card in a two-across grid, which spent half the page on
    descriptions and left the prompt editor -- the thing the page exists for --
    squeezed into the other half. As a list row the whole roster fits in a
    narrow rail beside a full-width editor, which is the shape this page
    actually is: pick one of fourteen, then edit it.

    The element keeps its ``agent-card`` id and class so the selection
    callback's className round-trip is unchanged.
    """
    count = len(prompts)
    return html.Button(
        [
            html.Span(html.I(className="fa-solid " + icon), className="agent-row-icon"),
            html.Span(
                [
                    html.Span(name, className="agent-row-name"),
                    html.Span(role, className="agent-row-role", title=role),
                ],
                className="agent-row-text",
            ),
            html.Span(
                [
                    html.Span(
                        str(count),
                        className="agent-row-count",
                        title=f"{count} prompt template{'s' if count != 1 else ''}",
                    ),
                    html.Span(className="agent-dot", id={"type": "agent-dot", "agent": name}),
                    # The word form of the state is kept for screen readers and
                    # for the callback that writes it; the dot carries it
                    # visually in a rail this narrow.
                    html.Span(
                        "idle",
                        className="agent-card-state",
                        id={"type": "agent-state", "agent": name},
                    ),
                ],
                className="agent-row-meta",
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
                    html.Span(title, className="agent-team-title"),
                    html.Span(str(len(agents)), className="agent-team-count"),
                ],
                className="agent-team-head",
                title=blurb,
            ),
            html.Div([_agent_card(*agent) for agent in agents], className="agent-list"),
        ],
        className="agent-team",
    )


def _editor():
    return html.Div(
        [
            html.Div(
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
                    html.Div(
                        dbc.Select(
                            id="agent-prompt-select",
                            options=[],
                            value=None,
                            className="config-select agent-prompt-select",
                        ),
                        className="agent-editor-picker",
                    ),
                ],
                className="agent-editor-bar",
            ),
            dcc.Textarea(
                id="agent-prompt-text",
                className="agent-prompt-text",
                value="",
                spellCheck=False,
                placeholder="Select an agent, then a template, to load the prompt it runs on.",
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
    """Master-detail: the roster rail on the left, the prompt editor beside it."""
    return [
        page_header(
            "Agents",
            "The fourteen agents in the graph, their live state, and the prompt each one runs on",
        ),
        html.Div(
            [
                html.Div(
                    panel(
                        "Pipeline",
                        html.Div(
                            [_team_block(*team) for team in AGENT_TEAMS],
                            className="agent-teams",
                        ),
                        icon="fa-diagram-project",
                        actions=html.Span("14 agents", className="agent-hint"),
                    ),
                    className="agent-rail",
                ),
                html.Div(
                    panel(
                        "Prompt Editor",
                        _editor(),
                        icon="fa-pen-to-square",
                        actions=html.Span(
                            "Saving retunes the next run",
                            className="agent-hint",
                        ),
                    ),
                    className="agent-detail",
                ),
            ],
            className="agent-workspace",
        ),
        # Seeded with the first agent so the editor opens on a real prompt
        # rather than an empty pane; the selection callback falls back to this
        # value whenever no card was the trigger.
        dcc.Store(id="agent-selected", data=ALL_AGENTS[0][0]),
        dcc.Interval(id="agents-interval", interval=2000, n_intervals=0),
    ]
