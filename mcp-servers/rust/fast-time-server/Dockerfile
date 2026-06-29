# syntax=docker/dockerfile:1
# fast-time-server - Multi-stage Rust build for minimal image size

# Build stage
FROM docker.io/rustlang/rust:nightly-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Build inside the repo workspace because this crate inherits package metadata
# and dependencies from the root Cargo.toml.
COPY Cargo.toml Cargo.lock* ./
COPY crates ./crates
COPY mcp-servers/rust/benchmark-server ./mcp-servers/rust/benchmark-server
COPY mcp-servers/rust/fast-time-server ./mcp-servers/rust/fast-time-server
COPY mcp-servers/rust/filesystem-server ./mcp-servers/rust/filesystem-server
COPY mcp-servers/rust/slow-time-server ./mcp-servers/rust/slow-time-server
COPY a2a-agents/rust/a2a-echo-agent ./a2a-agents/rust/a2a-echo-agent

RUN cargo build --release -p fast-time-server

# Runtime stage - minimal image
FROM registry.access.redhat.com/ubi10/ubi-minimal:10.2-1777462752

RUN microdnf install -y ca-certificates curl shadow-utils \
    && microdnf clean all

WORKDIR /app

# Copy binary from builder
COPY --from=builder /app/target/release/fast-time-server /app/fast-time-server

# Non-root user
RUN useradd -r -s /bin/false mcpuser
USER mcpuser

# Expose default port
EXPOSE 8880

# Environment
ENV BIND_ADDRESS=0.0.0.0:8880
ENV RUST_LOG=info

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8880/health || exit 1

ENTRYPOINT ["/app/fast-time-server"]
