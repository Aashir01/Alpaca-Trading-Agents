"""Dashboard, top bar, and Options Desk data callbacks.

Everything rendered here comes from live Alpaca data or in-process agent state.
Alpaca calls are wrapped so a credential or network failure degrades to a clear
"unavailable" state rather than rendering confident zeros.
"""

import json
from pathlib import Path

from dash import ALL, Input, Output, State, ctx, html

from webui.components.app_shell import empty_state
from webui.components.dashboard import EQUITY_RANGES
from webui.utils.charts import (
    create_allocation_donut,
    create_dte_chart,
    create_equity_curve,
    create_exposure_bar,
    create_payoff_diagram,
    create_pl_bars,
    create_signal_history,
    create_sparkline,
    empty_figure,
)
from webui.utils.state import app_state

# Option symbols are OCC-format and far longer than any equity ticker.
_OPTION_SYMBOL_MIN_LEN = 13

# Position dict keys, named here because the apostrophe cannot appear inside an
# f-string expression.
_DAY_PL_PCT = "Today's P/L (%)"
_DAY_PL_USD = "Today's P/L ($)"

_PIPELINE_STAGES = [
    ("Analysts", ["Market Analyst", "Social Analyst", "News Analyst",
                  "Fundamentals Analyst", "Macro Analyst"]),
    ("Research", ["Bull Researcher", "Bear Researcher", "Research Manager"]),
    ("Execution", ["Trader", "Options Strategist"]),
    ("Risk", ["Risky Analyst", "Safe Analyst", "Neutral Analyst", "Portfolio Manager"]),
]


# --------------------------------------------------------------- helpers ---

def _money(value, decimals=2):
    try:
        return f"${float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def _signed_money(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{'+' if value >= 0 else '-'}${abs(value):,.2f}"


