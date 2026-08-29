#!/usr/bin/env python
"""Record a daily ATM implied-volatility snapshot for a watchlist.

IV rank is only meaningful against stored history, and Alpaca exposes no
historical-IV endpoint. This script appends one true ATM IV observation per
symbol per day to the local cache that ``compute_iv_rank`` reads, so the rank
the strategist sees is grounded in real observations rather than a single
self-referential data point.

Run it once a day (cron, CI, or by hand) ahead of trading:

    python scripts/record_iv_history.py --symbols SPY QQQ AAPL MSFT NVDA

Nothing here is a substitute for real history: with fewer than
``options_min_iv_history_days`` observations the strategist is told the rank is
unreliable and prefers long-premium structures. This script is how that count
grows.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tradingagents.dataflows.options_data import (  # noqa: E402
    fetch_spot_price,
    get_option_chain_context,
    get_options_market_context,
    load_iv_history,
)


def record(symbol: str, dte_min: int, dte_max: int) -> tuple[bool, str]:
    """Record one ATM IV observation for ``symbol``; return (ok, message)."""
    try:
        spot = fetch_spot_price(symbol)
        if spot is None:
            return False, "spot price unavailable"

        chain = get_option_chain_context(
            symbol, spot=spot, dte_min=dte_min, dte_max=dte_max
        )
        if not chain:
            return False, "empty option chain"

        # get_options_market_context persists the observation as a side effect.
        context, _ = get_options_market_context(
            symbol,
            spot=spot,
            trade_date=date.today().isoformat(),
            dte_min=dte_min,
            dte_max=dte_max,
            chain_quotes=chain,
        )
        if context.atm_iv is None:
            return False, "no contract in the chain carried an implied volatility"

        stored = len(load_iv_history(symbol))
        rank = "n/a" if context.iv_rank is None else f"{context.iv_rank:.1f}"
        return True, (
            f"spot={spot:.2f} atm_iv={context.atm_iv:.4f} "
            f"iv_rank={rank} history={stored} day(s)"
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="Underlying tickers to snapshot, e.g. --symbols SPY QQQ AAPL",
    )
    parser.add_argument("--dte-min", type=int, default=7, help="Minimum days to expiration")
    parser.add_argument("--dte-max", type=int, default=45, help="Maximum days to expiration")
    args = parser.parse_args()

    failures = 0
    for symbol in args.symbols:
        symbol = symbol.upper()
        ok, message = record(symbol, args.dte_min, args.dte_max)
        print(f"[{'ok ' if ok else 'FAIL'}] {symbol}: {message}")
        if not ok:
            failures += 1

    if failures:
        print(f"\n{failures} of {len(args.symbols)} symbol(s) failed.", file=sys.stderr)
    return 1 if failures == len(args.symbols) else 0


if __name__ == "__main__":
    raise SystemExit(main())
