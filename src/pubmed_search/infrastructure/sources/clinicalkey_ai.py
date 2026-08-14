"""Entitlement-gated ClinicalKey AI citation data-plane adapter.

This adapter is intentionally not registered as a search source or MCP tool.
It returns only allowlisted citation metadata and never exposes provider chunks,
generated answers, request questions, or raw response payloads.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit, urlunsplit

import httpx
from typing_extensions import Self

from pubmed_search.application.search.clinical_evidence import (
    ClinicalCitationBatch,
    ClinicalCitationMetadata,
    ClinicalEvidenceCitationRequest,
    ClinicalEvidenceUseCase,
)
from pubmed_search.application.search.source_governance import (
    CLINICALKEY_AI_DATA_POLICY,
    SourceDataOperation,
)
from pubmed_search.shared.article_identity import normalize_article_doi
from pubmed_search.shared.async_utils import create_async_http_client, parse_retry_after

if TYPE_CHECKING:
    from pubmed_search.shared.settings import AppSettings

CLINICALKEY_AI_OAUTH_URL = "https://access.identity.elsevier.com/realms/digital/protocol/openid-connect/token"
CLINICALKEY_AI_CITATIONS_V2_URL = "https://api-us.digital.elsevier.com/knowledge/clinicalkey/ai/api/v2/citations"

_CITATION_SOURCE_FIELDS = frozenset(
    {
        "document_title",
        "title",
        "authors",
        "doi",
        "pmid",
        "identifier",
        "identifier_type",
        "publication_date",
        "href",
    }
)
_HEADER_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class _FailureSentinel:
    """Private result marker used to discard sensitive third-party exceptions."""


_REQUEST_FAILED = _FailureSentinel()
_JSON_DECODE_FAILED = _FailureSentinel()


class ClinicalKeyAIError(RuntimeError):
    """Base error for the restricted ClinicalKey AI adapter."""


class ClinicalKeyAIConfigurationError(ClinicalKeyAIError):
    """Raised when explicit enablement, entitlement, or credentials are missing."""


class ClinicalKeyAIInputPolicyError(ClinicalKeyAIError):
    """Raised before sending input that is outside the approved use case."""


class ClinicalKeyAITransportError(ClinicalKeyAIError):
    """Raised for a sanitized network failure without retaining request details."""


class ClinicalKeyAIResponseError(ClinicalKeyAIError):
    """Raised for a malformed response without retaining provider content."""


class ClinicalKeyAIUpstreamError(ClinicalKeyAIError):
    """Sanitized HTTP error that never owns an httpx response or request."""

    def __init__(
        self,
        *,
        operation: str,
        status_code: int,
        retry_after_seconds: float | None,
    ) -> None:
        super().__init__(f"ClinicalKey AI {operation} failed with HTTP {status_code}")
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class ClinicalKeyAIConfig:
    """Explicit activation gates and OAuth client configuration."""

    enabled: bool = False
    entitlement_confirmed: bool = False
    contract_acknowledged: bool = False
    client_id: str | None = None
    client_secret: str | None = field(default=None, repr=False)
    timeout_seconds: float = 30.0
    token_expiry_skew_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("ClinicalKey AI timeout must be positive")
        if self.token_expiry_skew_seconds < 0:
            raise ValueError("ClinicalKey AI token expiry skew cannot be negative")

    @classmethod
    def from_settings(cls, settings: AppSettings) -> ClinicalKeyAIConfig:
        """Build config without placing per-user identity in process settings."""
        secret = settings.clinicalkey_ai_client_secret
        return cls(
            enabled=settings.clinicalkey_ai_enabled,
            entitlement_confirmed=settings.clinicalkey_ai_entitlement_confirmed,
            contract_acknowledged=settings.clinicalkey_ai_contract_acknowledged,
            client_id=settings.clinicalkey_ai_client_id,
            client_secret=secret.get_secret_value() if secret is not None else None,
        )


@dataclass(frozen=True, slots=True)
class _OAuthAccessToken:
    value: str = field(repr=False)
    expires_at_monotonic: float


@dataclass(frozen=True, slots=True)
class _ValidatedCitationRequest:
    question: str = field(repr=False)
    end_user_id: str = field(repr=False)
    end_user_persona: str = field(repr=False)
    secondary_org_id: str | None = field(default=None, repr=False)


class ClinicalKeyAIClient:
    """OAuth client for the v2 citation endpoint with fail-closed governance."""

    def __init__(
        self,
        config: ClinicalKeyAIConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._http_client = http_client or create_async_http_client(
            timeout=config.timeout_seconds,
            follow_redirects=False,
            max_connections=10,
            max_keepalive_connections=5,
        )
        self._owns_http_client = http_client is None
        self._clock = clock
        self._access_token: _OAuthAccessToken | None = None
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: object,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close only the HTTP client owned by this adapter instance."""
        if self._owns_http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def fetch_citations(
        self,
        request: ClinicalEvidenceCitationRequest,
    ) -> ClinicalCitationBatch:
        """Fetch ephemeral citation metadata after all local policy gates pass."""
        self._require_activation()
        validated = self._validate_request(request)
        token = await self._get_access_token()

        response = await self._post_citations(validated, token)
        if response.status_code == httpx.codes.UNAUTHORIZED:
            token = await self._refresh_after_unauthorized(token)
            response = await self._post_citations(validated, token)

        self._raise_for_status(response, operation="citation request")
        payload = self._decode_json_object(response, operation="citation response")
        _raise_for_error_envelope(payload)
        return _extract_citation_batch(payload)

    def _require_activation(self) -> None:
        CLINICALKEY_AI_DATA_POLICY.require(SourceDataOperation.DIRECT_REQUEST)
        if self._config.enabled is not True:
            raise ClinicalKeyAIConfigurationError("ClinicalKey AI integration is disabled")
        if self._config.entitlement_confirmed is not True:
            raise ClinicalKeyAIConfigurationError("ClinicalKey AI entitlement must be explicitly confirmed")
        if self._config.contract_acknowledged is not True:
            raise ClinicalKeyAIConfigurationError("ClinicalKey AI data-use contract must be explicitly acknowledged")
        if not _has_text(self._config.client_id) or not _has_text(self._config.client_secret):
            raise ClinicalKeyAIConfigurationError("ClinicalKey AI OAuth credentials are incomplete")

    @staticmethod
    def _validate_request(request: ClinicalEvidenceCitationRequest) -> _ValidatedCitationRequest:
        if request.use_case is not ClinicalEvidenceUseCase.EVIDENCE_LOOKUP:
            raise ClinicalKeyAIInputPolicyError(
                "ClinicalKey AI adapter permits evidence lookup only; diagnostic use is forbidden"
            )
        if request.input_is_deidentified is not True:
            raise ClinicalKeyAIInputPolicyError("ClinicalKey AI input must be explicitly marked as de-identified")

        question = _required_question(request.question)
        return _ValidatedCitationRequest(
            question=question,
            end_user_id=_required_header_value(request.end_user_id, field_name="end-user id"),
            end_user_persona=_required_header_value(
                request.end_user_persona,
                field_name="end-user persona",
            ),
            secondary_org_id=_optional_header_value(
                request.secondary_org_id,
                field_name="secondary organization id",
            ),
        )

    async def _get_access_token(self) -> str:
        cached = self._access_token
        if cached is not None and self._is_token_valid(cached):
            return cached.value

        async with self._token_lock:
            cached = self._access_token
            if cached is not None and self._is_token_valid(cached):
                return cached.value
            return await self._request_access_token_locked()

    async def _refresh_after_unauthorized(self, rejected_token: str) -> str:
        """Refresh once, sharing another caller's already-completed refresh."""
        async with self._token_lock:
            current = self._access_token
            if current is not None and current.value != rejected_token and self._is_token_valid(current):
                return current.value

            self._access_token = None
            return await self._request_access_token_locked()

    def _is_token_valid(self, token: _OAuthAccessToken | None) -> bool:
        return token is not None and self._clock() < token.expires_at_monotonic

    async def _request_access_token_locked(self) -> str:
        client_id = self._config.client_id
        client_secret = self._config.client_secret
        if not _has_text(client_id) or not _has_text(client_secret):
            raise ClinicalKeyAIConfigurationError("ClinicalKey AI OAuth credentials are incomplete")

        response = await self._safe_post(
            CLINICALKEY_AI_OAUTH_URL,
            operation="token request",
            data={
                "grant_type": "client_credentials",
                "client_id": cast("str", client_id).strip(),
                "client_secret": cast("str", client_secret).strip(),
            },
            headers={"Accept": "application/json"},
        )
        self._raise_for_status(response, operation="token request")
        payload = self._decode_json_object(response, operation="token response")
        token = _parse_access_token(
            payload,
            now=self._clock(),
            configured_skew=self._config.token_expiry_skew_seconds,
        )
        self._access_token = token
        return token.value

    async def _post_citations(
        self,
        request: _ValidatedCitationRequest,
        token: str,
    ) -> httpx.Response:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "End-User-Id": request.end_user_id,
            "End-User-Persona": request.end_user_persona,
        }
        if request.secondary_org_id is not None:
            headers["Secondary-Org-Id"] = request.secondary_org_id

        return await self._safe_post(
            CLINICALKEY_AI_CITATIONS_V2_URL,
            operation="citation request",
            json={"question": request.question},
            headers=headers,
        )

    async def _safe_post(
        self,
        url: str,
        *,
        operation: str,
        data: Mapping[str, str] | None = None,
        json: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        response = await _post_without_exception_context(
            self._http_client,
            url,
            data=data,
            json=json,
            headers=headers,
        )
        if isinstance(response, _FailureSentinel):
            raise ClinicalKeyAITransportError(f"ClinicalKey AI {operation} failed before a response was received")
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, operation: str) -> None:
        if 200 <= response.status_code < 300:
            return
        raise ClinicalKeyAIUpstreamError(
            operation=operation,
            status_code=response.status_code,
            retry_after_seconds=parse_retry_after(response.headers.get("Retry-After")),
        )

    @staticmethod
    def _decode_json_object(response: httpx.Response, *, operation: str) -> Mapping[str, object]:
        payload = _decode_json_without_exception_context(response)
        if isinstance(payload, _FailureSentinel):
            raise ClinicalKeyAIResponseError(f"ClinicalKey AI {operation} was not valid JSON")
        if not isinstance(payload, Mapping):
            raise ClinicalKeyAIResponseError(f"ClinicalKey AI {operation} was not a JSON object")
        return cast("Mapping[str, object]", payload)


