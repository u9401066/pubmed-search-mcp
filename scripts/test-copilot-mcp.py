#!/usr/bin/env python3
"""
Test script to simulate Copilot Studio's MCP communication flow.

This script helps debug MCP integration by:
1. Sending the exact same requests as Copilot Studio
2. Showing detailed error messages
3. Validating the full handshake process

Usage:
    python scripts/test-copilot-mcp.py [URL]
    python scripts/test-copilot-mcp.py https://kmuh-ai.ngrok.dev/mcp
"""

import sys
import json
import requests
from typing import Optional


# Colors for terminal output
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_step(step: int, title: str):
    print(f"\n{Colors.BLUE}{Colors.BOLD}[Step {step}] {title}{Colors.RESET}")
    print("-" * 60)


def print_success(msg: str):
    print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")


def print_error(msg: str):
    print(f"{Colors.RED}❌ {msg}{Colors.RESET}")


def print_warning(msg: str):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.RESET}")


def print_json(data: dict):
    print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
    if len(json.dumps(data)) > 1000:
        print("... (truncated)")


def test_mcp_server(base_url: str):
    """Simulate Copilot Studio's MCP communication."""

    session = requests.Session()

    # Copilot Studio's exact headers
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json,text/event-stream",
        "X-Ms-User-Agent": "CopilotStudio PowerFx/1.5.0-test",
    }

    session_id: Optional[str] = None

    # =========================================================================
    # Step 1: Initialize
    # =========================================================================
    print_step(1, "Initialize (MCP Handshake)")

    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "CopilotStudio", "version": "1.0"},
        },
        "id": "1",
    }

    print(f"Request URL: {base_url}")
    print("Request Headers:")
    for k, v in headers.items():
        print(f"  {k}: {v}")
    print("Request Body:")
    print_json(init_payload)

    try:
        resp = session.post(base_url, json=init_payload, headers=headers, timeout=30)
        print(f"\nResponse Status: {resp.status_code}")
        print("Response Headers:")
        for k, v in resp.headers.items():
            print(f"  {k}: {v}")

        if resp.status_code == 200:
            session_id = resp.headers.get("Mcp-Session-Id")
            if session_id:
                print_success(f"Session ID: {session_id}")
            else:
                print_warning("No Mcp-Session-Id in response headers")

            data = resp.json()
            server_info = data.get("result", {}).get("serverInfo", {})
            print_success(
                f"Server: {server_info.get('name')} v{server_info.get('version')}"
            )
            print("Response (truncated):")
            print_json(data)
        else:
            print_error(f"HTTP {resp.status_code}: {resp.text[:500]}")
            return False

    except requests.exceptions.ConnectionError as e:
        print_error(f"Connection failed: {e}")
        return False
    except requests.exceptions.Timeout:
        print_error("Request timed out (30s)")
        return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

    # =========================================================================
    # Step 2: Send initialized notification
    # =========================================================================
    print_step(2, "Send 'initialized' notification")

    if session_id:
        headers["Mcp-Session-Id"] = session_id

    notif_payload = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    print("Request Body:")
    print_json(notif_payload)

    try:
        resp = session.post(base_url, json=notif_payload, headers=headers, timeout=30)
        print(f"\nResponse Status: {resp.status_code}")

        if resp.status_code in [200, 202]:
            print_success(f"Notification accepted (HTTP {resp.status_code})")
            if resp.text:
                print(f"Response: {resp.text[:200]}")
        else:
            print_error(f"HTTP {resp.status_code}: {resp.text[:500]}")

    except Exception as e:
        print_error(f"Error: {e}")

    # =========================================================================
    # Step 3: List tools
    # =========================================================================
    print_step(3, "List available tools")

    tools_payload = {"jsonrpc": "2.0", "method": "tools/list", "id": "2"}

    print("Request Body:")
    print_json(tools_payload)

    try:
        resp = session.post(base_url, json=tools_payload, headers=headers, timeout=30)
        print(f"\nResponse Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            tools = data.get("result", {}).get("tools", [])
            print_success(f"Found {len(tools)} tools")
            print("First 5 tools:")
            for t in tools[:5]:
                print(f"  - {t.get('name')}: {t.get('description', '')[:50]}...")
        else:
            print_error(f"HTTP {resp.status_code}: {resp.text[:500]}")

    except Exception as e:
        print_error(f"Error: {e}")

    # =========================================================================
    # Step 4: Call a simple tool (search_pubmed for Copilot mode)
    # =========================================================================
    print_step(4, "Call 'search_pubmed' tool (simple test)")

    call_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "search_pubmed",
            "arguments": {"query": "COVID-19 vaccine efficacy", "limit": 3},
        },
        "id": "3",
    }

    print("Request Body:")
    print_json(call_payload)

    try:
        resp = session.post(base_url, json=call_payload, headers=headers, timeout=60)
        print(f"\nResponse Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            if "result" in data:
                print_success("Tool call succeeded!")
                # Show content summary
                content = data.get("result", {}).get("content", [])
                if content and len(content) > 0:
                    text = content[0].get("text", "")[:500]
                    print(f"Result preview: {text}...")
            elif "error" in data:
                print_error(f"Tool error: {data['error']}")
                print_json(data)
        else:
            print_error(f"HTTP {resp.status_code}: {resp.text[:500]}")

    except Exception as e:
        print_error(f"Error: {e}")

    # =========================================================================
    # Step 5: Call get_article (real test)
    # =========================================================================
    print_step(5, "Call 'get_article' tool")

    search_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "get_article", "arguments": {"pmid": "33301246"}},
        "id": "4",
    }

    print("Request Body:")
    print_json(search_payload)

    try:
        resp = session.post(base_url, json=search_payload, headers=headers, timeout=60)
        print(f"\nResponse Status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            if "result" in data:
                print_success("Article fetch succeeded!")
                # Show content summary
                content = data.get("result", {}).get("content", [])
                if content and len(content) > 0:
                    text = content[0].get("text", "")[:500]
                    print(f"Result preview: {text}...")
            elif "error" in data:
                print_error(f"Tool error: {data['error']}")
        else:
            print_error(f"HTTP {resp.status_code}: {resp.text[:500]}")

    except Exception as e:
        print_error(f"Error: {e}")

    # =========================================================================
    # Summary
    # =========================================================================
    print(f"\n{'=' * 60}")
    print(f"{Colors.BOLD}Summary{Colors.RESET}")
    print(f"{'=' * 60}")
    print(f"Server URL: {base_url}")
    print(f"Session ID: {session_id or 'N/A'}")
    print("\nIf all steps passed, your MCP server is ready for Copilot Studio!")
    print("\nTo add to Copilot Studio:")
    print("  1. Go to copilotstudio.microsoft.com")
    print("  2. Open your Agent > Tools > Add a tool > New tool")
    print("  3. Select 'Model Context Protocol'")
    print("  4. Enter:")
    print("     - Server name: PubMed Search")
    print(f"     - Server URL: {base_url}")
    print("     - Authentication: None")

    return True


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://kmuh-ai.ngrok.dev/mcp"

    print("""
╔══════════════════════════════════════════════════════════════╗
║  Copilot Studio MCP Compatibility Test                       ║
║  Simulates the exact communication flow of Copilot Studio    ║
╚══════════════════════════════════════════════════════════════╝
""")

    test_mcp_server(url)
