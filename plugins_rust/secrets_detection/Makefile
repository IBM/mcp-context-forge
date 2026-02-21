# Makefile for Secrets Detection Plugin (Rust)
# Copyright 2026
# SPDX-License-Identifier: Apache-2.0
#
# Plugin-specific operations for secrets_detection
#
# Quick commands:
#   make install      - Build & install secrets_detection plugin
#   make test         - Test secrets_detection plugin
#   make bench        - Benchmark secrets_detection plugin
#   make compare      - Run Python vs Rust performance comparison

.PHONY: help build dev test clean check lint fmt bench audit doc install compare verify test-integration bench-compare test-all build-target

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
	@echo "$(BLUE)Secrets Detection Plugin Makefile$(NC)"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Examples:$(NC)"
	@echo "  make install      # Build and install plugin"
	@echo "  make test         # Run tests"
	@echo "  make bench        # Run benchmarks"
	@echo "  make compare      # Compare Python vs Rust performance"

# Build targets
stub-gen: ## Generate Python type stubs (.pyi files)
	@echo "$(GREEN)Generating Python type stubs...$(NC)"
	@cargo run --bin stub_gen
	@echo "$(GREEN)Type stubs generated$(NC)"

build-target: stub-gen ## Build for specific target (use TARGET=...)
	@echo "$(GREEN)Building for target: $(TARGET)...$(NC)"
	@uv run maturin build --release --target $(TARGET)
	@echo "$(GREEN)Build complete for $(TARGET)$(NC)"


install: stub-gen
	@echo "$(GREEN)Installing $(PACKAGE_NAME) plugin...$(NC)"
	@cd ../.. && uv run maturin develop --release --manifest-path plugins_rust/secrets_detection/Cargo.toml
	@echo "$(GREEN)Installation complete$(NC)"

# Testing targets
test: ## Run Rust tests for plugin
	@echo "$(GREEN)Running secrets_detection tests...$(NC)"
	cargo test

test-verbose: ## Run plugin tests (verbose)
	@echo "$(GREEN)Running secrets_detection tests (verbose)...$(NC)"
	cargo test --verbose

test-python: ## Run Python unit tests for plugin (requires dev install)
	@echo "$(GREEN)Running Python unit tests...$(NC)"
	cd ../.. && uv run pytest tests -k secrets_detection -v

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
	@echo "$(GREEN)Verifying secrets_detection installation...$(NC)"
	@uv run python -c "import secrets_detection; print('✅ secrets_detection available')" || echo "⚠️  secrets_detection not installed"

test-integration: ## Run integration tests
	@echo "$(GREEN)Running integration tests...$(NC)"
	@cargo test --test '*' --release

# Benchmarking targets
bench: ## Run Rust benchmarks for plugin
	@echo "$(GREEN)Running secrets_detection benchmarks...$(NC)"
	cargo bench

bench-compare: ## Alias for compare
	@$(MAKE) --no-print-directory compare

compare: install ## Run Python vs Rust performance comparison (full)
	@echo "$(GREEN)Running performance comparison (Python vs Rust)...$(NC)"
	@echo "$(YELLOW)Installing plugin first...$(NC)"
	@$(MAKE) --no-print-directory install
	@echo ""
	@echo "$(YELLOW)Running comparison script...$(NC)"
	cd ../../ && uv run python3 plugins_rust/secrets_detection/compare_performance.py

compare-quick: install ## Run Python vs Rust performance comparison (quick)
	@echo "$(GREEN)Running quick performance comparison...$(NC)"
	@echo "$(YELLOW)Installing plugin first...$(NC)"
	@$(MAKE) --no-print-directory install
	@echo ""
	@echo "$(YELLOW)Running comparison script (quick mode)...$(NC)"
	uv run compare_performance.py --iterations 100 --warmup 10

compare-detailed: install ## Run Python vs Rust performance comparison (detailed)
	@echo "$(GREEN)Running detailed performance comparison...$(NC)"
	@echo "$(YELLOW)Installing plugin first...$(NC)"
	@$(MAKE) --no-print-directory install
	@echo ""
	@echo "$(YELLOW)Running comparison script (detailed mode)...$(NC)"
	uv run compare_performance.py --iterations 50000 --warmup 500

