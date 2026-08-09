"""Regression tests for MCP SDK v2 public facade usage."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_copilot
from scripts import count_mcp_tools

REPO_ROOT = Path(__file__).resolve().parents[1]


class _PublicServerStub:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def _tool_manager(self) -> object:
        raise AssertionError("private MCP internals must not be accessed")

    async def list_tools(self) -> list[SimpleNamespace]:
        self.calls += 1
        return [
            SimpleNamespace(
                name="example",
                description="Example tool\nLonger details",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ]


def test_count_script_uses_public_list_tools_and_input_schema() -> None:
    server = _PublicServerStub()

    assert count_mcp_tools.get_registered_tools(server) == ["example"]
    assert count_mcp_tools.get_tool_details(server)["example"]["parameters"] == ["query"]
    assert server.calls == 2


def test_copilot_tool_count_uses_public_async_facade() -> None:
    server = _PublicServerStub()

    assert asyncio.run(run_copilot._count_registered_tools(server)) == 1
    assert server.calls == 1


@pytest.mark.parametrize("host", ["127.0.0.1", "127.10.20.30", "::1", "[::1]", "localhost"])
def test_copilot_accepts_only_loopback_spellings(host: str) -> None:
    assert run_copilot._is_loopback_host(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.test"])  # noqa: S104
def test_copilot_rejects_remote_bind_before_server_creation(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setattr(sys, "argv", ["run_copilot.py", "--host", host])

    with pytest.raises(SystemExit, match="2"):
        run_copilot.main()


def test_copilot_transport_enables_loopback_rebinding_guards(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_copilot.Path, "home", lambda: tmp_path)
    server = run_copilot.create_copilot_server(email="smoke@example.com")
    security = server.copilot_transport_kwargs["transport_security"]

    assert security.enable_dns_rebinding_protection is True
    assert "127.0.0.1:*" in security.allowed_hosts
    assert "http://localhost:*" in security.allowed_origins


def test_manual_copilot_smoke_uses_modern_protocol_without_session_lifecycle() -> None:
    script = (REPO_ROOT / "scripts" / "test-copilot-mcp.py").read_text(encoding="utf-8")

    assert "LATEST_MODERN_VERSION" in script
    assert '"method": "initialize"' not in script
    assert "notifications/initialized" not in script
    assert 'headers["Mcp-Session-Id"]' not in script


def test_public_copilot_tunnel_forces_authenticated_service_mode() -> None:
    studio = (REPO_ROOT / "scripts" / "start-copilot-studio.sh").read_text(encoding="utf-8")
    custom_domain = (REPO_ROOT / "scripts" / "start-copilot-ngrok.sh").read_text(encoding="utf-8")
    setup = (REPO_ROOT / "scripts" / "setup-ngrok.sh").read_text(encoding="utf-8")

    assert "PUBMED_AUTH_TOKENS:?" in studio
    assert "NGROK_DOMAIN:?" in studio
    assert "--mode service" in studio
    assert "--host 127.0.0.1" in studio
    assert "Auth Type:  None" not in studio
    assert "run_copilot.py" not in studio
    assert 'ngrok http "$PORT"' not in studio

    backend_start = studio.index("uv run pubmed-search-mcp-http")
    readiness_check = studio.index('"$BACKEND_URL/ready"')
    auth_check = studio.index('"$BACKEND_URL/mcp"')
    tunnel_start = studio.index('ngrok http --url="$PUBLIC_HOST"')
    assert backend_start < readiness_check < auth_check < tunnel_start

    cleanup = studio[studio.index("cleanup() {") : studio.index("trap cleanup")]
    assert cleanup.index("$NGROK_PID") < cleanup.index("$SERVER_PID")
    assert 'wait "$NGROK_PID"' in cleanup
    assert 'wait "$SERVER_PID"' in cleanup
    assert 'while kill -0 "$SERVER_PID"' in studio
    assert 'kill -0 "$NGROK_PID"' in studio
    assert "ngrok exited; stopping the authenticated backend" in studio

    assert "NGROK_DOMAIN:?" in custom_domain
    assert "start-copilot-studio.sh" in custom_domain
    assert "run_copilot.py" not in custom_domain

    assert 'exec "$SCRIPT_DIR/start-copilot-studio.sh" --with-ngrok' in setup
    assert "Authentication:     None" not in setup


def test_local_https_script_binds_only_loopback() -> None:
    script = (REPO_ROOT / "scripts" / "start-https-local.sh").read_text(encoding="utf-8")

    assert "--host 127.0.0.1" in script
    assert "--host 0.0.0.0" not in script


def _usable_bash() -> str | None:
    """Return a real Bash executable, avoiding the Windows WSL app alias."""
    if os.name == "nt":
        candidates = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/usr/bin/bash.exe",
        )
        return next((str(candidate) for candidate in candidates if candidate.is_file()), None)
    return shutil.which("bash")


def test_public_tunnel_refuses_an_occupied_backend_port_before_ngrok() -> None:
    """An existing local listener must never become the tunnel target."""
    bash = _usable_bash()
    if bash is None:
        pytest.skip("Bash is required for the public tunnel launcher regression")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        env = os.environ.copy()
        env.update(
            {
                "MCP_PORT": str(port),
                "NGROK_DOMAIN": "assigned-example.ngrok.dev",
                "PUBMED_AUTH_TOKENS": "copilot:0123456789abcdef0123456789abcdef",
            }
        )
        completed = subprocess.run(
            [
                bash,
                "-c",
                "ngrok() { printf 'NGROK_INVOKED\\n' >&2; return 99; }; "
                "export -f ngrok; bash ./scripts/start-copilot-studio.sh --with-ngrok",
            ],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert completed.returncode != 0
    assert "already in use; refusing to expose an existing listener" in completed.stderr
    assert "NGROK_INVOKED" not in completed.stderr
    assert "Starting authenticated MCP backend" not in completed.stdout


def test_public_tunnel_stops_backend_when_ngrok_exits_early() -> None:
    """The launcher must not leave its authenticated backend orphaned."""
    bash = _usable_bash()
    if bash is None:
        pytest.skip("Bash is required for the public tunnel launcher regression")

    env = os.environ.copy()
    env.update(
        {
            "MCP_PORT": "38457",
            "NGROK_DOMAIN": "assigned-example.ngrok.dev",
            "PUBMED_AUTH_TOKENS": "copilot:0123456789abcdef0123456789abcdef",
        }
    )
    harness = r"""
