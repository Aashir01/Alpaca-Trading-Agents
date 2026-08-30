"""Options Strategist graph node.

Reads the Trader's signal and conviction, fetches option market context, asks a
deep LLM to pick a defined-risk strategy, then runs the deterministic risk gate.
"""

from __future__ import annotations

from typing import Any

from ..dataflows.alpaca_utils import AlpacaUtils
from ..dataflows.options_data import (
    fetch_spot_price,
    get_option_chain_context,
    get_options_market_context,
)
from ..prompts import render_prompt
from .options_risk_gate import evaluate_strategy
from .schemas import OptionsStrategyProposal
from .utils.structured import bind_structured



def _extract_confidence(trader_plan: Any) -> str:
    if isinstance(trader_plan, dict):
        return str(trader_plan.get("confidence", "medium") or "medium").lower()
    return "medium"


def _direction_from_action(action: str) -> str:
    action = (action or "NEUTRAL").upper()
    if action in {"BUY", "LONG"}:
        return "bullish"
    if action in {"SELL", "SHORT"}:
        return "bearish"
    return "neutral"


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


def _format_chain(quotes: list, max_rows: int = 10) -> str:
    if not quotes:
        return "No option chain data available."
    rows = []
    for q in quotes[:max_rows]:
        rows.append(
            f"- {q.symbol}: {q.option_type or '?'} strike={q.strike or '?'} "
            f"bid={q.bid} ask={q.ask} iv={q.iv} delta={q.delta} theta={q.theta}"
        )
    return "\n".join(rows)


def create_options_strategist(llm, config=None):
    """Factory for the Options Strategist graph node.

    Args:
        llm: deep-thinking LLM from the graph.
        config: merged application config dict.

    Returns:
        A callable node function compatible with StateGraph.
    """
    config = config or {}
    enabled = bool(config.get("options_trading_enabled", False))
    structured_llm = bind_structured(llm, OptionsStrategyProposal, "OptionsStrategist")

    def options_strategist_node(state):
        symbol = state.get("company_of_interest", "")
        recommended_action = state.get("recommended_action", "HOLD")
        trader_plan = state.get("trader_investment_plan", "")
        trade_date = state.get("trade_date")
        confidence = _extract_confidence(trader_plan)
        direction = _direction_from_action(recommended_action)

        allow_neutral = bool(config.get("options_allow_neutral", True))

        if not enabled:
            return {
                "options_strategy_report": "Options trading is disabled; no options strategy selected.",
                "options_trade_plan": None,
                "sender": "Options Strategist",
            }

        # A neutral equity signal is not the same as "no options trade". The
        # prompt already reasons about it -- iron_condor is an allowed strategy,
        # selection rule 1 routes a neutral view with rich IV to it, and rule 6
        # returns `none` when there is no premium edge. Short-circuiting here
        # meant those rules never ran and the desk sat out every HOLD, which is
        # most of them. Let the strategist decide, and let the risk gate and the
        # no-naked-shorts rule keep the structure defined-risk.
        if direction == "neutral" and not allow_neutral:
            return {
                "options_strategy_report": (
                    f"Trader signal is {recommended_action} (neutral) and neutral "
                    "overlays are disabled; no options strategy selected."
                ),
                "options_trade_plan": None,
                "sender": "Options Strategist",
            }

        try:
            # Spot must be resolved before the chain: it is what makes
            # "near the money" mean anything. Without it the chain comes back
            # unsorted and the candidates below are an arbitrary slice.
            spot = fetch_spot_price(symbol)
            chain_quotes = get_option_chain_context(
                symbol,
                spot=spot,
                dte_min=int(config.get("options_dte_min", 7)),
                dte_max=int(config.get("options_dte_max", 45)),
            )
            market_context, chain_quotes = get_options_market_context(
                symbol,
                spot=spot,
                trade_date=trade_date,
                dte_min=int(config.get("options_dte_min", 7)),
                dte_max=int(config.get("options_dte_max", 45)),
                chain_quotes=chain_quotes,
            )
        except Exception as exc:
            return {
                "options_strategy_report": f"Failed to fetch options market context: {exc}",
                "options_trade_plan": None,
                "sender": "Options Strategist",
            }

        if market_context.spot is None:
            return {
                "options_strategy_report": (
                    "Spot price unavailable for "
                    f"{symbol}; refusing to select strikes from an unsorted chain."
                ),
                "options_trade_plan": None,
                "sender": "Options Strategist",
            }

        chain_summary = _format_chain(chain_quotes, max_rows=12)

        prompt = render_prompt(
            "trader/options_strategy",
            symbol=symbol,
            recommended_action=recommended_action,
            confidence=confidence,
            direction=direction,
            spot=market_context.spot or "unknown",
            atm_iv=market_context.atm_iv or "unknown",
            iv_rank=market_context.iv_rank if market_context.iv_rank is not None else "null",
            iv_percentile=market_context.iv_percentile if market_context.iv_percentile is not None else "null",
            hv_20=market_context.hv_20 or "unknown",
            days_to_earnings=market_context.days_to_earnings if market_context.days_to_earnings is not None else "null",
            iv_history_days=market_context.iv_history_days,
            near_the_money_chain=chain_summary,
        )

        try:
            proposal: OptionsStrategyProposal = structured_llm.invoke(prompt)
        except Exception as exc:
            return {
                "options_strategy_report": f"Options Strategist LLM invocation failed: {exc}",
                "options_trade_plan": None,
                "sender": "Options Strategist",
            }

        # Build a quote map for the gate from the chain we already fetched.
        chain_map = {}
        for q in chain_quotes:
            if q.bid is not None and q.ask is not None:
                chain_map[q.symbol] = {"bid": q.bid, "ask": q.ask}

        account = _build_account_snapshot()
        gate_result = evaluate_strategy(
            proposal,
            qty=int(config.get("options_max_contracts", 1)),
            account=account,
            chain=chain_map,
            max_loss_pct=float(config.get("options_max_loss_pct", 2.0)),
            max_spread_pct=float(config.get("options_max_spread_pct", 20.0)),
            stress_move_pct=float(config.get("options_stress_move_pct", 20.0)),
        )

        if not gate_result.approved:
            report = (
                f"**Options Strategy Proposed**: {proposal.strategy.value}\n\n"
                f"**Rationale**: {proposal.rationale}\n\n"
                f"**Risk Gate Veto**: {gate_result.approved}\n"
                f"**Reasons**: {', '.join(gate_result.reasons)}"
            )
            return {
                "options_strategy_report": report,
                "options_trade_plan": None,
                "sender": "Options Strategist",
            }

        plan_dict = proposal.model_dump(mode="json")
        plan_dict["gate_result"] = gate_result.model_dump(mode="json")
        plan_dict["market_quotes"] = chain_map

        report = (
            f"**Options Strategy**: {proposal.strategy.value}\n\n"
            f"**Direction**: {proposal.direction}\n"
            f"**Legs**: {plan_dict.get('legs', [])}\n\n"
            f"**IV Context**: rank={market_context.iv_rank} "
            f"(from {market_context.iv_history_days} days of IV history), "
            f"atm_iv={market_context.atm_iv}, hv_20={market_context.hv_20}, "
            f"days_to_earnings={market_context.days_to_earnings}\n\n"
            f"**Rationale**: {proposal.rationale}\n\n"
            f"**Gate Result**: approved — max_loss=${gate_result.max_loss_usd}, "
            f"net_credit_debit={gate_result.net_credit_debit}\n"
        )

        return {
            "options_strategy_report": report,
            "options_trade_plan": plan_dict,
            "sender": "Options Strategist",
        }

    return options_strategist_node
