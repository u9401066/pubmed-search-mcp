# PubMed Search MCP Server - 遠端服務部署指南

## 📋 目錄

- [部署模式總覽](#-部署模式總覽)
- [快速開始](#快速開始)
- [HTTPS 部署 (推薦)](#-https-部署--https-deployment)
- [Docker 部署](#-docker-部署)
- [客戶端配置](#客戶端配置)
- [安全建議](#安全建議)

---

## 🎯 部署模式總覽

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Deployment Options                                  │
├─────────────────┬─────────────────┬─────────────────┬────────────────────────┤
│   HTTP (Dev)    │   MCP SSE       │   MCP stdio     │   HTTPS (Production)   │
│   (Port 8765)   │   (Port 8765)   │   (Local)       │   (Nginx + TLS)        │
├─────────────────┼─────────────────┼─────────────────┼────────────────────────┤
│ ✅ Quick test   │ ✅ Remote MCP   │ ✅ Claude       │ ✅ Production deploy   │
│                 │    clients      │    Desktop      │ ✅ Secure connections  │
│                 │ ✅ Docker/Cloud │ ✅ VS Code      │ ✅ Rate limiting       │
│                 │                 │    Copilot      │ ✅ TLS 1.2/1.3         │
└─────────────────┴─────────────────┴─────────────────┴────────────────────────┘
```

| Mode | Protocol | Port | Best For |
|------|----------|------|----------|
| **stdio** | MCP stdio | - | Local Claude Desktop, VS Code Copilot |
| **sse** | MCP over SSE | 8765 | Remote MCP clients, Docker deployment |
| **https** | HTTPS (Nginx) | 443 | Production with TLS encryption 🔒 |

---

## 快速開始

### 1. 安裝

```bash
# Clone repo
git clone https://github.com/u9401066/pubmed-search-mcp.git
cd pubmed-search-mcp

# 建立虛擬環境
python3 -m venv .venv
source .venv/bin/activate

# 安裝套件
pip install -e ".[all]"
```

### 2. 啟動服務

```bash
# SSE 傳輸模式 (推薦，相容性較好)
python run_server.py --transport sse --port 8765 --email your@email.com

# 或使用 streamable-http 模式
python run_server.py --transport streamable-http --port 8765 --email your@email.com
```

### 3. 測試連接

```bash
# 使用測試客戶端
python test_client.py http://localhost:8765/sse
```

## 部署選項

### 選項 1: 直接運行 (開發/測試)

```bash
# 設置環境變數
export NCBI_EMAIL="your@email.com"
export NCBI_API_KEY="your_api_key"  # 可選，提高請求限制

# 啟動服務
python run_server.py --transport sse --port 8765
```

### 選項 2: 使用 systemd (生產環境)

創建 `/etc/systemd/system/pubmed-mcp.service`:

```ini
[Unit]
Description=PubMed Search MCP Server
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/pubmed-search-mcp
Environment=NCBI_EMAIL=your@email.com
Environment=NCBI_API_KEY=your_api_key
ExecStart=/path/to/pubmed-search-mcp/.venv/bin/python run_server.py --transport sse --port 8765
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

啟動服務:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pubmed-mcp
sudo systemctl start pubmed-mcp
```

### 選項 3: 使用 Docker

創建 `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install -e ".[all]"

EXPOSE 8765

ENV NCBI_EMAIL=pubmed-search@example.com

CMD ["python", "run_server.py", "--transport", "sse", "--port", "8765"]
```

構建並運行:

```bash
docker build -t pubmed-mcp .
docker run -d -p 8765:8765 -e NCBI_EMAIL=your@email.com pubmed-mcp
```

---

## 🔒 HTTPS 部署 | HTTPS Deployment

為生產環境提供安全的 HTTPS 連線，使用 Nginx 反向代理處理 TLS 終止。

### 架構 | Architecture

```
                    HTTPS (TLS 1.2/1.3)
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│              Nginx Reverse Proxy                     │
│  ┌────────────────────────────────────────────────┐ │
│  │ • TLS Termination (SSL Certificates)           │ │
│  │ • Rate Limiting (30 req/s)                     │ │
│  │ • Security Headers (XSS, CSRF protection)      │ │
│  │ • SSE Optimization (24h timeout, no buffer)    │ │
│  └────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────┘
                            │ HTTP (internal)
                            ▼
              ┌──────────────────────────┐
              │   PubMed Search MCP      │
              │   (Port 8765)            │
              │                          │
              │ • /sse                   │
              │ • /messages              │
              │ • /exports               │
              └──────────────────────────┘
```

### 快速開始 | Quick Start

#### Option 1: Docker Deployment (推薦)

```bash
# Step 1: 生成 SSL 憑證
chmod +x scripts/generate-ssl-certs.sh
./scripts/generate-ssl-certs.sh

# Step 2: 啟動 HTTPS 服務
./scripts/start-https-docker.sh up

# 其他命令
./scripts/start-https-docker.sh down     # 停止服務
./scripts/start-https-docker.sh logs     # 查看日誌
./scripts/start-https-docker.sh restart  # 重啟服務
./scripts/start-https-docker.sh status   # 查看狀態
```

**端點 | Endpoints:**

| Service | URL | Description |
|---------|-----|-------------|
| MCP SSE | `https://localhost/` | MCP Server root |
| MCP SSE | `https://localhost/sse` | SSE connection |
| Health | `https://localhost/health` | Health check |
| Exports | `https://localhost/exports` | Export files |

#### Option 2: Local Development (無 Docker)

使用 Uvicorn 原生 SSL 支援進行本地測試。

```bash
# Step 1: 生成 SSL 憑證
./scripts/generate-ssl-certs.sh

# Step 2: 啟動 HTTPS 服務
./scripts/start-https-local.sh

# 停止服務
./scripts/start-https-local.sh stop
```

**端點 | Endpoints:**

| Service | URL | Description |
|---------|-----|-------------|
| MCP SSE | `https://localhost:8443/` | MCP Server |
| MCP SSE | `https://localhost:8443/sse` | SSE connection |

### Claude Desktop 設定 (HTTPS)

```json
{
  "mcpServers": {
    "pubmed-search": {
      "url": "https://localhost/sse"
    }
  }
}
```

生產環境使用實際網域：

```json
{
  "mcpServers": {
    "pubmed-search": {
      "url": "https://mcp.your-domain.com/sse"
    }
  }
}
```

### 信任自簽憑證 | Trust Self-Signed Certificates

**Linux (Ubuntu/Debian):**
```bash
sudo cp nginx/ssl/ca.crt /usr/local/share/ca-certificates/pubmed-mcp-dev.crt
sudo update-ca-certificates
```

**macOS:**
```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain nginx/ssl/ca.crt
```

**Windows:**
```
雙擊 ca.crt → 安裝憑證 → 本機電腦 → 受信任的根憑證授權
```

### 相關檔案 | Files

| File | Description |
|------|-------------|
| `nginx/nginx.conf` | Nginx 設定 (TLS, rate limiting, SSE optimization) |
| `docker-compose.https.yml` | Docker Compose for HTTPS deployment |
| `scripts/generate-ssl-certs.sh` | 生成自簽 SSL 憑證 |
| `scripts/start-https-docker.sh` | Docker HTTPS 啟動腳本 |
| `scripts/start-https-local.sh` | 本地 HTTPS 啟動腳本 |

---

## 🐳 Docker 部署

### Docker Compose (HTTP)

```bash
# 啟動服務
docker-compose up -d

# 查看日誌
docker-compose logs -f

# 停止服務
docker-compose down
```

---

## 客戶端配置

### VS Code MCP 配置 (遠端連接)

在其他主機的 `.vscode/mcp.json` 中添加:

```json
{
  "servers": {
    "pubmed-search": {
      "type": "sse",
      "url": "http://YOUR_SERVER_IP:8765/sse"
    }
  }
}
```

### Claude Desktop 配置

在 `claude_desktop_config.json` 中添加:

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://YOUR_SERVER_IP:8765/sse"
      ]
    }
  }
}
```

### Python 客戶端

```python
from mcp.client.sse import sse_client
from mcp import ClientSession
import asyncio

async def main():
    async with sse_client("http://YOUR_SERVER_IP:8765/sse") as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            
            # 搜尋文獻
            result = await session.call_tool(
                "search_literature",
                arguments={
                    "query": "diabetes treatment",
                    "limit": 5
                }
            )
            print(result.content[0].text)

asyncio.run(main())
```

## 可用工具

| 工具名稱 | 說明 |
|---------|------|
| `search_literature` | 搜尋 PubMed 文獻 |
| `find_related_articles` | 尋找相關文章 |
| `find_citing_articles` | 尋找引用文章 |
| `fetch_article_details` | 獲取文章詳細資訊 |
| `generate_search_queries` | 生成多個搜尋查詢 |
| `merge_search_results` | 合併搜尋結果 |
| `expand_search_queries` | 擴展搜尋查詢 |

## 網路配置

### 防火牆設定

```bash
# UFW
sudo ufw allow 8765/tcp

# iptables
sudo iptables -A INPUT -p tcp --dport 8765 -j ACCEPT
```

### 反向代理 (Nginx)

```nginx
server {
    listen 443 ssl;
    server_name mcp.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;  # SSE 需要長連接
    }
}
```

## 故障排除

### 連接問題

1. 確認服務正在運行:
   ```bash
   curl http://localhost:8765/sse
   ```

2. 檢查防火牆設定

3. 確認 IP 地址可達

### 搜尋錯誤

1. 確認 NCBI_EMAIL 已設定
2. 如果請求頻繁，考慮申請 NCBI API Key

## 安全建議

1. **使用 HTTPS**: 在生產環境中，透過反向代理啟用 SSL/TLS
2. **限制訪問**: 使用防火牆限制可連接的 IP
3. **API Key**: 使用 NCBI API Key 提高請求限制並追蹤使用
4. **監控**: 設定日誌監控異常活動
