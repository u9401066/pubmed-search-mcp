---
paths:
  - "src/**"
  - "tests/**"
  - "scripts/**"
  - "run_server.py"
  - "run_copilot.py"
---

# Python and architecture rules

- Use `uv run` for pytest, mypy, ruff, and Python scripts in this repo.
- Keep MCP presentation files thin. Put orchestration in `application/` and core models in `domain/`.
- Reuse shared transport, source registries, session manager, and existing application services before creating new wrappers.
- Add or update tests for behavior changes in application and infrastructure code.
- Avoid introducing duplicate client-specific config or parallel implementations when a shared path already exists.