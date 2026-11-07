#!/usr/bin/env bash
set -euo pipefail

MCP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec node "$MCP_DIR/run.mjs" "$@"
