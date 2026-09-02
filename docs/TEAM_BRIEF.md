# Options Alpha — Briefing for our finance lead

**Read time: ~25 minutes. Deadline: Thursday 4 September, 8:00 PM PST.**

You don't need to read code. This explains what we built, how the pieces talk to each
other, and — at the end — the six things only you can decide, in priority order.

The short version: **we have a working autonomous options trading agent with a solid
safety layer, and a strategy that nobody with real markets experience has calibrated yet.**
That calibration is the difference between placing trades and winning.

---

## 1. What we're being judged on

| Criterion | Weight in practice | Who owns it |
|---|---|---|
| **P&L performance** in the Alpaca paper account | Highest — it's listed first | **You** (strategy) + me (execution) |
| Technology implementation (Alpaca API, MCP/CLI, options) | Strong | Me — API done, **MCP/CLI missing** |
| Creativity & originality | Medium | Both |
| Presentation & execution | Medium | Both |
| Social engagement (up to 5 posts, tag lablab.ai + Alpaca) | Bonus prize | Either |

Hard requirements we must not miss:

- Strategies **must** use options. ✅ Done.
- Must use Alpaca's Trading API + **MCP server or CLI**. 🔴 **We currently use neither — see §7.**
- Submission must run on a **brand-new paper account** funded to **$100,000**. ⚠️ Not created yet.
- We must submit that **account ID** — judges use it to read our trading activity.
- One-page write-up covering AI logic, risk gates, and Alpaca infrastructure.

Because P&L is judged from live paper trading activity over the competition window, **every
day the agent isn't trading a calibrated strategy is a day of lost score.**

---

## 2. The system in one paragraph

Fourteen LLM agents research a stock and argue about it. A "Trader" agent turns that
research into a direction (bullish / bearish / neutral) and a conviction level. If the
direction is bullish or bearish, an **Options Strategist** agent picks a defined-risk
options structure to express it. That proposal then hits a **deterministic risk gate** —
plain arithmetic, no AI — which re-prices every leg from live bid/ask, recomputes max loss,
and either approves or vetoes. Approved trades go to Alpaca as multi-leg orders.

**The core design principle:** the AI chooses the *shape* of the trade. Arithmetic decides
whether it's allowed and what it costs. The model's own numbers never touch an order.

---

## 3. Infrastructure — what runs where

```
   YOU / THE UI                     THE ENGINE                      THE MARKET
┌──────────────────┐        ┌───────────────────────┐        ┌──────────────────┐
│ Web app (Dash)   │───────▶│ LangGraph state       │───────▶│ Alpaca Trading   │
│ · Dashboard      │        │ machine               │        │ API (paper)      │
│ · Run Analysis   │◀───────│ 14 agents, 4 stages   │◀───────│ · quotes/bars    │
│ · Options Desk   │        │ + options overlay     │        │ · option chains  │
│ · Reports        │        └───────────┬───────────┘        │ · orders/account │
└──────────────────┘                    │                    └──────────────────┘
                                        │
                          ┌─────────────┴─────────────┐
                          │  Data + memory            │
                          │  · Finnhub (news, earnings)│
                          │  · FRED (macro)           │
                          │  · Reddit, web search     │
                          │  · ChromaDB agent memory  │
                          │  · IV history cache       │
                          └───────────────────────────┘
```

**Key facts:**

- Everything runs against **Alpaca paper trading**. No real money, real market data.
- One "run" = one symbol analysed end-to-end. Takes roughly 2–5 minutes and costs a few
  cents to a few dollars in LLM calls depending on depth.
- Runs can be **scheduled on a loop** (every N hours) or triggered during market hours.
- Every run writes a **full audit trail** — every prompt, every tool call, every decision —
  to disk. If a judge asks "why did it do that?", we can show them.
- A **safety layer** sits in front of every order independently of the agents: kill switch,
  trade size cap, daily-loss breaker, drawdown breaker, concentration limit, and an LLM
  budget cap.

---

## 4. The agent team — who talks to whom

Agents don't message each other directly. They **read from and write to a shared
"state" object** that flows down the pipeline, like a deal memo that each desk annotates
before passing it on. Here's the conversation, in order.

### Stage 1 — The analysts (5 agents, run in parallel)

