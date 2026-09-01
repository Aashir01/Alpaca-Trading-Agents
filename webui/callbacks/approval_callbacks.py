"""Human-in-the-loop approval for trades the agents have decided on.

When execution_mode is not "autonomous" the run stages its decision instead of
sending it, and nothing reaches the broker until someone presses Approve here.
Approving pops the staged trade before executing, so a double click cannot
submit the same decision twice.
"""

import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx, html, no_update

from webui.utils.state import app_state


def _empty(message, hint):
    return html.Div(
        [
            html.I(className="fa-solid fa-inbox fa-lg mb-2", style={"opacity": "0.4"}),
            html.Div(message, className="fw-semibold"),
            html.Div(hint, className="text-dim small"),
        ],
        className="text-center p-4",
    )


def _card(trade):
    symbol = trade.get("symbol", "?")
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(symbol, className="pending-symbol"),
                            html.Span(trade.get("decision", "?"), className="pending-decision"),
                        ],
                        className="pending-head",
                    ),
                    html.Div(
                        f"staged {trade.get('staged_at', '')}"
                        + (f" · ${trade.get('trade_amount')}" if trade.get("trade_amount") else ""),
                        className="pending-meta",
                    ),
                ],
                className="pending-info",
            ),
            html.Div(
                [
                    dbc.Button(
                        [html.I(className="fa-solid fa-check me-2"), "Approve"],
                        id={"type": "approve-trade", "symbol": symbol},
                        color="success",
                        size="sm",
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="fa-solid fa-xmark me-2"), "Discard"],
                        id={"type": "reject-trade", "symbol": symbol},
                        color="secondary",
                        outline=True,
                        size="sm",
                        n_clicks=0,
                    ),
                ],
                className="pending-actions",
            ),
        ],
        className="pending-card",
    )


def register_approval_callbacks(app):
    """Register the approval queue callbacks."""

    @app.callback(
        Output("pending-trades-body", "children"),
        [Input("pending-trades-interval", "n_intervals")],
    )
    def render_pending(_n):
        pending = list((app_state.pending_trades or {}).values())
        if not pending:
            return _empty(
                "Nothing waiting",
                "Decisions appear here when a run finishes in human-in-the-loop mode.",
            )
        return html.Div(
            [html.Div(id="pending-result", className="pending-result")]
            + [_card(t) for t in pending],
            className="pending-list",
        )

    @app.callback(
        Output("pending-result", "children"),
        [Input({"type": "approve-trade", "symbol": ALL}, "n_clicks"),
         Input({"type": "reject-trade", "symbol": ALL}, "n_clicks")],
        prevent_initial_call=True,
    )
    def act_on_pending(_approve, _reject):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            return no_update
        # Dash fires this on render with n_clicks=0; only a real press counts.
        if not (ctx.triggered and (ctx.triggered[0] or {}).get("value")):
            return no_update

        symbol = triggered.get("symbol")
        trade = app_state.take_pending_trade(symbol)
        if not trade:
            return f"{symbol}: nothing left to act on — it was already handled."

        if triggered.get("type") == "reject-trade":
            return f"{symbol}: discarded. Nothing was sent to the broker."

        from tradingagents.dataflows.config import get_config
        from webui.components.analysis import (
            execute_options_plan_after_analysis,
            execute_trade_after_analysis,
        )

        cfg = get_config() or {}
        try:
            if not bool(cfg.get("options_only_execution", False)):
                execute_trade_after_analysis(
                    symbol, trade.get("allow_shorts", False), trade.get("trade_amount")
                )
            execute_options_plan_after_analysis(symbol, trade.get("decision"))
        except Exception as exc:  # noqa: BLE001 - shown to the operator
            return f"{symbol}: execution failed — {exc}"
        return f"{symbol}: approved and sent. Check Recent Orders below."
