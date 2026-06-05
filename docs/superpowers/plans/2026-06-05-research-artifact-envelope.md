# Research Artifact Envelope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build complete, auditable MCP research artifacts while keeping MCP responses compact and useful.

**Architecture:** Add an application-layer artifact envelope/audit builder and wire it into `unified_search` artifact persistence. Session tools continue to provide the retrieval facade, with richer locators and pagination hints for local, remote, and sandboxed clients.

**Tech Stack:** Python 3.10+, uv, pytest, ruff, mypy, existing DDD application/presentation boundaries.

---

### Task 1: Artifact Envelope Tests

**Files:**
- Create: `tests/test_research_artifact_envelope.py`
- Modify: none

- [ ] Write tests for query strategy serialization, audit warnings, and summary read hints.
- [ ] Run `uv run pytest tests/test_research_artifact_envelope.py -q` and confirm the tests fail before implementation.

### Task 2: Application Artifact Envelope

**Files:**
- Create: `src/pubmed_search/application/session/artifact_envelope.py`
- Modify: `src/pubmed_search/application/session/__init__.py`
- Test: `tests/test_research_artifact_envelope.py`

- [ ] Implement `build_unified_search_artifact_files`.
- [ ] Implement `audit_unified_search_artifact`.
- [ ] Return files, summary, and metadata suitable for `SessionManager.save_artifact`.
- [ ] Run `uv run pytest tests/test_research_artifact_envelope.py -q` and confirm the envelope tests pass.

### Task 3: Unified Search Wiring

**Files:**
- Modify: `src/pubmed_search/presentation/mcp_server/tools/unified.py`
- Modify: `tests/test_unified_tools.py`

- [ ] Replace ad hoc artifact files with the application envelope builder.
- [ ] Preserve compact structured response behavior.
- [ ] Add coverage that the artifact locator includes audit status, files, and read hints.
- [ ] Run focused unified tests.

### Task 4: Session Retrieval Surface

**Files:**
- Modify: `src/pubmed_search/presentation/mcp_server/tools/artifact_memory.py`
- Modify: `src/pubmed_search/presentation/mcp_server/session_tools.py`
- Modify: `tests/test_session_artifacts.py`
- Modify: `tests/test_session_tools.py`

- [ ] Add locator fields for schema version, available files, read order, and audit status.
- [ ] Add response fields showing retrieval hints for paged artifact reads.
- [ ] Keep local paths redacted by default.
- [ ] Run focused session artifact tests.

### Task 5: Verification

**Files:**
- No production files.

- [ ] Run `uv run ruff check src tests docs`.
- [ ] Run `uv run ruff format --check src tests`.
- [ ] Run `uv run mypy src/ tests/`.
- [ ] Run focused tests for artifact, unified, and session tooling.
- [ ] Run the repo baseline if focused checks are clean.
