# syntax=docker/dockerfile:1
FROM docker.io/library/rust:1.86-slim AS builder

WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY mcp-servers/rust/benchmark-server ./mcp-servers/rust/benchmark-server
COPY mcp-servers/rust/fast-time-server ./mcp-servers/rust/fast-time-server
COPY mcp-servers/rust/filesystem-server ./mcp-servers/rust/filesystem-server
COPY mcp-servers/rust/slow-time-server ./mcp-servers/rust/slow-time-server
COPY a2a-agents/rust/a2a-echo-agent ./a2a-agents/rust/a2a-echo-agent
RUN cargo build --release -p benchmark-server

FROM registry.access.redhat.com/ubi10/ubi-minimal:10.2-1777462752
RUN microdnf install -y ca-certificates curl shadow-utils \
    && microdnf clean all \
    && useradd -r -s /bin/false mcpuser
WORKDIR /app
COPY --from=builder /app/target/release/benchmark-server /app/benchmark-server
USER mcpuser
EXPOSE 8080
ENV RUST_LOG=info
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1
ENTRYPOINT ["/app/benchmark-server"]
