"""Research-mode backtester for the Options Alpha strategy selector.

This script is NOT a pytest test. It replays a deterministic, no-LLM version
of the strategy-selection rules over historical underlying prices and a
synthetic implied-volatility proxy. The output is explicitly labeled as
research-mode expected-value analysis, not a claim about live performance.

Usage (from repo root):

    python tests/backtest_options.py --symbols AAPL MSFT TSLA --months 6

"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

# Research-mode: model implied volatility as historical vol scaled by a
# persistent market premium. This is a simplifying assumption; replace with
# real option IV when available.
IV_HV_PREMIUM = 1.15


def _parse_args():
    parser = argparse.ArgumentParser(description="Options Alpha research backtester")
    parser.add_argument("--symbols", nargs="+", default=["AAPL"], help="Watchlist tickers")
    parser.add_argument("--months", type=int, default=6, help="Months of history to replay")
    parser.add_argument("--dte", type=int, default=30, help="Target days to expiration")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for synthetic IV")
    return parser.parse_args()


@dataclass
class Signal:
    date: str
    direction: str
    iv_rank: float
    days_to_earnings: int | None


@dataclass
class Trade:
    symbol: str
    entry_date: str
    strategy: str
    direction: str
    entry_price: float
    exit_price: float
    pnl_pct: float


def fetch_bars(symbol: str, months: int):
    """Fetch daily close prices via yfinance."""
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("yfinance is required for the backtester") from exc

    end = datetime.now()
    start = end - timedelta(days=months * 31 + 60)
    df = yf.download(symbol, start=start, end=end, progress=False)
    if df is None or df.empty:
        raise ValueError(f"No historical data returned for {symbol}")
    return df["Close"].dropna().sort_index()


def compute_hv(prices: np.ndarray, window: int = 20) -> float:
    """Annualized historical volatility in percent."""
    if len(prices) < window + 1:
        return float("nan")
    log_returns = np.log(prices[1:] / prices[:-1])
    stdev = log_returns[-window:].std()
    return float(stdev * math.sqrt(252) * 100.0)


def compute_iv_rank(model_iv: float, history: list[float]) -> float:
    if not history:
        return 50.0
    lower = sum(1 for h in history if h < model_iv)
    equal = sum(1 for h in history if h == model_iv)
    return (lower + equal / 2.0) / len(history) * 100.0


def select_strategy(direction: str, iv_rank: float, days_to_earnings: int | None) -> str:
    """Deterministic strategy selection matching the Options Strategist rules."""
    no_earnings = days_to_earnings is None or days_to_earnings > 7
    high_iv = iv_rank >= 50.0

    if direction == "neutral":
        return "iron_condor" if high_iv and no_earnings else "none"

    if direction == "bullish":
        if high_iv and no_earnings:
            return "cash_secured_put"
        return "long_call"

    if direction == "bearish":
        if high_iv and no_earnings:
            return "bear_call_spread"
        return "long_put"

    return "none"


def direction_from_price(close: float, sma: float) -> str:
    if close > sma * 1.005:
        return "bullish"
    if close < sma * 0.995:
        return "bearish"
    return "neutral"


def simulate_pnl(strategy: str, direction: str, price_return: float, hv: float) -> float:
    """Simplified research-mode P&L in percent of notional at risk.

    Uses directional option payoff approximations; not a live-performance claim.
    """
    if strategy in ("long_call", "long_put"):
        # Long option: lose premium if wrong, gain if right (leverage ~ delta/hv).
        leverage = 1.0 / max(hv / 100.0, 0.05)
        if (direction == "bullish" and price_return > 0) or (direction == "bearish" and price_return < 0):
            return abs(price_return) * leverage - 0.10
        return -1.0

    if strategy in ("cash_secured_put", "bull_put_spread"):
        # Short put / bull put: profit if flat/up, hurt if down sharply.
        if price_return >= -hv / 100.0:
            return 0.10
        return -0.50

    if strategy in ("bear_call_spread",):
        # Bear call / short call: profit if flat/down, hurt if up sharply.
        if price_return <= hv / 100.0:
            return 0.10
        return -0.50

    if strategy == "iron_condor":
        # Profit if price stays within one HV band, loss if outside.
        if abs(price_return) <= hv / 100.0:
            return 0.15
        return -0.40

    return 0.0


@dataclass
class BacktestResult:
    symbol: str
    trades: list[Trade] = field(default_factory=list)

    def summary(self) -> dict:
        if not self.trades:
            return {"trades": 0, "win_rate": None, "avg_pnl": None}
        wins = sum(1 for t in self.trades if t.pnl_pct > 0)
        return {
            "trades": len(self.trades),
            "wins": wins,
            "win_rate": round(wins / len(self.trades) * 100.0, 2),
            "avg_pnl": round(float(sum(t.pnl_pct for t in self.trades) / len(self.trades)), 4),
        }


def run_symbol(symbol: str, months: int, dte: int) -> BacktestResult:
    prices = fetch_bars(symbol, months)
    values = prices.values.flatten()
    result = BacktestResult(symbol=symbol)
    iv_history: list[float] = []

    for i in range(21, len(values) - dte):
        window = values[i - 21 : i]
        hv = compute_hv(window)
        if math.isnan(hv):
            continue

        model_iv = hv * IV_HV_PREMIUM
        iv_rank = compute_iv_rank(model_iv, iv_history[-60:])
        iv_history.append(model_iv)

        sma = float(np.mean(window))
        close = float(values[i])
        direction = direction_from_price(close, sma)
        days_to_earnings = None

        strategy = select_strategy(direction, iv_rank, days_to_earnings)
        if strategy == "none":
            continue

        future = values[i + dte]
        price_return = (future - close) / close
        pnl = simulate_pnl(strategy, direction, price_return, hv)

        result.trades.append(
            Trade(
                symbol=symbol,
                entry_date=prices.index[i].strftime("%Y-%m-%d"),
                strategy=strategy,
                direction=direction,
                entry_price=close,
                exit_price=future,
                pnl_pct=pnl,
            )
        )

    return result


def main() -> int:
    args = _parse_args()
    np.random.seed(args.seed)
    print("Options Alpha Backtest — RESEARCH MODE, NOT LIVE PERFORMANCE\n")
    for symbol in args.symbols:
        try:
            result = run_symbol(symbol, args.months, args.dte)
        except Exception as exc:
            print(f"{symbol}: skipped ({exc})")
            continue
        summary = result.summary()
        print(f"{symbol}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
