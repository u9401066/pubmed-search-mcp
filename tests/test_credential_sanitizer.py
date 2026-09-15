"""Credential-alias regressions for durable unified-search inputs."""

from __future__ import annotations

import pytest

from pubmed_search.shared.credential_sanitizer import (
    contains_credential_material,
    extract_credential_values,
    is_credential_field,
    redact_credential_assignments,
    redact_known_credential_values,
)


def test_empty_credentials_cannot_expand_or_damage_unrelated_payloads() -> None:
    secrets = extract_credential_values("Authorization:   ")
    assert secrets == frozenset()
    payload = {"query": "cancer treatment", "results": ["research notes"]}
    assert redact_known_credential_values(payload, frozenset({"", " "})) == payload


@pytest.mark.parametrize(
    "label",
    [
        "NCBI_API_KEY",
        "CORE_API_KEY",
        "S2_API_KEY",
        "SEMANTIC_SCHOLAR_API_KEY",
        "OPENALEX_API_KEY",
        "SCOPUS_API_KEY",
        "SCOPUS_INSTTOKEN",
        "WEB_OF_SCIENCE_API_KEY",
        "CLINICALKEY_AI_CLIENT_SECRET",
        "PUBMED_AUTH_TOKENS",
        "BROWSER_FETCH_TOKEN",
        "BROWSER_FETCH_BROKER_TOKEN",
        "EZPROXY_COOKIE",
        "X-ELS-APIKey",
        "X-ELS-Insttoken",
        "x-api-key",
    ],
)
def test_repository_credential_aliases_are_detected(label: str) -> None:
    sentinel = "TOPSECRET_SENTINEL"

    text = f"cancer {label}={sentinel}"

    assert contains_credential_material(text)
    assert sentinel in extract_credential_values(text)
    assert sentinel not in redact_credential_assignments(text)
    assert "[REDACTED]" in redact_credential_assignments(text)
    assert is_credential_field(label)


def test_saved_pipeline_prefix_does_not_hide_credential_assignment() -> None:
    assert contains_credential_material("saved:S2_API_KEY=TOPSECRET_SENTINEL")


@pytest.mark.parametrize(
    "text",
    [
        "cancer --api-key TOPSECRET_SENTINEL",
        "cancer --api-key=TOPSECRET_SENTINEL",
        "cancer --ncbi-api-key TOPSECRET_SENTINEL",
        "cancer NCBI_API_KEY TOPSECRET_SENTINEL",
        "cancer X-API-Key TOPSECRET_SENTINEL",
    ],
)
def test_space_and_cli_credential_forms_are_detected_and_redacted(text: str) -> None:
    sentinel = "TOPSECRET_SENTINEL"

    assert contains_credential_material(text)
    assert sentinel in extract_credential_values(text)
    assert sentinel not in redact_credential_assignments(text)
    assert "[REDACTED]" in redact_credential_assignments(text)


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Bearer TOPSECRET_SENTINEL",
        "Authorization: Basic TOPSECRET_SENTINEL",
        '"Authorization": "Bearer TOPSECRET_SENTINEL"',
        "Proxy-Authorization: Basic TOPSECRET_SENTINEL",
    ],
)
def test_authorization_headers_redact_the_scheme_and_credential_together(text: str) -> None:
    sentinel = "TOPSECRET_SENTINEL"

    assert contains_credential_material(text)
    assert sentinel not in redact_credential_assignments(text)
    assert "[REDACTED]" in redact_credential_assignments(text)


@pytest.mark.parametrize(
    "query",
    [
        "protein kinase key interactions",
        "S2 score and API adoption in oncology",
        "insttokenization in clinical notes",
    ],
)
def test_unlabelled_biomedical_key_terms_are_not_credentials(query: str) -> None:
    assert not contains_credential_material(query)
