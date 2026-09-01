#!/usr/bin/env bash
# Instaluje wszystko, czego potrzeba do pracy z STWIN.box: SDK ST + środowisko Pythona.
# Idempotentny - można uruchamiać wielokrotnie.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="${STDATALOG_SDK:-$REPO_DIR/vendor/stdatalog-pysdk}"
VENV_DIR="$REPO_DIR/.venv"
PYTHON_VERSION="3.12"

echo "==> Katalog projektu: $REPO_DIR"

# --- 1. uv ---------------------------------------------------------------
# Wersje numpy/pandas przypięte przez ST nie mają kół dla najnowszych Pythonów,
# dlatego wymuszamy 3.12 przez uv zamiast używać interpretera systemowego.
if ! command -v uv >/dev/null 2>&1; then
    echo "==> Instaluję uv (menedżer środowisk Pythona)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# --- 2. SDK ST -----------------------------------------------------------
# STDATALOG-PYSDK nie jest publikowane na PyPI - trzeba je sklonować z GitHuba
# razem z submodułami, bo w głównym repo leżą tylko skrypty instalacyjne.
if [ ! -d "$SDK_DIR/.git" ]; then
    echo "==> Klonuję STDATALOG-PYSDK do $SDK_DIR"
    git clone --depth 1 https://github.com/STMicroelectronics/stdatalog-pysdk.git "$SDK_DIR"
fi

if [ ! -f "$SDK_DIR/stdatalog_core/setup.py" ]; then
    echo "==> Pobieram submoduły SDK (potrwa ok. minuty)"
    git -C "$SDK_DIR" submodule update --init --depth 1
fi

CORE_WHL=$(ls "$SDK_DIR"/stdatalog_core/dist/stdatalog_core-*.whl | sort -V | tail -1)
PNPL_WHL=$(ls "$SDK_DIR"/stdatalog_pnpl/dist/stdatalog_pnpl-*.whl | sort -V | tail -1)
echo "==> Znalezione pakiety:"
echo "    $(basename "$CORE_WHL")"
echo "    $(basename "$PNPL_WHL")"

# --- 3. Środowisko -------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Tworzę środowisko na Pythonie $PYTHON_VERSION"
    uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
fi

echo "==> Instaluję pakiety"
uv pip install --quiet --python "$VENV_DIR/bin/python" \
    "$PNPL_WHL" "$CORE_WHL" matplotlib scipy

# --- 4. Ścieżka do SDK ---------------------------------------------------
# Skrypty potrzebują dostępu do stdatalog_examples (LogController), który nie
# wchodzi w skład wheeli. Zapisujemy ścieżkę, żeby nie zgadywać jej w kodzie.
echo "$SDK_DIR" > "$REPO_DIR/.sdk_path"

echo ""
echo "==> Gotowe."
echo ""
echo "    Podłącz STWIN.box kablem USB-C i sprawdź połączenie:"
echo "        ./stwin probe"
echo ""
