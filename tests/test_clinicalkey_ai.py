"""Synthetic contract tests for the restricted ClinicalKey AI data plane."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, fields, replace
from urllib.parse import parse_qs

import httpx
import pytest

from pubmed_search.application.search.clinical_evidence import (
    ClinicalCitationMetadata,
    ClinicalEvidenceCitationRequest,
)
from pubmed_search.application.search.source_governance import (
    CLINICALKEY_AI_DATA_POLICY,
    ProviderAccessTier,
    ProviderRetentionMode,
    SourceDataOperation,
    SourceGovernanceError,
)
from pubmed_search.infrastructure.sources.clinicalkey_ai import (
    CLINICALKEY_AI_CITATIONS_V2_URL,
    CLINICALKEY_AI_OAUTH_URL,
    ClinicalKeyAIClient,
    ClinicalKeyAIConfig,
    ClinicalKeyAIConfigurationError,
    ClinicalKeyAIInputPolicyError,
    ClinicalKeyAIResponseError,
    ClinicalKeyAITransportError,
    ClinicalKeyAIUpstreamError,
)
from pubmed_search.infrastructure.sources.registry import get_source_registry
from pubmed_search.shared.settings import load_settings


class FakeClock:
    """Controllable monotonic clock for expiry tests."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _enabled_config() -> ClinicalKeyAIConfig:
    return ClinicalKeyAIConfig(
        enabled=True,
        entitlement_confirmed=True,
        contract_acknowledged=True,
        client_id="test-client",
        client_secret="test-secret",
    )


def _request(**overrides: object) -> ClinicalEvidenceCitationRequest:
    request = ClinicalEvidenceCitationRequest(
        question="What evidence supports intervention X?",
        end_user_id="tenant-user-7",
        end_user_persona="clinician",
        secondary_org_id="hospital-3",
        input_is_deidentified=True,
    )
    return replace(request, **overrides)


def _token_response(*, access_value: str = "access-token", expires_in: int = 300) -> httpx.Response:
    return httpx.Response(
        200,
        json={"access_token": access_value, "token_type": "Bearer", "expires_in": expires_in},
    )


