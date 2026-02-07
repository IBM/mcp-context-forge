# Makefile for pii_filter plugin (standalone)
# Copyright 2025
# SPDX-License-Identifier: Apache-2.0
#
# This Makefile is for developing the pii_filter plugin independently.
# For workspace-level operations, use the Makefile in plugins_rust/

.PHONY: help build dev test clean check lint fmt bench audit doc install

# Default target
.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)PII Filter Plugin Makefile (Standalone)$(NC)"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Examples:$(NC)"
	@echo "  make dev          # Build and install pii_filter_rust module"
	@echo "  make test         # Run tests for this plugin only"
	@echo "  make bench        # Run benchmarks for this plugin only"
	@echo "  make check        # Run all checks (fmt, clippy, test)"
	@echo ""
	@echo "$(YELLOW)Note:$(NC) This builds the standalone 'pii_filter_rust' module."
	@echo "      For workspace builds (plugins_rust), use ../Makefile"

# Build targets
build: ## Build release version of pii_filter_rust module
	@echo "$(GREEN)Building pii_filter_rust module (release)...$(NC)"
	maturin build --release --features extension-module

build-debug: ## Build debug version of pii_filter_rust module
	@echo "$(YELLOW)Building pii_filter_rust module (debug)...$(NC)"
	maturin build --features extension-module

dev: ## Build and install pii_filter_rust in development mode (editable)
	@echo "$(GREEN)Building and installing pii_filter_rust in development mode...$(NC)"
	maturin develop --release --features extension-module

dev-debug: ## Build and install debug version in development mode
	@echo "$(YELLOW)Building pii_filter_rust in development mode (debug)...$(NC)"
	maturin develop --features extension-module