def _tone(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    return "text-pos" if value > 0 else ("text-neg" if value < 0 else "text-dim")


def _parse_money(text):
    """Positions come back pre-formatted as strings like '$1,234.56'."""
    if text is None:
        return 0.0
    if isinstance(text, (int, float)):
        return float(text)
    try:
        return float(str(text).replace("$", "").replace(",", "").replace("%", "").strip())
    except ValueError:
        return 0.0


def _is_option_symbol(symbol):
    symbol = str(symbol or "")
    return len(symbol) >= _OPTION_SYMBOL_MIN_LEN and symbol[-9:-8] in ("C", "P")


def _days_to_expiry(occ_symbol):
    """Calendar days until an OCC contract expires, or None if unparseable.

    An OCC symbol is ROOT + YYMMDD + C/P + 8-digit strike, so the date always
    sits in the six characters before the option-type letter.
    """
    from datetime import date, datetime as _datetime

    raw = str(occ_symbol or "")
    if len(raw) < 15:
        return None
    try:
        expiry = _datetime.strptime(raw[-15:-9], "%y%m%d").date()
    except ValueError:
        return None
    return max(0, (expiry - date.today()).days)


def _spot_price(symbol):
    """Last quoted mid for the underlying, used to mark the payoff curve."""
    if not symbol or not _alpaca_configured():
        return None
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        quote = AlpacaUtils.get_latest_quote(symbol) or {}
    except Exception:
        return None
    bid = quote.get("bid_price") or quote.get("bid") or 0
    ask = quote.get("ask_price") or quote.get("ask") or 0
    try:
        bid, ask = float(bid), float(ask)
    except (TypeError, ValueError):
        return None
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return bid or ask or None


def _alpaca_configured():
    """True when Alpaca credentials are present.

    get_account_info deliberately returns zeros on failure so risk gates size
    to a zero allowance instead of an unverified number. That is right for the
    gate and wrong for the UI, where rendering a confident $0.00 would look
    like a funded-but-empty account. So the UI checks for credentials first and
    says "not connected" instead.
    """
    try:
        from tradingagents.dataflows.config import get_api_key

        return bool(
            get_api_key("alpaca_api_key", "ALPACA_API_KEY")
            and get_api_key("alpaca_secret_key", "ALPACA_SECRET_KEY")
        )
    except Exception:
        return False


# A single dashboard refresh fans out into a dozen callbacks -- KPIs, the
# equity curve, allocation, exposure, position P/L, the positions table, the
# orders table, the options tiles -- and every one of them wants the same
# account snapshot and the same position list. Without this, one 15-second
# tick becomes a dozen serial Alpaca round trips and the page paints in
# waves. The window is deliberately shorter than the fastest refresh
# interval, so nothing on screen is ever a tick behind.
_CACHE_TTL_SECONDS = 1.5
_cache = {}


def _cached(key, producer, ttl=_CACHE_TTL_SECONDS):
    """Return ``producer()``, reusing the value for ``ttl`` seconds."""
    import time

    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    value = producer()
    _cache[key] = (now, value)
    return value


def _account():
    if not _alpaca_configured():
        return None, "Alpaca not connected"

    def fetch():
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils

            return AlpacaUtils.get_account_info(), None
        except Exception as exc:
            return None, str(exc)

    return _cached("account", fetch)


def _positions():
    if not _alpaca_configured():
        return []

    def fetch():
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils

            return AlpacaUtils.get_positions_data() or []
        except Exception:
            return []

    return _cached("positions", fetch)


def _config():
    try:
        from tradingagents.dataflows.config import get_config

        return get_config() or {}
    except Exception:
        return {}


def _recorded_signal_counts(limit_days=30):
    """Count completed runs per trade date and final signal, across symbols.

    Reads the same persisted run logs the backtester replays, so the chart and
    the backtest are looking at one history rather than two. Returns
    ``({date: {action: count}}, {action: total})``.
    """
    from collections import defaultdict

    try:
        from tradingagents.backtest.signals import normalize_action
    except Exception:
        return {}, {}

    results_dir = Path(_config().get("results_dir") or "eval_results")
    if not results_dir.is_dir():
        return {}, {}

    per_date = defaultdict(lambda: defaultdict(int))
    totals = defaultdict(int)
    for run_path in results_dir.glob("*/TradingAgentsStrategy_logs/runs/*.json"):
        try:
            with run_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if payload.get("status") != "completed":
            continue
        action = normalize_action((payload.get("summary") or {}).get("final_signal"))
        trade_date = str(payload.get("trade_date") or "").strip()
        if not action or not trade_date:
            continue
        per_date[trade_date][action] += 1
        totals[action] += 1

    # Only the recent window: a year of history compressed into a panel-width
    # bar chart is a texture, not a reading.
    recent = sorted(per_date)[-limit_days:]
    return ({date: dict(per_date[date]) for date in recent}, dict(totals))


def _signal_counts_cached(limit_days=30):
    """``_recorded_signal_counts`` behind a longer window.

    It walks every run log on disk, which is far too slow to repeat on each
    15-second tick and changes only when a run finishes.
    """
    return _cached(f"signals:{limit_days}",
                   lambda: _recorded_signal_counts(limit_days), ttl=30.0)


def _delta_node(amount, percent):
    icon = "fa-arrow-up" if (amount or 0) >= 0 else "fa-arrow-down"
    return html.Span(
        [
            html.I(className=f"fas {icon}", style={"fontSize": "10px"}),
            f"{_signed_money(amount)} ({percent:+.2f}%)",
        ],
        className=_tone(amount),
    )


# ------------------------------------------------------------- callbacks ---

def register_dashboard_callbacks(app):

    @app.callback(
        [Output("topbar-equity", "children"),
         Output("topbar-daypl", "children"),
         Output("topbar-daypl", "className"),
         Output("topbar-bp", "children"),
         Output("topbar-market", "children"),
         Output("topbar-mode", "children")],
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_topbar(_n):
        info, error = _account()
        if error or not info:
            equity = bp = daypl = "—"
            daypl_class = "topbar-metric-value text-faint"
        else:
            equity = _money(info.get("equity"))
            bp = _money(info.get("buying_power"))
            change = info.get("daily_change_dollars") or 0
            pct = info.get("daily_change_percent") or 0
            daypl = f"{_signed_money(change)} ({pct:+.2f}%)"
            daypl_class = f"topbar-metric-value {_tone(change)}"

        try:
            from webui.utils.market_hours import is_market_open

            is_open, label = is_market_open()
        except Exception:
            is_open, label = False, "Market status unknown"

        market = html.Span(
            [html.Span(className="dot dot-pulse" if is_open else "dot"),
             html.Span("Market Open" if is_open else "Market Closed")],
            className=f"pill {'pill-open' if is_open else 'pill-closed'}",
            title=label,
        )

        try:
            from tradingagents.dataflows.config import get_alpaca_use_paper

            paper = get_alpaca_use_paper()
        except Exception:
            paper = True

        mode = html.Span(
            [html.Span(className="dot"), html.Span("Paper" if paper else "LIVE")],
            className=f"pill {'pill-paper' if paper else 'pill-live'}",
            title="Paper trading environment" if paper else "Live trading - real capital at risk",
        )
        return equity, daypl, daypl_class, bp, market, mode

    @app.callback(
        [Output("kpi-equity", "children"),
         Output("kpi-equity-delta", "children"),
         Output("kpi-equity-tile", "className"),
         Output("kpi-daypl", "children"),
         Output("kpi-daypl", "className"),
         Output("kpi-daypl-sub", "children"),
         Output("kpi-daypl-tile", "className"),
         Output("kpi-openpl", "children"),
         Output("kpi-openpl", "className"),
         Output("kpi-openpl-sub", "children"),
         Output("kpi-openpl-tile", "className"),
         Output("kpi-bp", "children"),
         Output("kpi-bp-sub", "children"),
         Output("kpi-exposure", "children"),
         Output("kpi-exposure-sub", "children"),
         Output("kpi-options", "children"),
         Output("kpi-options-sub", "children")],
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_kpis(_n):
        info, error = _account()
        positions = _positions()

        if error or not info:
            dash = "—"
            note = html.Span(error or "Alpaca unavailable", className="text-faint")
            hint = "Add Alpaca keys in Settings"
            return (dash, note, "kpi neutral", dash, "kpi-value text-faint", hint, "kpi neutral",
                    dash, "kpi-value text-faint", hint, "kpi neutral", dash, hint,
                    dash, hint, dash, hint)

        equity = info.get("equity") or 0
        change = info.get("daily_change_dollars") or 0
        pct = info.get("daily_change_percent") or 0

        open_pl = sum(_parse_money(p.get("Total P/L ($)")) for p in positions)
        cost_basis = sum(_parse_money(p.get("Cost Basis")) for p in positions)
        open_pct = (open_pl / cost_basis * 100) if cost_basis else 0.0
        gross = sum(abs(_parse_money(p.get("Market Value"))) for p in positions)
        gross_pct = (gross / equity * 100) if equity else 0.0

        option_positions = [p for p in positions if _is_option_symbol(p.get("Symbol"))]
        option_value = sum(abs(_parse_money(p.get("Market Value"))) for p in option_positions)

        equity_tone = "kpi pos" if change > 0 else ("kpi neg" if change < 0 else "kpi neutral")
        day_tone = "kpi pos" if change > 0 else ("kpi neg" if change < 0 else "kpi neutral")
        open_tone = "kpi pos" if open_pl > 0 else ("kpi neg" if open_pl < 0 else "kpi neutral")

        return (
            _money(equity),
            _delta_node(change, pct),
            equity_tone,
            _signed_money(change),
            f"kpi-value {_tone(change)}",
            f"{pct:+.2f}% since previous close",
            day_tone,
            _signed_money(open_pl),
            f"kpi-value {_tone(open_pl)}",
            f"{open_pct:+.2f}% on ${cost_basis:,.0f} cost basis" if cost_basis else "No open cost basis",
            open_tone,
            _money(info.get("buying_power")),
            f"{_money(info.get('cash'))} cash",
            _money(gross),
            f"{gross_pct:.1f}% of equity",
            str(len(option_positions)),
            f"{_money(option_value)} market value" if option_positions else "No options exposure",
        )

    @app.callback(
        Output("dash-allocation-chart", "figure"),
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_allocation(_n):
        positions = _positions()
        info, _ = _account()
        cash = float((info or {}).get("cash") or 0)

        slices = []
        for position in positions:
            raw = _parse_money(position.get("Market Value"))
            if abs(raw) > 0:
                label = str(position.get("Symbol", "?"))[:14]
                # A short leg contributes exposure, not value; say so in the
                # legend rather than letting it read as another long.
                slices.append((f"{label} (short)" if raw < 0 else label, abs(raw)))
        if cash > 0:
            slices.append(("Cash", cash))

        if not slices:
            if not _alpaca_configured():
                return empty_figure("Alpaca not connected",
                                    "Add API keys in Settings to see the book")
            return empty_figure("No allocation data",
                                "Holdings and cash appear here once the account is funded")
        return create_allocation_donut(slices)

    @app.callback(
        Output("dash-exposure-chart", "figure"),
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_exposure(_n):
        """Long / short / cash split of the equity, as one stacked row."""
        info, _ = _account()
        if info is None:
            return empty_figure("Alpaca not connected")

        long_value = short_value = 0.0
        for position in _positions():
            raw = _parse_money(position.get("Market Value"))
            if raw >= 0:
                long_value += raw
            else:
                short_value += abs(raw)
        return create_exposure_bar(long_value, short_value, float(info.get("cash") or 0))

    @app.callback(
        Output("dash-pl-chart", "figure"),
        Output("dash-pl-summary", "children"),
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_pl_chart(_n):
        """Which holdings are carrying the book, and which are bleeding."""
        if not _alpaca_configured():
            return empty_figure("Alpaca not connected",
                                "Add API keys in Settings to see position P/L"), ""

        rows = []
        for position in _positions():
            rows.append({
                "symbol": str(position.get("Symbol", "?"))[:16],
                "pl": _parse_money(position.get("Total P/L ($)")),
            })
        if not rows:
            return empty_figure("No open positions",
                                "Position-level P/L appears once the desk holds something"), ""

        winners = sum(1 for r in rows if r["pl"] > 0)
        losers = sum(1 for r in rows if r["pl"] < 0)
        summary = f"{winners} up · {losers} down · {len(rows)} held"
        return create_pl_bars(rows), summary

    @app.callback(
        Output("dash-equity-chart", "figure"),
        Output("dash-equity-summary", "children"),
        Output("kpi-equity-spark", "figure"),
        [Input("dashboard-interval", "n_intervals"),
         Input("equity-range-store", "data")],
    )
    def update_equity_curve(_n, selected_range):
        """Account equity over the selected window, from Alpaca's own history."""
        if not _alpaca_configured():
            blank = empty_figure("Alpaca not connected",
                                 "Add API keys in Settings to chart account equity")
            return blank, "", create_sparkline([])

        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        window = str(selected_range or "1M").upper()
        try:
            history = _cached(f"history:{window}",
                              lambda: AlpacaUtils.get_portfolio_history(window))
        except Exception as exc:  # network or credential failure
            return empty_figure("Portfolio history unavailable", str(exc)), "", create_sparkline([])

        points = history.get("points") or []
        values = [value for _, value in points]
        figure = create_equity_curve(points, baseline=values[0] if values else None)
        spark = create_sparkline(values)

        if len(values) < 2:
            return figure, [html.Span(
                "Alpaca reports equity once the account has a funded trading day.",
                className="text-faint",
            )], spark

        change = values[-1] - values[0]
        percent = (change / values[0] * 100) if values[0] else 0.0
        # A flat list, not a wrapping Span: the caption row is a flex
        # container, and its gap only reaches its own children.
        summary = [
            html.Span(_money(values[-1]), className="chart-caption-value"),
            html.Span(f"{_signed_money(change)} ({percent:+.2f}%)",
                      className=f"chart-caption-delta {_tone(change)}"),
            html.Span(f"over {window}", className="text-faint"),
        ]
        return figure, summary, spark

    @app.callback(
        Output("equity-range-store", "data"),
        Output("equity-range-buttons", "children"),
        [Input({"type": "equity-range", "value": ALL}, "n_clicks")],
        [State("equity-range-store", "data")],
        prevent_initial_call=True,
    )
    def select_equity_range(_clicks, current):
        """Track the chosen window in a store, so a refresh cannot reset it."""
        chosen = current or "1M"
        if ctx.triggered_id and isinstance(ctx.triggered_id, dict):
            chosen = ctx.triggered_id.get("value", chosen)
        return chosen, [
            html.Button(
                option,
                id={"type": "equity-range", "value": option},
                className="seg-btn active" if option == chosen else "seg-btn",
                n_clicks=0,
            )
            for option in EQUITY_RANGES
        ]

    @app.callback(
        Output("dash-signal-chart", "figure"),
        Output("dash-signal-summary", "children"),
        [Input("dashboard-interval", "n_intervals"),
         Input("medium-refresh-interval", "n_intervals")],
    )
    def update_signal_history(_a, _b):
        """Recorded BUY/SELL/HOLD calls per trading day, across every symbol."""
        per_date, totals = _signal_counts_cached()
        if not per_date:
            return (
                empty_figure(
                    "No recorded decisions yet",
                    "Completed analyses are logged under eval_results/ and charted here",
                ),
                "",
            )
        total = sum(totals.values())
        parts = [f"{count} {action}" for action, count in totals.items() if count]
        return create_signal_history(per_date), f"{total} runs · " + " · ".join(parts)

    @app.callback(
        [Output("dash-pipeline", "children"), Output("dash-pipeline-status", "children")],
        [Input("dashboard-interval", "n_intervals"), Input("refresh-interval", "n_intervals")],
    )
    def update_pipeline(_a, _b):
        symbol_states = app_state.symbol_states or {}
        if not symbol_states:
            return (
                empty_state("fa-robot", "No run in progress",
                            "Start an analysis to watch the agent team work"),
                "",
            )

        symbol = getattr(app_state, "current_symbol", None) or next(iter(symbol_states))
        state = symbol_states.get(symbol) or {}
        statuses = state.get("agent_statuses", {}) or {}

        rows = []
        for stage_name, agents in _PIPELINE_STAGES:
            present = [a for a in agents if a in statuses]
            if not present:
                continue
            rows.append(html.Div(stage_name, className="pipeline-stage"))
            for agent in present:
                status = statuses.get(agent, "pending")
                if status == "in_progress":
                    css, icon, label, tone = "agent-row running", "fa-spinner fa-spin", "Running", "text-warn"
                elif status == "completed":
                    css, icon, label, tone = "agent-row done", "fa-check", "Done", "text-pos"
                else:
                    css, icon, label, tone = "agent-row", "fa-minus", "Pending", "text-faint"
                rows.append(
                    html.Div(
                        [
                            html.Div(html.I(className=f"fas {icon}"), className="agent-icon"),
                            html.Span(agent, className="agent-name"),
                            html.Span(label, className=f"agent-state {tone}"),
                        ],
                        className=css,
                    )
                )

        done = sum(1 for v in statuses.values() if v == "completed")
        badge = html.Span(f"{symbol} · {done}/{len(statuses)}", className="text-faint",
                          style={"fontSize": "11.5px"})
        return html.Div(rows, className="pipeline"), badge

    @app.callback(
        [Output("dash-positions", "children"), Output("dash-positions-count", "children")],
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_positions(_n):
        if not _alpaca_configured():
            return (
                empty_state("fa-plug", "Alpaca not connected",
                            "Add your Alpaca API keys in Settings to see live positions"),
                "",
            )
        positions = _positions()
        if not positions:
            return (
                empty_state("fa-wallet", "No open positions",
                            "Positions opened by the agents will appear here"),
                "",
            )

        header = html.Thead(html.Tr([
            html.Th("Symbol"), html.Th("Side"), html.Th("Qty", className="num"),
            html.Th("Avg Entry", className="num"), html.Th("Market Value", className="num"),
            html.Th("Day P/L", className="num"), html.Th("Total P/L", className="num"),
        ]))

        rows = []
        for position in positions:
            qty = _parse_money(position.get("Qty"))
            day_pl = _parse_money(position.get(_DAY_PL_USD))
            total_pl = _parse_money(position.get("Total P/L ($)"))
            symbol = str(position.get("Symbol", ""))
            is_option = _is_option_symbol(symbol)

            # A short option leg is the risk-bearing side of a spread, so the
            # direction has to survive into the table rather than collapsing
            # into a generic "OPT".
            if is_option:
                tag_class = "tag tag-opt" if qty >= 0 else "tag tag-short"
                tag_text = "OPT LONG" if qty >= 0 else "OPT SHORT"
            elif qty >= 0:
                tag_class, tag_text = "tag tag-long", "LONG"
            else:
                tag_class, tag_text = "tag tag-short", "SHORT"

            rows.append(html.Tr([
                html.Td(symbol, className="sym"),
                html.Td(html.Span(tag_text, className=tag_class)),
                html.Td(f"{abs(qty):g}", className="num"),
                html.Td(position.get("Avg Entry", "—"), className="num"),
                html.Td(position.get("Market Value", "—"), className="num"),
                html.Td(
                    f"{_signed_money(day_pl)} ({position.get(_DAY_PL_PCT, '')})",
                    className=f"num {_tone(day_pl)}",
                ),
                html.Td(
                    f"{_signed_money(total_pl)} ({position.get('Total P/L (%)', '')})".strip(),
                    className=f"num {_tone(total_pl)}",
                ),
            ]))

        table = html.Div(
            html.Table([header, html.Tbody(rows)], className="data-table"),
            className="table-scroll",
        )
        options_count = sum(1 for p in positions if _is_option_symbol(p.get("Symbol")))
        summary = f"{len(positions)} position{'s' if len(positions) != 1 else ''}"
        if options_count:
            summary += f" · {options_count} options"
        return table, summary

    @app.callback(
        Output("dash-orders", "children"),
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_orders(_n):
        if not _alpaca_configured():
            return empty_state("fa-plug", "Alpaca not connected",
                               "Add your Alpaca API keys in Settings to see live orders")
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils

            orders = AlpacaUtils.get_recent_orders_page(page=1, page_size=8).get("orders", [])
        except Exception:
            orders = []

        if not orders:
            return empty_state("fa-receipt", "No recent orders",
                               "Orders submitted to Alpaca will appear here")

        header = html.Thead(html.Tr([
            html.Th("Asset"), html.Th("Side"), html.Th("Type"),
            html.Th("Qty", className="num"), html.Th("Filled", className="num"),
            html.Th("Avg Price", className="num"), html.Th("Status"),
        ]))

        rows = []
        for order in orders:
            # A multi-leg options order carries no Side or Asset of its own --
            # the legs hold them -- so it is named for what it is rather than
            # rendered as a "NONE" trade in a "None" symbol.
            side = str(order.get("Side") or "").replace("OrderSide.", "").lower()
            tag = "tag tag-buy" if "buy" in side else (
                "tag tag-sell" if "sell" in side else "tag tag-opt")
            status = str(order.get("Status", "")).replace("OrderStatus.", "").lower()
            rows.append(html.Tr([
                html.Td(str(order.get("Asset") or "Multi-leg"), className="sym"),
                html.Td(html.Span(side.upper() or "SPREAD", className=tag)),
                html.Td(str(order.get("Order Type", "")).replace("OrderType.", "").lower()),
                html.Td(f"{_parse_money(order.get('Qty')):g}", className="num"),
                html.Td(f"{_parse_money(order.get('Filled Qty')):g}", className="num"),
                html.Td(order.get("Avg. Fill Price", "—"), className="num"),
                html.Td(status),
            ]))

        return html.Div(
            html.Table([header, html.Tbody(rows)], className="data-table"),
            className="table-scroll",
        )

    @app.callback(
        Output("dash-decisions", "children"),
        [Input("dashboard-interval", "n_intervals"), Input("medium-refresh-interval", "n_intervals")],
    )
    def update_decisions(_a, _b):
        symbol_states = app_state.symbol_states or {}
        rows = []
        for symbol, state in symbol_states.items():
            action = state.get("recommended_action")
            if not action:
                continue
            action = str(action).upper()
            tag = {"BUY": "tag tag-buy", "LONG": "tag tag-buy",
                   "SELL": "tag tag-sell", "SHORT": "tag tag-sell"}.get(action, "tag tag-hold")
            plan = state.get("options_trade_plan") or {}
            overlay = plan.get("strategy", "").replace("_", " ") if plan else ""
            rows.append(html.Tr([
                html.Td(symbol, className="sym"),
                html.Td(html.Span(action, className=tag)),
                html.Td(html.Span(overlay or "—",
                                  className="tag tag-opt" if overlay else "text-faint")),
            ]))

        if not rows:
            return empty_state("fa-gavel", "No decisions yet",
                               "Final risk-adjusted calls will be listed here")

        header = html.Thead(html.Tr([
            html.Th("Symbol"), html.Th("Signal"), html.Th("Options Overlay"),
        ]))
        return html.Div(
            html.Table([header, html.Tbody(rows)], className="data-table"),
            className="table-scroll",
        )

    @app.callback(
        Output("dash-options", "children"),
        [Input("dashboard-interval", "n_intervals"), Input("medium-refresh-interval", "n_intervals")],
    )
    def update_options_summary(_a, _b):
        config = _config()
        if not config.get("options_trading_enabled", False):
            return empty_state("fa-layer-group", "Options overlay disabled",
                               "Set OPTIONS_TRADING_ENABLED=True to arm the desk")

        rows = [
            html.Div([html.Span("Overlay", className="gate-label"),
                      html.Span("Armed", className="gate-value text-pos")],
                     className="gate-row pass"),
            html.Div([html.Span("Max loss per trade", className="gate-label"),
                      html.Span(f"{config.get('options_max_loss_pct', 2.0)}% of equity",
                                className="gate-value")], className="gate-row"),
            html.Div([html.Span("Max bid-ask spread", className="gate-label"),
                      html.Span(f"{config.get('options_max_spread_pct', 20.0)}% of mid",
                                className="gate-value")], className="gate-row"),
            html.Div([html.Span("Expiry window", className="gate-label"),
                      html.Span(f"{config.get('options_dte_min', 7)}-{config.get('options_dte_max', 45)} DTE",
                                className="gate-value")], className="gate-row"),
        ]

        plans = [
            (symbol, state.get("options_trade_plan"))
            for symbol, state in (app_state.symbol_states or {}).items()
            if state.get("options_trade_plan")
        ]
        if plans:
            rows.append(html.Div("Approved plans", className="pipeline-stage"))
            for symbol, plan in plans:
                gate = plan.get("gate_result") or {}
                rows.append(html.Div([
                    html.Span(symbol, className="sym"),
                    html.Span(str(plan.get("strategy", "")).replace("_", " "),
                              className="tag tag-opt", style={"marginLeft": "8px"}),
                    html.Span(f"max loss {_money(gate.get('max_loss_usd'))}",
                              className="gate-value"),
                ], className="gate-row pass"))

        return html.Div(rows)

    # ----------------------------------------------------- options desk ---

    @app.callback(
        [Output("opt-kpi-status", "children"),
         Output("opt-kpi-status", "className"),
         Output("opt-kpi-status-sub", "children"),
         Output("opt-kpi-maxloss", "children"),
         Output("opt-kpi-maxloss-sub", "children"),
         Output("opt-kpi-contracts", "children"),
         Output("opt-kpi-contracts-sub", "children"),
         Output("opt-kpi-pl", "children"),
         Output("opt-kpi-pl", "className"),
         Output("opt-kpi-pl-sub", "children"),
         Output("opt-rules", "children")],
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_options_kpis(_n):
        config = _config()
        enabled = bool(config.get("options_trading_enabled", False))
        info, _ = _account()
        equity = float((info or {}).get("equity") or 0)

        max_loss_pct = float(config.get("options_max_loss_pct", 2.0))
        allowance = equity * max_loss_pct / 100.0

        positions = _positions()
        option_positions = [p for p in positions if _is_option_symbol(p.get("Symbol"))]
        contracts = sum(abs(_parse_money(p.get("Qty"))) for p in option_positions)
        options_pl = sum(_parse_money(p.get("Total P/L ($)")) for p in option_positions)

        rules = [
            ("No naked short legs", "Every short leg is paired or fully collateralized"),
            (f"Loss cap {max_loss_pct}% of equity", f"{_money(allowance)} allowance today"),
            (f"Spread ≤ {config.get('options_max_spread_pct', 20.0)}% of mid", "Illiquid legs are rejected"),
            ("Live-quote repricing", "Premium and max loss recomputed, never taken from the model"),
            ("Direction reconciliation", "Plan is dropped if the risk judge flips the signal"),
            ("Fail-closed re-check", "Gate re-runs against fresh quotes before submission"),
        ]
        rule_nodes = [
            html.Div([
                html.I(className="fas fa-check", style={"color": "#22D07F", "fontSize": "10px"}),
                html.Span(title, className="gate-label", style={"marginLeft": "8px"}),
                html.Span(detail, className="gate-value text-faint",
                          style={"fontSize": "11px", "fontWeight": "500"}),
            ], className="gate-row pass" if enabled else "gate-row")
            for title, detail in rules
        ]

        return (
            "Armed" if enabled else "Disabled",
            f"kpi-value sm {'text-pos' if enabled else 'text-faint'}",
            "Options Strategist is in the graph" if enabled
            else "OPTIONS_TRADING_ENABLED=False",
            _money(allowance) if equity else "—",
            f"{max_loss_pct}% of {_money(equity)} equity" if equity else "Account unavailable",
            f"{contracts:g}",
            f"{len(option_positions)} position{'s' if len(option_positions) != 1 else ''}",
            _signed_money(options_pl) if option_positions else "—",
            f"kpi-value {_tone(options_pl)}",
            "Unrealized on open options" if option_positions else "No open options",
            rule_nodes,
        )

    @app.callback(
        [Output("opt-proposal", "children"),
         Output("opt-proposal-symbol", "children"),
         Output("opt-gate", "children"),
         Output("opt-positions", "children")],
        [Input("dashboard-interval", "n_intervals"), Input("medium-refresh-interval", "n_intervals")],
    )
    def update_options_desk(_a, _b):
        report, symbol_label, plan = None, "", None
        for symbol, state in (app_state.symbol_states or {}).items():
            candidate = (state.get("current_reports") or {}).get("options_strategy_report")
            if candidate:
                report, symbol_label = candidate, symbol
                plan = state.get("options_trade_plan")
                break

        proposal = report or (
            "No options proposal yet.\n\n"
            "The Options Strategist runs between the Trader and the risk debate "
            "on every analysis when the overlay is enabled."
        )

        if plan:
            gate = plan.get("gate_result") or {}
            approved = gate.get("approved")
            net = gate.get("net_credit_debit") or 0
            gate_view = html.Div([
                html.Div([html.Span("Verdict", className="gate-label"),
                          html.Span("Approved" if approved else "Vetoed",
                                    className=f"gate-value {'text-pos' if approved else 'text-neg'}")],
                         className=f"gate-row {'pass' if approved else 'fail'}"),
                html.Div([html.Span("Worst case", className="gate-label"),
                          html.Span(_money(gate.get("max_loss_usd")), className="gate-value")],
                         className="gate-row"),
                html.Div([html.Span("Risk-sized loss", className="gate-label"),
                          html.Span(_money(gate.get("stress_loss_usd")), className="gate-value")],
                         className="gate-row"),
                html.Div([html.Span("Net premium", className="gate-label"),
                          html.Span(f"{_money(abs(net))} {'credit' if net < 0 else 'debit'}",
                                    className="gate-value")], className="gate-row"),
                html.Div([html.Span("Collateral", className="gate-label"),
                          html.Span(_money(gate.get("collateral_required")) if gate.get("collateral_required")
                                    else "None", className="gate-value")], className="gate-row"),
            ])
        else:
            gate_view = empty_state("fa-shield-halved", "No verdict yet",
                                    "Every leg is re-priced from live bid/ask before approval")

        option_positions = [p for p in _positions() if _is_option_symbol(p.get("Symbol"))]
        if not option_positions:
            positions_view = empty_state("fa-layer-group", "No open options positions",
                                         "Approved multi-leg orders will appear here once filled")
        else:
            header = html.Thead(html.Tr([
                html.Th("Contract"), html.Th("Side"), html.Th("Qty", className="num"),
                html.Th("Avg Entry", className="num"), html.Th("Market Value", className="num"),
                html.Th("Total P/L", className="num"),
            ]))
            rows = []
            for position in option_positions:
                total_pl = _parse_money(position.get("Total P/L ($)"))
                qty = _parse_money(position.get("Qty"))
                long_leg = qty >= 0
                rows.append(html.Tr([
                    html.Td(position.get("Symbol", ""), className="sym"),
                    html.Td(html.Span("LONG" if long_leg else "SHORT",
                                      className="tag tag-opt" if long_leg else "tag tag-short")),
                    html.Td(f"{abs(qty):g}", className="num"),
                    html.Td(position.get("Avg Entry", "—"), className="num"),
                    html.Td(position.get("Market Value", "—"), className="num"),
                    html.Td(_signed_money(total_pl), className=f"num {_tone(total_pl)}"),
                ]))
            positions_view = html.Div(
                html.Table([header, html.Tbody(rows)], className="data-table"),
                className="table-scroll",
            )

        return proposal, symbol_label, gate_view, positions_view

    @app.callback(
        Output("opt-payoff-chart", "figure"),
        Output("opt-payoff-summary", "children"),
        [Input("dashboard-interval", "n_intervals"),
         Input("medium-refresh-interval", "n_intervals")],
    )
    def update_options_payoff(_a, _b):
        """Draw the proposed structure's expiry payoff from the gate's numbers."""
        plan, symbol = None, ""
        for candidate_symbol, state in (app_state.symbol_states or {}).items():
            candidate = state.get("options_trade_plan")
            if candidate:
                plan, symbol = candidate, candidate_symbol
                break

        if not plan:
            return (
                empty_figure(
                    "No approved structure yet",
                    "The payoff curve is drawn once the risk gate approves a proposal",
                ),
                "",
            )

        gate = plan.get("gate_result") or {}
        contracts = int(_config().get("options_max_contracts", 1) or 1)
        figure = create_payoff_diagram(
            plan.get("legs") or [],
            gate.get("net_credit_debit"),
            contracts=contracts,
            spot=_spot_price(plan.get("symbol") or symbol),
            strategy=plan.get("strategy", ""),
        )
        max_loss = gate.get("max_loss_usd")
        summary = f"{plan.get('symbol') or symbol} · worst case {_money(max_loss)}" if max_loss else (
            plan.get("symbol") or symbol
        )
        return figure, summary

    @app.callback(
        Output("opt-dte-chart", "figure"),
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_options_dte(_n):
        """Time remaining on every open contract, parsed from its OCC symbol."""
        rows = []
        for position in _positions():
            symbol = str(position.get("Symbol") or "")
            if not _is_option_symbol(symbol):
                continue
            days = _days_to_expiry(symbol)
            if days is None:
                continue
            rows.append({"symbol": symbol, "dte": days})

        if not rows:
            return empty_figure("No open option contracts",
                                "Expiry runway appears once a spread is filled")
        return create_dte_chart(rows)

    @app.callback(
        Output("opt-iv-history", "children"),
        [Input("dashboard-interval", "n_intervals")],
    )
    def update_iv_history(_n):
        """Show how much IV history exists, since IV rank depends on it."""
        from pathlib import Path

        config = _config()
        minimum = int(config.get("options_min_iv_history_days", 20))
        cache = Path(config.get("data_cache_dir", "tradingagents/dataflows/data_cache"))
        directory = cache / "options_iv_history"

        entries = []
        if directory.exists():
            import json

            for path in sorted(directory.glob("*.json")):
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        history = json.load(handle)
                    entries.append((path.stem, len(history or {})))
                except (OSError, ValueError):
                    continue

        if not entries:
            return empty_state(
                "fa-wave-square", "No IV history recorded",
                "Run scripts/record_iv_history.py daily to make IV rank meaningful",
            )

        rows = []
        for symbol, days in entries:
            ready = days >= minimum
            rows.append(html.Tr([
                html.Td(symbol, className="sym"),
                html.Td(f"{days}", className="num"),
                html.Td(html.Span("Reliable" if ready else "Building",
                                  className="tag tag-long" if ready else "tag tag-hold")),
            ]))

        header = html.Thead(html.Tr([
            html.Th("Symbol"), html.Th("Observations", className="num"), html.Th("IV Rank"),
        ]))
        return html.Div([
            html.Table([header, html.Tbody(rows)], className="data-table"),
            html.Div(
                f"IV rank is treated as unreliable below {minimum} observations; "
                "the strategist is told so and prefers long-premium structures.",
                className="text-faint",
                style={"fontSize": "11.5px", "marginTop": "11px"},
            ),
        ])