async def _post_without_exception_context(
    http_client: httpx.AsyncClient,
    url: str,
    *,
    data: Mapping[str, str] | None,
    json: Mapping[str, str] | None,
    headers: Mapping[str, str] | None,
) -> httpx.Response | _FailureSentinel:
    """Return a marker so RequestError objects owning secret requests are discarded."""

    try:
        return await http_client.post(url, data=data, json=json, headers=headers)
    except httpx.RequestError:
        return _REQUEST_FAILED


def _decode_json_without_exception_context(response: httpx.Response) -> object:
    """Return a marker so JSON errors owning licensed response text are discarded."""

    try:
        return response.json()
    except ValueError:
        return _JSON_DECODE_FAILED


def _parse_access_token(
    payload: Mapping[str, object],
    *,
    now: float,
    configured_skew: float,
) -> _OAuthAccessToken:
    value = payload.get("access_token")
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 16_384
        or any(character.isspace() for character in value)
    ):
        raise ClinicalKeyAIResponseError("ClinicalKey AI token response omitted a usable access token")

    token_type = payload.get("token_type")
    if token_type is not None and (not isinstance(token_type, str) or token_type.strip().lower() != "bearer"):
        raise ClinicalKeyAIResponseError("ClinicalKey AI token response used an unsupported token type")

    expires_in = _positive_seconds(payload.get("expires_in"))
    if expires_in is None:
        raise ClinicalKeyAIResponseError("ClinicalKey AI token response omitted a valid expires_in")

    adaptive_skew = min(configured_skew, expires_in * 0.1)
    return _OAuthAccessToken(
        value=value,
        expires_at_monotonic=now + expires_in - adaptive_skew,
    )


