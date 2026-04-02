"""Tests for HTTP compatibility helpers used by MCP launchers."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from pubmed_search.presentation.mcp_server.http_compat import wrap_copilot_compatibility


async def _accepted(_request):
    return Response(status_code=202)


async def _ok(_request):
    return JSONResponse({"ok": True})


class TestCopilotStudioCompatibilityMiddleware:
    async def test_converts_202_to_empty_json_200(self):
        app = Starlette(routes=[Route("/accepted", _accepted)])
        wrapped = wrap_copilot_compatibility(app)

        async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://testserver") as client:
            response = await client.get("/accepted")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {}

    async def test_leaves_non_202_responses_unchanged(self):
        app = Starlette(routes=[Route("/ok", _ok)])
        wrapped = wrap_copilot_compatibility(app)

        async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://testserver") as client:
            response = await client.get("/ok")

        assert response.status_code == 200
        assert response.json() == {"ok": True}
