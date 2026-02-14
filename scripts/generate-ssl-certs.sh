#!/bin/bash
# =============================================================================
# PubMed Search MCP - SSL Certificate Generation Script
# =============================================================================
#
# Generates self-signed SSL certificates for development/testing.
# For production, use Let's Encrypt or your organization's CA.
#
# Usage:
#   ./scripts/generate-ssl-certs.sh
#
# Output:
#   nginx/ssl/ca.crt      - CA certificate (add to trust store to avoid warnings)
#   nginx/ssl/ca.key      - CA private key
#   nginx/ssl/server.crt  - Server certificate
#   nginx/ssl/server.key  - Server private key
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SSL_DIR="$PROJECT_ROOT/nginx/ssl"

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}🔐 PubMed Search MCP - SSL 憑證生成${NC}"
echo -e "${GREEN}============================================${NC}"

# Create SSL directory
mkdir -p "$SSL_DIR"

# Check if certificates already exist
if [ -f "$SSL_DIR/server.crt" ] && [ -f "$SSL_DIR/server.key" ]; then
    echo -e "${YELLOW}⚠️  SSL 憑證已存在${NC}"
    read -p "要重新生成嗎？(y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "保留現有憑證。"
        exit 0
    fi
    echo "刪除現有憑證..."
    rm -f "$SSL_DIR"/*
fi

echo -e "${BLUE}📜 步驟 1: 生成 CA 私鑰...${NC}"
openssl genrsa -out "$SSL_DIR/ca.key" 4096

echo -e "${BLUE}📜 步驟 2: 生成 CA 憑證...${NC}"
openssl req -new -x509 -days 3650 -key "$SSL_DIR/ca.key" -out "$SSL_DIR/ca.crt" \
    -subj "/C=TW/ST=Taiwan/L=Taipei/O=PubMed Search MCP Dev/OU=Development/CN=PubMed Search MCP CA"

echo -e "${BLUE}📜 步驟 3: 生成伺服器私鑰...${NC}"
openssl genrsa -out "$SSL_DIR/server.key" 2048

echo -e "${BLUE}📜 步驟 4: 創建 SAN 配置...${NC}"
cat > "$SSL_DIR/san.cnf" << EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
C = TW
ST = Taiwan
L = Taipei
O = PubMed Search MCP Dev
OU = Development
CN = localhost

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = pubmed-mcp
DNS.3 = *.local
IP.1 = 127.0.0.1
IP.2 = ::1
EOF

echo -e "${BLUE}📜 步驟 5: 生成伺服器 CSR...${NC}"
openssl req -new -key "$SSL_DIR/server.key" -out "$SSL_DIR/server.csr" \
    -config "$SSL_DIR/san.cnf"

echo -e "${BLUE}📜 步驟 6: 用 CA 簽署伺服器憑證...${NC}"
openssl x509 -req -in "$SSL_DIR/server.csr" -CA "$SSL_DIR/ca.crt" -CAkey "$SSL_DIR/ca.key" \
    -CAcreateserial -out "$SSL_DIR/server.crt" -days 365 \
    -extfile "$SSL_DIR/san.cnf" -extensions req_ext

# Clean up temporary files
rm -f "$SSL_DIR/server.csr" "$SSL_DIR/san.cnf" "$SSL_DIR/ca.srl"

# Set permissions
chmod 600 "$SSL_DIR"/*.key
chmod 644 "$SSL_DIR"/*.crt

echo ""
echo -e "${GREEN}✅ SSL 憑證生成完成！${NC}"
echo ""
echo -e "${YELLOW}📁 憑證位置：${NC}"
echo "  CA 憑證:     $SSL_DIR/ca.crt"
echo "  CA 私鑰:     $SSL_DIR/ca.key"
echo "  伺服器憑證:  $SSL_DIR/server.crt"
echo "  伺服器私鑰:  $SSL_DIR/server.key"
echo ""
echo -e "${YELLOW}📌 如何信任此憑證 (消除瀏覽器警告)：${NC}"
echo ""
echo "Linux (Ubuntu/Debian):"
echo "  sudo cp $SSL_DIR/ca.crt /usr/local/share/ca-certificates/pubmed-mcp-dev.crt"
echo "  sudo update-ca-certificates"
echo ""
echo "macOS:"
echo "  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $SSL_DIR/ca.crt"
echo ""
echo "Windows:"
echo "  雙擊 ca.crt → 安裝憑證 → 本機電腦 → 受信任的根憑證授權"
echo ""
echo -e "${GREEN}🚀 現在可以啟動 HTTPS 服務：${NC}"
echo "  Docker:  ./scripts/start-https-docker.sh up"
echo "  本地:    ./scripts/start-https-local.sh"
echo ""
echo "存取位址："
echo "  MCP SSE:  https://localhost/"
echo "  MCP SSE:  https://localhost/sse"
