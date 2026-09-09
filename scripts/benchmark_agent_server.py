"""Stdio evaluation adapter: basic tools or production MCP, frozen data only.

This launcher is never registered with the production MCP tool registry.
Production behavior remains in the repo; only its external searcher is replaced.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import socket
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from pubmed_search.infrastructure.evaluation.corpus import FrozenCorpus


def _block_network(event: str, _args: tuple[Any, ...]) -> None:
    """Block external socket connections in this offline server process."""
    if (
        event == "socket.connect"
        and isinstance(_args[0], socket.socket)
        and _args[0].family != getattr(socket, "AF_UNIX", None)
    ):
        raise RuntimeError("Network access is unavailable in the frozen benchmark")


async def build_server(corpus: FrozenCorpus, arm: str, state_dir: Path) -> MCPServer[Any]:
    if arm == "basic":
        server: MCPServer[Any] = MCPServer("frozen-literature", instructions="Search the frozen literature corpus.")

        @server.tool()
        async def search(query: str, limit: int = 10) -> str:
            """Search title/abstract text with plain lexical terms. Supports iterative queries."""
            return json.dumps(await corpus.search(query, limit), ensure_ascii=False)

        @server.tool()
        async def read(pmids: list[str]) -> str:
            """Read corpus records using numeric transport IDs returned by search."""
            return json.dumps(await corpus.fetch_details(pmids), ensure_ascii=False)
    else:
        from pubmed_search.presentation.mcp_server.server import create_server, get_container

        server = create_server(email="benchmark@example.invalid", data_dir=str(state_dir), mode="local")
        # Evaluation deliberately supports the archived pre-0.7 baseline as
        # well as the current server-scoped, typed provider boundary.
        if "server" in inspect.signature(get_container).parameters:
            from pubmed_search.application.search.source_models import SourceSearchPage

            searcher = get_container(server).searcher()

            async def search_page(query: str, limit: int = 10, **kwargs: Any) -> SourceSearchPage[dict[str, Any]]:
                items = await corpus.search(query, limit, **kwargs)
                return SourceSearchPage(
                    source="pubmed",
                    items=items,
                    query=query,
                    total=None,
                    metadata={"physical_query": query, "query_executed": True},
                )

            searcher.search_page = search_page
        else:
            searcher = get_container().searcher()  # type: ignore[call-arg] - historical evaluation revision
            searcher.search = corpus.search
        searcher.fetch_details = corpus.fetch_details
        allowed = {
            "unified_search",
            "fetch_article_details",
            "read_session",
            "get_session_summary",
            "get_cached_article",
            "get_session_pmids",
        }
        for tool in await server.list_tools():
            if tool.name not in allowed:
                server.remove_tool(tool.name)

    @MCPServer.tool(server)
    def budget_status() -> dict[str, int]:
        """Read remaining shared backend search and document-exposure budgets."""
        return {
            "searches_remaining": max(0, corpus.search_budget - corpus.search_calls),
            "document_exposures_remaining": max(0, corpus.document_budget - corpus.document_exposures),
        }

    # This evaluation profile only reads frozen data and writes its own audit/cache.
    # Supply accurate hints without changing production tool registrations.
    for tool in server._tool_manager.list_tools():  # noqa: SLF001 - SDK has no public annotation setter
        tool.annotations = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
    return server


def main() -> None:
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--arm", choices=("basic", "repo"), required=True)
    parser.add_argument("--search-budget", type=int, default=6)
    parser.add_argument("--document-budget", type=int, default=120)
    args = parser.parse_args()
    corpus = FrozenCorpus(
        args.corpus, args.audit, search_budget=args.search_budget, document_budget=args.document_budget
    )
    server = asyncio.run(build_server(corpus, args.arm, args.state_dir))
    sys.addaudithook(_block_network)
    try:
        server.run()
    finally:
        corpus.close()


if __name__ == "__main__":
    main()
