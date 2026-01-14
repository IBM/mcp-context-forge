# syntax=docker/dockerfile:1
# fast-test-server - Multi-stage Rust build for minimal image size

# Build stage
FROM docker.io/rustlang/rust:nightly-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copy manifests
COPY Cargo.toml Cargo.lock* ./

# Create dummy src to cache dependencies
RUN mkdir src && echo "fn main() {}" > src/main.rs
RUN cargo build --release && rm -rf src target/release/deps/fast_test_server* target/release/.fingerprint/fast-test-server*

# Copy actual source
COPY src ./src

# Build release binary (touch to ensure mtime is newer than cached artifacts)
RUN touch src/main.rs && cargo build --release

# Runtime stage - minimal image
FROM docker.io/library/debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy binary from builder
COPY --from=builder /app/target/release/fast-test-server /app/fast-test-server

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

ENTRYPOINT ["/app/fast-test-server"]
