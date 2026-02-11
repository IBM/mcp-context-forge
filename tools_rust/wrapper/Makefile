# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   🦀 ContextForge STDIO Wrapper (Rust)
#   High-performance stdio-to-HTTP bridge for ContextForge AI Gateway
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# SPDX-License-Identifier: Apache-2.0
# Usage: run `make` or `make help` to view available targets
#
# help: 🦀 ContextForge STDIO Wrapper (Rust)
#
# ──────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# Binary name
BIN := contextforge-stdio-wrapper

# =============================================================================
# 📖 DYNAMIC HELP
# =============================================================================
.PHONY: help
help:
	@grep "^# help\:" Makefile | grep -v grep | sed 's/\# help\: //' | sed 's/\# help\://'

# =============================================================================
# 🔨 BUILD
# =============================================================================
# help: 🔨 BUILD
# help: build                - Build debug version
# help: build-release        - Build optimized release version (fat LTO)
.PHONY: build build-release
build:
	@echo "🔨  Building debug..."
	@cargo build

build-release:
	@echo "🔨  Building release..."
	@cargo build --release

# =============================================================================
# 🧪 TEST
# =============================================================================
# help: 🧪 TEST
# help: test                 - Run all tests
# help: test-verbose         - Run tests with verbose output
.PHONY: test test-verbose
test:
	@echo "🧪  Running tests..."
	@cargo test

test-verbose:
	@echo "🧪  Running tests (verbose)..."
	@cargo test -- --nocapture

# =============================================================================
# ✅ CODE QUALITY
# =============================================================================
# help: ✅ CODE QUALITY
# help: check                - Run all checks (format, lint, test)
# help: fmt                  - Format code with rustfmt
# help: fmt-check            - Check code formatting (CI mode)
# help: clippy               - Run clippy linter
# help: clippy-pedantic      - Run clippy with pedantic lints
# help: clippy-fix           - Run clippy and auto-fix issues
.PHONY: check fmt fmt-check clippy clippy-pedantic clippy-fix
check: fmt clippy test
	@echo "✅  All checks passed!"

fmt:
	@echo "✏️   Formatting code..."
	@cargo fmt --all

fmt-check:
	@echo "✏️   Checking format..."
	@cargo fmt --all -- --check

clippy:
	@echo "📎  Running clippy..."
	@cargo clippy --all-targets -- -D warnings

clippy-pedantic:
	@echo "📎  Running clippy (pedantic)..."
	@cargo clippy --all-targets -- -W clippy::pedantic

clippy-fix:
	@echo "📎  Running clippy --fix..."
	@cargo clippy --all-targets --fix --allow-dirty -- -W clippy::pedantic

# =============================================================================
# 📊 COVERAGE
# =============================================================================
# help: 📊 COVERAGE
# help: coverage             - Generate HTML code coverage report
# help: coverage-open        - Generate and open coverage report in browser
# help: coverage-summary     - Show coverage summary in terminal
.PHONY: coverage coverage-open coverage-summary
coverage:
	@echo "📊  Generating coverage report..."
	@command -v cargo-llvm-cov >/dev/null 2>&1 || { echo "⬇️   Installing cargo-llvm-cov..."; cargo install cargo-llvm-cov; }
	@rustup component add llvm-tools-preview 2>/dev/null || true
	@cargo llvm-cov --html
	@echo "📁  Report: target/llvm-cov/html/index.html"

coverage-open: coverage
	@command -v xdg-open >/dev/null 2>&1 && xdg-open target/llvm-cov/html/index.html || open target/llvm-cov/html/index.html

coverage-summary:
	@command -v cargo-llvm-cov >/dev/null 2>&1 || { echo "⬇️   Installing cargo-llvm-cov..."; cargo install cargo-llvm-cov; }
	@cargo llvm-cov

