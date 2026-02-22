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

.PHONY: help build dev test clean fmt bench audit doc install compare

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


# Build targets
build: ## Build plugin in release mode
	@echo "$(GREEN)Building url_reputation plugin...$(NC)"
	maturin build --release

install: ## Build and install plugin (maturin develop)
	@echo "$(GREEN)Installing url_reputation plugin...$(NC)"
	maturin develop --release
	@echo "$(GREEN)Verifying installation...$(NC)"
	@python -c "import url_reputation; print('✓ url_reputation installed'); print('✓ Module:', url_reputation.__file__)" || { echo "$(RED)Installation verification failed!$(NC)"; exit 1; }
	@echo "$(GREEN)Installation verified successfully!$(NC)"


# Testing targets
test: ## Run Rust tests
	@echo "$(GREEN)Running Rust tests...$(NC)"
	cargo test

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

audit: ## Run cargo-audit
	@echo "$(GREEN)Running security audit...$(NC)"
	@command -v cargo-audit >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-audit...$(NC)"; cargo install cargo-audit; }
	cargo audit

audit-fix: ## Fix audit issues
	@echo "$(GREEN)Running security audit with fixes...$(NC)"
	cargo audit fix

# Documentation
doc: ## Build Rust docs
	@echo "$(GREEN)Building documentation...$(NC)"
	cargo doc --no-deps --document-private-items

doc-open: doc ## Open docs in browser
	@echo "$(GREEN)Opening documentation...$(NC)"
	cargo doc --no-deps --document-private-items --open

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
	rm -rf target/
	rm -rf coverage/
	find . -type f -name "*.whl" -delete
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
