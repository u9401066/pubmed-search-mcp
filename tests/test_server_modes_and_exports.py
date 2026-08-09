"""Security regression tests for local/service modes and export artifacts."""

from __future__ import annotations

import json
import socket
import sys
import time
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types.version import LATEST_MODERN_VERSION
from mcp_types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY
from starlette.applications import Starlette

from pubmed_search.application.export import (
    resolve_export_artifact,
    tenant_export_root,
    write_export_artifact,
)
from pubmed_search.application.session.registry import SessionManagerRegistry
from pubmed_search.infrastructure.auth import StaticTokenVerifier, parse_static_tokens
from pubmed_search.presentation.mcp_server import http_cli as http_cli_module
from pubmed_search.presentation.mcp_server.http_cli import _mount_auxiliary_routes, build_parser
from pubmed_search.presentation.mcp_server.http_security import AuxiliaryApiGuard
from pubmed_search.presentation.mcp_server.server import build_asgi_app, create_server, get_transport_options
from pubmed_search.presentation.mcp_server.tools._common import (
    get_session_registry,
    set_session_manager,
    set_session_registry,
)
from pubmed_search.presentation.mcp_server.tools.export import _format_export_response
from pubmed_search.shared.settings import AppSettings, load_settings
from pubmed_search.shared.tenancy import (
    ANONYMOUS_HTTP_TENANT,
    DEFAULT_TENANT,
    DEFAULT_TENANT_ID,
    LOCAL_HTTP_TENANT,
    TenantIdentity,
    bind_tenant,
)


def _clear_service_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PUBMED_AUTH_TOKENS",
        "PUBMED_AUTH_RESOURCE_SERVER_URL",
        "PUBMED_AUTH_ISSUER_URL",
        "PUBMED_ALLOWED_HOSTS",
        "PUBMED_ALLOWED_ORIGINS",
        "PUBMED_TENANT_ISOLATION",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _isolate_session_routing_globals():
    """Keep create_server tests from leaking their registry into later modules."""
    set_session_manager(None)
    set_session_registry(None)
    yield
    set_session_manager(None)
    set_session_registry(None)


def _configure_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PUBMED_AUTH_TOKENS", "team-a:tok-a,team-b:tok-b")
    monkeypatch.setenv("PUBMED_AUTH_RESOURCE_SERVER_URL", "https://mcp.example.test/mcp")
    monkeypatch.setenv("PUBMED_ALLOWED_HOSTS", "mcp.example.test")
    monkeypatch.setenv("PUBMED_ALLOWED_ORIGINS", "https://mcp.example.test")
    monkeypatch.setenv("PUBMED_TENANT_ISOLATION", "true")
    monkeypatch.setenv("PUBMED_DATA_DIR", str(tmp_path))


def _modern_tools_list_request() -> tuple[dict[str, object], dict[str, str]]:
    request: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {
            "_meta": {
                PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
                CLIENT_CAPABILITIES_META_KEY: {},
            }
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_MODERN_VERSION,
        "MCP-Method": "tools/list",
    }
    return request, headers


def _local_transport_security() -> TransportSecuritySettings:
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"],
        allowed_origins=["http://localhost", "http://localhost:*", "http://127.0.0.1", "http://127.0.0.1:*"],
    )