# =============================================================================
# 🔐 SECURITY & LICENSES
# =============================================================================
# help: 🔐 SECURITY & LICENSES
# help: licenses             - Check dependency licenses (deny.toml)
# help: audit                - Run security audit on dependencies
.PHONY: licenses audit
licenses:
	@echo "🔐  Checking licenses..."
	@command -v cargo-deny >/dev/null 2>&1 || { echo "⬇️   Installing cargo-deny..."; cargo install cargo-deny; }
	@cargo deny check licenses

audit:
	@echo "🔐  Running security audit..."
	@command -v cargo-audit >/dev/null 2>&1 || { echo "⬇️   Installing cargo-audit..."; cargo install cargo-audit; }
	@cargo audit

# =============================================================================
# 📖 DOCUMENTATION
# =============================================================================
# help: 📖 DOCUMENTATION
# help: doc                  - Build Rust documentation
# help: doc-open             - Build and open documentation in browser
.PHONY: doc doc-open
doc:
	@echo "📖  Building docs..."
	@cargo doc --no-deps --document-private-items

doc-open: doc
	@cargo doc --no-deps --document-private-items --open

# =============================================================================
# 📦 DEPENDENCY MANAGEMENT
# =============================================================================
# help: 📦 DEPENDENCY MANAGEMENT
# help: deps-tree            - Show dependency tree
# help: deps-outdated        - Check for outdated dependencies
# help: deps-update          - Update dependencies to latest compatible versions
.PHONY: deps-tree deps-outdated deps-update
deps-tree:
	@cargo tree --depth 1

deps-outdated:
	@command -v cargo-outdated >/dev/null 2>&1 || { echo "⬇️   Installing cargo-outdated..."; cargo install cargo-outdated; }
	@cargo outdated

deps-update:
	@echo "📦  Updating dependencies..."
	@cargo update
	@echo "💡  Review changes: git diff Cargo.lock"

# =============================================================================
# 🧹 CLEAN
# =============================================================================
# help: 🧹 CLEAN
# help: clean                - Remove build artifacts
.PHONY: clean
clean:
	@echo "🧹  Cleaning..."
	@cargo clean

# =============================================================================
# 🔄 DEVELOPMENT WORKFLOWS
# =============================================================================
# help: 🔄 DEVELOPMENT WORKFLOWS
# help: dev-cycle            - Quick dev cycle (format, lint, test)
# help: ci                   - CI pipeline (format check, lint, test, licenses)
# help: watch                - Watch for changes and run tests automatically
.PHONY: dev-cycle ci watch
dev-cycle: fmt clippy test
	@echo "✅  Dev cycle passed!"

ci: fmt-check clippy test licenses
	@echo "✅  CI checks passed!"

watch:
	@command -v cargo-watch >/dev/null 2>&1 || { echo "⬇️   Installing cargo-watch..."; cargo install cargo-watch; }
	@cargo watch -x test

# =============================================================================
# ℹ️  INFO
# =============================================================================
# help: ℹ️  INFO
# help: info                 - Show build and project information
# help: stats                - Show code statistics
.PHONY: info stats
info:
	@echo "ℹ️   Build Information:"
	@echo "  Rust:    $$(rustc --version)"
	@echo "  Cargo:   $$(cargo --version)"
	@echo ""
	@echo "ℹ️   Project:"
	@echo "  Name:    $(BIN)"
	@echo "  Version: $$(grep '^version' Cargo.toml | head -1 | cut -d'"' -f2)"
	@echo "  License: $$(grep '^license' Cargo.toml | head -1 | cut -d'"' -f2)"

stats:
	@echo "📈  Code Statistics:"
	@echo "  Source files: $$(find src -name '*.rs' | wc -l)"
	@echo "  Source lines: $$(find src -name '*.rs' -exec cat {} + | wc -l)"
	@echo "  Test files:   $$(find tests -name '*.rs' | wc -l)"
	@echo "  Test lines:   $$(find tests -name '*.rs' -exec cat {} + | wc -l)"
