"""Exit management for open options positions.

The strategist opens defined-risk structures and nothing ever closed them: a
spread rode to expiry whichever way it went. The risk gate caps what a *new*
position may lose and the safety breakers stop *new* orders, but neither
touches capital already at risk. This module is the other half -- it decides
when an open structure should be closed, and closes it.

Three exits, checked in order of urgency:

* **Stop loss** -- the loss has reached a multiple of the premium taken in
  (credit structures) or a fraction of the premium paid (debit structures).
* **Profit target** -- enough of the maximum gain has been captured that the
  remaining reward no longer justifies the risk still on the table.
* **Time** -- expiry is close enough that gamma dominates and the position no
  longer behaves like the structure that was opened.

Every number here comes from the broker's own cost basis and market value, so
no model opinion can keep a losing position open or close a winning one.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from tradingagents.dataflows.alpaca_utils import get_alpaca_trading_client

# OCC symbol: ROOT + YYMMDD + C/P + 8-digit strike in thousandths of a dollar.
_OCC = re.compile(r"^(?P<root>[A-Z]+)(?P<expiry>\d{6})(?P<right>[CP])(?P<strike>\d{8})$")


def parse_occ(symbol: str) -> Optional[Dict[str, Any]]:
    """Split an OCC option symbol into its parts, or None if it is not one."""
    match = _OCC.match(str(symbol or "").strip().upper())
    if not match:
        return None
    try:
        expiry = datetime.strptime(match.group("expiry"), "%y%m%d").date()
    except ValueError:
        return None
    return {
        "root": match.group("root"),
        "expiry": expiry,
        "right": "call" if match.group("right") == "C" else "put",
        "strike": int(match.group("strike")) / 1000.0,
    }


def group_positions(positions: List[Any]) -> Dict[str, Dict[str, Any]]:
    """Group raw Alpaca option positions into structures.

    Legs are keyed by underlying and expiry, which is how the strategist opens
    them: one plan is one expiry on one name. Two structures opened on the same
    underlying and expiry therefore manage as a single net position. That is
    the right arithmetic -- the net is the real exposure -- but it does mean
    they exit together.

    Alpaca already multiplies cost basis and market value by the 100-share
    contract multiplier, so nothing is scaled again here.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for position in positions:
        parsed = parse_occ(getattr(position, "symbol", ""))
        if parsed is None:
            continue  # equity or crypto: those carry broker-side brackets
        key = parsed["root"] + ":" + parsed["expiry"].isoformat()
        group = groups.setdefault(
            key,
            {
                "key": key,
                "underlying": parsed["root"],
                "expiry": parsed["expiry"],
                "legs": [],
                "cost_basis": 0.0,
                "market_value": 0.0,
                "unrealized_pl": 0.0,
            },
        )
        group["legs"].append(
            {
                "symbol": position.symbol,
                "qty": float(getattr(position, "qty", 0) or 0),
                "strike": parsed["strike"],
                "right": parsed["right"],
                "cost_basis": float(getattr(position, "cost_basis", 0) or 0),
                "market_value": float(getattr(position, "market_value", 0) or 0),
            }
        )
        group["cost_basis"] += float(getattr(position, "cost_basis", 0) or 0)
        group["market_value"] += float(getattr(position, "market_value", 0) or 0)
        group["unrealized_pl"] += float(getattr(position, "unrealized_pl", 0) or 0)
    return groups


def days_to_expiry(expiry: date, today: Optional[date] = None) -> int:
    return (expiry - (today or date.today())).days


