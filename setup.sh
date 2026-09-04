#!/usr/bin/env bash
# Installs everything needed to work with the STWIN.box: ST's SDK + a Python environment.
# Idempotent - safe to run repeatedly.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="${STDATALOG_SDK:-$REPO_DIR/vendor/stdatalog-pysdk}"
VENV_DIR="$REPO_DIR/.venv"
PYTHON_VERSION="3.12"

echo "==> Project directory: $REPO_DIR"

# --- 1. uv ---------------------------------------------------------------
# The numpy/pandas versions pinned by ST have no wheels for the newest Pythons,
# so we force 3.12 through uv instead of using the system interpreter.
if ! command -v uv >/dev/null 2>&1; then
    echo "==> Installing uv (Python environment manager)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# --- 2. ST's SDK ---------------------------------------------------------
# STDATALOG-PYSDK is not published on PyPI - it has to be cloned from GitHub
# together with its submodules, because the main repo holds only install scripts.
if [ ! -d "$SDK_DIR/.git" ]; then
    echo "==> Cloning STDATALOG-PYSDK into $SDK_DIR"
    git clone --depth 1 https://github.com/STMicroelectronics/stdatalog-pysdk.git "$SDK_DIR"
fi

if [ ! -f "$SDK_DIR/stdatalog_core/setup.py" ]; then
    echo "==> Fetching the SDK submodules (takes about a minute)"
    git -C "$SDK_DIR" submodule update --init --depth 1
fi

CORE_WHL=$(ls "$SDK_DIR"/stdatalog_core/dist/stdatalog_core-*.whl | sort -V | tail -1)
PNPL_WHL=$(ls "$SDK_DIR"/stdatalog_pnpl/dist/stdatalog_pnpl-*.whl | sort -V | tail -1)
echo "==> Packages found:"
echo "    $(basename "$CORE_WHL")"
echo "    $(basename "$PNPL_WHL")"

# --- 3. Environment ------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Creating the environment on Python $PYTHON_VERSION"
    uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
fi

echo "==> Installing packages"
uv pip install --quiet --python "$VENV_DIR/bin/python" \
    "$PNPL_WHL" "$CORE_WHL" matplotlib scipy bleak

# --- 4. USB permissions (Linux only) --------------------------------------
# Without the SDK's udev rules a regular user cannot open the board over USB.
# Confusingly, ST's library does not report that as an open error - the board
# then looks connected but never answers commands.
if [ "$(uname -s)" = "Linux" ]; then
    RULES_SRC="$SDK_DIR/linux_setup/30-hsdatalog.rules"
    RULES_DST="/etc/udev/rules.d/30-hsdatalog.rules"
    if ! cmp -s "$RULES_SRC" "$RULES_DST"; then
        echo "==> Installing udev rules for board access (requires sudo)"
        sudo cp "$RULES_SRC" "$RULES_DST"
        sudo groupadd -f hsdatalog
        sudo usermod -aG hsdatalog "$USER"
        sudo udevadm control --reload
        # Re-apply permissions to an already plugged-in board, no replug needed.
        sudo udevadm trigger --action=add --subsystem-match=usb
        echo "    NOTE: group membership takes effect on the next login."
    fi
fi

# --- 5. Path to the SDK --------------------------------------------------
# The scripts need access to stdatalog_examples (LogController), which is not
# part of the wheels. We store the path so it does not have to be guessed in code.
echo "$SDK_DIR" > "$REPO_DIR/.sdk_path"

echo ""
echo "==> Done."
echo ""
echo "    Plug the STWIN.box in with a USB-C cable and check the connection:"
echo "        ./stwin probe"
echo ""
