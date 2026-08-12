"""Tests for multi-agent deployment: tenant isolation, auth, and fair-share limits."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from pubmed_search.application.session.manager import SessionManager
from pubmed_search.application.session.registry import TENANT_DIR_NAME, SessionManagerRegistry
from pubmed_search.infrastructure.auth import (
    StaticTokenVerifier,
    parse_static_tokens,
)
from pubmed_search.presentation.mcp_server.auth import DEFAULT_ISSUER_URL, build_auth
from pubmed_search.presentation.mcp_server.http_security import AuxiliaryApiGuard
from pubmed_search.presentation.mcp_server.tenancy import (
    build_tenancy_middleware,
    durable_storage_denied,
    resolve_tenant,
)
from pubmed_search.presentation.mcp_server.tools import _common
from pubmed_search.shared.async_utils import tenant_slot
from pubmed_search.shared.settings import AppSettings
from pubmed_search.shared.tenancy import (
    ANONYMOUS_HTTP_TENANT,
    DEFAULT_TENANT,
    DEFAULT_TENANT_ID,
    LOCAL_HTTP_TENANT,
    TenantIdentity,
    bind_tenant,
    current_tenant,
    current_tenant_id,
    normalize_tenant_id,
    tenant_data_dir,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def make_settings(**overrides: object) -> AppSettings:
    """Build settings from environment aliases without touching the real env."""
    return AppSettings.model_validate(overrides)


def fake_request_context(headers: dict[str, str] | None = None) -> SimpleNamespace:
    """Build a minimal stand-in for the low-level server request context."""
    request = SimpleNamespace(headers=headers) if headers is not None else None
    return SimpleNamespace(method="tools/call", request=request)


class FakeSessionManager:
    """Minimal session manager used to observe registry routing."""

    def __init__(self, data_dir: str | None) -> None:
        self.data_dir = data_dir
        self.records: list[tuple[str, list[str]]] = []

    def add_search_record(self, query: str, pmids: list[str]) -> None:
        self.records.append((query, pmids))


# ── shared.tenancy ──────────────────────────────────────────────────────────


class TestTenantIdentity:
    """Tenant normalization and context binding."""

    def test_blank_values_map_to_default(self):
        assert normalize_tenant_id(None) == DEFAULT_TENANT_ID
        assert normalize_tenant_id("") == DEFAULT_TENANT_ID
        assert normalize_tenant_id("   ") == DEFAULT_TENANT_ID
        assert normalize_tenant_id("default") == DEFAULT_TENANT_ID

    def test_normalization_is_deterministic(self):
        assert normalize_tenant_id("agent-alpha") == normalize_tenant_id("agent-alpha")

    def test_normalization_is_idempotent(self):
        once = normalize_tenant_id("agent-alpha")
        assert normalize_tenant_id(once) == once

    def test_raw_principal_cannot_forge_an_already_normalized_id(self, tmp_path):
        first = TenantIdentity.for_principal("a", source="auth")
        forged_text = str(first.tenant_id)
        forged = TenantIdentity.for_principal(forged_text, source="auth")
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)
        first_manager = registry.for_tenant(first.tenant_id)
        forged_manager = registry.for_tenant(forged.tenant_id)

        assert forged.tenant_id != first.tenant_id
        assert forged_manager is not first_manager
        assert forged_manager.data_dir != first_manager.data_dir

    @pytest.mark.parametrize("principal", [DEFAULT_TENANT_ID, "", "   "])
    def test_authenticated_principal_cannot_enter_local_default_tenant(self, tmp_path, principal):
        identity = TenantIdentity.for_principal(principal, source="auth")
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)

        assert identity.tenant_id != DEFAULT_TENANT_ID
        assert identity.is_default is False
        assert registry.for_tenant(identity.tenant_id) is not registry.for_tenant(DEFAULT_TENANT_ID)

    def test_distinct_principals_never_collide_after_sanitization(self):
        # Both sanitize to the same slug, so only the digest keeps them apart.
        assert normalize_tenant_id("team/a") != normalize_tenant_id("team:a")

    def test_path_traversal_characters_are_stripped(self):
        tenant_id = normalize_tenant_id("../../etc/passwd")
        assert "/" not in tenant_id
        assert ".." not in tenant_id

    def test_long_principals_are_truncated_but_unique(self):
        first = normalize_tenant_id("x" * 200 + "a")
        second = normalize_tenant_id("x" * 200 + "b")
        assert len(first) <= 60
        assert first != second

    def test_identity_flags(self):
        authenticated = TenantIdentity.for_principal("agent", source="auth")
        transport = TenantIdentity.for_principal("sess-1", source="transport")

        assert authenticated.is_authenticated is True
        assert authenticated.is_default is False
        assert transport.is_authenticated is False
        assert DEFAULT_TENANT.is_default is True

    def test_identity_serializes_for_logs(self):
        payload = TenantIdentity.for_principal("agent", source="auth").to_dict()
        assert payload["principal"] == "agent"
        assert payload["authenticated"] is True

    def test_bind_tenant_restores_previous_identity(self):
        assert current_tenant_id() == DEFAULT_TENANT_ID

        outer = TenantIdentity.for_principal("outer", source="auth")
        inner = TenantIdentity.for_principal("inner", source="auth")

        with bind_tenant(outer):
            assert current_tenant() == outer
            with bind_tenant(inner):
                assert current_tenant() == inner
            assert current_tenant() == outer

        assert current_tenant_id() == DEFAULT_TENANT_ID

    async def test_tenant_binding_does_not_leak_across_tasks(self):
        observed: list[str] = []

        async def observe() -> None:
            observed.append(current_tenant_id())

        with bind_tenant(TenantIdentity.for_principal("scoped", source="auth")):
            await asyncio.gather(observe())

        await asyncio.gather(observe())
        assert observed[0] != DEFAULT_TENANT_ID
        assert observed[1] == DEFAULT_TENANT_ID


# ── SessionManagerRegistry ──────────────────────────────────────────────────


class TestSessionManagerRegistry:
    """Per-tenant session manager pooling."""

    def test_default_tenant_keeps_the_shared_root(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)
        assert registry.tenant_data_dir(DEFAULT_TENANT_ID) == str(tmp_path)

    def test_other_tenants_get_isolated_directories(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)
        tenant_id = normalize_tenant_id("agent-a")
        assert registry.tenant_data_dir(tenant_id) == str(tmp_path / TENANT_DIR_NAME / tenant_id)

    def test_managers_are_memoized_per_tenant(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)

        first = registry.for_tenant("agent-a")
        again = registry.for_tenant("agent-a")
        other = registry.for_tenant("agent-b")

        assert first is again
        assert first is not other
        assert len(registry.known_tenants()) == 2

    def test_durable_context_manager_is_memoized_and_never_returns_none(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)

        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            first = registry.for_tenant()
            second = registry.for_tenant()

        assert first is second
        assert first is not None
        assert len(registry.known_tenants()) == 1

    def test_anonymous_request_manager_is_scoped_and_never_cached(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)

        with bind_tenant(ANONYMOUS_HTTP_TENANT), registry.bind_request(ANONYMOUS_HTTP_TENANT) as scoped:
            assert registry.for_tenant() is scoped
            assert registry.for_tenant() is scoped

        with bind_tenant(ANONYMOUS_HTTP_TENANT), registry.bind_request(ANONYMOUS_HTTP_TENANT) as next_scope:
            assert next_scope is not scoped

        assert registry.known_tenants() == []
        assert not (tmp_path / TENANT_DIR_NAME).exists()

    def test_resolves_from_bound_context_when_no_argument(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)

        with bind_tenant(TenantIdentity.for_principal("ctx-agent", source="auth")):
            manager = registry.for_tenant()

        assert manager is registry.for_tenant("ctx-agent")

    def test_supports_persistence_free_mode(self):
        registry = SessionManagerRegistry(None, factory=FakeSessionManager)
        assert registry.tenant_data_dir("anything") is None
        assert registry.for_tenant("anything").data_dir is None

    def test_stats_report_active_tenants(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)
        registry.for_tenant("agent-a")

        stats = registry.stats()
        assert stats["active_tenants"] == 1
        assert stats["data_dir"] == str(tmp_path)

    def test_default_manager_is_reused_without_invoking_factory(self, tmp_path):
        default_manager = SessionManager(data_dir=str(tmp_path))
        factory_calls: list[str | None] = []

        def factory(path: str | None) -> SessionManager:
            factory_calls.append(path)
            return SessionManager(data_dir=path)

        registry = SessionManagerRegistry(
            tmp_path,
            factory=factory,
            default_manager=default_manager,
        )

        assert registry.for_tenant(DEFAULT_TENANT_ID) is default_manager
        assert registry.for_tenant(DEFAULT_TENANT_ID) is default_manager
        assert factory_calls == []

    def test_concurrent_factory_and_stats_snapshots_are_consistent(self, tmp_path):
        factory_calls = 0
        factory_lock = threading.Lock()
        registry_ref: SessionManagerRegistry | None = None

        def factory(path: str | None) -> SessionManager:
            nonlocal factory_calls
            with factory_lock:
                factory_calls += 1
            assert registry_ref is not None
            snapshot = registry_ref.stats()
            tenants = snapshot["tenants"]
            assert isinstance(tenants, list)
            assert snapshot["active_tenants"] == len(tenants)
            return SessionManager(data_dir=path)

        registry = SessionManagerRegistry(tmp_path, factory=factory)
        registry_ref = registry

        with ThreadPoolExecutor(max_workers=16) as executor:
            managers = list(executor.map(lambda _index: registry.for_tenant("shared-agent"), range(64)))

        assert all(manager is managers[0] for manager in managers)
        assert factory_calls == 1
        snapshot = registry.stats()
        tenants = snapshot["tenants"]
        assert isinstance(tenants, list)
        assert snapshot["active_tenants"] == 1
        assert snapshot["active_tenants"] == len(tenants)


# ── Tenant-routed session access ────────────────────────────────────────────


class TestTenantScopedSessionAccess:
    """`get_session_manager()` must follow the bound tenant."""

    @pytest.fixture(autouse=True)
    def _restore_registry(self):
        previous_registry = _common.get_session_registry()
        previous_manager = _common.get_session_manager()
        yield
        _common.set_session_manager(previous_manager)
        _common.set_session_registry(previous_registry)

    def test_two_agents_do_not_share_a_session_manager(self, tmp_path):
        _common.set_session_registry(SessionManagerRegistry(tmp_path, factory=FakeSessionManager))

        with bind_tenant(TenantIdentity.for_principal("alpha", source="auth")):
            alpha = _common.get_session_manager()
            alpha.add_search_record("alpha query", ["111"])

        with bind_tenant(TenantIdentity.for_principal("beta", source="auth")):
            beta = _common.get_session_manager()

        assert alpha is not beta
        assert beta.records == []
        assert alpha.records == [("alpha query", ["111"])]

    def test_falls_back_to_the_shared_manager_without_a_registry(self):
        shared = FakeSessionManager("shared")
        _common.set_session_registry(None)
        _common.set_session_manager(shared)

        with bind_tenant(TenantIdentity.for_principal("alpha", source="auth")):
            assert _common.get_session_manager() is shared

    def test_installing_a_single_manager_disables_tenant_routing(self, tmp_path):
        _common.set_session_registry(SessionManagerRegistry(tmp_path, factory=FakeSessionManager))
        shared = FakeSessionManager("shared")

        _common.set_session_manager(shared)

        assert _common.get_session_registry() is None
        with bind_tenant(TenantIdentity.for_principal("alpha", source="auth")):
            assert _common.get_session_manager() is shared

    def test_session_resources_follow_the_bound_tenant(self, tmp_path):
        # Session tools/resources are registered once, so they must resolve the
        # manager at call time rather than capturing the startup instance.
        from pubmed_search.presentation.mcp_server.session_tools import _TenantScopedSessionManager

        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)
        proxy = _TenantScopedSessionManager(FakeSessionManager("startup"), registry)

        with bind_tenant(TenantIdentity.for_principal("alpha", source="auth")):
            proxy.add_search_record("alpha", ["1"])
        with bind_tenant(TenantIdentity.for_principal("beta", source="auth")):
            proxy.add_search_record("beta", ["2"])

        assert registry.for_tenant("alpha").records == [("alpha", ["1"])]
        assert registry.for_tenant("beta").records == [("beta", ["2"])]

    def test_proxy_falls_back_to_the_startup_manager(self):
        from pubmed_search.presentation.mcp_server.session_tools import _TenantScopedSessionManager

        _common.set_session_registry(None)
        _common.set_session_manager(None)
        fallback = FakeSessionManager("startup")

        _TenantScopedSessionManager(fallback).add_search_record("q", ["1"])
        assert fallback.records == [("q", ["1"])]

    def test_proxy_ignores_unrelated_global_registry(self, tmp_path):
        from pubmed_search.presentation.mcp_server.session_tools import _TenantScopedSessionManager

        unrelated = SessionManagerRegistry(tmp_path / "unrelated", factory=FakeSessionManager)
        fallback = FakeSessionManager("registered")
        _common.set_session_registry(unrelated)

        _TenantScopedSessionManager(fallback).add_search_record("q", ["1"])

        assert fallback.records == [("q", ["1"])]
        assert unrelated.known_tenants() == []


# ── Static token auth ───────────────────────────────────────────────────────


class TestStaticTokenAuth:
    """Pre-shared bearer token verification."""

    def test_parses_principal_token_pairs(self):
        principals = parse_static_tokens("team-a:secret-a, team-b:secret-b")
        assert [entry.principal for entry in principals] == ["team-a", "team-b"]

    def test_skips_malformed_entries(self):
        assert parse_static_tokens("no-separator, :missing-principal, team:  , ok:tok") != []
        assert [e.principal for e in parse_static_tokens("no-separator, ok:tok")] == ["ok"]

    def test_secrets_are_not_retained_in_plaintext(self):
        entry = parse_static_tokens("team-a:super-secret")[0]
        assert "super-secret" not in entry.token_digest
        assert len(entry.token_digest) == 64

    async def test_accepts_a_configured_token(self):
        verifier = StaticTokenVerifier(parse_static_tokens("team-a:secret-a"))

        token = await verifier.verify_token("secret-a")
        assert token is not None
        assert token.subject == "team-a"
        assert token.client_id == "team-a"

    async def test_rejects_unknown_and_empty_tokens(self):
        verifier = StaticTokenVerifier(parse_static_tokens("team-a:secret-a"))

        assert await verifier.verify_token("wrong") is None
        assert await verifier.verify_token("") is None

    async def test_empty_configuration_rejects_everything(self):
        verifier = StaticTokenVerifier([])
        assert len(verifier) == 0
        assert await verifier.verify_token("anything") is None

    def test_build_auth_is_disabled_without_tokens(self):
        verifier, settings = build_auth(make_settings())
        assert verifier is None
        assert settings is None

    def test_build_auth_enables_verifier_and_settings(self):
        verifier, auth_settings = build_auth(make_settings(PUBMED_AUTH_TOKENS="team-a:secret"))

        assert verifier is not None
        assert verifier.principal_names == ["team-a"]
        assert auth_settings is not None
        assert str(auth_settings.issuer_url).startswith(DEFAULT_ISSUER_URL)

    def test_build_auth_honors_configured_issuer(self):
        _verifier, auth_settings = build_auth(
            make_settings(PUBMED_AUTH_TOKENS="team-a:secret", PUBMED_AUTH_ISSUER_URL="https://mcp.example.com")
        )
        assert auth_settings is not None
        assert "mcp.example.com" in str(auth_settings.issuer_url)

    def test_build_auth_derives_issuer_from_public_resource_origin(self):
        _verifier, auth_settings = build_auth(
            make_settings(
                PUBMED_AUTH_TOKENS="team-a:secret",
                PUBMED_AUTH_RESOURCE_SERVER_URL="https://mcp.example.com:8443/mcp",
            )
        )

        assert auth_settings is not None
        assert str(auth_settings.issuer_url) == "https://mcp.example.com:8443/"


# ── Tenant resolution from a request ────────────────────────────────────────


class TestResolveTenant:
    """Identity precedence for one inbound request."""

    def test_falls_back_to_default_on_stdio(self):
        assert resolve_tenant(fake_request_context()) == DEFAULT_TENANT

    def test_uses_transport_session_when_unauthenticated(self):
        identity = resolve_tenant(fake_request_context({"mcp-session-id": "sess-123"}))

        assert identity.source == "transport"
        assert identity.principal == "sess-123"
        assert identity.is_authenticated is False

    def test_isolation_can_be_disabled(self):
        identity = resolve_tenant(
            fake_request_context({"mcp-session-id": "sess-123"}),
            isolation_enabled=False,
        )
        assert identity == ANONYMOUS_HTTP_TENANT

    def test_authenticated_principal_wins_over_transport(self, monkeypatch):
        monkeypatch.setattr(
            "pubmed_search.presentation.mcp_server.tenancy.get_access_token",
            lambda: SimpleNamespace(subject="team-a", client_id="team-a"),
        )
        identity = resolve_tenant(fake_request_context({"mcp-session-id": "sess-123"}))

        assert identity.source == "auth"
        assert identity.principal == "team-a"

    def test_tolerates_transports_without_headers(self):
        assert resolve_tenant(SimpleNamespace(method="ping", request=object())) == ANONYMOUS_HTTP_TENANT

    def test_modern_http_without_session_header_is_non_durable(self):
        identity = resolve_tenant(fake_request_context({}))

        assert identity == ANONYMOUS_HTTP_TENANT
        assert identity.source == "anonymous_http"
        assert identity.owns_durable_storage is False

    def test_trusted_local_http_maps_to_durable_default_tenant(self):
        identity = resolve_tenant(fake_request_context({}), trusted_local_http=True)

        assert identity == LOCAL_HTTP_TENANT
        assert identity.source == "local_http"
        assert identity.owns_durable_storage is True


class TestTenancyMiddleware:
    """The middleware binds the tenant for the wrapped handler."""

    async def test_binds_tenant_for_the_handler(self):
        middleware = build_tenancy_middleware()
        seen: list[str] = []

        async def call_next(_ctx: object) -> str:
            seen.append(current_tenant_id())
            return "ok"

        result = await middleware(fake_request_context({"mcp-session-id": "sess-9"}), call_next)

        assert result == "ok"
        assert seen[0] != DEFAULT_TENANT_ID
        assert current_tenant_id() == DEFAULT_TENANT_ID

    async def test_restores_tenant_after_a_handler_error(self):
        middleware = build_tenancy_middleware()

        async def call_next(_ctx: object) -> str:
            msg = "boom"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            await middleware(fake_request_context({"mcp-session-id": "sess-9"}), call_next)

        assert current_tenant_id() == DEFAULT_TENANT_ID

    async def test_anonymous_modern_http_gets_one_fresh_manager_per_request(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)
        middleware = build_tenancy_middleware(registry=registry)
        seen: list[object] = []

        async def call_next(_ctx: object) -> str:
            first = registry.for_tenant()
            assert registry.for_tenant() is first
            seen.append(first)
            return "ok"

        await middleware(fake_request_context({}), call_next)
        await middleware(fake_request_context({}), call_next)

        assert seen[0] is not seen[1]
        assert registry.known_tenants() == []

    async def test_trusted_local_http_reuses_durable_default_manager(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)
        middleware = build_tenancy_middleware(registry=registry, trusted_local_http=True)
        seen: list[object] = []

        async def call_next(_ctx: object) -> str:
            seen.append(registry.for_tenant())
            return "ok"

        await middleware(fake_request_context({}), call_next)
        await middleware(fake_request_context({}), call_next)

        assert seen[0] is seen[1]
        assert registry.known_tenants() == [DEFAULT_TENANT_ID]
        assert registry.for_tenant(DEFAULT_TENANT_ID).data_dir == str(tmp_path)


# ── Auxiliary HTTP API guard ────────────────────────────────────────────────


class TestAuxiliaryApiGuard:
    """Bearer guard for the read-only HTTP routes."""

    @staticmethod
    def _request(authorization: str | None = None) -> SimpleNamespace:
        headers = {"authorization": authorization} if authorization else {}
        return SimpleNamespace(headers=headers)

    async def test_local_deployment_allows_durable_default_tenant(self, tmp_path):
        guard = AuxiliaryApiGuard(
            verifier=None,
            registry=SessionManagerRegistry(tmp_path, factory=FakeSessionManager),
            mode="local",
        )

        outcome = await guard.authenticate(self._request())
        assert guard.enforcing is False
        assert outcome.allowed is True
        assert outcome.identity == LOCAL_HTTP_TENANT

    async def test_missing_token_is_rejected(self, tmp_path):
        guard = AuxiliaryApiGuard(
            verifier=StaticTokenVerifier(parse_static_tokens("team-a:secret")),
            registry=SessionManagerRegistry(tmp_path, factory=FakeSessionManager),
            mode="service",
        )

        outcome = await guard.authenticate(self._request())
        assert outcome.allowed is False
        assert outcome.status_code == 401

    async def test_invalid_token_is_rejected(self, tmp_path):
        guard = AuxiliaryApiGuard(
            verifier=StaticTokenVerifier(parse_static_tokens("team-a:secret")),
            registry=SessionManagerRegistry(tmp_path, factory=FakeSessionManager),
            mode="service",
        )

        outcome = await guard.authenticate(self._request("Bearer wrong"))
        assert outcome.allowed is False
        assert outcome.status_code == 403

    async def test_valid_token_resolves_the_caller_tenant(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)
        guard = AuxiliaryApiGuard(
            verifier=StaticTokenVerifier(parse_static_tokens("team-a:secret")),
            registry=registry,
            mode="service",
        )

        outcome = await guard.authenticate(self._request("Bearer secret"))

        assert outcome.allowed is True
        assert outcome.identity is not None
        assert outcome.identity.principal == "team-a"
        assert guard.session_manager_for(outcome.identity) is registry.for_tenant("team-a")

    async def test_fails_closed_when_auth_required_but_unconfigured(self, tmp_path):
        guard = AuxiliaryApiGuard(
            verifier=None,
            registry=SessionManagerRegistry(tmp_path, factory=FakeSessionManager),
            mode="service",
            require_auth=True,
        )

        outcome = await guard.authenticate(self._request("Bearer anything"))
        assert outcome.allowed is False
        assert outcome.status_code == 503
        assert guard.enforcing is True

    async def test_two_tokens_get_separate_session_managers(self, tmp_path):
        registry = SessionManagerRegistry(tmp_path, factory=FakeSessionManager)
        guard = AuxiliaryApiGuard(
            verifier=StaticTokenVerifier(parse_static_tokens("team-a:tok-a,team-b:tok-b")),
            registry=registry,
            mode="service",
        )

        first = await guard.authenticate(self._request("Bearer tok-a"))
        second = await guard.authenticate(self._request("Bearer tok-b"))

        assert first.identity is not None
        assert second.identity is not None
        assert guard.session_manager_for(first.identity) is not guard.session_manager_for(second.identity)

    async def test_service_mode_fails_closed_even_without_require_auth_flag(self, tmp_path):
        guard = AuxiliaryApiGuard(
            verifier=None,
            registry=SessionManagerRegistry(tmp_path, factory=FakeSessionManager),
            mode="service",
        )

        outcome = await guard.authenticate(self._request())

        assert guard.enforcing is True
        assert outcome.allowed is False
        assert outcome.status_code == 503


# ── Per-tenant fair share ───────────────────────────────────────────────────


class TestTenantFairShare:
    """One tenant must not consume the whole concurrency budget."""

    async def test_concurrency_is_capped_per_tenant(self):
        in_flight = 0
        peak = 0

        async def work() -> None:
            nonlocal in_flight, peak
            async with tenant_slot(2, "busy-agent"):
                in_flight += 1
                peak = max(peak, in_flight)
                await asyncio.sleep(0.01)
                in_flight -= 1

        await asyncio.gather(*(work() for _ in range(6)))
        assert peak <= 2

    async def test_separate_tenants_do_not_block_each_other(self):
        order: list[str] = []

        async def hold() -> None:
            async with tenant_slot(1, "holder"):
                await asyncio.sleep(0.05)
                order.append("holder")

        async def other() -> None:
            async with tenant_slot(1, "other"):
                order.append("other")

        await asyncio.gather(hold(), other())
        assert order[0] == "other"

    async def test_non_positive_limit_disables_the_cap(self):
        async with tenant_slot(0, "unlimited") as tenant_id:
            assert tenant_id == "unlimited"

    async def test_defaults_to_the_bound_tenant(self):
        with bind_tenant(TenantIdentity.for_principal("bound", source="auth")):
            async with tenant_slot(1) as tenant_id:
                assert tenant_id == current_tenant_id()


class TestTenantDataDir:
    """The single rule every persistent store must route through."""

    def test_default_tenant_keeps_the_shared_root(self):
        assert tenant_data_dir("/data") == "/data"

    def test_other_tenants_get_an_isolated_subdirectory(self):
        root = Path("data")
        scoped = tenant_data_dir(root, "agent-a")
        assert scoped is not None
        assert Path(scoped).parent.name == TENANT_DIR_NAME
        assert Path(scoped) != root

    def test_distinct_tenants_never_share_a_directory(self):
        assert tenant_data_dir("/data", "agent-a") != tenant_data_dir("/data", "agent-b")

    def test_follows_the_bound_tenant_when_no_id_is_given(self):
        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            assert tenant_data_dir("/data") == tenant_data_dir("/data", "agent-a")

    def test_returns_none_without_persistence(self):
        assert tenant_data_dir(None, "agent-a") is None


class TestChronicleStoreIsolation:
    """Chronicles are per-agent research artifacts and must not be shared."""

    @pytest.fixture(autouse=True)
    def _restore_registry(self):
        previous_registry = _common.get_session_registry()
        previous_manager = _common.get_session_manager()
        yield
        _common.set_session_manager(previous_manager)
        _common.set_session_registry(previous_registry)

    def test_store_root_follows_the_current_tenant(self, tmp_path):
        from pubmed_search.presentation.mcp_server.tools import chronicle

        _common.set_session_registry(SessionManagerRegistry(tmp_path, factory=FakeSessionManager))

        default_root = chronicle._chronicle_store().root_dir
        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            agent_a_root = chronicle._chronicle_store().root_dir
        with bind_tenant(TenantIdentity.for_principal("agent-b", source="auth")):
            agent_b_root = chronicle._chronicle_store().root_dir

        assert len({default_root, agent_a_root, agent_b_root}) == 3

    def test_a_chronicle_saved_by_one_agent_is_invisible_to_another(self, tmp_path):
        from pubmed_search.domain.entities.chronicle import ChronicleSnapshot
        from pubmed_search.presentation.mcp_server.tools import chronicle

        _common.set_session_registry(SessionManagerRegistry(tmp_path, factory=FakeSessionManager))
        snapshot = ChronicleSnapshot(chronicle_id="shared-topic", topic="shared topic")

        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            chronicle._chronicle_store().save(snapshot)
            assert [r["chronicle_id"] for r in chronicle._chronicle_store().list_chronicles()] == ["shared-topic"]

        with bind_tenant(TenantIdentity.for_principal("agent-b", source="auth")):
            assert chronicle._chronicle_store().list_chronicles() == []
            assert chronicle._chronicle_store().load("shared-topic") is None


class TestPipelineStoreIsolation:
    """Saved pipelines belong to the agent that created them."""

    @pytest.fixture(autouse=True)
    def _reset_store(self):
        from pubmed_search.presentation.mcp_server.tools import pipeline_tools

        yield
        pipeline_tools.set_pipeline_store(None)

    def test_default_tenant_gets_the_registered_store(self, tmp_path):
        from pubmed_search.application.pipeline.store import PipelineStore
        from pubmed_search.presentation.mcp_server.tools import pipeline_tools

        base = PipelineStore(global_data_dir=str(tmp_path))
        pipeline_tools.set_pipeline_store(base)

        assert pipeline_tools.get_pipeline_store() is base

    def test_other_tenants_get_a_derived_store(self, tmp_path):
        from pubmed_search.application.pipeline.store import PipelineStore
        from pubmed_search.presentation.mcp_server.tools import pipeline_tools

        base = PipelineStore(global_data_dir=str(tmp_path))
        pipeline_tools.set_pipeline_store(base)

        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            scoped = pipeline_tools.get_pipeline_store()

        assert scoped is not base
        assert scoped is not None
        assert scoped.global_data_dir != base.global_data_dir
        assert TENANT_DIR_NAME in scoped.global_data_dir.parts

    def test_the_derived_store_is_cached_per_tenant(self, tmp_path):
        from pubmed_search.application.pipeline.store import PipelineStore
        from pubmed_search.presentation.mcp_server.tools import pipeline_tools

        pipeline_tools.set_pipeline_store(PipelineStore(global_data_dir=str(tmp_path)))

        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            first = pipeline_tools.get_pipeline_store()
            second = pipeline_tools.get_pipeline_store()
        assert first is second

    def test_re_registering_a_store_drops_stale_tenant_stores(self, tmp_path):
        from pubmed_search.application.pipeline.store import PipelineStore
        from pubmed_search.presentation.mcp_server.tools import pipeline_tools

        pipeline_tools.set_pipeline_store(PipelineStore(global_data_dir=str(tmp_path / "one")))
        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            stale = pipeline_tools.get_pipeline_store()

        pipeline_tools.set_pipeline_store(PipelineStore(global_data_dir=str(tmp_path / "two")))
        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            fresh = pipeline_tools.get_pipeline_store()

        assert fresh is not stale
        assert stale is not None
        assert fresh is not None
        assert str(tmp_path / "two") in str(fresh.global_data_dir)

    def test_no_store_registered_returns_none(self):
        from pubmed_search.presentation.mcp_server.tools import pipeline_tools

        pipeline_tools.set_pipeline_store(None)
        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            assert pipeline_tools.get_pipeline_store() is None


class TestDurableStorageGuard:
    """A transport session id is neither stable nor authenticated."""

    def test_stdio_may_persist(self):
        assert DEFAULT_TENANT.owns_durable_storage is True

    def test_authenticated_principal_may_persist(self):
        assert TenantIdentity.for_principal("agent-a", source="auth").owns_durable_storage is True

    def test_operator_override_may_persist(self):
        assert TenantIdentity.for_principal("agent-a", source="explicit").owns_durable_storage is True

    def test_transport_session_may_not_persist(self):
        assert TenantIdentity.for_principal("sess-1", source="transport").owns_durable_storage is False

    def test_guard_allows_authenticated_callers(self):
        with bind_tenant(TenantIdentity.for_principal("agent-a", source="auth")):
            assert durable_storage_denied("build_research_chronicle") is None

    def test_guard_refuses_transport_derived_callers(self):
        with bind_tenant(TenantIdentity.for_principal("sess-1", source="transport")):
            message = durable_storage_denied("build_research_chronicle")

        assert message is not None
        assert "authenticated" in message.lower()
        assert "PUBMED_AUTH_TOKENS" in message

    def test_reported_in_diagnostics(self):
        payload = TenantIdentity.for_principal("sess-1", source="transport").to_dict()
        assert payload["owns_durable_storage"] is False


class TestEphemeralTenantsNeverTouchDisk:
    """A reconnect must not leave a directory nobody can ever reach again."""

    def test_repeated_reconnects_create_no_directories(self, tmp_path):
        registry = SessionManagerRegistry(str(tmp_path))

        for session_id in ("sess-a", "sess-b", "sess-c", "sess-d", "sess-e"):
            with bind_tenant(TenantIdentity.for_principal(session_id, source="transport")):
                assert registry.for_tenant().data_dir is None

        assert list((tmp_path / TENANT_DIR_NAME).glob("*")) == []

    def test_authenticated_tenant_still_persists(self, tmp_path):
        registry = SessionManagerRegistry(str(tmp_path))

        with bind_tenant(TenantIdentity.for_principal("team-a", source="auth")):
            assert registry.for_tenant().data_dir is not None

    def test_default_tenant_keeps_the_shared_root(self, tmp_path):
        registry = SessionManagerRegistry(str(tmp_path))

        assert str(registry.for_tenant().data_dir) == str(tmp_path)

    def test_storage_root_is_none_for_ephemeral_callers(self, tmp_path):
        with bind_tenant(TenantIdentity.for_principal("sess-a", source="transport")):
            assert tenant_data_dir(str(tmp_path)) is None

    def test_explicit_tenant_id_is_an_operator_decision(self, tmp_path):
        with bind_tenant(TenantIdentity.for_principal("sess-a", source="transport")):
            assert tenant_data_dir(str(tmp_path), "team-a") is not None

    def test_pipeline_store_is_withheld_from_ephemeral_callers(self, tmp_path):
        from pubmed_search.application.pipeline.store import PipelineStore
        from pubmed_search.presentation.mcp_server.tools import pipeline_tools

        pipeline_tools.set_pipeline_store(PipelineStore(global_data_dir=str(tmp_path)))
        try:
            with bind_tenant(TenantIdentity.for_principal("sess-a", source="transport")):
                assert pipeline_tools.get_pipeline_store() is None
        finally:
            pipeline_tools.set_pipeline_store(None)


class TestTenantIdBoundaries:
    """Tenant ids become directory names, so hostile input must be neutralized."""

    @pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
    def test_blank_input_falls_back_to_the_default_tenant(self, raw):
        assert normalize_tenant_id(raw) == DEFAULT_TENANT_ID

    @pytest.mark.parametrize("raw", ["../../etc/passwd", "..", "/", "a/b/c", "..\\..\\windows"])
    def test_path_separators_never_survive(self, raw):
        normalized = normalize_tenant_id(raw)
        assert "/" not in normalized
        assert "\\" not in normalized
        assert ".." not in normalized.replace(".", "", 1) or normalized.count("..") == 0

    def test_a_null_byte_cannot_reach_the_filesystem(self):
        assert "\x00" not in normalize_tenant_id("a\x00b")

    def test_very_long_input_is_bounded(self):
        assert len(normalize_tenant_id("A" * 500)) <= 60

    def test_non_ascii_input_still_yields_a_usable_id(self):
        normalized = normalize_tenant_id("研究")
        assert normalized
        assert normalized != DEFAULT_TENANT_ID

    @pytest.mark.parametrize("raw", ["agent-a", "../../etc", "A" * 500, "研究", "a\x00b"])
    def test_normalization_is_idempotent(self, raw):
        once = normalize_tenant_id(raw)
        assert normalize_tenant_id(once) == once

    def test_distinct_inputs_stay_distinct_after_slugging(self):
        assert normalize_tenant_id("team/a") != normalize_tenant_id("team/b")

    def test_a_hostile_id_cannot_escape_the_storage_root(self):
        root = Path("data").resolve()
        resolved = tenant_data_dir(root, "../../etc/passwd")
        assert resolved is not None
        assert Path(resolved).resolve().is_relative_to(root)
