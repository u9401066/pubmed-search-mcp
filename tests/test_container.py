"""Tests for DI container and application lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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
        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp"})

        mock_searcher = MagicMock()
        container.searcher.override(mock_searcher)

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
    """Test MCPServer lifespan handler startup/shutdown."""

    async def test_lifespan_yields_container(self) -> None:
        """Lifespan handler yields the ApplicationContainer."""
        from pubmed_search.presentation.mcp_server.server import _make_lifespan
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import PipelineToolRuntime

        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp"})

        source_runtime = MagicMock()
        source_runtime.close_source_clients = AsyncMock()
        source_runtime.shared_http.close = AsyncMock()
        lifespan = _make_lifespan(container, PipelineToolRuntime(base_store=None), source_runtime)
        mock_server = MagicMock()

        async with lifespan(mock_server) as ctx:
            assert ctx is container
        source_runtime.close_source_clients.assert_awaited_once()
        source_runtime.shared_http.close.assert_awaited_once()

    async def test_lifespan_closes_http_client_on_shutdown(self) -> None:
        """Shutdown phase calls close_shared_async_client()."""
        from pubmed_search.presentation.mcp_server.server import _make_lifespan
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import PipelineToolRuntime

        container = ApplicationContainer()
        container.config.from_dict({"email": "test@example.com", "api_key": None, "data_dir": "/tmp"})

        source_runtime = MagicMock()
        source_runtime.close_source_clients = AsyncMock()
        source_runtime.shared_http.close = AsyncMock()
        lifespan = _make_lifespan(container, PipelineToolRuntime(base_store=None), source_runtime)
        mock_server = MagicMock()

        async with lifespan(mock_server):
            source_runtime.close_source_clients.assert_not_awaited()
            source_runtime.shared_http.close.assert_not_awaited()
        source_runtime.close_source_clients.assert_awaited_once()
        source_runtime.shared_http.close.assert_awaited_once()

    async def test_two_lifespans_manage_only_their_own_pipeline_scheduler(self) -> None:
        """A later server cannot replace another server's lifecycle dependency."""
        from pubmed_search.presentation.mcp_server.server import _make_lifespan
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import PipelineToolRuntime

        container_a = ApplicationContainer()
        container_b = ApplicationContainer()
        scheduler_a = MagicMock()
        scheduler_b = MagicMock()
        source_runtime_a = MagicMock()
        source_runtime_a.close_source_clients = AsyncMock()
        source_runtime_a.shared_http.close = AsyncMock()
        source_runtime_b = MagicMock()
        source_runtime_b.close_source_clients = AsyncMock()
        source_runtime_b.shared_http.close = AsyncMock()
        lifespan_a = _make_lifespan(
            container_a,
            PipelineToolRuntime(base_store=None, scheduler=scheduler_a),
            source_runtime_a,
        )
        lifespan_b = _make_lifespan(
            container_b,
            PipelineToolRuntime(base_store=None, scheduler=scheduler_b),
            source_runtime_b,
        )

        async with lifespan_a(MagicMock()):
            scheduler_a.start.assert_called_once_with()
            scheduler_b.start.assert_not_called()
            async with lifespan_b(MagicMock()):
                scheduler_b.start.assert_called_once_with()
                scheduler_a.shutdown.assert_not_called()
            scheduler_b.shutdown.assert_called_once_with()
            scheduler_a.shutdown.assert_not_called()

        scheduler_a.shutdown.assert_called_once_with()


# ============================================================================
# get_container() Tests
# ============================================================================


class TestGetContainer:
    """Test the server-owned container accessor."""

    def test_get_container_before_init_raises(self) -> None:
        from pubmed_search.presentation.mcp_server import server as srv_mod

        with pytest.raises(TypeError, match="container is unavailable"):
            srv_mod.get_container(MagicMock())

    def test_get_container_returns_container(self) -> None:
        from pubmed_search.presentation.mcp_server import server as srv_mod

        container = ApplicationContainer()
        container.config.from_dict({"email": "a@b.com", "api_key": None, "data_dir": "/tmp"})
        server = MagicMock()
        setattr(server, srv_mod._APPLICATION_CONTAINER_ATTR, container)
        assert srv_mod.get_container(server) is container