class TestServerModes:
    def test_http_cli_defaults_to_local_without_an_any_interface_bind(self, monkeypatch):
        monkeypatch.delenv("PUBMED_SERVER_MODE", raising=False)
        monkeypatch.delenv("MCP_HOST", raising=False)

        args = build_parser().parse_args([])

        assert args.mode == "local"
        assert args.host is None

    def test_service_mode_requires_tokens(self, monkeypatch, tmp_path):
        _clear_service_env(monkeypatch)

        with pytest.raises(RuntimeError, match="PUBMED_AUTH_TOKENS"):
            create_server(mode="service", data_dir=str(tmp_path))

    def test_service_mode_requires_resource_server_url(self, monkeypatch, tmp_path):
        _clear_service_env(monkeypatch)
        monkeypatch.setenv("PUBMED_AUTH_TOKENS", "team-a:tok-a")

        with pytest.raises(RuntimeError, match="PUBMED_AUTH_RESOURCE_SERVER_URL"):
            create_server(mode="service", data_dir=str(tmp_path))

    def test_service_mode_requires_explicit_host_and_origin_allowlists(self, monkeypatch, tmp_path):
        _clear_service_env(monkeypatch)
        monkeypatch.setenv("PUBMED_AUTH_TOKENS", "team-a:tok-a")
        monkeypatch.setenv("PUBMED_AUTH_RESOURCE_SERVER_URL", "https://mcp.example.test/mcp")

        with pytest.raises(RuntimeError, match=r"PUBMED_ALLOWED_HOSTS.*PUBMED_ALLOWED_ORIGINS"):
            create_server(mode="service", data_dir=str(tmp_path))

    def test_service_mode_forbids_disabling_transport_security(self, monkeypatch, tmp_path):
        _configure_service(monkeypatch, tmp_path)

        with pytest.raises(RuntimeError, match="forbids --no-security"):
            create_server(mode="service", data_dir=str(tmp_path), disable_security=True)

    def test_service_mode_uses_public_middleware_and_explicit_allowlists(self, monkeypatch, tmp_path):
        _configure_service(monkeypatch, tmp_path)

        server = create_server(mode="service", data_dir=str(tmp_path))
        options = get_transport_options(server)

        assert options.mode == "service"
        assert options.transport_security is not None
        assert options.transport_security.allowed_hosts == ["mcp.example.test"]
        assert options.transport_security.allowed_origins == ["https://mcp.example.test"]
        assert any(getattr(item, "__name__", "") == "tenancy_middleware" for item in server.middleware)

    def test_local_mode_rejects_remote_bind_without_explicit_container_opt_in(self, tmp_path):
        server = create_server(mode="local", data_dir=str(tmp_path))

        with pytest.raises(RuntimeError, match="only binds loopback"):
            build_asgi_app(server, host="0.0.0.0")  # noqa: S104

    def test_local_container_bind_requires_explicit_opt_in(self, tmp_path):
        server = create_server(mode="local", data_dir=str(tmp_path), allow_container_bind=True)

        app = build_asgi_app(server, host="0.0.0.0")  # noqa: S104

        assert app is not None

    def test_local_registry_reuses_container_default_session_manager(self, monkeypatch, tmp_path):
        from pubmed_search.presentation.mcp_server import server as server_module

        _clear_service_env(monkeypatch)
        create_server(mode="local", data_dir=str(tmp_path))

        registry = get_session_registry()
        assert registry is not None
        assert registry.for_tenant(DEFAULT_TENANT_ID) is server_module.get_container().session_manager()

    def test_disabling_caller_isolation_does_not_restore_anonymous_disk_state(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PUBMED_TENANT_ISOLATION", "false")

        create_server(mode="local", data_dir=str(tmp_path))

        registry = get_session_registry()
        assert registry is not None
        with bind_tenant(ANONYMOUS_HTTP_TENANT), registry.bind_request(ANONYMOUS_HTTP_TENANT):
            assert registry.for_tenant().data_dir is None
        assert registry.known_tenants() == []

    async def test_local_http_transport_enforces_host_and_origin_allowlists(self, tmp_path):
        server = create_server(mode="local", data_dir=str(tmp_path), json_response=True)
        app = build_asgi_app(server, host="127.0.0.1")
        request, headers = _modern_tools_list_request()

        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
                bad_host = await client.post("/mcp", json=request, headers={**headers, "Host": "evil.example"})
                bad_origin = await client.post(
                    "/mcp",
                    json=request,
                    headers={**headers, "Origin": "https://evil.example"},
                )
                allowed = await client.post("/mcp", json=request, headers=headers)

        assert bad_host.status_code == 421
        assert bad_origin.status_code == 403
        assert allowed.status_code == 200
        assert allowed.json()["result"]["tools"]

    async def test_service_http_transport_rejects_anonymous_mcp_requests(self, monkeypatch, tmp_path):
        _configure_service(monkeypatch, tmp_path)
        server = create_server(mode="service", data_dir=str(tmp_path), json_response=True)
        app = build_asgi_app(server, host="0.0.0.0")  # noqa: S104
        request, headers = _modern_tools_list_request()

        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="https://mcp.example.test") as client:
                anonymous = await client.post("/mcp", json=request, headers=headers)
                authenticated = await client.post(
                    "/mcp",
                    json=request,
                    headers={**headers, "Authorization": "Bearer tok-a"},
                )

        assert anonymous.status_code == 401
        assert authenticated.status_code == 200
        assert authenticated.json()["result"]["tools"]

    async def test_service_metadata_derives_reachable_issuer_from_resource_origin(self, monkeypatch, tmp_path):
        _configure_service(monkeypatch, tmp_path)
        server = create_server(mode="service", data_dir=str(tmp_path), json_response=True)
        app = build_asgi_app(server, host="0.0.0.0")  # noqa: S104

        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="https://mcp.example.test") as client:
                response = await client.get("/.well-known/oauth-protected-resource/mcp")

        assert response.status_code == 200
        assert response.json()["authorization_servers"] == ["https://mcp.example.test/"]


