#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  echo "Missing $PYTHON_BIN. Create .venv and install requirements.txt and requirements-build.txt."
  exit 1
fi
if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller is missing. Run: $PYTHON_BIN -m pip install -r requirements-build.txt"
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import cv2, googleapiclient, numpy, PIL, pillow_heif, tqdm' >/dev/null 2>&1; then
  echo "Runtime dependencies are missing. Run: $PYTHON_BIN -m pip install -r requirements.txt"
  exit 1
fi
if [ ! -f assets/templates/Blank_Lightroom/Blank_Lightroom.lrcat ] ||
   [ ! -f assets/templates/Blank_Premiere_Project.prproj ]; then
  echo "Bundled Lightroom or Premiere template is missing from assets/templates."
  exit 1
fi

VERSION="$(tr -d '[:space:]' < VERSION)"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "VERSION must contain a version like 1.2.3."
  exit 1
fi
RELEASE_REPOSITORY="${RELEASE_REPOSITORY:-Enishi-Marketing/event_control_center}"
if [[ ! "$RELEASE_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "RELEASE_REPOSITORY must be a GitHub owner/repository name."
  exit 1
fi
UPDATE_FEED_URL="https://github.com/$RELEASE_REPOSITORY/releases/latest/download/appcast.xml"

export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$PWD/.pyinstaller}"
"$PYTHON_BIN" -m PyInstaller EventControlBackend.spec --noconfirm --clean
swift build --package-path swiftui --configuration release --scratch-path "$PWD/build/swift"

APP_PATH="$PWD/dist/Event Control Center.app"
rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS" "$APP_PATH/Contents/Resources" "$APP_PATH/Contents/Frameworks"
cp "$PWD/build/swift/release/EventControlCenter" "$APP_PATH/Contents/MacOS/EventControlCenter"
ditto "$PWD/build/swift/release/Sparkle.framework" "$APP_PATH/Contents/Frameworks/Sparkle.framework"
install_name_tool -add_rpath '@executable_path/../Frameworks' "$APP_PATH/Contents/MacOS/EventControlCenter"
ditto "$PWD/dist/EventControlBackend" "$APP_PATH/Contents/Resources/backend"
cp assets/app_icon.icns "$APP_PATH/Contents/Resources/AppIcon.icns"

cat > "$APP_PATH/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleDisplayName</key><string>Event Control Center</string>
  <key>CFBundleExecutable</key><string>EventControlCenter</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleIdentifier</key><string>jp.ac.enishi.event-control-center</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>Event Control Center</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>SUFeedURL</key><string>$UPDATE_FEED_URL</string>
  <key>SUPublicEDKey</key><string>EH6wT4wm4aYsP/IXBs0/O5jhRHN5SylhovFi4Yjg9/A=</string>
  <key>SUEnableAutomaticChecks</key><true/>
  <key>SUAutomaticallyUpdate</key><true/>
  <key>SUVerifyUpdateBeforeExtraction</key><true/>
  <key>SURequireSignedFeed</key><true/>
</dict></plist>
EOF
printf 'APPL????' > "$APP_PATH/Contents/PkgInfo"

# A Developer ID identity can be supplied for a notarizable staff release.
CODESIGN_IDENTITY="${CODESIGN_IDENTITY:--}"
if [ "$CODESIGN_IDENTITY" = "-" ]; then
  # Hardened Runtime library validation rejects ad hoc signed Sparkle in a
  # separately ad hoc signed host. The no-fee build does not use notarization.
  codesign --force --deep --sign - "$APP_PATH"
else
  codesign --force --deep --options runtime --timestamp --sign "$CODESIGN_IDENTITY" "$APP_PATH"
fi
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
echo "Built $APP_PATH"
