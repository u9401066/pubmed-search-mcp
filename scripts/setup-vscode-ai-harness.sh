#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v code-insiders >/dev/null 2>&1; then
  VSCODE_BIN="code-insiders"
elif command -v code >/dev/null 2>&1; then
  VSCODE_BIN="code"
else
  echo "VS Code CLI not found. Install 'code' or 'code-insiders' in PATH first." >&2
  exit 1
fi

extensions=(
  "github.copilot"
  "github.copilot-chat"
  "saoudrizwan.claude-dev"
  "ms-python.python"
  "charliermarsh.ruff"
)

echo "Installing recommended VS Code extensions using ${VSCODE_BIN}..."
for extension in "${extensions[@]}"; do
  "${VSCODE_BIN}" --install-extension "${extension}" >/dev/null
  echo "  - ${extension}"
done

cat <<EOF

Workspace AI harness assets are ready in:
  ${ROOT_DIR}/AGENTS.md
  ${ROOT_DIR}/.clinerules/
  ${ROOT_DIR}/.vscode/mcp.json
  ${ROOT_DIR}/.vscode/extensions.json

Next steps:
  1. Reload VS Code so extension recommendations and MCP configuration refresh.
  2. In Cline, verify workspace rules and workflows are visible.
  3. In Copilot Chat, verify the pubmed-search MCP server is listed.
EOF