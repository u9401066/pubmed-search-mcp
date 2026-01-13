#!/bin/bash
# Start PubMed Search MCP Server for Microsoft Copilot Studio
# 
# Copilot Studio requires:
# - Streamable HTTP transport (SSE deprecated since Aug 2025)
# - Public HTTPS URL
# - /mcp endpoint
#
# Usage:
#   ./scripts/start-copilot-studio.sh
#   ./scripts/start-copilot-studio.sh --with-ngrok

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Default settings
PORT=${MCP_PORT:-8765}
HOST=${MCP_HOST:-0.0.0.0}
EMAIL=${NCBI_EMAIL:-pubmed-search@example.com}

echo "=========================================="
echo "PubMed Search MCP for Copilot Studio"
echo "=========================================="
echo ""
echo "Transport: streamable-http (required by Copilot Studio)"
echo "Endpoint:  /mcp"
echo "Port:      $PORT"
echo ""

# Check if ngrok mode
if [ "$1" == "--with-ngrok" ]; then
    echo "Starting with ngrok tunnel..."
    echo ""
    
    # Check if ngrok is installed
    if ! command -v ngrok &> /dev/null; then
        echo "❌ ngrok not found. Install from https://ngrok.com/download"
        exit 1
    fi
    
    # Start server in background
    python run_server.py --transport streamable-http --port $PORT --email "$EMAIL" &
    SERVER_PID=$!
    
    sleep 2
    
    # Start ngrok
    echo "Starting ngrok tunnel..."
    ngrok http $PORT &
    NGROK_PID=$!
    
    sleep 3
    
    # Get ngrok URL
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys, json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || echo "")
    
    if [ -n "$NGROK_URL" ]; then
        echo ""
        echo "=========================================="
        echo "✅ Server ready for Copilot Studio!"
        echo "=========================================="
        echo ""
        echo "Copilot Studio Configuration:"
        echo "  Server URL: ${NGROK_URL}/mcp"
        echo "  Auth Type:  None"
        echo ""
        echo "Press Ctrl+C to stop"
        echo ""
        
        # Wait for Ctrl+C
        trap "kill $SERVER_PID $NGROK_PID 2>/dev/null; exit 0" SIGINT SIGTERM
        wait
    else
        echo "⚠️  Could not get ngrok URL. Check ngrok dashboard: http://localhost:4040"
        wait $SERVER_PID
    fi
else
    echo "Starting server locally..."
    echo ""
    echo "For Copilot Studio, you need a public HTTPS URL."
    echo "Options:"
    echo "  1. Use ngrok:   $0 --with-ngrok"
    echo "  2. Deploy to:   Azure, Railway, Render, etc."
    echo ""
    echo "Local endpoint: http://localhost:$PORT/mcp"
    echo ""
    
    python run_server.py --transport streamable-http --port $PORT --email "$EMAIL"
fi
