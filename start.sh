#!/bin/bash
# PubMed Search MCP Server - Quick Start Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Default values
PORT=${MCP_PORT:-8765}
EMAIL=${NCBI_EMAIL:-pubmed-search@example.com}
TRANSPORT=${MCP_TRANSPORT:-streamable-http}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}PubMed Search MCP Server${NC}"
echo "================================"

# Check if uv is available
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${RED}uv is required but was not found on PATH.${NC}"
    exit 1
fi

echo ""
echo -e "Email:     ${GREEN}$EMAIL${NC}"
echo -e "Port:      ${GREEN}$PORT${NC}"
echo -e "Transport: ${GREEN}$TRANSPORT${NC}"
echo ""
echo -e "${GREEN}Starting server...${NC}"
echo "Press Ctrl+C to stop"
echo ""

# Run the server
uv run python run_server.py --transport "$TRANSPORT" --port "$PORT" --email "$EMAIL"
