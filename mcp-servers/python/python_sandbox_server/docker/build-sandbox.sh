#!/bin/bash
# Build script for Python sandbox container

set -euo pipefail

# Build the sandbox container
echo "Building Python sandbox container..."

docker build -t python-sandbox:latest -f Dockerfile.sandbox .

echo "Sandbox container built successfully!"
echo "To test the container:"
echo "  echo 'print(\"Hello from sandbox!\")' > test.py"
echo "  docker run --rm -v \$(pwd)/test.py:/tmp/code.py:ro python-sandbox:latest"

# Optional: Test with gVisor if available
if docker info 2>/dev/null | grep -q "runsc"; then
    echo ""
    echo "gVisor runtime detected. Testing with gVisor:"
    echo "  docker run --rm --runtime=runsc -v \$(pwd)/test.py:/tmp/code.py:ro python-sandbox:latest"
else
    echo ""
    echo "gVisor runtime not detected. Container will run with default runtime."
    echo "For maximum security, consider installing gVisor: https://gvisor.dev/docs/user_guide/install/"
fi
