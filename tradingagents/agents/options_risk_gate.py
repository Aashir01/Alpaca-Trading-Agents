"""Options risk gate — deterministic veto/approval for options strategies.

This module is intentionally pure: it receives a proposed options strategy,
an account snapshot, and a chain quote map, and returns an approval decision
with reasons. It never talks to the broker or the LLM.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .schemas import OptionsStrategy, OptionsStrategyProposal, RiskGateResult

# Map equity signals to a directional bias used by the options strategist.
_BULLISH = {"BUY", "LONG"}
_BEARISH = {"SELL", "SHORT"}


def _direction_for_action(action: str) -> str:
    action = (action or "").upper()
    if action in _BULLISH:
        return "bullish"
    if action in _BEARISH:
        return "bearish"
    return "neutral"


def evaluate_strategy(
    proposal: OptionsStrategyProposal,
    *,
    qty: int,
    account: Mapping[str, Any],
    chain: Mapping[str, Mapping[str, Any]],
    max_loss_pct: float = 2.0,
    max_spread_pct: float = 20.0,
    stress_move_pct: float = 20.0,
) -> RiskGateResult:
    """Veto or approve an options strategy.

    Args:
        proposal: the structured options strategy to evaluate.
        qty: number of spread units (contracts) to be traded.
        account: account snapshot with ``equity``, ``buying_power`` and ``positions``.
        chain: map from leg symbol to a quote dict with ``bid`` and ``ask``.
        max_loss_pct: maximum allowed loss as a percent of account equity.
        max_spread_pct: maximum allowed bid-ask spread as a percent of mid price.
        stress_move_pct: adverse move, as a percent below the short strike, used
            to size collateralized shorts. A cash-secured put's true worst case
            is the stock going to zero, which is honest but useless as a sizing
            rule, so the equity limit is applied to this stressed loss while the
            to-zero figure is still reported.

    Returns:
        ``RiskGateResult`` with ``approved`` flag and a list of veto reasons.
    """
    reasons: list[str] = []

    equity = float(account.get("equity") or 0.0)
    buying_power = float(account.get("buying_power") or 0.0)
    positions = account.get("positions") or []

    if proposal.strategy == OptionsStrategy.NONE:
        return RiskGateResult(approved=True, reasons=["Strategy is 'none'; no options trade required."])

    if not proposal.legs:
        return RiskGateResult(approved=False, reasons=["No legs provided for non-'none' strategy."])

    # Liquidity checks on every leg.
    missing_quotes: list[str] = []
    wide_spreads: list[str] = []
    for leg in proposal.legs:
        quote = chain.get(leg.symbol)
        if not quote:
            missing_quotes.append(leg.symbol)
            continue
        try:
            bid = float(quote.get("bid") or 0.0)
            ask = float(quote.get("ask") or 0.0)
        except (TypeError, ValueError):
            missing_quotes.append(leg.symbol)
            continue
        if bid <= 0 or ask <= 0:
            missing_quotes.append(leg.symbol)
            continue
        mid = (bid + ask) / 2.0
        spread_pct = (ask - bid) / mid * 100.0 if mid > 0 else 0.0
        if spread_pct > max_spread_pct:
            wide_spreads.append(f"{leg.symbol} ({spread_pct:.1f}%)")

    if missing_quotes:
        reasons.append(f"Missing or invalid quotes for: {', '.join(missing_quotes)}.")
    if wide_spreads:
        reasons.append(f"Bid-ask spread too wide for: {', '.join(wide_spreads)}.")

    # Compute per-spread net credit/debit from the chain (independent of proposal estimate).
    per_share_premium = 0.0
    for leg in proposal.legs:
        quote = chain.get(leg.symbol)
        if not quote:
            continue
        try:
            bid = float(quote.get("bid") or 0.0)
            ask = float(quote.get("ask") or 0.0)
        except (TypeError, ValueError):
            continue
        mid = (bid + ask) / 2.0
        side_sign = -1.0 if leg.side == "sell" else 1.0
        per_share_premium += side_sign * mid * leg.ratio_qty
    per_unit_premium = per_share_premium * 100.0  # one contract = 100 shares

    # Strategy-specific defined-risk checks.
    max_loss, collateral, stress_loss = _compute_risk_metrics(
        proposal, per_unit_premium, account, stress_move_pct
    )

    if proposal.strategy in {OptionsStrategy.CASH_SECURED_PUT, OptionsStrategy.COVERED_CALL}:
        if collateral is None:
            reasons.append("Collateral-based strategy lacks required collateral information.")
        elif proposal.strategy == OptionsStrategy.CASH_SECURED_PUT:
            required = collateral * qty
            if required > buying_power:
                reasons.append(
                    f"Insufficient buying power for CSP collateral (${required:,.2f} needed)."
                )
        elif proposal.strategy == OptionsStrategy.COVERED_CALL:
            owned_shares = sum(
                float(p.get("qty", 0))
                for p in positions
                if p.get("symbol") == proposal.symbol and p.get("side") == "long"
            )
            if owned_shares < qty * 100:
                reasons.append(
                    f"Covered call requires {qty * 100} long shares; account holds {owned_shares:.0f}."
                )

    # Buying power for debit strategies.
    if per_unit_premium > 0 and per_unit_premium * qty > buying_power:
        reasons.append(f"Net debit ${per_unit_premium * qty:,.2f} exceeds buying power.")

    # Max loss. For defined-risk spreads the stressed loss equals the max loss,
    # so this is the plain 2%-of-equity rule. For collateralized shorts it is
    # the loss at an adverse move, because the to-zero figure would veto every
    # cash-secured put ever written.
    if max_loss is None or stress_loss is None:
        reasons.append("Unable to compute defined loss for the proposed strategy.")
    else:
        max_allowed_loss = equity * (max_loss_pct / 100.0)
        if stress_loss * qty > max_allowed_loss:
            reasons.append(
                f"Risk-sized loss ${stress_loss * qty:,.2f} exceeds {max_loss_pct}% of equity (${max_allowed_loss:,.2f})."
            )

    # No undefined-risk legs: every short leg must be paired with a long leg of
    # the same type/expiry in a 1:1 ratio, unless the strategy is explicitly
    # collateralized (CSP/covered call).
    if proposal.strategy not in {
        OptionsStrategy.CASH_SECURED_PUT,
        OptionsStrategy.COVERED_CALL,
    }:
        short_legs = [leg for leg in proposal.legs if leg.side == "sell"]
        long_legs = [leg for leg in proposal.legs if leg.side == "buy"]
        for short in short_legs:
            hedge = next(
                (
                    long
                    for long in long_legs
                    if long.option_type == short.option_type
                    and long.expiry == short.expiry
                    and long.ratio_qty == short.ratio_qty
                    and long.strike != short.strike
                ),
                None,
            )
            if hedge is None:
                reasons.append(
                    f"Short leg {short.symbol} is unhedged; only defined-risk spreads are allowed."
                )

    return RiskGateResult(
        approved=len(reasons) == 0,
        reasons=reasons,
        max_loss_usd=max_loss * qty if max_loss is not None else None,
        stress_loss_usd=stress_loss * qty if stress_loss is not None else None,
        net_credit_debit=per_unit_premium,
        collateral_required=collateral * qty if collateral is not None else None,
    )


def _compute_risk_metrics(
    proposal: OptionsStrategyProposal,
    per_unit_premium: float,
    account: Mapping[str, Any],
    stress_move_pct: float = 20.0,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (max_loss_per_unit, collateral_per_unit, stress_loss_per_unit).

    ``per_unit_premium`` is the net premium per spread unit computed from the
    current bid/ask mid; positive for debit, negative for credit.

    ``max_loss`` is the honest worst case, including the to-zero case for a
    cash-secured put. ``stress_loss`` is what the equity-percentage rule is
    applied to; for every defined-risk structure the two are identical, and
    they only diverge for collateralized shorts.
    """
    strategy = proposal.strategy
    legs = proposal.legs
    per_share_premium = per_unit_premium / 100.0
    # Credit received per share (0 for a net debit).
    credit_per_share = max(0.0, -per_share_premium)

    def defined(loss: float) -> tuple[float, None, float]:
        """A defined-risk structure: worst case and sizing loss are the same."""
        return loss, None, loss

    if strategy in (OptionsStrategy.LONG_CALL, OptionsStrategy.LONG_PUT):
        # Long premium: the debit paid is the whole risk.
        return defined(max(0.0, per_unit_premium))

    if strategy == OptionsStrategy.CASH_SECURED_PUT:
        put_strikes = [leg.strike for leg in legs if leg.strike is not None]
        if not put_strikes:
            return None, None, None
        strike = max(put_strikes)
        # Worst case is assignment with the stock at zero, less the credit kept.
        max_loss = max(0.0, strike - credit_per_share) * 100.0
        # Sizing case: assigned with the stock stress_move_pct below the strike.
        stress_loss = max(0.0, strike * (stress_move_pct / 100.0) - credit_per_share) * 100.0
        return max_loss, strike * 100.0, stress_loss

    if strategy == OptionsStrategy.COVERED_CALL:
        # The short call caps upside on shares already owned; it adds no new
        # downside. Share ownership is enforced separately, so the incremental
        # risk of the options leg really is zero.
        return 0.0, None, 0.0

    # Spreads: collect put/call legs with strikes.
    put_strikes = sorted(
        leg.strike for leg in legs if leg.option_type == "put" and leg.strike is not None
    )
    call_strikes = sorted(
        leg.strike for leg in legs if leg.option_type == "call" and leg.strike is not None
    )

    if strategy in (OptionsStrategy.BULL_CALL_SPREAD, OptionsStrategy.BEAR_PUT_SPREAD):
        # Debit verticals: risk is the net debit paid.
        strikes = call_strikes if strategy == OptionsStrategy.BULL_CALL_SPREAD else put_strikes
        if len(strikes) < 2:
            return None, None, None
        return defined(max(0.0, per_unit_premium))

    if strategy == OptionsStrategy.BULL_PUT_SPREAD:
        if len(put_strikes) < 2:
            return None, None, None
        width = abs(put_strikes[-1] - put_strikes[0])
        # Credit spread: max loss per contract = (width - net_credit_per_share) * 100
        return defined(max(0.0, width - credit_per_share) * 100.0)

    if strategy == OptionsStrategy.BEAR_CALL_SPREAD:
        if len(call_strikes) < 2:
            return None, None, None
        width = abs(call_strikes[-1] - call_strikes[0])
        return defined(max(0.0, width - credit_per_share) * 100.0)

    if strategy == OptionsStrategy.IRON_CONDOR:
        if not put_strikes or not call_strikes:
            return None, None, None
        put_width = abs(put_strikes[-1] - put_strikes[0])
        call_width = abs(call_strikes[-1] - call_strikes[0])
        # Only one side can finish in the money, so the risk is the wider wing.
        wing = max(put_width, call_width)
        return defined(max(0.0, wing - credit_per_share) * 100.0)

    return None, None, None


def reconcile_direction(
    proposal: OptionsStrategyProposal, final_action: str
) -> tuple[bool, str]:
    """Return (matches, reason) comparing the options plan to the final signal.

    The options plan is only executed if its directional bias matches the final
    risk-adjusted decision. ``final_action`` is one of the equity signals
    (BUY/HOLD/SELL/LONG/NEUTRAL/SHORT).
    """
    final_dir = _direction_for_action(final_action)
    if final_dir == "neutral" and proposal.strategy == OptionsStrategy.NONE:
        return True, "Final signal is neutral and no options trade is planned."
    if proposal.direction == final_dir:
        return True, f"Options plan direction ({proposal.direction}) matches final signal."
    return False, (
        f"Options plan direction ({proposal.direction}) does not match "
        f"final signal direction ({final_dir})."
    )


def is_options_trade_allowed(config: Optional[Mapping[str, Any]] = None) -> bool:
    """Convenience helper for feature-flag checks."""
    if config is None:
        return False
    return bool(config.get("options_trading_enabled", False))
