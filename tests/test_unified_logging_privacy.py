"""Unified-search operational logs must not retain query or secret text."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.presentation.mcp_server.tools import unified_runner
from pubmed_search.presentation.mcp_server.tools.search_run_journal import SearchRunJournal


@pytest.mark.asyncio
async def test_unexpected_planning_exception_logs_only_failure_type(caplog) -> None:  # type: ignore[no-untyped-def]
    private_query = "PRIVATE_QUERY_SENTINEL"
    secret = "TOPSECRET_SENTINEL"
    failure = RuntimeError(f"planning failed for q={private_query} token={secret}")
    journal = SearchRunJournal(manager=None)

    caplog.set_level(logging.DEBUG)
    with (
        patch.object(SearchRunJournal, "start", new=AsyncMock(return_value=journal)),
        patch.object(unified_runner, "build_unified_search_plan", new=AsyncMock(side_effect=failure)),
    ):
        response = await unified_runner.run_unified_search(
            searcher=MagicMock(),
            query="safe public query",
            output_format="json",
        )

    assert "RuntimeError" in caplog.text
    assert private_query not in caplog.text
    assert secret not in caplog.text
    assert private_query not in response
    assert secret not in response
