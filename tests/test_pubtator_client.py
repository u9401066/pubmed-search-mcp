"""
Tests for infrastructure/pubtator/client.py.

Covers: PubTatorClient, rate limiting, find_entity, search_by_entity,
        resolve_entity, find_relations, annotations, and runtime ownership.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.infrastructure.pubtator.client import (
    PubTatorClient,
    close_pubtator_client,
    get_pubtator_client,
)
from pubmed_search.infrastructure.pubtator.models import (
    EntityMatch,
)
from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.shared.async_utils import RetryableOperationError


@pytest.fixture
def client():
    return PubTatorClient(timeout=5.0, rate_limit=100.0)


# ============================================================
# PubTatorClient init
# ============================================================


class TestPubTatorClientInit:
    async def test_default_values(self):
        c = PubTatorClient()
        assert c._timeout == PubTatorClient.DEFAULT_TIMEOUT
        assert c._requests_per_second == PubTatorClient.DEFAULT_RATE_LIMIT
        assert c._client is not None
        await c.close()

    async def test_custom_values(self):
        c = PubTatorClient(timeout=30.0, rate_limit=5.0)
        assert c._timeout == 30.0
        assert c._requests_per_second == 5.0
        await c.close()


# ============================================================
# _get_client
# ============================================================


class TestGetClient:
    @pytest.mark.asyncio
    async def test_creates_client(self, client):
        http_client = await client._get_client()
        assert http_client is not None
        assert not http_client.is_closed
        await client.close()

    @pytest.mark.asyncio
    async def test_reuses_client(self, client):
        c1 = await client._get_client()
        c2 = await client._get_client()
        assert c1 is c2
        await client.close()


# ============================================================
# close
# ============================================================


class TestClose:
    @pytest.mark.asyncio
    async def test_close_idempotent(self, client):
        await client.close()  # no client yet
        await client._get_client()
        await client.close()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_when_already_closed(self, client):
        await client.close()
        assert client._client is None


# ============================================================
# shared transport
# ============================================================


class TestSharedTransport:
    @pytest.mark.asyncio
    async def test_min_interval_derived_from_rate_limit(self, client):
        assert client._min_interval == pytest.approx(0.01)


# ============================================================
# _request
# ============================================================


class TestRequest:
    @pytest.mark.asyncio
    async def test_success(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"result": "ok"}

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp
        mock_http.is_closed = False

        client._execute_request = mock_http.get
        result = await client._request("test/endpoint", {"key": "val"})
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_rate_limit_429(self, client):
        """429 triggers retry."""
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_429.headers = {"Retry-After": "0"}

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.raise_for_status = MagicMock()
        mock_resp_ok.json.return_value = {"ok": True}

        mock_http = AsyncMock()
        mock_http.get.side_effect = [mock_resp_429, mock_resp_ok]
        mock_http.is_closed = False

        client._execute_request = mock_http.get
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("test")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_timeout_retries(self, client):
        """Timeout retries, then raises a sanitized typed failure."""
        import httpx

        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.TimeoutException("timeout")
        mock_http.is_closed = False

        client._execute_request = mock_http.get
        with pytest.raises(APIRequestError, match="PubTator3 request failed"):
            await client._request("test")
        assert mock_http.get.call_count == client._MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_server_error_retries(self, client):
        """5xx triggers retry."""
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        error = httpx.HTTPStatusError("500", request=MagicMock(), response=mock_resp)
        mock_resp.raise_for_status.side_effect = error

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp
        mock_http.is_closed = False

        client._execute_request = mock_http.get
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RetryableOperationError, match="PubTator3 request failed") as caught:
                await client._request("test")
        assert caught.value.status_code == 500

    @pytest.mark.asyncio
    async def test_client_error_raises_sanitized_failure(self, client):
        """4xx (not 429) raises the shared sanitized typed failure."""
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.reason_phrase = "Bad Request"
        error = httpx.HTTPStatusError("400", request=MagicMock(), response=mock_resp)
        mock_resp.raise_for_status.side_effect = error

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp
        mock_http.is_closed = False

        client._execute_request = mock_http.get
        with pytest.raises(APIRequestError, match="PubTator3 request failed with HTTP 400") as caught:
            await client._request("test")
        assert caught.value.status_code == 400

    @pytest.mark.asyncio
    async def test_autocomplete_404_disables_future_entity_requests(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.reason_phrase = "Not Found"
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp
        mock_http.is_closed = False

        client._execute_request = mock_http.get

        first = await client.find_entity("propofol", concept="chemical")
        second = await client.find_entity("midazolam", concept="chemical")

        assert first == []
        assert second == []
        assert client._entity_autocomplete_disabled is True
        assert mock_http.get.await_count == 1

    @pytest.mark.asyncio
    async def test_unexpected_error(self, client):
        mock_http = AsyncMock()
        mock_http.get.side_effect = ValueError("unexpected")
        mock_http.is_closed = False

        client._execute_request = mock_http.get
        with pytest.raises(APIRequestError, match="PubTator3 request failed"):
            await client._request("test")


# ============================================================
# find_entity
# ============================================================


class TestFindEntity:
    @pytest.mark.asyncio
    async def test_success(self, client):
        with patch.object(
            client,
            "_request",
            return_value={
                "results": [
                    {
                        "_id": "@CHEMICAL_Propofol",
                        "name": "Propofol",
                        "type": "chemical",
                        "identifier": "C12345",
                        "score": 0.95,
                    }
                ]
            },
        ):
            matches = await client.find_entity("propofol", concept="chemical")
        assert len(matches) == 1
        assert matches[0].name == "Propofol"
        assert matches[0].entity_id == "@CHEMICAL_Propofol"

    @pytest.mark.asyncio
    async def test_no_results(self, client):
        with patch.object(client, "_request", return_value=None):
            matches = await client.find_entity("xyznonexistent")
        assert matches == []

    @pytest.mark.asyncio
    async def test_empty_results(self, client):
        with patch.object(client, "_request", return_value={"results": []}):
            matches = await client.find_entity("nothing")
        assert matches == []

    @pytest.mark.asyncio
    async def test_skips_lookup_when_autocomplete_already_disabled(self, client):
        client._entity_autocomplete_disabled = True
        with patch.object(client, "_request", new=AsyncMock()) as mock_request:
            matches = await client.find_entity("propofol", concept="chemical")

        assert matches == []
        mock_request.assert_not_awaited()


# ============================================================
# search_by_entity
# ============================================================


class TestSearchByEntity:
    @pytest.mark.asyncio
    async def test_success(self, client):
        with patch.object(
            client,
            "_request",
            return_value={"count": 42, "results": ["123", "456"]},
        ):
            result = await client.search_by_entity("@CHEMICAL_Propofol")
        assert result["count"] == 42
        assert len(result["pmids"]) == 2

    @pytest.mark.asyncio
    async def test_empty(self, client):
        with patch.object(client, "_request", return_value=None):
            result = await client.search_by_entity("@UNKNOWN")
        assert result == {"count": 0, "pmids": []}


# ============================================================
# resolve_entity
# ============================================================


class TestResolveEntity:
    @pytest.mark.asyncio
    async def test_success(self, client):
        mock_match = EntityMatch(
            entity_id="@GENE_BRCA1",
            name="BRCA1",
            type="gene",
            identifier="672",
            score=1.0,
        )
        with patch.object(client, "find_entity", return_value=[mock_match]):
            entity = await client.resolve_entity("BRCA1", preferred_type="gene")
        assert entity is not None
        assert entity.resolved_name == "BRCA1"
        assert entity.entity_type == "gene"

    @pytest.mark.asyncio
    async def test_not_found(self, client):
        with patch.object(client, "find_entity", return_value=[]):
            entity = await client.resolve_entity("unknown_entity")
        assert entity is None


# ============================================================
# find_relations
# ============================================================


class TestFindRelations:
    @pytest.mark.asyncio
    async def test_success(self, client):
        with patch.object(
            client,
            "_request",
            return_value={
                "results": [
                    {
                        "e1": {"id": "@CHEMICAL_Propofol", "name": "Propofol"},
                        "type": "treat",
                        "e2": {"id": "@DISEASE_Pain", "name": "Pain"},
                        "count": 10,
                        "pmids": ["111", "222"],
                    }
                ]
            },
        ):
            rels = await client.find_relations("@CHEMICAL_Propofol", relation_type="treat", target_type="disease")
        assert len(rels) == 1
        assert rels[0].relation_type == "treat"
        assert rels[0].target_name == "Pain"

    @pytest.mark.asyncio
    async def test_empty(self, client):
        with patch.object(client, "_request", return_value=None):
            rels = await client.find_relations("@UNKNOWN")
        assert rels == []


# ============================================================
# get_annotations
# ============================================================


class TestGetAnnotations:
    @pytest.mark.asyncio
    async def test_success(self, client):
        with patch.object(
            client,
            "_request",
            return_value={
                "PubTator3": [
                    {
                        "id": "12345678",
                        "passages": [
                            {
                                "annotations": [
                                    {"text": "Propofol", "infons": {"type": "Chemical", "identifier": "C12345"}},
                                    {"text": "BRCA1", "infons": {"type": "Gene", "identifier": "672"}},
                                ]
                            }
                        ],
                    }
                ]
            },
        ):
            ann = await client.get_annotations("12345678")
        assert len(ann["chemicals"]) == 1
        assert ann["chemicals"][0]["text"] == "Propofol"
        assert len(ann["genes"]) == 1

    @pytest.mark.asyncio
    async def test_empty(self, client):
        with patch.object(client, "_request", return_value=None):
            ann = await client.get_annotations("99999")
        assert ann == {}


# ============================================================
# Runtime ownership
# ============================================================


class TestRuntimeOwnership:
    async def test_get_pubtator_client(self):
        from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime

        runtime_a = SourceRuntime()
        runtime_b = SourceRuntime()
        with bind_source_runtime(runtime_a):
            c1 = get_pubtator_client()
            c2 = get_pubtator_client()
        with bind_source_runtime(runtime_b):
            c3 = get_pubtator_client()

        assert c1 is c2
        assert c1 is not c3
        await runtime_a.close()
        await runtime_b.close()

    @pytest.mark.asyncio
    async def test_close_pubtator_client_closes_only_active_runtime(self):
        from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime

        runtime_a = SourceRuntime()
        runtime_b = SourceRuntime()
        with bind_source_runtime(runtime_a):
            client_a = get_pubtator_client()
        with bind_source_runtime(runtime_b):
            client_b = get_pubtator_client()
        client_a.close = AsyncMock()
        client_b.close = AsyncMock()

        with bind_source_runtime(runtime_a):
            await close_pubtator_client()

        client_a.close.assert_awaited_once()
        client_b.close.assert_not_awaited()
        with bind_source_runtime(runtime_a):
            assert get_pubtator_client() is not client_a
        await runtime_a.close()
        await runtime_b.close()

    @pytest.mark.asyncio
    async def test_close_when_none(self):
        from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime

        runtime = SourceRuntime()
        with bind_source_runtime(runtime):
            await close_pubtator_client()
        assert runtime.cached_clients() == ()


async def test_pubtator_real_http_path_and_bioc_annotations(client):
    import httpx

    def respond(request):
        assert request.url.path == "/research/pubtator3-api/publications/export/biocjson"
        return httpx.Response(
            200,
            json={
                "PubTator3": [
                    {
                        "id": "123",
                        "passages": [
                            {
                                "annotations": [
                                    {"text": "BRCA1", "infons": {"type": "Gene", "identifier": "672"}},
                                    {"text": "cancer", "infons": {"type": "Disease", "identifier": "D009369"}},
                                ]
                            }
                        ],
                    }
                ]
            },
        )

    await client.close()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await client.get_annotations("123")
        assert result["genes"] == [{"text": "BRCA1", "id": "672"}]
        assert result["diseases"] == [{"text": "cancer", "id": "D009369"}]
    finally:
        await client.close()
        await client.close()
