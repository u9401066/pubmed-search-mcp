"""
Tests for Session management and Article caching.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pubmed_search.application.session import (
    ArticleCache,
    CachedArticle,
    ResearchSession,
    SearchRecord,
    SessionManager,
)


class TestCachedArticle:
    """Tests for CachedArticle dataclass."""

    async def test_create_cached_article(self):
        """Test creating a CachedArticle."""
        article = CachedArticle(
            pmid="12345678",
            title="Test Article",
            authors=["Smith J"],
            abstract="Test abstract",
            journal="Test Journal",
            year="2024",
        )

        assert article.pmid == "12345678"
        assert article.title == "Test Article"
        assert article.cached_at is not None

    async def test_cached_article_not_expired(self):
        """Test that fresh cache entry is not expired."""
        article = CachedArticle(pmid="123", title="Test", authors=[], abstract="", journal="", year="")
        assert not article.is_expired(max_age_days=7)

    async def test_cached_article_expired(self):
        """Test that old cache entry is expired."""
        old_time = (datetime.now() - timedelta(days=10)).isoformat()
        article = CachedArticle(
            pmid="123",
            title="Test",
            authors=[],
            abstract="",
            journal="",
            year="",
            cached_at=old_time,
        )
        assert article.is_expired(max_age_days=7)


class TestSearchRecord:
    """Tests for SearchRecord dataclass."""

    async def test_create_search_record(self):
        """Test creating a SearchRecord."""
        record = SearchRecord(
            query="diabetes treatment",
            timestamp=datetime.now().isoformat(),
            result_count=100,
            pmids=["123", "456", "789"],
        )

        assert record.query == "diabetes treatment"
        assert record.result_count == 100
        assert len(record.pmids) == 3

    async def test_search_record_with_filters(self):
        """Test SearchRecord with filters."""
        record = SearchRecord(
            query="cancer",
            timestamp=datetime.now().isoformat(),
            result_count=50,
            pmids=[],
            filters={"date_from": "2020", "publication_type": "Review"},
        )

        assert record.filters["date_from"] == "2020"
        assert record.filters["publication_type"] == "Review"


class TestResearchSession:
    """Tests for ResearchSession dataclass."""

    async def test_create_session(self):
        """Test creating a ResearchSession."""
        session = ResearchSession(session_id="test-001", topic="diabetes research")

        assert session.session_id == "test-001"
        assert session.topic == "diabetes research"
        assert session.article_cache == {}
        assert session.search_history == []

    async def test_session_touch(self):
        """Test updating session timestamp."""
        session = ResearchSession(session_id="test-001")
        old_time = session.updated_at

        # Small delay to ensure timestamp changes
        import time

        time.sleep(0.01)
        session.touch()

        assert session.updated_at != old_time


class TestArticleCache:
    """Tests for ArticleCache class."""

    async def test_memory_only_cache(self):
        """Test cache without persistence."""
        cache = ArticleCache(cache_dir=None)

        # Add article using put()
        cache.put(
            "12345",
            {
                "pmid": "12345",
                "title": "Test",
                "authors": ["Author"],
                "abstract": "Abstract",
                "journal": "Journal",
                "year": "2024",
            },
        )

        # Retrieve
        retrieved = cache.get("12345")
        assert retrieved is not None
        assert retrieved.title == "Test"

    async def test_cache_with_persistence(self, temp_dir):
        """Test cache with file persistence."""
        cache = ArticleCache(cache_dir=str(temp_dir))

        cache.put(
            "99999",
            {
                "pmid": "99999",
                "title": "Persistent Article",
                "authors": [],
                "abstract": "",
                "journal": "",
                "year": "",
            },
        )

        # Check file was created
        cache_file = temp_dir / "article_cache.json"
        assert cache_file.exists()

        # Load in new cache instance
        cache2 = ArticleCache(cache_dir=str(temp_dir))
        retrieved = cache2.get("99999")
        assert retrieved is not None
        assert retrieved.title == "Persistent Article"

    async def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = ArticleCache()
        assert cache.get("nonexistent") is None

    async def test_cache_has(self):
        """Test get() returns None for missing, value for existing."""
        cache = ArticleCache()

        # Should return None for nonexistent
        assert cache.get("12345") is None

        cache.put(
            "12345",
            {
                "pmid": "12345",
                "title": "Test",
                "authors": [],
                "abstract": "",
                "journal": "",
                "year": "",
            },
        )

        # Should return the cached article
        assert cache.get("12345") is not None


class TestSessionManager:
    """Tests for SessionManager class."""

    async def test_create_session_manager(self, temp_dir):
        """Test creating SessionManager."""
        manager = SessionManager(data_dir=str(temp_dir))
        assert manager is not None

    async def test_get_or_create_session(self, temp_dir):
        """Test getting or creating a session."""
        manager = SessionManager(data_dir=str(temp_dir))

        session = manager.get_or_create_session("test-topic")
        assert session is not None
        assert session.topic == "test-topic"

    async def test_session_persistence(self, temp_dir):
        """Test session is persisted."""
        manager1 = SessionManager(data_dir=str(temp_dir))
        manager1.get_or_create_session("persistent-topic")

        # SessionManager auto-saves, no explicit save needed

        # Load in new manager
        manager2 = SessionManager(data_dir=str(temp_dir))

        # Should have the session (either as current or in sessions list)
        session2 = manager2.get_current_session()
        assert session2 is not None or len(manager2._sessions) > 0

    async def test_add_to_cache(self, temp_dir, mock_article_data):
        """Test adding articles to cache."""
        manager = SessionManager(data_dir=str(temp_dir))
        manager.get_or_create_session("test")

        manager.add_to_cache([mock_article_data])

        # Check cache
        cached = manager.get_from_cache(mock_article_data["pmid"])
        assert cached is not None

    async def test_add_search_record(self, temp_dir):
        """Test adding search record."""
        manager = SessionManager(data_dir=str(temp_dir))
        manager.get_or_create_session("test")

        manager.add_search_record("diabetes", ["123", "456"])

        session = manager.get_current_session()
        assert len(session.search_history) == 1
        assert session.search_history[0]["query"] == "diabetes"

    async def test_find_cached_search(self, temp_dir, mock_article_data):
        """Test finding cached search results."""
        manager = SessionManager(data_dir=str(temp_dir))
        manager.get_or_create_session("test")

        # Add articles and record search
        manager.add_to_cache([mock_article_data])
        manager.add_search_record("diabetes treatment", [mock_article_data["pmid"]])

        # Should find cached results
        cached = manager.find_cached_search("diabetes treatment")
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["pmid"] == mock_article_data["pmid"]

        # Case insensitive
        cached2 = manager.find_cached_search("DIABETES TREATMENT")
        assert cached2 is not None

        # Different query should return None
        not_cached = manager.find_cached_search("cancer therapy")
        assert not_cached is None

    async def test_find_cached_search_with_limit(self, temp_dir):
        """Test cache lookup respects limit parameter."""
        manager = SessionManager(data_dir=str(temp_dir))
        manager.get_or_create_session("test")

        # Add 3 articles
        articles = [
            {
                "pmid": "111",
                "title": "Article 1",
                "authors": [],
                "abstract": "",
                "journal": "",
                "year": "2024",
            },
            {
                "pmid": "222",
                "title": "Article 2",
                "authors": [],
                "abstract": "",
                "journal": "",
                "year": "2024",
            },
            {
                "pmid": "333",
                "title": "Article 3",
                "authors": [],
                "abstract": "",
                "journal": "",
                "year": "2024",
            },
        ]
        manager.add_to_cache(articles)
        manager.add_search_record("test query", ["111", "222", "333"])

        # Request more than cached - should return None
        cached = manager.find_cached_search("test query", limit=5)
        assert cached is None

        # Request exactly what's cached - should work
        cached = manager.find_cached_search("test query", limit=3)
        assert cached is not None
        assert len(cached) == 3

        # Request less than cached - should return limited
        cached = manager.find_cached_search("test query", limit=2)
        assert cached is not None
        assert len(cached) == 2
