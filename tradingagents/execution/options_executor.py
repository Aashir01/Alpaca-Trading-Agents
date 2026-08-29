"""Options order execution.

Submits defined-risk multi-leg options orders via Alpaca's MLEG support and
provides a fail-closed re-check through the same risk gate used by the
strategist.
"""

from __future__ import annotations

from typing import Any, Optional

from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest

from ..agents.options_risk_gate import OptionsStrategy, evaluate_strategy, reconcile_direction
from ..agents.schemas import OptionsLeg, OptionsStrategyProposal, RiskGateResult
from ..dataflows.alpaca_utils import AlpacaUtils, get_alpaca_trading_client
from ..safety import get_safety_guard


def _proposal_from_dict(plan: dict) -> OptionsStrategyProposal:
    legs = [
        OptionsLeg(**leg)
        for leg in plan.get("legs", [])
    ]
    strategy = OptionsStrategy(plan.get("strategy", "none"))
    return OptionsStrategyProposal(
        strategy=strategy,
        symbol=plan.get("symbol", ""),
        direction=plan.get("direction", "neutral"),
        legs=legs,
        rationale=plan.get("rationale", ""),
        max_loss_estimate=plan.get("max_loss_estimate"),
        expected_credit_debit=plan.get("expected_credit_debit"),
        iv_rank_used=plan.get("iv_rank_used"),
        days_to_earnings=plan.get("days_to_earnings"),
    )


def _build_account_snapshot() -> dict:
    info = AlpacaUtils.get_account_info()
    positions_data = AlpacaUtils.get_positions_data()
    positions = []
    for pos in positions_data:
        qty = float(pos.get("Qty") or 0)
        if qty == 0:
            continue
        positions.append(
            {
                "symbol": pos.get("Symbol", ""),
                "qty": abs(qty),
                "side": "long" if qty > 0 else "short",
            }
        )
    return {
        "equity": float(info.get("equity") or 0.0),
        "buying_power": float(info.get("buying_power") or 0.0),
        "positions": positions,
    }


def _build_chain_map(proposal: OptionsStrategyProposal, market_quotes: Optional[dict] = None) -> dict:
    if market_quotes:
        return market_quotes
    chain_map = {}
    for leg in proposal.legs:
        # Executor does not re-fetch quotes; rely on the quote snapshot carried
        # by the caller or the gate will veto missing quotes.
        chain_map[leg.symbol] = {"bid": None, "ask": None}
    return chain_map


def submit_options_plan(
    plan: dict,
    *,
    final_action: str,
    qty: int = 1,
    market_quotes: Optional[dict] = None,
    max_loss_pct: float = 2.0,
    max_spread_pct: float = 20.0,
) -> dict:
    """Submit a multi-leg options order, or return a veto/failure record.

    Args:
        plan: the options trade plan (from ``options_trade_plan`` state key).
        final_action: the final equity signal from the risk judge (BUY/HOLD/SELL/LONG/NEUTRAL/SHORT).
        qty: number of spread units to trade.
        market_quotes: optional symbol -> {bid, ask} map for gate re-check.
        max_loss_pct: max defined loss as % of equity.
        max_spread_pct: max bid-ask spread % allowed.

    Returns:
        A status dict with ``submitted`` (bool), ``order_id`` (str or None),
        ``gate_result`` (RiskGateResult), and ``error`` (str or None).
    """
    proposal = _proposal_from_dict(plan)

    if proposal.strategy == OptionsStrategy.NONE:
        return {"submitted": False, "order_id": None, "gate_result": None, "error": "Strategy is 'none'."}

    # Direction reconciliation: the risk judge may have flipped the signal after
    # the options node ran. Never submit an options plan that no longer matches.
    matches, reason = reconcile_direction(proposal, final_action)
    if not matches:
        return {"submitted": False, "order_id": None, "gate_result": None, "error": reason}

    account = _build_account_snapshot()
    if market_quotes is None:
        market_quotes = plan.get("market_quotes")
    chain_map = _build_chain_map(proposal, market_quotes)
    gate_result = evaluate_strategy(
        proposal,
        qty=qty,
        account=account,
        chain=chain_map,
        max_loss_pct=max_loss_pct,
        max_spread_pct=max_spread_pct,
    )
    if not gate_result.approved:
        return {
            "submitted": False,
            "order_id": None,
            "gate_result": gate_result.model_dump(mode="json"),
            "error": "Risk gate veto: " + "; ".join(gate_result.reasons),
        }

    try:
        client = get_alpaca_trading_client()
    except Exception as exc:
        return {"submitted": False, "order_id": None, "gate_result": None, "error": f"Trading client error: {exc}"}

    limit_price = proposal.expected_credit_debit
    if limit_price is None:
        # Should not happen for a real plan; use a tiny positive debit as a safe fallback.
        limit_price = 0.01

    # Alpaca requires >= 2 legs for MLEG. Single-leg strategies (long call/put,
    # cash-secured put, covered call) use a simple option limit order.
    single_leg = len(proposal.legs) == 1
    if single_leg:
        leg = proposal.legs[0]
        order_request = LimitOrderRequest(
            symbol=leg.symbol.upper(),
            qty=qty * leg.ratio_qty,
            limit_price=abs(limit_price),
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.SIMPLE,
            side=OrderSide.BUY if leg.side == "buy" else OrderSide.SELL,
        )
    else:
        legs = [
            OptionLegRequest(
                symbol=leg.symbol,
                ratio_qty=leg.ratio_qty,
                side=OrderSide.BUY if leg.side == "buy" else OrderSide.SELL,
            )
            for leg in proposal.legs
        ]
        order_request = LimitOrderRequest(
            symbol=proposal.symbol.upper(),
            qty=qty,
            limit_price=limit_price,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.MLEG,
            legs=legs,
        )

    # Run through the existing deterministic safety guard.
    try:
        guard = get_safety_guard()
        guard.check_order(order_request)
    except Exception as exc:
        return {"submitted": False, "order_id": None, "gate_result": None, "error": f"Safety guard veto: {exc}"}

    try:
        submitted_order = client.submit_order(order_request)
        return {
            "submitted": True,
            "order_id": str(submitted_order.id) if submitted_order else None,
            "gate_result": gate_result.model_dump(mode="json"),
            "error": None,
        }
    except Exception as exc:
        return {"submitted": False, "order_id": None, "gate_result": None, "error": f"Broker submission error: {exc}"}


def get_options_positions() -> list[dict]:
    """Return open option positions from Alpaca in a normalized dict format."""
    try:
        positions = AlpacaUtils.get_positions_data()
        return [
            {
                "symbol": p.get("Symbol"),
                "qty": p.get("Qty"),
                "market_value": p.get("Market Value"),
                "avg_entry": p.get("Avg Entry"),
                "total_pl": p.get("Total P/L ($)"),
            }
            for p in positions
            if p.get("Symbol") and len(str(p.get("Symbol"))) > 12  # rough option-symbol length proxy
        ]
    except Exception:
        return []
