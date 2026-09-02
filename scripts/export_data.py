#!/usr/bin/env python
"""Bundle everything this deployment has recorded into one archive.

Three stores, written by three different parts of the system, answer three
different questions:

* ``eval_results/*/TradingAgentsStrategy_logs/runs/*.json`` -- what the agents
  read, thought, and decided, prompt by prompt and tool call by tool call.
* ``trade_ledger.jsonl`` -- what actually reached the broker, and what came
  back.
* ``options_iv_history/`` -- the daily IV observations, which cannot be
  back-filled if a day is missed.

Keeping them together is the difference between "the desk lost money" and
"this reasoning produced this order which lost money".

    python scripts/export_data.py                    # -> exports/<timestamp>.tar.gz
    python scripts/export_data.py --out /tmp/x.tgz
    python scripts/export_data.py --summary-only     # print, archive nothing

Prompts can contain whatever the tools returned, so the archive is written
0600 and never redacted automatically: treat it as sensitive.
"""

import argparse
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _config():
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    from tradingagents.dataflows.config import get_config

    return get_config() or {}


def _gather(config):
    """Locate the stores. A missing one is reported, not fatal."""
    results_dir = Path(config.get("results_dir") or "eval_results")
    cache_dir = Path(config.get("data_cache_dir") or "tradingagents/dataflows/data_cache")

    run_logs = sorted(results_dir.glob("*/TradingAgentsStrategy_logs/runs/*.json"))
    ledger = results_dir / "trade_ledger.jsonl"
    iv_history = cache_dir / "options_iv_history"

    return {
        "results_dir": results_dir,
        "run_logs": run_logs,
        "ledger": ledger if ledger.is_file() else None,
        "iv_history": iv_history if iv_history.is_dir() else None,
    }


def _summarize(config, found):
    from tradingagents.ledger import summarize

    signals = {}
    symbols = set()
    for path in found["run_logs"]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        symbols.add(payload.get("symbol", ""))
        signal = str((payload.get("summary") or {}).get("final_signal") or "none")
        signals[signal] = signals.get(signal, 0) + 1

    ledger = summarize(config)
    return {
        "run_logs": len(found["run_logs"]),
        "symbols": sorted(s for s in symbols if s),
        "signals": signals,
        "ledger_entries": ledger["entries"],
        "ledger_exits": ledger["exits"],
        "exit_reasons": ledger["exit_reasons"],
        "iv_history_files": (
            len(list(found["iv_history"].glob("*.json"))) if found["iv_history"] else 0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="archive path (default exports/<timestamp>.tar.gz)")
    parser.add_argument("--summary-only", action="store_true",
                        help="print what would be archived and stop")
    args = parser.parse_args()

    config = _config()
    found = _gather(config)
    summary = _summarize(config, found)

    print("Recorded data")
    print("  run logs         : %d  (%s)" % (summary["run_logs"], ", ".join(summary["symbols"]) or "no symbols"))
    print("  final signals    : %s" % (summary["signals"] or "none"))
    print("  ledger entries   : %d" % summary["ledger_entries"])
    print("  ledger exits     : %d  %s" % (summary["ledger_exits"], summary["exit_reasons"] or ""))
    print("  IV history files : %d" % summary["iv_history_files"])

    if args.summary_only:
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else Path("exports") / ("options-alpha-%s.tar.gz" % stamp)
    out.parent.mkdir(parents=True, exist_ok=True)

    members = []
    if found["run_logs"]:
        members.append((found["results_dir"], "run-logs"))
    if found["ledger"]:
        members.append((found["ledger"], "trade_ledger.jsonl"))
    if found["iv_history"]:
        members.append((found["iv_history"], "options_iv_history"))

    if not members:
        print("\nNothing recorded yet; no archive written.")
        return 0

    with tarfile.open(out, "w:gz") as archive:
        for source, arcname in members:
            archive.add(source, arcname=arcname)
    # Prompts and tool output can contain anything the tools returned.
    try:
        out.chmod(0o600)
    except OSError:
        pass

    print("\nWrote %s (%.1f KB)" % (out, out.stat().st_size / 1024.0))
    print("Contains prompts and tool output -- treat as sensitive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
