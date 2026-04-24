"""
Application DI container.

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
    container.searcher.override(mock_searcher)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")
_UNSET = object()


class _ConfigValueProvider:
    """Callable config value accessor used by singleton providers."""

    def __init__(self, config: _ConfigurationProvider, key: str) -> None:
        self._config = config
        self._key = key

    def __call__(self) -> Any:
        return self._config.get(self._key)


class _ConfigurationProvider:
    """Small configuration provider compatible with the app's DI needs."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def from_dict(self, values: dict[str, Any]) -> None:
        self._values.update(values)

    def get(self, key: str) -> Any:
        try:
            return self._values[key]
        except KeyError as exc:
            msg = f"Container configuration value {key!r} has not been set"
            raise RuntimeError(msg) from exc

    def __getattr__(self, key: str) -> _ConfigValueProvider:
        if key.startswith("_"):
            raise AttributeError(key)
        return _ConfigValueProvider(self, key)


class _ObjectProvider(Generic[T]):
    """Provider that returns a fixed object."""

    def __init__(self, value: T) -> None:
        self._value = value

    def __call__(self) -> T:
        return self._value


def _resolve(value: Any) -> Any:
    if isinstance(value, (_ConfigValueProvider, _ObjectProvider, _SingletonProvider)):
        return value()
    return value


class _SingletonProvider(Generic[T]):
    """Minimal singleton provider with override/reset support."""

    def __init__(self, factory: Callable[..., T], **dependencies: Any) -> None:
        self._factory = factory
        self._dependencies = dependencies
        self._instance: T | object = _UNSET
        self._override: Any = _UNSET

    def __call__(self) -> T:
        if self._override is not _UNSET:
            return cast("T", _resolve(self._override))

        if self._instance is _UNSET:
            kwargs = {key: _resolve(value) for key, value in self._dependencies.items()}
            self._instance = self._factory(**kwargs)

        return cast("T", self._instance)

    def override(self, value: T | Any) -> None:
        self._override = _ObjectProvider(value)

    def reset_override(self) -> None:
        self._override = _UNSET

    def reset(self) -> None:
        self._instance = _UNSET


def _create_searcher(email: str, api_key: str | None) -> object:
    """Lazy factory for LiteratureSearcher (avoids top-level import)."""
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

    return LiteratureSearcher(email=email, api_key=api_key or None)


def _create_strategy_generator(email: str, api_key: str | None) -> object:
    """Lazy factory for SearchStrategyGenerator."""
    from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

    return SearchStrategyGenerator(email=email, api_key=api_key or None)


def _create_article_cache(data_dir: str) -> object:
    """Lazy factory for the shared article cache."""
    from pubmed_search.application.session.manager import ArticleCache

    return ArticleCache(cache_dir=data_dir)


def _create_session_manager_with_cache(data_dir: str, article_cache: Any) -> object:
    """Lazy factory for SessionManager with an injected article cache."""
    from pubmed_search.application.session.manager import SessionManager

    return SessionManager(data_dir=data_dir, article_cache=article_cache)


class ApplicationContainer:
    """Central DI container for PubMed Search MCP application.

    Manages creation and lifecycle of all core services:
    - ``searcher``: NCBI Entrez literature search
    - ``strategy_generator``: MeSH / ESpell query intelligence
    - ``session_manager``: Session cache and persistence
    """

    def __init__(self) -> None:
        self.config: _ConfigurationProvider = _ConfigurationProvider()
        self.searcher: _SingletonProvider[object] = _SingletonProvider(
            _create_searcher,
            email=self.config.email,
            api_key=self.config.api_key,
        )
        self.strategy_generator: _SingletonProvider[object] = _SingletonProvider(
            _create_strategy_generator,
            email=self.config.email,
            api_key=self.config.api_key,
        )
        self.article_cache: _SingletonProvider[object] = _SingletonProvider(
            _create_article_cache,
            data_dir=self.config.data_dir,
        )
        self.session_manager: _SingletonProvider[object] = _SingletonProvider(
            _create_session_manager_with_cache,
            data_dir=self.config.data_dir,
            article_cache=self.article_cache,
        )


__all__ = ["ApplicationContainer"]
