"""
Backtest callbacks for TradingAgents WebUI
Runs the walk-forward backtest over recorded agent decisions and renders
metrics, the equity curve, and per-window robustness results.
"""

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, State, html

from webui.utils.charts import (
    BG,
    BORDER,
    NEG,
    POS,
    TEXT_FAINT,
    apply_chart_theme,
    empty_figure,
)


def _fmt_pct(value):
    return "—" if value is None else f"{value:+.2%}"


def _fmt_ratio(value):
    return "—" if value is None else f"{value:.2f}"


def _metric_tone(value, invert=False):
    """Polarity class for a metric, or neutral when it could not be computed."""
    if value is None:
        return "neutral"
    good = value < 0 if invert else value > 0
    return "pos" if good else "neg"


def _metric_card(label, text, tone="neutral"):
    """One backtest metric, wearing the same KPI tile the rest of the app uses."""
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


def _build_metric_cards(metrics, signals_used):
    sharpe = metrics.get("sharpe_ratio")
    drawdown = metrics.get("max_drawdown")
    return html.Div(
        [
            _metric_card(
                "Cumulative Return",
                _fmt_pct(metrics.get("cumulative_return")),
                _metric_tone(metrics.get("cumulative_return")),
            ),
            _metric_card(
                "Annualized Return",
                _fmt_pct(metrics.get("annualized_return")),
                _metric_tone(metrics.get("annualized_return")),
            ),
            _metric_card("Sharpe Ratio", _fmt_ratio(sharpe), _metric_tone(sharpe)),
            _metric_card(
                "Max Drawdown",
                "—" if drawdown is None else f"-{drawdown:.2%}",
                _metric_tone(drawdown, invert=True) if drawdown else "neutral",
            ),
            _metric_card(
                "Win Rate",
                "—" if metrics.get("win_rate") is None else f"{metrics['win_rate']:.0%}",
            ),
            _metric_card(
                "Trades / Signals",
                f"{metrics.get('num_trades', 0)} / {signals_used}",
            ),
        ],
        className="kpi-grid tight",
    )


def _build_equity_figure(equity_curve, symbol):
    """Backtested equity, drawn the same way the live curve is.

    The line takes the polarity colour of the period's net result and the
    starting capital is marked, so a replay that lost money cannot be mistaken
    for one that made money at a glance.
    """
    values = [float(v) for v in equity_curve.values]
    if len(values) < 2:
        return empty_figure("Not enough data to plot", f"No replayable price history for {symbol}")

    colour = POS if values[-1] >= values[0] else NEG
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=list(equity_curve.index),
            y=values,
            mode="lines",
            name="Equity",
            line={"color": colour, "width": 2},
            fill="tozeroy",
            fillcolor=f"rgba({int(colour[1:3], 16)},{int(colour[3:5], 16)},{int(colour[5:7], 16)},0.10)",
            hovertemplate="%{x|%b %d, %Y}<br><b>$%{y:,.2f}</b><extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[list(equity_curve.index)[-1]],
            y=[values[-1]],
            mode="markers",
            marker=dict(color=colour, size=8, line=dict(color=BG, width=2)),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    figure.add_hline(
        y=values[0],
        line=dict(color=BORDER, width=1, dash="dot"),
        annotation_text=f"start ${values[0]:,.0f}",
        annotation_position="top left",
        annotation_font=dict(color=TEXT_FAINT, size=10.5),
    )
    low, high = min(values), max(values)
    pad = max((high - low) * 0.12, high * 0.0015, 1.0)
    figure.update_layout(
        margin={"l": 62, "r": 18, "t": 26, "b": 32},
        yaxis={"title": "Portfolio value", "tickformat": ",.0f", "tickprefix": "$",
               "range": [low - pad, high + pad]},
        showlegend=False,
        height=320,
    )
    apply_chart_theme(figure)
    figure.update_layout(margin={"l": 62, "r": 18, "t": 26, "b": 32})
    figure.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                        spikecolor=BORDER, spikethickness=1, spikedash="solid")
    figure.add_annotation(
        text=f"<b>Equity curve — {symbol}</b>",
        xref="paper", yref="paper", x=0, y=1.10, showarrow=False, xanchor="left",
        font=dict(color=TEXT_FAINT, size=11.5),
    )
    return figure


def _build_windows_table(windows):
    if len(windows) < 2:
        return None
    header = html.Thead(
        html.Tr(
            [
                html.Th("Window"),
                html.Th("Bars", className="num"),
                html.Th("Return", className="num"),
                html.Th("Sharpe", className="num"),
                html.Th("Max DD", className="num"),
                html.Th("Win Rate", className="num"),
            ]
        )
    )
    rows = []
    for window in windows:
        metrics = window["metrics"]
        cum = metrics.get("cumulative_return")
        rows.append(
            html.Tr(
                [
                    html.Td(f"{window['start_date']} → {window['end_date']}"),
                    html.Td(window["bars"], className="num"),
                    html.Td(
                        _fmt_pct(cum),
                        className=f"num text-{_metric_tone(cum)}" if cum is not None else "num",
                    ),
                    html.Td(_fmt_ratio(metrics.get("sharpe_ratio")), className="num"),
                    html.Td(
                        "—" if metrics.get("max_drawdown") is None else f"-{metrics['max_drawdown']:.2%}",
                        className="num",
                    ),
                    html.Td(
                        "—" if metrics.get("win_rate") is None else f"{metrics['win_rate']:.0%}",
                        className="num",
                    ),
                ]
            )
        )
    return html.Div(
        [
            html.Div("Out-of-sample windows", className="subhead"),
            html.Table([header, html.Tbody(rows)], className="data-table"),
        ]
    )


