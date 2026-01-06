###############################################################################
# Rust builder stage - builds Rust plugins in manylinux2014 container
# To build WITH Rust: docker build --build-arg ENABLE_RUST=true .
# To build WITHOUT Rust (default): docker build .
###############################################################################
ARG ENABLE_RUST=false

FROM quay.io/pypa/manylinux2014:2025.12.13-1 AS rust-builder-base
ARG ENABLE_RUST

# Set shell with pipefail for safety
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Only build if ENABLE_RUST=true
RUN if [ "$ENABLE_RUST" != "true" ]; then \
        echo "⏭️  Rust builds disabled (set --build-arg ENABLE_RUST=true to enable)"; \
        mkdir -p /build/plugins_rust/target/wheels; \
        exit 0; \
    fi

# Install Rust toolchain (only if ENABLE_RUST=true)
RUN if [ "$ENABLE_RUST" = "true" ]; then \
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable; \
    fi
ENV PATH="/root/.cargo/bin:$PATH"

WORKDIR /build

# Copy only Rust plugin files (only if ENABLE_RUST=true)
COPY plugins_rust/ /build/plugins_rust/

# Switch to Rust plugin directory
WORKDIR /build/plugins_rust

# Build Rust plugins using Python 3.12 from manylinux image (only if ENABLE_RUST=true)
# The manylinux2014 image has Python 3.12 at /opt/python/cp312-cp312/bin/python
RUN if [ "$ENABLE_RUST" = "true" ]; then \
        rm -rf target/wheels && \
        /opt/python/cp312-cp312/bin/python -m pip install --upgrade pip maturin && \
        /opt/python/cp312-cp312/bin/maturin build --release --compatibility manylinux2014 && \
        echo "✅ Rust plugins built successfully"; \
    else \
        echo "⏭️  Skipping Rust plugin build"; \
    fi

FROM rust-builder-base AS rust-builder

###############################################################################
# Main application stage
###############################################################################
FROM registry.access.redhat.com/ubi10-minimal:10.1-1764604111
LABEL maintainer="Mihai Criveti" \
      name="mcp/mcpgateway" \
      version="1.0.0-BETA-1" \
      description="ContextForge MCP Gateway: An enterprise-ready Model Context Protocol Gateway"

ARG PYTHON_VERSION=3.12
ARG GRPC_PYTHON_BUILD_SYSTEM_OPENSSL='False'

# Install Python and build dependencies
# hadolint ignore=DL3041
RUN microdnf update -y && \
    microdnf install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-devel gcc git openssl-devel postgresql-devel gcc-c++ && \
    microdnf clean all

# Set default python3 to the specified version
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1

WORKDIR /app

# ----------------------------------------------------------------------------
# s390x architecture does not support BoringSSL when building wheel grpcio.
# Force Python whl to use OpenSSL.
# ----------------------------------------------------------------------------
RUN if [ `uname -m` = "s390x" ]; then \
        echo "Building for s390x."; \
        echo "export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL='True'" > /etc/profile.d/use-openssl.sh; \
    else \
        echo "export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL='False'" > /etc/profile.d/use-openssl.sh; \
    fi
RUN chmod 644 /etc/profile.d/use-openssl.sh

# Copy project files into container
COPY . /app

# Copy Rust plugin wheels from builder (if any exist)
COPY --from=rust-builder /build/plugins_rust/target/wheels/ /tmp/rust-wheels/

# Create virtual environment, upgrade pip and install dependencies using uv for speed
# Including observability packages for OpenTelemetry support and Rust plugins (if built)
# Granian is included as an optional high-performance alternative to Gunicorn
ARG ENABLE_RUST=false
RUN python3 -m venv /app/.venv && \
    . /etc/profile.d/use-openssl.sh && \
    /app/.venv/bin/python3 -m pip install --upgrade pip setuptools pdm uv && \
    /app/.venv/bin/python3 -m uv pip install ".[redis,postgres,mysql,alembic,observability,granian]" && \
    if [ "$ENABLE_RUST" = "true" ] && ls /tmp/rust-wheels/*.whl 1> /dev/null 2>&1; then \
        echo "🦀 Installing Rust plugins..."; \
        /app/.venv/bin/python3 -m pip install /tmp/rust-wheels/mcpgateway_rust-*-manylinux*.whl && \
        /app/.venv/bin/python3 -c "from plugins_rust import PIIDetectorRust; print('✓ Rust PII filter installed successfully')"; \
    else \
        echo "⏭️  Rust plugins not available - using Python implementations"; \
    fi && \
    rm -rf /tmp/rust-wheels

# update the user permissions
RUN chown -R 1001:0 /app && \
    chmod -R g=u /app

# Expose the application port
EXPOSE 4444

# Set the runtime user
USER 1001

# Ensure virtual environment binaries are in PATH
ENV PATH="/app/.venv/bin:$PATH"

# HTTP server selection via HTTP_SERVER environment variable:
#   - gunicorn : Python-based with Uvicorn workers (default)
#   - granian  : Rust-based HTTP server (alternative)
#
# Examples:
#   docker run -e HTTP_SERVER=gunicorn mcpgateway  # Default
#   docker run -e HTTP_SERVER=granian mcpgateway   # Alternative
ENV HTTP_SERVER=gunicorn
CMD ["./docker-entrypoint.sh"]
