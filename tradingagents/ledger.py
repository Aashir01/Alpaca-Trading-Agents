"""Append-only record of every order this deployment places.

The run logs under ``eval_results/`` already hold the reasoning: prompts, tool
calls, agent outputs, and the final signal. What they never held is what
actually happened at the broker. An order id, whether it filled, what it cost,
when it was closed and for how much lived only inside Alpaca, unlinked to the
run that caused it -- so "did the desk make money, and which reasoning produced
the winners?" was not a question this system could answer about itself.

This is that missing half. Two record kinds share one file:

* ``entry`` -- an order submitted to open exposure, carrying the run id, the
  structure, and the risk gate's own numbers.
* ``exit``  -- an order submitted to close it, carrying the rule that fired.

Records are appended, never rewritten, so the file is safe to tail, copy, or
read while the desk is trading. Fill status is not written at submission time
because it is not known then: ``reconcile`` fetches the terminal state from the
broker later and appends the result rather than mutating history.

Writing to the ledger must never be able to break a trade. Every entry point
swallows its own errors: a full disk should cost visibility, not an exit.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_LOCK = threading.Lock()

# One line per record. JSONL rather than a single JSON document so an
# interrupted write costs one line instead of the whole history, and so the
# file can be appended to without reading it back.
LEDGER_FILENAME = "trade_ledger.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ledger_path(config: Optional[Dict[str, Any]] = None) -> Path:
    """Where the ledger lives: alongside the run logs it cross-references."""
    results_dir = None
    if config:
        results_dir = config.get("results_dir")
    if not results_dir:
        results_dir = os.getenv("TRADINGAGENTS_RESULTS_DIR") or "eval_results"
    return Path(results_dir) / LEDGER_FILENAME


def _append(record: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> bool:
    path = ledger_path(config)
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=str) + "\n")
        return True
    except Exception as exc:  # noqa: BLE001 - visibility must not break trading
        print("[LEDGER] could not append record: %s" % exc)
        return False


def record_entry(
    *,
    symbol: str,
    order_id: Optional[str],
    asset_class: str = "option",
    strategy: str = "",
    legs: Optional[List[Dict[str, Any]]] = None,
    limit_price: Optional[float] = None,
    quantity: Optional[float] = None,
    signal: str = "",
    run_id: Optional[str] = None,
    gate: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Record an order submitted to open exposure."""
    gate = gate or {}
    return _append(
        {
            "kind": "entry",
            "recorded_at": _utc_now(),
            "symbol": symbol,
            "asset_class": asset_class,
            "order_id": order_id,
            "run_id": run_id,
            "strategy": strategy,
            "signal": signal,
            "quantity": quantity,
            "limit_price": limit_price,
            "legs": legs or [],
            # The gate's recomputed numbers, not the model's estimate: this is
            # what the deterministic layer actually approved.
            "max_loss_usd": gate.get("max_loss_usd"),
            "net_credit_debit": gate.get("net_credit_debit"),
            "collateral_required": gate.get("collateral_required"),
            **(extra or {}),
        },
        config,
    )


