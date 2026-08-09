"""Release-level smoke tests using real MCP subprocess transports."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parents[1]


def _smoke_env(data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "NCBI_EMAIL": "release-smoke@example.com",
            "PUBMED_DATA_DIR": str(data_dir),
            "PUBMED_SCHEDULER_ENABLED": "false",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


async def _assert_protocol_contract(transport: object) -> None:
    async with Client(transport, read_timeout_seconds=20) as client:
        tools = await client.list_tools()
        assert "analyze_search_query" in {tool.name for tool in tools.tools}

        result = await client.call_tool(
            "analyze_search_query",
            {"query": "aspirin stroke prevention"},
        )
        assert result.is_error is False
        assert any("Query Analysis" in block.text for block in result.content if hasattr(block, "text"))


@pytest.mark.asyncio
async def test_real_stdio_subprocess_lists_calls_and_shuts_down(tmp_path: Path) -> None:
    """Exercise the packaged stdio module through an actual child process."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pubmed_search.presentation.mcp_server"],
        cwd=ROOT,
        env=_smoke_env(tmp_path / "stdio-data"),
    )

    await _assert_protocol_contract(stdio_client(parameters))


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _running_http_server(tmp_path: Path) -> Iterator[str]:
    port = _unused_loopback_port()
    log_path = tmp_path / "streamable-http.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pubmed_search.presentation.mcp_server.http_cli",
                "--mode",
                "local",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=_smoke_env(tmp_path / "http-data"),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if process.poll() is not None:
                    break
                try:
                    response = httpx.get(f"{base_url}/health", timeout=0.25)
                    if response.status_code == 200:
                        yield base_url
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)

            log.flush()
            details = log_path.read_text(encoding="utf-8", errors="replace")
            raise AssertionError(f"HTTP smoke server did not become ready:\n{details}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.asyncio
async def test_real_streamable_http_health_protocol_and_rebinding_guards(tmp_path: Path) -> None:
    """Exercise health, MCP list/call, and SDK Host/Origin rejection on a real port."""
    with _running_http_server(tmp_path) as base_url:
        health = httpx.get(f"{base_url}/health", timeout=2)
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        await _assert_protocol_contract(f"{base_url}/mcp")

        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        invalid_host = httpx.post(
            f"{base_url}/mcp",
            headers={"Host": "attacker.example"},
            json=payload,
            timeout=2,
        )
        invalid_origin = httpx.post(
            f"{base_url}/mcp",
            headers={"Origin": "https://attacker.example"},
            json=payload,
            timeout=2,
        )

        assert invalid_host.status_code == 421
        assert invalid_origin.status_code == 403


@pytest.mark.slow
@pytest.mark.asyncio
async def test_built_wheel_fresh_install_entrypoints(tmp_path: Path) -> None:
    """Build a wheel, install it into an empty venv, then exercise its consoles."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for the release wheel smoke")

    dist_dir = tmp_path / "dist"
    venv_dir = tmp_path / "fresh-venv"
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(dist_dir.glob("pubmed_search_mcp-*.whl"))

    subprocess.run(
        [uv, "venv", str(venv_dir), "--python", sys.executable],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [uv, "pip", "install", "--python", str(venv_python), str(wheel)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    stdio_entrypoint = scripts_dir / f"pubmed-search-mcp{suffix}"
    http_entrypoint = scripts_dir / f"pubmed-search-mcp-http{suffix}"
    broker_entrypoint = scripts_dir / f"pubmed-browser-fetch-broker{suffix}"

    env = _smoke_env(tmp_path / "wheel-data")
    for entrypoint in (http_entrypoint, broker_entrypoint):
        completed = subprocess.run(
            [str(entrypoint), "--help"],
            cwd=tmp_path,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert completed.returncode == 0, completed.stderr

    parameters = StdioServerParameters(
        command=str(stdio_entrypoint),
        cwd=tmp_path,
        env=env,
    )
    await _assert_protocol_contract(stdio_client(parameters))
