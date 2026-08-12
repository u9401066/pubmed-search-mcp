# Python 3.11.15 slim-trixie multi-platform index, resolved 2026-08-09.
FROM python:3.11.15-slim-trixie@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

LABEL org.opencontainers.image.title="PubMed Search MCP" \
      org.opencontainers.image.description="MCP SDK v2 server for multi-source biomedical literature research" \
      org.opencontainers.image.source="https://github.com/u9401066/pubmed-search-mcp" \
      org.opencontainers.image.version="0.6.2" \
      org.opencontainers.image.licenses="Apache-2.0"

# Pin the build tool so an upstream ``latest`` image cannot change release
# behavior without a reviewed dependency update.
COPY --from=ghcr.io/astral-sh/uv:0.11.24 /uv /uvx /bin/

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/

# Install Python dependencies
RUN uv sync --frozen --no-dev

# The service writes only tenant data below PUBMED_DATA_DIR. Keep the runtime
# process unprivileged and give it ownership of that explicit persistence root.
RUN groupadd --system --gid 10001 pubmed \
    && useradd --system --uid 10001 --gid pubmed --create-home --home-dir /home/pubmed pubmed \
    && mkdir -p /var/lib/pubmed-search-mcp \
    && chown -R pubmed:pubmed /app /var/lib/pubmed-search-mcp

# Default environment variables
ENV NCBI_EMAIL=pubmed-search@example.com
ENV MCP_PORT=8765
ENV MCP_HOST=127.0.0.1
ENV PUBMED_DATA_DIR=/var/lib/pubmed-search-mcp

# Expose port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

USER pubmed

# Run the packaged HTTP server
CMD ["uv", "run", "pubmed-search-mcp-http", "--transport", "streamable-http"]
