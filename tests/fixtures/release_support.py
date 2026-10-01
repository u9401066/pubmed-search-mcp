"""Shared artifact installation and process helpers for release acceptance.

Only the test driver uses development dependencies. Child servers run the real
entrypoints outside the checkout with a clean environment and production deps.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from pubmed_search import __version__

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parents[2]
PASSTHROUGH_ENV_KEYS = frozenset(
    {
        "COMSPEC",
        "DYLD_LIBRARY_PATH",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LD_LIBRARY_PATH",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "USERPROFILE",
        "WINDIR",
    }
)


def smoke_env(root: Path) -> dict[str, str]:
    """Never inherit provider credentials, import paths, proxies or user settings."""
    env = {key: value for key, value in os.environ.items() if key in PASSTHROUGH_ENV_KEYS}
    env.update(
        {
            "NCBI_EMAIL": "release-smoke@example.com",
            "PUBMED_DATA_DIR": str(root / "data"),
            "PUBMED_WORKSPACE_DIR": str(root / "workspace"),
            "PUBMED_NOTES_DIR": str(root / "notes"),
            "PUBMED_SCHEDULER_ENABLED": "false",
            "PUBMED_AUTH_REQUIRED": "false",
            "PUBMED_SERVER_MODE": "local",
            "INSTITUTIONAL_DIRECT_FETCH": "false",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    return env


def run_checked(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=180, check=False)
    if completed.returncode:
        raise AssertionError(
            f"Command failed ({completed.returncode}): {command}\n{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout.strip()


@dataclass(frozen=True)
class ReleaseInstallation:
    python: Path
    wheel: Path
    sdist: Path
    version: str

    def entrypoint(self, name: str) -> Path:
        return self.python.parent / (name + (".exe" if os.name == "nt" else ""))


def install_release(root: Path, dist: Path | None) -> ReleaseInstallation:
    """Build once per session or test the exact distributions supplied by CI."""
    uv = shutil.which("uv")
    assert uv is not None, "uv is required: release acceptance must not silently skip"
    if dist is None:
        dist = root / "dist"
        run_checked([uv, "build", "--no-sources", "--out-dir", str(dist)], cwd=ROOT)
    wheels, sdists = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1, (
        "Expected exactly one wheel and one sdist; use a clean distribution directory"
    )
    wheel, sdist = wheels[0].resolve(), sdists[0].resolve()
    assert wheel.name.startswith(f"pubmed_search_mcp-{__version__}-"), (
        "Wheel version does not match the source under test"
    )
    assert sdist.name == f"pubmed_search_mcp-{__version__}.tar.gz", "sdist version does not match the source under test"
    # A published sdist must reproduce the same installed files as the wheel.
    rebuilt = root / "from-sdist"
    run_checked([uv, "build", "--no-sources", "--wheel", str(sdist), "--out-dir", str(rebuilt)], cwd=root)
    rebuilt_wheel = next(rebuilt.glob("*.whl"))
    assert rebuilt_wheel.name == wheel.name, "sdist and wheel names/versions differ"

    def contents(path: Path) -> dict[str, str]:
        with zipfile.ZipFile(path) as archive:
            return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}

    assert contents(wheel) == contents(rebuilt_wheel), "sdist rebuild differs from the wheel being published"
    venv = root / "venv"
    run_checked([uv, "venv", str(venv), "--python", sys.executable], cwd=root)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run_checked([uv, "pip", "install", "--python", str(python), str(wheel)], cwd=root)
    imported = json.loads(
        run_checked(
            [
                str(python),
                "-I",
                "-c",
                "import json, importlib.metadata, pubmed_search; from pubmed_search.api import PubMedSearchClient; "
                "print(json.dumps([pubmed_search.__file__, pubmed_search.__version__, "
                "importlib.metadata.version('pubmed-search-mcp')]))",
            ],
            cwd=root,
            env=smoke_env(root),
        )
    )
    assert Path(imported[0]).resolve().is_relative_to(venv.resolve()), "Checkout import masked broken packaging"
    assert imported[1] == imported[2] == __version__, "Installed metadata/package version differs from source"
    return ReleaseInstallation(python, wheel, sdist, imported[1])


def unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base_url: str, *, process: subprocess.Popen[str] | None = None) -> None:
    deadline = time.monotonic() + 20
    with httpx.Client(trust_env=False, timeout=0.5) as client:
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise AssertionError(f"Server exited before readiness: {process.returncode}")
            try:
                response = client.get(f"{base_url}/health")
                if response.status_code == 200 and response.json().get("status") == "ok":
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.05)
    raise AssertionError("Server did not become healthy within 20 seconds")


@contextmanager
def running_http_server(command: list[str], root: Path) -> Iterator[str]:
    port = unused_loopback_port()
    root.mkdir(parents=True, exist_ok=True)
    log_path = root / "http.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [*command, "--mode", "local", "--host", "127.0.0.1", "--port", str(port)],
            cwd=root,
            env=smoke_env(root),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            wait_for_health(base_url, process=process)
            yield base_url
        except BaseException:
            log.flush()
            # Preserve startup diagnostics in pytest's captured output.
            print(log_path.read_text(encoding="utf-8", errors="replace"))
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
