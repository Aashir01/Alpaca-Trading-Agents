# -------------------------------- charts.py -----------------------
"""Plotly figure builders for the trading desk.

Every figure in the app is built here so the whole dashboard reads as one
system: one theme, one categorical palette, one empty state, one hover
convention. Two rules from the house data-viz standard are load-bearing and
are worth stating because breaking them is easy:

* **No dual y-axes.** Price and volume live in stacked subplot rows sharing
  one x-axis, never overlaid on two scales -- overlaying invents a
  correlation the data does not contain.
* **The categorical palette is validated, not eyeballed.** ``PALETTE`` below
  clears the lightness band, chroma floor, CVD separation, normal-vision and
  contrast checks against this app's near-black surface.

Up/down colours (``POS``/``NEG``) are a *polarity* encoding, not categorical:
green-up / red-down is a domain convention and is deliberately kept distinct
from the categorical slots so a series colour can never impersonate a P/L sign.
"""

import random
from datetime import datetime, timedelta
from typing import Union

import pandas as pd
import plotly.graph_objects as go
import pytz
from plotly.subplots import make_subplots

from tradingagents.dataflows.alpaca_utils import AlpacaUtils

# --------------------------------------------------------------- tokens ---
# These mirror the custom properties in webui/assets/dashboard.css. Charts sit
# inside the app shell, so a stock plotly template would punch a lit rectangle
# through a true-black page.

BG = "#000000"
SURFACE = "#0A0A0C"
SURFACE_2 = "#131318"
GRID = "#1F1F27"
BORDER = "#26262E"
TEXT = "#F4F5F7"
TEXT_DIM = "#A0A0AD"
TEXT_FAINT = "#6E6E7C"

ACCENT = "#4F8DFD"
POS = "#22D07F"
NEG = "#FF5F5F"
WARN = "#FFB020"
OPTIONS = "#A78BFA"

# Validated categorical palette (dark mode, surface #0A0A0C). Assigned in this
# fixed order and never cycled: a ninth series folds into "Other".
PALETTE = [
    "#4F8DFD",  # blue      (brand accent)
    "#d95926",  # orange
    "#199e70",  # aqua
    "#c98500",  # yellow
    "#d55181",  # magenta
    "#008300",  # green
    "#9085e9",  # violet
    "#e66767",  # red
]

FONT = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
MONO = "JetBrains Mono, SF Mono, Menlo, Consolas, monospace"

CHART_THEME = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=TEXT_DIM, family=FONT, size=12),
    title_font=dict(color=TEXT, size=14),
    legend=dict(font=dict(size=11, color=TEXT_DIM), bgcolor="rgba(0,0,0,0)"),
    hoverlabel=dict(
        bgcolor=SURFACE_2,
        bordercolor=BORDER,
        font=dict(color=TEXT, size=12, family=FONT),
    ),
    hovermode="x unified",
    margin=dict(l=52, r=18, t=18, b=34),
    dragmode="pan",
)

# Gridlines and axis rules are solid hairlines one shade off the surface --
# dashed grid reads as "threshold" when it is only chrome.
_AXIS_THEME = dict(
    gridcolor=GRID,
    zerolinecolor=BORDER,
    linecolor=BORDER,
    tickfont=dict(size=11, color=TEXT_FAINT),
    title_font=dict(size=11.5, color=TEXT_FAINT),
)

# Toolbars are noise on a dashboard tile; the analysis chart keeps its own.
STATIC_CONFIG = {"displayModeBar": False, "responsive": True}
INTERACTIVE_CONFIG = {
    "displayModeBar": "hover",
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
}


def apply_chart_theme(fig):
    """Apply the shared dark theme without clobbering per-chart axis settings."""
    fig.update_layout(**CHART_THEME)
    fig.update_xaxes(**_AXIS_THEME)
    fig.update_yaxes(**_AXIS_THEME)
    return fig


# Kept for callers that imported the private name before this module grew up.
_apply_chart_theme = apply_chart_theme


