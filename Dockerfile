FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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

# Default environment variables
ENV NCBI_EMAIL=pubmed-search@example.com
ENV MCP_PORT=8765
ENV MCP_HOST=0.0.0.0

# Expose port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

# Run the packaged HTTP server
CMD ["uv", "run", "pubmed-search-mcp-http", "--transport", "streamable-http"]
