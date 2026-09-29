#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION_FILE="VERSION"

usage() {
  cat <<'USAGE'
Usage:
  scripts/release_macos_app.sh [patch|minor|major]
  scripts/release_macos_app.sh --version X.Y.Z

Examples:
  scripts/release_macos_app.sh
  scripts/release_macos_app.sh minor
  scripts/release_macos_app.sh --version 1.2.0
USAGE
}

if [ ! -f "$VERSION_FILE" ]; then
  echo "Missing $VERSION_FILE."
  exit 1
fi

current_version="$(tr -d '[:space:]' < "$VERSION_FILE")"

if [[ ! "$current_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "$VERSION_FILE must contain a version like 1.2.3."
  exit 1
fi

bump_part="${1:-patch}"

if [ "$bump_part" = "--help" ] || [ "$bump_part" = "-h" ]; then
  usage
  exit 0
fi

if [ "$bump_part" = "--version" ]; then
  if [ "${2:-}" = "" ]; then
    echo "Missing version after --version."
    usage
    exit 1
  fi
  new_version="$2"
  if [[ ! "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Version must look like 1.2.3."
    exit 1
  fi
elif [ "$bump_part" = "patch" ] || [ "$bump_part" = "minor" ] || [ "$bump_part" = "major" ]; then
  IFS=. read -r major minor patch <<< "$current_version"
  case "$bump_part" in
    patch)
      patch=$((patch + 1))
      ;;
    minor)
      minor=$((minor + 1))
      patch=0
      ;;
    major)
      major=$((major + 1))
      minor=0
      patch=0
      ;;
  esac
  new_version="${major}.${minor}.${patch}"
else
  echo "Unknown version bump: $bump_part"
  usage
  exit 1
fi

printf '%s\n' "$new_version" > "$VERSION_FILE"

echo "Version: $current_version -> $new_version"
if ! scripts/package_staff_dmg.sh; then
  printf '%s\n' "$current_version" > "$VERSION_FILE"
  echo "Build failed. Restored version to $current_version."
  exit 1
fi
