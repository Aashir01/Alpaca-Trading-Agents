#!/usr/bin/env bash
# Provision a fresh Ubuntu or Oracle Linux / RHEL VM to run Options Alpha 24/7.
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
REPO_REF="${REPO_REF:-main}"
# A systemd service cannot run out of a home directory under SELinux: files
# there are labelled user_home_t, which init_t may neither read (so the
# EnvironmentFile fails) nor write (so the log file fails). /opt is usr_t and
# works, so it is the default wherever SELinux is enforcing.
if [ -z "${APP_DIR:-}" ]; then
    if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" = "Enforcing" ]; then
        APP_DIR="/opt/options-alpha"
    else
        APP_DIR="$HOME/options-alpha"
    fi
fi
SERVICE_NAME="optionsalpha"
RUN_USER="${SUDO_USER:-$USER}"
# Free-tier shapes ship as little as 512 MB of RAM. Resolving this dependency
# tree needs several times that, and pip will wedge the whole box rather than
# fail cleanly, so swap is provisioned before anything heavy runs.
SWAP_GB="${SWAP_GB:-4}"
SWAPFILE="/swapfile-optionsalpha"

total_ram_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$total_ram_mb" -lt 1900 ] && [ ! -f "$SWAPFILE" ]; then
    echo "==> Only ${total_ram_mb}MB RAM: adding ${SWAP_GB}G of swap first"
    sudo fallocate -l "${SWAP_GB}G" "$SWAPFILE" || sudo dd if=/dev/zero of="$SWAPFILE" bs=1M count=$((SWAP_GB*1024)) status=none
    sudo chmod 600 "$SWAPFILE"
    sudo mkswap -q "$SWAPFILE" >/dev/null
    sudo swapon "$SWAPFILE"
    grep -q "$SWAPFILE" /etc/fstab || echo "$SWAPFILE none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Installing system packages"
if command -v dnf >/dev/null 2>&1; then
    # Oracle Linux / RHEL / Rocky. The distro python is 3.9 on OL9 and this
    # project needs 3.10+, so a parallel-installable interpreter is used.
    PY_PKG="${PY_PKG:-python3.11}"
    sudo dnf install -y -q --setopt=install_weak_deps=False         "$PY_PKG" "${PY_PKG}-pip" "${PY_PKG}-devel" git curl gcc
    PYTHON_BIN="$(command -v "$PY_PKG")"
else
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-venv python3-pip git curl
    PYTHON_BIN="$(command -v python3)"
fi

python_ok=$("$PYTHON_BIN" -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')
if [ "$python_ok" != "1" ]; then
    echo "ERROR: $PYTHON_BIN is $("$PYTHON_BIN" -V); this project needs Python 3.10 or newer." >&2
    exit 1
fi

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
if [ ! -d "$APP_DIR" ]; then
    sudo mkdir -p "$APP_DIR"
    sudo chown "$RUN_USER:$RUN_USER" "$APP_DIR"
fi
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch --depth 1 origin "$REPO_REF"
    git -C "$APP_DIR" checkout -q FETCH_HEAD
elif [ -f "$APP_DIR/requirements.txt" ]; then
    # A source tree was placed here by hand -- an unpacked tarball, rsync, or a
    # bind mount. Private repos have no credentials on a fresh VM, and putting
    # a token on the box to fetch code we can just copy there is a worse trade.
    echo "    using the existing source tree in $APP_DIR (no checkout)"
else
    git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> Installing Python dependencies"
"$PYTHON_BIN" -m venv .venv
./.venv/bin/pip install -q --upgrade pip
# --no-cache-dir keeps pip from holding whole wheels in a cache it also has to
# copy; on a 512 MB box that alone is the difference between finishing and
# being OOM-killed.
./.venv/bin/pip install -q --no-cache-dir -r requirements.txt

# chromadb refuses to import against sqlite < 3.35, and Oracle Linux 9 ships
# 3.34.1 with no newer package. pysqlite3-binary has no aarch64 wheel, so the
# library is built here and the interpreter is pointed at it through
# LD_LIBRARY_PATH -- no application code has to know about any of this.
SQLITE_PREFIX="/opt/sqlite"
sqlite_ver=$(./.venv/bin/python -c 'import sqlite3; print(sqlite3.sqlite_version)')
if [ "$(printf '%s
3.35.0
' "$sqlite_ver" | sort -V | head -1)" != "3.35.0" ]    && [ ! -e "$SQLITE_PREFIX/lib/libsqlite3.so.0" ]; then
    echo "==> System sqlite is ${sqlite_ver}; building ${SQLITE_VERSION:-3.46.1} for chromadb"
    SQLITE_TARBALL="${SQLITE_TARBALL:-https://www.sqlite.org/2024/sqlite-autoconf-3460100.tar.gz}"
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/sqlite.tar.gz" "$SQLITE_TARBALL"
    tar -xzf "$tmp/sqlite.tar.gz" -C "$tmp"
    ( cd "$tmp"/sqlite-autoconf-*       && ./configure --prefix="$SQLITE_PREFIX" --disable-static CFLAGS=-O2 >/dev/null       && make -j"$(nproc)" >/dev/null       && sudo make install >/dev/null )
    rm -rf "$tmp"
fi
if [ -e "$SQLITE_PREFIX/lib/libsqlite3.so.0" ]; then
    SQLITE_ENV="Environment=LD_LIBRARY_PATH=${SQLITE_PREFIX}/lib"
else
    SQLITE_ENV=""
fi

echo "==> Registering the systemd service"
UV_BIN_DIR="$HOME/.local/bin"
# firewalld ships enabled on Oracle Linux and blocks the UI port; opening it
# here still leaves the cloud-side security list to the operator.
if command -v firewall-cmd >/dev/null 2>&1 && sudo firewall-cmd --state >/dev/null 2>&1; then
    sudo firewall-cmd --permanent --add-port=7860/tcp >/dev/null
    sudo firewall-cmd --reload >/dev/null
fi
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<UNIT
[Unit]
Description=Options Alpha autonomous options trading desk
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
Environment=WEBUI_PRODUCTION=true
# Without this, Python block-buffers stdout when it is a pipe, so the startup
# banner and every print sit in the buffer instead of reaching the journal.
Environment=PYTHONUNBUFFERED=1
${SQLITE_ENV}
Environment=PATH=${UV_BIN_DIR}:/usr/local/bin:/usr/bin:/bin
ExecStart=${APP_DIR}/.venv/bin/python run_webui_dash.py --server-name 0.0.0.0 --port 7860
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

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

  The host firewall is already open for 7860. You still need an ingress rule
  for TCP 7860 on the subnet's security list in your cloud console, then
  browse to http://<your-vm-ip>:7860 and sign in.

DONE
