# Options Alpha Web UI

This directory contains the Dash and Flask application for Options Alpha: an app shell with sidebar navigation, a live trading dashboard, an Options Desk showing risk-gate verdicts, and the agent audit trail.

## Structure

- `app_dash.py`: Dash application factory, auth, and server entry point
- `layout.py`: Assembles the shell around the page containers
- `components/`: Page and panel builders
  - `app_shell.py`: Sidebar, top bar, `panel()`, `kpi_tile()`, `segmented()`
  - `dashboard.py`, `options_desk.py`, `analysis.py`, `backtest_panel.py`, …
- `callbacks/`: One module per surface; all data binding lives here
- `utils/`: Utility functions
  - `charts.py`: Every Plotly figure in the app, plus the shared chart theme
    and the validated categorical palette
  - `report_rendering.py`: Markdown/table rendering for agent reports
  - `state.py`: Application state management
  - `styles.py`: Legacy Gradio-era CSS constants; not used by the Dash UI
- `assets/`: Stylesheets, served alphabetically by Dash
  - `custom.css`: Older component styles
  - `dashboard.css`: Design tokens and the app shell / chart component styles
    (loaded second, so it wins on ties)

## Running the Web UI

You can run the web UI using the helper script:

```bash
python run_webui_dash.py
```

Or directly from Python:

```python
from webui.app_dash import run_app

run_app(port=7860, debug=True)
```

## Charts

Every figure is built in `utils/charts.py` so the app reads as one system.
Two conventions there are load-bearing:

- **No dual y-axes.** Price and volume are stacked subplot rows sharing one
  x-axis, never two scales on one plot.
- **The categorical palette is validated, not eyeballed** — it clears the
  lightness, chroma, colour-vision-deficiency, and contrast checks against
  this app's near-black surface. Up/down green/red is a separate polarity
  scale, kept distinct so a series colour cannot impersonate a P/L sign.

Surfaces: account equity curve with a range selector, portfolio allocation
donut and long/short/cash composition, unrealized P/L per position, recorded
decision history, candlestick + volume with EMA overlays, options payoff at
expiry with breakevens, expiry runway, backtest equity curve, and LLM spend
per day.

## Features

- Interactive stock charts with technical indicators
- Real-time agent status updates with parallel execution support
- Detailed analysis reports in a tabbed interface
- Configurable analysis parameters (ticker, date, analysts, LLMs)
- Parallel analyst execution for faster analysis with API rate limiting
- Prompt and tool-output inspection for debugging and audit review
- Alpaca paper-trading-first account controls, with optional order execution when explicitly enabled
- Dark mode UI optimized for financial data visualization

## Dependencies

- Dash: Web application framework (v3.0+)
- Flask: Backend server
- Plotly: Interactive charts
- Dash Bootstrap Components: UI components
- Pandas: Data manipulation
- yfinance: Financial data retrieval

## Customization

You can customize the UI by modifying the `app_dash.py` file and the CSS in the `assets/custom.css` file.

## Troubleshooting

- If you encounter an error related to `app.run_server`, make sure you're using `app.run` instead, as newer versions of Dash (3.0+) have deprecated the `run_server` method. 
