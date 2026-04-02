#!/bin/bash
# =============================================================================
# PubMed Search MCP - Quick Start for Copilot Studio
# =============================================================================
#
# Domain: kmuh-ai.ngrok.dev
# Copilot Studio URL: https://kmuh-ai.ngrok.dev/mcp
#
# Usage:
#   ./scripts/start-copilot-ngrok.sh
#
# Environment variables:
#   NGROK_DOMAIN  - ngrok custom domain (default: kmuh-ai.ngrok.dev)
#   COPILOT_PORT  - local server port (default: 8765)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration (override via environment variables)
NGROK_DOMAIN="${NGROK_DOMAIN:-kmuh-ai.ngrok.dev}"
PORT="${COPILOT_PORT:-8765}"

cd "$PROJECT_DIR"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  PubMed Search MCP × Microsoft Copilot Studio"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Domain:  $NGROK_DOMAIN"
echo "  Port:    $PORT"
echo ""

# Check uv
if ! command -v uv &> /dev/null; then
    echo "❌ uv not found. Install from https://docs.astral.sh/uv/"
    exit 1
fi

# Kill any existing processes on the port
echo "Checking for existing processes..."
pkill -f "run_copilot.py.*$PORT" 2>/dev/null || true
pkill -f "run_server.py.*$PORT" 2>/dev/null || true
pkill -f "ngrok.*$NGROK_DOMAIN" 2>/dev/null || true
sleep 1

# Start MCP server (using run_copilot.py - simplified for Copilot Studio)
echo "Starting PubMed Search MCP Server..."
uv run python run_copilot.py --port $PORT &
SERVER_PID=$!
sleep 3

if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "❌ Failed to start MCP server"
    exit 1
fi
echo "✅ MCP server started (PID: $SERVER_PID)"

# Start ngrok
echo "Starting ngrok tunnel..."
ngrok http --url=$NGROK_DOMAIN $PORT &
NGROK_PID=$!
sleep 3

if ! kill -0 $NGROK_PID 2>/dev/null; then
    echo "❌ Failed to start ngrok"
    kill $SERVER_PID 2>/dev/null
    exit 1
fi
echo "✅ ngrok tunnel started (PID: $NGROK_PID)"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  🎉 Ready for Microsoft Copilot Studio!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  MCP Server URL:  https://${NGROK_DOMAIN}/mcp"
echo ""
echo "  ┌─────────────────────────────────────────────────────────┐"
echo "  │ Copilot Studio Configuration:                          │"
echo "  │                                                         │"
echo "  │   Server name:     PubMed Search                       │"
echo "  │   Server URL:      https://${NGROK_DOMAIN}/mcp         │"
echo "  │   Authentication:  None                                 │"
echo "  └─────────────────────────────────────────────────────────┘"
echo ""
echo "  Test command:"
echo "    curl -X POST https://${NGROK_DOMAIN}/mcp"
echo ""
echo "  ngrok Dashboard: http://localhost:4040"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Press Ctrl+C to stop both servers"
echo ""

# Handle shutdown
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $SERVER_PID 2>/dev/null || true
    kill $NGROK_PID 2>/dev/null || true
    echo "Done."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Wait for either process to exit
wait
