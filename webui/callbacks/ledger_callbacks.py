"""Trade Ledger page callbacks.

Reads the append-only ledger and the run logs from disk. Nothing here calls
the broker except the explicit Reconcile button, so the page stays responsive
whether or not Alpaca is reachable.
"""

import json
from pathlib import Path

from dash import Input, Output, html

from webui.components.app_shell import empty_state
from webui.utils.charts import NEG, POS, TEXT_FAINT, WARN, apply_chart_theme, empty_figure

# Exit reasons wear the meaning they carry: a stop is bad news, a target is
# good news, a time exit is neither.
_REASON_COLORS = {
    "stop loss": NEG,
    "profit target": POS,
    "time exit": WARN,
    "account breaker": NEG,
}


def _config():
    try:
        from tradingagents.dataflows.config import get_config

        return get_config() or {}
    except Exception:
        return {}


# A run log holds every prompt and tool response, so they run to hundreds of
# kilobytes each. Parsing all of them on a 20-second tick blocked the whole UI
# -- the page could not even be navigated to. Only the newest few are parsed,
# chosen by mtime so no file has to be opened to rank it, and the result is
# cached between ticks.
_RUNS_CACHE = {"at": 0.0, "rows": [], "key": None}
_RUNS_TTL_SECONDS = 30.0


