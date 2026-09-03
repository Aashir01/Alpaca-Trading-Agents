# Options Alpha — One-Page Technical Write-Up

**Alpaca AI Trading Agents Hackathon** · [github.com/Aashir01/Alpaca-Trading-Agents](https://github.com/Aashir01/Alpaca-Trading-Agents)

**Thesis: 14 LLM agents research a position. Arithmetic decides whether it trades.**
The agents choose the *shape* of a trade. They are never a source of truth for the numbers
that decide risk — every figure that can lose money is recomputed from live bid/ask before
an order reaches the broker.

---

## 1. AI logic

A LangGraph state machine runs **14 agents in 4 teams**, with structured Pydantic outputs
between stages so the next agent receives predictable fields rather than free prose.

| Team | Agents | Job |
|---|---|---|
| **Analysts** (parallel) | Market, Social, News, Fundamentals, Macro | Five views of the same bar, each with its own tools |
| **Research** (debate) | Bull, Bear, Research Manager | Two sides argue; a manager adjudicates on evidence quality, not volume |
| **Trading** | Trader, Options Strategist | Turns the verdict into a plan, then into a defined-risk options structure |
| **Risk** (debate) | Risky, Safe, Neutral, Portfolio Manager | Three stances stress the plan; a judge sizes it or stands aside |

Analysts run in parallel and their reports are fused by the research debate — the
*parallel + debate + critic* pattern the literature converges on. Prompts live as editable
templates on disk and are hot-swappable from the **Agents** page, so behaviour is retuned
without touching code. Persistent memory (ChromaDB) carries dated lessons between runs.

**Every prompt, tool call, tool response, and agent output is persisted per run** under
`eval_results/`, so any decision can be replayed and audited.

## 2. Risk gates — the part the model cannot argue with

Three independent layers, all deterministic Python. **The LLM cannot reach the broker.**

**(a) Options risk gate** (`agents/options_risk_gate.py`) — re-prices *every leg* from live
bid/ask and recomputes net premium and max loss itself, discarding the model's estimate.
Vetoes on: missing/invalid quotes · bid-ask spread wider than 20% of mid · risk-sized loss
above 2% of equity · net debit exceeding buying power · collateral shortfall on a
cash-secured put · any structure whose loss cannot be bounded. It also **re-runs against
fresh quotes immediately before submission** (fail-closed) and drops the plan if the risk
judge flipped direction after the options node ran.

**(b) Safety guardrails** (`safety/guardrails.py`) — checked before every order:
`kill_switch`, `trade_notional`, `concentration`, `daily_loss`, `drawdown`,
`rejection_streak`, plus a daily LLM token budget.

**(c) Position lifecycle** (`execution/position_manager.py`) — a defined-risk structure
bounds what a position *can* lose; it says nothing about when to stop losing it. Legs are
grouped into structures by underlying and expiry (a 4-leg condor is **one** position) and
closed on a stop (1.5× the credit received, or 50% of a debit paid), a profit target (35% of
premium), or a time exit at 21 DTE. Credit and debit need different stops: a debit spread
cannot lose more than it cost, so a credit-style multiple could never fire on one.

Closes go out as a **single MLEG order** — closing a condor leg by leg can partially fill and
leave a naked short, the exact exposure the structure existed to prevent. The loss breakers
**flatten** rather than only veto, because refusing to open is no protection for capital
already committed. Entries and exits are both **idempotent**: the executor refuses to open a
structure that already exists, and the manager will not send a second close while the first
is still working.

## 3. Alpaca infrastructure

Everything runs against **Alpaca paper trading**. Broker calls route through the **official
Alpaca MCP server** (`uvx alpaca-mcp-server`, stdio) when enabled, falling back to
`alpaca-py` if it is unreachable — the transport changes, the gate and guard do not.

| Surface | Used for |
|---|---|
| `TradingClient` | orders, positions, account, `get_clock` |
| `StockHistoricalDataClient` / `CryptoHistoricalDataClient` | OHLCV and quotes |
| `OptionHistoricalDataClient` | option chains and leg quotes for the gate |
| `OrderClass.MLEG` + `OptionLegRequest` | multi-leg spreads, entry and exit |
| `OrderClass.BRACKET` / `OTO` + `StopLoss`/`TakeProfit` | broker-side equity stops (GTC) |
| `GetPortfolioHistoryRequest` | dashboard equity curve |

Equity protective orders live **at Alpaca**, so they fire whether or not the app is running.
Options exits run on a **systemd timer** independent of the agent graph — a stop that only
fires when an analysis happens to be running is not a stop — and the runner asks Alpaca's
clock whether the market is open rather than hard-coding hours.

Deployed on Oracle Cloud (Ampere A1, Oracle Linux 9) via `deploy/setup.sh`: systemd units,
firewalld, and a daily IV-history cron. Basic auth is mandatory before the UI will bind
publicly, because it can place orders.

## 4. What is recorded, and what is not yet proven

An append-only ledger (`tradingagents/ledger.py`) ties every order to the run that produced
it — entries carry the *gate's* recomputed numbers, exits carry the rule that fired verbatim,
and fill status is reconciled from the broker afterwards rather than guessed. **433 tests,
fully offline.**

**Honest limitation:** this deployment has a handful of filled trades. The system demonstrates
*governed autonomy* — bounded authority, deterministic risk, full auditability — **not** a
proven edge. Claims about profitability would need far more history than exists here, and the
Backtest page is built to measure exactly that once it does.
