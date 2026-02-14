#!/usr/bin/env python3
"""
Test client for PubMed Search MCP Server

This script tests the MCP server running in SSE mode.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from mcp import ClientSession
from mcp.client.sse import sse_client


@pytest.mark.asyncio
@pytest.mark.skip(reason="Integration test - requires running server")
async def test_mcp_server(url: str = "http://localhost:8765/sse"):
    """Test the MCP server connection and tools."""
    print(f"Connecting to MCP server at {url}...")

    async with sse_client(url) as streams:
        async with ClientSession(*streams) as session:
            # Initialize the session
            await session.initialize()
            print("??Connected and initialized successfully!")

            # List available tools
            print("\n?? Available tools:")
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description[:60]}...")

            # Test search_literature
            print("\n?? Testing search_literature...")
            result = await session.call_tool(
                "search_literature",
                arguments={"query": "COVID-19 vaccine efficacy", "limit": 3},
            )
            print("Search results:")
            for content in result.content:
                if hasattr(content, "text"):
                    print(content.text[:500])

            print("\n??All tests passed!")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765/sse"
    asyncio.run(test_mcp_server(url))
