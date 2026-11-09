#!/usr/bin/env bash
# One-time setup for macOS (Apple Silicon or Intel). Re-runnable; each step reports success/failure
# instead of aborting, so read the summary at the end.  Requires Homebrew (https://brew.sh).
set -u
cd "$(dirname "$0")/.."
ok=(); bad=()
step() { local name="$1"; shift; echo "==> $name"; if "$@"; then ok+=("$name"); else bad+=("$name"); fi; }

command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }

# --- design-time tools
step "KiCad (app + kicad-cli)"      brew install --cask kicad
step "ngspice (circuit simulation)" brew install ngspice
step "Java 21 (Freerouting)"        brew install openjdk@21
step "cairo (PCB renders)"          brew install cairo
step "Freerouting 2.1.0 jar"        bash -c 'mkdir -p tools/freerouting && [ -f tools/freerouting/freerouting.jar ] || curl -fL -o tools/freerouting/freerouting.jar https://github.com/freerouting/freerouting/releases/download/v2.1.0/freerouting-2.1.0.jar'

# --- firmware + bench tools
step "ARM GCC toolchain"            brew install --cask gcc-arm-embedded
step "OpenOCD"                      brew install open-ocd
step "dfu-util (USB DFU flashing)"  brew install dfu-util
step "stlink tools"                 brew install stlink

# --- python environment (system python3 is fine; KiCad's own python is only needed for generator/)
step "python venv + packages"       bash -c 'python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt'

KCLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
step "kicad-cli on PATH"            bash -c "[ -x $KCLI ] && mkdir -p ~/.local/bin && ln -sf $KCLI ~/.local/bin/kicad-cli"

echo; echo "OK:     ${ok[*]:-none}"; echo "FAILED: ${bad[*]:-none}"
cat <<'MSG'

Manual / optional:
  - STM32CubeMX (needs a free ST account): https://www.st.com/en/development-tools/stm32cubemx.html
  - PulseView/sigrok for a USB logic analyzer: https://sigrok.org/wiki/Downloads
  - Add ~/.local/bin to PATH if `kicad-cli --version` is not found.
  - Activate the venv in new shells:  source .venv/bin/activate
Then run:  make check
MSG
