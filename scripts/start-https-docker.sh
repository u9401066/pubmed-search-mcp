#!/bin/bash
# =============================================================================
# PubMed Search MCP - Docker HTTPS 啟動腳本
# =============================================================================
#
# 使用 Docker Compose 啟動 HTTPS 服務 (Nginx + MCP streamable-http)
#
# Usage:
#   ./scripts/start-https-docker.sh up       # 啟動服務
#   ./scripts/start-https-docker.sh down     # 停止服務
#   ./scripts/start-https-docker.sh logs     # 查看日誌
#   ./scripts/start-https-docker.sh restart  # 重啟服務
#   ./scripts/start-https-docker.sh status   # 查看狀態
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

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ 錯誤: 需要安裝 Docker${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}❌ 錯誤: 需要安裝 Docker Compose${NC}"
    exit 1
fi

# Check SSL certificates
if [ ! -f "$SSL_DIR/server.crt" ] || [ ! -f "$SSL_DIR/server.key" ]; then
    echo -e "${YELLOW}⚠️  SSL 憑證不存在，正在生成...${NC}"
    bash "$SCRIPT_DIR/generate-ssl-certs.sh"
fi

# Parse arguments
ACTION="${1:-up}"

# Docker Compose command
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

case "$ACTION" in
    up)
        echo -e "${GREEN}🚀 啟動 HTTPS 服務...${NC}"
        $COMPOSE_CMD -f docker-compose.https.yml up -d --build
        echo ""
        echo -e "${GREEN}✅ 服務已啟動！${NC}"
        echo ""
        echo "端點："
        echo "  MCP:         https://localhost/mcp"
        echo "  Info:        https://localhost/info"
        echo "  Health:      https://localhost/health"
        echo "  Exports:     https://localhost/exports"
        echo ""
        echo "Claude Desktop 設定："
        echo '  {'
        echo '    "mcpServers": {'
        echo '      "pubmed-search": {'
        echo '        "url": "https://localhost/mcp"'
        echo '      }'
        echo '    }'
        echo '  }'
        ;;

    down)
        echo -e "${YELLOW}🛑 停止 HTTPS 服務...${NC}"
        $COMPOSE_CMD -f docker-compose.https.yml down
        echo -e "${GREEN}✅ 服務已停止${NC}"
        ;;

    logs)
        echo -e "${BLUE}📋 查看日誌...${NC}"
        $COMPOSE_CMD -f docker-compose.https.yml logs -f
        ;;

    restart)
        echo -e "${YELLOW}🔄 重啟 HTTPS 服務...${NC}"
        $COMPOSE_CMD -f docker-compose.https.yml restart
        echo -e "${GREEN}✅ 服務已重啟${NC}"
        ;;

    status)
        echo -e "${BLUE}📊 服務狀態：${NC}"
        $COMPOSE_CMD -f docker-compose.https.yml ps
        ;;

    *)
        echo "Usage: $0 {up|down|logs|restart|status}"
        exit 1
        ;;
esac