def record_exit(
    *,
    symbol: str,
    order_id: Optional[str],
    reason: str,
    group_key: str = "",
    legs: Optional[List[Dict[str, Any]]] = None,
    premium: Optional[float] = None,
    unrealized_pl: Optional[float] = None,
    structure: str = "",
    dte: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Record an order submitted to close exposure, and the rule that fired."""
    return _append(
        {
            "kind": "exit",
            "recorded_at": _utc_now(),
            "symbol": symbol,
            "asset_class": "option",
            "order_id": order_id,
            "group_key": group_key,
            "reason": reason,
            "structure": structure,
            "premium": premium,
            # P/L as the manager saw it when it decided. The realized figure
            # arrives later from the broker via reconcile().
            "unrealized_pl_at_decision": unrealized_pl,
            "dte": dte,
            "legs": legs or [],
            **(extra or {}),
        },
        config,
    )


def record_fill(
    *,
    order_id: str,
    status: str,
    filled_qty: Optional[float] = None,
    filled_avg_price: Optional[float] = None,
    filled_at: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Record what the broker finally did with an order.

    Appended rather than merged into the original record: history stays
    immutable, and readers fold the latest status per order id.
    """
    return _append(
        {
            "kind": "fill",
            "recorded_at": _utc_now(),
            "order_id": order_id,
            "status": status,
            "filled_qty": filled_qty,
            "filled_avg_price": filled_avg_price,
            "filled_at": filled_at,
        },
        config,
    )


def read_records(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Every record, oldest first. A corrupt line is skipped, not fatal."""
    path = ledger_path(config)
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue  # a torn final line from an interrupted write
    except OSError as exc:
        print("[LEDGER] could not read ledger: %s" % exc)
    return records


def load_orders(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """One row per order, with its latest known fill status folded in."""
    records = read_records(config)
    fills: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if record.get("kind") == "fill" and record.get("order_id"):
            fills[record["order_id"]] = record

    orders: List[Dict[str, Any]] = []
    for record in records:
        if record.get("kind") not in ("entry", "exit"):
            continue
        row = dict(record)
        fill = fills.get(record.get("order_id") or "")
        row["fill_status"] = (fill or {}).get("status")
        row["filled_qty"] = (fill or {}).get("filled_qty")
        row["filled_avg_price"] = (fill or {}).get("filled_avg_price")
        orders.append(row)
    return orders


def summarize(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Headline counts for the ledger surface in the UI."""
    orders = load_orders(config)
    entries = [o for o in orders if o["kind"] == "entry"]
    exits = [o for o in orders if o["kind"] == "exit"]

    def _filled(rows: Iterable[Dict[str, Any]]) -> int:
        return sum(1 for r in rows if str(r.get("fill_status") or "").lower() == "filled")

    exit_reasons: Dict[str, int] = {}
    for row in exits:
        # "stop loss: down $..." -> "stop loss"
        label = str(row.get("reason") or "unknown").split(":")[0].strip()
        exit_reasons[label] = exit_reasons.get(label, 0) + 1

    return {
        "entries": len(entries),
        "exits": len(exits),
        "entries_filled": _filled(entries),
        "exits_filled": _filled(exits),
        "exit_reasons": exit_reasons,
        "symbols": sorted({str(o.get("symbol")) for o in orders if o.get("symbol")}),
        "path": str(ledger_path(config)),
    }


def reconcile(config: Optional[Dict[str, Any]] = None, limit: int = 200) -> Dict[str, Any]:
    """Ask the broker what became of orders we have no terminal status for.

    Submission time cannot know whether an order fills, so the ledger records
    the submission and this fills in the outcome afterwards. Terminal statuses
    are never re-checked.
    """
    terminal = {"filled", "canceled", "cancelled", "expired", "rejected", "done_for_day"}
    orders = load_orders(config)

    pending = []
    for row in orders:
        order_id = row.get("order_id")
        status = str(row.get("fill_status") or "").lower()
        if order_id and status not in terminal:
            pending.append(order_id)
    # Preserve order while dropping duplicates.
    pending = list(dict.fromkeys(pending))[:limit]

    report = {"checked": len(pending), "updated": 0, "errors": []}
    if not pending:
        return report

    try:
        from tradingagents.dataflows.alpaca_utils import get_alpaca_trading_client

        client = get_alpaca_trading_client()
    except Exception as exc:
        report["errors"].append("no broker client: %s" % exc)
        return report

    for order_id in pending:
        try:
            order = client.get_order_by_id(order_id)
        except Exception as exc:
            report["errors"].append("%s: %s" % (order_id, exc))
            continue
        status = str(getattr(order, "status", "")).split(".")[-1].lower()
        record_fill(
            order_id=order_id,
            status=status,
            filled_qty=float(getattr(order, "filled_qty", 0) or 0),
            filled_avg_price=(
                float(order.filled_avg_price) if getattr(order, "filled_avg_price", None) else None
            ),
            filled_at=str(getattr(order, "filled_at", "") or "") or None,
            config=config,
        )
        report["updated"] += 1
    return report
