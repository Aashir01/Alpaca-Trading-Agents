"""Options market data helpers.

Uses ``alpaca-py`` ``OptionHistoricalDataClient.get_option_chain`` to fetch
option chain snapshots (quotes, implied volatility, Greeks) for a given
underlying. Also maintains a local IV-history cache so IV rank/percentile can
be computed without a historical IV endpoint.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest

from .alpaca_utils import get_alpaca_stock_client, get_alpaca_trading_client
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

    ``iv_rank`` is the percentile rank 0-100 of the current IV in the history.
    ``iv_percentile`` is the same value expressed 0-1.
    """
    if not history or atm_iv is None:
        return None, None
    lower_count = sum(1 for h in history if h < atm_iv)
    equal_count = sum(1 for h in history if h == atm_iv)
    n = len(history)
    if n == 0:
        return None, None
    rank = (lower_count + equal_count / 2.0) / n * 100.0
    return rank, rank / 100.0


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
        quotes.sort(key=lambda q: (abs((q.strike or 0) - spot), (q.expiry or date.max)))
    return quotes


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

    atm_iv: Optional[float] = None
    if chain:
        for quote in chain:
            if quote.iv is not None:
                atm_iv = quote.iv
                break
        if atm_iv is None:
            # Fallback: use mid of bid/ask as a proxy if IV is missing.
            for quote in chain:
                if quote.bid is not None and quote.ask is not None:
                    atm_iv = (quote.bid + quote.ask) / 2.0
                    break

    if trade_date is None:
        trade_date = datetime.now().date().isoformat()

    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    if atm_iv is not None:
        history = load_iv_history(symbol)
        iv_rank, iv_percentile = compute_iv_rank(atm_iv, list(history.values()))
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
    )
    return context, chain


def _fetch_spot(symbol: str) -> Optional[float]:
    """Best-effort spot price via the existing Alpaca stock quote path."""
    try:
        df = get_alpaca_stock_client().get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol.upper()))
        if df is not None and not df.empty:
            return (float(df.iloc[0].get("bid_price", 0)) + float(df.iloc[0].get("ask_price", 0))) / 2.0
    except Exception:
        pass
    return None


def _fetch_hv_20(symbol: str) -> Optional[float]:
    """20-day annualized historical volatility from Alpaca daily bars."""
    try:
        end = datetime.now()
        start = end - timedelta(days=60)
        bars = get_alpaca_stock_client().get_stock_bars(
            StockBarsRequest(symbol_or_symbols=symbol.upper(), timeframe="1Day", start=start, end=end)
        )
        if bars is None or bars.df.empty:
            return None
        prices = bars.df["close"].dropna()
        return _annualized_hv(prices, window=20)
    except Exception:
        return None


def _fetch_days_to_earnings(symbol: str, config: Optional[dict]) -> Optional[int]:
    """Days until next earnings, if available via Finnhub."""
    try:
        from .earnings_utils import get_earnings_calendar_data

        calendar = get_earnings_calendar_data(symbol=symbol, config=config)
        if calendar and "next_earnings_date" in calendar:
            next_date = datetime.strptime(calendar["next_earnings_date"], "%Y-%m-%d").date()
            return (next_date - date.today()).days
    except Exception:
        pass
    return None


