# Quick Start

From zero to a first multi-agent analysis in about five minutes.

## 1. Install

```bash
git clone https://github.com/Aashir01/Alpaca-Trading-Agents.git
cd Alpaca-Trading-Agents
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure keys

```bash
cp env.sample .env   # Windows: copy env.sample .env
```

Edit `.env` — the minimum to run:

| Key | Where to get it | Required |
|---|---|---|
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | free paper account at [alpaca.markets](https://alpaca.markets) | ✅ |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) (or set `LLM_PROVIDER` to another provider) | ✅ |
| `FINNHUB_API_KEY` | [finnhub.io](https://finnhub.io) — richer news | optional |
| `FRED_API_KEY` | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) — macro analyst | optional |
| `COINDESK_API_KEY` | crypto news | optional |

> **Keep `ALPACA_USE_PAPER=True`.** Everything works against the paper
> API; switch to live only when you have a tested, reviewed setup and
> accept the risk.

### Optional: arm the options overlay

Off by default. To add the Options Strategist and its risk gate to the graph:

```bash
OPTIONS_TRADING_ENABLED=True
OPTIONS_MAX_LOSS_PCT=2.0     # cap risk-sized loss at 2% of equity
```

IV rank only means something with history behind it, so start recording it
now — it takes calendar days to become useful:

```bash
python scripts/record_iv_history.py --symbols SPY QQQ AAPL MSFT NVDA
```

## 3. Run

```bash
python run_webui_dash.py
```

Open the printed URL (usually `http://127.0.0.1:7860`), then:

1. Go to **Settings** and add your API keys if you skipped step 2.
2. Open **Run Analysis** — enter symbols (stocks `NVDA, AAPL`, crypto
   `BTC/USD`, or a mix), pick your LLM provider and research depth.
3. Press **Start Analysis**. Switch to **Dashboard** to watch the agent
   pipeline stream live, or **Agent Reports** to read each agent's output
   as it lands.
4. With the overlay armed, **Options Desk** shows the proposed structure
   beside the risk gate's independently recomputed numbers.
5. Execute the recommendation manually, or enable auto-execution and
   recurring scheduled analysis.

Prefer a terminal? `python -m cli.main` runs the same pipeline
interactively.

## 4. Verify your setup

```bash
pip install pytest
python -m pytest tests/ -q
```

355 tests, deterministic (no network, no live keys) — they should all pass
on a fresh clone.

## 5. Where results live

- **Reports & audit trail**: `eval_results/<symbol>/TradingAgentsStrategy_logs/runs/`
  — every prompt, tool call, LLM call (with token usage), and the final state.
- **Decision log**: `~/.tradingagents/memory/trading_memory.md` — every
  final decision, later resolved with realized returns.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Alpaca API key or secret not found` | `.env` not loaded or keys empty — recheck step 2. |
| `unauthorized` from Alpaca | Keys expired or live keys used against paper — regenerate paper keys. |
| Analysis stalls at an analyst | Usually a rate limit; lower research depth or increase the start delays in settings. |
| Crypto symbol not found | Use the slash format: `BTC/USD`, not `BTCUSD`. |
| Dashboard shows "Alpaca not connected" | Expected without keys — the UI refuses to render a fake `$0.00`. Add keys in **Settings**. |
| Options Desk says "Disabled" | Set `OPTIONS_TRADING_ENABLED=True` in `.env` and restart. |
| Every options trade gets vetoed | Check the veto reason on the Options Desk — usually a wide bid-ask spread or a loss above `OPTIONS_MAX_LOSS_PCT`. |

Next: read [ARCHITECTURE.md](ARCHITECTURE.md) for how the pipeline works
inside.
