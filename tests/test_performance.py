"""Performance smoke tests for canonical application services."""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.slow


class TestCachePerformance:
    """Guard the session cache's local hot path."""

    async def test_cache_hit_performance(self) -> None:
        from pubmed_search.application.session import SessionManager

        manager = SessionManager()
        manager.create_session(topic="diabetes")
        manager.add_to_cache([{"pmid": "12345678", "title": "Cached Article"}])

        found, missing = manager.get_from_cache(["12345678"])

        assert missing == []
        assert found[0]["pmid"] == "12345678"

    async def test_repeated_cache_read_remains_bounded(self) -> None:
        from pubmed_search.application.session import SessionManager

        manager = SessionManager()
        manager.create_session(topic="cache-smoke")
        manager.add_to_cache([{"pmid": "11111111", "title": "Article"}])

        started = time.perf_counter()
        for _ in range(1_000):
            found, missing = manager.get_from_cache(["11111111"])
            assert found and not missing

        assert time.perf_counter() - started < 1.0


class TestSessionScalability:
    """Guard bounded in-memory session creation overhead."""

    async def test_create_one_hundred_sessions(self) -> None:
        from pubmed_search.application.session import SessionManager

        manager = SessionManager()
        started = time.perf_counter()
        for index in range(100):
            manager.create_session(topic=f"topic-{index}")

        assert time.perf_counter() - started < 1.0
        assert len(manager.list_sessions()) >= 100
