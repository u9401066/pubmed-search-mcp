<!-- Generated from docs/INTEGRATIONS.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# Integrations & Operations Guide

The complete operator-facing extension of the README: choose a runtime contract,
connect an AI client, configure the multi-source and browser brokers, verify the
modern MCP SDK v2 protocol, and recover common failures.

> **Quick Start**: For minimal configuration snippets, see the main [README.md](#/overview#configuration).

---

## Table of Contents

- [Integrations & Operations Guide](#integrations--operations-guide)
  - [Table of Contents](#table-of-contents)
  - [Runtime and Transport Contracts](#runtime-and-transport-contracts)
    - [MCP SDK v2 Protocol Baseline](#mcp-sdk-v2-protocol-baseline)
    - [stdio (Default)](#stdio-default)
    - [Local Loopback Streamable HTTP](#local-loopback-streamable-http)
    - [Multi-User Service](#multi-user-service-auth-and-tenant-isolation)
    - [Auxiliary HTTP APIs](#auxiliary-http-apis)
    - [Python SDK Facade](#python-sdk-facade)
    - [Persistent Artifact Retrieval](#persistent-artifact-retrieval)
  - [Environment Variables](#environment-variables)
    - [Source Selection and Source Gating](#source-selection-and-source-gating)
    - [Commercial Connectors](#commercial-connectors)
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

## Runtime and Transport Contracts

Choose the trust boundary before choosing client-specific options:

![Client integration and deployment workflow](images/integration-deployment-workflow.svg)

| Contract | Entry point | State and network boundary |
| --- | --- | --- |
| **Local stdio** | `uvx pubmed-search-mcp` | One local OS user, durable local store, no MCP listening port |
| **Local loopback HTTP** | `pubmed-search-mcp-http --mode local --host 127.0.0.1` | Trusted single-user integration; MCP requests share the durable `default` tenant |
| **Multi-user service** | `pubmed-search-mcp-http --mode service` | Remote/team use behind HTTPS; bearer principal and Host/Origin allowlists are mandatory |

### MCP SDK v2 Protocol Baseline

This release uses `mcp>=2.0,<3` and the modern 2026-07-28 MCP request model.
A current HTTP client sends JSON-RPC `tools/list` and `tools/call` requests
directly; it does **not** begin with `initialize` and does not depend on
`Mcp-Session-Id`. Service clients must send their bearer credential on every
protected request. Legacy protocol compatibility, when used by an older client,
never becomes an identity, authorization, or persistence boundary.

Use Streamable HTTP for current remote clients. The legacy SSE transport remains
available only as a compatibility surface. See the
[MCP protocol update](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
and the repository's [deployment smoke checklist](#/deployment#10-%E9%A9%97%E8%AD%89%E6%B8%85%E5%96%AE).

### stdio (Default)

The client spawns the server as a subprocess and communicates via stdin/stdout.
No networking configuration is needed. The stdio entry point always uses local
mode and does not start an auxiliary HTTP listener unless
`PUBMED_STDIO_AUX_HTTP=1` is explicitly set.

```bash
uvx pubmed-search-mcp
```

### Local Loopback Streamable HTTP

For a local connector or protocol smoke test:

```bash
# Local loopback HTTP
pubmed-search-mcp-http --mode local --transport streamable-http \
  --host 127.0.0.1 --port 8765

# Via run_copilot.py (12-tool primitive-schema smoke for Copilot Studio)
uv run python run_copilot.py --port 8765
```

The simplified inventory includes `unified_search` plus primitive-schema
`read_session`, so a Copilot smoke can inspect durable search runs, obtain
non-executing replay arguments, and read a persisted artifact without switching
to the full schema.

The MCP endpoint is available at `http://localhost:8765/mcp`. Do not change only
the bind address and treat this as a remote service. Explicit local mode is a
trusted single-user contract: its loopback MCP requests use the durable
`default` tenant, so `pmids="last"`, sessions, article cache, and exports survive
across requests and reconnects. The launcher-enforced loopback bind and
Host/Origin allowlists are the security boundary.

> **Note**: Legacy SSE (`--transport sse`) is retained for older integrations;
> new deployments should use Streamable HTTP.

### Multi-User Service (Auth and Tenant Isolation)

Service mode is fail closed. It refuses startup unless bearer credentials, the
public resource-server URL, and Host/Origin allowlists are all configured:

```bash
export PUBMED_SERVER_MODE=service
export PUBMED_AUTH_TOKENS="team-a:$(openssl rand -hex 32),team-b:$(openssl rand -hex 32)"
export PUBMED_AUTH_RESOURCE_SERVER_URL="https://mcp.example.org/mcp"
export PUBMED_AUTH_ISSUER_URL="https://mcp.example.org"  # optional; defaults to resource origin
export PUBMED_ALLOWED_HOSTS="mcp.example.org"
export PUBMED_ALLOWED_ORIGINS="https://mcp.example.org"
export PUBMED_TRUSTED_PROXY_IPS="127.0.0.1"  # only the actual TLS proxy
pubmed-search-mcp-http --mode service --transport streamable-http --host 0.0.0.0 --port 8765
```

Clients then present the token as a bearer credential:

```jsonc
{
  "servers": {
    "pubmed-search": {
      "type": "http",
      "url": "https://mcp.example.org/mcp",
      "headers": { "Authorization": "Bearer <your token>" }
    }
  }
}
```

Each authenticated principal gets its **own** session, article cache, search
history, `pmids="last"`, artifacts, exports, chronicles, and pipelines. An MCP
transport session identifier is protocol lifecycle state, not tenant identity or
authorization, and never grants persistence.

Filesystem-facing capabilities are deliberately narrower for authenticated
service callers:

| Capability | Local stdio / loopback HTTP | Authenticated service |
| --- | --- | --- |
| Saved pipelines | `workspace`, `global`, or `auto`; caller may load `file:path.yaml` | Tenant-derived store only; `auto` resolves below that principal's data root and `file:` reads are rejected |
| Literature notes | Caller may choose `output_dir` and `template_file` | Caller cannot choose host paths or read a template file; built-in formats write below `<tenant-root>/references/` |
| Scheduler | May be enabled for a trusted local process | Disabled by `docker-compose.service.yml`; future scheduling needs one leader/lease, not one scheduler per request worker |
| Institutional settings | Local user may configure process-owned access settings | Authenticated callers cannot mutate process-global institutional configuration |
| Server-local paths | May be exposed explicitly to a trusted local client | Redacted by default; remote clients retrieve artifacts through `read_session` |

The word `workspace` never means a shared team directory in service mode. A
tenant-derived pipeline store intentionally drops the process-wide workspace
root so one principal cannot read another principal's repository files.
Authenticated service callers cannot read `file:` paths from the server
filesystem; save the pipeline in the current tenant store and load it by name.
They also cannot choose `output_dir` or `template_file` for notes; use a built-in
format in the principal-scoped `references/` directory.

For containers, use `docker-compose.yml` only as a single-user loopback demo and
`docker-compose.service.yml` for the authenticated, persistent, single-replica
service. See [DEPLOYMENT.md](#/deployment) for the complete contract.

### Auxiliary HTTP APIs

![Session cache and auxiliary HTTP API workflow](images/session-cache-and-http-api.svg)

Besides the primary MCP contract at `/mcp`, the packaged HTTP CLI exposes
auxiliary routes. Only liveness/readiness metadata is public in service mode;
tenant data and exports require the same bearer principal as MCP:

| Endpoint | Purpose |
| --- | --- |
| `/health` | Liveness probe (open) |
| `/ready` | Readiness probe: transport, whether auth is enforced, active tenant count (open) |
| `/api/cached_article/{pmid}` | Read one cached article, optionally fetch on miss |
| `/api/cached_articles?pmids=...` | Read multiple cached articles |
| `/api/session/summary` | Read current session summary |
| `/exports` | List opaque export ids belonging to the current local or authenticated tenant |
| `/download/{export_id}` | Download one opaque export id belonging to that tenant |

In service mode, `/api/*`, `/exports`, and `/download/*` require the same bearer
token as `/mcp` and return only that principal's data. `/health` and `/ready`
stay open for orchestrator probes. In explicit local mode these routes use the
same durable single-user `default` tenant as `/mcp`; in service mode an
anonymous request is always rejected and never falls back to local state.

This auxiliary API is a convenience for cache and session reads; it is **not** the
primary MCP tool contract. For agent tool discovery and normal runtime usage,
`/mcp` remains the canonical external interface.

### Python SDK Facade

For in-process Python integrations, use the SDK facade instead of importing MCP
tool modules or relying on auxiliary HTTP endpoints:

```python
from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig

client = PubMedSearchClient(PubMedSearchConfig(email="your@email.com"))
result = await client.unified_search("remimazolam ICU sedation", limit=20)

articles = result.articles
source_counts = result.source_counts
artifact = result.artifact
```

Use `/mcp` for agent tool discovery and task-oriented MCP calls. Use
`pubmed_search.api` for Python package, notebook, or application code that wants
an in-process object contract.

### Persistent Artifact Retrieval

When session persistence is enabled, `unified_search` and `get_fulltext` write
complete reusable outputs to local artifact files and return a compact
`artifact` locator in the MCP response. Local path fields are redacted by
default; set `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true` for local MCP clients
that should receive `local_path` and `manifest_path` directly. Remote clients
should use the MCP session facade:

```text
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_id="...", artifact_file="payload.json", offset=0, max_chars=200000)
read_session(action="list_artifacts", include_local_paths=true)
```

`read_session(action="artifact")` reads existing artifact files only; it does
not repeat upstream source calls. Use `offset` and `max_chars` to page through a
large artifact from remote clients. `read_session` redacts local paths by
default; pass `include_local_paths=true` for local-server workflows.
The `local_path` and `manifest_path` fields are paths on the MCP server host,
not portable client paths. Full-text artifacts can contain copyrighted,
subscription, or institutionally accessed article text; keep redistribution and
retention aligned with the applicable publisher, license, and institutional
terms.
Large `get_fulltext` responses are capped inline when an artifact is available;
use `read_session(action="artifact", ...)` to retrieve the saved full content.

`unified_search` can also return partial source diagnostics without failing the
whole query. JSON responses use `source_errors`; markdown responses include a
`Source warnings` line. Semantic Scholar HTTP 429 warnings recommend setting
`S2_API_KEY` / `SEMANTIC_SCHOLAR_API_KEY`, retrying later, or excluding the
source with `sources="auto,-semantic_scholar"` /
`PUBMED_SEARCH_DISABLED_SOURCES=semantic_scholar`.

---

## Environment Variables

Semantic Scholar accepts either `S2_API_KEY` or `SEMANTIC_SCHOLAR_API_KEY`.
If repeated 429 responses appear in Cline or other MCP clients, set a key or
temporarily disable the source with `PUBMED_SEARCH_DISABLED_SOURCES=semantic_scholar`.

Live provider queries and bulk datasets are intentionally separate. Semantic
Scholar release/manifest/diff inspection is an operator data-plane workflow;
it never downloads a dataset partition during `unified_search`. OpenAlex cursor
and native semantic modes are likewise bounded broker capabilities, while an
entire-corpus mirror must use the operator snapshot path. See
[Semantic Scholar data plane](#/semantic-scholar-api),
[OpenAlex search/data plane](#/openalex-api), and the
[ClinicalKey AI licensed boundary](#/clinicalkey-ai).

Provider-native execution stays behind the single literature-search facade:

```text
unified_search(query="treatment resistance",
               sources="openalex",
               options="native_semantic")

unified_search(query="melanoma AND immunotherapy",
               sources="pubmed,openalex,semantic_scholar",
               options="systematic")
```

The flags are mutually exclusive and disable multi-strategy deep expansion.
Explicit unsupported source/mode pairs fail before I/O; automatic mode keeps
capable sources only. The per-source MCP `limit` stays at most 100. Inspect
`source_metadata` and the artifact's `query_strategy.json` for the actual
provider mode, compiled/canonical query, continuation, cost/rate fields, and
warnings. This bounded mode is not an exhaustive systematic-review claim.

| Variable | Required | Description | Default |
| --- | --- | --- | --- |
| `NCBI_EMAIL` | **Yes** | Email for NCBI API policy compliance | `pubmed-search@example.com` |
| `NCBI_API_KEY` | No | NCBI API key for higher rate limits (10 req/s vs 3 req/s) | — |
| `CORE_API_KEY` | No | [CORE API](https://core.ac.uk/services/api) key for open access search | — |
| `S2_API_KEY` / `SEMANTIC_SCHOLAR_API_KEY` | No | Semantic Scholar `x-api-key`; improves live quota stability and is required to obtain dataset partition/diff URLs | — |
| `OPENALEX_API_KEY` | No | OpenAlex API key for a higher credit budget; runtime decisions still use response rate/cost metadata | — |
| `CLINICALKEY_AI_ENABLED` | No | Enables only the default-off ClinicalKey application/data-plane adapter; it never adds an MCP tool/source | `false` |
| `CLINICALKEY_AI_ENTITLEMENT_CONFIRMED` | ClinicalKey adapter | Operator assertion that licensed API entitlement is active | `false` |
| `CLINICALKEY_AI_CONTRACT_ACKNOWLEDGED` | ClinicalKey adapter | Operator assertion that MCP/retention/use terms were reviewed for this deployment | `false` |
| `CLINICALKEY_AI_CLIENT_ID` | ClinicalKey adapter | OAuth client id held by the operator secret store | — |
| `CLINICALKEY_AI_CLIENT_SECRET` | ClinicalKey adapter | OAuth client secret; never logged or persisted | — |
| `CROSSREF_EMAIL` | No | Optional CrossRef polite-pool email override. Defaults to the runtime server contact email. | `NCBI_EMAIL`, CLI `--email`, or detected git email |
| `UNPAYWALL_EMAIL` | No | Optional Unpaywall email override. Defaults to the runtime server contact email. | `NCBI_EMAIL`, CLI `--email`, or detected git email |
| `PUBMED_SEARCH_DISABLED_SOURCES` | No | Comma-separated source keys to globally disable in unified_search and cross-search | — |
| `PUBMED_SERVER_MODE` | HTTP only | `local` for loopback development or `service` for fail-closed remote/team use | `local` |
| `PUBMED_LOCAL_ALLOW_CONTAINER_BIND` | No | Explicit local-container exception permitting an internal `0.0.0.0` bind; the host port must still publish only to loopback | `false` |
| `PUBMED_STDIO_AUX_HTTP` | No | Opt in to the stdio process's loopback auxiliary HTTP API | `false` |
| `PUBMED_AUTH_TOKENS` | **Service: yes** | Comma-separated `principal:token` credentials; inject from a secret store | — |
| `PUBMED_AUTH_RESOURCE_SERVER_URL` | **Service: yes** | Public HTTPS MCP resource-server URL, including `/mcp` | — |
| `PUBMED_AUTH_ISSUER_URL` | No | Issuer advertised in auth metadata; defaults to the public resource URL origin | Resource URL origin |
| `PUBMED_ALLOWED_HOSTS` | **Service: yes** | Comma-separated public Host allowlist | Safe loopback defaults in local mode |
| `PUBMED_ALLOWED_ORIGINS` | **Service: yes** | Comma-separated HTTPS Origin allowlist | Safe loopback defaults in local mode |
| `PUBMED_TRUSTED_PROXY_IPS` | No | Exact reverse-proxy IP allowlist; empty means forwarded headers are not trusted | — |
| `PUBMED_TENANT_ISOLATION` | Service forces `true` | Keep authenticated principals in separate state/storage scopes | `true` |
| `PUBMED_TENANT_MAX_CONCURRENCY` | No | Maximum in-flight requests per authenticated principal | `8` |
| `PUBMED_NOTES_DIR` | No | Local wiki/Foam-compatible/Markdown/MedPaper-style note export directory used by `save_literature_notes` | `PUBMED_WORKSPACE_DIR/references`, `PUBMED_DATA_DIR/references`, then `~/.pubmed-search-mcp/references` |
| `PUBMED_WORKSPACE_DIR` | No | Workspace root used for pipeline persistence and note export fallback | — |
| `PUBMED_DATA_DIR` | No | User-level data root used for cache/persistence and note export fallback | `~/.pubmed-search-mcp` |
| `PUBMED_PROFILING` | No | Enable runtime profiling diagnostics | `false` |
| `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS` | No | Include server-local artifact paths for trusted local clients | `false` |
| `PUBMED_FULLTEXT_INLINE_MAX_CHARS` | No | Maximum inline full-text characters before artifact paging | `20000` |
| `PUBMED_SCHEDULER_ENABLED` | No | Enable the saved-pipeline scheduler for a trusted local process; the authenticated service Compose profile forces it off | `true` |
| `PUBMED_SCHEDULER_TIMEZONE` | No | Scheduler timezone | `UTC` |
| `PUBMED_SCHEDULER_MAX_INSTANCES` | No | Maximum scheduler instances per process; it does not provide distributed leader election | `1` |
| `SCOPUS_ENABLED` | No | Enable the default-off Scopus connector (`true/false`) | `false` |
| `SCOPUS_API_KEY` | No | Elsevier Scopus API key. Required when `SCOPUS_ENABLED=true` | — |
| `SCOPUS_INSTTOKEN` | No | Optional Elsevier institutional token for Scopus | — |
| `WEB_OF_SCIENCE_ENABLED` | No | Enable the default-off Web of Science connector (`true/false`) | `false` |
| `WEB_OF_SCIENCE_API_KEY` | No | Clarivate Web of Science API key. Required when `WEB_OF_SCIENCE_ENABLED=true` | — |
| `OPENURL_RESOLVER` | No | Institutional link resolver base URL | — |
| `OPENURL_PRESET` | No | Preset name for institutional resolver | — |
| `OPENURL_ENABLED` | No | Enable/disable OpenURL resolver | `true` |
| `INSTITUTIONAL_DIRECT_FETCH` | No | Try direct DOI / EZproxy fulltext retrieval inside `get_fulltext` before CORE fallback | `true` |
| `EZPROXY_ENABLED` | No | Enable EZproxy fulltext retrieval after setting host and cookie | `false` |
| `EZPROXY_HOST` | No | EZproxy hostname, e.g. `ezproxy.lib.example.edu` | — |
| `EZPROXY_COOKIE_FILE` | No | Browser-exported cookies JSON file for EZproxy requests | — |
| `EZPROXY_COOKIE` | No | Inline cookie header string for EZproxy requests | — |
| `BROWSER_FETCH_CONFIG` | No | Preferred single JSON setting for browser-session broker and auto mode | — |
| `BROWSER_FETCH_ENABLED` | No | Enable browser-session broker via per-field envs | `false` |
| `BROWSER_FETCH_AUTO` | No | Auto-use broker when tool call omits allow_browser_session | `false` |
| `BROWSER_FETCH_BROKER_URL` | No | Local broker endpoint, e.g. `http://127.0.0.1:8766/fetch` | — |
| `BROWSER_FETCH_TOKEN` | No | Shared bearer token for the local broker | — |
| `BROWSER_FETCH_ALLOWED_HOSTS` | No | Comma-separated host allow-list for broker targets | — |
| `BROWSER_FETCH_TIMEOUT` | No | Browser-session client and broker timeout in seconds | `45` |
| `BROWSER_FETCH_MAX_BYTES` | No | Maximum PDF payload accepted from the broker | `52428800` |
| `BROWSER_FETCH_REQUIRE_LOCAL` | No | Require the configured broker URL to be localhost | `true` |
| `BROWSER_FETCH_VERIFY_TLS` | No | Verify TLS when calling an HTTPS broker URL | `true` |
| `PUBMED_HTTP_API_PORT` | No | Port for background HTTP API (stdio mode) | `8765` |
| `HTTP_PROXY` / `HTTPS_PROXY` | No | Proxy settings for outbound requests | — |
| `BROWSER_FETCH_BROKER_TOKEN` | No | Bearer token expected by the local broker server | Falls back to `BROWSER_FETCH_TOKEN`; otherwise a high-entropy runtime token is generated and printed |
| `BROWSER_FETCH_BROKER_HOST` | No | Broker bind host | `127.0.0.1` |
| `BROWSER_FETCH_BROKER_PORT` | No | Broker bind port | `8766` |
| `BROWSER_FETCH_BROKER_HEADLESS` | No | Run broker browser headless | `false` |
| `BROWSER_FETCH_BROKER_USER_DATA_DIR` | No | Persistent browser profile directory for broker login state | `~/.pubmed-search-mcp/browser-broker-profile` |
| `BROWSER_FETCH_BROKER_DOWNLOAD_DIR` | No | Temporary broker download directory | `~/.pubmed-search-mcp/browser-broker-downloads` |

### Source Selection and Source Gating

![Search and query intelligence workflow](images/search-query-workflow.svg)

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
| [Semantic Scholar API Key](https://www.semanticscholar.org/product/api) | Request through the official API page | More stable live quota; dataset file/diff manifests require a key |
| [OpenAlex API Key](https://help.openalex.org/api/authentication/) | Follow the official authentication guide | Higher credit budget; actual rate/cost remains response-driven |
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
        "S2_API_KEY": "your_semantic_scholar_key",
        "OPENALEX_API_KEY": "your_openalex_key",
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
        "BROWSER_FETCH_CONFIG": "{\"enabled\":true,\"auto_enabled\":true,\"broker_url\":\"http://127.0.0.1:8766/fetch\",\"token\":\"<random-32-byte-token>\",\"allowed_hosts\":[\"jamanetwork.com\",\"*.jamanetwork.com\"]}"
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
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
uv run pubmed-browser-fetch-broker --token "<same-random-32-byte-token>"
```

Use the generated value in both the broker command and MCP client config; do
not reuse a published example token. When `--token` is omitted, the broker
generates and prints a high-entropy runtime token. It always rejects non-loopback
binds, Host headers, and browser Origins.

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

PubMed Search MCP now ships a workspace-scoped Cline overlay so project users do not need to recreate rules by hand:

- `AGENTS.md`: shared baseline used to avoid duplicating common rules across agents
- `.clinerules/*.md`: Cline-only rules, mostly path-scoped to keep context lean
- `.clinerules/workflows/*.md`: reusable harness workflows for validation, MCP sync, and dual-agent setup
- `.vscode/extensions.json`: recommended VS Code extensions for Copilot + Cline + Python support
- `scripts/setup-vscode-ai-harness.sh`: installs the recommended extension set with one command

This split keeps shared behavior in one place while leaving Copilot-specific behavior in `.github/` and Cline-specific automation in `.clinerules/`.

**Config file**: `cline_mcp_settings.json`

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com",
        "S2_API_KEY": "your_semantic_scholar_key",
        "PUBMED_SEARCH_DISABLED_SOURCES": ""
      },
      "alwaysAllow": [],
      "disabled": false
    }
  }
}
```

For repeated Semantic Scholar 429 responses, either provide `S2_API_KEY` /
`SEMANTIC_SCHOLAR_API_KEY` or set `PUBMED_SEARCH_DISABLED_SOURCES` to
`semantic_scholar`.

Recommended first-run sequence:

```bash
./scripts/setup-vscode-ai-harness.sh
```

Then restart VS Code, confirm Cline sees the workspace rules/workflows, and confirm Copilot Chat lists the `pubmed-search` MCP server from `.vscode/mcp.json`.

---

### Microsoft Copilot Studio

![Copilot Studio deployment flow](images/copilot-studio-deployment-flow.svg)

Copilot Studio requires **Streamable HTTP** transport with a public URL.

**Architecture**:

```text
Copilot Studio ──HTTPS──▶ ngrok ──HTTP──▶ MCP Server (localhost:8765)
```

**Step 1**: Start the MCP server with HTTP transport

```bash
# Option A: Full 45-tool primary MCP surface with an assigned ngrok dev/custom domain
export PUBMED_AUTH_TOKENS="copilot:$(openssl rand -hex 32)"
export NGROK_DOMAIN="your-domain.ngrok.dev"
./scripts/start-copilot-studio.sh --with-ngrok

# Option B: the same authenticated service with an assigned ngrok domain
export PUBMED_AUTH_TOKENS="copilot:$(openssl rand -hex 32)"
export NGROK_DOMAIN="your-domain.ngrok.dev"
./scripts/start-copilot-ngrok.sh

# Option C: simplified 12-tool local schema smoke (never tunnel this mode)
uv run python run_copilot.py --port 8765

# Option D: manual service when the public URL is already known
export PUBMED_AUTH_TOKENS="copilot:$(openssl rand -hex 32)"
export PUBMED_AUTH_RESOURCE_SERVER_URL="https://your-domain.ngrok.dev/mcp"
export PUBMED_ALLOWED_HOSTS="your-domain.ngrok.dev"
export PUBMED_ALLOWED_ORIGINS="https://your-domain.ngrok.dev"
pubmed-search-mcp-http --mode service --transport streamable-http \
  --copilot-compatible --host 127.0.0.1 --port 8765
```

**Step 2**: Expose the already configured service via ngrok (if not using a
script)

```bash
ngrok http --url=your-domain.ngrok.dev 8765
```

**Step 3**: Configure in Copilot Studio

| Setting | Value |
| --- | --- |
| Server name | `PubMed Search` |
| Server URL | `https://your-domain.ngrok.dev/mcp` |
| Authentication | Bearer token for service mode; `None` only during an unpublished local smoke test |

**Environment variables** for the authenticated custom-domain ngrok wrapper:

```bash
export NGROK_DOMAIN="your-domain.ngrok.dev"
export COPILOT_PORT=8765
export PUBMED_AUTH_TOKENS="copilot:$(openssl rand -hex 32)"
./scripts/start-copilot-ngrok.sh
```

Both tunnel scripts converge on the same fail-closed `--mode service` launcher.
They require bearer credentials plus an assigned `NGROK_DOMAIN`, reject an
already occupied backend port, start the loopback service first, and verify
`/ready` plus unauthenticated `/mcp` rejection before ngrok is started. The
resource URL and Host/Origin allowlists are derived from that known HTTPS
domain. `run_copilot.py` remains loopback-only and must not be tunneled.

The simplified surface still exposes the generic search as `unified_search`,
not a PubMed-only alias. Its primitive schema accepts `query`, `limit`,
`min_year`, `max_year`, `sources`, and `options`, then delegates to the
same unified runner as the primary surface. This keeps the single-search
contract while avoiding Copilot Studio `anyOf` / `$ref` schema problems.

> See [copilot-studio/README.md](https://github.com/u9401066/pubmed-search-mcp/blob/master/copilot-studio/README.md) for the full OpenAPI schema and Copilot Studio setup walkthrough.

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

1. **Local stdio**: ask the AI to list PubMed tools; it should enumerate 45 tools in the primary MCP surface.
2. **HTTP probes**: confirm `/health`, `/ready`, and `/info`; a service-mode health probe must use an allowed `Host`.
3. **Modern MCP call**: send authenticated `tools/list` directly, without `initialize` or `Mcp-Session-Id`.
4. **Simple search**: ask for "CRISPR gene therapy" and confirm `unified_search` reports source counts or explicit source warnings.
5. **Isolation check**: in service mode, verify two bearer principals cannot read each other's session, export, artifact, chronicle, note, or pipeline state.

### Common Issues

| Problem | Solution |
| --- | --- |
| `uvx` not found | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Server not connecting | Check the config file path and JSON syntax |
| `NCBI_EMAIL` warning | Set the `NCBI_EMAIL` environment variable in the config |
| Slow responses | Add `NCBI_API_KEY` for 10 req/s (vs 3 req/s default) |
| Tool output shows `Canceled: Canceled` during progress reporting | Update to a build with non-cancelling best-effort progress callbacks. If a specific broad search still exceeds your client's own tool timeout, retry with `options="shallow"` or specify narrower `sources`. |
| Source API uses placeholder email | Set `NCBI_EMAIL` or pass `--email`; CrossRef, Unpaywall, and OpenAlex reuse that runtime contact unless a source-specific override/API key is configured |
| CORE search fails | Set `CORE_API_KEY` — [get one free](https://core.ac.uk/services/api) |
| Behind proxy | Set `HTTP_PROXY` / `HTTPS_PROXY` environment variables |
| Modern client waits for an MCP session id | Remove the obsolete initialize/session-id handshake; send `tools/list` or `tools/call` directly |
| Service note export rejects `output_dir` or `template_file` | This is intentional; omit host paths and use a built-in note format in the tenant's isolated `references/` directory |
| Service pipeline rejects `file:` or `workspace` scope | Save the YAML into the authenticated tenant store and load it as `saved:<name>`; service callers cannot read process-wide workspace files |
| Scheduled service pipeline does not run | The service Compose profile disables the in-process scheduler; run manually or design a single external leader/lease before enabling schedules |

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

The default Compose file is a single-user loopback demo. Team/remote use has a
separate fail-closed service profile:

```bash
# Local loopback demo
docker compose up -d

# Local self-signed HTTPS smoke test
docker compose -f docker-compose.https.yml up -d

# Authenticated service (populate the ignored .env from the example first)
cp .env.service.example .env
docker compose --env-file .env -f docker-compose.service.yml up -d
```

The service profile uses a persistent volume, one replica/server process, a
disabled in-process scheduler, and a host-loopback application port intended for
a trusted same-host TLS proxy. See
[DEPLOYMENT.md](#/deployment) for proxy, secret, backup, and readiness
requirements.
