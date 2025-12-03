# PubMed Search MCP Server - 遠端服務部署指南

## 概述

此文件說明如何將 PubMed Search MCP Server 部署為遠端服務，讓其他主機可以連接使用。

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
