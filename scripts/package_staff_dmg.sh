#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Free staff distribution: an ad hoc signature keeps the bundled binaries
# valid, while each recipient approves first launch in macOS Settings.
unset CODESIGN_IDENTITY
scripts/build_staff_app.sh

VERSION="$(tr -d '[:space:]' < VERSION)"
DMG_PATH="$PWD/dist/Event Control Center v${VERSION}.dmg"
STAGE_DIR="$PWD/build/staff-dmg"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
ditto "$PWD/dist/Event Control Center.app" "$STAGE_DIR/Event Control Center.app"
ln -s /Applications "$STAGE_DIR/Applications"
cat > "$STAGE_DIR/Install Event Control Center.txt" <<'EOF'
EVENT CONTROL CENTER — INSTALL ON A STAFF MAC

1. Drag Event Control Center.app onto Applications in this window.
2. Open Event Control Center from Applications.
3. If macOS blocks the first launch, open System Settings > Privacy & Security.
   Scroll to Security, click Open Anyway, enter your Mac login password,
   then click Open. The button appears after you first try to open the app.
4. In the app's Settings, choose your shared-drive Events folder and local
   Events folder, then save.

The app and its Python backend are included. No terminal, Python, or Swift
installation is needed. The app checks for signed updates when it opens and
installs them automatically when a new release is available. Keep macOS
security settings enabled.
EOF

rm -f "$DMG_PATH"
hdiutil create -volname "Event Control Center" -srcfolder "$STAGE_DIR" -format UDZO "$DMG_PATH"
hdiutil verify "$DMG_PATH"
shasum -a 256 "$DMG_PATH" > "$DMG_PATH.sha256"
echo "Ready for staff with first-launch approval: $DMG_PATH"
