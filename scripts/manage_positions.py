#!/usr/bin/env python
"""Close open options structures that have hit their exit conditions.

Runs on a timer, not inside the agent graph: an exit has to fire whether or
not an analysis happens to be running, and a stop that waits for the next
scheduled run is not a stop. Costs no LLM calls -- every decision is
arithmetic on the broker's own cost basis.

    python scripts/manage_positions.py            # act
    python scripts/manage_positions.py --dry-run  # report only, place nothing
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tradingagents.console_encoding import ensure_utf8_console

ensure_utf8_console()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="evaluate and report, but submit no closing orders",
    )
    parser.add_argument(
        "--ignore-clock",
        action="store_true",
        help="run even when the market is closed (closing orders will be rejected)",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    from tradingagents.dataflows.config import get_config
    from tradingagents.execution import manage_open_positions

    config = get_config() or {}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    if not config.get("options_exit_manager_enabled", True):
        print("[%s] exit manager disabled (OPTIONS_EXIT_MANAGER_ENABLED)" % stamp)
        return 0

    # Ask the broker whether the market is open rather than hard-coding hours:
    # a closing order sent after hours is rejected, and enough consecutive
    # rejections engage the kill switch. This also makes the timer immune to
    # daylight-saving shifts.
    if not (args.dry_run or args.ignore_clock) and not _market_is_open():
        print("[%s] market closed; nothing attempted" % stamp)
        return 0

    report = manage_open_positions(config=config, dry_run=args.dry_run)

    mode = " (dry run)" if args.dry_run else ""
    print(
        "[%s] checked %d structure(s)%s" % (stamp, report["checked"], mode)
    )
    if report.get("flattened"):
        print("  ACCOUNT BREAKER TRIPPED -- flattening every open structure")
    for held in report["held"]:
        print("  hold  %-12s %s" % (held["key"], held["reason"]))
    for closed in report["closed"]:
        result = closed.get("result", {})
        detail = result.get("order_id") or ("would close" if result.get("dry_run") else "")
        print("  CLOSE %-12s %s  %s" % (closed["key"], closed["reason"], detail))
    for error in report["errors"]:
        print("  ERROR %s" % error)

    # A failure to close is the one outcome worth a non-zero exit: it is the
    # case where capital is still at risk after the manager believed it acted.
    return 1 if report["errors"] else 0


def _market_is_open() -> bool:
    """True when Alpaca says the market is open. Unknown counts as closed."""
    try:
        from tradingagents.dataflows.alpaca_utils import get_alpaca_trading_client

        return bool(get_alpaca_trading_client().get_clock().is_open)
    except Exception as exc:
        print("  could not read the market clock (%s); treating as closed" % exc)
        return False


if __name__ == "__main__":
    raise SystemExit(main())
