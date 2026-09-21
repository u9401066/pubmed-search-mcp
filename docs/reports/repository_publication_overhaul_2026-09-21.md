# Repository organization and publication overhaul — 2026-09-21

Scope: classify the whole repository and replace the old citation/manuscript
workflow. Baseline: `d7a4060f6009a1f08a28c30795a5b1680cdadef9` (after v0.7.4).
Git delivery follows the user's September 21 instruction to commit in segments
and push `docs/repository-publication-overhaul`.

The software release remains 0.7.4. No benchmark long run, API load test, arXiv
submission, new package release or cloud publication was performed in this task.

## File organization

- Initial inventory: **787 tracked files**, including 27 root entry/config files,
  226 source files, 208 test files, 147 docs files and 58 script files.
- Relocated **36 canonical documents** according to
  [document-migrations.json](../document-migrations.json). Current guides,
  development notes, architecture contracts, provider references, research,
  design records and historical proposals have separate locations.
- Preserved **four old publication originals byte-for-byte**, checked against
  baseline Git objects and [checksums](../archive/publication/originals.json).
  The old paper entry now points to the canonical publication workspace.
- Root configuration and established script/runtime command paths remain stable.
  Website hash routes and Wiki names remain stable; raw repository document
  links in the move map change. External links to those raw paths need migration.
- Every current Git-visible file is classified by
  [repository-layout.json](../repository-layout.json). Unowned or multiply owned
  new files fail the local full gate. Ignored local output is excluded.
  Final inventory: **805 / 805 files classified**, zero unowned or ambiguous paths.
- This is file-placement coverage, **not a new semantic review of all code**.
  No core Python file changed: 224 files, 458 classes, 2,456 functions/methods/nested
  functions, 2,914 definitions. The existing core review requirement still passes.
  Newly changed maintenance scripts/tests are not mislabeled as core-reviewed.

The documentation link regression now includes every Markdown file in all seven
maintained document categories, in addition to existing entrypoints. A wider
manual scan also checked client instructions, script maps and reports; the only
non-file target found was an existing figure-skill `output_path` template example.
Historical original drafts are intentionally not rewritten to fix old links.

## Manuscript and citations

The [publication workspace](../publication/README.md) has one current English
TeX manuscript, 12 reviewed references, a claim/evidence map and a proposed
controlled evaluation. Author and institution follow the user's confirmation:
Tz-Ping Gau / Kaohsiung Medical University Hospital. `CITATION.cff` remains a
software citation; the old contact address is retained and no arXiv ID is invented.

The paper attributes BM25, RRF and MMR to prior work, corrects ASReview metadata,
and removes unsupported novelty, research-maturity and clinical-evidence claims.
Existing component results, offline latency, three-pair pilot and release tests
have separate interpretations. In particular, the pilot shows no score difference
and does not establish a package-level gain.

The local builder validates five pinned JSON inputs and citation keys, generates
tables, and packages an explicit six-file TeX source allowlist. Compilation outputs
stay in ignored `build/publication/`; copies of PDFs and scratch files are not
added to the current source workspace. Publication preflight is local and offline;
there is no new GitHub Actions job or provider call in that check.

## Verification record

- Four historical originals match their baseline Git bytes exactly.
- Narrow documentation, publication and Wiki checks: **40 passed** after path and
  asset-cache correction.
- Initial full gate: 4,763 passed and one website cache-key assertion failed;
  the date/version asset marker was corrected without changing the software version.
- Core ledger verification: `symbol_inventory.py --require-reviewed src/` passed.
- Tectonic 0.17.0 built an **8-page PDF**, with no unresolved citations/references
  or overfull lines in the final build. Title page and result tables were visually
  inspected. A remaining underfull bibliography-line warning affects spacing only.
- `arxiv-source.zip` contains only `main.tex`, `references.bib`, `evidence.tex`,
  two generated tables and `main.bbl`. It compiled successfully from a fresh
  temporary directory using only the cached TeX bundle, without repository files.
- Final `check_repo.py full`: **4,764 passed, 23 skipped, 30 deselected** in
  118.09 seconds on local Python 3.10.12. Ruff, formatting, async checks, file
  ownership, publication preflight, Python inventory and mypy all passed.
  This run includes actual MCP transport and fresh-wheel acceptance; it does not
  add a new cross-platform matrix or rerun historical performance measurements.
- Additional checks: vulture, Bandit medium/high on the new scripts, DDD layer
  checks, Cline/Codex skill validation and `git diff --check` passed.

## Browser verification

Browser plugin not available; used existing Playwright 1.63.0 and local Chromium,
without adding browser dependencies to the project. Served `docs/` locally at
`http://127.0.0.1:8874`, with desktop 1440×1000 and mobile 390×844 viewports.

Flow: documentation map → publication link → manuscript/evidence workspace;
mobile menu → Chinese → filter “publication” → select publication. This found an
existing same-route issue: no `hashchange` event meant the menu stayed open.
Delegating navigation clicks now closes it even after filtering and when the
selected page is already active. Page identity, content, console errors, overflow
and the repeated interaction were checked. Screenshots/logs are local `/tmp/`
review artifacts, not publication source files. Other browsers and remote hosting
were not tested in this task.

| Check | Result |
| --- | --- |
| Page identity / nonblank content | Pass; expected publication route/title, 4,135 characters of document content |
| Runtime errors / framework overlay | Pass; no page or console errors, visible documentation content |
| Desktop and mobile screenshots | Reviewed; no whole-page horizontal overflow at 390 px |
| Same-route mobile interaction after fix | Pass; menu closes, backdrop clears, publication content remains visible |
| Chinese language/filter navigation | Pass; publication remains discoverable in both language modes |

## Repeat locally

```bash
uv run --frozen python scripts/check_repository_layout.py --output build/repository-layout.json
uv run --frozen python scripts/build_publication.py --prepare-only --output build/publication-preflight
uv run --frozen python scripts/build_publication.py --tectonic /path/to/tectonic
uv run --frozen python scripts/check_repo.py full
uv run --frozen python scripts/perf/symbol_inventory.py --require-reviewed src/
```

Before actual submission, the author still reviews the manuscript, declarations,
license/contact details and arXiv-generated PDF. Local build success is not
submission or acceptance. A full controlled agent benchmark remains future work.
