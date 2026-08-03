"""Static bearer-token verification for self-hosted deployments.

The MCP SDK expects a ``TokenVerifier``. Full OAuth is overkill for a team that
just wants a few trusted agents to reach a private server, so this verifier maps
pre-shared tokens to principals through configuration.

Tokens are compared with :func:`hmac.compare_digest` and are only ever kept as
digests, so a memory dump or an accidental log of this object cannot leak them.

For anything beyond a handful of agents, plug a real OAuth resource-server
verifier into ``MCPServer(token_verifier=...)`` instead - this class is
intentionally the simple option, not the general one.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)

#: Scope granted to every statically configured token.
DEFAULT_SCOPE = "pubmed:search"


def _digest(token: str) -> str:
    """Return a stable digest used for constant-time token comparison."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StaticTokenPrincipal:
    """A configured caller.

    Attributes:
        principal: Stable identity used to derive the tenant.
        token_digest: SHA-256 digest of the shared secret.
        scopes: Scopes granted to this caller.
    """

    principal: str
    token_digest: str
    scopes: tuple[str, ...] = (DEFAULT_SCOPE,)


class StaticTokenVerifier:
    """Verify pre-shared bearer tokens against a configured principal map."""

    def __init__(self, principals: list[StaticTokenPrincipal]) -> None:
        """Create the verifier.

        Args:
            principals: Configured callers. An empty list rejects every token.
        """
        self._principals = list(principals)

    def __len__(self) -> int:
        """Return how many principals are configured."""
        return len(self._principals)

    @property
    def principal_names(self) -> list[str]:
        """Return the configured principal names (never the secrets)."""
        return [entry.principal for entry in self._principals]

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access token for a valid bearer token, else ``None``.

        Args:
            token: The raw bearer token presented by the client.

        Returns:
            An :class:`AccessToken` whose ``subject`` is the configured
            principal, or ``None`` when no principal matches.
        """
        if not token:
            return None

        presented = _digest(token)
        for entry in self._principals:
            if hmac.compare_digest(presented, entry.token_digest):
                return AccessToken(
                    token=token,
                    client_id=entry.principal,
                    subject=entry.principal,
                    scopes=list(entry.scopes),
                    expires_at=None,
                )

        logger.warning("Rejected bearer token: no matching principal")
        return None


def parse_static_tokens(raw: str) -> list[StaticTokenPrincipal]:
    """Parse the ``principal:token`` configuration string.

    Args:
        raw: Comma-separated ``principal:token`` pairs, e.g.
            ``"team-a:s3cret,team-b:0ther"``. Whitespace is ignored and
            malformed entries are skipped with a warning.

    Returns:
        The parsed principals, deduplicated by principal name.
    """
    principals: dict[str, StaticTokenPrincipal] = {}
    for chunk in raw.split(","):
        entry = chunk.strip()
        if not entry:
            continue
        principal, separator, token = entry.partition(":")
        principal, token = principal.strip(), token.strip()
        if not separator or not principal or not token:
            logger.warning("Ignoring malformed auth token entry (expected 'principal:token')")
            continue
        principals[principal] = StaticTokenPrincipal(principal=principal, token_digest=_digest(token))
    return list(principals.values())


__all__ = [
    "DEFAULT_SCOPE",
    "StaticTokenPrincipal",
    "StaticTokenVerifier",
    "parse_static_tokens",
]
