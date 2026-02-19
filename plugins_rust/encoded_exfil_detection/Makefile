# Makefile for Encoded Exfiltration Detection Plugin (Rust)
# Copyright 2025
# SPDX-License-Identifier: Apache-2.0
#
# Plugin-specific operations for encoded_exfil_detection
#
# Quick commands:
#   make install      - Build & install encoded_exfil_detection plugin
#   make test         - Test encoded_exfil_detection plugin
#   make coverage     - Generate code coverage report
#   make compare      - Run performance comparison (if available)

.PHONY: help build dev test clean check lint fmt audit doc install coverage bench bench-compare compare verify test-integration test-all build-target

# Default target
.DEFAULT_GOAL := help

# Project metadata
DIST_DIR := target

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(BLUE)Encoded Exfiltration Detection Plugin Makefile$(NC)"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Examples:$(NC)"
	@echo "  make install      # Build and install plugin"
	@echo "  make test         # Run tests"
	@echo "  make coverage     # Generate coverage report"

# Build targets
stub-gen: ## Generate Python type stubs (.pyi files)
	@echo "$(GREEN)Generating Python type stubs...$(NC)"
	@cargo run --bin stub_gen
	@echo "$(GREEN)Type stubs generated $(NC)"


build-target: stub-gen ## Build for specific target (use TARGET=...)
	@echo "$(GREEN)Building for target: $(TARGET)...$(NC)"
	@cd ../.. && uv run maturin build --release --manifest-path plugins_rust/encoded_exfil_detection/Cargo.toml --target $(TARGET)
	@echo "$(GREEN)Build complete for $(TARGET)$(NC)"

install: stub-gen
	@echo "$(GREEN)Installing $(PACKAGE_NAME) plugin...$(NC)"
	@cd ../.. && uv run maturin develop --release --manifest-path plugins_rust/encoded_exfil_detection/Cargo.toml
	@echo "$(GREEN)Installation complete$(NC)"

# Testing targets
test: ## Run Rust tests for plugin
	@echo "$(GREEN)Running encoded_exfil_detection tests...$(NC)"
	cargo test

test-verbose: ## Run plugin tests (verbose)
	@echo "$(GREEN)Running encoded_exfil_detection tests (verbose)...$(NC)"
	cargo test --verbose

test-python: ## Run Python unit tests for plugin (requires dev install)
	@echo "$(GREEN)Running Python unit tests...$(NC)"
	cd ../.. && uv run pytest tests -k encoded_exfil -v

fmt: ## Format code with rustfmt
	@echo "$(GREEN)Formatting code...$(NC)"
	cargo fmt

fmt-check: ## Check if code is formatted
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

verify: ## Verify plugin installation
	@echo "$(GREEN)Verifying encoded_exfil_detection installation...$(NC)"
	@uv run python -c "import encoded_exfil_detection; print('✅ encoded_exfil_detection available')" || echo "⚠️  encoded_exfil_detection not installed"

test-integration: ## Run integration tests
	@echo "$(GREEN)Running integration tests...$(NC)"
	@cargo test --test '*' --release

test-all: install test test-python ## Run all tests (Rust + Python)
	@echo "$(GREEN)✓ All tests completed successfully$(NC)"

# Benchmarking targets
bench: ## Run Rust benchmarks
	@echo "$(GREEN)Running benchmarks...$(NC)"
	@cargo bench

bench-compare: ## Compare performance (alias for compare)
	@$(MAKE) --no-print-directory compare

compare: install ## Run performance comparison
	@echo "$(GREEN)Running performance comparison...$(NC)"
	@echo "$(YELLOW)Note: This plugin doesn't have a compare_performance.py script yet$(NC)"

# Coverage targets
coverage: install ## Generate code coverage report
	@echo "$(GREEN)Generating code coverage...$(NC)"
	@command -v cargo-llvm-cov >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-llvm-cov...$(NC)"; cargo install cargo-llvm-cov; }
	@echo "$(YELLOW)Building extension with maturin first...$(NC)"
	@$(MAKE) --no-print-directory install
	@echo "$(YELLOW)Running cargo-llvm-cov...$(NC)"
	@mkdir -p coverage
	cargo llvm-cov --cobertura --output-path coverage/cobertura.xml
	@echo "$(GREEN)Coverage report generated at coverage/cobertura.xml$(NC)"

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

# Cleaning targets
uninstall: ## Uninstall plugin from Python environment
	@echo "$(YELLOW)Uninstalling encoded_exfil_detection...$(NC)"
	@uv pip uninstall -y encoded_exfil_detection 2>/dev/null || pip uninstall -y encoded_exfil_detection 2>/dev/null || true
	@echo "$(GREEN)encoded_exfil_detection uninstalled$(NC)"

clean: ## Remove build artifacts
	@echo "$(YELLOW)Cleaning build artifacts...$(NC)"
	cargo clean
	rm -rf target/
	rm -rf coverage/
	find . -type f -name "*.whl" -delete
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

clean-all: clean ## Remove all generated files including caches
	@echo "$(RED)Cleaning all generated files...$(NC)"
	rm -rf ~/.cargo/registry/cache/
	rm -rf ~/.cargo/git/db/

info: ## Show build information
	@echo "$(BLUE)Build Information:$(NC)"
	@echo "  Rust version:    $$(rustc --version)"
	@echo "  Cargo version:   $$(cargo --version)"
	@echo "  Maturin version: $$(uv run maturin --version 2>/dev/null || echo 'not installed')"
	@echo "  Python version:  $$(uv run python --version)"
	@echo ""
	@echo "$(BLUE)Plugin Information:$(NC)"
	@echo "  Name:    encoded_exfil_detection"
	@echo "  Version: $$(grep '^version' Cargo.toml | head -1 | cut -d'"' -f2)"
	@echo "  License: Apache-2.0"

deps: ## Install/update dependencies
	@echo "$(GREEN)Installing/updating dependencies...$(NC)"
	@command -v uv >/dev/null 2>&1 && uv pip install maturin || { echo "$(YELLOW)Installing maturin...$(NC)"; uv pip install maturin; }
	@command -v cargo-audit >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-audit...$(NC)"; cargo install cargo-audit; }
	@command -v cargo-tarpaulin >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-tarpaulin...$(NC)"; cargo install cargo-tarpaulin; }
	@echo "$(GREEN)Dependencies installed!$(NC)"

# All PHONY targets
.PHONY: help install build-target \
        test test-verbose test-python test-integration test-all \
        fmt fmt-check clippy check-all \
        bench bench-compare compare \
        audit audit-fix \
        doc doc-open \
        coverage \
        clean clean-all \
        uninstall verify stub-gen \
        info deps
