"""Auth wiring for the MCP server.

Translates the deployment settings into the ``token_verifier`` / ``auth`` pair
that :class:`~mcp.server.mcpserver.MCPServer` expects. Keeping it here means
``create_server()`` stays a thin assembly step and the credential parsing has
one testable home.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from pubmed_search.infrastructure.auth import DEFAULT_SCOPE, StaticTokenVerifier, parse_static_tokens

if TYPE_CHECKING:
    from pubmed_search.shared.settings import AppSettings

logger = logging.getLogger(__name__)

#: Issuer advertised when a deployment enables auth without naming one.
DEFAULT_ISSUER_URL = "https://pubmed-search-mcp.local"


def build_auth(settings: AppSettings) -> tuple[StaticTokenVerifier | None, AuthSettings | None]:
    """Build the verifier and auth settings for the configured tokens.

    Args:
        settings: Runtime settings carrying ``auth_tokens_raw`` and
            ``auth_issuer_url``.

    Returns:
        ``(verifier, auth_settings)``, or ``(None, None)`` when no tokens are
        configured so local stdio installs keep working with no setup.
    """
    principals = parse_static_tokens(settings.auth_tokens_raw)
    if not principals:
        return None, None

    issuer = settings.auth_issuer_url.strip() or DEFAULT_ISSUER_URL
    return (
        StaticTokenVerifier(principals),
        AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=None,
            required_scopes=[DEFAULT_SCOPE],
        ),
    )


__all__ = ["DEFAULT_ISSUER_URL", "build_auth"]
