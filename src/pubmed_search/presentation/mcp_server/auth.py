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


def _resource_origin(resource_url: AnyHttpUrl) -> str:
    """Return the network origin advertised by a public resource URL."""
    host = str(resource_url.host or "")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 443 if resource_url.scheme == "https" else 80
    port = resource_url.port
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{resource_url.scheme}://{host}{port_suffix}"


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

    resource_server_url_raw = settings.auth_resource_server_url.strip()
    resource_server_url = AnyHttpUrl(resource_server_url_raw) if resource_server_url_raw else None
    issuer = settings.auth_issuer_url.strip()
    if not issuer:
        issuer = _resource_origin(resource_server_url) if resource_server_url is not None else DEFAULT_ISSUER_URL
    return (
        StaticTokenVerifier(principals),
        AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=resource_server_url,
            required_scopes=[DEFAULT_SCOPE],
        ),
    )


__all__ = ["DEFAULT_ISSUER_URL", "build_auth"]
