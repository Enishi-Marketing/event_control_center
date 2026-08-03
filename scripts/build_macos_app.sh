#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Could not find $PYTHON_BIN. Create the virtual environment and install requirements first."
  exit 1
fi

export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$PWD/.pyinstaller}"

VERSION="$(tr -d '[:space:]' < VERSION)"

"$PYTHON_BIN" -m PyInstaller EventControlCenter.spec --noconfirm --clean

APP_PATH="dist/Event Control Center.app"
ZIP_PATH="dist/Event Control Center v${VERSION}.zip"
LATEST_ZIP_PATH="dist/Event Control Center.zip"

if [ ! -d "$APP_PATH" ]; then
  echo "Build finished, but $APP_PATH was not created."
  exit 1
fi

xattr -cr "$APP_PATH"
codesign --force --deep --sign - "$APP_PATH"

rm -f "$ZIP_PATH" "$LATEST_ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ZIP_PATH"
cp "$ZIP_PATH" "$LATEST_ZIP_PATH"

echo "Built $APP_PATH"
echo "Created $ZIP_PATH"
echo "Updated $LATEST_ZIP_PATH"
