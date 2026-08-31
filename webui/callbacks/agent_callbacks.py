"""Callbacks for the Agents page: live agent state, and prompt read/write.

Saving writes the template the graph actually loads, so an edit here changes
the next run. That is the point of the page -- retuning behaviour without
touching code -- and it is also why the save path validates the name through
the loader's own checks rather than joining paths by hand.
"""

from dash import ALL, Input, Output, State, ctx, html, no_update

from tradingagents.prompts import PromptTemplateError, load_prompt, save_prompt
from webui.components.agents import AGENT_PROMPTS, AGENT_ROLES, ALL_AGENTS
from webui.utils.state import app_state

# Graph status -> (dot modifier, label). Anything unrecognised reads as idle
# rather than inventing a state the run never reported.
_STATE_STYLES = {
    "pending": ("agent-dot", "idle"),
    "in_progress": ("agent-dot is-running", "running"),
    "running": ("agent-dot is-running", "running"),
    "completed": ("agent-dot is-done", "done"),
    "error": ("agent-dot is-error", "error"),
}


def _live_statuses():
    """Agent -> status for the symbol on screen, or the only one running."""
    symbol = app_state.current_symbol or app_state.analyzing_symbol
    states = app_state.symbol_states or {}
    if symbol and symbol in states:
        return states[symbol].get("agent_statuses") or {}
    if len(states) == 1:
        return next(iter(states.values())).get("agent_statuses") or {}
    return {}


def register_agent_callbacks(app):
    """Register the Agents page callbacks."""

    @app.callback(
        [Output({"type": "agent-dot", "agent": ALL}, "className"),
         Output({"type": "agent-state", "agent": ALL}, "children"),
         Output({"type": "agent-state", "agent": ALL}, "className")],
        [Input("agents-interval", "n_intervals")],
    )
    def refresh_agent_states(_n):
        statuses = _live_statuses()
        dots, labels, label_classes = [], [], []
        for name, _icon, _role, _prompts in ALL_AGENTS:
            raw = str(statuses.get(name, "pending")).lower()
            dot_class, label = _STATE_STYLES.get(raw, _STATE_STYLES["pending"])
            dots.append(dot_class)
            labels.append(label)
            label_classes.append("agent-card-state is-" + label)
        return dots, labels, label_classes

    @app.callback(
        [Output("agent-selected", "data"),
         Output("agent-editor-name", "children"),
         Output("agent-editor-role", "children"),
         Output("agent-prompt-select", "options"),
         Output("agent-prompt-select", "value"),
         Output({"type": "agent-card", "agent": ALL}, "className")],
        [Input({"type": "agent-card", "agent": ALL}, "n_clicks")],
        [State("agent-selected", "data")],
    )
    def select_agent(_clicks, current):
        triggered = ctx.triggered_id
        selected = triggered.get("agent") if isinstance(triggered, dict) else current
        names = [a[0] for a in ALL_AGENTS]
        classes = [
            "agent-card is-selected" if name == selected else "agent-card"
            for name in names
        ]
        if not selected:
            return None, "No agent selected", (
                "Pick an agent on the left to load the prompt it runs on."
            ), [], None, classes

        prompts = AGENT_PROMPTS.get(selected, [])
        options = [{"label": p.split("/")[-1].replace("_", " "), "value": p} for p in prompts]
        return (
            selected,
            selected,
            AGENT_ROLES.get(selected, ""),
            options,
            prompts[0] if prompts else None,
            classes,
        )

    @app.callback(
        [Output("agent-prompt-text", "value"),
         Output("agent-prompt-save", "disabled"),
         Output("agent-prompt-status", "children"),
         Output("agent-prompt-status", "className")],
        [Input("agent-prompt-select", "value")],
    )
    def load_selected_prompt(name):
        if not name:
            return "", True, "", "agent-prompt-status"
        try:
            return load_prompt(name), False, name + ".md", "agent-prompt-status"
        except PromptTemplateError as exc:
            return "", True, str(exc), "agent-prompt-status is-error"

    @app.callback(
        [Output("agent-prompt-status", "children", allow_duplicate=True),
         Output("agent-prompt-status", "className", allow_duplicate=True)],
        [Input("agent-prompt-save", "n_clicks")],
        [State("agent-prompt-select", "value"), State("agent-prompt-text", "value")],
        prevent_initial_call=True,
    )
    def save_selected_prompt(n_clicks, name, content):
        if not n_clicks or not name:
            return no_update, no_update
        if not (content or "").strip():
            return "Nothing to save: the prompt is empty.", "agent-prompt-status is-error"
        try:
            path = save_prompt(name, content)
        except PromptTemplateError as exc:
            return str(exc), "agent-prompt-status is-error"
        except OSError as exc:
            return "Could not write the template: " + str(exc), "agent-prompt-status is-error"
        return "Saved to " + path.name + " — the next run uses it.", "agent-prompt-status is-ok"
