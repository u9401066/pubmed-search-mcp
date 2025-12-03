#!/bin/bash
# PubMed Search MCP Server - Quick Start Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Default values
PORT=${MCP_PORT:-8765}
EMAIL=${NCBI_EMAIL:-pubmed-search@example.com}
TRANSPORT=${MCP_TRANSPORT:-sse}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}PubMed Search MCP Server${NC}"
echo "================================"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Check if dependencies are installed
if ! python3 -c "import pubmed_search" 2>/dev/null; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip install -e ".[all]" --quiet
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
python3 run_server.py --transport "$TRANSPORT" --port "$PORT" --email "$EMAIL"
