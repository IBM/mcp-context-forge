# syntax=docker/dockerfile:1
FROM docker.io/library/rust:1.86-slim AS builder

WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY a2a-agents/rust/a2a-echo-agent ./a2a-agents/rust/a2a-echo-agent
RUN cargo build --release -p a2a-echo-agent

FROM docker.io/library/debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -s /bin/false mcpuser
WORKDIR /app
COPY --from=builder /app/target/release/a2a-echo-agent /app/a2a-echo-agent
USER mcpuser
EXPOSE 9100
ENV A2A_ECHO_ADDR=0.0.0.0:9100
ENV A2A_ECHO_NAME=a2a-echo-agent
ENV A2A_ECHO_PROTOCOL_VERSION=1.0.0
ENV RUST_LOG=info
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:9100/health || exit 1
ENTRYPOINT ["/app/a2a-echo-agent"]