install: build ## Build and install pii_filter_rust (non-editable)
	@echo "$(GREEN)Installing pii_filter_rust package...$(NC)"
	pip install --force-reinstall dist/*.whl

# Testing targets
test: ## Run Rust tests for pii_filter only
	@echo "$(GREEN)Running pii_filter tests...$(NC)"
	cargo test --package pii_filter --lib --bins --no-default-features

test-verbose: ## Run Rust tests for pii_filter (verbose)
	@echo "$(GREEN)Running pii_filter tests (verbose)...$(NC)"
	cargo test --package pii_filter --lib --bins --verbose --no-default-features

# Code quality targets
check: fmt clippy test ## Run all checks (format, lint, test)
	@echo "$(GREEN)All checks passed!$(NC)"

fmt: ## Format code with rustfmt
	@echo "$(GREEN)Formatting pii_filter code...$(NC)"
	cargo fmt --package pii_filter

fmt-check: ## Check if code is formatted
	@echo "$(GREEN)Checking pii_filter code format...$(NC)"
	cargo fmt --package pii_filter -- --check

clippy: ## Run clippy linter on pii_filter
	@echo "$(GREEN)Running clippy on pii_filter...$(NC)"
	cargo clippy --package pii_filter --all-targets --all-features -- -D warnings

lint: clippy ## Alias for clippy
	@echo "$(GREEN)Linting completed!$(NC)"

# Benchmarking targets
bench: ## Run Rust benchmarks for pii_filter
	@echo "$(GREEN)Running pii_filter benchmarks...$(NC)"
	cargo bench --package pii_filter --no-default-features

# Security and audit targets
audit: ## Run security audit on pii_filter dependencies
	@echo "$(GREEN)Running security audit...$(NC)"
	@command -v cargo-audit >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-audit...$(NC)"; cargo install cargo-audit; }
	cargo audit

audit-fix: ## Run security audit and apply fixes
	@echo "$(GREEN)Running security audit with fixes...$(NC)"
	cargo audit fix

# Documentation targets
doc: ## Build Rust documentation for pii_filter
	@echo "$(GREEN)Building pii_filter documentation...$(NC)"
	cargo doc --package pii_filter --no-deps --document-private-items

doc-open: doc ## Build and open documentation in browser
	@echo "$(GREEN)Opening pii_filter documentation...$(NC)"
	cargo doc --package pii_filter --no-deps --document-private-items --open

# Coverage targets
coverage: ## Generate code coverage report for pii_filter
	@echo "$(GREEN)Generating pii_filter code coverage...$(NC)"
	@command -v cargo-tarpaulin >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-tarpaulin...$(NC)"; cargo install cargo-tarpaulin; }
	cargo tarpaulin --package pii_filter --lib --no-default-features --out Html --out Xml --output-dir coverage

coverage-open: coverage ## Generate and open coverage report
	@echo "$(GREEN)Opening coverage report...$(NC)"
	@command -v xdg-open >/dev/null 2>&1 && xdg-open coverage/index.html || open coverage/index.html

# Cleaning targets
clean: ## Remove build artifacts for pii_filter
	@echo "$(YELLOW)Cleaning pii_filter build artifacts...$(NC)"
	cargo clean --package pii_filter
	rm -rf dist/
	rm -rf target/wheels/
	rm -rf coverage/
	find . -type f -name "*.whl" -delete
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

clean-all: clean ## Remove all generated files including caches
	@echo "$(RED)Cleaning all generated files...$(NC)"
	rm -rf ~/.cargo/registry/cache/
	rm -rf ~/.cargo/git/db/

# Development workflow targets
dev-cycle: fmt clippy test ## Quick development cycle (format, lint, test)
	@echo "$(GREEN)Development cycle completed!$(NC)"

ci: fmt-check clippy test ## Run CI checks (format check, lint, test)
	@echo "$(GREEN)CI checks passed!$(NC)"

pre-commit: fmt clippy test ## Run pre-commit checks
	@echo "$(GREEN)Pre-commit checks passed!$(NC)"

# Utility targets
verify: ## Verify pii_filter_rust installation
	@echo "$(GREEN)Verifying pii_filter_rust installation...$(NC)"
	@python -c "from pii_filter_rust import PIIDetectorRust; print('✓ pii_filter_rust module available')" && \
		echo "$(GREEN)✓ Installation verified$(NC)" || \
		echo "$(RED)✗ Installation failed - run 'make dev' first$(NC)"

info: ## Show build information
	@echo "$(BLUE)Build Information:$(NC)"
	@echo "  Rust version:    $$(rustc --version)"
	@echo "  Cargo version:   $$(cargo --version)"
	@echo "  Maturin version: $$(maturin --version 2>/dev/null || echo 'not installed')"
	@echo "  Python version:  $$(python --version)"
	@echo ""
	@echo "$(BLUE)Plugin Information:$(NC)"
	@echo "  Name:    pii_filter_rust (standalone)"
	@echo "  Package: pii_filter"
	@echo "  Version: $$(grep '^version' Cargo.toml | head -1 | cut -d'"' -f2 || echo 'unknown')"
	@echo "  License: Apache-2.0"

deps: ## Install/update development dependencies
	@echo "$(GREEN)Installing/updating dependencies...$(NC)"
	@command -v maturin >/dev/null 2>&1 || { echo "$(YELLOW)Installing maturin...$(NC)"; pip install maturin; }
	@command -v cargo-audit >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-audit...$(NC)"; cargo install cargo-audit; }
	@command -v cargo-tarpaulin >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-tarpaulin...$(NC)"; cargo install cargo-tarpaulin; }
	@command -v cargo-upgrade >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-edit (cargo-upgrade)...$(NC)"; cargo install cargo-edit; }
	@command -v cargo-outdated >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-outdated...$(NC)"; cargo install cargo-outdated; }
	@echo "$(GREEN)Dependencies installed!$(NC)"

upgrade-deps-check: ## Check for outdated dependencies (dry-run)
	@echo "$(GREEN)Checking for outdated dependencies...$(NC)"
	@command -v cargo-outdated >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-outdated...$(NC)"; cargo install cargo-outdated; }
	cargo outdated

upgrade-deps: ## Update dependencies to latest versions
	@echo "$(GREEN)Updating Rust dependencies to latest versions...$(NC)"
	@command -v cargo-upgrade >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-edit (cargo-upgrade)...$(NC)"; cargo install cargo-edit; }
	@echo "$(YELLOW)Running cargo upgrade --incompatible...$(NC)"
	cargo upgrade --incompatible
	@echo "$(YELLOW)Updating Cargo.lock...$(NC)"
	cargo update
	@echo "$(YELLOW)Building release to verify compatibility...$(NC)"
	cargo build --release --package pii_filter --features extension-module
	@echo "$(YELLOW)Running tests to verify functionality...$(NC)"
	cargo test --package pii_filter --lib --bins --no-default-features
	@echo "$(GREEN)Dependencies updated successfully!$(NC)"
	@echo "$(YELLOW)Review changes with: git diff Cargo.toml Cargo.lock$(NC)"

# Release targets
release-build: clean ## Build release packages for pii_filter_rust
	@echo "$(GREEN)Building pii_filter_rust release packages...$(NC)"
	maturin build --release --features extension-module --out dist

release-check: fmt-check clippy test audit ## Run all release checks
	@echo "$(GREEN)Release checks passed!$(NC)"

release: release-check release-build ## Full release workflow (checks + build)
	@echo "$(GREEN)Release build completed!$(NC)"
	@echo "$(YELLOW)Wheels created in dist/:$(NC)"
	@ls -lh dist/

# Watch targets (requires cargo-watch)
watch: ## Watch for changes and run tests
	@command -v cargo-watch >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-watch...$(NC)"; cargo install cargo-watch; }
	cargo watch -x 'test --package pii_filter'

watch-dev: ## Watch for changes and rebuild in dev mode
	@command -v cargo-watch >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-watch...$(NC)"; cargo install cargo-watch; }
	cargo watch -s 'maturin develop --features extension-module'

# Performance profiling
profile: ## Profile Rust code with flamegraph
	@command -v cargo-flamegraph >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-flamegraph...$(NC)"; cargo install flamegraph; }
	@echo "$(GREEN)Profiling with flamegraph...$(NC)"
	cargo flamegraph --bench pii_filter

# Statistics
stats: ## Show code statistics for pii_filter
	@echo "$(BLUE)Code Statistics:$(NC)"
	@echo "  Rust files:  $$(find src -name '*.rs' | wc -l)"
	@echo "  Rust lines:  $$(find src -name '*.rs' -exec cat {} \; | wc -l)"
	@echo "  Bench files: $$(find benches -name '*.rs' 2>/dev/null | wc -l)"
	@echo ""
	@echo "$(BLUE)Dependency Tree:$(NC)"
	@cargo tree --package pii_filter --depth 1

# Quick commands
q: dev-cycle ## Quick: format, lint, test (alias for dev-cycle)

qq: fmt test ## Very quick: format and test only (no clippy)

.PHONY: help build build-debug dev dev-debug install \
        test test-verbose \
        check fmt fmt-check clippy lint \
        bench \
        audit audit-fix \
        doc doc-open \
        coverage coverage-open \
        clean clean-all \
        dev-cycle ci pre-commit \
        verify info deps upgrade-deps-check upgrade-deps \
        release-build release-check release \
        watch watch-dev profile stats q qq
