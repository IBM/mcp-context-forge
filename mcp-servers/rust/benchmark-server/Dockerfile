# syntax=docker/dockerfile:1
FROM docker.io/library/rust:1.86-slim AS builder

WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY mcp-servers/rust/benchmark-server/Cargo.toml ./mcp-servers/rust/benchmark-server/Cargo.toml
RUN mkdir -p mcp-servers/rust/benchmark-server/src \
    && echo "fn main() {}" > mcp-servers/rust/benchmark-server/src/main.rs \
    && cargo build --release -p benchmark-server
COPY mcp-servers/rust/benchmark-server/src ./mcp-servers/rust/benchmark-server/src
RUN touch mcp-servers/rust/benchmark-server/src/main.rs \
    && cargo build --release -p benchmark-server

FROM docker.io/library/debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -s /bin/false mcpuser
WORKDIR /app
COPY --from=builder /app/target/release/benchmark-server /app/benchmark-server
USER mcpuser
EXPOSE 8080
ENV RUST_LOG=info
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1
ENTRYPOINT ["/app/benchmark-server"]
