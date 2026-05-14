# MCP Setup: Asset-Aware MCP (Local STDIO)

This workflow installs (or updates) an MCP server entry for this repository into Cline’s `cline_mcp_settings.json`.

It uses `uv run` so the server runs from the workspace and loads the repo `.env`.

<execute_command>
<command>python3 scripts/install_cline_mcp.py --write</command>
</execute_command>

After it writes settings, restart Cline (or reload the VS Code window) and confirm the server is enabled in the MCP Servers UI.

For custom Cline CLI config roots, use:
<execute_command>
<command>python3 scripts/install_cline_mcp.py --cline-dir "$CLINE_DIR" --only-cli --write</command>
</execute_command>
