<!-- Generated from docs/INTEGRATIONS.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# External Integrations Guide

Detailed setup guide for integrating PubMed Search MCP with various AI clients and platforms.

> **Quick Start**: For minimal configuration snippets, see the main [README.md](../README.md#-configuration).

---

## Table of Contents

- [External Integrations Guide](#external-integrations-guide)
  - [Table of Contents](#table-of-contents)
  - [Transport Modes](#transport-modes)
    - [stdio (Default)](#stdio-default)
    - [Streamable HTTP](#streamable-http)
  - [Environment Variables](#environment-variables)
    - [Getting API Keys](#getting-api-keys)
  - [Client Configurations](#client-configurations)
    - [VS Code / Cursor](#vs-code--cursor)
    - [Claude Desktop](#claude-desktop)
    - [Claude Code](#claude-code)
    - [Zed AI](#zed-ai)
    - [OpenClaw 🦞](#openclaw-)
    - [Cline](#cline)
    - [Microsoft Copilot Studio](#microsoft-copilot-studio)
    - [Other MCP Clients](#other-mcp-clients)
  - [Verification \& Troubleshooting](#verification--troubleshooting)
    - [Quick Health Check](#quick-health-check)
    - [Common Issues](#common-issues)
    - [Debug Mode](#debug-mode)
  - [Advanced: Proxy \& Network](#advanced-proxy--network)
  - [Advanced: Docker Deployment](#advanced-docker-deployment)

---

## Transport Modes

PubMed Search MCP supports two transport modes:

| Mode | Protocol | Use Case | Default |
| --- | --- | --- | --- |
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
uv run python run_copilot.py --port 8765
```

The MCP endpoint will be available at `http://localhost:8765/mcp`.

> **Note**: SSE transport (`--transport sse`) is deprecated in favor of Streamable HTTP per MCP spec 2025-03-26.

### Auxiliary HTTP APIs

Besides the primary MCP contract at `/mcp`, `run_server.py` also exposes a **public auxiliary read-only HTTP API** for cache and session access:

| Endpoint | Purpose |
| --- | --- |
| `/api/cached_article/{pmid}` | Read one cached article, optionally fetch on miss |
| `/api/cached_articles?pmids=...` | Read multiple cached articles |
| `/api/session/summary` | Read current session summary |

This auxiliary API is public in the sense that callers may use it directly, but it is **not** the primary MCP tool contract. For agent tool discovery and normal runtime usage, `/mcp` remains the canonical external interface.

---

## Environment Variables

| Variable | Required | Description | Default |
| --- | --- | --- | --- |
| `NCBI_EMAIL` | **Yes** | Email for NCBI API policy compliance | `user@example.com` |
| `NCBI_API_KEY` | No | NCBI API key for higher rate limits (10 req/s vs 3 req/s) | — |
| `CORE_API_KEY` | No | [CORE API](https://core.ac.uk/services/api) key for open access search | — |
| `CROSSREF_EMAIL` | No | Email for CrossRef polite pool (faster responses) | — |
| `UNPAYWALL_EMAIL` | No | Email for Unpaywall API access | — |
| `PUBMED_SEARCH_DISABLED_SOURCES` | No | Comma-separated source keys to globally disable in unified_search and cross-search | — |
| `SCOPUS_ENABLED` | No | Enable the default-off Scopus connector (`true/false`) | `false` |
| `SCOPUS_API_KEY` | No | Elsevier Scopus API key. Required when `SCOPUS_ENABLED=true` | — |
| `SCOPUS_INSTTOKEN` | No | Optional Elsevier institutional token for Scopus | — |
| `WEB_OF_SCIENCE_ENABLED` | No | Enable the default-off Web of Science connector (`true/false`) | `false` |
| `WEB_OF_SCIENCE_API_KEY` | No | Clarivate Web of Science API key. Required when `WEB_OF_SCIENCE_ENABLED=true` | — |
| `OPENURL_RESOLVER` | No | Institutional link resolver base URL | — |
| `OPENURL_PRESET` | No | Preset name for institutional resolver | — |
| `OPENURL_ENABLED` | No | Enable/disable OpenURL resolver | `true` |
| `BROWSER_FETCH_CONFIG` | No | Preferred single JSON setting for browser-session broker and auto mode | — |
| `BROWSER_FETCH_ENABLED` | No | Enable browser-session broker via per-field envs | `false` |
| `BROWSER_FETCH_AUTO` | No | Auto-use broker when tool call omits allow_browser_session | `false` |
| `BROWSER_FETCH_BROKER_URL` | No | Local broker endpoint, e.g. `http://127.0.0.1:8766/fetch` | — |
| `BROWSER_FETCH_TOKEN` | No | Shared bearer token for the local broker | — |
| `BROWSER_FETCH_ALLOWED_HOSTS` | No | Comma-separated host allow-list for broker targets | — |
| `PUBMED_HTTP_API_PORT` | No | Port for background HTTP API (stdio mode) | `8765` |
| `HTTP_PROXY` / `HTTPS_PROXY` | No | Proxy settings for outbound requests | — |
| `BROWSER_FETCH_BROKER_TOKEN` | No | Bearer token expected by the local broker server | Falls back to `BROWSER_FETCH_TOKEN` |
| `BROWSER_FETCH_BROKER_HOST` | No | Broker bind host | `127.0.0.1` |
| `BROWSER_FETCH_BROKER_PORT` | No | Broker bind port | `8766` |
| `BROWSER_FETCH_BROKER_HEADLESS` | No | Run broker browser headless | `false` |
| `BROWSER_FETCH_BROKER_USER_DATA_DIR` | No | Persistent browser profile directory for broker login state | `~/.pubmed-search-mcp/browser-broker-profile` |
| `BROWSER_FETCH_BROKER_DOWNLOAD_DIR` | No | Temporary broker download directory | `~/.pubmed-search-mcp/browser-broker-downloads` |

### Source Selection and Source Gating

`unified_search` now supports source expressions such as:

```text
sources="pubmed,openalex"
sources="auto,-semantic_scholar"
sources="all,-crossref"
```

You can also globally disable sources without changing prompts or client config:

```bash
PUBMED_SEARCH_DISABLED_SOURCES=semantic_scholar,core
```

This applies to unified multi-source dispatch and internal alternate-source cross-search.

### Commercial Connectors

Commercial sources should be wired as **default-off** connectors.

Current status:

- `scopus`: connector skeleton is implemented, but it stays unavailable unless both
  `SCOPUS_ENABLED=true` and `SCOPUS_API_KEY` are present.
- `web_of_science`: connector skeleton is implemented, but it stays unavailable unless
  both `WEB_OF_SCIENCE_ENABLED=true` and `WEB_OF_SCIENCE_API_KEY` are present.

Recommended practice for future commercial sources:

- Keep the connector disabled by default.
- Gate it behind explicit env vars and credentials.
- Cover behavior with mocked unit tests in CI.
- Add opt-in live integration tests only in licensed environments.

### Getting API Keys

| Service | How to Get | Benefit |
| --- | --- | --- |
| [NCBI API Key](https://www.ncbi.nlm.nih.gov/account/settings/) | Create NCBI account → Settings → API Key | 10 req/s (vs 3 req/s) |
| [CORE API Key](https://core.ac.uk/services/api) | Register at core.ac.uk | Access 200M+ open access papers |
| Scopus API Key | Elsevier Developer Portal / licensed institutional access | Adds Scopus as an explicit or `all` source when enabled |
| Web of Science API Key | Clarivate Developer Portal / licensed institutional access | Adds Web of Science as an explicit or `all` source when enabled |

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

**One-time browser-session auto mode**:

```json
{
  "servers": {
    "pubmed-search": {
      "type": "stdio",
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com",
        "BROWSER_FETCH_CONFIG": "{\"enabled\":true,\"auto_enabled\":true,\"broker_url\":\"http://127.0.0.1:8766/fetch\",\"token\":\"local-dev-token\",\"allowed_hosts\":[\"jamanetwork.com\",\"*.jamanetwork.com\"]}"
      }
    }
  }
}
```

This is the recommended VS Code / Cursor setup when you want a single setting that enables authenticated browser fallback automatically. If you prefer separate values, `BROWSER_FETCH_ENABLED`, `BROWSER_FETCH_AUTO`, `BROWSER_FETCH_BROKER_URL`, `BROWSER_FETCH_TOKEN`, and `BROWSER_FETCH_ALLOWED_HOSTS` still work and override the JSON setting.

### Running the local browser broker

The MCP server only contains the broker client. To eliminate manual browser download prompts, run the companion local broker that intercepts Playwright download events and streams PDF bytes back to MCP.

```bash
uv sync --extra browser-broker
uv run playwright install chromium
uv run pubmed-browser-fetch-broker --token local-dev-token
```

Recommended first run:

1. Start the broker in non-headless mode.
2. Let the broker open its persistent browser profile.
3. Sign in to the target publisher or institution once in that browser.
4. Keep the broker running while MCP issues `get_fulltext` requests.

Because downloads are intercepted inside the Playwright-controlled browser, publisher PDF flows no longer rely on the operating system's native Save As dialog.

**Verification**: Open Copilot Chat → type `@pubmed-search` → you should see the server listed.

---

### Claude Desktop

**Config file**: `claude_desktop_config.json`

| OS | Path |
| --- | --- |
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

```text
Copilot Studio ──HTTPS──▶ ngrok ──HTTP──▶ MCP Server (localhost:8765)
```

**Step 1**: Start the MCP server with HTTP transport

```bash
# Option A: Quick start script (uses ngrok)
./scripts/start-copilot-ngrok.sh

# Option B: Manual setup
uv run python run_copilot.py --port 8765

# Option C: Full 42-tool primary MCP surface with Copilot-compatible HTTP semantics
uv run python run_server.py --transport streamable-http --copilot-compatible --port 8765
```

**Step 2**: Expose via ngrok (if not using the script)

```bash
ngrok http --url=your-domain.ngrok.dev 8765
```

**Step 3**: Configure in Copilot Studio

| Setting | Value |
| --- | --- |
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

# From source (development, stdio)
cd pubmed-search-mcp
uv run python -m pubmed_search.presentation.mcp_server
```

---

## Verification & Troubleshooting

### Quick Health Check

After configuring any client, verify the server is working:

1. **Ask the AI**: "List all available PubMed tools" — the AI should enumerate 42 tools in the primary MCP surface
2. **Simple search**: "Search PubMed for CRISPR gene therapy" — should return article results
3. **Check tool list**: The server provides tools like `unified_search`, `fetch_article_details`, `get_fulltext`, etc.

### Common Issues

| Problem | Solution |
| --- | --- |
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

See [DEPLOYMENT.md](#/deployment) for full production deployment instructions.
