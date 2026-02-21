# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   🦀 PII-FILTER - Makefile
#   High-performance PII detection and masking library (Rust + Python)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Usage: make <target>  or just `make help`
#
# help: 🦀 PII-FILTER (Rust + Python extension build & automation)
# ─────────────────────────────────────────────────────────────────────────

# =============================================================================
# 📖 DYNAMIC HELP
# =============================================================================
.PHONY: help
help:
	@grep '^# help\:' $(firstword $(MAKEFILE_LIST)) | sed 's/^# help\: //'

# =============================================================================
# 📦 PROJECT METADATA
# =============================================================================
PACKAGE_NAME    := pii_filter
VERSION         ?= $(shell cargo metadata --format-version 1 --no-deps 2>/dev/null | jq -r '.packages[0].version' || echo "1.0.0-RC-1")
DIST_DIR        := target
PYTHON          ?= python3

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

# Legacy color names for compatibility
ifeq ($(shell test -t 1 && echo tty),tty)
C_BLUE  := \033[38;5;75m
C_GREEN := \033[38;5;82m
C_RESET := \033[0m
else
C_BLUE  :=
C_GREEN :=
C_RESET :=
endif

# =============================================================================
# 🔍 LINTING & FORMAT
# =============================================================================
# help: 🔍 LINTING & FORMAT
# help: fmt                   - Format Rust code with rustfmt
# help: fmt-check             - Check Rust code formatting (CI)
# help: clippy                - Run clippy lints
# help: cargo-check           - Run cargo check
.PHONY: fmt fmt-check clippy cargo-check build-target

fmt:
	@echo "$(GREEN)Formatting code...$(NC)"
	cargo fmt

fmt-check:
	@echo "$(GREEN)Checking code format...$(NC)"
	cargo fmt -- --check

clippy:
	@echo "$(GREEN)Running clippy...$(NC)"
	cargo clippy -- -D warnings

cargo-check:
	@cargo check

# =============================================================================
# 🧪 TESTS
# =============================================================================
# help: 🧪 TESTS
# help: test                  - Run Rust unit tests
# help: test-verbose          - Run Rust tests with verbose output
# help: test-python           - Run Python integration tests
# help: test-all              - Run both Rust and Python tests
.PHONY: test test-verbose test-python test-all

test:
	@echo "$(GREEN)Running pii_filter tests...$(NC)"
	cargo test

test-verbose:
	@echo "$(GREEN)Running pii_filter tests (verbose)...$(NC)"
	cargo test -- --nocapture

test-python: ## Run Python unit tests for plugin (requires dev install)
	@echo "$(GREEN)Running Python unit tests...$(NC)"
	cd ../.. && uv run pytest -k pii_filter -v

test-all: test test-python

# =============================================================================
# 🛠 BUILD (maturin for Python extension)
# =============================================================================
# help: 🛠 BUILD
# help: stub-gen              - Generate Python type stubs (.pyi files)
# help: build-target        - Build for specific target (use TARGET=...)
# help: install               - Build and install wheel
.PHONY: stub-gen build-target install

stub-gen:
	@echo "$(GREEN)Generating Python type stubs...$(NC)"
	@cargo run --bin stub_gen
	@echo "$(GREEN)Type stubs generated$(NC)"

build-target: stub-gen
	@echo "$(GREEN)Building for target: $(TARGET)...$(NC)"
	@uv run maturin build --release --target $(TARGET)
	@echo "$(GREEN)Build complete for $(TARGET)$(NC)"


install: stub-gen
	@echo "$(GREEN)Installing $(PACKAGE_NAME) plugin...$(NC)"
	@cd ../.. && uv run maturin develop --release --manifest-path plugins_rust/pii_filter/Cargo.toml
	@echo "$(GREEN)Installation complete$(NC)"

# =============================================================================
# 📊 BENCHMARKS
# =============================================================================
# help: 📊 BENCHMARKS
# help: bench                 - Run Criterion benchmarks
# help: bench-baseline        - Save benchmark baseline
# help: bench-compare         - Compare against baseline
.PHONY: bench bench-baseline bench-compare compare

bench:
	@echo "$(GREEN)Running benchmarks...$(NC)"
	@cargo bench

bench-baseline:
	@echo "$(GREEN)Running benchmarks...$(NC)"
	@cargo bench

bench-compare:
	@echo "$(GREEN)Running benchmarks...$(NC)"
	@cargo bench

compare: install ## Run performance comparison (skip benchmarks)
	@echo "$(GREEN)Running performance comparison...$(NC)"
	@echo "$(YELLOW)Note: This plugin doesn't have a compare_performance.py script yet$(NC)"

# =============================================================================
# 🧹 CLEANUP
# =============================================================================
# help: 🧹 CLEANUP
# help: clean                 - Remove build artifacts
# help: clean-all             - Remove all build artifacts including wheels
# help: uninstall             - Uninstall plugin from Python environment
.PHONY: clean clean-all uninstall

uninstall:
	@echo "$(YELLOW)Uninstalling $(PACKAGE_NAME)...$(NC)"
	@uv pip uninstall -y $(PACKAGE_NAME) 2>/dev/null || pip uninstall -y $(PACKAGE_NAME) 2>/dev/null || true
	@echo "$(GREEN)$(PACKAGE_NAME) uninstalled$(NC)"

clean:
	@echo "$(YELLOW)Cleaning build artifacts...$(NC)"
	cargo clean
	rm -rf target/
	rm -rf coverage/
	find . -type f -name "*.whl" -delete
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

clean-all: clean
	@echo "$(RED)Cleaning all generated files...$(NC)"
	rm -rf ~/.cargo/registry/cache/
	rm -rf ~/.cargo/git/db/

# =============================================================================
# 📚 DOCUMENTATION
# =============================================================================
# help: 📚 DOCUMENTATION
# help: doc                   - Generate Rust documentation
# help: doc-open              - Generate and open documentation
.PHONY: doc doc-open

doc:
	@echo "$(GREEN)Building documentation...$(NC)"
	cargo doc --no-deps --document-private-items

doc-open: doc
	@echo "$(GREEN)Opening documentation...$(NC)"
	cargo doc --no-deps --document-private-items --open

# =============================================================================
# � DEVELOPMENT HELPERS
# =============================================================================
# help: 🔧 DEVELOPMENT HELPERS
# help: verify                - Verify plugin installation
# help: check-all             - Run all checks (fmt, clippy, test)
# help: test-integration      - Run integration tests
# help: pre-commit            - Run pre-commit checks
.PHONY: verify check-all test-integration pre-commit

verify:
	@echo "$(GREEN)Verifying pii_filter installation...$(NC)"
	@uv run python -c "import pii_filter; print('✅ pii_filter available')" || echo "⚠️  pii_filter not installed"

check-all: fmt-check clippy test
	@echo "$(GREEN)✔ All checks passed$(NC)"

pre-commit: check-all
	@echo "$(GREEN)✔ Ready to commit$(NC)"

# ---------------------------------------------------------------------------
# Default goal
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
