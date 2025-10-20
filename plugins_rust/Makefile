# Makefile for Rust plugins
# Copyright 2025
# SPDX-License-Identifier: Apache-2.0

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
	@echo "$(BLUE)Rust Plugins Makefile$(NC)"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Examples:$(NC)"
	@echo "  make dev          # Build and install in development mode"
	@echo "  make test         # Run all tests"
	@echo "  make bench        # Run benchmarks"
	@echo "  make check        # Run all checks (fmt, clippy, test)"

# Build targets
build: ## Build release version
	@echo "$(GREEN)Building release version...$(NC)"
	maturin build --release

build-debug: ## Build debug version
	@echo "$(YELLOW)Building debug version...$(NC)"
	maturin build

dev: ## Build and install in development mode (editable)
	@echo "$(GREEN)Building and installing in development mode...$(NC)"
	maturin develop --release

dev-debug: ## Build and install debug version in development mode
	@echo "$(YELLOW)Building debug version in development mode...$(NC)"
	maturin develop

install: build ## Build and install (non-editable)
	@echo "$(GREEN)Installing built package...$(NC)"
	pip install --force-reinstall dist/*.whl

# Testing targets
test: ## Run all Rust tests (unit tests only, excludes integration tests requiring Python)
	@echo "$(GREEN)Running Rust tests...$(NC)"
	cargo test --lib --bins --verbose --no-default-features

test-integration: dev ## Run integration tests (requires Python module built)
	@echo "$(GREEN)Running integration tests (with Python module)...$(NC)"
	cargo test --test integration --verbose

test-python: ## Run Python tests (requires dev install)
	@echo "$(GREEN)Running Python unit tests...$(NC)"
	cd .. && pytest tests/unit/mcpgateway/plugins/test_pii_filter_rust.py -v

test-differential: ## Run differential tests (Rust vs Python)
	@echo "$(GREEN)Running differential tests...$(NC)"
	cd .. && pytest tests/differential/test_pii_filter_differential.py -v

test-all: test test-integration test-python test-differential ## Run all tests (Rust + Python)
	@echo "$(GREEN)All tests completed!$(NC)"

# Code quality targets
check: fmt clippy test ## Run all checks (format, lint, test)
	@echo "$(GREEN)All checks passed!$(NC)"

fmt: ## Format code with rustfmt
	@echo "$(GREEN)Formatting code...$(NC)"
	cargo fmt --all

fmt-check: ## Check if code is formatted
	@echo "$(GREEN)Checking code format...$(NC)"
	cargo fmt --all -- --check

clippy: ## Run clippy linter
	@echo "$(GREEN)Running clippy...$(NC)"
	cargo clippy --all-targets --all-features -- -D warnings

lint: clippy ## Alias for clippy
	@echo "$(GREEN)Linting completed!$(NC)"

# Benchmarking targets
bench: ## Run Rust benchmarks with Criterion
	@echo "$(GREEN)Running Rust benchmarks...$(NC)"
	cargo bench

bench-compare: dev ## Run Python comparison benchmarks
	@echo "$(GREEN)Running Python vs Rust comparison...$(NC)"
	cd .. && python benchmarks/compare_pii_filter.py

bench-save: dev ## Run benchmarks and save results
	@echo "$(GREEN)Running benchmarks and saving results...$(NC)"
	cd .. && python benchmarks/compare_pii_filter.py --output benchmark-results.json
	@echo "$(GREEN)Results saved to ../benchmark-results.json$(NC)"

bench-all: bench bench-compare ## Run all benchmarks (Rust + Python comparison)
	@echo "$(GREEN)All benchmarks completed!$(NC)"

# Security and audit targets
audit: ## Run security audit with cargo-audit
	@echo "$(GREEN)Running security audit...$(NC)"
	@command -v cargo-audit >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-audit...$(NC)"; cargo install cargo-audit; }
	cargo audit

audit-fix: ## Run security audit and apply fixes
	@echo "$(GREEN)Running security audit with fixes...$(NC)"
	cargo audit fix

# Documentation targets
doc: ## Build Rust documentation
	@echo "$(GREEN)Building documentation...$(NC)"
	cargo doc --no-deps --document-private-items

doc-open: doc ## Build and open documentation in browser
	@echo "$(GREEN)Opening documentation...$(NC)"
	cargo doc --no-deps --document-private-items --open

# Coverage targets
coverage: ## Generate code coverage report
	@echo "$(GREEN)Generating code coverage...$(NC)"
	@command -v cargo-tarpaulin >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-tarpaulin...$(NC)"; cargo install cargo-tarpaulin; }
	cargo tarpaulin --out Html --out Xml --output-dir coverage

coverage-open: coverage ## Generate and open coverage report
	@echo "$(GREEN)Opening coverage report...$(NC)"
	@command -v xdg-open >/dev/null 2>&1 && xdg-open coverage/index.html || open coverage/index.html

# Cleaning targets
clean: ## Remove build artifacts
	@echo "$(YELLOW)Cleaning build artifacts...$(NC)"
	cargo clean
	rm -rf dist/
	rm -rf target/
	rm -rf coverage/
	rm -f Cargo.lock
	find . -type f -name "*.whl" -delete
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(YELLOW)Cleaning benchmark results...$(NC)"
	rm -f benchmarks/results/*.json
	rm -f benchmarks/results/*.csv

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
verify: ## Verify installation
	@echo "$(GREEN)Verifying Rust installation...$(NC)"
	@python -c "from plugins_rust import PIIDetectorRust; print('✓ Rust PII filter available')" && \
		echo "$(GREEN)✓ Installation verified$(NC)" || \
		echo "$(RED)✗ Installation failed - run 'make dev' first$(NC)"

info: ## Show build information
	@echo "$(BLUE)Build Information:$(NC)"
	@echo "  Rust version:    $$(rustc --version)"
	@echo "  Cargo version:   $$(cargo --version)"
	@echo "  Maturin version: $$(maturin --version 2>/dev/null || echo 'not installed')"
	@echo "  Python version:  $$(python --version)"
	@echo ""
	@echo "$(BLUE)Project Information:$(NC)"
	@echo "  Name:    plugins_rust"
	@echo "  Version: $$(grep '^version' Cargo.toml | head -1 | cut -d'"' -f2)"
	@echo "  License: Apache-2.0"

deps: ## Install/update dependencies
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
	cargo build --release
	@echo "$(YELLOW)Running tests to verify functionality...$(NC)"
	cargo test --lib --bins --no-default-features
	@echo "$(GREEN)Dependencies updated successfully!$(NC)"
	@echo "$(YELLOW)Review changes with: git diff Cargo.toml Cargo.lock$(NC)"

# Release targets
release-build: clean ## Build release packages for all platforms
	@echo "$(GREEN)Building release packages...$(NC)"
	maturin build --release --out dist

release-check: fmt-check clippy test audit ## Run all release checks
	@echo "$(GREEN)Release checks passed!$(NC)"

release: release-check release-build ## Full release workflow (checks + build)
	@echo "$(GREEN)Release build completed!$(NC)"
	@echo "$(YELLOW)Wheels created in dist/:$(NC)"
	@ls -lh dist/

# Watch targets (requires cargo-watch)
watch: ## Watch for changes and run tests
	@command -v cargo-watch >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-watch...$(NC)"; cargo install cargo-watch; }
	cargo watch -x test

watch-dev: ## Watch for changes and rebuild in dev mode
	@command -v cargo-watch >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-watch...$(NC)"; cargo install cargo-watch; }
	cargo watch -x 'maturin develop'

# Performance profiling
profile: ## Profile Rust code with flamegraph
	@command -v cargo-flamegraph >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-flamegraph...$(NC)"; cargo install flamegraph; }
	@echo "$(GREEN)Profiling with flamegraph...$(NC)"
	cargo flamegraph --bench pii_filter

# Statistics
stats: ## Show code statistics
	@echo "$(BLUE)Code Statistics:$(NC)"
	@echo "  Rust files:  $$(find src -name '*.rs' | wc -l)"
	@echo "  Rust lines:  $$(find src -name '*.rs' -exec cat {} \; | wc -l)"
	@echo "  Test files:  $$(find tests -name '*.rs' | wc -l)"
	@echo "  Test lines:  $$(find tests -name '*.rs' -exec cat {} \; | wc -l)"
	@echo "  Bench files: $$(find benches -name '*.rs' 2>/dev/null | wc -l)"
	@echo ""
	@echo "$(BLUE)Dependency Tree:$(NC)"
	@cargo tree --depth 1

# Quick commands
q: dev-cycle ## Quick: format, lint, test (alias for dev-cycle)

qq: fmt test ## Very quick: format and test only (no clippy)

.PHONY: help build build-debug dev dev-debug install \
        test test-integration test-python test-differential test-all \
        check fmt fmt-check clippy lint \
        bench bench-compare bench-save bench-all \
        audit audit-fix \
        doc doc-open \
        coverage coverage-open \
        clean clean-all \
        dev-cycle ci pre-commit \
        verify info deps upgrade-deps-check upgrade-deps \
        release-build release-check release \
        watch watch-dev profile stats q qq
