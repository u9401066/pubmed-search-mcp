# Sync MCP Surface

Use this workflow after changing MCP tools, categories, or setup docs.

## Step 1: Inspect changed MCP surfaces
Review the touched files under `src/pubmed_search/presentation/mcp_server/`, `.github/hooks/`, `README*.md`, and `docs/`.

## Step 2: Refresh generated tool and docs artifacts when needed
<execute_command>
<command>uv run python scripts/count_mcp_tools.py --update-docs && uv run python scripts/build_docs_site.py</command>
<requires_approval>false</requires_approval>
</execute_command>

If the change did not affect tool count or README-driven docs, explain why the generation step can be skipped.

## Step 3: Run the sync-focused tests
<execute_command>
<command>uv run pytest tests/test_docs_site_sync.py tests/test_tool_registry.py tests/test_copilot_hook_policy.py -q</command>
<requires_approval>false</requires_approval>
</execute_command>

If a sync artifact is stale, update it before moving on.

## Step 4: Summarize what was synchronized
List which runtime files, generated docs, and policy files changed.