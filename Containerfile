###########################
# Frontend builder stage
###########################
FROM node:lts-alpine AS frontend-builder
WORKDIR /app

# Copy package.json and package-lock.json
COPY package.json package-lock.json ./

# Install frontend dependencies
RUN npm install --frozen-lockfile

# Copy frontend source files
COPY mcpgateway/admin_ui/ mcpgateway/admin_ui/
COPY vite.config.js ./

# Run Vite build (cleans old bundles and generates fresh manifest)
RUN npm run vite:build

###############################################################################
# Main application stage
###############################################################################
FROM registry.access.redhat.com/ubi10/ubi-minimal:10.1-1776071394
LABEL maintainer="Mihai Criveti" \
      name="mcp/mcpgateway" \
      version="1.0.0-RC-3" \
      description="ContextForge: An enterprise-ready Model Context Protocol Gateway"

ARG PYTHON_VERSION=3.12

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
# NOTE: ppc64le has the same OpenSSL requirement
# ----------------------------------------------------------------------------
RUN if [ "$(uname -m)" = "s390x" ] || [ "$(uname -m)" = "ppc64le" ]; then \
        echo "Building for $(uname -m)."; \
        echo "export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL='True'" > /etc/profile.d/use-openssl.sh; \
    else \
        echo "export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL='False'" > /etc/profile.d/use-openssl.sh; \
    fi
RUN chmod 644 /etc/profile.d/use-openssl.sh

# Copy project files into container
COPY . /app

# Copy frontend build artifacts from frontend-builder stage
COPY --from=frontend-builder /app/mcpgateway/static/ /app/mcpgateway/static/

# Create virtual environment, upgrade pip and install dependencies using uv for speed
# Including observability packages for OpenTelemetry support and plugins from PyPI
# Granian is included as an optional high-performance alternative to Gunicorn
RUN python3 -m venv /app/.venv && \
    . /etc/profile.d/use-openssl.sh && \
    /app/.venv/bin/python3 -m pip install --upgrade pip setuptools pdm uv && \
    /app/.venv/bin/python3 -m uv pip install ".[redis,postgres,observability,granian,plugins]"

# update the user permissions
RUN chown -R 1001:0 /app && \
    chmod -R g=u /app

# Expose the application port
EXPOSE 4444

# Set the runtime user
USER 1001

# Ensure virtual environment binaries are in PATH and project modules resolve
# even when containers run an alternate Python entrypoint.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

# HTTP server selection via HTTP_SERVER environment variable:
#   - gunicorn : Python-based with Uvicorn workers (default)
#   - granian  : Rust-based HTTP server (alternative)
#
# Examples:
#   docker run -e HTTP_SERVER=gunicorn mcpgateway  # Default
#   docker run -e HTTP_SERVER=granian mcpgateway   # Alternative
ENV HTTP_SERVER=gunicorn
CMD ["./docker-entrypoint.sh"]
