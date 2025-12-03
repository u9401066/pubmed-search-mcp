FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY run_server.py ./

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[mcp]"

# Default environment variables
ENV NCBI_EMAIL=pubmed-search@example.com
ENV MCP_PORT=8765
ENV MCP_HOST=0.0.0.0

# Expose port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8765/ || exit 1

# Run the server
CMD ["python", "run_server.py", "--transport", "sse"]
