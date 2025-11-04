#!/bin/bash
# schemas/generate_python.sh
# Generate Python classes from protobuf schemas using betterproto
#
# This script generates Pydantic-compatible Python dataclasses from the
# protobuf schemas defined in this directory.
#
# Requirements:
#   - protobuf
#   - protoc (Protocol Buffers compiler)
#
# Usage:
#   ./generate_python.sh [output_dir]
#
# Default output directory: ../mcpgateway/plugins/framework/generated

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Default output directory
OUTPUT_DIR="${1:-../../..}"

echo -e "${GREEN}ContextForge Protobuf to Python Generator${NC}"
echo "=========================================="
echo ""

# Check if google.protobuf is installed
if ! python3 -c "import google.protobuf" 2>/dev/null; then
    echo -e "${RED}Error: protobuf is not installed${NC}"
    echo "Please install it with: pip install protobuf"
    exit 1
fi

# Check if protoc is installed
if ! command -v protoc &> /dev/null; then
    echo -e "${RED}Error: protoc is not installed${NC}"
    echo "Please install Protocol Buffers compiler"
    echo "  macOS: brew install protobuf"
    echo "  Ubuntu: apt-get install protobuf-compiler"
    echo "  Other: https://grpc.io/docs/protoc-installation/"
    exit 1
fi

echo -e "${GREEN}✓${NC} Dependencies found"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"
echo -e "${GREEN}Output directory:${NC} $OUTPUT_DIR"
echo ""

# Generate standard Python protobuf code
echo -e "${GREEN}Generating protobuf Python classes...${NC}"
echo ""

# Using standard protoc Python generator
# Generates _pb2.py files that can be imported and used with Pydantic conversion methods
# Syntax: protoc --python_out=<output_dir> --proto_path=<input_dir> <proto_files>

# Generate from all proto files
protoc \
    --python_out="$OUTPUT_DIR" \
    --proto_path="." \
    mcpgateway/plugins/framework/generated/types.proto \
    mcpgateway/plugins/framework/generated/tools.proto \
    mcpgateway/plugins/framework/generated/prompts.proto \
    mcpgateway/plugins/framework/generated/resources.proto \
    mcpgateway/plugins/framework/generated/agents.proto

echo ""
echo -e "${GREEN}✓${NC} Python classes generated successfully!"
echo ""

# Create __init__.py files for proper Python package structure
echo -e "${GREEN}Creating package structure...${NC}"

# Root __init__.py
cat > "$OUTPUT_DIR/mcpgateway/plugins/framework/generated/__init__.py" << 'EOF'
# -*- coding: utf-8 -*-
"""Generated protobuf Python classes for ContextForge plugins.

This package contains standard protobuf Python classes (_pb2.py files) generated
from protobuf schemas. These are used for cross-language serialization.

The canonical Python implementation uses Pydantic models in mcpgateway.plugins.framework.models
which have model_dump_pb() and model_validate_pb() methods for conversion.

Generated using standard protoc from schemas in protobufs/plugins/schemas/
"""
EOF

echo -e "${GREEN}✓${NC} Package structure created"
echo ""

# Print summary
echo -e "${GREEN}Generation Summary${NC}"
echo "=================="
echo ""
echo "Generated files:"
find "$OUTPUT_DIR" -name "*.py" -type f | while read -r file; do
    echo "  - ${file#$OUTPUT_DIR/}"
done
echo ""

echo -e "${GREEN}✓${NC} All done!"
echo ""
echo "Generated protobuf Python classes (_pb2.py files)."
echo ""
echo "Usage:"
echo "  1. Use Pydantic models from mcpgateway.plugins.framework.models (canonical)"
echo "  2. Convert to protobuf when needed:"
echo "     proto_obj = pydantic_model.model_dump_pb()"
echo "  3. Convert from protobuf:"
echo "     pydantic_model = GlobalContext.model_validate_pb(proto_obj)"
echo ""
echo "The protobuf classes are used for:"
echo "  - Cross-language serialization (Rust, Go, etc.)"
echo "  - Wire protocol for external plugins"
echo "  - Schema documentation and validation"
