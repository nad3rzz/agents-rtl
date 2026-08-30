#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTENSION_DIR="$ROOT_DIR/extension"
DIST_DIR="$ROOT_DIR/dist"
STAGING_DIR="$ROOT_DIR/.build-vsix"
BASE_CONTENT_URL="https://github.com/nad3rzz/agents-rtl/blob/main"
BASE_IMAGES_URL="https://raw.githubusercontent.com/nad3rzz/agents-rtl/main"

stage_and_package() {
  local target="$1"
  local helper_file_name="$2"

  cd "$ROOT_DIR"
  rm -rf "$STAGING_DIR"
  mkdir -p "$STAGING_DIR/bin"

  rsync -a \
    --exclude "bin/**" \
    --exclude "*.vsix" \
    "$EXTENSION_DIR"/ \
    "$STAGING_DIR"/

  cp "$DIST_DIR/$helper_file_name" "$STAGING_DIR/bin/$helper_file_name"

  cd "$STAGING_DIR"
  npx --yes @vscode/vsce package \
    --target "$target" \
    --baseContentUrl "$BASE_CONTENT_URL" \
    --baseImagesUrl "$BASE_IMAGES_URL"

  mv "$STAGING_DIR"/agents-rtl-"$target"-*.vsix "$EXTENSION_DIR"/
  cd "$ROOT_DIR"
}

rm -rf "$DIST_DIR" "$STAGING_DIR"
mkdir -p "$DIST_DIR"

cd "$ROOT_DIR/helper-go"
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o "$DIST_DIR/agents-rtl-helper-linux" .
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o "$DIST_DIR/agents-rtl-helper-windows.exe" .

stage_and_package "linux-x64" "agents-rtl-helper-linux"
stage_and_package "win32-x64" "agents-rtl-helper-windows.exe"

rm -rf "$STAGING_DIR" "$DIST_DIR"
