#!/usr/bin/env bash
set -euo pipefail

# Run the full Rust workspace pipeline via Makefile (rust-full-check).
# Skip silently if Rust or Cargo.toml are not available (e.g., partial checkouts).

if ! command -v cargo >/dev/null 2>&1; then
  exit 0
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -f "$root/Cargo.toml" ]; then
  exit 0
fi

cd "$root"

echo "🦀 Rust pre-commit: full workspace check (rust-full-check)..."
make rust-full-check
