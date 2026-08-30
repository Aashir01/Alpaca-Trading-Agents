"""Options order execution.

Submits defined-risk multi-leg options orders via Alpaca's MLEG support and
provides a fail-closed re-check through the same risk gate used by the
strategist.
"""

from __future__ import annotations

from typing import Optional

from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest

from ..agents.options_risk_gate import OptionsStrategy, evaluate_strategy, reconcile_direction
from ..agents.schemas import OptionsLeg, OptionsStrategyProposal
from ..dataflows.alpaca_utils import AlpacaUtils, get_alpaca_trading_client
from ..safety import get_safety_guard


from tradingagents.mcp_client import AlpacaMCPError, alpaca_mcp_enabled, call_alpaca_tool


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
    stress_move_pct: float = 20.0,
) -> dict:
    """Submit a multi-leg options order, or return a veto/failure record.

    Args:
        plan: the options trade plan (from ``options_trade_plan`` state key).
        final_action: the final equity signal from the risk judge (BUY/HOLD/SELL/LONG/NEUTRAL/SHORT).
        qty: number of spread units to trade.
        market_quotes: optional symbol -> {bid, ask} map for gate re-check.
        max_loss_pct: max risk-sized loss as % of equity.
        max_spread_pct: max bid-ask spread % allowed.
        stress_move_pct: adverse move used to size collateralized shorts.

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
        stress_move_pct=stress_move_pct,
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

    # Price the order from the gate's own figure, not the model's estimate.
    # gate_result.net_credit_debit is the net premium per spread unit computed
    # from live bid/ask mid; Alpaca wants a positive per-share limit price and
    # infers debit vs credit from the legs, so take the magnitude.
    gate_premium = gate_result.net_credit_debit
    if gate_premium:
        limit_price = round(abs(gate_premium) / 100.0, 2)
    else:
        limit_price = None
    if not limit_price or limit_price <= 0:
        return {
            "submitted": False,
            "order_id": None,
            "gate_result": gate_result.model_dump(mode="json"),
            "error": "Could not derive a limit price from live quotes; refusing to price from the model estimate.",
        }

    # Alpaca requires >= 2 legs for MLEG. Single-leg strategies (long call/put,
    # cash-secured put, covered call) use a simple option limit order.
    single_leg = len(proposal.legs) == 1
    if single_leg:
        leg = proposal.legs[0]
        order_request = LimitOrderRequest(
            symbol=leg.symbol.upper(),
            qty=qty * leg.ratio_qty,
            limit_price=limit_price,
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
        # No top-level symbol on an MLEG order: the legs carry their own OCC
        # symbols, and Alpaca rejects the parent outright ("symbol is not
        # allowed for mleg order") when the underlying is set here as well.
        order_request = LimitOrderRequest(
            qty=qty,
            limit_price=limit_price,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.MLEG,
            legs=legs,
        )

    # Run through the existing deterministic safety guard. check_order takes
    # (symbol, notional) and *returns* a verdict -- it does not raise and it
    # does not accept an order object. Passing the request here made every
    # options order fail with a TypeError that the except-block below then
    # reported as a veto, so no options order could ever be submitted.
    # Capital at risk, not premium paid, is the exposure the guard should see:
    # for a credit spread the debit is small while the loss is not.
    try:
        guard = get_safety_guard()
        notional = abs(float(getattr(gate_result, "max_loss_usd", 0.0) or 0.0))
        if not notional:
            notional = abs(float(limit_price or 0.0)) * 100.0 * max(qty, 1)
        verdict = guard.check_order(
            symbol=proposal.symbol.upper(),
            notional=notional,
            account=account,
        )
        if verdict is not None and not verdict.allowed:
            return {
                "submitted": False,
                "order_id": None,
                "gate_result": gate_result.model_dump(mode="json"),
                "error": "Safety guard veto: " + "; ".join(verdict.reasons),
            }
    except Exception as exc:
        return {
            "submitted": False,
            "order_id": None,
            "gate_result": gate_result.model_dump(mode="json"),
            "error": f"Safety guard error: {exc}",
        }

    # Route through Alpaca's official MCP server when enabled, falling back to
    # the SDK if it is unreachable. The gate and the guard above run either
    # way: the transport changes, the safety path does not.
    if alpaca_mcp_enabled():
        try:
            order_id = _submit_via_mcp(proposal, qty, limit_price, single_leg)
            return {
                "submitted": True,
                "order_id": order_id,
                "gate_result": gate_result.model_dump(mode="json"),
                "limit_price": limit_price,
                "model_estimate": proposal.expected_credit_debit,
                "transport": "alpaca-mcp-server",
                "error": None,
            }
        except AlpacaMCPError as exc:
            print(f"[options_executor] MCP submission failed ({exc}); falling back to the SDK")

    try:
        submitted_order = client.submit_order(order_request)
        return {
            "submitted": True,
            "order_id": str(submitted_order.id) if submitted_order else None,
            "gate_result": gate_result.model_dump(mode="json"),
            "limit_price": limit_price,
            "model_estimate": proposal.expected_credit_debit,
            "transport": "alpaca-py",
            "error": None,
        }
    except Exception as exc:
        return {"submitted": False, "order_id": None, "gate_result": None, "error": f"Broker submission error: {exc}"}


def _submit_via_mcp(proposal, qty: int, limit_price: float, single_leg: bool) -> Optional[str]:
    """Place the options order through Alpaca's MCP server.

    Every value the tool takes is a string, including qty and ratio_qty. For a
    multi-leg order the parent carries no symbol or side -- the legs do -- and
    limit_price is the net debit (positive) or credit (negative).
    """
    args: dict = {
        "qty": str(qty),
        "type": "limit",
        "limit_price": str(limit_price),
        "time_in_force": "day",
    }
    if single_leg:
        leg = proposal.legs[0]
        args["symbol"] = leg.symbol.upper()
        args["side"] = leg.side
        args["qty"] = str(qty * leg.ratio_qty)
        args["position_intent"] = "buy_to_open" if leg.side == "buy" else "sell_to_open"
    else:
        args["order_class"] = "mleg"
        args["legs"] = [
            {
                "symbol": leg.symbol.upper(),
                "ratio_qty": str(leg.ratio_qty),
                "side": leg.side,
                "position_intent": "buy_to_open" if leg.side == "buy" else "sell_to_open",
            }
            for leg in proposal.legs
        ]

    response = call_alpaca_tool("place_option_order", args)
    if isinstance(response, dict):
        for key in ("id", "order_id"):
            if response.get(key):
                return str(response[key])
        inner = response.get("result") or response.get("order") or response.get("data")
        if isinstance(inner, dict):
            for key in ("id", "order_id"):
                if inner.get(key):
                    return str(inner[key])
    # No id means the broker did not acknowledge an order. Reporting success
    # here would claim a trade that may not exist, so treat it as a failure and
    # let the caller fall back to the SDK.
    raise AlpacaMCPError(f"place_option_order returned no order id: {str(response)[:200]}")


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
