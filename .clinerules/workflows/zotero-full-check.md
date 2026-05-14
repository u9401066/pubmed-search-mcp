# Full Check: Zotero Keeper + VS Code Extension

Run the local verification gates for the Zotero Keeper repository.

## Step 1: Zotero server lint/type/test

<execute_command>
<command>cd mcp-server && uv run ruff check .</command>
</execute_command>

<execute_command>
<command>cd mcp-server && uv run mypy src --ignore-missing-imports</command>
</execute_command>

<execute_command>
<command>cd mcp-server && uv run pytest</command>
</execute_command>

If any step fails, stop and report the failures.

## Step 2: Cline skill audit

<execute_command>
<command>python3 scripts/check_cline_skills.py</command>
</execute_command>

If it fails, stop and report the drift.

## Step 3: VS Code extension tests

<execute_command>
<command>cd vscode-extension && npm run sync-assets && npm run compile && npm test</command>
</execute_command>

If it fails, stop and report the failures.

## Step 4: VSIX package smoke

<execute_command>
<command>cd vscode-extension && npm run package</command>
</execute_command>

If packaging fails, stop and report the VSIX issue.

## Step 5: Diff hygiene

<execute_command>
<command>git diff --check</command>
</execute_command>