def _run_logs(config, limit=40):
    """Recent run logs, newest first, parsed sparingly."""
    import time

    results_dir = Path(config.get("results_dir") or "eval_results")
    if not results_dir.is_dir():
        return []

    now = time.monotonic()
    cache_key = str(results_dir)
    if (
        _RUNS_CACHE["key"] == cache_key
        and now - _RUNS_CACHE["at"] < _RUNS_TTL_SECONDS
    ):
        return _RUNS_CACHE["rows"]

    paths = sorted(
        results_dir.glob("*/TradingAgentsStrategy_logs/runs/*.json"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )[:limit]

    rows = []
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        summary = payload.get("summary") or {}
        rows.append(
            {
                "symbol": payload.get("symbol", ""),
                "trade_date": payload.get("trade_date", ""),
                "started_at": payload.get("started_at", ""),
                "status": payload.get("status", ""),
                "signal": summary.get("final_signal") or "—",
                "tools": summary.get("tool_events", 0),
                "tokens": summary.get("total_llm_tokens", 0),
                "path": str(path),
            }
        )
    rows.sort(key=lambda r: r["started_at"], reverse=True)
    _RUNS_CACHE.update({"at": now, "rows": rows, "key": cache_key})
    return rows


def register_ledger_callbacks(app):
    @app.callback(
        [Output("ledger-kpi-entries", "children"),
         Output("ledger-kpi-entries-sub", "children"),
         Output("ledger-kpi-exits", "children"),
         Output("ledger-kpi-exits-sub", "children"),
         Output("ledger-kpi-symbols", "children"),
         Output("ledger-kpi-symbols-sub", "children"),
         Output("ledger-kpi-runs", "children"),
         Output("ledger-kpi-runs-sub", "children"),
         Output("ledger-store-path", "children"),
         Output("ledger-reasons-chart", "figure"),
         Output("ledger-table", "children"),
         Output("ledger-runs", "children")],
        [Input("ledger-interval", "n_intervals"),
         Input("ledger-reconcile-btn", "n_clicks")],
    )
    def refresh_ledger(_n, reconcile_clicks):
        from dash import ctx

        from tradingagents.ledger import load_orders, reconcile, summarize

        config = _config()

        # Only the button reaches the broker; the periodic refresh is disk-only.
        if ctx.triggered_id == "ledger-reconcile-btn" and reconcile_clicks:
            reconcile(config=config)

        summary = summarize(config)
        orders = load_orders(config)
        runs = _run_logs(config)

        reasons = summary["exit_reasons"]
        if reasons:
            labels = list(reasons)
            figure = _reasons_figure(labels, [reasons[k] for k in labels])
        else:
            figure = empty_figure(
                "No exits recorded yet",
                "Closes are appended here with the rule that caused them",
            )

        return (
            str(summary["entries"]),
            "%d filled" % summary["entries_filled"],
            str(summary["exits"]),
            "%d filled" % summary["exits_filled"],
            str(len(summary["symbols"])),
            ", ".join(summary["symbols"][:6]) or "None yet",
            str(len(runs)),
            "with full prompts and tool output",
            summary["path"],
            figure,
            _orders_table(orders),
            _runs_table(runs),
        )


def _reasons_figure(labels, counts):
    import plotly.graph_objects as go

    figure = go.Figure(
        go.Bar(
            x=counts,
            y=labels,
            orientation="h",
            marker=dict(
                color=[_REASON_COLORS.get(label, TEXT_FAINT) for label in labels],
                line=dict(width=0),
            ),
            text=[str(c) for c in counts],
            textposition="outside",
            cliponaxis=False,
            # Pinned, not proportional: with a single exit reason a bar sized
            # by bargap alone fills the whole plot and reads as a slab.
            width=[0.45] * len(labels),
            hovertemplate="<b>%{y}</b><br>%{x} exit(s)<extra></extra>",
        )
    )
    figure.update_layout(
        height=max(180, 44 * len(labels) + 70),
        showlegend=False,
        bargap=0.4,
        margin=dict(l=8, r=30, t=10, b=34),
    )
    figure.update_xaxes(title_text="Exits", rangemode="tozero", dtick=1)
    apply_chart_theme(figure)
    figure.update_layout(margin=dict(l=8, r=30, t=10, b=34), hovermode="closest")
    figure.update_yaxes(automargin=True)
    return figure


def _orders_table(orders):
    if not orders:
        return empty_state(
            "fa-receipt", "No orders recorded yet",
            "Entries and exits are appended here as they are submitted",
        )

    header = html.Thead(html.Tr([
        html.Th("When"), html.Th("Symbol"), html.Th("Kind"),
        html.Th("Structure / Reason"), html.Th("Premium", className="num"),
        html.Th("Fill"), html.Th("Order"),
    ]))

    rows = []
    for order in reversed(orders[-200:]):  # newest first, bounded
        is_entry = order["kind"] == "entry"
        kind_tag = "tag tag-long" if is_entry else "tag tag-sell"
        detail = order.get("strategy") if is_entry else order.get("reason", "")
        premium = order.get("net_credit_debit") if is_entry else order.get("premium")
        status = str(order.get("fill_status") or "pending").lower()
        status_class = (
            "text-pos" if status == "filled"
            else ("text-neg" if status in ("rejected", "canceled", "cancelled") else "text-dim")
        )
        order_id = str(order.get("order_id") or "—")
        rows.append(html.Tr([
            html.Td(str(order.get("recorded_at", ""))[:19].replace("T", " "),
                    className="pl-sub"),
            html.Td(order.get("symbol", ""), className="sym"),
            html.Td(html.Span("ENTRY" if is_entry else "EXIT", className=kind_tag)),
            html.Td(str(detail or "").replace("_", " ")),
            html.Td("—" if premium is None else "%.2f" % float(premium), className="num"),
            html.Td(html.Span([html.Span(className="dot"), status],
                              className="status-inline %s" % status_class)),
            html.Td(order_id[:8], className="pl-sub", title=order_id),
        ]))

    return html.Div(
        html.Table([header, html.Tbody(rows)], className="data-table"),
        className="table-scroll",
    )


def _runs_table(runs):
    if not runs:
        return empty_state(
            "fa-folder-open", "No run logs found",
            "Every completed analysis is written under eval_results/",
        )

    header = html.Thead(html.Tr([
        html.Th("Started"), html.Th("Symbol"), html.Th("Trade date"),
        html.Th("Signal"), html.Th("Status"),
        html.Th("Tools", className="num"), html.Th("Tokens", className="num"),
    ]))

    rows = []
    for run in runs:
        signal = str(run["signal"]).upper()
        signal_class = {
            "BUY": "tag tag-buy", "SELL": "tag tag-sell", "HOLD": "tag tag-hold",
        }.get(signal, "tag tag-hold")
        status = str(run["status"]).lower()
        status_class = (
            "text-pos" if status == "completed"
            else ("text-neg" if status == "failed" else "text-dim")
        )
        rows.append(html.Tr([
            html.Td(str(run["started_at"])[:19].replace("T", " "), className="pl-sub"),
            html.Td(run["symbol"], className="sym"),
            html.Td(run["trade_date"]),
            html.Td(html.Span(signal, className=signal_class)),
            html.Td(status, className=status_class),
            html.Td("{:,}".format(int(run["tools"] or 0)), className="num"),
            html.Td("{:,}".format(int(run["tokens"] or 0)), className="num"),
        ]))

    return html.Div(
        html.Table([header, html.Tbody(rows)], className="data-table"),
        className="table-scroll",
    )
