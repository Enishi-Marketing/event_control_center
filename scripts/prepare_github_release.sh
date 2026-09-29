#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION="$(tr -d '[:space:]' < VERSION)"
RELEASE_REPOSITORY="${RELEASE_REPOSITORY:-Enishi-Marketing/event_control_center}"
SOURCE_DMG_NAME="Event Control Center v${VERSION}.dmg"
# GitHub normalizes spaces in uploaded asset names; match the final URL in the signed feed.
RELEASE_DMG_NAME="Event.Control.Center.v${VERSION}.dmg"
DMG_PATH="$PWD/dist/$SOURCE_DMG_NAME"
APPCAST_TOOL="$PWD/build/swift/artifacts/sparkle/Sparkle/bin/generate_appcast"
STAGE_DIR="$PWD/build/github-release"
APP_PATH="$PWD/dist/Event Control Center.app"

if [[ ! "$RELEASE_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "RELEASE_REPOSITORY must be a GitHub owner/repository name."
  exit 1
fi
if [ ! -f "$DMG_PATH" ] || [ ! -x "$APPCAST_TOOL" ]; then
  echo "Build the staff DMG first with scripts/package_staff_dmg.sh."
  exit 1
fi
EXPECTED_FEED="https://github.com/$RELEASE_REPOSITORY/releases/latest/download/appcast.xml"
ACTUAL_FEED="$(/usr/libexec/PlistBuddy -c 'Print :SUFeedURL' "$APP_PATH/Contents/Info.plist")"
if [ "$ACTUAL_FEED" != "$EXPECTED_FEED" ]; then
  echo "The app's update feed targets $ACTUAL_FEED, but this release targets $EXPECTED_FEED."
  echo "Rebuild with RELEASE_REPOSITORY=$RELEASE_REPOSITORY scripts/package_staff_dmg.sh"
  exit 1
fi

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
cp "$DMG_PATH" "$STAGE_DIR/$RELEASE_DMG_NAME"
(cd "$STAGE_DIR" && shasum -a 256 "$RELEASE_DMG_NAME" > "$RELEASE_DMG_NAME.sha256")
"$APPCAST_TOOL" \
  --account jp.ac.enishi.event-control-center \
  --download-url-prefix "https://github.com/$RELEASE_REPOSITORY/releases/download/v$VERSION/" \
  --maximum-deltas 0 \
  -o "$STAGE_DIR/appcast.xml" \
  "$STAGE_DIR"

echo "Release assets ready in $STAGE_DIR"
echo "Create tag v$VERSION and attach the DMG, checksum, and signed appcast.xml to the GitHub Release."
