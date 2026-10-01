# Testing and release gates / 測試與發布分工

The complete local pretest runs before push. Cloud CI independently exercises
installed artifacts and operating-system boundaries; it is not the first place
to discover formatting, type, documentation or ordinary regression failures.

## Commands

```bash
uv sync --frozen --dev
uv run --frozen python scripts/check_repo.py pretest
# `full` is the same complete gate and remains the pre-push hook entrypoint.
uv run --frozen python scripts/check_repo.py smoke
# Verify exactly the distributions that will be published:
uv build --no-sources --out-dir build/release-dist
uv run --frozen python scripts/check_repo.py smoke --release-dist build/release-dist
# Requires Docker; starts the default image command and checks real requests:
docker build --tag pubmed-search-mcp:local .
uv run --frozen python scripts/check_repo.py container --container-image pubmed-search-mcp:local
```

Use a clean distribution directory: the artifact check requires exactly one
wheel and one sdist matching the source version; stale distributions fail before
installation. The wheel is installed once per pytest session into an empty
virtual environment with production dependencies only. The sdist is rebuilt and
its wheel entries are compared with the supplied wheel. The driver runs outside
the checkout, checks the actual import location, and clears inherited credentials,
proxies and `PYTHONPATH` from server subprocesses. Missing `uv`, failed builds and
invalid artifacts fail acceptance instead of silently skipping it.

## Which checks run where?

| Boundary | Local pretest | Ordinary CI | Tag publication |
| --- | --- | --- | --- |
| Lint, format, async tests, types | Required | Already local | Already local |
| File ownership, publication evidence, symbol inventory, generated docs | Required | Pages/Wiki deployment retains its own checks | Already local |
| All non-live regressions, including security/concurrency/input contracts | Required, single pytest process | Explicit extended matrix only | Already local |
| Production stdio/HTTP, all-tool wire contract, provider HTTP workflow | Required | Ubuntu and Windows, Python 3.13 | Ubuntu, exact uploaded distributions |
| PowerShell hook process/UTF-8/privacy/recovery contracts | Runs when PowerShell is installed | 13 real wrapper cases on Windows | Required through mainline CI |
| Fresh installation and sdist/wheel parity | Required, one shared installation | Independent clean environments | Exact files promoted to PyPI/GitHub |
| Non-root container, health/readiness, MCP calls and persisted writes | Explicit when Docker is available | Manual extended checks | Required before upload |
| Actual provider availability/credentials | Explicit opt-in | Manual live integrations | Not a publication dependency |
| Trusted publishing and public Pages/Wiki deployment | Cannot prove locally | Actual hosted deployment | Actual registry publication |

`build/validation/<profile>.json` records the commit, dirty state, interpreter,
platform, child exit codes and elapsed times. `--report PATH` changes the location.
A failure replaces earlier successful evidence. A dry run only prints commands.
Reports are **not a success cache**, not an attestation, and never bypass checks;
Git hooks are local and can be bypassed. CI therefore retains independent runtime
acceptance. Release branches use PR checks rather than duplicate push + PR jobs;
master/main still check the merged revision. Full compatibility and Mermaid
rendering remain available through `run_extended_checks`.

## What the smoke tests actually prove

- `test_release_transport_smoke.py` starts production console/module entrypoints,
  validates all public tool schemas, performs real MCP calls, checks HTTP health
  and Host/Origin protection, rejects an invalid write with `/tags/0`, and repairs
  it with one retry. Saved pipelines survive a process restart; a different data
  root cannot see them, and deletion survives another restart. The installed
  browser broker fails closed before Chromium startup when its token is absent.
- `test_e2e_workflows.py` serves synthetic Europe PMC JSON/JATS and NCBI XML over
  a real loopback HTTP socket. Only endpoint addresses are redirected. Production
  HTTP handling, Biopython XML parsing, article normalization, search, fulltext
  prefetch/read reuse, Markdown/CSL export and session cache are exercised. One
  search, one XML download and one metadata fetch complete the workflow. Invalid
  provider JSON and HTTP 401 must remain failures, not successful empty results.
- `test_all_tools_mcp_acceptance.py` covers all public tools through stdio, HTTP
  and an installed wheel, including encoded containers and one-retry repair.
  Its injected provider doubles intentionally isolate **wire/tool contracts**;
  they do not claim to test provider parsing or live availability.
- `test_container_smoke.py` starts the image's default command, confirms the
  effective UID is nonzero, then runs the same HTTP/MCP/write contract. `--help`
  alone is not a service smoke test.

Local fixture traffic is real HTTP with synthetic data. It does not measure WAN
latency, provider uptime, research relevance, agent tokens or browser downloads.
The optional browser-backed institutional flow still needs Chromium and a valid
operator session. To probe actual providers explicitly:

```bash
PUBMED_RUN_LIVE_TESTS=1 uv run --frozen pytest -q -m integration -rs
```

## Keep tests that detect failures

Prefer a test that fails when a user-visible contract breaks: rejected input
must not perform work; cancelled downloads must not leak capacity; missing body
sections must not become abstracts; exported files must parse and preserve
identifiers; authorization must prevent cross-tenant access.

Before removing a test, identify stronger retained coverage and record the
reason. Avoid empty `pass` placeholders, permanent skips for retired APIs,
`x is None or x is not None`, import-only checks already exercised by startup,
and “E2E” tests that merely verify their own `AsyncMock.return_value`. Do not
remove exception, cancellation, malformed-input or security tests merely because
they are small or use mocks. Mocking the external boundary is useful; mocking the
behavior being claimed is not evidence that it works.

The [v0.7.7 removal ledger](../reports/test_renovation_removals_v077.json) records
64 reviewed removals and their retained coverage. This is a bounded cleanup,
not a claim that every remaining test has undergone semantic review.

## 維護重點

先跑 `pretest`，再 push。CI 保留本機無法完整代表的乾淨環境、Windows、容器與
實際發布邊界；不要把 CI 當成反覆試錯的地方。離線 smoke 使用合成資料，與外部
provider 即時測試分開。刪測試必須有理由及替代保護，不能以降低數量或提高 coverage
百分比為目標。測試報告不會自動豁免下一次檢查。

Build/install isolation follows the [uv packaging guide](https://docs.astral.sh/uv/guides/package/).
The event split uses [GitHub's workflow triggers](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#on).
