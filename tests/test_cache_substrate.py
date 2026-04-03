from __future__ import annotations

from pubmed_search.shared.cache_substrate import CacheStore, JsonFileCacheBackend, MemoryCacheBackend


class TestCacheStore:
    async def test_warmup_invalidate_and_stats(self, tmp_path):
        store = CacheStore[str](
            MemoryCacheBackend(max_entries=10),
            default_ttl=60.0,
            name="test-cache",
        )

        warmed = store.warmup({"alpha": "A", "beta": "B"})

        assert warmed == 2
        assert store.stats.warmups == 2
        assert store.get("alpha") == "A"
        assert store.stats.hits == 1
        assert store.invalidate("alpha") is True
        assert store.stats.invalidations == 1

    async def test_cache_aside_fetches_only_once(self):
        store = CacheStore[str](MemoryCacheBackend(max_entries=10), default_ttl=60.0)
        calls = 0

        async def fetch_value():
            nonlocal calls
            calls += 1
            return "resolved"

        first = await store.get_or_fetch("entity:propofol", fetch_value)
        second = await store.get_or_fetch("entity:propofol", fetch_value)

        assert first == "resolved"
        assert second == "resolved"
        assert calls == 1

    async def test_json_backend_persists_entries(self, tmp_path):
        file_path = tmp_path / "cache.json"
        store = CacheStore[str](JsonFileCacheBackend(file_path), default_ttl=60.0)
        store.set("paper:123", "cached")

        reloaded = CacheStore[str](JsonFileCacheBackend(file_path), default_ttl=60.0)

        assert reloaded.get("paper:123") == "cached"
