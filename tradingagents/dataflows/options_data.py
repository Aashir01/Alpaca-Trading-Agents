"""Options market data helpers.

Uses ``alpaca-py`` ``OptionHistoricalDataClient.get_option_chain`` to fetch
option chain snapshots (quotes, implied volatility, Greeks) for a given
underlying. Also maintains a local IV-history cache so IV rank/percentile can
be computed without a historical IV endpoint.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from .alpaca_utils import AlpacaUtils, get_alpaca_stock_client
from .config import get_api_key

_OPTION_SYMBOL_RE = re.compile(
    r"^(?P<underlying>[A-Z\.]{1,6})(?P<expiry>\d{6})(?P<type>[CP])(?P<strike>\d{8})$"
)


@dataclass
class OptionQuote:
    symbol: str
    underlying: str
    expiry: Optional[date]
    strike: Optional[float]
    option_type: Optional[str]  # call or put
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]
    iv: Optional[float]
    delta: Optional[float]
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]
    underlying_price: Optional[float]


@dataclass
class OptionsMarketContext:
    symbol: str
    spot: Optional[float]
    atm_iv: Optional[float]
    iv_rank: Optional[float]
    iv_percentile: Optional[float]
    hv_20: Optional[float]
    days_to_earnings: Optional[int]
    timestamp: str
    # Number of stored IV observations behind iv_rank/iv_percentile. Fewer than
    # ~20 and those figures are not yet meaningful; the prompt says so outright.
    iv_history_days: int = 0


def _parse_option_symbol(symbol: str) -> tuple[Optional[str], Optional[date], Optional[float], Optional[str]]:
    match = _OPTION_SYMBOL_RE.match(symbol)
    if not match:
        return None, None, None, None
    underlying = match.group("underlying")
    expiry_str = match.group("expiry")
    option_type = "call" if match.group("type") == "C" else "put"
    try:
        expiry = datetime.strptime(expiry_str, "%y%m%d").date()
    except ValueError:
        expiry = None
    try:
        strike = int(match.group("strike")) / 1000.0
    except ValueError:
        strike = None
    return underlying, expiry, strike, option_type


def _get_options_client() -> Any:
    from alpaca.data.historical import OptionHistoricalDataClient

    api_key = get_api_key("alpaca_api_key", "ALPACA_API_KEY")
    api_secret = get_api_key("alpaca_secret_key", "ALPACA_SECRET_KEY")
    if not api_key or not api_secret:
        raise ValueError("Alpaca API key or secret not found.")
    return OptionHistoricalDataClient(api_key, api_secret)


def _get_cache_dir(config: Optional[dict] = None) -> Path:
    if config is None:
        from ..default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG
    cache = Path(config.get("data_cache_dir", "tradingagents/dataflows/data_cache"))
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _iv_history_path(symbol: str, cache_dir: Path) -> Path:
    return cache_dir / "options_iv_history" / f"{symbol.upper()}.json"


def load_iv_history(symbol: str, cache_dir: Optional[Path] = None) -> dict[str, float]:
    if cache_dir is None:
        cache_dir = _get_cache_dir()
    path = _iv_history_path(symbol, cache_dir)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): float(v) for k, v in data.items() if v is not None}
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return {}


def save_iv_history(symbol: str, trade_date: str, atm_iv: float, cache_dir: Optional[Path] = None) -> None:
    if cache_dir is None:
        cache_dir = _get_cache_dir()
    path = _iv_history_path(symbol, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    history = load_iv_history(symbol, cache_dir)
    history[trade_date] = float(atm_iv)
    with path.open("w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def compute_iv_rank(atm_iv: float, history: Sequence[float]) -> tuple[Optional[float], Optional[float]]:
    """Return (iv_rank, iv_percentile) for ``atm_iv`` against a history series.

    These are two genuinely different statistics, and the strategy selection
    rules read both:

    * ``iv_rank`` is where current IV sits between the historical low and high,
      ``(iv - min) / (max - min) * 100``. It answers "is vol expensive relative
      to its own range?"
    * ``iv_percentile`` is the fraction of past observations below current IV
      (0-1), midpoint convention for ties. It answers "how often has vol been
      cheaper than this?"

    A series containing one extreme spike can show a low rank and a high
    percentile at the same time, which is precisely when selling premium on
    "high IV" would be a mistake.
    """
    if atm_iv is None:
        return None, None
    series = [float(h) for h in history if h is not None]
    if not series:
        return None, None

    low, high = min(series), max(series)
    if high > low:
        # Rounded because these values are rendered into prompts and persisted
        # as JSON, where a trailing 49.999999999999986 is just noise.
        iv_rank = round(max(0.0, min(100.0, (atm_iv - low) / (high - low) * 100.0)), 6)
    else:
        # Degenerate history (every observation identical): the range-based
        # rank is undefined, so report the neutral midpoint.
        iv_rank = 50.0

    n = len(series)
    lower = sum(1 for h in series if h < atm_iv)
    equal = sum(1 for h in series if h == atm_iv)
    iv_percentile = round((lower + equal / 2.0) / n, 6)

    return iv_rank, iv_percentile


def _option_snapshot_to_quote(
    symbol: str,
    snapshot: Any,
    underlying: str,
    spot: Optional[float],
) -> OptionQuote:
    quote = getattr(snapshot, "latest_quote", None) or snapshot
    greeks = getattr(snapshot, "greeks", None)

    bid = getattr(quote, "bid_price", None)
    ask = getattr(quote, "ask_price", None)
    last = getattr(snapshot, "latest_trade", None)
    if last is not None:
        last = getattr(last, "price", None)

    volume = getattr(snapshot, "latest_quote", None)
    if volume is not None:
        volume = getattr(volume, "bid_size", None)  # no real volume on quote; leave None

    parsed_underlying, expiry, strike, option_type = _parse_option_symbol(symbol)
    if parsed_underlying:
        underlying = parsed_underlying

    return OptionQuote(
        symbol=symbol,
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        bid=bid,
        ask=ask,
        last=last,
        volume=None,
        open_interest=None,
        iv=getattr(snapshot, "implied_volatility", None),
        delta=getattr(greeks, "delta", None) if greeks else None,
        gamma=getattr(greeks, "gamma", None) if greeks else None,
        theta=getattr(greeks, "theta", None) if greeks else None,
        vega=getattr(greeks, "vega", None) if greeks else None,
        underlying_price=spot,
    )


def get_option_chain_context(
    symbol: str,
    *,
    spot: Optional[float] = None,
    dte_min: int = 7,
    dte_max: int = 45,
    client: Optional[Any] = None,
) -> list[OptionQuote]:
    """Fetch near-the-money option chain quotes/Greeks for ``symbol``.

    Args:
        symbol: underlying ticker (e.g. ``AAPL``).
        spot: optional current underlying price; used to filter near-the-money.
        dte_min/dte_max: expiration window in days.
        client: optional ``OptionHistoricalDataClient`` for testing/injection.

    Returns:
        List of ``OptionQuote`` sorted by absolute distance from ``spot``.
    """
    if client is None:
        client = _get_options_client()

    from alpaca.data.requests import OptionChainRequest

    today = date.today()
    start = today + timedelta(days=dte_min)
    end = today + timedelta(days=dte_max)

    request = OptionChainRequest(
        underlying_symbol=symbol.upper(),
        expiration_date_gte=start,
        expiration_date_lte=end,
    )
    chain = client.get_option_chain(request)
    if not chain:
        return []

    quotes: list[OptionQuote] = []
    for opt_symbol, snapshot in chain.items():
        try:
            quote = _option_snapshot_to_quote(opt_symbol, snapshot, symbol, spot)
            quotes.append(quote)
        except Exception:
            # Skip malformed snapshots; never fail the whole chain because of one bad contract.
            continue

    if spot is not None:
        quotes = sort_chain_near_the_money(quotes, spot)
    return quotes


def sort_chain_near_the_money(quotes: list[OptionQuote], spot: float) -> list[OptionQuote]:
    """Order a chain by distance from the money, then by nearest expiry.

    Callers slice the head of this list as "near-the-money candidates", so the
    ordering is load-bearing: contracts with no strike sort last rather than
    being treated as zero-distance.
    """
    return sorted(
        quotes,
        key=lambda q: (
            abs(q.strike - spot) if q.strike is not None else float("inf"),
            q.expiry or date.max,
        ),
    )


def _select_atm_iv(chain: Sequence[OptionQuote], spot: Optional[float]) -> Optional[float]:
    """Return at-the-money implied volatility for the front expiry.

    Taking "the first contract that has an IV" off an unsorted chain can land on
    a deep out-of-the-money wing, whose IV is far from ATM because of skew. IV
    rank is computed from this number and drives strategy selection, so it has
    to be the real ATM.

    Picks the nearest expiry, then the strike closest to spot, then averages the
    call and put IV at that strike (the standard ATM convention - the two differ
    slightly through put/call parity and dividends).
    """
    candidates = [q for q in chain if q.iv is not None and q.iv > 0]
    if not candidates:
        return None

    if spot is None:
        # Without spot we cannot identify the money. The median IV of the chain
        # is a far better central estimate than an arbitrary contract.
        ivs = sorted(q.iv for q in candidates)
        return float(np.median(ivs))

    dated = [q for q in candidates if q.expiry is not None]
    if dated:
        front_expiry = min(q.expiry for q in dated)
        candidates = [q for q in dated if q.expiry == front_expiry]

    strikes = [q for q in candidates if q.strike is not None]
    if not strikes:
        return float(np.median(sorted(q.iv for q in candidates)))

    atm_strike = min(strikes, key=lambda q: abs(q.strike - spot)).strike
    at_strike = [q for q in strikes if q.strike == atm_strike]

    call_iv = next((q.iv for q in at_strike if q.option_type == "call"), None)
    put_iv = next((q.iv for q in at_strike if q.option_type == "put"), None)
    both = [iv for iv in (call_iv, put_iv) if iv is not None]
    if both:
        return float(sum(both) / len(both))
    return float(at_strike[0].iv)


def _annualized_hv(prices: pd.Series, window: int = 20) -> Optional[float]:
    if prices is None or len(prices) < window + 1:
        return None
    log_returns = np.log(prices / prices.shift(1))
    stdev = log_returns.tail(window).std()
    if pd.isna(stdev):
        return None
    return float(stdev * math.sqrt(252) * 100.0)


def get_options_market_context(
    symbol: str,
    *,
    spot: Optional[float] = None,
    trade_date: Optional[str] = None,
    dte_min: int = 7,
    dte_max: int = 45,
    client: Optional[Any] = None,
    config: Optional[dict] = None,
    chain_quotes: Optional[list[OptionQuote]] = None,
) -> tuple[OptionsMarketContext, list[OptionQuote]]:
    """Build the market context used by the options strategist.

    Includes ATM implied volatility, IV rank/percentile, 20-day historical
    volatility, and days-to-earnings. Returns the context plus the chain
    quotes used to build it (so callers can reuse them for the risk gate and
    prompt without another API round trip).
    """
    if spot is None:
        spot = _fetch_spot(symbol)

    chain = chain_quotes if chain_quotes is not None else get_option_chain_context(
        symbol,
        spot=spot,
        dte_min=dte_min,
        dte_max=dte_max,
        client=client,
    )

    # A chain supplied by the caller may have been fetched before spot was
    # known, and therefore be unsorted. Sort it here so "near the money" is
    # true for both ATM IV selection and the candidates shown to the LLM.
    if spot is not None and chain:
        chain = sort_chain_near_the_money(chain, spot)

    atm_iv = _select_atm_iv(chain, spot) if chain else None

    if trade_date is None:
        trade_date = datetime.now().date().isoformat()

    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    history_days = 0
    if atm_iv is not None:
        history = load_iv_history(symbol)
        # Rank against history as it stood *before* today, so the current
        # observation cannot rank itself.
        prior = [v for k, v in history.items() if str(k) != str(trade_date)]
        history_days = len(prior)
        iv_rank, iv_percentile = compute_iv_rank(atm_iv, prior)
        save_iv_history(symbol, str(trade_date), atm_iv)

    hv_20 = _fetch_hv_20(symbol)
    days_to_earnings = _fetch_days_to_earnings(symbol, config)

    context = OptionsMarketContext(
        symbol=symbol,
        spot=spot,
        atm_iv=atm_iv,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        hv_20=hv_20,
        days_to_earnings=days_to_earnings,
        timestamp=datetime.now().isoformat(),
        iv_history_days=history_days,
    )
    return context, chain


def _fetch_spot(symbol: str) -> Optional[float]:
    """Best-effort spot price via the existing Alpaca stock quote path.

    Reuses ``AlpacaUtils.get_latest_quote``, which already returns a normalized
    dict. Spot drives near-the-money chain sorting and ATM IV selection, so a
    failure here silently degrades strike selection - it is logged, not
    swallowed.
    """
    try:
        quote = AlpacaUtils.get_latest_quote(symbol.upper())
    except Exception as exc:
        print(f"[options_data] spot lookup failed for {symbol}: {exc}")
        return None

    if not quote:
        print(f"[options_data] no quote returned for {symbol}; spot unavailable")
        return None

    bid = quote.get("bid_price")
    ask = quote.get("ask_price")
    prices = [float(p) for p in (bid, ask) if p not in (None, 0)]
    if not prices:
        print(f"[options_data] quote for {symbol} had no usable bid/ask")
        return None
    return sum(prices) / len(prices)


def fetch_spot_price(symbol: str) -> Optional[float]:
    """Public spot-price lookup for callers that need it before the chain.

    Strike selection depends on knowing where the money is, so the strategist
    resolves spot first and threads it through both the chain fetch and the
    market-context build.
    """
    return _fetch_spot(symbol)


def _fetch_hv_20(symbol: str) -> Optional[float]:
    """20-day annualized historical volatility from Alpaca daily bars."""
    try:
        end = datetime.now()
        start = end - timedelta(days=60)
        bars = get_alpaca_stock_client().get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbol.upper(),
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
            )
        )
        if bars is None or bars.df.empty:
            return None
        prices = bars.df["close"].dropna()
        return _annualized_hv(prices, window=20)
    except Exception as exc:
        # The default feed is SIP, which a free data plan may not query for
        # recent bars ("subscription does not permit querying recent SIP
        # data"). IEX is available on every plan and is accurate enough for a
        # 20-day volatility estimate, so fall back rather than returning None:
        # without HV the strategist has nothing to compare implied vol against.
        if "SIP" in str(exc) or "subscription" in str(exc).lower():
            try:
                from alpaca.data.enums import DataFeed

                bars = get_alpaca_stock_client().get_stock_bars(
                    StockBarsRequest(
                        symbol_or_symbols=symbol.upper(),
                        timeframe=TimeFrame.Day,
                        start=start,
                        end=end,
                        feed=DataFeed.IEX,
                    )
                )
                if bars is not None and not bars.df.empty:
                    return _annualized_hv(bars.df["close"].dropna(), window=20)
            except Exception as iex_exc:
                exc = iex_exc
        print(f"[options_data] HV-20 lookup failed for {symbol}: {exc}")
        return None


def _fetch_days_to_earnings(symbol: str, config: Optional[dict]) -> Optional[int]:
    """Days until the next scheduled earnings date, via Finnhub.

    This previously called get_earnings_calendar_data(symbol=..., config=...),
    which takes neither argument and returns a formatted string rather than a
    mapping. The bare except swallowed the TypeError, so earnings proximity was
    silently always None -- and an options desk that cannot see an upcoming
    print will happily sell premium straight into an IV crush.
    """
    if "/" in symbol:          # crypto has no earnings
        return None
    try:
        from .finnhub_utils import get_finnhub_client

        client = get_finnhub_client()
        if client is None:
            return None
        today = date.today()
        calendar = client.earnings_calendar(
            _from=today.isoformat(),
            to=(today + timedelta(days=120)).isoformat(),
            symbol=symbol.upper(),
        )
        entries = (calendar or {}).get("earningsCalendar") or []
        upcoming = []
        for entry in entries:
            raw = entry.get("date")
            if not raw:
                continue
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                continue
            if parsed >= today:
                upcoming.append(parsed)
        if upcoming:
            return (min(upcoming) - today).days
    except Exception as exc:
        print(f"[options_data] earnings lookup failed for {symbol}: {exc}")
    return None


