# Search integration maintenance audit — 2026-09-15

Latest follow-up: [v0.7.4 scheduling, provider safety and document organization](release_v074_2026-09-18.md).

The [ten-phase core review](core_review_2026-09-15.md) completed all 2,901
definitions in v0.7.3. This report preserves the earlier maintenance snapshot;
use the latest release follow-up above for current counts and gates.

Scope: local source, tests, CI configuration, and shipped agent guidance. This
is a maintenance change to the academic search integration layer, not a new
autonomous research agent. No model benchmark, provider live run, or release
was started. No retrieval-score improvement is claimed from this work.

The subsequent [renovation audit](renovation_plan_2026-09-15.md) adds a complete
Python symbol inventory, explicit review accounting, cache/export/DOI fixes,
and the fulltext fallback consolidation. Counts and validation below are the
earlier maintenance snapshot, not the current working-tree totals.

## Findings and changes

| Finding | Change | Retained protection |
| --- | --- | --- |
| Ordinary CI scheduled nine jobs: six full fast-suite environments, quality/package, Mermaid, and container | One independent smoke job; full matrix/render/container require `run_extended_checks` | Full pre-push gate; source, error, provenance, docs, stdio, HTTP, and fresh-wheel smoke; complete tag-publication verification |
| Installing pre-commit alone did not install the push hook; the old push command forced four workers | Default hook types include commit and push; one shared sequential `check_repo.py full` | No success cache, no trust in a report from an older commit, live-provider exclusion |
| Semgrep downloaded upstream rules during normal push | Move it to explicit manual invocation | Bandit remains a commit-stage security check; source scanning was also run locally |
| Coverage-driven tests included an always-true length assertion, swallowed exceptions, registration-only checks, exact duplicates, and sleep-only rate-limit exercises | Remove 26 test functions, including seven duplicate month-parser cases | Stronger source/transport/session suites, deterministic rate-limit schedule regression, one canonical month-parser suite |
| CI metadata test asserted a display name and inline wheel command | Check executable shared-gate wiring and required acceptance paths | Detect accidentally dropping wheel acceptance or re-enabling the default full matrix |
| Two identical month parsers, a third sorting parser, and duplicate year parsers could drift | One application-layer publication-date module | Timeline/milestone tests and a consumer-level ordering/date regression |
| Boolean month values became January; signed numeric months could sort differently from their event date | Reject boolean months and use the same parser in ordering and event construction | An in-memory reintroduction of boolean-as-January makes the regression fail |
| Generic Cline project/full-check/release guidance referred to sibling projects and absent directories | Route generic entrypoints to PubMed guidance; scope Zotero project rules and remove its broad Python-script scope | Existing PubMed workflow remains canonical; sibling references are not copied into installed research skills |
| The test-generation skill encouraged broad suites, coverage quotas, and automatic parallel execution | Replace generic multi-language scaffolding with focused regression selection and links to shared policy | Failure, cancellation, isolation, budget, and persistence contracts remain explicit priorities |

Nine to one is a configured job-count reduction, **not a measured reduction in
GitHub billing or runtime**. Pages/Wiki deployment workflows and tag publication
are separate and remain available. Cross-platform checks no longer happen on
every PR: contributors must request extended checks for platform/dependency
changes and before release. A bypassed local hook is not evidence of a full pass.

## Harness installation ownership

The existing VS Code setup shell script only installs extensions; it did not
overwrite workspace files. The new explicit `install_research_skills.py`
helper copies only missing `pubmed-*` and `pipeline-persistence` skill folders
from a source checkout. Existing whole folders are user-owned and skipped,
including their references, even after a bundle update or interrupted install.

It has no force/reset mode and does not copy contributor rules, `AGENTS.md`,
hooks, or MCP settings. Dry-run does not create directories. File, directory,
and symlink collisions are preserved; symlinked destination parents are
rejected. Users review/merge upgrades against the printed source path.

This does not change an installer in a separate Zotero/Asset-Aware VSIX. Such
installers need their own adoption and upgrade-preservation tests; this repo
must not claim to have fixed their activation behavior. Git merges of tracked
repository instructions also remain separate from skill installation.

## Redundancy audit boundaries

An AST comparison scanned 2,435 source functions/methods and 4,853 test/support
functions in the starting tree. Ignoring docstrings and requiring at least
three body statements found six exact source-body duplicate groups and 19
test/support groups. These are candidate counts, not a semantic duplicate or
dead-code percentage. They do not prove the rest of the system is minimal.

The date parsers were consolidated because their consumers need the same
calendar policy and already showed inconsistent behavior. Other matches were
not merged blindly: lazy module exports preserve package boundaries; RIS and
BibTeX author renderers have distinct format responsibilities; HTTP readers
have different decoding/security policies; provider-specific DOI helpers
need contract review before replacement. Repeated fixtures and similarly
shaped tests for different providers are not automatically redundant.

The removed weak tests have stronger protection in `test_session_tools.py`,
`test_all_tools_mcp_acceptance.py`, `test_search_and_discovery.py`,
`test_ncbi_provider_schema_contracts.py`, `test_async_utils.py`, and the retained
formatter/cache suites. This was a conservative first cleanup, not a blanket
deletion of older coverage-named modules.

## Validation

- `uv run --frozen python scripts/check_repo.py full`: **4,546 passed, 23 skipped,
  30 deselected**, 108.02 seconds for pytest; Ruff, format (465 files), async
  consistency, and mypy (429 files) also passed.
- `uv run --frozen python scripts/check_repo.py smoke`: **163 passed**, 12.59
  seconds for pytest. This is the actual command used by ordinary cloud CI.
- The initial full run found one stale CI step-name assertion; it was replaced
  with executable gate/acceptance checks, then the complete gate was rerun.
- Actual Mermaid parsing/rendering: **121 diagrams rendered to SVG**. The
  real-stdio MCP test with mandatory Mermaid rendering also passed.
- In-memory fault injection: restoring boolean-as-January behavior made the
  timeline regression fail as expected; no source file was mutated on disk.
- Installer tests cover upgrade preservation, incomplete directories, file and
  symlink collisions, dry-run, and source/destination isolation. The real bundle
  dry-run discovered the expected 11 research skills without copying files.
- DDD, Cline/Codex skills, instruction/hook consistency, pre-commit configuration,
  Bandit, deptry, vulture, and diff whitespace checks passed. Informational hook
  version and existing Bandit suppression warnings were not failures.
- Both Git hooks were installed in this checkout. Other clones must run
  `uv run pre-commit install` themselves.

The shared commands are documented in `CONTRIBUTING.md`; no cloud workflow was
triggered to discover local failures. Docker is unavailable in this environment,
so this change does not claim a new container build or Windows/macOS matrix pass.
Local pytest timings above are observations, not a cloud cost benchmark.

## Next retrieval-quality work

Keep benchmark changes separate from this maintenance patch. Prioritize fixed
corpus BioASQ document/snippet retrieval, Asta paper-finding/search tasks, then
high-recall review selection and claim-evidence attribution. Compare a thin
same-source adapter, the original MCP, and the changed MCP under equal budgets;
use a fixed external agent only for a second consumer-effectiveness comparison.
Source coverage, retrieval quality, evidence access, and orchestration cost
must be reported separately. The existing 5,000-question model run remains
setup-only until a new execution budget is authorized.
