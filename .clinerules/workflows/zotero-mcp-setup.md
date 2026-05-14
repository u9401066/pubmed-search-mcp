# MCP Setup: Zotero Keeper + PubMed Search

Use this workflow when configuring the local repository for Cline.

## VS Code Extension Path

The recommended setup path is the extension command:

- Command Palette: `Zotero MCP: Setup Wizard (One-Click Setup)`
- Then verify the MCP servers in VS Code's MCP Servers UI.

## Local Development Smoke

Check that both Python entrypoints import from the workspace.

<execute_command>
<command>cd mcp-server && uv run python -m zotero_mcp --help</command>
</execute_command>

<execute_command>
<command>cd external/pubmed-search-mcp && uv run python -m pubmed_search.presentation.mcp_server --help</command>
</execute_command>

If either command fails, fix the Python environment before editing Cline MCP settings.
