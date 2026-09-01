"""
Cost callbacks for TradingAgents WebUI
Scans the persisted run logs, aggregates LLM spend per day/symbol/model,
joins each symbol's realized returns, and shows the daily token budget
state from the safety layer.
"""

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, html

from webui.utils.charts import ACCENT, apply_chart_theme, empty_figure


def _fmt_usd(value):
    return "—" if value is None else f"${value:,.2f}"


def _fmt_tokens(value):
    return f"{int(value or 0):,}"


def _summary_card(label, text, tone="neutral"):
    """One cost figure, wearing the same KPI tile the rest of the app uses."""
    value_class = "kpi-value sm"
    if tone in ("pos", "neg"):
        value_class += f" text-{tone}"
    return html.Div(
        [
            html.Div(label, className="kpi-label"),
            html.Div(text, className=value_class),
        ],
        className=f"kpi {tone}",
    )


def _budget_text():
    """Daily token usage vs the safety layer's budget, if configured."""
    try:
        from tradingagents.safety import get_safety_guard

        guard = get_safety_guard()
        used = guard.llm_tokens_used()
        budget = float(guard.config.get("daily_llm_token_budget", 0) or 0)
        if budget > 0:
            return f"{used:,} / {budget:,.0f}", ("neg" if used >= budget else "pos")
        return f"{used:,} / ∞", "neutral"
    except Exception:
        return "—", "neutral"


def _build_daily_figure(per_day):
    """One series, one colour: the bar length already carries the magnitude."""
    days = sorted(per_day)
    # A local or self-hosted model has no configured price, so every bar is
    # zero and the chart renders as an empty grid. Say why instead.
    if not any(per_day[d]["cost_usd"] for d in days):
        return empty_figure(
            "No priced spend recorded",
            "These runs used models with no configured price — see unpriced tokens above",
        )
    figure = go.Figure(
        go.Bar(
            x=days,
            y=[per_day[d]["cost_usd"] for d in days],
            marker=dict(color=ACCENT, line=dict(width=0)),
            hovertemplate="%{x}<br><b>$%{y:,.2f}</b> estimated<extra></extra>",
        )
    )
    figure.update_layout(
        margin={"l": 58, "r": 18, "t": 16, "b": 32},
        yaxis={"title": "USD", "tickformat": ",.2f", "tickprefix": "$", "rangemode": "tozero"},
        showlegend=False,
        bargap=0.4,
        height=260,
    )
    apply_chart_theme(figure)
    figure.update_layout(margin={"l": 58, "r": 18, "t": 16, "b": 32})
    return figure


def _build_symbol_table(per_symbol, returns_by_symbol):
    if not per_symbol:
        return None
    header = html.Thead(
        html.Tr(
            [
                html.Th("Symbol"),
                html.Th("Runs", className="num"),
                html.Th("Tokens", className="num"),
                html.Th("Est. cost", className="num"),
                html.Th("Resolved decisions", className="num"),
                html.Th("Avg realized return", className="num"),
            ]
        )
    )
    rows = []
    for symbol in sorted(per_symbol, key=lambda s: -per_symbol[s]["cost_usd"]):
        stats = per_symbol[symbol]
        outcome = returns_by_symbol.get(symbol) or {}
        avg = outcome.get("avg_return")
        avg_text = "—" if avg is None else f"{avg:+.2%}"
        avg_class = "num" if avg is None else (
            "num text-pos" if avg > 0 else "num text-neg")
        rows.append(
            html.Tr(
                [
                    html.Td(symbol, className="sym"),
                    html.Td(stats["runs"], className="num"),
                    html.Td(_fmt_tokens(stats["total_tokens"]), className="num"),
                    html.Td(_fmt_usd(stats["cost_usd"]), className="num"),
                    html.Td(outcome.get("resolved", 0), className="num"),
                    html.Td(avg_text, className=avg_class),
                ]
            )
        )
    return html.Div(
        [
            html.Div("Per symbol — cost vs realized outcome", className="subhead"),
            html.Table([header, html.Tbody(rows)], className="data-table"),
        ]
    )


def _build_model_table(per_model):
    if not per_model:
        return None
    header = html.Thead(
        html.Tr(
            [
                html.Th("Model"),
                html.Th("Input tokens", className="num"),
                html.Th("Output tokens", className="num"),
                html.Th("Est. cost", className="num"),
            ]
        )
    )
    rows = []
    for model in sorted(per_model, key=lambda m: -per_model[m]["cost_usd"]):
        stats = per_model[model]
        cost_text = _fmt_usd(stats["cost_usd"]) + (" (partly unpriced)" if stats.get("unpriced") else "")
        rows.append(
            html.Tr(
                [
                    html.Td(model, className="sym"),
                    html.Td(_fmt_tokens(stats["input_tokens"]), className="num"),
                    html.Td(_fmt_tokens(stats["output_tokens"]), className="num"),
                    html.Td(cost_text, className="num"),
                ]
            )
        )
    return html.Div(
        [
            html.Div("Per model", className="subhead"),
            html.Table([header, html.Tbody(rows)], className="data-table"),
        ]
    )


def register_cost_callbacks(app):
    """Register cost-panel callbacks with the Dash app"""

    @app.callback(
        [
            Output("cost-summary-cards", "children"),
            Output("cost-daily-graph", "figure"),
            Output("cost-graph-container", "style"),
            Output("cost-symbol-table", "children"),
            Output("cost-model-table", "children"),
        ],
        Input("cost-refresh-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def refresh_cost_panel(n_clicks):
        hidden = {"display": "none"}
        empty = empty_figure("No recorded LLM spend yet",
                             "Run an analysis, then refresh to attribute its cost")
        try:
            from tradingagents.dataflows.config import get_config
            from tradingagents.llm_cost import (
                aggregate_costs,
                realized_returns_by_symbol,
                scan_run_costs,
            )

            config = {}
            try:
                config = dict(get_config() or {})
            except Exception:
                config = {}
            records = scan_run_costs(
                eval_results_dir=config.get("results_dir", "eval_results"),
                overrides=config.get("llm_pricing_per_million"),
            )
            aggregates = aggregate_costs(records)
            returns_by_symbol = realized_returns_by_symbol(config)
        except Exception as e:
            alert = dbc.Alert(f"Cost scan failed: {e}", color="danger", className="mb-0")
            return alert, empty, hidden, None, None

        totals = aggregates["totals"]
        if not totals["runs"]:
            alert = dbc.Alert(
                "No recorded runs found under eval_results/ yet.",
                color="info",
                className="mb-0",
            )
            return alert, empty, hidden, None, None

        budget_text, budget_tone = _budget_text()
        cards = html.Div(
            [
                _summary_card("Analyses", f"{totals['runs']:,}"),
                _summary_card("Total tokens", _fmt_tokens(totals["total_tokens"])),
                _summary_card("Est. cost", _fmt_usd(totals["cost_usd"])),
                _summary_card("Unpriced tokens", _fmt_tokens(totals["unpriced_tokens"])),
                _summary_card("Today's tokens / budget", budget_text, budget_tone),
            ],
            className="kpi-grid tight",
        )
        figure = _build_daily_figure(aggregates["per_day"])
        symbol_table = _build_symbol_table(aggregates["per_symbol"], returns_by_symbol)
        model_table = _build_model_table(aggregates["per_model"])
        return cards, figure, {"display": "block"}, symbol_table, model_table
