"""
webui/components/reports_panel.py - Enhanced reports panel with symbol-based pagination
"""

import dash_bootstrap_components as dbc
from dash import dcc, html
from webui.components.app_shell import panel
from webui.components.prompt_modal import create_prompt_modal
from webui.components.tool_outputs_modal import create_tool_outputs_modal


def create_symbol_pagination(pagination_id, max_symbols=1):
    """Symbol pager. Filled by the report callbacks; the id is load-bearing."""
    return html.Div(
        id=f"{pagination_id}-container",
        children=html.Div(
            "No symbols available",
            className="text-faint",
            style={"padding": "8px", "fontSize": "12px"},
        ),
        className="symbol-pagination-container",
    )


def create_reports_panel():
    """Create the reports panel for the web UI with emoji tabs and enhanced styling"""
    
    # Enhanced tab structure with emojis - each tab contains a content container that callbacks will update
    tabs = dbc.Tabs(
        [
            dbc.Tab(
                html.Div(
                    id="market-analysis-tab-content",
                    children=[
                        dcc.Markdown(
                            "📊 **Loading Market Analysis...** \n\nTechnical indicators and swing trading signals will appear here.",
                            mathjax=True,
                            highlight_config={"theme": "dark"},
                            dangerously_allow_html=False,
                            className='enhanced-markdown-content'
                        )
                    ]
                ),
                label="📊 Market Analysis", 
                tab_id="market-analysis",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="social-sentiment-tab-content",
                    children=[
                        dcc.Markdown(
                            "📱 **Loading Social Sentiment...** \n\nSocial media sentiment and community analysis will appear here.",
                            mathjax=True,
                            highlight_config={"theme": "dark"},
                            dangerously_allow_html=False,
                            className='enhanced-markdown-content'
                        )
                    ]
                ),
                label="📱 Social Sentiment", 
                tab_id="social-sentiment",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="news-analysis-tab-content",
                    children=[
                        dcc.Markdown(
                            "📰 **Loading News Analysis...** \n\nMarket news and catalyst analysis will appear here.",
                            mathjax=True,
                            highlight_config={"theme": "dark"},
                            dangerously_allow_html=False,
                            className='enhanced-markdown-content'
                        )
                    ]
                ),
                label="📰 News Analysis", 
                tab_id="news-analysis",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="fundamentals-analysis-tab-content",
                    children=[
                        dcc.Markdown(
                            "📈 **Loading Fundamentals Analysis...** \n\nFundamental metrics and earnings analysis will appear here.",
                            mathjax=True,
                            highlight_config={"theme": "dark"},
                            dangerously_allow_html=False,
                            className='enhanced-markdown-content'
                        )
                    ]
                ),
                label="📈 Fundamentals", 
                tab_id="fundamentals-analysis",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="macro-analysis-tab-content",
                    children=[
                        dcc.Markdown(
                            "🌍 **Loading Macro Analysis...** \n\nMacroeconomic indicators and market outlook will appear here.",
                            mathjax=True,
                            highlight_config={"theme": "dark"},
                            dangerously_allow_html=False,
                            className='enhanced-markdown-content'
                        )
                    ]
                ),
                label="🌍 Macro Analysis", 
                tab_id="macro-analysis",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="researcher-debate-tab-content",
                    children=[
                        html.P("🔍 Loading Researcher Debate...", className="loading-message"),
                        html.P("Bull vs Bear analysis will appear here.", className="loading-description")
                    ],
                    className="debate-content-wrapper"
                ),
                label="🔍 Researcher Debate", 
                tab_id="researcher-debate",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="research-manager-tab-content",
                    children=[
                        dcc.Markdown(
                            "🎯 **Loading Research Manager Decision...** \n\nManagement synthesis and recommendations will appear here.",
                            mathjax=True,
                            highlight_config={"theme": "dark"},
                            dangerously_allow_html=False,
                            className='enhanced-markdown-content'
                        )
                    ]
                ),
                label="🎯 Research Manager", 
                tab_id="research-manager",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="trader-plan-tab-content",
                    children=[
                        dcc.Markdown(
                            "🧠 **Loading Trader Plan...** \n\nResearch plan and proposed execution details will appear here.",
                            mathjax=True,
                            highlight_config={"theme": "dark"},
                            dangerously_allow_html=False,
                            className='enhanced-markdown-content'
                        )
                    ]
                ),
                label="🧠 Trader Plan", 
                tab_id="trader-plan",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="options-strategy-tab-content",
                    children=[
                        dcc.Markdown(
                            "📐 **Loading Options Strategy...** \n\nThe selected options structure, the live-quote risk gate verdict, and any veto reasons will appear here.",
                            mathjax=True,
                            highlight_config={"theme": "dark"},
                            dangerously_allow_html=False,
                            className='enhanced-markdown-content'
                        )
                    ]
                ),
                label="📐 Options",
                tab_id="options-strategy",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="risk-debate-tab-content",
                    children=[
                        html.P("⚖️ Loading Risk Debate...", className="loading-message"),
                        html.P("Risk management discussion will appear here.", className="loading-description")
                    ],
                    className="debate-content-wrapper"
                ),
                label="⚖️ Risk Debate", 
                tab_id="risk-debate",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
            dbc.Tab(
                html.Div(
                    id="final-decision-tab-content",
                    children=[
                        dcc.Markdown(
                            "⚡ **Loading Final Decision...** \n\nFinal decision, risk review, and audit details will appear here.",
                            mathjax=True,
                            highlight_config={"theme": "dark"},
                            dangerously_allow_html=False,
                            className='enhanced-markdown-content'
                        )
                    ]
                ),
                label="⚡ Final Decision", 
                tab_id="final-decision",
                label_style={"color": "#94A3B8", "font-weight": "600"},
                active_label_style={"color": "#FFFFFF", "font-weight": "700"}
            ),
        ],
        id="tabs",
        active_tab="market-analysis",
        className="enhanced-tabs",
    )

    # Hidden content containers for backward compatibility with existing callbacks
    hidden_content_containers = html.Div([
        html.Div(id="market-analysis-tab", style={"display": "none"}),
        html.Div(id="social-sentiment-tab", style={"display": "none"}),
        html.Div(id="news-analysis-tab", style={"display": "none"}),
        html.Div(id="fundamentals-analysis-tab", style={"display": "none"}),
        html.Div(id="macro-analysis-tab", style={"display": "none"}),
        html.Div(id="researcher-debate-tab", style={"display": "none"}),
        html.Div(id="research-manager-tab", style={"display": "none"}),
        html.Div(id="trader-plan-tab", style={"display": "none"}),
        html.Div(id="options-strategy-tab", style={"display": "none"}),
        html.Div(id="risk-debate-tab", style={"display": "none"}),
        html.Div(id="final-decision-tab", style={"display": "none"})
    ])

    body = [
        html.Div(
            [
                html.Div(create_symbol_pagination("report-pagination"),
                         className="chart-toolbar-symbols"),
                html.Div(
                    html.Span(id="current-symbol-report-display", className="symbol-display"),
                    className="chart-toolbar-actions",
                ),
            ],
            className="chart-toolbar",
        ),
        tabs,
        hidden_content_containers,
        create_prompt_modal(),
        create_tool_outputs_modal(),
        # Modal state lives outside the modals so it survives their re-render.
        html.Div(
            [
                dcc.Store(id="global-prompt-modal-state", data={
                    "is_open": False, "report_type": None, "title": "Agent Prompt",
                }),
                dcc.Store(id="global-tool-outputs-modal-state", data={
                    "is_open": False, "report_type": None, "title": "Tool Outputs",
                }),
            ],
            style={"display": "none"},
        ),
        # The control callbacks drive the real dbc pagination; the visible
        # symbol buttons above are a skin over it, so it stays mounted.
        html.Div(
            dbc.Pagination(
                id="report-pagination",
                max_value=1,
                fully_expanded=True,
                first_last=True,
                previous_next=True,
                className="d-none",
            ),
            style={"display": "none"},
        ),
    ]

    return panel("Agent Reports & Audit Trail", body, icon="fa-file-lines",
                 panel_id="reports-panel")
