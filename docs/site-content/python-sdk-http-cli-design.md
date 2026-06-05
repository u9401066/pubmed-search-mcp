<!-- Generated from docs/PYTHON_SDK_AND_HTTP_CLI_DESIGN.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# Python SDK And HTTP CLI Design

Status: implemented as a compatibility-first application facade.

## Problem

The package already works well as an MCP server, but Python callers previously
had to choose between low-level `LiteratureSearcher` imports and presentation
internals under `pubmed_search.presentation.mcp_server.tools`. That made the
external package API hard to describe and encouraged callers to depend on MCP
tool modules.

The HTTP server was also documented through the source-tree `run_server.py`
script, which is not an installed package entry point.

## Contracts

The project now has three explicit external contracts:

| Contract | Entry | Audience |
| --- | --- | --- |
| MCP tool surface | `uvx pubmed-search-mcp` and `/mcp` | AI agents and MCP clients |
| Python SDK facade | `from pubmed_search.api import PubMedSearchClient` | Python packages and notebooks |
| HTTP MCP server CLI | `pubmed-search-mcp-http --transport streamable-http` | Remote MCP deployments |

These contracts are related but separate. The auxiliary HTTP cache API is not
the Python SDK, and the Python SDK is not a replacement for MCP tool discovery.

## Design

`pubmed_search.api` is a lightweight facade. Importing it must not load MCP,
FastMCP, HTTP clients, settings, YAML, or source registries. The client creates
runtime dependencies lazily when a method is called.

`pubmed_search.application.unified` owns the stable request/service contract for
unified search. It accepts an injected runner so application and SDK callers do
not import MCP presentation modules at import time.

`pubmed_search.presentation.mcp_server.tools.unified_runner` remains in the
presentation layer because it still formats MCP-compatible strings, reports
FastMCP progress, records MCP session state, and persists session artifacts.
The MCP tool wrapper injects its module-level dependencies into the runner so
existing tests and private patch points remain compatible.

## Deferred Work

The full unified-search execution stack still has presentation-side behavior:
session notification, artifact persistence, response formatting, and source
runner wiring. Moving those into pure application services should happen with
ports for progress, session recording, artifact writing, and source execution.
That migration can be staged without breaking the SDK facade added here.

## Verification

The compatibility contract is covered by:

- `tests/test_public_api_facade.py`
- `tests/test_package_entrypoints.py`
- `tests/test_import_surface.py::test_public_api_import_keeps_mcp_and_http_lazy`
- existing unified-search MCP tests that patch presentation module hook points