def _positive_seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    return seconds


def _required_question(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClinicalKeyAIInputPolicyError("ClinicalKey AI evidence question is required")
    normalized = value.strip()
    if "\x00" in normalized:
        raise ClinicalKeyAIInputPolicyError("ClinicalKey AI evidence question contains invalid control data")
    return normalized


def _required_header_value(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClinicalKeyAIInputPolicyError(f"ClinicalKey AI {field_name} is required")
    return _validated_header_value(value, field_name=field_name)


def _optional_header_value(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return _validated_header_value(value, field_name=field_name)


def _validated_header_value(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if len(normalized) > 512 or _HEADER_CONTROL_CHARACTERS.search(normalized):
        raise ClinicalKeyAIInputPolicyError(f"ClinicalKey AI {field_name} is not a safe header value")
    return normalized


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _extract_citation_batch(payload: Mapping[str, object]) -> ClinicalCitationBatch:
    entries = _reference_entries(payload)
    citations: list[ClinicalCitationMetadata] = []
    seen: set[str] = set()
    dropped = 0

    for reference_id, raw_reference in entries:
        source = _citation_source(raw_reference)
        citation = _citation_from_source(reference_id, source) if source is not None else None
        if citation is None:
            dropped += 1
            continue

        identity = _citation_identity(citation)
        if identity in seen:
            dropped += 1
            continue
        seen.add(identity)
        citations.append(citation)

    return ClinicalCitationBatch(
        citations=tuple(citations),
        provider_reference_count=len(entries),
        dropped_reference_count=dropped,
    )


def _raise_for_error_envelope(payload: Mapping[str, object]) -> None:
    """Reject ClinicalKey's HTTP-200 error union without retaining its text."""

    candidates = [payload]
    wrapped = _as_mapping(payload.get("result"))
    if wrapped is not None:
        candidates.append(wrapped)
    for candidate in candidates:
        status = candidate.get("status")
        normalized_status = status.strip().lower() if isinstance(status, str) else ""
        if (
            candidate.get("error_type") is not None
            or candidate.get("error_code") is not None
            or normalized_status in {"error", "failed", "failure"}
        ):
            raise ClinicalKeyAIResponseError("ClinicalKey AI citation response reported an upstream error")


def _reference_entries(payload: Mapping[str, object]) -> list[tuple[str, object]]:
    references: object = payload.get("references")
    wrapped = _as_mapping(payload.get("result"))
    if references is None and wrapped is not None:
        references = wrapped.get("references")

    if isinstance(references, Mapping):
        entries: list[tuple[str, object]] = []
        for key, value in references.items():
            # The official v2 schema is dict[str, list[ReferenceItem]].  Keep
            # accepting the earlier dict[str, ReferenceItem] shape because the
            # published examples and schema have drifted in prior revisions.
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                entries.extend((str(key), item) for item in value)
            else:
                entries.append((str(key), value))
        return entries
    if isinstance(references, Sequence) and not isinstance(references, (str, bytes, bytearray)):
        return [(str(index), value) for index, value in enumerate(references, start=1)]
    return []


def _citation_source(raw_reference: object) -> Mapping[str, object] | None:
    reference = _as_mapping(raw_reference)
    if reference is None:
        return None

    result = _as_mapping(reference.get("result"))
    if result is not None:
        nested_source = _as_mapping(result.get("_source"))
        if nested_source is not None:
            return nested_source
        if _looks_like_citation_source(result):
            return result

    direct_source = _as_mapping(reference.get("_source"))
    if direct_source is not None:
        return direct_source
    if _looks_like_citation_source(reference):
        return reference
    return None


def _looks_like_citation_source(value: Mapping[str, object]) -> bool:
    return bool(_CITATION_SOURCE_FIELDS.intersection(value))


def _citation_from_source(
    reference_id: str,
    source: Mapping[str, object],
) -> ClinicalCitationMetadata | None:
    normalized_reference_id = _clean_scalar(reference_id, max_length=128) or "unknown"
    document_title = _clean_text(source.get("document_title"), max_length=2_000)
    container_title = _clean_text(source.get("title"), max_length=1_000)
    authors = _clean_authors(source.get("authors"))
    doi = _clean_doi(source.get("doi"))
    pmid = _clean_pmid(source.get("pmid"))
    identifier = _clean_scalar(source.get("identifier"), max_length=512)
    identifier_type = _clean_text(source.get("identifier_type"), max_length=128)
    publication_date = _clean_text(source.get("publication_date"), max_length=128)
    href = _safe_href(source.get("href"))

    if not any(
        (
            document_title,
            container_title,
            authors,
            doi,
            pmid,
            identifier,
            identifier_type,
            publication_date,
            href,
        )
    ):
        return None

    return ClinicalCitationMetadata(
        reference_id=normalized_reference_id,
        document_title=document_title,
        container_title=container_title,
        authors=authors,
        doi=doi,
        pmid=pmid,
        identifier=identifier,
        identifier_type=identifier_type,
        publication_date=publication_date,
        href=href,
    )


def _citation_identity(citation: ClinicalCitationMetadata) -> str:
    if citation.doi:
        return f"doi:{citation.doi}"
    if citation.pmid:
        return f"pmid:{citation.pmid}"
    if citation.identifier:
        return f"identifier:{citation.identifier_type or ''}:{citation.identifier.casefold()}"
    if citation.document_title:
        return f"title:{citation.document_title.casefold()}:{citation.publication_date or ''}"
    return f"reference:{citation.reference_id}"


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)


def _clean_text(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > max_length:
        return None
    return normalized


def _clean_scalar(value: object, *, max_length: int) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    if not normalized or len(normalized) > max_length:
        return None
    return normalized


def _clean_authors(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        author = _clean_text(value, max_length=512)
        return (author,) if author is not None else ()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return ()

    authors: list[str] = []
    for item in value[:100]:
        author = _clean_text(item, max_length=512)
        if author is None:
            author_mapping = _as_mapping(item)
            if author_mapping is not None:
                author = next(
                    (
                        name
                        for key in ("display_name", "full_name", "name")
                        if (name := _clean_text(author_mapping.get(key), max_length=512)) is not None
                    ),
                    None,
                )
        if author is not None and author not in authors:
            authors.append(author)
    return tuple(authors)


def _clean_doi(value: object) -> str | None:
    raw = _clean_text(value, max_length=512)
    if raw is None:
        return None
    normalized = normalize_article_doi(raw)
    return normalized or None


def _clean_pmid(value: object) -> str | None:
    raw = _clean_scalar(value, max_length=32)
    if raw is None:
        return None
    normalized = raw.removeprefix("PMID:").removeprefix("pmid:").strip()
    return normalized if normalized.isdigit() else None


def _safe_href(value: object) -> str | None:
    raw = _clean_text(value, max_length=2_048)
    if raw is None:
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() != "https" or parsed.hostname is None:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        _ = parsed.port
    except ValueError:
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, "", ""))
