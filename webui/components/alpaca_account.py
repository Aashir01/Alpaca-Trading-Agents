"""
webui/components/alpaca_account.py - Alpaca account information components
"""

from dash import html, dcc

from tradingagents.dataflows.alpaca_utils import AlpacaUtils
from tradingagents.dataflows.config import get_alpaca_use_paper
from webui.components.app_shell import empty_state, panel


ORDERS_PAGE_SIZE = 10


def _visible_order_pages(active_page, total_pages):
    """Show latest five pages, oldest five pages, and the active page if it sits between them."""
    if total_pages <= 11:
        return list(range(1, total_pages + 1))

    latest_pages = set(range(1, min(5, total_pages) + 1))
    oldest_pages = set(range(max(1, total_pages - 4), total_pages + 1))
    pages = sorted(latest_pages | oldest_pages | {active_page})

    visible = []
    previous = None
    for page in pages:
        if previous is not None and page - previous > 1:
            visible.append("gap")
        visible.append(page)
        previous = page
    return visible


def render_orders_pagination(active_page, total_pages, total_orders=0, has_more=False):
    """Compact Recent Orders pagination with latest/oldest page windows."""
    total_pages = max(1, int(total_pages or 1))
    active_page = max(1, min(int(active_page or 1), total_pages))
    page_items = _visible_order_pages(active_page, total_pages)

    def page_button(children, page_key, title, disabled=False, active=False):
        return html.Button(
            children,
            id={"type": "orders-page-btn", "page": page_key},
            className=f"seg-btn orders-page-btn{' active' if active else ''}",
            disabled=disabled,
            title=title,
            n_clicks=0,
        )

    buttons = [
        page_button(
            html.I(className="fas fa-chevron-left"),
            f"prev-{max(1, active_page - 1)}",
            "Previous page",
            disabled=active_page <= 1,
        )
    ]

    for item in page_items:
        if item == "gap":
            buttons.append(html.Span("…", className="orders-page-gap"))
            continue
        buttons.append(
            page_button(
                str(item),
                f"page-{item}",
                f"Page {item}",
                disabled=item == active_page,
                active=item == active_page,
            )
        )

    buttons.append(
        page_button(
            html.I(className="fas fa-chevron-right"),
            f"next-{min(total_pages, active_page + 1)}",
            "Next page",
            disabled=active_page >= total_pages,
        )
    )

    total_text = f"{total_orders}+ orders" if has_more else f"{total_orders} orders"

    return html.Div(
        [
            html.Div(buttons, className="segmented wrap"),
            html.Div(
                f"Page {active_page} of {total_pages} · {total_text}",
                className="orders-page-meta",
            ),
        ],
        className="orders-pagination",
    )


def render_positions_table():
    """Open positions with a per-row liquidate action.

    Rendered with the app's own table skin rather than the old "enhanced"
    gradient cards, so this page reads as the same product as the dashboard.
    Every id the liquidation callbacks target is unchanged.
    """
    try:
        positions_data = AlpacaUtils.get_positions_data()

        if not positions_data:
            return empty_state(
                "fa-wallet",
                "No open positions",
                "Positions opened by the agents will appear here",
            )

        def _pl_class(pl_str):
            """Colour by the sign of the number, not the shape of the string."""
            try:
                value = float(str(pl_str).replace("$", "").replace(",", ""))
            except ValueError:
                return "text-dim"
            return "text-pos" if value > 0 else ("text-neg" if value < 0 else "text-dim")

        rows = []
        for position in positions_data:
            today_class = _pl_class(position["Today's P/L ($)"])
            total_class = _pl_class(position["Total P/L ($)"])
            quantity = position["Qty"]
            long_leg = float(quantity or 0) >= 0

            rows.append(
                html.Tr(
                    [
                        html.Td(
                            [
                                html.Div(position["Symbol"], className="sym"),
                                html.Div(
                                    html.Span(
                                        "LONG" if long_leg else "SHORT",
                                        className="tag tag-long" if long_leg else "tag tag-short",
                                    ),
                                    style={"marginTop": "4px"},
                                ),
                            ]
                        ),
                        html.Td(f"{quantity:g}" if isinstance(quantity, (int, float))
                                else str(quantity), className="num"),
                        html.Td(position["Avg Entry"], className="num"),
                        html.Td(position["Market Value"], className="num"),
                        html.Td(
                            [
                                html.Div(position["Today's P/L ($)"], className=today_class),
                                html.Div(position["Today's P/L (%)"],
                                         className=f"{today_class} pl-sub"),
                            ],
                            className="num",
                        ),
                        html.Td(
                            [
                                html.Div(position["Total P/L ($)"], className=total_class),
                                html.Div(position["Total P/L (%)"],
                                         className=f"{total_class} pl-sub"),
                            ],
                            className="num",
                        ),
                        html.Td(
                            html.Button(
                                [html.I(className="fas fa-xmark"), "Close"],
                                id={"type": "liquidate-btn", "index": position["Symbol"]},
                                className="danger-btn",
                                title=f"Liquidate {position['Symbol']}",
                            ),
                            className="num",
                        ),
                    ],
                    id=f"position-row-{position['Symbol']}",
                )
            )

        header = html.Thead(
            html.Tr(
                [
                    html.Th("Position"),
                    html.Th("Qty", className="num"),
                    html.Th("Avg Entry", className="num"),
                    html.Th("Market Value", className="num"),
                    html.Th("Today's P/L", className="num"),
                    html.Th("Total P/L", className="num"),
                    html.Th("", className="num"),
                ]
            )
        )
        return html.Div(
            html.Table([header, html.Tbody(rows)], className="data-table"),
            className="table-scroll",
        )

    except Exception as e:
        print(f"Error rendering positions table: {e}")
        return empty_state(
            "fa-triangle-exclamation",
            "Unable to load positions",
            f"Check your Alpaca API keys — {e}",
        )


