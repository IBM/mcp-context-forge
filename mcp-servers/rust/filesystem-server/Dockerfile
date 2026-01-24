# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# filesystem-server - Minimal Rust static binary Docker image
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ==========================
# Build stage: static Rust binary
# ==========================
FROM rust:1.92-slim AS builder

WORKDIR /app

# Install musl and pkg-config for static builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    musl-tools \
    pkg-config \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Add musl target
RUN rustup target add x86_64-unknown-linux-musl

# Copy manifests first for caching
COPY Cargo.toml Cargo.lock ./

# Create minimal dummy main to cache dependencies
RUN mkdir src && echo "fn main() {}" > src/main.rs \
    && cargo build --release --target x86_64-unknown-linux-musl \
    && rm -rf src target/x86_64-unknown-linux-musl/release/deps/* \
           target/x86_64-unknown-linux-musl/release/.fingerprint/*

# Copy real source code
COPY src ./src

# Build final static binary and strip
RUN cargo build --release --target x86_64-unknown-linux-musl \
    && strip target/x86_64-unknown-linux-musl/release/filesystem-server

# ==========================
# Runtime stage: minimal scratch image
# ==========================
FROM scratch

WORKDIR /app

# Copy static binary
COPY --from=builder /app/target/x86_64-unknown-linux-musl/release/filesystem-server /filesystem-server

# Copy CA certs for TLS if needed
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# Expose port
EXPOSE 8084

# Environment
ENV RUST_LOG=info

# Entrypoint
ENTRYPOINT ["/filesystem-server"]
