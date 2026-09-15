from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from pubmed_search.shared.cache_substrate import CacheStore, JsonFileCacheBackend, MemoryCacheBackend, StoredCacheEntry


class TestCacheStore:
    def test_persistence_does_not_overwrite_a_shared_fixed_temp_filename(self, tmp_path):
        path = tmp_path / "cache.json"
        other_writer = tmp_path / "cache.json.tmp"
        other_writer.write_text("another writer's pending data", encoding="utf-8")
        store = CacheStore[str](JsonFileCacheBackend(path))
        store.set("paper", "content")
        assert other_writer.read_text(encoding="utf-8") == "another writer's pending data"
        assert CacheStore[str](JsonFileCacheBackend(path)).get("paper") == "content"

    @pytest.mark.parametrize("field,value", [("expires_at", "not-a-date"), ("expires_at", ""), ("cached_at", "bad")])
    def test_corrupt_timestamps_do_not_poison_other_cached_articles(self, tmp_path, field, value):
        good = StoredCacheEntry(value="good").to_dict()
        broken = {**good, field: value}
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"broken": broken, "good": good}), encoding="utf-8")
        store = CacheStore[str](JsonFileCacheBackend(path))
        assert store.get("broken") is None
        assert store.keys() == ["good"]
        assert store.get("good") == "good"

    def test_reloaded_json_cache_applies_its_capacity(self, tmp_path):
        path = tmp_path / "cache.json"
        original = CacheStore[str](JsonFileCacheBackend(path))
        original.warmup({"old": "1", "middle": "2", "new": "3"})
        reloaded = CacheStore[str](JsonFileCacheBackend(path, max_entries=2))
        assert reloaded.keys() == ["middle", "new"]
        assert reloaded.get("old") is None

    @pytest.mark.parametrize("backend_type", [MemoryCacheBackend, JsonFileCacheBackend])
    def test_negative_cache_capacity_is_rejected_before_mutation(self, tmp_path, backend_type):
        args = (tmp_path / "cache.json",) if backend_type is JsonFileCacheBackend else ()
        with pytest.raises(ValueError, match="max_entries"):
            backend_type(*args, max_entries=-1)

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

    async def test_cache_fetch_failure_does_not_log_key_or_exception_detail(self, caplog):
        store = CacheStore[str](MemoryCacheBackend(max_entries=10), default_ttl=60.0)
        secret = "PRIVATE_CACHE_KEY_AND_EXCEPTION_DETAIL"

        async def fail_fetch():
            raise RuntimeError(secret)

        assert await store.get_or_fetch(secret, fail_fetch) is None
        assert secret not in caplog.text
        assert "RuntimeError" in caplog.text

    async def test_json_backend_persists_entries(self, tmp_path):
        file_path = tmp_path / "cache.json"
        store = CacheStore[str](JsonFileCacheBackend(file_path), default_ttl=60.0)
        store.set("paper:123", "cached")

        reloaded = CacheStore[str](JsonFileCacheBackend(file_path), default_ttl=60.0)

        assert reloaded.get("paper:123") == "cached"

    @pytest.mark.parametrize(
        "payload",
        [
            "raw-value",
            {"value": "missing-envelope-fields"},
            {"value": "x", "cached_at": 123, "expires_at": None, "metadata": {}},
            {"value": "x", "cached_at": "2026-01-01T00:00:00Z", "expires_at": None, "metadata": []},
        ],
    )
    def test_cache_entry_rejects_noncanonical_persisted_shapes(self, payload):
        with pytest.raises((TypeError, ValueError), match="Invalid cache entry payload"):
            StoredCacheEntry.from_dict(payload)

    def test_json_backend_skips_invalid_entries_without_migrating_them(self, tmp_path):
        file_path = tmp_path / "cache.json"
        file_path.write_text(
            json.dumps(
                {
                    "retired": {"raw": "payload"},
                    "current": StoredCacheEntry(value="ok").to_dict(),
                }
            ),
            encoding="utf-8",
        )

        backend = JsonFileCacheBackend(file_path)

        assert backend.keys() == ["current"]

    def test_json_backend_concurrent_mutations_keep_file_valid(self, tmp_path):
        file_path = tmp_path / "cache.json"
        backend = JsonFileCacheBackend(file_path)

        def _mutate(index: int) -> None:
            key = f"paper:{index:03d}"
            backend.set_entry(key, StoredCacheEntry(value={"index": index}))
            if index % 4 == 0:
                backend.delete(key)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(_mutate, range(80)))

        payload = json.loads(file_path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert not file_path.with_name("cache.json.tmp").exists()

        reloaded = JsonFileCacheBackend(file_path)
        keys = reloaded.keys()
        assert all(key.startswith("paper:") for key in keys)

    def test_memory_backend_operations_are_safe_under_thread_contention(self):
        backend = MemoryCacheBackend(max_entries=32)

        def _mutate(worker: int) -> None:
            for step in range(160):
                key = f"worker:{worker}:slot:{step % 40}"
                backend.set_entry(key, StoredCacheEntry(value={"worker": worker, "step": step}))
                backend.get_entry(key)
                if step % 5 == 0:
                    backend.delete(f"worker:{worker}:slot:{(step - 1) % 40}")
                if step % 11 == 0:
                    backend.set_entries(
                        [
                            (f"batch:{worker}:{step}:a", StoredCacheEntry(value="a")),
                            (f"batch:{worker}:{step}:b", StoredCacheEntry(value="b")),
                        ]
                    )
                if step % 17 == 0:
                    backend.keys()
                    backend.items()
                if step % 79 == 0:
                    backend.clear()

        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(_mutate, range(12)))

        keys = backend.keys()
        items = backend.items()
        assert len(keys) <= 32
        assert len(keys) == len(set(keys))
        assert {key for key, _entry in items} == set(keys)

        removed = backend.clear()
        assert removed == len(keys)
        assert backend.keys() == []