def register_backtest_callbacks(app):
    """Register backtest callbacks with the Dash app"""

    @app.callback(
        [
            Output("backtest-status", "children"),
            Output("backtest-metrics", "children"),
            Output("backtest-equity-graph", "figure"),
            Output("backtest-graph-container", "style"),
            Output("backtest-windows-table", "children"),
        ],
        Input("backtest-run-btn", "n_clicks"),
        [
            State("backtest-symbol-input", "value"),
            State("backtest-start-date", "value"),
            State("backtest-end-date", "value"),
            State("backtest-window-bars", "value"),
            State("backtest-allow-shorts", "value"),
            State("backtest-slippage-model", "value"),
        ],
        prevent_initial_call=True,
    )
    def run_backtest_callback(n_clicks, symbol, start_date, end_date, window_bars, allow_shorts, slippage_model):
        hidden = {"display": "none"}
        empty = empty_figure("No backtest run yet",
                             "Enter a symbol and press Run Backtest")

        symbol = (symbol or "").strip().upper()
        if not symbol:
            alert = dbc.Alert("Enter a symbol to backtest.", color="warning", className="mb-0")
            return alert, None, empty, hidden, None

        try:
            from tradingagents.backtest import run_recorded_walk_forward

            result = run_recorded_walk_forward(
                symbol,
                start_date=start_date or None,
                end_date=end_date or None,
                window_bars=int(window_bars or 63),
                allow_shorts=bool(allow_shorts),
                slippage_model=slippage_model or "fixed",
            )
        except ValueError as e:
            alert = dbc.Alert(str(e), color="warning", className="mb-0")
            return alert, None, empty, hidden, None
        except Exception as e:
            alert = dbc.Alert(f"Backtest failed: {e}", color="danger", className="mb-0")
            return alert, None, empty, hidden, None

        full = result.full_period
        slippage = full.slippage or {}
        slippage_text = {
            "fixed": f"slippage: {slippage.get('bps', 0):g} bps",
            "volatility": "slippage: volatility-scaled",
            "none": "slippage: none",
        }.get(slippage.get("model"), "slippage: n/a")
        status_bits = [
            f"{full.start_date} → {full.end_date}",
            f"{full.signals_used} recorded signal(s)",
            "execution: next-bar open",
            slippage_text,
        ]
        if full.rejected_orders:
            status_bits.append(f"{len(full.rejected_orders)} order(s) rejected on gaps")
        status = html.Div(" · ".join(status_bits), className="text-muted small")

        metrics_cards = _build_metric_cards(full.metrics, full.signals_used)
        figure = _build_equity_figure(full.equity_curve, symbol)
        windows_table = _build_windows_table(result.windows)
        return status, metrics_cards, figure, {"display": "block"}, windows_table

    @app.callback(
        Output("backtest-teach-status", "children"),
        Input("backtest-teach-btn", "n_clicks"),
        [
            State("backtest-symbol-input", "value"),
            State("backtest-start-date", "value"),
            State("backtest-end-date", "value"),
        ],
        prevent_initial_call=True,
    )
    def teach_memory_callback(n_clicks, symbol, start_date, end_date):
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return dbc.Alert(
                "Enter a symbol to teach from.", color="warning", className="mb-0"
            )

        try:
            from tradingagents.backtest import (
                default_agent_memories,
                teach_memories_from_history,
            )

            summary = teach_memories_from_history(
                symbol,
                default_agent_memories(),
                start_date=start_date or None,
                end_date=end_date or None,
            )
        except ValueError as e:
            return dbc.Alert(str(e), color="warning", className="mb-0")
        except Exception as e:
            return dbc.Alert(f"Teaching failed: {e}", color="danger", className="mb-0")

        taught = summary["decisions_taught"]
        if not taught and summary["decisions_skipped_duplicate"]:
            text = (
                f"Nothing new to teach for {symbol}: "
                f"{summary['decisions_skipped_duplicate']} decision(s) already in memory."
            )
            return dbc.Alert(text, color="info", className="mb-0")
        if not taught:
            text = (
                f"No teachable decisions for {symbol} "
                f"({summary['outcomes_computed']} outcome(s) computed, "
                f"{summary['decisions_skipped_no_state']} without a recorded final state; "
                "teaching also requires OpenAI embeddings)."
            )
            return dbc.Alert(text, color="warning", className="mb-0")

        text = (
            f"Taught {taught} decision(s) for {symbol} — "
            f"{summary['lessons_written']} lesson(s) written to the agent memories "
            f"({summary['decisions_skipped_duplicate']} duplicate(s) skipped, "
            f"{summary['decisions_skipped_no_state']} without final state)."
        )
        return dbc.Alert(text, color="success", className="mb-0")
