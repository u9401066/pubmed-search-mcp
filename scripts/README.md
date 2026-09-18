# Maintenance script map

Run Python scripts with `uv run` from the repository root. Canonical validation
policy is in [CONTRIBUTING](../CONTRIBUTING.md) and [AGENTS](../AGENTS.md).

| Purpose | Entry points |
| --- | --- |
| Required local gates | `check_repo.py full` before push; `check_repo.py smoke` is the smaller independent CI gate |
| Documentation generation | `build_docs_site.py`, `build_github_wiki.py`, `count_mcp_tools.py --update-docs` |
| Semantic review inventory | `perf/symbol_inventory.py --require-reviewed src/` checks existing authored reviews against current files |
| Structural inspection | `perf/complexity_scan.py`, `perf/import_surface_audit.py`; findings require human/agent review |
| Offline execution latency | `perf/search_execution.py --output scripts/_tmp/latency.json`; compare with `--baseline <prior.json>` |
| Retrieval quality and harness evaluation | `benchmark_retrieval.py`, `benchmark_product_harness.py`, `benchmark_agent_harness.py`; agent runs require an explicit execution budget |
| Benchmark transport support | `benchmark_agent_server.py` is an evaluation launcher, not another product server |
| Targeted checks | `check_async_tests.py`, `check_cline_skills.py`, `check_mermaid_rendering.mjs`, `hooks/` |
| Install research skills | `install_research_skills.py` preserves existing entire user-owned skill folders |
| Development and deployment helpers | `start-*`, `setup-*`, `run_https_local.py`, `generate-ssl-certs.sh`; see deployment docs before use |

`perf/` contains inspection and performance experiments; `hooks/` contains
repository validation and tool-specific hook adapters. Keep their established
paths because pre-commit, contributor docs and integrations invoke them.
Use ignored `scripts/_tmp/` for disposable output and [docs/reports](../docs/reports/README.md)
for reviewed evidence. Avoid a new cloud job for a benchmark that can run locally.
