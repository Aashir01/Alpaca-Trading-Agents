<div align="center">

# Options Alpha

### An autonomous multi-agent options trading desk, built on Alpaca

**14 LLM agents research a position. Arithmetic decides whether it trades.**

Built by [@Aashir01](https://github.com/Aashir01) for the
[Alpaca AI Trading Agents Hackathon](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon)

[![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Alpaca](https://img.shields.io/badge/Alpaca-paper%20trading-FFD100)](https://alpaca.markets/)
[![LangGraph](https://img.shields.io/badge/LangGraph-multi--agent-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![Tests](https://img.shields.io/badge/tests-355%20passing-22D07F)](#testing)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

[Quick Start](#quick-start) · [How It Works](#how-it-works) · [The Risk Gate](#the-risk-gate) ·
[The App](#the-app) · [Configuration](#configuration) · [Testing](#testing)

</div>

---

## What this is

A trading system where a team of specialised LLM agents debates a position, and a
**deterministic risk gate** — pure arithmetic over live bid/ask — decides whether that
position is allowed to exist, how large it can be, and what price it goes out at.

The agents are good at reading market context and choosing the *shape* of a trade. They are
not a source of truth for the numbers that decide risk. Every figure that could lose money
is recomputed from the live option chain before an order reaches the broker, so a model that
hallucinates a $99.99 premium on a $2.55 spread cannot move the order price by a cent.

Everything runs against **Alpaca's paper trading environment**.

<div align="center">
<img src="assets/screenshots/dashboard.png" alt="Options Alpha dashboard" width="100%">
<em>Live dashboard — account KPIs, allocation, and the agent pipeline mid-run</em>
</div>

---

## How it works

An analysis run is a LangGraph state machine. Fourteen agents, four stages, one gate:

```
                       ┌──────────────────────────────────────┐
   Market ─┐           │  Analysts run in parallel             │
   Social ─┤           │  Each writes an evidence-scored       │
   News   ─┼──────────▶│  report into shared state             │
   Fund.  ─┤           └──────────────────────────────────────┘
   Macro  ─┘                          │
                                      ▼
                     Bull Researcher ⇄ Bear Researcher      ← structured debate
                                      │
                                      ▼
                             Research Manager                ← picks a side
                                      │
                                      ▼
                                   Trader                    ← direction + conviction
                                      │
                                      ▼
                    ╔═════════════════════════════════════╗
                    ║       OPTIONS STRATEGIST            ║  ← LLM picks a structure
                    ║  long call · vertical · condor      ║
                    ║  CSP · covered call · none          ║
                    ╠═════════════════════════════════════╣
                    ║       OPTIONS RISK GATE             ║  ← deterministic veto
                    ║  no naked shorts · loss cap         ║
                    ║  liquidity · collateral · repricing ║
                    ╚═════════════════════════════════════╝
                                      │
                                      ▼
                Risky ⇄ Safe ⇄ Neutral  →  Risk Judge        ← final risk-adjusted call
                                      │
                                      ▼
                       Direction reconciliation
                                      │
                                      ▼
                        Alpaca multi-leg (MLEG) order
```

### Where the AI stops and arithmetic starts

This split is the whole design. It is enforced in code, not by prompt instruction:

| Decision | Owner |
| --- | --- |
| Which structure to trade | **LLM** |
| Which strikes and expiries | **LLM**, restricted to contracts present in the live chain |
| Net premium of the position | **Recomputed from live bid/ask** — never the model's estimate |
| Max loss and position sizing | **Recomputed** from strikes and live premium |
| The order's limit price | **Derived from the gate's premium**, not the model's |
| Whether the trade happens at all | **Deterministic risk gate** |

The Options Strategist proposes off the *Trader's* signal. The Risk Judge may then flip the
signal. Before submission, the executor re-runs the entire gate against fresh quotes and
**drops any plan whose direction no longer matches** the final decision. Approval at proposal
time is not approval at order time.

---

## The Risk Gate

Every rule is arithmetic over the live chain. Any single failure vetoes the trade.

| Rule | What it enforces |
| --- | --- |
| **No undefined risk** | Every short leg must be paired with a long leg of the same type and expiry at a different strike, or be fully collateralized. A naked short is never submitted. |
| **Loss cap** | Risk-sized loss must stay under `OPTIONS_MAX_LOSS_PCT` of account equity. |
| **Liquidity** | Any leg whose bid-ask spread exceeds `OPTIONS_MAX_SPREAD_PCT` of its mid is rejected. Missing or zero quotes are rejected, never assumed. |
| **Buying power** | Net debits are checked against buying power. |
| **Collateral** | A cash-secured put must be fully cash-collateralized; a covered call must be backed by 100 real shares per contract, verified against live Alpaca positions. |
| **Direction reconciliation** | A plan whose direction no longer matches the final risk decision is dropped, not sent. |
| **Fail-closed re-check** | The gate re-runs against fresh quotes immediately before submission. |

<div align="center">
<img src="assets/screenshots/options-desk.png" alt="Options Desk" width="100%">
<em>Options Desk — the model's proposal beside the gate's independently recomputed numbers</em>
</div>

### Honest worst-case reporting

A cash-secured put's true worst case is assignment with the stock at zero. That number is
honest but useless for sizing — applied literally it would veto every CSP ever written. So
the gate reports **both**:

- `max_loss_usd` — the real worst case, to zero, less the credit received.
- `stress_loss_usd` — the loss at `OPTIONS_STRESS_MOVE_PCT` below the short strike, which is
  what the equity limit is actually applied to.

For every defined-risk structure the two are identical. They diverge only for collateralized
shorts — exactly where a single number would mislead.

### IV rank and IV percentile are not the same number

- **IV rank** = `(iv − min) / (max − min) × 100` — where volatility sits in its own range.
- **IV percentile** = the fraction of past observations below current IV.

A series containing one volatility spike produces a **low rank and a high percentile at the
same time**. That is precisely the case where "high IV, sell premium" is the wrong read, so
the strategist is shown both and told to trust the percentile when they disagree.

IV rank needs history to mean anything. The market context reports how many observations
stand behind it, and below `OPTIONS_MIN_IV_HISTORY_DAYS` the model is told the rank is
unreliable and steered toward long-premium structures. Build that history before trading:

```bash
python scripts/record_iv_history.py --symbols SPY QQQ AAPL MSFT NVDA
```

Run it once a day (cron or CI). It records one true ATM observation per symbol — the average
of the ATM call and put in the front expiry, not whichever contract happened to return first.

---

## The App

A navigable application, not a single scrolling page. A fixed sidebar routes seven
workspaces; a sticky top bar keeps equity, day P/L, buying power, market status, and the
paper/live badge visible everywhere.

| Workspace | Purpose |
| --- | --- |
| **Dashboard** | Live KPIs, allocation donut, agent pipeline, positions, options overlay, decisions, orders |
| **Run Analysis** | Configure the agent team, symbols, research depth; launch a run |
| **Agent Reports** | Full audit trail — one tab per agent, including the Options tab |
| **Options Desk** | Proposals, risk-gate verdicts, open contracts, IV history depth |
| **Positions & Orders** | Live Alpaca positions, order history, account detail |
| **Backtest** | Replay strategies over historical data |
| **Settings** | API credentials, safety guardrails, LLM cost monitor |

<div align="center">
<img src="assets/screenshots/run-analysis.png" alt="Run Analysis" width="100%">
<em>Run Analysis — symbols, analyst selection, research depth, and execution controls</em>
</div>

**Design decisions worth knowing:**

- **State is honest.** When Alpaca is not connected the UI says so and points at Settings. It
  never renders a confident `$0.00` — which is what the risk gate's deliberate fail-closed
  zeros would otherwise look like.
- **Navigation preserves state.** Pages are hidden rather than unmounted, so a run in
  progress keeps streaming while you move between workspaces.
- **Short legs stay visible.** Options positions are detected by OCC symbol and tagged
  `OPT LONG` / `OPT SHORT`. A short leg is the risk-bearing side of a spread and is never
  displayed as another long.

<div align="center">
<img src="assets/screenshots/dashboard-positions.png" alt="Positions and orders" width="100%">
<em>Positions, options overlay, and order history — each spread leg keeps its side</em>
</div>

- **No hard CDN dependency for layout.** The shell, grid, tables, and tab strip are styled by
  the app's own stylesheet, so the layout survives a slow or blocked CDN.
- **Responsive.** Below 860px the sidebar collapses to an icon rail and panels reflow.

---

## Quick Start

```bash
git clone https://github.com/Aashir01/Alpaca-Trading-Agents.git
cd Alpaca-Trading-Agents

pip install -r requirements.txt

cp env.sample .env          # add your keys — see Configuration below
python run_webui_dash.py    # http://localhost:7860
```

Or with Docker:

```bash
cp env.sample .env
docker compose up -d --build
```

Set `HOST_PORT` to use a different host port, e.g. `HOST_PORT=7861 docker compose up -d --build`.

**Web UI options:** `--port PORT`, `--server-name HOST`, `--share`, `--debug`.

**CLI:**

```bash
python -m cli.main
```

Accepts single symbols (`NVDA`), crypto (`BTC/USD`), or mixed lists
(`NVDA, ETH/USD, AAPL`).

---

## Configuration

Copy `env.sample` to `.env`. Every variable is documented inline there.

### Required

| Variable | Purpose |
| --- | --- |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Trading and market data — [get keys](https://app.alpaca.markets/signup) |
| `ALPACA_USE_PAPER` | `True` for paper trading. **Keep this True unless you mean it.** |
| `OPENAI_API_KEY` | Default LLM provider and web-search tools |

### Options overlay

Off by default. Turn it on to add the Options Strategist node to the graph:

```bash
OPTIONS_TRADING_ENABLED=True
OPTIONS_DTE_MIN=7              # expiration window scanned, in days
OPTIONS_DTE_MAX=45
OPTIONS_MAX_LOSS_PCT=2.0       # risk-sized loss cap, % of equity
OPTIONS_MAX_SPREAD_PCT=20.0    # reject legs wider than this % of mid
OPTIONS_STRESS_MOVE_PCT=20.0   # adverse move used to size collateralized shorts
OPTIONS_MAX_CONTRACTS=1        # spread units per trade
OPTIONS_MIN_IV_HISTORY_DAYS=20 # below this, IV rank is flagged unreliable
```

### LLM providers

Set `LLM_PROVIDER` in `.env`, the CLI, or the Web UI. Supported: OpenAI, local
OpenAI-compatible endpoints, Google Gemini, Anthropic Claude, xAI, MiniMax, DeepSeek,
Qwen/DashScope, GLM/Zhipu, OpenRouter, Ollama, and Azure OpenAI. Each has its own key in
`env.sample`; provider-specific controls (reasoning effort, thinking level, verbosity) are
preserved.

### Market data

| Variable | Purpose |
| --- | --- |
| `FINNHUB_API_KEY` | Stock news, insider sentiment, earnings calendar |
| `FRED_API_KEY` | Macro indicators for the Macro Analyst |
| `COINDESK_API_KEY` | Crypto news |
| `ALPHA_VANTAGE_API_KEY` | Optional fallback market data |

---

## Python API

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["options_trading_enabled"] = True   # add the Options Strategist to the graph
config["options_max_loss_pct"] = 2.0       # cap risk-sized loss at 2% of equity
config["max_debate_rounds"] = 2
config["allow_shorts"] = False             # investment mode: BUY / HOLD / SELL

graph = TradingAgentsGraph(debug=True, config=config)
final_state, decision = graph.propagate("NVDA", "2025-09-02")

print(decision)
print(final_state["options_strategy_report"])   # proposal + gate verdict
print(final_state["options_trade_plan"])        # None if the gate vetoed it
```

Submitting an approved plan re-runs the gate before anything reaches the broker:

```python
from tradingagents.execution import submit_options_plan

result = submit_options_plan(
    final_state["options_trade_plan"],
    final_action=decision,   # dropped if direction no longer matches
    qty=1,
)
print(result["submitted"], result["limit_price"], result["error"])
```

---

## Safety

Independent of the options gate, a deterministic guard sits in front of **every** order:

- **Kill switch** — halts all execution immediately, from the UI.
- **Trade size cap**, **concentration limit**, **daily loss breaker**, **drawdown breaker**.
- **Rejection-streak breaker** — repeated broker rejections stop the loop rather than retrying.
- **LLM budget cap** — bounded spend per run, with a live cost monitor.
- **Fail-closed account reads** — when Alpaca can't be reached, sizing sees zero equity and
  refuses to trade rather than sizing against an unverified balance.

---

## Testing

```bash
pip install pytest
python -m pytest tests/ -q
```

**355 tests, fully offline** — every Alpaca and LLM call is mocked.

Coverage worth knowing about:

- **Reachability** — the options node is in the compiled graph, the Trader doesn't bypass it,
  and the state keys it returns survive a LangGraph state update. (LangGraph silently drops
  keys absent from the schema; a node can return a perfect plan and the pipeline see nothing.)
- **Config plumbing** — risk limits set in `.env` actually arrive at the gate.
- **Pricing** — a hallucinated $99.99 premium cannot move a $2.55 order.
- **Risk math** — CSP worst case vs. stress-sized loss, debit verticals, credit spreads,
  iron condor wings, unhedged-short rejection.
- **UI wiring** — every callback target is mounted, no duplicate component ids.

---

## Project structure

```
tradingagents/
├── agents/
│   ├── analysts/           market · social · news · fundamentals · macro
│   ├── researchers/        bull · bear
│   ├── managers/           research manager · risk manager
│   ├── risk_mgmt/          risky · safe · neutral debators
│   ├── options_strategist.py   ← LLM picks the structure
│   ├── options_risk_gate.py    ← deterministic veto (pure, no I/O)
│   └── schemas.py              structured decision + options schemas
├── graph/                  LangGraph setup, propagation, checkpointing
├── dataflows/              Alpaca, options chain, news, macro, crypto
├── execution/              multi-leg order submission + fail-closed re-check
├── safety/                 kill switch, breakers, pre-trade guards
├── prompts/templates/      46 editable Markdown prompts
└── backtest/               engine, metrics, signals

webui/
├── components/             app shell, dashboard, options desk, panels
├── callbacks/              navigation, dashboard, reports, trading
└── assets/                 design system stylesheet

scripts/record_iv_history.py    daily ATM IV snapshots
tests/                          355 offline tests
```

Prompts live in `tradingagents/prompts/templates` as plain Markdown — edit them to retune
agent behaviour without touching code. Set `TRADINGAGENTS_PROMPT_DIR` to override selected
templates from outside the repo.

---

## Disclaimers

This project is for **research and educational purposes**. It is not financial, investment,
or trading advice.

Options trading involves substantial risk and is not suitable for every investor. Read
[Characteristics and Risks of Standardized Options](https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document)
before trading options with real capital. This system is built and tested against Alpaca's
paper trading environment; paper results are hypothetical and do not represent actual trading
or guarantee future results.

Trading performance depends on the backbone model, temperature, trading period, data quality,
and other non-deterministic factors. Do your own due diligence.

---

## Credits and license

Released under the [Apache License 2.0](LICENSE).

This project began as a fork of [AlpacaTradingAgent](https://github.com/huygiatrng/AlpacaTradingAgent),
which is itself built on the [TradingAgents](https://github.com/TauricResearch/TradingAgents)
multi-agent framework by Tauric Research. The multi-agent analyst/researcher/risk-debate
architecture originates there; the options overlay, deterministic risk gate, application
shell, and dashboard in this repository are my own work. Attribution is retained as Apache
2.0 requires.

```bibtex
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework},
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138},
}
```
