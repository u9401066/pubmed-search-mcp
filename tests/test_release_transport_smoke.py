"""Production entrypoints, artifact isolation, one-retry repair and durable state.

No provider or application services are replaced. These workflows deliberately
need no literature network; provider-backed acceptance is tested separately.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.fixtures.release_support import (
    PASSTHROUGH_ENV_KEYS,
    ReleaseInstallation,
    running_http_server,
    smoke_env,
)
from tests.test_all_tools_mcp_acceptance import EXPECTED_TOOLS, PIPELINE_CONFIG


def result_text(result: Any) -> str:
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))


async def assert_protocol_contract(client: Client) -> None:
    """Check the actual registry and repair a failed write using the returned contract."""
    listed = (await client.list_tools()).tools
    assert {tool.name for tool in listed} == EXPECTED_TOOLS
    for tool in listed:
        Draft202012Validator.check_schema(tool.input_schema)
    result = await client.call_tool("analyze_search_query", {"query": "aspirin stroke prevention"})
    assert result.is_error is False, result_text(result)
    assert "Query Analysis" in result_text(result)

    arguments = {"name": "release-smoke", "config": PIPELINE_CONFIG, "scope": "global", "tags": [False]}
    rejected = await client.call_tool("save_pipeline", arguments)
    assert rejected.is_error is True
    error = rejected.structured_content
    assert error["executed"] is False
    assert error["recovery"]["action"] == "correct_arguments"
    detail = next(item for item in error["errors"] if item["path"] == "/tags/0")
    assert detail["expected"]["type"] == "string"
    listing = await client.call_tool("list_pipelines", {"scope": "global"})
    assert "release-smoke" not in result_text(listing), "Rejected write changed durable state"
    # One correction followed by one retry; normalizable container spelling
    # must not force another tool call.
    arguments["tags"] = json.dumps(["smoke"])
    saved = await client.call_tool("save_pipeline", arguments)
    assert saved.is_error is False, result_text(saved)
    assert "saved successfully" in result_text(saved)
    loaded = await client.call_tool("load_pipeline", {"source": "saved:release-smoke"})
    assert "query: offline pipeline" in result_text(loaded)

    resources = await client.list_resources()
    assert "session://context" in {resource.uri for resource in resources.resources}
    context = await client.read_resource("session://context")
    assert context.contents
    json.loads(context.contents[0].text)


async def assert_http_contract(base_url: str, *, version: str) -> None:
    with httpx.Client(trust_env=False, timeout=3) as http:
        health = http.get(f"{base_url}/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["version"] == version
        ready = http.get(f"{base_url}/ready")
        assert ready.status_code == 200
        assert ready.json()["transport"] == "streamable-http"
        assert ready.json()["auth_enforced"] is False
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        assert http.post(f"{base_url}/mcp", headers={"Host": "attacker.example"}, json=payload).status_code == 421
        assert (
            http.post(f"{base_url}/mcp", headers={"Origin": "https://attacker.example"}, json=payload).status_code
            == 403
        )
    async with Client(f"{base_url}/mcp", read_timeout_seconds=20) as client:
        await assert_protocol_contract(client)


@pytest.mark.asyncio
async def test_real_stdio_subprocess_lists_calls_and_shuts_down(tmp_path: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pubmed_search.presentation.mcp_server"],
        cwd=tmp_path,
        env=smoke_env(tmp_path),
    )
    async with Client(stdio_client(parameters), read_timeout_seconds=20) as client:
        await assert_protocol_contract(client)


@pytest.mark.asyncio
async def test_real_streamable_http_health_protocol_and_rebinding_guards(tmp_path: Path) -> None:
    from pubmed_search import __version__

    command = [sys.executable, "-m", "pubmed_search.presentation.mcp_server.http_cli"]
    with running_http_server(command, tmp_path) as base_url:
        await assert_http_contract(base_url, version=__version__)


@pytest.mark.slow
@pytest.mark.timeout(240)
@pytest.mark.asyncio
async def test_installed_stdio_persists_across_restart_and_isolates_data_roots(
    tmp_path: Path, release_installation: ReleaseInstallation
) -> None:
    """Exercise installed consoles, real disk persistence, restart and deletion."""
    parameters = StdioServerParameters(
        command=str(release_installation.entrypoint("pubmed-search-mcp")),
        cwd=tmp_path,
        env=smoke_env(tmp_path),
    )
    async with Client(stdio_client(parameters), read_timeout_seconds=20) as client:
        await assert_protocol_contract(client)
    async with Client(stdio_client(parameters), read_timeout_seconds=20) as restarted:
        result = await restarted.call_tool("load_pipeline", {"source": "saved:release-smoke"})
        assert result.is_error is False
        assert "query: offline pipeline" in result_text(result), "Saved pipeline lost after a real process restart"
        other = parameters.model_copy(update={"env": smoke_env(tmp_path / "other-operator")})
        async with Client(stdio_client(other), read_timeout_seconds=20) as isolated:
            listing = await isolated.call_tool("list_pipelines", {"scope": "global"})
            assert "release-smoke" not in result_text(listing), "Data leaked between operator roots"
        deleted = await restarted.call_tool("delete_pipeline", {"name": "release-smoke"})
        assert "deleted" in result_text(deleted)
    async with Client(stdio_client(parameters), read_timeout_seconds=20) as restarted:
        listing = await restarted.call_tool("list_pipelines", {"scope": "global"})
        assert "release-smoke" not in result_text(listing), "Deletion did not survive restart"


@pytest.mark.slow
@pytest.mark.timeout(240)
@pytest.mark.asyncio
async def test_installed_http_serves_real_requests(tmp_path: Path, release_installation: ReleaseInstallation) -> None:
    with running_http_server([str(release_installation.entrypoint("pubmed-search-mcp-http"))], tmp_path) as base_url:
        await assert_http_contract(base_url, version=release_installation.version)


@pytest.mark.slow
@pytest.mark.timeout(240)
@pytest.mark.asyncio
async def test_registry_and_plugin_metadata_launch_the_exact_published_wheel(
    tmp_path: Path, release_installation: ReleaseInstallation
) -> None:
    """Registry/plugin hosts start ``uvx <identifier>@<version>`` with only declared env."""
    root = Path(__file__).resolve().parents[1]
    server = json.loads((root / "server.json").read_text(encoding="utf-8"))
    plugin = json.loads((root / "plugins/pubmed-search/mcp.json").read_text(encoding="utf-8"))
    (package,) = server["packages"]
    version = release_installation.version
    assert server["version"] == package["version"] == version
    assert (package["registryType"], package["runtimeHint"], package["transport"]) == ("pypi", "uvx", {"type": "stdio"})
    launcher = plugin["mcpServers"]["pubmed-search"]
    assert (launcher["command"], launcher["args"]) == ("uvx", [f"{package['identifier']}@{version}"])

    with zipfile.ZipFile(release_installation.wheel) as wheel:
        dist_info = next(name.split("/")[0] for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = wheel.read(f"{dist_info}/METADATA").decode("utf-8")
        entry_points = wheel.read(f"{dist_info}/entry_points.txt").decode("utf-8")
    # The registry proves PyPI ownership from this marker in the uploaded long description.
    assert f"<!-- mcp-name: {server['name']} -->" in metadata
    assert f"Name: {package['identifier']}\n" in metadata
    assert any(line.split("=")[0].strip() == package["identifier"] for line in entry_points.splitlines())

    declared = {item["name"] for item in package["environmentVariables"]}
    assert all(not name.startswith("PUBMED_") for name in declared)
    home = tmp_path / "home"
    home.mkdir()
    env = {key: value for key, value in smoke_env(tmp_path).items() if key in PASSTHROUGH_ENV_KEYS}
    env.update({"HOME": str(home), "USERPROFILE": str(home), "NCBI_EMAIL": "release-smoke@example.com"})
    parameters = StdioServerParameters(
        command=str(release_installation.entrypoint(package["identifier"])),
        cwd=tmp_path,
        env=env,
    )
    async with Client(stdio_client(parameters), read_timeout_seconds=30) as client:
        listed = (await client.list_tools()).tools
        assert {tool.name for tool in listed} == EXPECTED_TOOLS
        analysis = await client.call_tool("analyze_search_query", {"query": "aspirin stroke prevention"})
        assert analysis.is_error is False, result_text(analysis)


@pytest.mark.slow
@pytest.mark.timeout(240)
def test_installed_browser_broker_requires_token_before_startup(
    tmp_path: Path, release_installation: ReleaseInstallation
) -> None:
    """Optional Chromium is not installed; missing credentials must fail first."""
    process = subprocess.run(
        [str(release_installation.entrypoint("pubmed-browser-fetch-broker")), "--headless"],
        cwd=tmp_path,
        env=smoke_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert process.returncode != 0
    assert "browser broker token is required" in process.stderr
    assert "ModuleNotFoundError" not in process.stderr
