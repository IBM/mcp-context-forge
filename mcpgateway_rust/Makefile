# Makefile for MCP Gateway Rust Workspace
# Copyright 2026
# SPDX-License-Identifier: Apache-2.0
#
# Workspace-level operations for mcpgateway_rust
#
# Quick commands:
#   make build        - Build all workspace crates (release)
#   make test         - Test all workspace crates
#   make install      - Build & install all PyO3 modules
#   make clean        - Clean all build artifacts

.PHONY: help build build-debug dev install test test-verbose test-all \
        clean clean-all check fmt fmt-check clippy audit doc info \
        bench watch stats

# Default target
.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)MCP Gateway Rust Workspace Makefile$(NC)"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Examples:$(NC)"
	@echo "  make build        # Build all crates (release)"
	@echo "  make install      # Build and install all PyO3 modules"
	@echo "  make test         # Run all tests"
	@echo "  make clean        # Clean build artifacts"

# Build targets
build: ## Build all workspace crates in release mode
	@echo "$(GREEN)Building workspace (release)...$(NC)"
	cargo build --workspace --release

build-debug: ## Build all workspace crates in debug mode
	@echo "$(GREEN)Building workspace (debug)...$(NC)"
	cargo build --workspace

dev: build-debug ## Alias for build-debug

install: ## Build and install all PyO3 modules with one command (maturin develop --workspace)
	@echo "$(GREEN)Installing all PyO3 modules (workspace)...$(NC)"
	maturin develop --release
	@echo "$(GREEN)All modules installed successfully!$(NC)"

install-debug: ## Build and install all PyO3 modules (debug mode, workspace)
	@echo "$(GREEN)Installing all PyO3 modules (debug, workspace)...$(NC)"
	maturin develop
	@echo "$(GREEN)Debug installations complete!$(NC)"

# Testing targets
test: ## Run all workspace tests
	@echo "$(GREEN)Running workspace tests...$(NC)"
	cargo test --workspace

test-verbose: ## Run all workspace tests (verbose)
	@echo "$(GREEN)Running workspace tests (verbose)...$(NC)"
	cargo test --workspace --verbose

test-python: install ## Run Python integration tests
	@echo "$(GREEN)Running Python integration tests...$(NC)"
	cd .. && pytest tests/ -v

test-all: install ## Run complete test suite (Rust + Python)
	@echo "$(BLUE)Running complete test suite...$(NC)"
	@echo ""
	@echo "$(GREEN)Step 1/3: Installing modules...$(NC)"
	@$(MAKE) --no-print-directory install
	@echo ""
	@echo "$(GREEN)Step 2/3: Running Rust tests...$(NC)"
	cargo test --workspace
	@echo ""
	@echo "$(GREEN)Step 3/3: Running Python tests...$(NC)"
	cd .. && pytest tests/ -v
	@echo ""
	@echo "$(BLUE)✓ All tests completed successfully!$(NC)"

# Code quality targets
check: ## Run cargo check on workspace
	@echo "$(GREEN)Checking workspace...$(NC)"
	cargo check --workspace

fmt: ## Format all workspace code
	@echo "$(GREEN)Formatting workspace code...$(NC)"
	cargo fmt --all

fmt-check: ## Check if workspace code is formatted
	@echo "$(GREEN)Checking workspace format...$(NC)"
	cargo fmt --all -- --check

clippy: ## Run clippy on workspace
	@echo "$(GREEN)Running clippy on workspace...$(NC)"
	cargo clippy --workspace --all-targets --all-features -- -D warnings

# Benchmarking targets
bench: ## Run all workspace benchmarks
	@echo "$(GREEN)Running workspace benchmarks...$(NC)"
	cargo bench --workspace

bench-a2a: ## Run a2a_service benchmarks only
	@echo "$(GREEN)Running a2a_service benchmarks...$(NC)"
	cd a2a_service && cargo bench

# Security and audit targets
audit: ## Run security audit on workspace
	@echo "$(GREEN)Running security audit...$(NC)"
	@command -v cargo-audit >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-audit...$(NC)"; cargo install cargo-audit; }
	cargo audit

