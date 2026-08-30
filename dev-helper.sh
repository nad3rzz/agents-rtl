#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if (( $# < 2 )); then
  printf 'Usage: %s <workspace-cwd> <devtools-port> [devtools-port ...]\n' "$0" >&2
  exit 2
fi

WORKSPACE_CWD="$1"
shift
DEVTOOLS_PORT_ARGUMENTS=()
for devtools_port in "$@"; do
  DEVTOOLS_PORT_ARGUMENTS+=(--port "$devtools_port")
done

cd "$ROOT_DIR/helper-go"

exec go run . \
  "${DEVTOOLS_PORT_ARGUMENTS[@]}" \
  --workspace-cwd "$WORKSPACE_CWD" \
  --interval-ms 500
