#!/bin/bash
set -e

# Copy .env.example to .env if .env does not exist
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Copied .env.example to .env"
fi

# Install development dependencies using Makefile target
make install-dev

# Run tests to verify setup
# make test

echo "Devcontainer setup complete."

# Activate the virtual environment for the current session
source ~/.venv/mcpgateway/bin/activate