audit-fix: ## Run security audit and apply fixes
	@echo "$(GREEN)Running security audit with fixes...$(NC)"
	cargo audit fix

# Documentation targets
doc: ## Build workspace documentation
	@echo "$(GREEN)Building workspace documentation...$(NC)"
	cargo doc --workspace --no-deps --document-private-items

doc-open: doc ## Build and open workspace documentation
	@echo "$(GREEN)Opening workspace documentation...$(NC)"
	cargo doc --workspace --no-deps --document-private-items --open

# Cleaning targets
clean: ## Remove build artifacts
	@echo "$(YELLOW)Cleaning workspace build artifacts...$(NC)"
	cargo clean
	rm -rf target/
	find . -type f -name "*.whl" -delete
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)Workspace cleaned!$(NC)"

clean-all: clean ## Remove all generated files including caches
	@echo "$(RED)Cleaning all generated files...$(NC)"
	rm -rf ~/.cargo/registry/cache/
	rm -rf ~/.cargo/git/db/

# Information targets
info: ## Show workspace build information
	@echo "$(BLUE)Workspace Information:$(NC)"
	@echo "  Rust version:    $$(rustc --version)"
	@echo "  Cargo version:   $$(cargo --version)"
	@echo "  Maturin version: $$(maturin --version 2>/dev/null || echo 'not installed')"
	@echo "  Python version:  $$(python --version)"
	@echo ""
	@echo "$(BLUE)Workspace Members:$(NC)"
	@cargo metadata --no-deps --format-version 1 | python -c "import sys, json; members = json.load(sys.stdin)['workspace_members']; print('\\n'.join('  - ' + m.split()[0] for m in members))"
	@echo ""
	@echo "$(BLUE)Workspace Version:$(NC)"
	@echo "  Version: $$(grep '^version' Cargo.toml | head -1 | cut -d'"' -f2)"
	@echo "  License: Apache-2.0"

deps: ## Install/update development dependencies
	@echo "$(GREEN)Installing/updating dependencies...$(NC)"
	@command -v maturin >/dev/null 2>&1 || { echo "$(YELLOW)Installing maturin...$(NC)"; pip install maturin; }
	@command -v cargo-audit >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-audit...$(NC)"; cargo install cargo-audit; }
	@command -v cargo-watch >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-watch...$(NC)"; cargo install cargo-watch; }
	@echo "$(GREEN)Dependencies installed!$(NC)"

# Watch targets (requires cargo-watch)
watch: ## Watch for changes and run tests
	@command -v cargo-watch >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-watch...$(NC)"; cargo install cargo-watch; }
	cargo watch -x 'test --workspace'

watch-build: ## Watch for changes and rebuild
	@command -v cargo-watch >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-watch...$(NC)"; cargo install cargo-watch; }
	cargo watch -x 'build --workspace --release'

# Statistics
stats: ## Show workspace statistics
	@echo "$(BLUE)Workspace Statistics:$(NC)"
	@echo "  Total crates:    $$(cargo metadata --no-deps --format-version 1 | python -c "import sys, json; print(len(json.load(sys.stdin)['workspace_members']))")"
	@echo "  Rust files:      $$(find . -name '*.rs' -not -path './target/*' | wc -l)"
	@echo "  Total lines:     $$(find . -name '*.rs' -not -path './target/*' -exec cat {} \; | wc -l)"
	@echo ""
	@echo "$(BLUE)Dependency Tree:$(NC)"
	@cargo tree --workspace --depth 1

# Update targets
update: ## Update workspace dependencies
	@echo "$(GREEN)Updating workspace dependencies...$(NC)"
	cargo update

update-check: ## Check for outdated dependencies
	@echo "$(GREEN)Checking for outdated dependencies...$(NC)"
	@command -v cargo-outdated >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-outdated...$(NC)"; cargo install cargo-outdated; }
	cargo outdated --workspace

# Verify target
verify: fmt-check clippy test ## Run all verification checks (format, clippy, tests)
	@echo "$(GREEN)✓ All verification checks passed!$(NC)"