Each gets the ticker and its own tools. Each writes one report into shared state. In the
default parallel mode they each work from a private copy of the state, so **none of them
sees another's report** — deliberately, so they don't anchor on each other.

| Agent | Data it pulls | Writes |
|---|---|---|
| **Market Analyst** | Alpaca bars, technical indicators | `market_report` |
| **Social Analyst** | Reddit, web search sentiment | `sentiment_report` |
| **News Analyst** | Finnhub news, Google News | `news_report` |
| **Fundamentals Analyst** | Company financials, earnings | `fundamentals_report` |
| **Macro Analyst** | FRED economic data | `macro_report` |

All five reports are then scored and packed into a context bundle so downstream agents
don't blow past the model's context limit.

### Stage 2 — The research debate (3 agents, sequential)

> **Bull Researcher** ⇄ **Bear Researcher** → **Research Manager**

The Bull argues the long case using the five reports. The Bear reads the Bull's argument
and rebuts it. They alternate for N rounds (default 4 rounds = 8 turns; configurable).
Both consult a **persistent memory** of lessons from past trades that resolved badly.

The **Research Manager** then reads the whole debate and writes an `investment_plan` —
a recommendation with a confidence level and a rationale.

*In trading-desk terms: two analysts pitch opposite sides, a PM picks.*

### Stage 3 — The Trader

Reads the investment plan, the account state, and its own memory of past trades. Outputs
`trader_investment_plan` and a `recommended_action`:

- **Investment mode:** `BUY` / `HOLD` / `SELL`
- **Trading mode:** `LONG` / `NEUTRAL` / `SHORT` (shorts enabled)

Plus a **confidence** level (high / medium / low) that the options layer reads.

### Stage 4 — The Options Strategist ⭐ (our differentiator)

This is the node you most need to have opinions about. It runs **only** when the overlay
is enabled, and it sits between the Trader and the risk debate.

It reads: the Trader's direction, the Trader's confidence, and live options market context
(spot price, ATM implied volatility, IV rank, IV percentile, 20-day historical volatility,
days to earnings, and the near-the-money option chain).

It writes: `options_strategy_report` (human-readable) and `options_trade_plan` (structured,
or `None` if vetoed).

It may choose from: `long_call`, `long_put`, `bull_call_spread`, `bear_put_spread`,
`bull_put_spread`, `bear_call_spread`, `iron_condor`, `cash_secured_put`, `covered_call`,
or `none`.

### Stage 5 — The risk debate (3 agents + judge)

> **Risky Analyst** → **Safe Analyst** → **Neutral Analyst** → **Risk Judge**

Three personas stress-test the trade — one arguing for more aggression, one for caution,
one for balance — rotating for N rounds (default 3 rounds = 9 turns). The **Risk Judge**
issues the final call and a
structured `TradeIntent` that execution can act on mechanically.

**Important:** the Risk Judge can *overrule the Trader* and flip the direction. Our options
plan was built on the Trader's earlier signal, so before submission we check the plan's
direction still matches the final call — and **drop it if it doesn't**.

### Stage 6 — Execution

Equity order goes out via Alpaca (with optional bracket stop/target). Then the options
plan is re-checked through the **entire risk gate again** against fresh quotes, and
submitted as a multi-leg (MLEG) order if it still passes.

### Stage 7 — Learning

The decision is logged as `pending`. Later, once the outcome is known, realized returns are
computed and each agent writes a **reflection** into its own memory, which gets retrieved on
future similar setups.

---

## 5. The risk gate — the part you should audit

This is pure arithmetic. No LLM involvement. Any single failure kills the trade.

| Check | Rule |
|---|---|
| **No naked shorts** | Every short leg must be paired with a long leg, same type and expiry, different strike — or be fully collateralized (CSP / covered call). |
| **Loss cap** | Risk-sized loss ≤ **2% of account equity** (configurable). |
| **Liquidity** | Any leg with bid-ask spread > **20% of mid** is rejected. Missing or zero quotes are rejected, never assumed. |
| **Buying power** | Net debit must fit in buying power. |
| **Collateral** | CSP must be fully cash-collateralized. Covered call must be backed by 100 real shares per contract, verified against live positions. |
| **Direction match** | Plan dropped if the Risk Judge flipped the signal. |
| **Fail-closed re-check** | Gate re-runs on fresh quotes immediately before the order goes out. |

### The exact formulas — please sanity-check these

