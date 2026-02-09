# External Integrations Guide

Detailed setup guide for integrating PubMed Search MCP with various AI clients and platforms.

> **Quick Start**: For minimal configuration snippets, see the main [README.md](../README.md#-configuration).

---

## Table of Contents

- [Transport Modes](#transport-modes)
- [Environment Variables](#environment-variables)
- [Client Configurations](#client-configurations)
  - [VS Code / Cursor](#vs-code--cursor)
  - [Claude Desktop](#claude-desktop)
  - [Claude Code](#claude-code)
  - [Zed AI](#zed-ai)
  - [OpenClaw](#openclaw-)
  - [Cline](#cline)
  - [Microsoft Copilot Studio](#microsoft-copilot-studio)
  - [Other MCP Clients](#other-mcp-clients)
- [Verification & Troubleshooting](#verification--troubleshooting)
- [Advanced: Proxy & Network](#advanced-proxy--network)
- [Advanced: Docker Deployment](#advanced-docker-deployment)

---

## Transport Modes

PubMed Search MCP supports two transport modes:

| Mode | Protocol | Use Case | Default |
|------|----------|----------|---------|
| **stdio** | Standard I/O | Local clients (VS Code, Claude Desktop, etc.) | ✅ |
| **Streamable HTTP** | HTTP POST/SSE | Remote/cloud clients (Copilot Studio, web apps) | — |

### stdio (Default)

The client spawns the server as a subprocess and communicates via stdin/stdout. Zero configuration needed for networking.

```bash
uvx pubmed-search-mcp
```

### Streamable HTTP

For remote access, run the server in HTTP mode:

```bash
# Direct HTTP
uvx pubmed-search-mcp --transport streamable-http --port 8765

# Via run_copilot.py (simplified for Copilot Studio)
python run_copilot.py --port 8765
```

The MCP endpoint will be available at `http://localhost:8765/mcp`.

> **Note**: SSE transport (`--transport sse`) is deprecated in favor of Streamable HTTP per MCP spec 2025-03-26.

---

## Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `NCBI_EMAIL` | **Yes** | Email for NCBI API policy compliance | `user@example.com` |
| `NCBI_API_KEY` | No | NCBI API key for higher rate limits (10 req/s vs 3 req/s) | — |
| `CORE_API_KEY` | No | [CORE API](https://core.ac.uk/services/api) key for open access search | — |
| `CROSSREF_EMAIL` | No | Email for CrossRef polite pool (faster responses) | — |
| `UNPAYWALL_EMAIL` | No | Email for Unpaywall API access | — |
| `OPENURL_RESOLVER` | No | Institutional link resolver base URL | — |
| `OPENURL_PRESET` | No | Preset name for institutional resolver | — |
| `OPENURL_ENABLED` | No | Enable/disable OpenURL resolver | `true` |
| `PUBMED_HTTP_API_PORT` | No | Port for background HTTP API (stdio mode) | `8765` |
| `HTTP_PROXY` / `HTTPS_PROXY` | No | Proxy settings for outbound requests | — |

### Getting API Keys

| Service | How to Get | Benefit |
|---------|-----------|---------|
| [NCBI API Key](https://www.ncbi.nlm.nih.gov/account/settings/) | Create NCBI account → Settings → API Key | 10 req/s (vs 3 req/s) |
| [CORE API Key](https://core.ac.uk/services/api) | Register at core.ac.uk | Access 200M+ open access papers |

---

## Client Configurations

### VS Code / Cursor

**Config file**: `.vscode/mcp.json` (project-level) or User Settings

```json
{
  "servers": {
    "pubmed-search": {
      "type": "stdio",
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com",
        "NCBI_API_KEY": "your_api_key"
      }
    }
  }
}
```

**With all optional keys**:

```json
{
  "servers": {
    "pubmed-search": {
      "type": "stdio",
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com",
        "NCBI_API_KEY": "your_api_key",
        "CORE_API_KEY": "your_core_key",
        "CROSSREF_EMAIL": "your@email.com",
        "UNPAYWALL_EMAIL": "your@email.com"
      }
    }
  }
}
```

**Verification**: Open Copilot Chat → type `@pubmed-search` → you should see the server listed.

---

### Claude Desktop

**Config file**: `claude_desktop_config.json`

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      }
    }
  }
}
```

**Verification**: Open Claude Desktop → Settings → Developer → you should see "pubmed-search" listed and running.

> **Tip**: If `uvx` is not found, use the full path (e.g., `/Users/you/.local/bin/uvx` or `C:\Users\you\.local\bin\uvx.exe`).

---

### Claude Code

**Quick setup** (one command):

```bash
claude mcp add pubmed-search -- uvx pubmed-search-mcp
```

**Or via `.mcp.json`** in your project root:

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      }
    }
  }
}
```

**Verification**: Run `claude mcp list` → should show `pubmed-search` as connected.

---

### Zed AI

[Zed](https://zed.dev) supports MCP servers natively via **Custom Server** configuration.

**Config file**: Zed `settings.json` (Command Palette → `zed: open settings`)

```json
{
  "context_servers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      }
    }
  }
}
```

**Alternative setup**: Agent Panel → Settings icon → "Add Custom Server"

**Verification**: Open the Agent Panel → the server should appear in the context server list.

**Zed-specific notes**:
- Zed uses `context_servers` (not `mcpServers`)
- Supports stdio transport only
- MCP tools are available in Assistant Panel conversations
- See [Zed MCP docs](https://zed.dev/docs/ai/mcp) for more details

**Using profiles** for different research contexts:

```json
{
  "context_servers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      }
    }
  },
  "assistant": {
    "profiles": {
      "literature-review": {
        "name": "Literature Review",
        "context_servers": {
          "pubmed-search": { "enabled": true }
        }
      },
      "coding": {
        "name": "Coding",
        "context_servers": {
          "pubmed-search": { "enabled": false }
        }
      }
    }
  }
}
```

---

### OpenClaw 🦞

[OpenClaw](https://docs.openclaw.ai/) uses MCP servers via the [mcp-adapter plugin](https://github.com/androidStern-personal/openclaw-mcp-adapter).

**Step 1**: Install the adapter

```bash
openclaw plugins install mcp-adapter
```

**Step 2**: Configure `~/.openclaw/openclaw.json`

```json
{
  "plugins": {
    "entries": {
      "mcp-adapter": {
        "enabled": true,
        "config": {
          "servers": [
            {
              "name": "pubmed-search",
              "transport": "stdio",
              "command": "uvx",
              "args": ["pubmed-search-mcp"],
              "env": {
                "NCBI_EMAIL": "your@email.com"
              }
            }
          ]
        }
      }
    }
  }
}
```

**Step 3**: Restart and verify

```bash
openclaw gateway restart
openclaw plugins list  # Should show: mcp-adapter | loaded
```

---

### Cline

**Config file**: `cline_mcp_settings.json`

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      },
      "alwaysAllow": [],
      "disabled": false
    }
  }
}
```

---

### Microsoft Copilot Studio

Copilot Studio requires **Streamable HTTP** transport with a public URL.

**Architecture**:

```
Copilot Studio ──HTTPS──▶ ngrok ──HTTP──▶ MCP Server (localhost:8765)
```

**Step 1**: Start the MCP server with HTTP transport

```bash
# Option A: Quick start script (uses ngrok)
./scripts/start-copilot-ngrok.sh

# Option B: Manual setup
python run_copilot.py --port 8765
```

**Step 2**: Expose via ngrok (if not using the script)

```bash
ngrok http --url=your-domain.ngrok.dev 8765
```

**Step 3**: Configure in Copilot Studio

| Setting | Value |
|---------|-------|
| Server name | `PubMed Search` |
| Server URL | `https://your-domain.ngrok.dev/mcp` |
| Authentication | None |

**Environment variables** for the ngrok script:

```bash
export NGROK_DOMAIN="your-domain.ngrok.dev"
export COPILOT_PORT=8765
./scripts/start-copilot-ngrok.sh
```

> See [copilot-studio/README.md](../copilot-studio/README.md) for the full OpenAPI schema and Copilot Studio setup walkthrough.

---

### Other MCP Clients

Any MCP-compatible client can use this server via stdio:

```bash
# Basic
uvx pubmed-search-mcp

# With environment variables
NCBI_EMAIL=your@email.com NCBI_API_KEY=your_key uvx pubmed-search-mcp

# From source (development)
cd pubmed-search-mcp
uv run python -m pubmed_search
```

---

## Verification & Troubleshooting

### Quick Health Check

After configuring any client, verify the server is working:

1. **Ask the AI**: "List all available PubMed tools" — the AI should enumerate ~40 tools
2. **Simple search**: "Search PubMed for CRISPR gene therapy" — should return article results
3. **Check tool list**: The server provides tools like `unified_search`, `fetch_article_details`, `get_fulltext`, etc.

### Common Issues

| Problem | Solution |
|---------|----------|
| `uvx` not found | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Server not connecting | Check the config file path and JSON syntax |
| `NCBI_EMAIL` warning | Set the `NCBI_EMAIL` environment variable in the config |
| Slow responses | Add `NCBI_API_KEY` for 10 req/s (vs 3 req/s default) |
| CORE search fails | Set `CORE_API_KEY` — [get one free](https://core.ac.uk/services/api) |
| Behind proxy | Set `HTTP_PROXY` / `HTTPS_PROXY` environment variables |

### Debug Mode

Run the server directly to see logs:

```bash
NCBI_EMAIL=your@email.com uvx pubmed-search-mcp 2>server.log
```

---

## Advanced: Proxy & Network

If you're behind a corporate proxy:

```json
{
  "servers": {
    "pubmed-search": {
      "type": "stdio",
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com",
        "HTTP_PROXY": "http://proxy.corp.com:8080",
        "HTTPS_PROXY": "http://proxy.corp.com:8080"
      }
    }
  }
}
```

---

## Advanced: Docker Deployment

For production deployments or team sharing:

```bash
# Build
docker build -t pubmed-search-mcp .

# Run with HTTP transport
docker run -p 8765:8765 \
  -e NCBI_EMAIL=your@email.com \
  -e NCBI_API_KEY=your_key \
  pubmed-search-mcp

# With HTTPS (nginx reverse proxy)
docker compose -f docker-compose.https.yml up -d
```

See [DEPLOYMENT.md](../DEPLOYMENT.md) for full production deployment instructions.
