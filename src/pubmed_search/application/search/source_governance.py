"""Application policy for providers with restricted data-use contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderAccessTier(str, Enum):
    """Contract tier required before a provider may be called."""

    OPEN = "open"
    LICENSED_ENTITLEMENT = "licensed_entitlement"


class ProviderRetentionMode(str, Enum):
    """Maximum retention allowed for provider-derived data."""

    STANDARD = "standard"
    EPHEMERAL_METADATA = "ephemeral_metadata"


class SourceDataOperation(str, Enum):
    """Operations that a provider governance policy may permit."""

    DIRECT_REQUEST = "direct_request"
    AUTO_DISPATCH = "auto_dispatch"
    CACHE = "cache"
    PERSIST = "persist"
    SESSION = "session"
    ARTIFACT = "artifact"
    EXPORT = "export"
    PIPELINE = "pipeline"
    SCHEDULE = "schedule"
    EMBED = "embed"
    TRAIN = "train"
    REGISTER_SEARCH_SOURCE = "register_search_source"
    REGISTER_MCP_TOOL = "register_mcp_tool"


class SourceGovernanceError(PermissionError):
    """Raised before an operation that violates a provider data contract."""


@dataclass(frozen=True, slots=True)
class SourceDataGovernancePolicy:
    """Machine-checkable application boundary for one external provider."""

    provider_key: str
    access_tier: ProviderAccessTier
    retention_mode: ProviderRetentionMode
    allowed_operations: frozenset[SourceDataOperation]
    allowed_output_fields: frozenset[str]
    persistable_fields: frozenset[str] = frozenset()
    raw_payload_retention_allowed: bool = True
    requires_contract_acknowledgement: bool = False
    requires_entitlement_confirmation: bool = False
    requires_end_user_context: bool = False
    sensitive_input_allowed: bool = True
    data_plane_only: bool = False

    def allows(self, operation: SourceDataOperation) -> bool:
        """Return whether the provider contract permits an operation."""
        return operation in self.allowed_operations

    def require(self, operation: SourceDataOperation) -> None:
        """Fail closed when an application path requests a forbidden operation."""
        if not self.allows(operation):
            raise SourceGovernanceError(f"{self.provider_key} governance policy forbids {operation.value}")


CLINICALKEY_AI_CITATION_FIELDS = frozenset(
    {
        "reference_id",
        "document_title",
        "container_title",
        "authors",
        "doi",
        "pmid",
        "identifier",
        "identifier_type",
        "publication_date",
        "href",
    }
)


CLINICALKEY_AI_DATA_POLICY = SourceDataGovernancePolicy(
    provider_key="clinicalkey_ai",
    access_tier=ProviderAccessTier.LICENSED_ENTITLEMENT,
    retention_mode=ProviderRetentionMode.EPHEMERAL_METADATA,
    allowed_operations=frozenset({SourceDataOperation.DIRECT_REQUEST}),
    allowed_output_fields=CLINICALKEY_AI_CITATION_FIELDS,
    persistable_fields=frozenset(),
    raw_payload_retention_allowed=False,
    requires_contract_acknowledgement=True,
    requires_entitlement_confirmation=True,
    requires_end_user_context=True,
    sensitive_input_allowed=False,
    data_plane_only=True,
)
