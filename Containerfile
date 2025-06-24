FROM registry.access.redhat.com/ubi9-minimal:9.6-1749489516
LABEL maintainer="Mihai Criveti" \
      name="mcp/mcpgateway" \
      version="0.2.0" \
      description="MCP Gateway: An enterprise-ready Model Context Protocol Gateway"

ARG PYTHON_VERSION=3.11

# Install Python and build dependencies
# hadolint ignore=DL3041
RUN microdnf update -y && \
    microdnf install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-devel gcc git && \
    microdnf clean all

# Set default python3 to the specified version
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1

WORKDIR /app

# Copy project files into container
COPY . /app

# Create virtual environment, upgrade pip and install dependencies using uv for speed
RUN python3 -m venv /app/.venv && \
    /app/.venv/bin/python3 -m pip install --upgrade pip setuptools pdm uv && \
    /app/.venv/bin/python3 -m uv pip install ".[redis,postgres]"

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
