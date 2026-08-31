#!/usr/bin/env bash
# Provision a fresh Ubuntu VM to run Options Alpha 24/7.
#
#   curl -fsSL https://raw.githubusercontent.com/Aashir01/Alpaca-Trading-Agents/main/deploy/setup.sh | bash
#
# or, from a clone:  bash deploy/setup.sh
#
# Installs Python and uv, pulls the repo, installs dependencies, and registers
# a systemd service that restarts on crash and comes back after a reboot. It
# does not write secrets: you create .env yourself in the step it prints.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Aashir01/Alpaca-Trading-Agents.git}"
APP_DIR="${APP_DIR:-$HOME/options-alpha}"
SERVICE_NAME="optionsalpha"

echo "==> Installing system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip git curl

# The Alpaca MCP server is fetched on demand with uvx, so uv has to exist for
# the broker path to work at all.
if ! command -v uv >/dev/null 2>&1; then
    echo "==> Installing uv (required by the Alpaca MCP server)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    grep -q 'HOME/.local/bin' "$HOME/.bashrc" 2>/dev/null \
        || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
fi

echo "==> Fetching the application"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull --ff-only
else
    git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> Installing Python dependencies"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

echo "==> Registering the systemd service"
UV_BIN_DIR="$HOME/.local/bin"
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<UNIT
[Unit]
Description=Options Alpha autonomous options trading desk
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
Environment=WEBUI_PRODUCTION=true
Environment=PATH=${UV_BIN_DIR}:/usr/local/bin:/usr/bin:/bin
ExecStart=${APP_DIR}/.venv/bin/python run_webui_dash.py --server-name 0.0.0.0 --port 7860
Restart=always
RestartSec=10
StandardOutput=append:${APP_DIR}/logs/app.log
StandardError=append:${APP_DIR}/logs/app.log

[Install]
WantedBy=multi-user.target
UNIT

mkdir -p "${APP_DIR}/logs"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

# IV rank needs one observation per day and Alpaca exposes no historical-IV
# endpoint, so a missed day is a day that cannot be recovered.
echo "==> Scheduling the daily IV snapshot"
CRON_LINE="5 13 * * 1-5 cd ${APP_DIR} && ${APP_DIR}/.venv/bin/python scripts/record_iv_history.py --symbols SPY QQQ NVDA AAPL MSFT TSLA AMD >> ${APP_DIR}/logs/iv.log 2>&1"
( crontab -l 2>/dev/null | grep -v record_iv_history || true; echo "$CRON_LINE" ) | crontab -

cat <<DONE

Provisioned. Two things left, both yours:

  1. Create ${APP_DIR}/.env  (start from env.sample)
     It must set ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_USE_PAPER=True,
     the LLM keys, and WEBUI_PASSWORD. Without WEBUI_PASSWORD the app refuses
     to bind publicly, by design: this UI can place orders.

  2. Start it:
       sudo systemctl start ${SERVICE_NAME}
       journalctl -u ${SERVICE_NAME} -f          # follow the logs

  Then confirm the broker path end to end:
       cd ${APP_DIR} && ./.venv/bin/python scripts/verify_mcp.py

  Open the firewall for 7860 in your cloud console, then browse to
  http://<your-vm-ip>:7860 and sign in.

DONE
