# Makefile for URL Reputation Plugin (Rust)
# Copyright 2026
# SPDX-License-Identifier: Apache-2.0
#
# Plugin-specific operations for url_reputation
#
# Quick commands:
#   make install      - Build & install url_reputation plugin
#   make test         - Run Rust tests
#   make test-python  - Run Python tests
#   make bench        - Run benchmarks
#   make compare      - Compare Python vs Rust performance

.PHONY: help build dev stub-gen test test-python clean fmt fmt-check clippy check-all bench audit audit-fix doc doc-open coverage install compare uninstall verify

# Default target
.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)URL Reputation Plugin Makefile$(NC)"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Examples:$(NC)"
	@echo "  make install      # Build and install plugin"
	@echo "  make test         # Run Rust tests"
	@echo "  make test-python  # Run Python unit tests"


# Stub generation
stub-gen: ## Generate Python type stubs (.pyi files)
	@echo "$(GREEN)Generating Python type stubs...$(NC)"
	@mkdir -p python/url_reputation_rust
	@cp url_reputation_rust.pyi python/url_reputation_rust/__init__.pyi
	@echo "$(GREEN)Type stubs generated at python/url_reputation_rust/__init__.pyi$(NC)"


# Build targets
build: stub-gen ## Build plugin in release mode
	@echo "$(GREEN)Building url_reputation_rust plugin...$(NC)"
	@cd ../.. && uv run maturin build --release --manifest-path plugins_rust/url_reputation/Cargo.toml

dev: stub-gen ## Build and install plugin in dev mode (faster, no optimizations)
	@echo "$(GREEN)Installing url_reputation_rust plugin (dev mode)...$(NC)"
	@cd ../.. && uv run maturin develop --manifest-path plugins_rust/url_reputation/Cargo.toml
	@echo "$(GREEN)Verifying installation...$(NC)"
	@uv run python -c "import url_reputation_rust; print('✓ url_reputation_rust installed'); print('✓ Module:', url_reputation_rust.__file__)" || { echo "$(RED)Installation verification failed!$(NC)"; exit 1; }

install: stub-gen ## Build and install plugin (maturin develop)
	@echo "$(GREEN)Installing url_reputation_rust plugin...$(NC)"
	@cd ../.. && uv run maturin develop --release --manifest-path plugins_rust/url_reputation/Cargo.toml
	@echo "$(GREEN)Verifying installation...$(NC)"
	@uv run python -c "import url_reputation_rust; print('✓ url_reputation_rust installed'); print('✓ Module:', url_reputation_rust.__file__)" || { echo "$(RED)Installation verification failed!$(NC)"; exit 1; }
	@echo "$(GREEN)Installation verified successfully!$(NC)"

uninstall: ## Uninstall plugin from Python environment
	@echo "$(YELLOW)Uninstalling url_reputation_rust...$(NC)"
	@uv pip uninstall -y url_reputation_rust 2>/dev/null || pip uninstall -y url_reputation_rust 2>/dev/null || true
	@echo "$(GREEN)url_reputation_rust uninstalled$(NC)"

verify: ## Verify plugin installation
	@echo "$(GREEN)Verifying url_reputation_rust installation...$(NC)"
	@uv run python -c "import url_reputation_rust; print('✅ url_reputation_rust available')" || echo "⚠️  url_reputation_rust not installed"


# Testing targets
test: ## Run Rust tests
	@echo "$(GREEN)Running Rust tests...$(NC)"
	cargo test

test-verbose: ## Run Rust tests (verbose)
	@echo "$(GREEN)Running Rust tests (verbose)...$(NC)"
	cargo test --verbose

test-python: ## Run Python tests (requires dev install)
	@echo "$(GREEN)Running Python unit tests...$(NC)"
	cd ../.. && uv run pytest tests -k url_reputation -v

fmt: ## Format code with rustfmt
	@echo "$(GREEN)Formatting code...$(NC)"
	cargo fmt

fmt-check: ## Check code format
	@echo "$(GREEN)Checking code format...$(NC)"
	cargo fmt -- --check

clippy: ## Run clippy linter
	@echo "$(GREEN)Running clippy...$(NC)"
	cargo clippy --all-targets --all-features -- -D warnings

check-all: ## Run all checks (format, lint, test)
	@echo "$(GREEN)Running all checks...$(NC)"
	@$(MAKE) --no-print-directory fmt-check
	@$(MAKE) --no-print-directory clippy
	@$(MAKE) --no-print-directory test

audit: ## Run cargo-audit
	@echo "$(GREEN)Running security audit...$(NC)"
	@command -v cargo-audit >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-audit...$(NC)"; cargo install cargo-audit; }
	cargo audit

audit-fix: ## Fix audit issues
	@echo "$(GREEN)Running security audit with fixes...$(NC)"
	cargo audit fix

# Benchmarks
bench: ## Run Rust benchmarks with criterion
	@echo "$(GREEN)Running benchmarks...$(NC)"
	cargo bench

compare: ## Compare Python vs Rust performance
	@echo "$(GREEN)Comparing Python vs Rust performance...$(NC)"
	cd ../.. && uv run python plugins_rust/url_reputation/compare_performance.py

# Documentation
doc: ## Build Rust docs
	@echo "$(GREEN)Building documentation...$(NC)"
	cargo doc --no-deps --document-private-items

doc-open: doc ## Open docs in browser
	@echo "$(GREEN)Opening documentation...$(NC)"
	xdg-open target/doc/url_reputation_rust/index.html

# Coverage
coverage: ## Generate code coverage using cargo llvm-cov
	@echo "$(GREEN)Generating coverage report using llvm-cov...$(NC)"
	@command -v cargo-llvm-cov >/dev/null 2>&1 || { \
		echo "$(YELLOW)Installing cargo-llvm-cov...$(NC)"; \
		cargo install cargo-llvm-cov; \
	}
	@rm -rf coverage/
	cargo llvm-cov

# Cleaning
clean: ## Clean build artifacts
	@echo "$(YELLOW)Cleaning build artifacts...$(NC)"
	cargo clean
	rm -rf coverage/
	find . -type f -name "*.whl" -delete
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
