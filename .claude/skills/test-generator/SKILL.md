---
name: test-generator
description: "Add focused regression tests for observable PubMed Search MCP behavior. Triggers: test, 測試, 寫測試, pytest, 驗證."
---

# Focused regression tests

Read `AGENTS.md` and the testing policy in `CONTRIBUTING.md`. Those files own
shared validation rules; this skill describes how to choose useful cases.

## Choose the defect before writing the test

1. State the observable incorrect behavior the test must catch: dropped relevant
   papers, wrong filter propagation, a swallowed provider failure, corrupt
   persistence, false citation evidence, or overwritten user configuration.
2. Find the existing suite for that contract. Extend its cases or fixtures
   instead of creating another coverage-percentage or “final push” module.
3. Exercise the public service boundary where practical. For an MCP contract,
   use the existing real protocol acceptance fixture and replace provider I/O
   at its boundary. Keep session, schema, artifacts, and orchestration real.
4. Assert the relevant output, error, or persisted state. `len(result) >= 0`,
   catch-and-ignore exceptions, and mock registration alone do not establish
   correct behavior. Do not duplicate Python/library behavior tests.
5. For an asynchronous policy, use a controlled clock or deterministic event
   synchronization when possible. Avoid sleeping merely to execute more lines.
6. Reproduce the failure before the fix, or temporarily inject that specific
   defect and verify that the test fails. Restore source before continuing.

## Validate locally

```bash
# First run the affected existing suite:
uv run pytest -q tests/test_source_contracts.py
# Before push, use the same complete gate as the installed pre-push hook:
uv run --frozen python scripts/check_repo.py full
```

Default execution is single-process with the configured test timeout. Choose
explicit parallelism only when available memory permits it. Live provider tests
are opt-in; unit and contract tests must not depend on PubMed/API uptime.

Coverage can reveal untested branches, but it is not a quota. Keep meaningful
failure, cancellation, isolation, and recovery cases. Remove duplicate or
ineffective cases only after identifying the stronger retained protection.
Do not add cloud jobs or full-suite matrix runs just because a new test exists;
see `CONTRIBUTING.md` for the small default CI and opt-in extended checks.

When reporting validation, name the regression checked, the actual command and
result, and any environment-dependent checks that were not exercised. A dry
run or successful test collection is not an executed test pass.