class TestTenantExportArtifacts:
    def test_authenticated_large_export_uses_tenant_root_without_exposing_path(self, tmp_path):
        identity = TenantIdentity.for_principal("team-a", source="auth")
        registry = SessionManagerRegistry(tmp_path)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.get_session_registry",
            return_value=registry,
        ):
            with bind_tenant(identity):
                payload = json.loads(_format_export_response("content", "ris", 25))

        export_root = tenant_export_root(tmp_path, identity)
        assert export_root is not None
        assert payload["export_id"]
        assert "file_path" not in payload
        assert (export_root / payload["export_id"]).read_text(encoding="utf-8") == "content"

    def test_installed_registry_root_wins_over_environment_for_authenticated_export(self, tmp_path, monkeypatch):
        identity = TenantIdentity.for_principal("team-a", source="auth")
        installed_root = tmp_path / "installed"
        environment_root = tmp_path / "environment"
        registry = SessionManagerRegistry(installed_root)
        monkeypatch.setenv("PUBMED_DATA_DIR", str(environment_root))

        with (
            patch("pubmed_search.presentation.mcp_server.tools.export.get_session_registry", return_value=registry),
            bind_tenant(identity),
        ):
            payload = json.loads(_format_export_response("content", "ris", 25))

        export_root = tenant_export_root(installed_root, identity)
        assert export_root is not None
        assert (export_root / payload["export_id"]).read_text(encoding="utf-8") == "content"
        assert not environment_root.exists()

    def test_anonymous_large_export_is_inline_and_never_touches_disk(self, tmp_path):
        with (
            patch("pubmed_search.presentation.mcp_server.tools.export.EXPORT_DIR", tmp_path),
            bind_tenant(ANONYMOUS_HTTP_TENANT),
        ):
            payload = json.loads(_format_export_response("content", "ris", 25))

        assert payload["export_text"] == "content"
        assert "export_id" not in payload
        assert list(tmp_path.iterdir()) == []

    def test_local_stdio_large_export_remains_a_local_file(self, tmp_path):
        with (
            patch("pubmed_search.presentation.mcp_server.tools.export.EXPORT_DIR", tmp_path),
            bind_tenant(DEFAULT_TENANT),
        ):
            payload = json.loads(_format_export_response("content", "ris", 25))

        assert Path(payload["file_path"]).is_file()

    def test_resolver_rejects_traversal_absolute_paths_and_unknown_names(self, tmp_path):
        root = tmp_path / "exports"
        root.mkdir()

        assert resolve_export_artifact(root, "../secret.ris") is None
        assert resolve_export_artifact(root, r"C:\Windows\secret.ris") is None
        assert resolve_export_artifact(root, "not-an-opaque-id.ris") is None

    def test_resolver_rejects_symlink_escape_when_supported(self, tmp_path):
        root = tmp_path / "exports"
        root.mkdir()
        outside = tmp_path / "outside.ris"
        outside.write_text("secret", encoding="utf-8")
        link = root / f"{'a' * 32}.ris"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation is unavailable on this Windows host")

        assert resolve_export_artifact(root, link.name) is None


