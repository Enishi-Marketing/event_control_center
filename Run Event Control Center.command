#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python environment not found."
  echo "Run this once from the Event Control Center folder:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r requirements.txt"
  read -r "?Press Return to close…"
  exit 1
fi

if ! command -v swift >/dev/null 2>&1; then
  echo "Swift is not available on this Mac. Install Xcode or the Xcode Command Line Tools."
  read -r "?Press Return to close…"
  exit 1
fi

cd "$SCRIPT_DIR"
exec env ECC_BACKEND_ROOT="$SCRIPT_DIR" ECC_PYTHON="$PYTHON_BIN" \
  swift run --package-path swiftui