def evaluate_group(
    group: Dict[str, Any],
    config: Dict[str, Any],
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Decide whether one structure should be closed, and say why.

    A negative net cost basis means premium was *received* (a credit
    structure); positive means premium was *paid* (a debit structure). They
    need different stops: a debit spread cannot lose more than it cost, so a
    "twice the premium" stop could never fire on one.
    """
    take_profit_pct = float(config.get("options_take_profit_pct", 0.35) or 0)
    stop_multiple = float(config.get("options_stop_loss_multiple", 1.5) or 0)
    debit_stop_pct = float(config.get("options_debit_stop_pct", 0.5) or 0)
    close_dte = int(config.get("options_close_dte", 21) or 0)

    net_cost = group["cost_basis"]
    pl = group["unrealized_pl"]
    dte = days_to_expiry(group["expiry"], today)
    is_credit = net_cost < 0
    premium = abs(net_cost)
    kind = "credit" if is_credit else "debit"

    decision = {
        "key": group["key"],
        "underlying": group["underlying"],
        "expiry": group["expiry"].isoformat(),
        "dte": dte,
        "structure": kind,
        "premium": premium,
        "unrealized_pl": pl,
        "pl_pct_of_premium": (pl / premium * 100.0) if premium else 0.0,
        "action": "hold",
        "reason": "",
    }

    if premium <= 0:
        decision["reason"] = "no premium basis to measure against"
        return decision

    # Stop first. A position can be past both thresholds only if the numbers
    # are stale, and in that case the loss is the one that matters.
    stop_amount = stop_multiple * premium if is_credit else debit_stop_pct * premium
    if stop_amount > 0 and pl <= -stop_amount:
        decision["action"] = "close"
        decision["reason"] = (
            "stop loss: down $%.2f against a $%.2f %s (limit $%.2f)"
            % (abs(pl), premium, kind, stop_amount)
        )
        return decision

    target_amount = take_profit_pct * premium
    if target_amount > 0 and pl >= target_amount:
        decision["action"] = "close"
        decision["reason"] = (
            "profit target: up $%.2f, %.0f%% of the $%.2f %s"
            % (pl, pl / premium * 100.0, premium, kind)
        )
        return decision

    if close_dte > 0 and dte <= close_dte:
        decision["action"] = "close"
        decision["reason"] = (
            "time exit: %d days to expiry (threshold %d)" % (dte, close_dte)
        )
        return decision

    decision["reason"] = (
        "holding: $%.2f of a $%.2f %s, %dd to expiry" % (pl, premium, kind, dte)
    )
    return decision


def close_group(group: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """Close every leg of a structure as one order.

    Legs are reversed in a single MLEG order rather than closed one at a time:
    closing a four-leg condor leg by leg can partially fill and leave a naked
    short, which is the exposure the defined-risk structure existed to avoid.
    """
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest, OptionLegRequest

    legs = group.get("legs") or []
    if not legs:
        return {"submitted": False, "error": "no legs to close"}

    if dry_run:
        return {
            "submitted": False,
            "dry_run": True,
            "would_close": [leg["symbol"] for leg in legs],
        }

    try:
        client = get_alpaca_trading_client()
        if len(legs) == 1:
            leg = legs[0]
            # Reverse the position: a long leg is sold, a short leg bought back.
            request = MarketOrderRequest(
                symbol=leg["symbol"],
                qty=abs(int(leg["qty"])),
                side=OrderSide.SELL if leg["qty"] > 0 else OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.SIMPLE,
            )
        else:
            quantities = [abs(int(leg["qty"])) for leg in legs if int(leg["qty"])]
            unit = min(quantities) if quantities else 1
            request = MarketOrderRequest(
                qty=unit,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.MLEG,
                legs=[
                    OptionLegRequest(
                        symbol=leg["symbol"],
                        ratio_qty=max(1, abs(int(leg["qty"])) // unit),
                        side=OrderSide.SELL if leg["qty"] > 0 else OrderSide.BUY,
                    )
                    for leg in legs
                ],
            )
        order = client.submit_order(request)
        return {
            "submitted": True,
            "order_id": str(order.id),
            "status": str(order.status),
        }
    except Exception as exc:
        return {"submitted": False, "error": str(exc)}


def manage_open_positions(
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Evaluate every open options structure and close the ones that qualify.

    Also enforces the account-level breakers as an *exit*, not just a veto.
    The safety guard already refuses new orders once the daily-loss or
    drawdown limit is hit, but refusing to open is no protection for capital
    already committed -- so when a breaker has tripped, everything is flattened
    and the kill switch is engaged.
    """
    if config is None:
        from tradingagents.dataflows.config import get_config

        config = get_config() or {}

    report: Dict[str, Any] = {
        "checked": 0,
        "closed": [],
        "held": [],
        "errors": [],
        "flattened": False,
    }

    try:
        positions = list(get_alpaca_trading_client().get_all_positions())
    except Exception as exc:
        report["errors"].append("could not read positions: %s" % exc)
        return report

    groups = group_positions(positions)
    report["checked"] = len(groups)
    if not groups:
        return report

    breaker = _tripped_breaker(config)
    for group in groups.values():
        if breaker:
            decision = {
                "key": group["key"],
                "underlying": group["underlying"],
                "action": "close",
                "reason": "account breaker: %s" % breaker,
                "unrealized_pl": group["unrealized_pl"],
            }
            report["flattened"] = True
        else:
            decision = evaluate_group(group, config, today=today)

        if decision["action"] != "close":
            report["held"].append(decision)
            continue

        result = close_group(group, dry_run=dry_run)
        decision["result"] = result
        if result.get("submitted"):
            _record_exit_in_ledger(group, decision, result, config)
        if result.get("submitted") or result.get("dry_run"):
            report["closed"].append(decision)
        else:
            report["errors"].append(
                "%s: %s" % (group["key"], result.get("error", "close failed"))
            )

    if breaker and not dry_run and report["closed"]:
        try:
            from tradingagents.safety import get_safety_guard

            get_safety_guard().engage_kill_switch("flattened by exit manager: %s" % breaker)
        except Exception:
            pass

    return report


def _record_exit_in_ledger(group, decision, result, config) -> None:
    """Persist the close, and the rule that caused it.

    Guarded like the entry side: the closing order is already live by this
    point, and an exception here would misreport a real exit as a failure.
    """
    try:
        from tradingagents.ledger import record_exit

        record_exit(
            symbol=group["underlying"],
            order_id=result.get("order_id"),
            reason=decision.get("reason", ""),
            group_key=group["key"],
            legs=[
                {"symbol": leg["symbol"], "qty": leg["qty"]} for leg in group["legs"]
            ],
            premium=decision.get("premium"),
            unrealized_pl=decision.get("unrealized_pl"),
            structure=decision.get("structure", ""),
            dte=decision.get("dte"),
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        print("[position_manager] ledger write failed: %s" % exc)


def _tripped_breaker(config: Dict[str, Any]) -> Optional[str]:
    """Return the name of a tripped *loss* breaker, or None.

    Only the loss breakers flatten. The kill switch is deliberately not one of
    them: it means "stop trading", which is a halt on new exposure, not an
    instruction to liquidate a book someone may have halted precisely because
    they wanted it left alone. Normal profit and stop exits still run while it
    is engaged, because closing reduces risk.

    Thresholds come from the safety guard's own config so the exit side and
    the entry side cannot drift into two different definitions of "too much".
    """
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
        from tradingagents.safety import get_safety_guard

        guard = get_safety_guard()
        if not guard.enabled:
            return None

        info = AlpacaUtils.get_account_info() or {}
        equity = float(info.get("equity") or 0)
        last_equity = float(info.get("last_equity") or 0)
        # get_account_info returns zeros when the broker call fails. Treating
        # that as a 100% drawdown would flatten the book on a network blip.
        if equity <= 0:
            return None

        daily_halt = float(guard.config.get("daily_loss_halt_pct", 0) or 0)
        if daily_halt > 0 and last_equity > 0:
            change_pct = (equity - last_equity) / last_equity * 100.0
            if change_pct <= -daily_halt:
                return "daily loss %.2f%% (limit %.2f%%)" % (abs(change_pct), daily_halt)

        drawdown_halt = float(guard.config.get("max_drawdown_halt_pct", 0) or 0)
        if drawdown_halt > 0:
            high_water = guard._state.get("high_water_mark")
            if high_water and float(high_water) > 0:
                drawdown = (float(high_water) - equity) / float(high_water) * 100.0
                if drawdown >= drawdown_halt:
                    return "drawdown %.2f%% from high-water mark (limit %.2f%%)" % (
                        drawdown,
                        drawdown_halt,
                    )
    except Exception:
        # An exit manager that cannot read the account must not guess that the
        # account is fine, but it must not flatten on a guess either.
        return None
    return None