class TestExportHttpRoutes:
    async def test_local_http_export_roundtrip_uses_opaque_id(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path)
        guard = AuxiliaryApiGuard(verifier=None, registry=registry, mode="local")

        with (
            patch("pubmed_search.presentation.mcp_server.tools.export.get_session_registry", return_value=registry),
            bind_tenant(LOCAL_HTTP_TENANT),
        ):
            payload = json.loads(_format_export_response("local-content", "ris", 25))

        assert payload["export_id"]
        assert "file_path" not in payload

        app = Starlette()
        _mount_auxiliary_routes(
            app,
            transport="streamable-http",
            port=8765,
            data_dir=str(tmp_path),
            transport_security=_local_transport_security(),
            guard=guard,
            searcher=AsyncMock(),
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
            listed = await client.get("/exports")
            downloaded = await client.get(f"/download/{payload['export_id']}")

        assert listed.status_code == 200
        assert listed.json()["files"][0]["export_id"] == payload["export_id"]
        assert downloaded.status_code == 200
        assert downloaded.text == "local-content"

    async def test_auxiliary_routes_enforce_host_and_origin_on_the_entire_app(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path)
        app = Starlette()
        _mount_auxiliary_routes(
            app,
            transport="streamable-http",
            port=8765,
            data_dir=str(tmp_path),
            transport_security=_local_transport_security(),
            guard=AuxiliaryApiGuard(verifier=None, registry=registry, mode="local"),
            searcher=AsyncMock(),
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
            for path in ("/api/session/summary", "/exports", "/info"):
                evil_host = await client.get(path, headers={"Host": "evil.example"})
                evil_origin = await client.get(path, headers={"Origin": "https://evil.example"})

                assert evil_host.status_code == 421
                assert evil_origin.status_code == 403

            assert (await client.get("/info")).status_code == 200

    async def test_exports_require_auth_and_are_tenant_scoped(self, tmp_path):
        verifier = StaticTokenVerifier(parse_static_tokens("team-a:tok-a,team-b:tok-b"))
        registry = SessionManagerRegistry(tmp_path)
        guard = AuxiliaryApiGuard(verifier=verifier, registry=registry, mode="service", require_auth=True)
        identity_a = TenantIdentity.for_principal("team-a", source="auth")
        root_a = tenant_export_root(tmp_path, identity_a)
        assert root_a is not None
        export_id, _path = write_export_artifact("tenant-a", extension="ris", root=root_a)

        app = Starlette()
        _mount_auxiliary_routes(
            app,
            transport="streamable-http",
            port=8765,
            data_dir=str(tmp_path),
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["testserver"],
                allowed_origins=["https://testserver"],
            ),
            guard=guard,
            searcher=AsyncMock(),
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            anonymous = await client.get("/exports")
            list_a = await client.get("/exports", headers={"Authorization": "Bearer tok-a"})
            download_a = await client.get(f"/download/{export_id}", headers={"Authorization": "Bearer tok-a"})
            download_b = await client.get(f"/download/{export_id}", headers={"Authorization": "Bearer tok-b"})

        assert anonymous.status_code == 401
        assert list_a.status_code == 200
        assert list_a.json()["files"][0]["export_id"] == export_id
        assert download_a.status_code == 200
        assert download_a.text == "tenant-a"
        assert download_b.status_code == 404


def test_new_runtime_settings_are_normalized(monkeypatch):
    monkeypatch.setenv("PUBMED_SERVER_MODE", " SERVICE ")
    monkeypatch.setenv("PUBMED_ALLOWED_HOSTS", "one.example, two.example ")
    monkeypatch.setenv("PUBMED_ALLOWED_ORIGINS", "https://one.example, https://two.example")
    monkeypatch.setenv("PUBMED_TRUSTED_PROXY_IPS", "127.0.0.1, 10.0.0.2")

    settings = load_settings()

    assert settings.server_mode == "service"
    assert settings.allowed_hosts == ("one.example", "two.example")
    assert settings.allowed_origins == ("https://one.example", "https://two.example")
    assert settings.trusted_proxy_ips == ("127.0.0.1", "10.0.0.2")


def test_http_cli_passes_loaded_data_dir_to_server_and_auxiliary_routes(monkeypatch, tmp_path):
    settings = AppSettings.model_validate(
        {
            "PUBMED_DATA_DIR": str(tmp_path),
            "NCBI_EMAIL": "test@example.com",
        }
    )
    server = MagicMock()
    app = Starlette()
    create = MagicMock(return_value=server)
    mount = MagicMock()

    monkeypatch.setattr(sys, "argv", ["pubmed-search-mcp-http"])
    monkeypatch.setattr(http_cli_module, "load_settings", lambda: settings)
    monkeypatch.setattr(http_cli_module, "create_server", create)
    monkeypatch.setattr(http_cli_module, "build_asgi_app", MagicMock(return_value=app))
    monkeypatch.setattr(http_cli_module, "get_container", lambda: SimpleNamespace(searcher=lambda: AsyncMock()))
    monkeypatch.setattr(http_cli_module, "build_auth", lambda _settings: (None, None))
    monkeypatch.setattr(http_cli_module, "get_session_registry", lambda: None)
    monkeypatch.setattr(
        http_cli_module,
        "get_transport_options",
        lambda _server: SimpleNamespace(transport_security=_local_transport_security()),
    )
    monkeypatch.setattr(http_cli_module, "_mount_auxiliary_routes", mount)
    monkeypatch.setattr("uvicorn.run", MagicMock())

    http_cli_module.main()

    assert create.call_args.kwargs["data_dir"] == str(tmp_path)
    assert mount.call_args.kwargs["data_dir"] == str(tmp_path)
    assert mount.call_args.kwargs["guard"].registry.data_dir == str(tmp_path)


def test_stdio_auxiliary_http_enforces_host_origin_and_safe_cors(tmp_path):
    from pubmed_search.presentation.mcp_server.server import start_http_api_background

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    session_manager = MagicMock(data_dir=str(tmp_path))
    session_manager.get_session_summary.return_value = {"searches": 1}
    start_http_api_background(session_manager, None, port=port)

    def _request(host: str, origin: str | None = None):
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        connection.putrequest("GET", "/api/session/summary", skip_host=True)
        connection.putheader("Host", host)
        if origin is not None:
            connection.putheader("Origin", origin)
        connection.endheaders()
        response = connection.getresponse()
        response.read()
        connection.close()
        return response

    deadline = time.monotonic() + 2
    while True:
        try:
            allowed = _request(f"localhost:{port}", f"http://localhost:{port}")
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)

    evil_host = _request("evil.example")
    evil_origin = _request(f"localhost:{port}", "https://evil.example")

    assert allowed.status == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == f"http://localhost:{port}"
    assert allowed.headers["Access-Control-Allow-Origin"] != "*"
    assert evil_host.status == 421
    assert evil_origin.status == 403


def test_stdio_main_does_not_start_auxiliary_http_by_default(monkeypatch, tmp_path):
    from pubmed_search.presentation.mcp_server import server as server_module

    settings = AppSettings.model_validate(
        {
            "PUBMED_DATA_DIR": str(tmp_path),
            "PUBMED_STDIO_AUX_HTTP": False,
            "NCBI_EMAIL": "test@example.com",
        }
    )
    mcp = MagicMock()
    monkeypatch.setattr(sys, "argv", ["pubmed-search-mcp"])
    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(server_module, "create_server", MagicMock(return_value=mcp))
    background = MagicMock()
    monkeypatch.setattr(server_module, "start_http_api_background", background)

    server_module.main()

    background.assert_not_called()
    mcp.run.assert_called_once_with()


def test_stdio_main_auxiliary_http_reuses_installed_default_manager(monkeypatch, tmp_path):
    from pubmed_search.presentation.mcp_server import server as server_module

    settings = AppSettings.model_validate(
        {
            "PUBMED_DATA_DIR": str(tmp_path),
            "PUBMED_STDIO_AUX_HTTP": True,
            "PUBMED_HTTP_API_PORT": 19001,
            "NCBI_EMAIL": "test@example.com",
        }
    )
    mcp = MagicMock()
    installed_manager = MagicMock(name="installed-manager")
    fallback_manager = MagicMock(name="container-manager")
    searcher = MagicMock(name="searcher")
    container = SimpleNamespace(session_manager=lambda: fallback_manager, searcher=lambda: searcher)
    background = MagicMock()

    monkeypatch.setattr(sys, "argv", ["pubmed-search-mcp"])
    monkeypatch.setattr(server_module, "load_settings", lambda: settings)
    monkeypatch.setattr(server_module, "create_server", MagicMock(return_value=mcp))
    monkeypatch.setattr(server_module, "get_container", lambda: container)
    monkeypatch.setattr(server_module, "get_session_manager", lambda: installed_manager)
    monkeypatch.setattr(server_module, "start_http_api_background", background)

    server_module.main()

    background.assert_called_once_with(installed_manager, searcher, port=19001)
    fallback_manager.assert_not_called()
    mcp.run.assert_called_once_with()


def test_local_https_builder_replays_recorded_transport_options(monkeypatch):
    from scripts import run_https_local

    server = MagicMock()
    app = Starlette()
    create = MagicMock(return_value=server)
    build = MagicMock(return_value=app)
    monkeypatch.setattr("pubmed_search.presentation.mcp_server.server.create_server", create)
    monkeypatch.setattr("pubmed_search.presentation.mcp_server.server.build_asgi_app", build)
    monkeypatch.setattr(
        "pubmed_search.presentation.mcp_server.http_compat.wrap_copilot_compatibility",
        lambda value: value,
    )

    result = run_https_local.create_https_app("test@example.com", None, host="127.0.0.1")

    assert result is app
    build.assert_called_once_with(server, "streamable-http", host="127.0.0.1")
    assert {route.path for route in result.routes} >= {"/health", "/ready", "/info"}