def test_settings_are_default_off_and_secrets_are_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    names = (
        "CLINICALKEY_AI_ENABLED",
        "CLINICALKEY_AI_ENTITLEMENT_CONFIRMED",
        "CLINICALKEY_AI_CONTRACT_ACKNOWLEDGED",
        "CLINICALKEY_AI_CLIENT_ID",
        "CLINICALKEY_AI_CLIENT_SECRET",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()
    config = ClinicalKeyAIConfig.from_settings(settings)

    assert settings.clinicalkey_ai_enabled is False
    assert settings.clinicalkey_ai_entitlement_confirmed is False
    assert settings.clinicalkey_ai_contract_acknowledged is False
    assert settings.clinicalkey_ai_client_id is None
    assert settings.clinicalkey_ai_client_secret is None
    assert config.enabled is False

    monkeypatch.setenv("CLINICALKEY_AI_ENABLED", "true")
    monkeypatch.setenv("CLINICALKEY_AI_ENTITLEMENT_CONFIRMED", "true")
    monkeypatch.setenv("CLINICALKEY_AI_CONTRACT_ACKNOWLEDGED", "true")
    monkeypatch.setenv("CLINICALKEY_AI_CLIENT_ID", " client-id ")
    monkeypatch.setenv("CLINICALKEY_AI_CLIENT_SECRET", " client-secret ")
    configured_settings = load_settings()
    configured = ClinicalKeyAIConfig.from_settings(configured_settings)

    assert configured.client_id == "client-id"
    assert configured.client_secret == "client-secret"
    assert "client-secret" not in repr(configured_settings)
    assert "client-secret" not in repr(configured)


@pytest.mark.parametrize(
    "config",
    [
        ClinicalKeyAIConfig(),
        replace(_enabled_config(), entitlement_confirmed=False),
        replace(_enabled_config(), contract_acknowledged=False),
        replace(_enabled_config(), client_secret=None),
    ],
)
async def test_activation_gates_fail_before_network(config: ClinicalKeyAIConfig) -> None:
    def unexpected_request(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected network call to {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)) as http_client:
        client = ClinicalKeyAIClient(config, http_client=http_client)
        with pytest.raises(ClinicalKeyAIConfigurationError):
            await client.fetch_citations(_request())


def test_governance_allows_only_explicit_ephemeral_data_plane_requests() -> None:
    policy = CLINICALKEY_AI_DATA_POLICY
    assert policy.access_tier is ProviderAccessTier.LICENSED_ENTITLEMENT
    assert policy.retention_mode is ProviderRetentionMode.EPHEMERAL_METADATA
    assert policy.data_plane_only is True
    assert policy.requires_contract_acknowledgement is True
    assert policy.requires_entitlement_confirmation is True
    assert policy.requires_end_user_context is True
    assert policy.sensitive_input_allowed is False
    assert policy.persistable_fields == frozenset()
    assert policy.raw_payload_retention_allowed is False
    assert policy.allowed_operations == frozenset({SourceDataOperation.DIRECT_REQUEST})
    assert policy.allowed_output_fields == {item.name for item in fields(ClinicalCitationMetadata)}

    for forbidden in set(SourceDataOperation) - {SourceDataOperation.DIRECT_REQUEST}:
        with pytest.raises(SourceGovernanceError):
            policy.require(forbidden)

    registry = get_source_registry()
    assert registry.get("clinicalkey_ai") is None
    assert "clinicalkey_ai" not in registry.list_unified_sources()


@pytest.mark.parametrize(
    ("citation_request", "message"),
    [
        (_request(input_is_deidentified=False), "de-identified"),
        (
            _request(use_case="differential_diagnosis"),  # type: ignore[arg-type]
            "diagnostic use is forbidden",
        ),
        (_request(end_user_id="bad\r\nX-Injected: yes"), "safe header"),
    ],
)
async def test_input_policy_blocks_sensitive_diagnostic_and_header_injection(
    citation_request: ClinicalEvidenceCitationRequest,
    message: str,
) -> None:
    def unexpected_request(raw_request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected network call to {raw_request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        with pytest.raises(ClinicalKeyAIInputPolicyError, match=message):
            await client.fetch_citations(citation_request)


async def test_v2_headers_oauth_form_and_metadata_allowlist() -> None:
    requests: list[httpx.Request] = []
    question = "What evidence supports intervention X?"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL):
            form = parse_qs(request.content.decode())
            assert form == {
                "grant_type": ["client_credentials"],
                "client_id": ["test-client"],
                "client_secret": ["test-secret"],
            }
            return _token_response(access_value="private-token")

        assert request.url == httpx.URL(CLINICALKEY_AI_CITATIONS_V2_URL)
        assert request.headers["Authorization"] == "Bearer private-token"
        assert request.headers["End-User-Id"] == "tenant-user-7"
        assert request.headers["End-User-Persona"] == "clinician"
        assert request.headers["Secondary-Org-Id"] == "hospital-3"
        assert json.loads(request.content) == {"question": question}
        return httpx.Response(
            200,
            json={
                "result": {
                    "references": {
                        "ref-1": [
                            {
                                "result": {
                                    "_source": {
                                        "document_title": "  Evidence   Trial  ",
                                        "title": "Journal of Evidence",
                                        "authors": ["Ada Author", {"name": "Ben Writer"}],
                                        "doi": "https://doi.org/10.1234/ABC",
                                        "pmid": 123456,
                                        "identifier": "CK-9",
                                        "identifier_type": "clinicalkey",
                                        "publication_date": "2026-01-02",
                                        "href": "https://example.org/article?access_token=leak#licensed",
                                        "chunk_text": "LICENSED_CHUNK_MUST_NOT_ESCAPE",
                                        "breadcrumbs": ["licensed", "hierarchy"],
                                        "content_props": {"body": "PROPRIETARY_BODY"},
                                        "copyright_license": "PROVIDER_LICENSE_TEXT",
                                    }
                                }
                            }
                        ]
                    },
                    "answer": "GENERATED_ANSWER_MUST_NOT_ESCAPE",
                    "processed_question": question,
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        batch = await client.fetch_citations(_request())

    assert len(requests) == 2
    assert batch.provider_reference_count == 1
    assert batch.dropped_reference_count == 0
    citation = batch.citations[0]
    assert citation.reference_id == "ref-1"
    assert citation.document_title == "Evidence Trial"
    assert citation.container_title == "Journal of Evidence"
    assert citation.authors == ("Ada Author", "Ben Writer")
    assert citation.doi == "10.1234/abc"
    assert citation.pmid == "123456"
    assert citation.href == "https://example.org/article"

    serialized = json.dumps(asdict(batch), sort_keys=True)
    for forbidden in (
        question,
        "private-token",
        "test-secret",
        "LICENSED_CHUNK_MUST_NOT_ESCAPE",
        "PROPRIETARY_BODY",
        "PROVIDER_LICENSE_TEXT",
        "GENERATED_ANSWER_MUST_NOT_ESCAPE",
        "access_token=leak",
    ):
        assert forbidden not in serialized


async def test_tolerant_schema_handles_wrapped_unwrapped_partial_and_duplicate_references() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL):
            return _token_response()
        return httpx.Response(
            200,
            json={
                "references": [
                    {"_source": {"document_title": "First", "pmid": "7001"}},
                    {
                        "document_title": "Duplicate identity",
                        "pmid": 7001,
                        "chunk_text": "duplicate raw chunk",
                    },
                    {
                        "result": {
                            "identifier": 42,
                            "identifier_type": "ck",
                            "authors": "Solo Author",
                        }
                    },
                    {"result": {"_source": {"chunk_text": "only licensed content"}}},
                    "malformed",
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        batch = await client.fetch_citations(_request(secondary_org_id=None))

    assert batch.provider_reference_count == 5
    assert batch.dropped_reference_count == 3
    assert [citation.reference_id for citation in batch.citations] == ["1", "3"]
    assert batch.citations[0].pmid == "7001"
    assert batch.citations[1].identifier == "42"
    assert batch.citations[1].authors == ("Solo Author",)


async def test_http_200_error_envelope_fails_closed_without_leaking_provider_text() -> None:
    secret_question = "patient-question-must-not-leak"
    secret_error = "licensed-provider-error-must-not-leak"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL):
            return _token_response()
        return httpx.Response(
            200,
            json={
                "status": "error",
                "error_type": "provider_failure",
                "error_msg": secret_error,
                "question": secret_question,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        with pytest.raises(ClinicalKeyAIResponseError) as error_info:
            await client.fetch_citations(_request(question=secret_question))

    rendered = str(error_info.value)
    assert secret_question not in rendered
    assert secret_error not in rendered


async def test_truthy_non_boolean_values_cannot_bypass_governance_gates() -> None:
    config = replace(
        _enabled_config(),
        enabled="false",  # type: ignore[arg-type]
        entitlement_confirmed="false",  # type: ignore[arg-type]
        contract_acknowledged="false",  # type: ignore[arg-type]
    )
    request = replace(_request(), input_is_deidentified="false")  # type: ignore[arg-type]

    def unexpected_request(raw_request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unexpected network call to {raw_request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)) as http_client:
        client = ClinicalKeyAIClient(config, http_client=http_client)
        with pytest.raises(ClinicalKeyAIConfigurationError):
            await client.fetch_citations(_request())

        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        with pytest.raises(ClinicalKeyAIInputPolicyError):
            await client.fetch_citations(request)


async def test_oauth_token_is_reused_until_expiry_then_refreshed() -> None:
    clock = FakeClock()
    token_calls = 0
    citation_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL):
            token_calls += 1
            return _token_response(access_value=f"token-{token_calls}", expires_in=100)
        citation_tokens.append(request.headers["Authorization"])
        return httpx.Response(200, json={"references": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client, clock=clock)
        await client.fetch_citations(_request())
        clock.advance(89)
        await client.fetch_citations(_request())
        clock.advance(2)
        await client.fetch_citations(_request())

    assert token_calls == 2
    assert citation_tokens == ["Bearer token-1", "Bearer token-1", "Bearer token-2"]


async def test_parallel_initial_oauth_requests_are_single_flight() -> None:
    token_calls = 0
    citation_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, citation_calls
        if request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL):
            token_calls += 1
            await asyncio.sleep(0)
            return _token_response()
        citation_calls += 1
        return httpx.Response(200, json={"references": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        await asyncio.gather(
            client.fetch_citations(_request()),
            client.fetch_citations(_request()),
            client.fetch_citations(_request()),
        )

    assert token_calls == 1
    assert citation_calls == 3


async def test_parallel_401_responses_share_one_refresh_and_retry_once() -> None:
    token_calls = 0
    old_token_arrivals = 0
    citation_tokens: list[str] = []
    both_old_requests_arrived = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, old_token_arrivals
        if request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL):
            token_calls += 1
            return _token_response(access_value="old-token" if token_calls == 1 else "new-token")

        authorization = request.headers["Authorization"]
        citation_tokens.append(authorization)
        if authorization == "Bearer old-token":
            old_token_arrivals += 1
            if old_token_arrivals == 2:
                both_old_requests_arrived.set()
            await both_old_requests_arrived.wait()
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"references": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        await asyncio.gather(
            client.fetch_citations(_request()),
            client.fetch_citations(_request()),
        )

    assert token_calls == 2
    assert citation_tokens.count("Bearer old-token") == 2
    assert citation_tokens.count("Bearer new-token") == 2


async def test_second_401_is_not_retried_and_error_is_sanitized() -> None:
    token_calls = 0
    citation_calls = 0
    upstream_body = "provider-body-with-test-secret-and-patient-question"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, citation_calls
        if request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL):
            token_calls += 1
            return _token_response(access_value=f"private-token-{token_calls}")
        citation_calls += 1
        return httpx.Response(401, text=upstream_body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        with pytest.raises(ClinicalKeyAIUpstreamError) as error_info:
            await client.fetch_citations(_request(question="patient-question"))

    assert token_calls == 2
    assert citation_calls == 2
    assert error_info.value.status_code == 401
    rendered_error = repr(error_info.value)
    assert "test-secret" not in rendered_error
    assert "private-token" not in rendered_error
    assert "patient-question" not in rendered_error
    assert upstream_body not in rendered_error


async def test_rate_limit_exposes_only_standard_retry_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL):
            return _token_response()
        return httpx.Response(
            429,
            headers={"Retry-After": "7"},
            text="licensed body must stay private",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        with pytest.raises(ClinicalKeyAIUpstreamError) as error_info:
            await client.fetch_citations(_request())

    assert error_info.value.status_code == 429
    assert error_info.value.retry_after_seconds == 7.0
    assert "licensed body" not in repr(error_info.value)


async def test_token_transport_error_does_not_retain_oauth_secret_context() -> None:
    secret = "oauth-client-secret-sentinel"
    config = replace(_enabled_config(), client_secret=secret)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(config, http_client=http_client)
        with pytest.raises(ClinicalKeyAITransportError) as error_info:
            await client.fetch_citations(_request())

    error = error_info.value
    assert secret not in str(error)
    assert secret not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None


async def test_invalid_json_error_does_not_retain_licensed_body_context() -> None:
    licensed_body = "licensed-response-body-sentinel"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL):
            return _token_response()
        return httpx.Response(200, text=licensed_body, headers={"Content-Type": "application/json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        with pytest.raises(ClinicalKeyAIResponseError) as error_info:
            await client.fetch_citations(_request())

    error = error_info.value
    assert licensed_body not in str(error)
    assert licensed_body not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(
    "token_payload",
    [
        {},
        {"access_token": "token", "expires_in": 0},
        {"access_token": "token with spaces", "expires_in": 300},
        {"access_token": "token", "token_type": "MAC", "expires_in": 300},
        {"access_token": "token", "token_type": 7, "expires_in": 300},
    ],
)
async def test_malformed_token_contract_fails_closed(token_payload: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(CLINICALKEY_AI_OAUTH_URL)
        return httpx.Response(200, json=token_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)
        with pytest.raises(ClinicalKeyAIResponseError):
            await client.fetch_citations(_request())


async def test_client_does_not_close_injected_http_client() -> None:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: _token_response()))
    client = ClinicalKeyAIClient(_enabled_config(), http_client=http_client)

    await client.aclose()

    assert http_client.is_closed is False
    await http_client.aclose()