def render_orders_table_body(orders_data, page=1):
    """Render only the Recent Orders table body so the loading spinner stays off pagination."""
    if not orders_data:
        return empty_state(
            "fa-receipt", "No recent orders", "No trading activity found on this account"
        )

    status_classes = {
        "filled": "text-pos",
        "canceled": "text-neg",
        "rejected": "text-neg",
        "expired": "text-dim",
        "pending_new": "text-warn",
        "accepted": "text-dim",
        "new": "text-dim",
    }

    rows = []
    for idx, order in enumerate(orders_data):
        # A multi-leg options order carries Side and Asset as None -- the legs
        # hold them, not the parent. `.get(key, "")` still returns None when the
        # key is present and null, so the default alone is not enough and the
        # whole orders table used to fail to render once an mleg order existed.
        status = str(order.get("Status") or "").lower().replace("orderstatus.", "")
        status_class = status_classes.get(status, "text-dim")
        side = str(order.get("Side") or "").lower().replace("orderside.", "")
        side_tag = "tag tag-buy" if side == "buy" else (
            "tag tag-sell" if side == "sell" else "tag tag-opt")
        order_type = str(order.get("Order Type") or "").lower().replace("ordertype.", "")

        rows.append(
            html.Tr(
                [
                    html.Td(
                        [
                            html.Div(order.get("Asset") or "Multi-leg", className="sym"),
                            html.Div(order_type, className="pl-sub"),
                        ]
                    ),
                    html.Td(html.Span(side.upper() or "SPREAD", className=side_tag)),
                    html.Td(f"{float(order.get('Qty') or 0):g}", className="num"),
                    html.Td(f"{float(order.get('Filled Qty') or 0):g}", className="num"),
                    html.Td(order.get("Avg. Fill Price", "—"), className="num"),
                    html.Td(
                        html.Span(
                            [html.Span(className="dot"), status or "—"],
                            className=f"status-inline {status_class}",
                        )
                    ),
                ],
                id=f"order-row-{order.get('Asset') or 'mleg'}-{page}-{idx}",
            )
        )

    header = html.Thead(
        html.Tr(
            [
                html.Th("Asset"),
                html.Th("Side"),
                html.Th("Qty", className="num"),
                html.Th("Filled", className="num"),
                html.Th("Avg Price", className="num"),
                html.Th("Status"),
            ]
        )
    )
    return html.Table([header, html.Tbody(rows)], className="data-table")


def render_orders_table_error(error):
    return empty_state(
        "fa-triangle-exclamation",
        "Unable to load orders",
        f"Check your Alpaca API keys — {error}",
    )


