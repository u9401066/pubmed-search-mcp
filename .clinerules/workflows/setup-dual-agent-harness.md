# Setup Dual-Agent Harness

Prepare this workspace so GitHub Copilot and Cline can both use the repo productively without duplicate rule sets.

## Step 1: Verify prerequisites
Confirm that `uv` is installed and that the repository root is the current workspace.

## Step 2: Install the recommended VS Code extensions
<execute_command>
<command>./scripts/setup-vscode-ai-harness.sh</command>
<requires_approval>false</requires_approval>
</execute_command>

If `code` or `code-insiders` is unavailable, stop and explain how to install the recommended extensions manually.

## Step 3: Verify workspace assets
Check that the following files exist and explain their roles:
- `AGENTS.md`
- `.clinerules/`
- `.vscode/mcp.json`
- `.vscode/extensions.json`

## Step 4: Explain the layering
Summarize the no-duplication split:
- shared baseline in `AGENTS.md`
- Copilot-specific behavior in `.github/`
- Cline-specific rules and workflows in `.clinerules/`

## Step 5: Suggest the first verification action
Recommend a simple validation prompt or workflow the user should run next.