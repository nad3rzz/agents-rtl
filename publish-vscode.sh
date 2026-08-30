#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTENSION_DIR="$ROOT_DIR/extension"
ENV_FILE="$ROOT_DIR/.env.publish"
PACKAGE_VERSION="$(node -p "require('$EXTENSION_DIR/package.json').version")"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [[ -z "${VSCE_PAT:-}" ]]; then
  echo "Missing VSCE_PAT in $ENV_FILE"
  exit 1
fi

cd "$EXTENSION_DIR"

npx --yes @vscode/vsce publish \
  --packagePath \
  "agents-rtl-linux-x64-$PACKAGE_VERSION.vsix" \
  "agents-rtl-win32-x64-$PACKAGE_VERSION.vsix" \
  --skip-duplicate \
  --pat "$VSCE_PAT"
