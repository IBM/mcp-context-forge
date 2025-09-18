# Build stage
FROM --platform=$TARGETPLATFORM golang:1.23 AS builder
WORKDIR /src

# Copy go mod files first for better caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build with optimizations
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /pandoc-server .

# Pandoc stage - extract pandoc and its dependencies
FROM debian:stable-slim as pandoc_stage
RUN apt-get update && \
    apt-get install -y --no-install-recommends pandoc && \
    rm -rf /var/lib/apt/lists/*

# Final stage - minimal runtime
FROM debian:stable-slim

# Install runtime dependencies for pandoc
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgmp10 && \
    rm -rf /var/lib/apt/lists/* && \
    # Create non-root user
    useradd -m -u 1000 -s /bin/bash mcp

# Copy binaries
COPY --from=builder --chown=mcp:mcp /pandoc-server /usr/local/bin/pandoc-server
COPY --from=pandoc_stage /usr/bin/pandoc /usr/bin/pandoc

# Switch to non-root user
USER mcp
WORKDIR /home/mcp

# Add metadata
LABEL org.opencontainers.image.title="Pandoc MCP Server" \
      org.opencontainers.image.description="MCP server for pandoc document conversion" \
      org.opencontainers.image.version="0.2.0"

ENTRYPOINT ["/usr/local/bin/pandoc-server"]
