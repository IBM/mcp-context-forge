###############################################################################
# ContextForge (standard) - Full-featured container build
#
# This Dockerfile produces a complete runtime image using ubi10-minimal.
# It includes optional frontend (Vite) and Tailwind CSS builds.
# For a lighter build with optional Rust, see Containerfile.lite.
# For an ultra-slim scratch-based image, see Containerfile.scratch.
###############################################################################

###########################
# Base image overrides — defaults to UBI 10; pass UBI 9 values for FedRAMP builds
#
# FedRAMP/Dreadnought deployments MUST override these with images pulled from
# an approved internal registry.
# Public registry defaults (registry.access.redhat.com) are for standard builds only.
#
# Example (Dreadnought):
#   docker build -f Containerfile \
#     --build-arg ENABLE_FIPS=true \
#     --build-arg NODEJS_IMAGE=<internal-registry>/ubi9/nodejs-20:latest \
#     --build-arg UBI_MINIMAL=<internal-registry>/ubi9/ubi-minimal:latest \
#     .
###########################
ARG NODEJS_IMAGE=registry.access.redhat.com/ubi10/nodejs-24:10.1-1778561468
ARG UBI_MINIMAL=registry.access.redhat.com/ubi10/ubi-minimal:10.1-1778576723

###########################
# Frontend builder stage
###########################
FROM node:lts-alpine AS frontend-builder
WORKDIR /app

# Copy package.json and package-lock.json
COPY package.json package-lock.json ./

# Install frontend dependencies
RUN npm ci

# Copy frontend source files
COPY mcpgateway/admin_ui/ mcpgateway/admin_ui/
COPY vite.config.js ./

# Run Vite build (cleans old bundles and generates fresh manifest)
RUN npm run vite:build

###############################################################################
# Node.js builder stage - builds Tailwind CSS
###############################################################################
# Use official Red Hat UBI10 Node.js 24 image
FROM ${NODEJS_IMAGE} AS node-builder

USER root
RUN mkdir -p /build && chown 1001:0 /build && chmod g=u /build
USER 1001
WORKDIR /build

# Copy only files needed for CSS build (with proper ownership for non-root user)
COPY --chown=1001:1001 package.json package-lock.json* ./
COPY --chown=1001:1001 tailwind.config.js postcss.config.js ./
COPY --chown=1001:1001 mcpgateway/templates/ ./mcpgateway/templates/
COPY --chown=1001:1001 mcpgateway/static/ ./mcpgateway/static/

# Install dependencies and build CSS
RUN npm ci && \
    npm run build:css && \
    echo "✅ Tailwind CSS built successfully"

###############################################################################
# Main application stage
###############################################################################
FROM ${UBI_MINIMAL}
ARG ENABLE_FIPS=false
LABEL maintainer="Mihai Criveti" \
      name="mcp/mcpgateway" \
      version="1.0.0-RC-2" \
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

# Copy Tailwind CSS build artifact from node-builder stage
COPY --from=node-builder /build/mcpgateway/static/css/tailwind.min.css /app/mcpgateway/static/css/


# Create virtual environment, upgrade pip and install dependencies using uv for speed
# Including observability packages for OpenTelemetry support and plugins from PyPI
# Granian is included as an optional high-performance alternative to Gunicorn
RUN python3 -m venv /app/.venv && \
    . /etc/profile.d/use-openssl.sh && \
    /app/.venv/bin/python3 -m pip install --upgrade pip setuptools pdm uv && \
    /app/.venv/bin/python3 -m uv pip install ".[redis,postgres,observability,granian,plugins,llmchat]"

# update the user permissions
RUN chown -R 1001:0 /app && \
    chmod -R g=u /app

# hadolint ignore=DL3041
# FedRAMP compliance block — only active when ENABLE_FIPS=true
# Resolves: FIPS:STIG crypto policy (RHEL-09-215105/672030), SSH ciphers/MACs,
#           gnutls-utils (RHEL-09-215080), nss-tools (RHEL-09-215085),
#           subscription-manager (RHEL-09-215010), pam_wheel (RHEL-09-432035),
#           init file perms 0740 (RHEL-09-232045), home dir perms 0750 (RHEL-09-232050),
#           rootfiles tmpfile.d (RHEL-09-232045), SSH RekeyLimit
#
# NOTE: subscription-manager pulls in UBI9's system python3 (3.9) as a
# dependency, which overwrites /usr/bin/python3 and clobbers the
# python3 -> python${PYTHON_VERSION} symlink set up earlier — surfacing at
# runtime as a misleading "ModuleNotFoundError: No module named 'gunicorn'".
# We re-create the symlink right after the package install below.
RUN if [ "$ENABLE_FIPS" = "true" ]; then \
        if ! grep -q "release 9" /etc/redhat-release 2>/dev/null; then \
            echo "ERROR: ENABLE_FIPS=true requires UBI 9 base images (UBI_MINIMAL must be ubi9/ubi-minimal)" >&2; \
            exit 1; \
        fi; \
        microdnf install -y crypto-policies crypto-policies-scripts rootfiles \
            gnutls-utils nss-tools subscription-manager \
        && microdnf clean all \
        && ln -sf /usr/bin/python${PYTHON_VERSION} /usr/bin/python3 \
        && (test -f /usr/share/crypto-policies/policies/modules/STIG.pmod \
            || printf '# STIG module stub — not shipped in UBI9 minimal\n' \
               > /usr/share/crypto-policies/policies/modules/STIG.pmod) \
        && update-crypto-policies --set FIPS:STIG \
        && mkdir -p /etc/ssh/ssh_config.d /etc/tmpfiles.d /usr/lib/tmpfiles.d /usr/share/rootfiles \
        && echo "RekeyLimit 512M 1h" > /etc/ssh/ssh_config.d/02-rekey-limit.conf \
        && if [ -f /etc/pam.d/su ]; then \
               grep -Eq '^[[:space:]]*auth[[:space:]]+required[[:space:]]+pam_wheel\.so([[:space:]]|$)' /etc/pam.d/su \
               || echo 'auth required pam_wheel.so use_uid' >> /etc/pam.d/su; \
           fi \
        && cp -p /root/.bash_logout /root/.bash_profile /root/.bashrc /root/.cshrc /root/.tcshrc \
               /usr/share/rootfiles/ \
        && printf '%s\n' \
            'C /root/.bash_logout  600 root root - /usr/share/rootfiles/.bash_logout' \
            'C /root/.bash_profile 600 root root - /usr/share/rootfiles/.bash_profile' \
            'C /root/.bashrc       600 root root - /usr/share/rootfiles/.bashrc' \
            'C /root/.cshrc        600 root root - /usr/share/rootfiles/.cshrc' \
            'C /root/.tcshrc       600 root root - /usr/share/rootfiles/.tcshrc' \
            | tee /usr/lib/tmpfiles.d/rootfiles.conf > /etc/tmpfiles.d/rootfiles.conf \
        && find /root -maxdepth 1 -name '.*' -type f -exec chmod 0740 {} \; \
        && chmod 0750 /root \
        && (chgrp 0 /app 2>/dev/null || true) \
        && (chmod 0750 /app 2>/dev/null || true) \
        && (find /app -maxdepth 1 -name '.*' -type f -exec chmod 0740 {} \; 2>/dev/null || true) \
        && find /home -maxdepth 1 -mindepth 1 -type d -exec chmod 0750 {} \; \
        && find /home -maxdepth 2 -name '.*' -type f -exec chmod 0740 {} \;; \
    else \
        echo "ENABLE_FIPS=false — skipping FedRAMP compliance block"; \
    fi

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