def render_orders_table(page=1, page_size=ORDERS_PAGE_SIZE):
    """Render the enhanced Recent Orders surface with table-only loading."""
    try:
        page_data = AlpacaUtils.get_recent_orders_page(page=page, page_size=page_size)
        active_page = page_data.get("page", page)
        total_pages = page_data.get("total_pages", 1)
        total_orders = page_data.get("total_orders", 0)
        has_more = page_data.get("has_more", False)

        return html.Div([
            dcc.Loading(
                html.Div(
                    id="orders-table-body-container",
                    children=render_orders_table_body(page_data.get("orders", []), active_page),
                    className="orders-table-body",
                ),
                type="circle",
                className="orders-loading",
            ),
            html.Div(
                id="orders-pagination-container",
                children=render_orders_pagination(active_page, total_pages, total_orders, has_more),
            ),
        ], className="orders-table-container")

    except Exception as e:
        print(f"Error rendering orders table: {e}")
        return html.Div([
            dcc.Loading(
                html.Div(id="orders-table-body-container", children=render_orders_table_error(e)),
                type="circle",
                className="orders-loading",
            ),
            html.Div(id="orders-pagination-container", children=render_orders_pagination(1, 1, 0, False)),
        ], className="orders-table-container")


def render_account_summary():
    """Account cash, buying power, and the day's change, as KPI tiles."""
    try:
        account_info = AlpacaUtils.get_account_info()
        daily_change_dollars = account_info["daily_change_dollars"]
        daily_change_percent = account_info["daily_change_percent"]
        tone = "pos" if daily_change_dollars >= 0 else "neg"
        arrow = "fa-arrow-up" if daily_change_dollars >= 0 else "fa-arrow-down"

        def tile(label, icon, value, value_class="kpi-value", tone_class="neutral", sub=None):
            children = [
                html.Div([html.I(className=f"fas {icon}"), label], className="kpi-label"),
                html.Div(value, className=value_class),
            ]
            if sub:
                children.append(html.Div(sub, className="kpi-sub"))
            return html.Div(children, className=f"kpi {tone_class}")

        return html.Div(
            [
                tile("Buying Power", "fa-wallet",
                     f"${account_info['buying_power']:,.2f}"),
                tile("Cash", "fa-dollar-sign", f"${account_info['cash']:,.2f}"),
                tile("Portfolio Value", "fa-sack-dollar",
                     f"${account_info['portfolio_value']:,.2f}"),
                tile(
                    "Daily Change", arrow,
                    f"{'+' if daily_change_dollars >= 0 else '-'}"
                    f"${abs(daily_change_dollars):,.2f}",
                    value_class=f"kpi-value text-{tone}",
                    tone_class=tone,
                    sub=f"{daily_change_percent:+.2f}% since previous close",
                ),
            ],
            className="kpi-grid",
        )

    except Exception as e:
        print(f"Error rendering account summary: {e}")
        return empty_state(
            "fa-triangle-exclamation",
            "Unable to load account summary",
            f"Check your Alpaca API keys — {e}",
        )


def get_positions_data():
    """Get positions data for table callback"""
    try:
        return AlpacaUtils.get_positions_data()
    except Exception as e:
        print(f"Error getting positions data: {e}")
        return []

def get_recent_orders(page=1, page_size=ORDERS_PAGE_SIZE):
    """Get recent orders data for table callback"""
    try:
        return AlpacaUtils.get_recent_orders(page=page, page_size=page_size)
    except Exception as e:
        print(f"Error getting orders data: {e}")
        return []

def render_alpaca_account_section():
    """The account surface: summary tiles, then positions and orders.

    Positions and orders are stacked full-width rather than sat side by side.
    They are both wide tables, and squeezing orders into a 5-column gutter was
    what forced the old cramped two-line-per-cell layout.
    """
    use_paper_str = get_alpaca_use_paper()
    is_paper = str(use_paper_str).strip().lower() not in ("false", "0", "no")
    account_mode_label = "Paper Trading" if is_paper else "Live Trading"

    refresh_button = html.Button(
        html.I(className="fas fa-rotate"),
        id="refresh-alpaca-btn",
        className="icon-btn",
        title="Refresh Alpaca account data",
    )

    return html.Div(
        [
            panel(
                html.Span(f"Alpaca {account_mode_label} Account", id="alpaca-account-title"),
                render_account_summary(),
                icon="fa-building-columns",
                actions=refresh_button,
            ),
            panel(
                "Open Positions",
                html.Div(id="positions-table-container", children=render_positions_table()),
                icon="fa-briefcase",
                flush=True,
            ),
            panel(
                "Recent Orders",
                [
                    dcc.Store(id="orders-page-store", data=1),
                    html.Div(id="orders-table-container", children=render_orders_table()),
                ],
                icon="fa-clock-rotate-left",
                flush=True,
            ),
            # Liquidation plumbing: the dialog and its result line.
            dcc.ConfirmDialog(id="liquidate-confirm", message=""),
            html.Div(id="liquidation-status", className="liquidation-status"),
        ],
        className="alpaca-account-section",
    )
