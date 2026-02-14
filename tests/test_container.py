"""Tests for DI container and application lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.container import ApplicationContainer

# ============================================================================
# DI Container Tests
# ============================================================================


class TestApplicationContainer:
    """Test the DI container manages services correctly."""

    def test_container_creation(self) -> None:
        container = ApplicationContainer()
        container.config.from_dict(
            {
                "email": "test@example.com",
                "api_key": "test-key",
                "data_dir": "/tmp/test-pubmed",
            }
        )
        assert container.config.email() == "test@example.com"
        assert container.config.api_key() == "test-key"
        assert container.config.data_dir() == "/tmp/test-pubmed"

    def test_searcher_singleton(self) -> None:
        """Searcher provider returns the same instance (Singleton)."""
        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp"})

        s1 = container.searcher()
        s2 = container.searcher()
        assert s1 is s2

    def test_session_manager_singleton(self) -> None:
        """SessionManager provider returns the same instance."""
        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp/test-sm"})

        sm1 = container.session_manager()
        sm2 = container.session_manager()
        assert sm1 is sm2

    def test_strategy_generator_singleton(self) -> None:
        """StrategyGenerator provider returns the same instance."""
        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp"})

        sg1 = container.strategy_generator()
        sg2 = container.strategy_generator()
        assert sg1 is sg2

    def test_override_provider(self) -> None:
        """Container supports provider overriding for tests."""
        from dependency_injector import providers

        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp"})

        mock_searcher = MagicMock()
        container.searcher.override(providers.Object(mock_searcher))

        assert container.searcher() is mock_searcher

        # Reset override
        container.searcher.reset_override()
        real = container.searcher()
        assert real is not mock_searcher

    def test_container_reset(self) -> None:
        """Container reset clears all singletons."""
        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp"})

        s1 = container.searcher()
        container.searcher.reset()
        s2 = container.searcher()
        assert s1 is not s2


# ============================================================================
# Lifecycle Tests
# ============================================================================


class TestLifecycle:
    """Test FastMCP lifespan handler startup/shutdown."""

    async def test_lifespan_yields_container(self) -> None:
        """Lifespan handler yields the ApplicationContainer."""
        from pubmed_search.presentation.mcp_server.server import _make_lifespan

        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp"})

        lifespan = _make_lifespan(container)
        mock_server = MagicMock()

        with patch(
            "pubmed_search.shared.async_utils.close_shared_async_client",
            new_callable=AsyncMock,
        ) as mock_close:
            async with lifespan(mock_server) as ctx:
                assert ctx is container
            mock_close.assert_awaited_once()

    async def test_lifespan_closes_http_client_on_shutdown(self) -> None:
        """Shutdown phase calls close_shared_async_client()."""
        from pubmed_search.presentation.mcp_server.server import _make_lifespan

        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp"})

        lifespan = _make_lifespan(container)
        mock_server = MagicMock()

        with patch(
            "pubmed_search.shared.async_utils.close_shared_async_client",
            new_callable=AsyncMock,
        ) as mock_close:
            async with lifespan(mock_server):
                # Server is "running"
                mock_close.assert_not_awaited()
            # After exit: shutdown occurred
            mock_close.assert_awaited_once()


# ============================================================================
# get_container() Tests
# ============================================================================


class TestGetContainer:
    """Test the module-level container accessor."""

    def test_get_container_before_init_raises(self) -> None:
        from pubmed_search.presentation.mcp_server import server as srv_mod

        original = srv_mod._container
        try:
            srv_mod._container = None
            with pytest.raises(RuntimeError, match="Container not initialized"):
                srv_mod.get_container()
        finally:
            srv_mod._container = original

    def test_get_container_returns_container(self) -> None:
        from pubmed_search.presentation.mcp_server import server as srv_mod

        container = ApplicationContainer()
        container.config.from_dict({"email": "a@b.com", "api_key": None, "data_dir": "/tmp"})
        original = srv_mod._container
        try:
            srv_mod._container = container
            assert srv_mod.get_container() is container
        finally:
            srv_mod._container = original
