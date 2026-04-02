#!/bin/bash
# =============================================================================
# PubMed Search MCP - 本地 HTTPS 啟動腳本
# =============================================================================
#
# 使用本專案的 streamable-http + HTTPS wrapper 進行本地開發測試
# (不需要 Docker，直接執行)
#
# Usage:
#   ./scripts/start-https-local.sh          # 啟動 HTTPS 服務
#   ./scripts/start-https-local.sh stop     # 停止服務
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SSL_DIR="$PROJECT_ROOT/nginx/ssl"

cd "$PROJECT_ROOT"

# PID file
PID_FILE="$PROJECT_ROOT/.https-server.pid"

stop_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo -e "${YELLOW}🛑 停止 HTTPS 服務 (PID: $PID)...${NC}"
            kill "$PID" 2>/dev/null || true
            rm -f "$PID_FILE"
            echo -e "${GREEN}✅ 服務已停止${NC}"
        else
            echo -e "${YELLOW}⚠️  服務未運行${NC}"
            rm -f "$PID_FILE"
        fi
    else
        echo -e "${YELLOW}⚠️  找不到 PID 檔案，嘗試查找進程...${NC}"
        pkill -f "uvicorn.*ssl.*8443" 2>/dev/null || echo "無進程需要停止"
    fi
}

# Handle stop command
if [ "${1:-}" = "stop" ]; then
    stop_server
    exit 0
fi

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}🔐 PubMed Search MCP - HTTPS 本地啟動${NC}"
echo -e "${GREEN}============================================${NC}"

# Check SSL certificates
if [ ! -f "$SSL_DIR/server.crt" ] || [ ! -f "$SSL_DIR/server.key" ]; then
    echo -e "${YELLOW}⚠️  SSL 憑證不存在，正在生成...${NC}"
    bash "$SCRIPT_DIR/generate-ssl-certs.sh"
fi

# Check uv
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ 缺少 uv，請先安裝 uv${NC}"
    exit 1
fi

# Stop existing server if running
stop_server

# Start HTTPS server
echo -e "${BLUE}🚀 啟動 MCP Server (HTTPS, port 8443, streamable-http)...${NC}"

# Run in background
nohup uv run python scripts/run_https_local.py \
    --host 0.0.0.0 \
    --port 8443 \
    --certfile "$SSL_DIR/server.crt" \
    --keyfile "$SSL_DIR/server.key" > "$PROJECT_ROOT/https-server.log" 2>&1 &

# Save PID
echo $! > "$PID_FILE"

echo ""
echo -e "${GREEN}✅ HTTPS 服務已啟動！${NC}"
echo ""
echo "端點："
echo "  MCP:      https://localhost:8443/mcp"
echo "  Health:   https://localhost:8443/health"
echo "  Info:     https://localhost:8443/info"
echo ""
echo "日誌："
echo "  tail -f $PROJECT_ROOT/https-server.log"
echo ""
echo "停止服務："
echo "  ./scripts/start-https-local.sh stop"
echo ""
echo "Claude Desktop 設定："
echo '  {'
echo '    "mcpServers": {'
echo '      "pubmed-search": {'
echo '        "url": "https://localhost:8443/mcp"'
echo '      }'
echo '    }'
echo '  }'
