"""Opt-in Docker verification of the default non-root HTTP runtime."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.fixtures.release_support import ROOT, run_checked, wait_for_health
from tests.test_release_transport_smoke import assert_http_contract


@pytest.mark.container
@pytest.mark.timeout(90)
async def test_container_serves_mcp_as_non_root(request: pytest.FixtureRequest) -> None:
    image = request.config.getoption("--container-image")
    if not image:
        pytest.skip("Build an image and pass --container-image to exercise Docker")
    docker = shutil.which("docker")
    assert docker is not None, "An explicitly requested container smoke requires Docker"
    container = run_checked(
        [
            docker,
            "run",
            "--detach",
            "--publish",
            "127.0.0.1::8765",
            "--env",
            "MCP_HOST=0.0.0.0",
            "--env",
            "PUBMED_SCHEDULER_ENABLED=false",
            "--env",
            "PUBMED_LOCAL_ALLOW_CONTAINER_BIND=true",
            image,
        ],
        cwd=ROOT,
    )
    try:
        info = json.loads(run_checked([docker, "inspect", container], cwd=ROOT))[0]
        assert info["Config"]["User"] not in ("", "0", "root")
        # Verify the effective UID, not just the Dockerfile's USER declaration.
        assert run_checked([docker, "exec", container, "id", "-u"], cwd=ROOT) != "0"
        version = info["Config"]["Labels"]["org.opencontainers.image.version"]
        port = info["NetworkSettings"]["Ports"]["8765/tcp"][0]["HostPort"]
        url = f"http://127.0.0.1:{port}"
        wait_for_health(url)
        await assert_http_contract(url, version=version)
    except BaseException:
        subprocess.run([docker, "logs", container], check=False, timeout=10)
        raise
    finally:
        run_checked([docker, "rm", "--force", container], cwd=ROOT)
