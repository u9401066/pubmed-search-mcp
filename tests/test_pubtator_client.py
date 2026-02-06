"""
Tests for infrastructure/pubtator/client.py.

Covers: PubTatorClient, rate limiting, find_entity, search_by_entity,
        resolve_entity, find_relations, get_annotations, singleton.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pubmed_search.infrastructure.pubtator.client import (
    PubTatorClient,
    PubTator3Error,
    get_pubtator_client,
    close_pubtator_client,
)
from pubmed_search.infrastructure.pubtator.models import (
    EntityMatch,
    PubTatorEntity,
    RelationMatch,
)


@pytest.fixture
def client():
    return PubTatorClient(timeout=5.0, rate_limit=100.0)


# ============================================================
# PubTatorClient init
# ============================================================


class TestPubTatorClientInit:
    def test_default_values(self):
        c = PubTatorClient()
        assert c._timeout == PubTatorClient.DEFAULT_TIMEOUT
        assert c._rate_limit == PubTatorClient.DEFAULT_RATE_LIMIT
        assert c._client is None

    def test_custom_values(self):
        c = PubTatorClient(timeout=30.0, rate_limit=5.0)
        assert c._timeout == 30.0
        assert c._rate_limit == 5.0


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
# _rate_limit_wait
# ============================================================


class TestRateLimitWait:
    @pytest.mark.asyncio
    async def test_no_wait_first_call(self, client):
        client._rate_limit = 100.0
        await client._rate_limit_wait()  # should not block significantly


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

        client._client = mock_http
        result = await client._request("test/endpoint", {"key": "val"})
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_rate_limit_429(self, client):
        """429 triggers retry."""
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.raise_for_status = MagicMock()
        mock_resp_ok.json.return_value = {"ok": True}

        mock_http = AsyncMock()
        mock_http.get.side_effect = [mock_resp_429, mock_resp_ok]
        mock_http.is_closed = False

        client._client = mock_http
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("test")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_timeout_retries(self, client):
        """Timeout triggers retry, returns None if all fail."""
        import httpx

        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.TimeoutException("timeout")
        mock_http.is_closed = False

        client._client = mock_http
        result = await client._request("test")
        assert result is None
        assert mock_http.get.call_count == client.MAX_RETRIES

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

        client._client = mock_http
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_client_error_raises(self, client):
        """4xx (not 429) raises PubTator3Error."""
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        error = httpx.HTTPStatusError("400", request=MagicMock(), response=mock_resp)
        mock_resp.raise_for_status.side_effect = error

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_resp
        mock_http.is_closed = False

        client._client = mock_http
        with pytest.raises(PubTator3Error):
            await client._request("test")

    @pytest.mark.asyncio
    async def test_unexpected_error(self, client):
        mock_http = AsyncMock()
        mock_http.get.side_effect = ValueError("unexpected")
        mock_http.is_closed = False

        client._client = mock_http
        result = await client._request("test")
        assert result is None


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
            rels = await client.find_relations(
                "@CHEMICAL_Propofol", relation_type="treat", target_type="disease"
            )
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
                    {"type": "chemicals", "text": "Propofol", "identifier": "C12345"},
                    {"type": "genes", "text": "BRCA1", "identifier": "672"},
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
# Singleton
# ============================================================


class TestSingleton:
    def test_get_pubtator_client(self):
        import pubmed_search.infrastructure.pubtator.client as mod

        mod._client_instance = None
        c1 = get_pubtator_client()
        c2 = get_pubtator_client()
        assert c1 is c2
        mod._client_instance = None

    @pytest.mark.asyncio
    async def test_close_pubtator_client(self):
        import pubmed_search.infrastructure.pubtator.client as mod

        mod._client_instance = None
        _ = get_pubtator_client()
        await close_pubtator_client()
        assert mod._client_instance is None

    @pytest.mark.asyncio
    async def test_close_when_none(self):
        import pubmed_search.infrastructure.pubtator.client as mod

        mod._client_instance = None
        await close_pubtator_client()
        assert mod._client_instance is None