Net premium per spread is computed from **live bid/ask mid**, not the model's estimate:

```
per_share_premium = Σ (±1 × mid_price × ratio) ,  −1 for short legs, +1 for long
net_premium       = per_share_premium × 100      ,  positive = debit, negative = credit
```

Max loss per structure:

| Structure | Max loss |
|---|---|
| Long call / long put | net debit paid |
| Bull call spread / bear put spread (debit verticals) | net debit paid |
| Bull put spread / bear call spread (credit verticals) | (strike width − credit) × 100 |
| Iron condor | (**wider** wing width − credit) × 100 |
| Cash-secured put | (strike − credit) × 100 — i.e. assignment at zero |
| Covered call | 0 incremental (caps upside on shares we already own) |

**The one judgement call I made that I want you to check:** a cash-secured put's true worst
case is the stock going to zero. That's honest but useless for sizing — applied against a
2%-of-equity cap it would veto every CSP ever written. So the gate reports **two** numbers:

- `max_loss_usd` — the honest worst case (to zero).
- `stress_loss_usd` — the loss if the stock finishes **20% below the short strike**, which
  is what the 2% equity cap is actually applied to.

For every defined-risk spread the two are identical. They only diverge on collateralized
shorts. **Is 20% the right stress move? Should it vary by the underlying's volatility?**
That's your call.

### IV rank vs IV percentile

We compute both, and they are genuinely different:

- **IV rank** = (current IV − 52wk low) / (52wk high − low) × 100
- **IV percentile** = % of past observations below current IV

A single volatility spike gives a *low rank and a high percentile at the same time* — exactly
when "high IV, sell premium" is the wrong read. The strategist is shown both and told to
trust the percentile when they disagree. **Confirm that's the right instruction.**

⚠️ **IV rank needs history we don't have yet.** We have a script that records one true ATM
IV observation per symbol per day. Below 20 stored observations the agent is told the rank
is unreliable and steered toward buying premium rather than selling it. **We need to start
recording IV history on our watchlist immediately — it accrues in calendar days and we
have three.**

---

## 6. What I found that needs your judgement

Three gaps I can fix in hours, but the *rules* have to come from you.

### 🔴 Gap 1 — Nothing ever closes a position

This is the single biggest P&L lever and it's currently missing.

Right now the agent **opens** options positions and never touches them again. No profit
target, no stop, no time-based exit, no roll. Every position rides to expiry.

For a competition scored on P&L over roughly a week, that is close to fatal: a bull call
spread that hits 80% of max profit on day two gives it all back if the stock reverses, and
we'd never take the win.

**What I need from you — specific numbers:**

- Profit target for credit structures (e.g. "close at 50% of max profit"?)
- Profit target for debit structures (e.g. "close at +100% of debit"? "at 80% of max"?)
- Stop loss (e.g. "close at 2× credit received"? "at −50% of debit"?)
- Time stop (e.g. "close everything at 21 DTE regardless"?)
- Earnings rule (e.g. "close any short-premium position before earnings"?)

Give me the thresholds and I'll implement the monitor.

### 🟠 Gap 2 — Iron condors can never actually be selected

The strategy menu offers `iron_condor` for neutral views with high IV. But the code exits
early whenever the Trader says `HOLD`/`NEUTRAL` — so the options agent is never even asked.
Iron condor is unreachable in practice.

That's probably a large missed opportunity, because **most signals are likely to be HOLD**.
A flat directional view with high IV rank is the textbook premium-selling setup.

**Decision for you:** should a `HOLD` signal with high IV rank sell a neutral structure
(iron condor / short strangle-equivalent with wings), or should we stay flat? If yes, what
IV rank threshold and what wing width?

### 🟡 Gap 3 — Strike selection has no rule

The agent sees the near-the-money chain **with deltas** and picks strikes freely. There's no
instruction like "short leg at 20–30 delta, long leg 5–10 points wide". It's improvising.

**What I need:** delta targets per structure, and spread widths. For example:

- Credit spreads: short leg at ~X delta, width $Y
- Debit verticals: long leg ~X delta, short leg ~Y delta
- CSP: short put at ~X delta
- Preferred DTE window (we currently scan 7–45 days — is that right?)

This is probably the highest-value hour you can spend, because it converts a vague prompt
into a rule the model must follow.

