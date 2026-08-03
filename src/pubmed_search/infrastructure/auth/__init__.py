"""Authentication adapters for remote MCP deployments."""

from __future__ import annotations

from .static_tokens import (
    DEFAULT_SCOPE,
    StaticTokenPrincipal,
    StaticTokenVerifier,
    parse_static_tokens,
)

__all__ = [
    "DEFAULT_SCOPE",
    "StaticTokenPrincipal",
    "StaticTokenVerifier",
    "parse_static_tokens",
]
