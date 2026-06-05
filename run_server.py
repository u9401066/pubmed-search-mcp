#!/usr/bin/env python3
"""Source-tree wrapper for the packaged PubMed Search MCP HTTP CLI.

Installed packages and containers should prefer `pubmed-search-mcp-http`.
This file remains for contributors who run the repository directly.
"""

from __future__ import annotations

import os
import sys
import tempfile
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _default_export_dir() -> str:
    """Return the default export directory used by the HTTP CLI."""
    return str(Path(tempfile.gettempdir()) / "pubmed_exports")


def main() -> None:
    """Run the packaged HTTP CLI from a source checkout."""
    sys.path.insert(0, str(ROOT / "src"))
    os.environ.setdefault("MCP_TRANSPORT", "streamable-http")
    http_cli = import_module("pubmed_search.presentation.mcp_server.http_cli")
    http_cli.main()


if __name__ == "__main__":
    main()
