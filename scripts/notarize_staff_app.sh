#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${CODESIGN_IDENTITY:-}" ] || [[ "$CODESIGN_IDENTITY" != "Developer ID Application:"* ]]; then
  echo "Set CODESIGN_IDENTITY to the full Developer ID Application certificate name."
  exit 1
fi
if [ -z "${NOTARYTOOL_PROFILE:-}" ]; then
  echo "Set NOTARYTOOL_PROFILE to a saved notarytool keychain profile."
  exit 1
fi

scripts/build_staff_app.sh

VERSION="$(tr -d '[:space:]' < VERSION)"
APP_PATH="$PWD/dist/Event Control Center.app"
DMG_PATH="$PWD/dist/Event Control Center v${VERSION}.dmg"
STAGE_DIR="$PWD/build/staff-dmg"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
ditto "$APP_PATH" "$STAGE_DIR/Event Control Center.app"
ln -s /Applications "$STAGE_DIR/Applications"

rm -f "$DMG_PATH"
hdiutil create -volname "Event Control Center" -srcfolder "$STAGE_DIR" -format UDZO "$DMG_PATH"
codesign --force --timestamp --sign "$CODESIGN_IDENTITY" "$DMG_PATH"
hdiutil verify "$DMG_PATH"

NOTARY_RESULT="$PWD/build/notarization-result.json"
xcrun notarytool submit "$DMG_PATH" --keychain-profile "$NOTARYTOOL_PROFILE" --wait --output-format json > "$NOTARY_RESULT"
if ! python3 - "$NOTARY_RESULT" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as result_file:
    result = json.load(result_file)
print("Apple notarization:", result.get("status", "Unknown"))
sys.exit(0 if result.get("status") == "Accepted" else 1)
PY
then
  echo "Apple did not accept the disk image. Inspect $NOTARY_RESULT and the notarytool log."
  exit 1
fi

xcrun stapler staple "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"
echo "Ready for staff: $DMG_PATH"
