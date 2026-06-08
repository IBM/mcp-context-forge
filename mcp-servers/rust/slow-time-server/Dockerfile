# syntax=docker/dockerfile:1
FROM docker.io/library/rust:1.86-slim AS builder

WORKDIR /app
COPY Cargo.toml Cargo.lock* ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release
COPY src ./src
RUN touch src/main.rs && cargo build --release

FROM docker.io/library/debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -s /bin/false mcpuser
WORKDIR /app
COPY --from=builder /app/target/release/slow-time-server /app/slow-time-server
USER mcpuser
EXPOSE 8081
ENV BIND_ADDRESS=0.0.0.0:8081
ENV DEFAULT_LATENCY=5s
ENV FAILURE_RATE=0.0
ENV RUST_LOG=info
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:8081/health || exit 1
ENTRYPOINT ["/app/slow-time-server"]
