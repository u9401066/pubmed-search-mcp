#!/usr/bin/env bash
# Start PubMed Search MCP for Microsoft Copilot Studio.
#
# Local invocation is an unpublished loopback smoke test. ``--with-ngrok`` is
# a public deployment path and therefore always starts fail-closed service
# mode; it refuses to create a tunnel without explicit bearer credentials.

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

PORT="${MCP_PORT:-8765}"
EMAIL="${NCBI_EMAIL:-pubmed-search@example.com}"
SERVER_PID=""
NGROK_PID=""

cleanup() {
    # Close the public edge before stopping its authenticated backend.
    if [ -n "$NGROK_PID" ]; then
        kill "$NGROK_PID" 2>/dev/null || true
        wait "$NGROK_PID" 2>/dev/null || true
    fi
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required." >&2
    exit 1
fi

echo "PubMed Search MCP for Copilot Studio"
echo "Transport: streamable-http"
echo "Endpoint:  /mcp"
echo "Port:      $PORT"

if [ "${1:-}" = "--with-ngrok" ]; then
    : "${PUBMED_AUTH_TOKENS:?Set PUBMED_AUTH_TOKENS to principal:high-entropy-token before opening a public tunnel}"
    : "${NGROK_DOMAIN:?Set NGROK_DOMAIN to an assigned ngrok HTTPS domain before opening a public tunnel}"

    for dependency in ngrok curl; do
        if ! command -v "$dependency" >/dev/null 2>&1; then
            echo "ERROR: $dependency is required for --with-ngrok." >&2
            exit 1
        fi
    done

    PUBLIC_HOST="$(
        uv run python -c \
            'import sys; from urllib.parse import urlsplit; raw=sys.argv[1].strip(); parsed=urlsplit(raw if "://" in raw else f"https://{raw}"); valid=parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None and parsed.port is None and parsed.path in ("", "/") and not parsed.query and not parsed.fragment; sys.exit(2) if not valid else None; print(parsed.hostname)' \
            "$NGROK_DOMAIN"
    )" || {
        echo "ERROR: NGROK_DOMAIN must be one assigned HTTPS host without a path, query, or port." >&2
        exit 1
    }
    PUBLIC_ORIGIN="https://${PUBLIC_HOST}"

    # Never point a tunnel at an existing listener. The service is started and
    # verified before ngrok is allowed to publish this port.
    if ! uv run python - "$PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.bind(("127.0.0.1", port))
PY
    then
        echo "ERROR: 127.0.0.1:$PORT is already in use; refusing to expose an existing listener." >&2
        exit 1
    fi

    export PUBMED_AUTH_RESOURCE_SERVER_URL="${PUBLIC_ORIGIN}/mcp"
    export PUBMED_ALLOWED_HOSTS="$PUBLIC_HOST"
    export PUBMED_ALLOWED_ORIGINS="$PUBLIC_ORIGIN"
    export PUBMED_TRUSTED_PROXY_IPS="127.0.0.1"

    echo "Starting authenticated MCP backend on loopback..."
    uv run pubmed-search-mcp-http \
        --mode service \
        --transport streamable-http \
        --copilot-compatible \
        --host 127.0.0.1 \
        --port "$PORT" \
        --email "$EMAIL" &
    SERVER_PID=$!

    BACKEND_URL="http://127.0.0.1:${PORT}"
    BACKEND_READY=""
    for _attempt in $(seq 1 40); do
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            break
        fi
        READY_BODY="$(curl -fsS --max-time 1 -H "Host: $PUBLIC_HOST" "$BACKEND_URL/ready" 2>/dev/null || true)"
        if [ -n "$READY_BODY" ] && printf '%s' "$READY_BODY" | uv run python -c \
            'import json,sys; data=json.load(sys.stdin); raise SystemExit(0 if data.get("status") == "ready" and data.get("auth_enforced") is True else 1)' \
            >/dev/null 2>&1; then
            BACKEND_READY="1"
            break
        fi
        sleep 0.25
    done

    if [ -z "$BACKEND_READY" ]; then
        echo "ERROR: authenticated MCP service did not become ready; tunnel was not opened." >&2
        exit 1
    fi

    AUTH_STATUS="$(
        curl -sS --max-time 2 -o /dev/null -w '%{http_code}' \
            -H "Host: $PUBLIC_HOST" \
            -H 'Content-Type: application/json' \
            --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
            "$BACKEND_URL/mcp" 2>/dev/null || true
    )"
    if [ "$AUTH_STATUS" != "401" ]; then
        echo "ERROR: backend auth boundary returned HTTP $AUTH_STATUS instead of 401; tunnel was not opened." >&2
        exit 1
    fi

    echo "Backend ready with bearer authentication enforced. Starting ngrok tunnel..."
    ngrok http --url="$PUBLIC_HOST" "$PORT" &
    NGROK_PID=$!

    NGROK_URL=""
    for _attempt in $(seq 1 20); do
        if ! kill -0 "$NGROK_PID" 2>/dev/null; then
            break
        fi
        NGROK_URL="$(
            curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null |
                uv run python -c 'import json,sys; print(next((t["public_url"] for t in json.load(sys.stdin).get("tunnels", []) if t.get("public_url", "").startswith("https://")), ""))' \
                2>/dev/null || true
        )"
        if [ "${NGROK_URL%/}" = "$PUBLIC_ORIGIN" ]; then
            break
        fi
        NGROK_URL=""
        sleep 0.5
    done

    if [ -z "$NGROK_URL" ]; then
        echo "ERROR: ngrok did not publish the assigned HTTPS domain $PUBLIC_ORIGIN." >&2
        exit 1
    fi

    echo "Server URL:     ${PUBLIC_ORIGIN}/mcp"
    echo "Authentication: Bearer token (the token value configured in PUBMED_AUTH_TOKENS)"
    echo "Press Ctrl+C to stop."
    while kill -0 "$SERVER_PID" 2>/dev/null && kill -0 "$NGROK_PID" 2>/dev/null; do
        sleep 1
    done
    if ! kill -0 "$NGROK_PID" 2>/dev/null; then
        echo "ERROR: ngrok exited; stopping the authenticated backend." >&2
        exit 1
    fi
    wait "$SERVER_PID"
else
    echo "Starting unpublished local-only schema/protocol smoke server."
    echo "Do not place this local mode behind ngrok or another public tunnel."
    echo "Local endpoint: http://127.0.0.1:$PORT/mcp"

    uv run pubmed-search-mcp-http \
        --mode local \
        --transport streamable-http \
        --copilot-compatible \
        --host 127.0.0.1 \
        --port "$PORT" \
        --email "$EMAIL"
fi