def empty_figure(message, hint=None, height=None):
    """The one empty state every chart in the app uses.

    An empty chart says why it is empty. Rendering a confident zero line for
    an account we could not reach would be worse than saying nothing.
    """
    fig = go.Figure()
    text = f"<b>{message}</b>"
    if hint:
        text += f"<br><span style='font-size:11.5px'>{hint}</span>"
    fig.add_annotation(
        text=text,
        showarrow=False,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        font=dict(color=TEXT_FAINT, size=13, family=FONT),
        align="center",
    )
    fig.update_layout(**{**CHART_THEME, "hovermode": False})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    if height:
        fig.update_layout(height=height)
    return fig


def _tone(value):
    """Colour for a signed number, on the up/down polarity scale."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return TEXT_DIM
    return POS if value > 0 else (NEG if value < 0 else TEXT_DIM)


def _rgba(hex_color, alpha):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# ------------------------------------------------------- price / candles ---

_PERIOD_MAP = {
    "15m": ("15Min", timedelta(days=5)),
    "1d": ("5Min", timedelta(days=2)),
    "1w": ("30Min", timedelta(days=10)),
    "1mo": ("1Hour", timedelta(days=45)),
    "1y": ("1Day", timedelta(days=365)),
}

_PERIOD_TITLES = {
    "15m": "15 Minutes",
    "1d": "1 Day",
    "1w": "1 Week",
    "1mo": "1 Month",
    "1y": "1 Year",
}


def _rangebreaks(ticker, period):
    """Collapse the hours the market is shut so candles are not stretched."""
    if "/" in str(ticker):  # crypto trades continuously
        return []
    if period in ("15m", "1d"):
        return [
            dict(bounds=["sat", "mon"]),
            dict(bounds=[20, 9.5], pattern="hour"),
        ]
    if period in ("1w", "1mo"):
        return [dict(bounds=["sat", "mon"])]
    return []


def _ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def _price_figure(ticker, period, timestamps, opens, highs, lows, closes, volumes,
                  subtitle=None, demo_note=None):
    """Candles over their own volume row -- one shared x-axis, never two y-scales.

    The volume row is a separate subplot rather than an overlay: overlaying
    volume on a second y-axis lets the reader infer a price/volume alignment
    that is an artifact of two arbitrary scales.
    """
    closes = pd.Series(list(closes), dtype="float64")
    opens_s = pd.Series(list(opens), dtype="float64")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.76, 0.24],
    )

    fig.add_trace(
        go.Candlestick(
            x=timestamps,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name="Price",
            increasing=dict(line=dict(color=POS, width=1), fillcolor=POS),
            decreasing=dict(line=dict(color=NEG, width=1), fillcolor=NEG),
            showlegend=False,
            hoverlabel=dict(namelength=0),
        ),
        row=1,
        col=1,
    )

    # Moving averages are the reason a trader looks at a chart at all; they are
    # only drawn once enough bars exist to make them meaningful.
    for span, colour in ((20, ACCENT), (50, OPTIONS)):
        if len(closes) >= span:
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=_ema(closes, span),
                    mode="lines",
                    name=f"EMA {span}",
                    line=dict(color=colour, width=1.4),
                    hovertemplate="EMA " + str(span) + " %{y:,.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

    # Volume bars inherit the candle's direction so the two rows read together.
    bar_colors = [
        _rgba(POS if c >= o else NEG, 0.5)
        for c, o in zip(closes, opens_s)
    ]
    fig.add_trace(
        go.Bar(
            x=timestamps,
            y=list(volumes),
            name="Volume",
            marker=dict(color=bar_colors, line=dict(width=0)),
            showlegend=False,
            hovertemplate="Vol %{y:,.0f}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    breaks = _rangebreaks(ticker, period)
    fig.update_xaxes(
        type="date",
        rangeslider_visible=False,
        rangebreaks=breaks,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor=BORDER,
        spikethickness=1,
        spikedash="solid",
        row=1,
        col=1,
    )
    fig.update_xaxes(type="date", rangebreaks=breaks, row=2, col=1)
    fig.update_yaxes(title_text="Price", tickprefix="$", side="right", row=1, col=1)
    fig.update_yaxes(title_text="Volume", side="right", showgrid=False,
                     tickformat=".2s", row=2, col=1)

    fig.update_layout(
        height=420,
        autosize=True,
        bargap=0.12,
        legend=dict(orientation="h", yanchor="middle", y=1.055,
                    xanchor="left", x=0, font=dict(size=11)),
        margin=dict(l=10, r=56, t=40, b=28),
    )
    apply_chart_theme(fig)
    # apply_chart_theme resets shared layout keys; restore the ones this
    # figure sets deliberately.
    fig.update_layout(
        margin=dict(l=10, r=56, t=40, b=28),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="middle", y=1.055,
                    xanchor="left", x=0, font=dict(size=11, color=TEXT_DIM)),
    )

    # The panel head and the caption line above the plot already name the
    # symbol, so the header strip carries only what the chart itself knows:
    # the legend on the left, the period's price move on the right. Both sit
    # on one line so neither can collide with the other.
    period_label = _PERIOD_TITLES.get(period, period)
    if subtitle:
        period_label += f" · {subtitle}"
    right_text = f"<span style='color:{TEXT_FAINT}'>{period_label}</span>"
    if len(closes) >= 2:
        last, first = float(closes.iloc[-1]), float(closes.iloc[0])
        change = last - first
        pct = (change / first * 100) if first else 0.0
        right_text = (
            f"<b>${last:,.2f}</b>  "
            f"<span style='color:{_tone(change)}'>{change:+,.2f} ({pct:+.2f}%)</span>  "
            f"<span style='color:{TEXT_FAINT}'>{period_label}</span>"
        )
    fig.add_annotation(
        text=right_text,
        xref="paper", yref="paper", x=1, y=1.055,
        showarrow=False, xanchor="right", yanchor="middle",
        font=dict(color=TEXT, size=12.5, family=FONT),
    )

    if demo_note:
        fig.add_annotation(
            x=0.5, y=0.06, xref="paper", yref="paper",
            text=f"DEMO DATA: {demo_note}", showarrow=False,
            font=dict(color=NEG, size=11),
            bgcolor=_rgba(SURFACE_2, 0.92), bordercolor=NEG, borderwidth=1,
            borderpad=5,
        )
    return fig


def create_chart(ticker: str, period: str = "1y", end_date: Union[str, datetime] = None):
    """Candlestick + volume chart for a ticker, with a demo-data fallback."""
    now_utc = datetime.now(pytz.UTC)
    if end_date:
        end_dt = pd.to_datetime(end_date)
        end_dt = end_dt.tz_localize(pytz.UTC) if end_dt.tzinfo is None else end_dt
    else:
        end_dt = now_utc

    tf_str, delta = _PERIOD_MAP.get(period, _PERIOD_MAP["1y"])
    start_dt = end_dt - delta

    df = AlpacaUtils.get_stock_data(
        symbol=ticker, start_date=start_dt, end_date=end_dt, timeframe=tf_str
    )

    if df.empty:
        return create_demo_chart(
            ticker, period, end_date, error_msg="No data returned from Alpaca API."
        )

    subtitle = f"as of {pd.to_datetime(end_date).date()}" if end_date else None
    return _price_figure(
        ticker, period,
        df["timestamp"], df["open"], df["high"], df["low"], df["close"], df["volume"],
        subtitle=subtitle,
    )


def create_demo_chart(ticker, period="1y", end_date=None, error_msg=None):
    """Random-walk stand-in, shown only when the data feed returns nothing."""
    points_map = {"15m": 160, "1d": 96, "1w": 48, "1mo": 90, "1y": 252}
    points = points_map.get(period, 252)

    end_dt = pd.to_datetime(end_date) if end_date else datetime.now()
    dates = pd.date_range(end=end_dt, periods=points)
    prices = [100 + random.uniform(-20, 20)]
    for _ in range(1, points):
        prices.append(max(5, prices[-1] + random.uniform(-2, 2) + random.uniform(-0.5, 0.7)))

    closes = prices
    opens, highs, lows, vols = [], [], [], []
    for i, close in enumerate(closes):
        open_ = closes[i - 1] if i > 0 else close
        opens.append(open_)
        highs.append(max(open_, close) + random.uniform(0.1, 1))
        lows.append(min(open_, close) - random.uniform(0.1, 1))
        vols.append(random.randint(100_000, 10_000_000))

    subtitle = f"as of {pd.to_datetime(end_date).date()}" if end_date else None
    return _price_figure(
        ticker, period, dates, opens, highs, lows, closes, vols,
        subtitle=subtitle, demo_note=error_msg or "live data unavailable",
    )


def create_welcome_chart():
    """Placeholder shown on the analysis page before a symbol is chosen."""
    return empty_figure(
        "No symbol selected",
        "Add a ticker above, then press Start Analysis to load its chart",
        height=420,
    )


# ------------------------------------------------------------- equity ------

def create_equity_curve(points, baseline=None, label="Portfolio equity"):
    """Account equity over time as a single filled line.

    ``points`` is a sequence of ``(datetime, equity)``. The fill and line take
    the polarity colour of the period's net change, so the shape of the curve
    and its colour say the same thing.
    """
    points = [(t, v) for t, v in (points or []) if v is not None]
    if len(points) < 2:
        return empty_figure(
            "Not enough portfolio history",
            "Alpaca reports equity once the account has a funded trading day",
        )

    times = [p[0] for p in points]
    values = [float(p[1]) for p in points]
    start = baseline if baseline not in (None, 0) else values[0]
    change = values[-1] - start
    colour = POS if change >= 0 else NEG

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=times,
            y=values,
            mode="lines",
            name=label,
            line=dict(color=colour, width=2, shape="linear"),
            fill="tozeroy",
            fillcolor=_rgba(colour, 0.10),
            hovertemplate="%{x|%b %d, %H:%M}<br><b>$%{y:,.2f}</b><extra></extra>",
        )
    )

    # The opening equity is the reference the eye needs to read the curve.
    fig.add_hline(
        y=start,
        line=dict(color=BORDER, width=1, dash="dot"),
        annotation_text=f"open ${start:,.0f}",
        annotation_position="top left",
        annotation_font=dict(color=TEXT_FAINT, size=10.5),
    )

    # One direct label on the endpoint, rather than a number on every point.
    fig.add_trace(
        go.Scatter(
            x=[times[-1]],
            y=[values[-1]],
            mode="markers",
            marker=dict(color=colour, size=8, line=dict(color=BG, width=2)),
            showlegend=False,
            hoverinfo="skip",
        )
    )

    low, high = min(values), max(values)
    pad = max((high - low) * 0.12, high * 0.0015, 1.0)
    fig.update_yaxes(range=[low - pad, high + pad], tickprefix="$", tickformat=",.0f")
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikecolor=BORDER, spikethickness=1, spikedash="solid")
    fig.update_layout(autosize=True, showlegend=False,
                      margin=dict(l=62, r=18, t=14, b=30))
    apply_chart_theme(fig)
    fig.update_layout(margin=dict(l=62, r=18, t=14, b=30))
    return fig


def create_sparkline(values, positive=None):
    """Tiny trend line for a KPI tile -- no axes, no hover, no chrome."""
    values = [float(v) for v in (values or []) if v is not None]
    fig = go.Figure()
    if len(values) < 2:
        fig.update_layout(**{**CHART_THEME, "hovermode": False})
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(height=38, margin=dict(l=0, r=0, t=0, b=0))
        return fig

    if positive is None:
        positive = values[-1] >= values[0]
    colour = POS if positive else NEG
    fig.add_trace(
        go.Scatter(
            x=list(range(len(values))),
            y=values,
            mode="lines",
            line=dict(color=colour, width=1.6),
            fill="tozeroy",
            fillcolor=_rgba(colour, 0.09),
            hoverinfo="skip",
        )
    )
    low, high = min(values), max(values)
    pad = max((high - low) * 0.15, 0.0001)
    fig.update_layout(**{**CHART_THEME, "hovermode": False})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, range=[low - pad, high + pad])
    fig.update_layout(height=38, margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
    return fig


# ------------------------------------------------------ portfolio shape ----

def create_allocation_donut(slices, total_label="Allocated"):
    """Part-to-whole of the book. ``slices`` is ``[(label, value), ...]``.

    Capped at six segments (five holdings plus a rolled-up tail) because past
    that, adjacent wedges stop being separable at a glance.
    """
    slices = [(str(label), abs(float(value))) for label, value in (slices or []) if value]
    slices = [s for s in slices if s[1] > 0]
    if not slices:
        return empty_figure("No allocation data", "Positions and cash appear here once the account is funded")

    slices.sort(key=lambda item: -item[1])
    if len(slices) > 6:
        tail = sum(value for _, value in slices[5:])
        slices = slices[:5] + [("Other", tail)]

    labels = [label for label, _ in slices]
    values = [value for _, value in slices]
    total = sum(values)

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.66,
            sort=False,
            direction="clockwise",
            marker=dict(
                colors=PALETTE[: len(labels)],
                # A 2px surface gap, not a border, separates the wedges.
                line=dict(color=BG, width=2),
            ),
            # Percent labels are the secondary encoding that keeps the wedges
            # readable without relying on hue alone.
            textinfo="percent",
            textposition="outside",
            textfont=dict(color=TEXT_DIM, size=11, family=FONT),
            hovertemplate="<b>%{label}</b><br>$%{value:,.2f} · %{percent}<extra></extra>",
        )
    )
    fig.update_layout(
        height=320,
        showlegend=True,
        legend=dict(orientation="v", x=1.02, xanchor="left", y=0.5,
                    font=dict(size=11, color=TEXT_DIM), itemsizing="constant"),
        margin=dict(l=8, r=8, t=10, b=10),
        annotations=[dict(
            text=(f"<b>${total:,.0f}</b><br>"
                  f"<span style='font-size:10.5px;color:{TEXT_FAINT}'>{total_label}</span>"),
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=18, color=TEXT, family=FONT),
        )],
    )
    apply_chart_theme(fig)
    fig.update_layout(
        margin=dict(l=8, r=8, t=10, b=10),
        hovermode="closest",
        annotations=[dict(
            text=(f"<b>${total:,.0f}</b><br>"
                  f"<span style='font-size:10.5px;color:{TEXT_FAINT}'>{total_label}</span>"),
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=18, color=TEXT, family=FONT),
        )],
    )
    return fig


def create_pl_bars(rows, value_key="pl", label_key="symbol", title_prefix="Unrealized"):
    """Per-position P/L as diverging horizontal bars around a zero rule.

    Colour here is polarity (made money / lost money), which is exactly what
    the bar's direction already says -- so the two reinforce rather than
    compete, and no legend is needed for a single measure.
    """
    rows = [r for r in (rows or []) if r.get(value_key) is not None]
    if not rows:
        return empty_figure("No open positions", "Position-level P/L appears once the desk holds something")

    rows = sorted(rows, key=lambda r: float(r[value_key]))
    if len(rows) > 12:  # keep the largest movers in both directions
        rows = rows[:6] + rows[-6:]

    labels = [str(r[label_key]) for r in rows]
    values = [float(r[value_key]) for r in rows]
    colours = [POS if v >= 0 else NEG for v in values]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colours, line=dict(width=0)),
            hovertemplate="<b>%{y}</b><br>" + title_prefix + " $%{x:,.2f}<extra></extra>",
            text=[f"{v:+,.0f}" for v in values],
            textposition="outside",
            textfont=dict(color=TEXT_DIM, size=10.5, family=MONO),
            cliponaxis=False,
        )
    )
    fig.add_vline(x=0, line=dict(color=BORDER, width=1))
    span = max((abs(v) for v in values), default=1) or 1
    fig.update_xaxes(range=[-span * 1.35, span * 1.35], tickprefix="$", tickformat=",.0f")
    fig.update_yaxes(tickfont=dict(family=MONO, size=11, color=TEXT_DIM))
    fig.update_layout(
        height=max(190, 34 * len(rows) + 60),
        showlegend=False,
        bargap=0.35,
        margin=dict(l=8, r=18, t=12, b=30),
    )
    apply_chart_theme(fig)
    fig.update_layout(margin=dict(l=8, r=18, t=12, b=30), hovermode="closest")
    fig.update_yaxes(tickfont=dict(family=MONO, size=11, color=TEXT_DIM), automargin=True)
    return fig


def create_exposure_bar(long_value, short_value, cash_value):
    """Where the equity currently sits: long, short, and uninvested cash.

    One stacked row rather than three donuts -- the question is proportion of a
    single total, and a stacked bar answers it without three separate baselines.
    """
    segments = [
        ("Long", abs(float(long_value or 0)), PALETTE[2]),
        ("Short", abs(float(short_value or 0)), PALETTE[1]),
        ("Cash", abs(float(cash_value or 0)), PALETTE[0]),
    ]
    total = sum(value for _, value, _ in segments)
    if total <= 0:
        return empty_figure("No exposure to show", "Connect Alpaca to see how the equity is deployed")

    fig = go.Figure()
    for name, value, colour in segments:
        if value <= 0:
            continue
        fig.add_trace(
            go.Bar(
                x=[value],
                y=["Book"],
                name=name,
                orientation="h",
                marker=dict(color=colour, line=dict(color=BG, width=2)),
                hovertemplate=f"<b>{name}</b><br>$%{{x:,.2f}}"
                              f"<br>{value / total:.1%} of book<extra></extra>",
                text=[f"{name} {value / total:.0%}" if value / total > 0.14 else ""],
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(color="#08110C", size=11, family=FONT),
            )
        )

    fig.update_layout(
        barmode="stack",
        height=132,
        bargap=0.55,
        showlegend=True,
        legend=dict(orientation="h", y=-0.55, x=0, font=dict(size=11, color=TEXT_DIM)),
        margin=dict(l=8, r=12, t=8, b=8),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    apply_chart_theme(fig)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(
        margin=dict(l=8, r=12, t=8, b=8),
        hovermode="closest",
        legend=dict(orientation="h", y=-0.35, x=0, font=dict(size=11, color=TEXT_DIM)),
    )
    return fig


# ---------------------------------------------------------- agent output ---

# BUY/SELL/HOLD is a state, not an identity, so it wears the reserved status
# colours -- the same green/red/grey the P/L numbers use everywhere else.
SIGNAL_COLORS = {"BUY": POS, "SELL": NEG, "HOLD": TEXT_FAINT}


def create_signal_history(per_date):
    """Agent decisions over time, stacked by action.

    ``per_date`` is ``{date: {"BUY": n, "SELL": n, "HOLD": n}}``.
    """
    dates = sorted(per_date or {})
    if not dates:
        return empty_figure(
            "No recorded decisions yet",
            "Completed analyses are logged under eval_results/ and charted here",
        )

    fig = go.Figure()
    for action in ("BUY", "HOLD", "SELL"):
        counts = [int((per_date[d] or {}).get(action, 0)) for d in dates]
        if not any(counts):
            continue
        fig.add_trace(
            go.Bar(
                x=dates,
                y=counts,
                name=action,
                marker=dict(color=SIGNAL_COLORS[action], line=dict(color=BG, width=2)),
                hovertemplate=f"<b>{action}</b><br>%{{x}}<br>%{{y}} run(s)<extra></extra>",
            )
        )

    fig.update_layout(
        barmode="stack",
        height=250,
        bargap=0.62,
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11, color=TEXT_DIM)),
        margin=dict(l=40, r=16, t=32, b=34),
    )
    # Trading days, not calendar days: a date axis would stretch three runs
    # across eight months of empty weekends and holidays.
    apply_chart_theme(fig)
    # Trading days, not calendar days: a date axis would stretch three runs
    # across eight months of empty weekends and holidays. Set after the theme
    # pass so the category type is not reset back to a date axis.
    fig.update_xaxes(type="category", tickangle=0, showgrid=False)
    fig.update_yaxes(title_text="Runs", rangemode="tozero", tickformat="d")
    fig.update_layout(
        margin=dict(l=40, r=16, t=32, b=34),
        legend=dict(orientation="h", y=1.14, x=0, font=dict(size=11, color=TEXT_DIM)),
    )
    return fig


# --------------------------------------------------------------- options ---

def _leg_intrinsic(leg, spot):
    """Value of one contract leg at expiry, per share, signed by side."""
    strike = leg.get("strike")
    option_type = str(leg.get("option_type") or "").lower()
    if strike is None or option_type not in ("call", "put"):
        return None
    strike = float(strike)
    intrinsic = max(0.0, spot - strike) if option_type == "call" else max(0.0, strike - spot)
    sign = -1.0 if str(leg.get("side") or "buy").lower() == "sell" else 1.0
    return sign * float(leg.get("ratio_qty") or 1) * intrinsic


def create_payoff_diagram(legs, net_premium, contracts=1, spot=None, strategy=""):
    """Profit/loss of the proposed structure at expiry, across underlying price.

    Computed from the legs and the *gate's* recomputed net premium, not the
    model's own estimate -- so what is drawn is what the deterministic gate
    priced. Positive ``net_premium`` is a debit paid, negative is a credit
    received, matching ``RiskGateResult.net_credit_debit``.
    """
    legs = [leg for leg in (legs or []) if leg.get("strike") is not None]
    if not legs:
        return empty_figure(
            "No structure to plot",
            "A payoff curve is drawn once the strategist proposes priced legs",
        )

    strikes = [float(leg["strike"]) for leg in legs]
    low = min(strikes) * 0.82
    high = max(strikes) * 1.18
    if spot:
        low = min(low, float(spot) * 0.82)
        high = max(high, float(spot) * 1.18)
    step = (high - low) / 220 or 1.0

    prices, payoffs = [], []
    price = low
    multiplier = 100.0 * float(contracts or 1)
    while price <= high:
        legs_value = 0.0
        for leg in legs:
            value = _leg_intrinsic(leg, price)
            if value is None:
                return empty_figure("Structure not priceable", "Legs are missing a strike or option type")
            legs_value += value
        prices.append(price)
        payoffs.append((legs_value - float(net_premium or 0.0)) * multiplier)
        price += step

    fig = go.Figure()
    # Two clipped fills, so profit and loss regions read at a glance without
    # colouring a single line two ways.
    fig.add_trace(
        go.Scatter(
            x=prices, y=[max(0.0, p) for p in payoffs],
            mode="lines", line=dict(width=0), fill="tozeroy",
            fillcolor=_rgba(POS, 0.16), hoverinfo="skip", showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=prices, y=[min(0.0, p) for p in payoffs],
            mode="lines", line=dict(width=0), fill="tozeroy",
            fillcolor=_rgba(NEG, 0.16), hoverinfo="skip", showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=prices, y=payoffs, mode="lines", name="P/L at expiry",
            line=dict(color=ACCENT, width=2),
            hovertemplate="Underlying $%{x:,.2f}<br><b>P/L $%{y:,.2f}</b><extra></extra>",
        )
    )
    fig.add_hline(y=0, line=dict(color=BORDER, width=1))

    # Breakevens are the first number a trader looks for on a payoff curve, so
    # they are marked rather than left to be read off the axis. They are found
    # by scanning the computed curve for sign changes -- one rule that works
    # for every structure, instead of a formula per strategy.
    for index in range(1, len(payoffs)):
        previous, current = payoffs[index - 1], payoffs[index]
        if (previous < 0 <= current) or (previous > 0 >= current):
            span = current - previous
            fraction = (-previous / span) if span else 0.0
            crossing = prices[index - 1] + fraction * (prices[index] - prices[index - 1])
            fig.add_annotation(
                x=crossing, y=0,
                text=f"BE {crossing:,.2f}",
                showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=TEXT_FAINT,
                ax=0, ay=-26,
                font=dict(color=TEXT_DIM, size=10, family=MONO),
            )

    for strike in sorted(set(strikes)):
        fig.add_vline(
            x=strike,
            line=dict(color=OPTIONS, width=1, dash="dot"),
            annotation_text=f"{strike:g}",
            annotation_position="top",
            annotation_font=dict(color=OPTIONS, size=10),
        )
    if spot:
        fig.add_vline(
            x=float(spot),
            line=dict(color=WARN, width=1.4),
            annotation_text=f"spot {float(spot):,.2f}",
            annotation_position="bottom right",
            annotation_font=dict(color=WARN, size=10),
        )

    fig.update_xaxes(title_text="Underlying price at expiry", tickprefix="$")
    fig.update_yaxes(title_text="Profit / loss", tickprefix="$", tickformat=",.0f")
    fig.update_layout(
        height=320, showlegend=False,
        margin=dict(l=62, r=18, t=30, b=42),
    )
    apply_chart_theme(fig)
    fig.update_layout(margin=dict(l=62, r=18, t=30, b=42))
    if strategy:
        fig.add_annotation(
            text=f"<b>{str(strategy).replace('_', ' ').title()}</b> · {contracts:g} contract(s)",
            xref="paper", yref="paper", x=0, y=1.1, showarrow=False, xanchor="left",
            font=dict(color=TEXT_DIM, size=11.5, family=FONT),
        )
    return fig


def create_dte_chart(rows):
    """Days-to-expiry runway for open option positions.

    ``rows`` is ``[{"symbol": str, "dte": int, "pl": float}, ...]``. Bar length
    is time remaining; the P/L sign rides in the tooltip rather than the hue,
    so the one visual channel encodes the one thing the chart is about.
    """
    rows = [r for r in (rows or []) if r.get("dte") is not None]
    if not rows:
        return empty_figure("No open option contracts", "Expiry runway appears once a spread is filled")

    rows = sorted(rows, key=lambda r: -int(r["dte"]))[:12]
    labels = [str(r["symbol"]) for r in rows]
    dtes = [int(r["dte"]) for r in rows]

    fig = go.Figure(
        go.Bar(
            x=dtes, y=labels, orientation="h",
            marker=dict(color=OPTIONS, line=dict(width=0)),
            text=[f"{d}d" for d in dtes],
            textposition="outside",
            textfont=dict(color=TEXT_DIM, size=10.5, family=MONO),
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{x} days to expiry<extra></extra>",
        )
    )
    fig.update_xaxes(title_text="Days to expiry", rangemode="tozero")
    fig.update_yaxes(tickfont=dict(family=MONO, size=10.5, color=TEXT_DIM), automargin=True)
    fig.update_layout(
        height=max(180, 32 * len(rows) + 62), showlegend=False, bargap=0.38,
        margin=dict(l=8, r=30, t=10, b=36),
    )
    apply_chart_theme(fig)
    fig.update_layout(margin=dict(l=8, r=30, t=10, b=36), hovermode="closest")
    fig.update_yaxes(tickfont=dict(family=MONO, size=10.5, color=TEXT_DIM), automargin=True)
    return fig
