# Makefile for pii_filter subcrate
# Copyright 2025
# SPDX-License-Identifier: Apache-2.0

.PHONY: help build dev test test-verbose bench fmt fmt-check clippy clean

.DEFAULT_GOAL := help

BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m

help: ## Show this help message
	@echo "$(BLUE)PII Filter Subcrate Makefile$(NC)"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'

build: ## Build pii_filter subcrate (release)
	@echo "$(GREEN)Building pii_filter...$(NC)"
	cargo build --release -p pii_filter

dev: ## Build and install workspace module with pii_filter changes
	@echo "$(GREEN)Building and installing via workspace...$(NC)"
	cd .. && maturin develop --release

test: ## Run pii_filter unit tests
	@echo "$(GREEN)Running pii_filter tests...$(NC)"
	cargo test -p pii_filter

test-verbose: ## Run pii_filter unit tests (verbose)
	@echo "$(GREEN)Running pii_filter tests (verbose)...$(NC)"
	cargo test -p pii_filter --verbose

bench: ## Run pii_filter benchmarks
	@echo "$(GREEN)Running pii_filter benchmarks...$(NC)"
	cargo bench -p pii_filter

fmt: ## Format pii_filter code
	@echo "$(GREEN)Formatting code...$(NC)"
	cargo fmt -p pii_filter

fmt-check: ## Check pii_filter code formatting
	@echo "$(GREEN)Checking code format...$(NC)"
	cargo fmt -p pii_filter -- --check

clippy: ## Run clippy on pii_filter
	@echo "$(GREEN)Running clippy...$(NC)"
	cargo clippy -p pii_filter --all-targets -- -D warnings

clean: ## Remove build artifacts
	@echo "$(YELLOW)Cleaning build artifacts...$(NC)"
	cargo clean -p pii_filter
