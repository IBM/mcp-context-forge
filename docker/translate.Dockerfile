# -*- coding: utf-8 -*-
# MCP Gateway Transport-Translation Bridge Docker Image
# Multi-stage build for production deployment

# ================================================================
# Stage 1: Base Python environment with UV package manager
# ================================================================
FROM python:3.12-slim as base

# Install system dependencies and UV package manager
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
RUN pip install uv

# Set working directory
WORKDIR /app

# ================================================================
# Stage 2: Build dependencies and install packages
# ================================================================
FROM base as builder

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv (much faster than pip)
RUN uv sync --frozen --no-dev

# ================================================================
# Stage 3: Production runtime image
# ================================================================
FROM python:3.12-slim as runtime

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r mcpuser && useradd -r -g mcpuser mcpuser

# Set working directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy application source code
COPY mcpgateway/ ./mcpgateway/
COPY README.md LICENSE ./

# Set up Python path and activate virtual environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"

# Create directories for logs and data
RUN mkdir -p /app/logs /app/data && \
    chown -R mcpuser:mcpuser /app

# Switch to non-root user
USER mcpuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import mcpgateway.translate" || exit 1

# Set default environment variables
ENV MCP_TRANSLATE_LOG_LEVEL=info
ENV MCP_TOOL_CALL_TIMEOUT=90

# Expose default port
EXPOSE 8000

# Use tini as init process for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command runs the translate bridge
CMD ["python", "-m", "mcpgateway.translate", "--help"]

# ================================================================
# Stage 4: UVX variant (for running arbitrary MCP servers)
# ================================================================
FROM runtime as uvx

USER root

# Install Node.js and npm for uvx support
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g @modelcontextprotocol/server-* || true && \
    rm -rf /var/lib/apt/lists/*

# Install uvx
RUN pip install uvx

USER mcpuser

# ================================================================
# Stage 5: Deno variant (for Deno-based MCP servers)
# ================================================================
FROM runtime as deno

USER root

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/root/.deno/bin:$PATH"

USER mcpuser

# Labels for metadata
LABEL org.opencontainers.image.title="MCP Gateway Transport-Translation Bridge"
LABEL org.opencontainers.image.description="Transport bridge for MCP protocols"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.authors="Mihai Criveti <redacted@ibm.com>"
LABEL org.opencontainers.image.source="https://github.com/IBM/mcp-context-forge"
LABEL org.opencontainers.image.licenses="Apache-2.0"
