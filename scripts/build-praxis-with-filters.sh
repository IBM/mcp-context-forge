#!/bin/bash
# Build Praxis server with ContextForge MCP dataplane filters
# This script temporarily modifies Praxis server's Cargo.toml to include
# the praxis_cf_dataplane filter library, builds the binary, and copies
# it to this repository's bin/ directory.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PRAXIS_SERVER_DIR="$REPO_ROOT/../praxis/server"
FILTER_CRATE_PATH="$REPO_ROOT/praxis_cf_dataplane"
OUTPUT_DIR="$REPO_ROOT/build/bin"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Building Praxis server with ContextForge filters...${NC}"

# Verify Praxis server directory exists
if [ ! -d "$PRAXIS_SERVER_DIR" ]; then
    echo -e "${RED}Error: Praxis server directory not found at $PRAXIS_SERVER_DIR${NC}"
    echo "Please clone Praxis repository to ../praxis"
    exit 1
fi

# Verify filter crate exists
if [ ! -d "$FILTER_CRATE_PATH" ]; then
    echo -e "${RED}Error: Filter crate not found at $FILTER_CRATE_PATH${NC}"
    exit 1
fi

# Check if dependency already exists
if grep -q "praxis_cf_dataplane" "$PRAXIS_SERVER_DIR/Cargo.toml"; then
    echo -e "${YELLOW}Dependency already exists in Praxis server Cargo.toml${NC}"
else
    echo "Adding praxis_cf_dataplane dependency to Praxis server..."
    # Add dependency after the tracing line using computed path
    FILTER_CRATE_REALPATH="$(realpath "$FILTER_CRATE_PATH")"
    sed -i.bak '/^tracing = { workspace = true }$/a\
praxis_cf_dataplane = { path = "'"$FILTER_CRATE_REALPATH"'" }
' "$PRAXIS_SERVER_DIR/Cargo.toml"
    echo -e "${GREEN}Dependency added${NC}"
fi

# Build Praxis server
echo "Building Praxis server (this may take a few minutes)..."
cd "$PRAXIS_SERVER_DIR"
cargo build --release

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Copy binary (built in workspace root target directory)
echo "Copying binary to $OUTPUT_DIR..."
PRAXIS_ROOT="$(cd "$PRAXIS_SERVER_DIR/.." && pwd)"
cp "$PRAXIS_ROOT/target/release/praxis" "$OUTPUT_DIR/praxis"

echo -e "${GREEN}Build complete!${NC}"
echo "Binary location: $OUTPUT_DIR/praxis"
echo ""
echo "To run the server:"
echo "  $OUTPUT_DIR/praxis -c /path/to/praxis.yaml"
echo ""
echo "To restore Praxis server Cargo.toml:"
echo "  cd $PRAXIS_SERVER_DIR && mv Cargo.toml.bak Cargo.toml"