test-all: install ## Run all tests: cargo test, integration tests, and performance comparison
	@echo "$(BLUE)Running complete test suite...$(NC)"
	@echo ""
	@echo "$(GREEN)Step 1/4: Installing plugin...$(NC)"
	@$(MAKE) --no-print-directory install
	@echo ""
	@echo "$(GREEN)Step 2/4: Running Rust unit tests...$(NC)"
	cargo test
	@echo ""
	@echo "$(GREEN)Step 3/4: Running Python tests...$(NC)"
	cd ../.. && uv run python -m pytest tests -k secrets_detection -v
	@echo ""
	@echo "$(BLUE)✓ All tests completed successfully!$(NC)"

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
	@command -v cargo-llvm-cov >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-llvm-cov...$(NC)"; cargo install cargo-llvm-cov; }
	@mkdir -p coverage
	cargo llvm-cov --cobertura --output-path coverage/cobertura.xml
	@echo "$(GREEN)Coverage report generated at coverage/cobertura.xml$(NC)"

# Cleaning targets
uninstall: ## Uninstall plugin from Python environment
	@echo "$(YELLOW)Uninstalling secrets_detection...$(NC)"
	@uv pip uninstall -y secrets_detection 2>/dev/null || pip uninstall -y secrets_detection 2>/dev/null || true
	@echo "$(GREEN)secrets_detection uninstalled$(NC)"

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
	@echo "  Name:    secrets_detection"
	@echo "  Version: $$(grep '^version' Cargo.toml | head -1 | cut -d'"' -f2)"
	@echo "  License: Apache-2.0"

deps: ## Install/update dependencies
	@echo "$(GREEN)Installing/updating dependencies...$(NC)"
	@command -v uv >/dev/null 2>&1 && uv pip install maturin || { echo "$(YELLOW)Installing maturin...$(NC)"; uv pip install maturin; }
	@command -v cargo-audit >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-audit...$(NC)"; cargo install cargo-audit; }
	@command -v cargo-tarpaulin >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-tarpaulin...$(NC)"; cargo install cargo-tarpaulin; }
	@echo "$(GREEN)Dependencies installed!$(NC)"

# Watch targets (requires cargo-watch)
watch: ## Watch for changes and run tests
	@command -v cargo-watch >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-watch...$(NC)"; cargo install cargo-watch; }
	cargo watch -x test

watch-dev: ## Watch for changes and rebuild in dev mode
	@command -v cargo-watch >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-watch...$(NC)"; cargo install cargo-watch; }
	cargo watch -s 'make install'

# Performance profiling
flamegraph: ## Generate flamegraph from heavy workload example
	@command -v cargo-flamegraph >/dev/null 2>&1 || { echo "$(YELLOW)Installing cargo-flamegraph...$(NC)"; cargo install flamegraph; }
	@echo "$(GREEN)Generating flamegraph from heavy workload...$(NC)"
	cargo flamegraph --example heavy_workload
	@echo "$(GREEN)Flamegraph saved to: flamegraph.svg$(NC)"
	@echo "$(YELLOW)Open flamegraph.svg in a browser to view the interactive visualization$(NC)"

# Statistics
stats: ## Show code statistics
	@echo "$(BLUE)Code Statistics:$(NC)"
	@echo "  Rust files:  $$(find src -name '*.rs' | wc -l)"
	@echo "  Rust lines:  $$(find src -name '*.rs' -exec cat {} \; | wc -l)"
	@echo "  Bench files: $$(find benches -name '*.rs' 2>/dev/null | wc -l)"
	@echo ""
	@echo "$(BLUE)Dependency Tree:$(NC)"
	@cargo tree --depth 1

# All PHONY targets
.PHONY: help build-target install \
        test test-verbose test-python test-integration test-all \
        fmt fmt-check clippy \
        bench compare compare-quick compare-detailed \
        audit audit-fix \
        doc doc-open \
        coverage \
        clean clean-all \
        info deps \
        watch watch-dev flamegraph stats
