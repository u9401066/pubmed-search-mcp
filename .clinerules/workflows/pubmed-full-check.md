# Full Check: PubMed Search MCP

Run the same complete local gate used before push:

<execute_command>
<command>uv run --frozen python scripts/check_repo.py full</command>
</execute_command>

This runs lint, format, async consistency, types, and all non-live tests,
including the fresh-wheel and real MCP transport checks. A failure stops the
gate. Use focused tests first for a narrow change; see `CONTRIBUTING.md` for
explicit Mermaid, container, and live-provider checks.

When changing tool or skill contracts, regenerate the relevant assets and
inspect the diff before repeating affected checks:

<execute_command>
<command>uv run python scripts/count_mcp_tools.py --update-docs</command>
</execute_command>

<execute_command>
<command>uv run python scripts/check_cline_skills.py</command>
</execute_command>

<execute_command>
<command>git diff --check</command>
</execute_command>
