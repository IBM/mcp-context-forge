FROM registry.access.redhat.com/ubi10-minimal:10.0-1755721767
LABEL maintainer="Mihai Criveti" \
      name="mcp/mcpgateway" \
      version="0.8.0" \
      description="MCP Gateway: An enterprise-ready Model Context Protocol Gateway"

ARG PYTHON_VERSION=3.12
ARG TARGETPLATFORM
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
RUN if [ "$TARGETPLATFORM" = "linux/s390x" ]; then \
        echo "Building for s390x."; \
        echo "export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL='True'" > /etc/profile.d/use-openssl.sh; \
    else \
        echo "export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL='False'" > /etc/profile.d/use-openssl.sh; \
    fi
RUN chmod 644 /etc/profile.d/use-openssl.sh

# Copy project files into container
COPY . /app

# Create virtual environment, upgrade pip and install dependencies using uv for speed
# Including observability packages for OpenTelemetry support
RUN python3 -m venv /app/.venv && \
    . /etc/profile.d/use-openssl.sh && \
    /app/.venv/bin/python3 -m pip install --upgrade pip setuptools pdm uv && \
    /app/.venv/bin/python3 -m uv pip install ".[redis,postgres,mysql,alembic,observability]"

# update the user permissions
RUN chown -R 1001:0 /app && \
    chmod -R g=u /app

# Expose the application port
EXPOSE 4444

# Set the runtime user
USER 1001

# Ensure virtual environment binaries are in PATH
ENV PATH="/app/.venv/bin:$PATH"

# Start the application using run-gunicorn.sh
CMD ["./run-gunicorn.sh"]
