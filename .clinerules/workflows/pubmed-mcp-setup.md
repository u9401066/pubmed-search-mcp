# MCP Setup: PubMed Search MCP

Use this workflow when configuring the local repository for Cline or another STDIO MCP client.

## Local Server Smoke

<execute_command>
<command>uv run python -m pubmed_search.presentation.mcp_server --help</command>
</execute_command>

If this fails, fix the Python environment first.

## Required Configuration

- Set `NCBI_EMAIL` for NCBI policy compliance.
- Add `NCBI_API_KEY` when higher NCBI rate limits are needed.
- Add `OPENALEX_API_KEY`, `S2_API_KEY`, or `CORE_API_KEY` only when the user has provided them.
- Set `PUBMED_WORKSPACE_DIR` when pipeline/session files should be rooted in a workspace.

## VS Code Extension Path

When using Zotero Keeper's VSIX, prefer the extension setup wizard because it registers both
Zotero Keeper and PubMed Search MCP definitions together.
