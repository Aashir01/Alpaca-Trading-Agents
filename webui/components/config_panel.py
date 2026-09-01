"""Run configuration for the Analysis page.

Split into three panels rather than one tall accordion, because the three
groups are used on completely different cadences: **Run Setup** is touched on
every run and sits at the top with the start button in its header; **Execution**
and **Models** are set once and revisited rarely, so they live below the live
output instead of pushing it off screen.

Every component id here is targeted by ``control_callbacks`` and
``api_config_callbacks``; only the grouping and the framing changed.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from webui.components.app_shell import panel
from tradingagents.openai_model_registry import (
    PARAMETER_HELP,
    get_default_model_params,
    get_llm_provider_options,
    get_model_options_for_provider,
)


ANALYSTS = [
    ("analyst-market", "Market", "fa-chart-line"),
    ("analyst-social", "Social", "fa-comments"),
    ("analyst-news", "News", "fa-newspaper"),
    ("analyst-fundamentals", "Fundamentals", "fa-building-columns"),
    ("analyst-macro", "Macro", "fa-globe"),
]


def _field(label, control, icon=None, class_name=""):
    label_children = []
    if icon:
        label_children.append(html.I(className=f"fa-solid {icon} me-2"))
    label_children.append(label)

    return html.Div(
        [
            dbc.Label(label_children, className="config-label"),
            control,
        ],
        className=f"config-field {class_name}".strip(),
    )


def _help_label(label, tooltip_id, help_key):
    return html.Div(
        [
            dbc.Label(label, className="config-label mb-0"),
            html.Span("?", id=tooltip_id, className="llm-param-help", title=PARAMETER_HELP[help_key]),
            dbc.Tooltip(PARAMETER_HELP[help_key], target=tooltip_id, placement="top"),
        ],
        className="config-label-row",
    )


def _analyst_checkbox(component_id, label, icon):
    return html.Div(
        html.Label(
            [
                dbc.Checkbox(
                    id=component_id,
                    value=True,
                    className="analyst-checkbox",
                ),
                html.Span(
                    [
                        html.I(className=f"fa-solid {icon} me-2"),
                        html.Span(label),
                    ],
                    className="analyst-tile-label",
                ),
            ],
            className="analyst-tile-click-target",
        ),
        className="analyst-tile",
    )


def _switch_with_help(component_id, label, default_value, help_key):
    tooltip_id = f"{component_id}-help"
    return html.Div(
        [
            html.Div(
                [
                    dbc.Switch(
                        id=component_id,
                        label=label,
                        value=default_value,
                        className="config-switch",
                    ),
                    html.Span("?", id=tooltip_id, className="llm-param-help", title=PARAMETER_HELP[help_key]),
                    dbc.Tooltip(PARAMETER_HELP[help_key], target=tooltip_id, placement="top"),
                ],
                className="config-switch-row",
            ),
        ]
    )


def _llm_param_controls(role, default_model):
    defaults = get_default_model_params(default_model, role)
    prefix = f"{role}-llm"
    return html.Div(
        [
            html.Div(
                [
                    _help_label("Reasoning effort", f"{prefix}-reasoning-help", "reasoning_effort"),
                    dbc.Select(
                        id=f"{prefix}-reasoning-effort",
                        value=defaults.get("reasoning_effort"),
                        className="config-select",
                    ),
                ],
                id=f"{prefix}-reasoning-effort-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Text verbosity", f"{prefix}-verbosity-help", "text_verbosity"),
                    dbc.Select(
                        id=f"{prefix}-verbosity",
                        value=defaults.get("text_verbosity"),
                        className="config-select",
                    ),
                ],
                id=f"{prefix}-verbosity-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Reasoning summary", f"{prefix}-summary-help", "reasoning_summary"),
                    dbc.Select(
                        id=f"{prefix}-summary",
                        value=defaults.get("reasoning_summary", "auto"),
                        className="config-select",
                    ),
                ],
                id=f"{prefix}-summary-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Temperature", f"{prefix}-temperature-help", "temperature"),
                    dbc.Input(
                        id=f"{prefix}-temperature",
                        type="number",
                        min=0,
                        max=2,
                        step=0.1,
                        value=defaults.get("temperature"),
                        className="config-input",
                    ),
                ],
                id=f"{prefix}-temperature-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Top P", f"{prefix}-top-p-help", "top_p"),
                    dbc.Input(
                        id=f"{prefix}-top-p",
                        type="number",
                        min=0,
                        max=1,
                        step=0.05,
                        value=defaults.get("top_p"),
                        className="config-input",
                    ),
                ],
                id=f"{prefix}-top-p-group",
                className="llm-param-field",
            ),
            html.Div(
                [
                    _help_label("Max output tokens", f"{prefix}-max-output-help", "max_output_tokens"),
                    dbc.Input(
                        id=f"{prefix}-max-output-tokens",
                        type="number",
                        min=64,
                        step=128,
                        placeholder="No cap",
                        value=defaults.get("max_output_tokens"),
                        className="config-input",
                    ),
                ],
                id=f"{prefix}-max-output-group",
                className="llm-param-field",
            ),
            html.Div(
                _switch_with_help(
                    f"{prefix}-store",
                    "Store responses",
                    defaults.get("store", False),
                    "store",
                ),
                id=f"{prefix}-store-group",
                className="llm-param-field llm-param-switch",
            ),
            html.Div(
                _switch_with_help(
                    f"{prefix}-parallel-tool-calls",
                    "Parallel tool calls",
                    defaults.get("parallel_tool_calls", True),
                    "parallel_tool_calls",
                ),
                id=f"{prefix}-parallel-tool-calls-group",
                className="llm-param-field llm-param-switch",
            ),
        ],
        className="llm-param-controls",
    )


def _model_defaults(role):
    """Resolve the configured model into a (dropdown value, custom text) pair.

    DEFAULT_CONFIG reads DEEP_THINK_LLM / QUICK_THINK_LLM from .env. A model
    that is not in the OpenAI catalog (any open-weight id) has to be carried by
    the "custom" option, otherwise the layout falls back to a GPT-5 id that a
    non-OpenAI endpoint cannot serve.
    """
    fallback = "gpt-5.4-nano" if role == "quick" else "gpt-5.4-mini"
    configured = _configured(
        "quick_think_llm" if role == "quick" else "deep_think_llm", fallback
    )
    known = {option["value"] for option in get_model_options_for_provider("openai", role)}
    if configured in known:
        return configured, ""
    return "custom", configured


def _model_panel(role, title, icon, default_model):
    prefix = f"{role}-llm"
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className=f"fa-solid {icon} model-panel-icon"),
                            html.Div(
                                [
                                    html.H6(title, className="model-panel-title"),
                                    html.Small("Model and supported parameters", className="model-panel-meta"),
                                ]
                            ),
                        ],
                        className="model-panel-heading",
                    ),
                    dbc.Select(
                        id=prefix,
                        options=get_model_options_for_provider("openai", role),
                        value=_model_defaults(role)[0] or default_model,
                        className="config-select mt-3",
                    ),
                    html.Div(
                        _field(
                            "Custom model ID",
                            dbc.Input(
                                id=f"{prefix}-custom-model",
                                type="text",
                                placeholder="provider/model-name",
                                value=_model_defaults(role)[1],
                                className="config-input",
                            ),
                            "keyboard",
                        ),
                        id=f"{prefix}-custom-model-group",
                        className="model-custom-field",
                        style={"display": "none"},
                    ),
                    html.Div(id=f"{prefix}-info", className="llm-model-info"),
                    dbc.Accordion(
                        [
                            dbc.AccordionItem(
                                _llm_param_controls(role, default_model),
                                title="Advanced parameters",
                                item_id=f"{role}-params",
                            )
                        ],
                        id=f"{prefix}-params-accordion",
                        start_collapsed=True,
                        flush=True,
                        className="config-subaccordion mt-3",
                    ),
                ]
            )
        ],
        className="model-panel",
    )


def _run_button():
    return dbc.Button(
        [html.I(className="fa-solid fa-play me-2"), "Start Analysis"],
        id="control-btn",
        color="primary",
        size="lg",
        className="w-100 config-primary-action",
    )


def _core_setup():
    """Symbols, analysts, and the two run-shape choices.

    Laid out as three stacked bands rather than a single column of fields: the
    symbol picker wants the full width, the analyst tiles read as one row, and
    the remaining choices are short enough to sit side by side.
    """
    return html.Div(
        [
            _field(
                "Symbols",
                html.Div(
                    [
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.Div(id="symbol-selected-chips", className="symbol-chip-list"),
                                        dcc.Input(
                                            id="symbol-query-input",
                                            type="text",
                                            value="",
                                            debounce=False,
                                            placeholder="Type a symbol...",
                                            className="symbol-query-input",
                                        ),
                                    ],
                                    className="symbol-combobox",
                                ),
                                html.Div(id="symbol-suggestions", className="symbol-suggestions-menu"),
                            ],
                            className="symbol-combobox-wrap",
                        ),
                        dcc.Input(
                            id="ticker-input",
                            type="hidden",
                            value="NVDA, AMD, TSLA",
                        ),
                        html.Div(id="symbol-search-status", className="symbol-search-status"),
                    ],
                    className="symbol-picker",
                ),
                "tag",
            ),
            _field(
                "Analyst team",
                html.Div(
                    [_analyst_checkbox(component_id, label, icon)
                     for component_id, label, icon in ANALYSTS],
                    className="analyst-grid",
                ),
                "users",
            ),
            html.Div(
                [
                    _field(
                        "Trading horizon",
                        dbc.RadioItems(
                            id="trading-horizon",
                            options=[
                                {"label": "Swing", "value": "swing"},
                                {"label": "Day", "value": "day"},
                                {"label": "Scalp", "value": "scalp"},
                            ],
                            value=_configured("trading_horizon", "swing"),
                            inline=True,
                            className="segmented-radio",
                        ),
                        "stopwatch",
                    ),
                    _field(
                        "Research depth",
                        dbc.RadioItems(
                            id="research-depth",
                            options=[
                                {"label": "Shallow", "value": "Shallow"},
                                {"label": "Medium", "value": "Medium"},
                                {"label": "Deep", "value": "Deep"},
                            ],
                            value="Shallow",
                            inline=True,
                            className="segmented-radio",
                        ),
                        "layer-group",
                    ),
                    _field(
                        "Direction",
                        html.Div(
                            dbc.Switch(
                                id="allow-shorts",
                                label="Allow shorts",
                                value=False,
                                className="config-switch",
                            ),
                            className="config-toggle-tile",
                        ),
                        "arrows-up-down",
                    ),
                ],
                className="config-three-column",
            ),
            html.Div(
                [
                    html.Div(id="research-depth-info", className="config-status-slot"),
                    html.Div(id="trading-mode-info", className="config-status-slot"),
                ],
                className="config-note-row split",
            ),
        ],
        className="config-section-body",
    )


def _schedule_and_trading():
    """Two groups with their own subheads: when it runs, and what it sends.

    They used to be one undifferentiated stack of two-column rows, which read
    as a settings dump. Naming the groups is what makes the panel scannable --
    scheduling and order flow are separate decisions with separate risk.
    """
    return html.Div(
        [
            html.Div("Schedule", className="subhead first"),
            html.Div(
                [
                    _field(
                        "Loop mode",
                        html.Div(
                            dbc.Switch(
                                id="loop-enabled",
                                label="Repeat on an interval",
                                value=False,
                                className="config-switch",
                            ),
                            className="config-toggle-tile",
                        ),
                        "repeat",
                    ),
                    _field(
                        "Loop interval (min)",
                        dbc.Input(
                            id="loop-interval",
                            type="number",
                            placeholder="60",
                            value=60,
                            min=1,
                            max=1440,
                            className="config-input",
                        ),
                        "clock",
                    ),
                    _field(
                        "Market hours",
                        html.Div(
                            dbc.Switch(
                                id="market-hour-enabled",
                                label="Run at market hour",
                                value=False,
                                className="config-switch",
                            ),
                            className="config-toggle-tile",
                        ),
                        "bell",
                    ),
                    _field(
                        "Hours of the day",
                        dbc.Input(
                            id="market-hours-input",
                            type="text",
                            placeholder="11,13",
                            value="",
                            className="config-input",
                        ),
                        "calendar-days",
                    ),
                ],
                className="config-four-column",
            ),
            html.Div(
                [
                    html.Div(id="market-hours-validation", className="config-validation-slot"),
                    html.Div(id="scheduling-mode-info", className="config-status-slot"),
                ],
                className="config-note-row",
            ),
            html.Div("Order flow", className="subhead"),
            html.Div(
                [
                    _field(
                        "Who approves the trade",
                        dbc.RadioItems(
                            id="execution-mode",
                            options=[
                                {"label": "Human in the loop", "value": "approval"},
                                {"label": "Autonomous", "value": "autonomous"},
                            ],
                            value=_configured("execution_mode", "approval"),
                            inline=True,
                            className="segmented-radio",
                        ),
                        "user-shield",
                    ),
                    _field(
                        "After analysis",
                        html.Div(
                            dbc.Switch(
                                id="trade-after-analyze",
                                label="Place the order",
                                value=False,
                                className="config-switch",
                            ),
                            className="config-toggle-tile",
                        ),
                        "paper-plane",
                    ),
                    _field(
                        "Order amount",
                        dbc.InputGroup(
                            [
                                dbc.InputGroupText("$"),
                                dbc.Input(
                                    id="trade-dollar-amount",
                                    type="number",
                                    placeholder="4500",
                                    value=4500,
                                    min=1,
                                    max=10000000,
                                    className="config-input",
                                ),
                            ],
                            className="config-input-group",
                        ),
                        "sack-dollar",
                    ),
                ],
                className="config-three-column",
            ),
            html.Div(
                [
                    html.Div(id="execution-mode-info", className="config-status-slot"),
                    html.Div(id="trade-after-analyze-info", className="config-status-slot"),
                ],
                className="config-note-row split",
            ),
        ],
        className="config-section-body",
    )


def _configured(key, fallback):
    """Read a default from DEFAULT_CONFIG, which is populated from .env."""
    try:
        from tradingagents.default_config import DEFAULT_CONFIG

        return DEFAULT_CONFIG.get(key) or fallback
    except Exception:
        return fallback


def _model_setup():
    """Provider settings on one row, then the two model roles side by side."""
    return html.Div(
        [
            html.Div("Provider", className="subhead first"),
            html.Div(
                [
                    _field(
                        "LLM provider",
                        dbc.Select(
                            id="llm-provider",
                            options=get_llm_provider_options(),
                            # Default to the provider configured in .env so the
                            # UI opens on a combination that can actually run.
                            value=_configured("llm_provider", "openai"),
                            className="config-select",
                        ),
                        "network-wired",
                    ),
                    html.Div(
                        _field(
                            "Endpoint override",
                            dbc.Input(
                                id="backend-url",
                                type="text",
                                placeholder="Optional OpenAI-compatible endpoint",
                                value=_configured("backend_url", ""),
                                className="config-input",
                            ),
                            "server",
                        ),
                        id="backend-url-group",
                    ),
                    _field(
                        "Output language",
                        dbc.Input(
                            id="output-language",
                            type="text",
                            value="English",
                            className="config-input",
                        ),
                        "language",
                    ),
                    _field(
                        "Checkpoints",
                        html.Div(
                            dbc.Switch(
                                id="checkpoint-enabled",
                                label="Resume from checkpoint",
                                value=False,
                                className="config-switch",
                            ),
                            className="config-toggle-tile",
                        ),
                        "floppy-disk",
                    ),
                ],
                className="config-four-column",
            ),
            # Provider-specific knobs; each group is unhidden by its own
            # callback when that provider is selected.
            html.Div(
                [
                    html.Div(
                        _field(
                            "Gemini thinking",
                            dbc.Select(
                                id="google-thinking-level",
                                options=[
                                    {"label": "Provider default", "value": ""},
                                    {"label": "High thinking", "value": "high"},
                                    {"label": "Minimal / disabled", "value": "minimal"},
                                ],
                                value="",
                                className="config-select",
                            ),
                            "lightbulb",
                        ),
                        id="google-thinking-level-group",
                        style={"display": "none"},
                    ),
                    html.Div(
                        _field(
                            "Claude effort",
                            dbc.Select(
                                id="anthropic-effort",
                                options=[
                                    {"label": "Provider default", "value": ""},
                                    {"label": "High", "value": "high"},
                                    {"label": "Medium", "value": "medium"},
                                    {"label": "Low", "value": "low"},
                                ],
                                value="",
                                className="config-select",
                            ),
                            "gauge-high",
                        ),
                        id="anthropic-effort-group",
                        style={"display": "none"},
                    ),
                ],
                className="config-two-column provider-options-grid",
            ),
            html.Div(id="llm-provider-info", className="config-status-slot"),
            html.Div("Model roles", className="subhead"),
            html.Div(
                [
                    _model_panel("quick", "Quick thinker", "bolt", "gpt-5.4-nano"),
                    _model_panel("deep", "Deep thinker", "brain", "gpt-5.4-mini"),
                ],
                className="model-grid",
            ),
        ],
        className="config-section-body",
    )


def create_run_setup_panel():
    """The controls touched on every run, with the start button in the header.

    The button used to float in a sticky bar that overlapped whatever section
    was scrolled behind it. Anchoring it to the panel head keeps it reachable
    without covering anything.
    """
    return panel(
        "Run Setup",
        [
            _core_setup(),
            html.Div(id="result-text", className="result-status"),
        ],
        icon="fa-sliders",
        actions=html.Div(
            html.Div(id="control-button-container", children=[_run_button()]),
            className="run-action",
        ),
        panel_id="run-setup-panel",
    )


def create_execution_panel():
    """Scheduling and order controls: set once, revisited rarely."""
    return panel(
        "Execution & Schedule",
        [
            html.Div(
                "When the desk runs, who approves the trade, and what it is "
                "allowed to send to the broker.",
                className="panel-blurb",
            ),
            _schedule_and_trading(),
        ],
        icon="fa-calendar-check",
    )


def create_models_panel():
    """Provider, endpoint, and the two model roles."""
    return panel(
        "Models",
        [
            html.Div(
                "The provider and the two model roles the graph runs on. "
                "Quick thinker handles the analysts; deep thinker handles the "
                "debates and the final call.",
                className="panel-blurb",
            ),
            _model_setup(),
        ],
        icon="fa-microchip",
    )


def create_config_panel():
    """All three configuration panels, in the order the page shows them."""
    return [create_run_setup_panel(), create_execution_panel(), create_models_panel()]
