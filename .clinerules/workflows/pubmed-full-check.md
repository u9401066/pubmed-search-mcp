# Full Check: PubMed Search MCP

Run the local verification gates for PubMed Search MCP.

## Step 1: Lint and format

<execute_command>
<command>uv run ruff check .</command>
</execute_command>

<execute_command>
<command>uv run ruff format --check .</command>
</execute_command>

If any step fails, stop and report the failures.

## Step 2: Type check

<execute_command>
<command>uv run mypy src/ tests/</command>
</execute_command>

If it fails, stop and report the failures.

## Step 3: Tests

<execute_command>
<command>uv run pytest</command>
</execute_command>

If it fails, stop and report the failures.

## Step 4: Tool and skill sync

<execute_command>
<command>uv run python scripts/count_mcp_tools.py --update-docs</command>
</execute_command>

<execute_command>
<command>python3 scripts/check_cline_skills.py</command>
</execute_command>

If either step changes files, inspect the diff before continuing.

## Step 5: Diff hygiene

<execute_command>
<command>git diff --check</command>
</execute_command>
