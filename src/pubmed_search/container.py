"""
Application DI Container (dependency-injector).

Centralizes service creation and lifecycle management.
Replaces scattered manual instantiation and ``mcp._xxx`` private attribute access.

Usage::

    from pubmed_search.container import ApplicationContainer

    container = ApplicationContainer()
    container.config.from_dict({
        "email": "user@example.com",
        "api_key": None,
        "data_dir": "~/.pubmed-search-mcp",
    })

    searcher = container.searcher()
    session_manager = container.session_manager()

    # In tests — override any provider:
    container.searcher.override(providers.Object(mock_searcher))
"""

from __future__ import annotations

import logging

from dependency_injector import containers, providers

logger = logging.getLogger(__name__)


def _create_searcher(email: str, api_key: str | None) -> object:
    """Lazy factory for LiteratureSearcher (avoids top-level import)."""
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

    return LiteratureSearcher(email=email, api_key=api_key or None)


def _create_strategy_generator(email: str, api_key: str | None) -> object:
    """Lazy factory for SearchStrategyGenerator."""
    from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

    return SearchStrategyGenerator(email=email, api_key=api_key or None)


def _create_session_manager(data_dir: str) -> object:
    """Lazy factory for SessionManager."""
    from pubmed_search.application.session.manager import SessionManager

    return SessionManager(data_dir=data_dir)


class ApplicationContainer(containers.DeclarativeContainer):
    """Central DI container for PubMed Search MCP application.

    Manages creation and lifecycle of all core services:
    - ``searcher``: NCBI Entrez literature search
    - ``strategy_generator``: MeSH / ESpell query intelligence
    - ``session_manager``: Session cache and persistence
    """

    config = providers.Configuration()

    searcher = providers.Singleton(
        _create_searcher,
        email=config.email,
        api_key=config.api_key,
    )

    strategy_generator = providers.Singleton(
        _create_strategy_generator,
        email=config.email,
        api_key=config.api_key,
    )

    session_manager = providers.Singleton(
        _create_session_manager,
        data_dir=config.data_dir,
    )


__all__ = ["ApplicationContainer"]