---

## 7. Your work queue — prioritized, time-boxed

We have **three days**. Ranked by expected P&L impact per hour of your time.

| # | Task | Time | Why it matters |
|---|---|---|---|
| **1** | **Exit rules** (Gap 1) — give me the five numbers | 1 hr | Biggest P&L lever. Without this we can't take profits. |
| **2** | **Strike selection + DTE rules** (Gap 3) | 1–2 hrs | Turns improvisation into a repeatable edge. |
| **3** | **Watchlist** — 8–12 tickers with genuinely liquid options (penny-wide markets) | 1 hr | Our 20%-spread gate will veto illiquid names all day. Wrong list = no trades. Include which to avoid into earnings. |
| **4** | **Neutral/condor decision** (Gap 2) | 30 min | Potentially unlocks the majority of signals. |
| **5** | **Audit the formulas in §5** | 1 hr | If a judge finds a wrong max-loss formula, our credibility is gone. Especially the CSP stress-sizing choice. |
| **6** | **Sizing rule** — we currently trade a fixed 1 spread per signal | 30 min | Should size scale with conviction, IV rank, or account %? |
| **7** | **The one-page write-up** — the finance narrative | 1 hr | Required submission. You explain *why* the strategy should make money; I'll cover the infra. |

### Please don't spend time on

- Rebuilding the risk gate — it's implemented and covered by 355 passing tests.
- The UI — done.
- Backtesting infrastructure — we don't have time to make it rigorous, and the judges score
  the *live paper account*, not a backtest.

### Things I'm handling

- Implementing whatever exit rules you specify.
- Adding delta/DTE constraints to the agent's instructions.
- Creating the fresh $100k paper account and starting the IV history recording.
- Wiring in Alpaca MCP/CLI — an eligibility requirement we currently fail (see below).

### ⚠️ Two logistics items that could disqualify us

1. **The submission must run on a brand-new paper account funded to $100,000.** Projects on
   reused accounts are explicitly *not eligible for judging*. We need this created and
   trading as early as possible so there's a P&L history to show.
2. 🔴 **We do not currently use Alpaca's MCP server or CLI — and the rules require one of
   them.** I searched the codebase to confirm: we use the Trading API via `alpaca-py`
   throughout, but there is no MCP server integration and no CLI invocation anywhere. The
   challenge states projects "must utilize either Alpaca's MCP server or its CLI tools."
   This is an **eligibility requirement, not a scoring bonus** — I'm treating it as the top
   engineering blocker and wiring it in before anything else. No action needed from you;
   flagging it so you know it's tracked.

---

## 8. Where things live (for reference)

You won't need to open these, but if you want to point at something specific:

| What | File |
|---|---|
| The options agent's instructions (plain English, editable) | `tradingagents/prompts/templates/trader/options_strategy.md` |
| Strategy selection code | `tradingagents/agents/options_strategist.py` |
| **The risk gate + all formulas** | `tradingagents/agents/options_risk_gate.py` |
| Order submission | `tradingagents/execution/options_executor.py` |
| IV rank / chain data | `tradingagents/dataflows/options_data.py` |
| All tunable settings | `env.sample` and `tradingagents/default_config.py` |
| Daily IV recorder | `scripts/record_iv_history.py` |

**The prompt file is plain Markdown.** If you want to change the strategy rules, you can
literally edit that file in English — no code required. Send me your edits or edit it
directly.

---

## 9. How to run it yourself

```bash
cp env.sample .env          # add Alpaca paper keys + an LLM key
pip install -r requirements.txt
python run_webui_dash.py    # opens on http://localhost:7860
```

Then: **Run Analysis** → enter a ticker → **Start Analysis**. Watch the **Dashboard** for the
live agent pipeline, and the **Options Desk** for the proposal, the gate's recomputed
numbers, and the veto reasons.

To arm the options overlay, set in `.env`:

```bash
OPTIONS_TRADING_ENABLED=True
```

The Options Desk showing a **veto reason** is the fastest way to understand the gate's
behaviour — try a wide-spread illiquid ticker and watch it refuse.

---

## 10. The one-sentence ask

**Give me the exit rules and the strike-selection rules by end of Tuesday, and a vetted
liquid watchlist, and I'll have a calibrated agent trading a real strategy with two full
days of P&L on the board before the deadline.**