uv() {
    [ "${1:-}" = "run" ] || return 1
    shift
    if [ "${1:-}" = "python" ] && [ "${2:-}" = "-c" ]; then
        case "${3:-}" in
            *urlsplit*) printf '%s\n' 'assigned-example.ngrok.dev' ;;
            *)
                payload="$(cat)"
                case "$payload" in
                    *public_url*) printf '%s\n' 'https://assigned-example.ngrok.dev' ;;
                esac
                ;;
        esac
        return 0
    fi
    if [ "${1:-}" = "python" ] && [ "${2:-}" = "-" ]; then
        cat >/dev/null
        return 0
    fi
    if [ "${1:-}" = "pubmed-search-mcp-http" ]; then
        printf 'SERVER_STARTED\n' >&2
        trap 'printf "SERVER_STOPPED\\n" >&2; exit 0' TERM INT
        while :; do sleep 1; done
    fi
    return 1
}
curl() {
    case "$*" in
        *'/ready'*) printf '%s\n' '{"status":"ready","auth_enforced":true}' ;;
        *'/mcp'*) printf '401' ;;
        *'4040/api/tunnels'*) printf '%s\n' '{"tunnels":[{"public_url":"https://assigned-example.ngrok.dev"}]}' ;;
        *) return 1 ;;
    esac
}
ngrok() {
    printf 'NGROK_STARTED\n' >&2
    return 17
}
export -f uv curl ngrok
bash ./scripts/start-copilot-studio.sh --with-ngrok
"""
    completed = subprocess.run(
        [bash, "-c", harness],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode != 0
    assert "SERVER_STARTED" in completed.stderr
    assert "NGROK_STARTED" in completed.stderr
    assert "SERVER_STOPPED" in completed.stderr
    assert completed.stderr.index("SERVER_STARTED") < completed.stderr.index("NGROK_STARTED")
    assert completed.stderr.index("NGROK_STARTED") < completed.stderr.index("SERVER_STOPPED")
