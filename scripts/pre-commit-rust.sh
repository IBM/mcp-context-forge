#!/usr/bin/env bash
# Run Rust checks (fmt, build, clippy) when Rust is installed. Skip silently otherwise.
# Used by pre-commit; mirrors CI checks from .github/workflows/rust.yml.

set -e

if ! command -v cargo >/dev/null 2>&1; then
  exit 0
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -f "$root/Cargo.toml" ]; then
  exit 0
fi

cd "$root"

echo "🦀 Rust pre-commit: fmt (fix if needed)..."
cargo fmt --all
if [ -n "$(git diff --name-only)" ]; then
  echo "🦀 Rust format was applied; please re-stage modified files and commit again."
  exit 1
fi

echo "🦀 Rust pre-commit: build..."
cargo build --workspace

echo "🦀 Rust pre-commit: clippy..."
cargo clippy --workspace --all-targets -- -D warnings

echo "✅ Rust pre-commit passed"
