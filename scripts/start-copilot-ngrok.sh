#!/usr/bin/env bash
# Backward-compatible custom-domain wrapper for the authenticated Copilot
# Studio service launcher. The full security contract lives in one script.

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${NGROK_DOMAIN:?Set NGROK_DOMAIN to the assigned ngrok HTTPS host}"
export MCP_PORT="${MCP_PORT:-${COPILOT_PORT:-8765}}"

exec "$SCRIPT_DIR/start-copilot-studio.sh" --with-ngrok
