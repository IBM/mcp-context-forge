# Use official Python 3.11 slim image as base
FROM python:3.11-slim

# Install Docker CLI (for container management inside devcontainer)
RUN apt-get update && apt-get install -y \
    docker.io \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Install pip upgrade and pdm (Python package manager used in Makefile)
RUN python3 -m pip install --upgrade pip setuptools pdm uv

# Note: Project files will be mounted by devcontainer, so no need to copy them during build
# Dependencies will be installed via postCreateCommand.sh using make install-dev

# Expose port 4444 for the gateway
EXPOSE 4444

# Default shell
SHELL ["/bin/bash", "-c"]

# Set environment variables for development
ENV MCPGATEWAY_DEV_MODE=true

# Set entrypoint to bash for interactive use
ENTRYPOINT ["/bin/bash"]
