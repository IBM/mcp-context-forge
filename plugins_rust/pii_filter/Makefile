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
	cd ../.. && pytest -k pii_filter -v

test-all: test test-python

# =============================================================================
# 🛠 BUILD (maturin for Python extension)
# =============================================================================
# help: 🛠 BUILD
# help: build                 - Build debug Python extension
# help: release               - Build optimized release Python extension
# help: develop               - Install in development mode (editable)
# help: install               - Build and install wheel
.PHONY: build release develop install

build:
	@echo "$(GREEN)Building release Python extension...$(NC)"
	@maturin build --release
	@echo "$(GREEN)Release build complete$(NC)"

build-target:
	@echo "$(GREEN)Building for target: $(TARGET)...$(NC)"
	@maturin build --release --target $(TARGET)
	@echo "$(GREEN)Build complete for $(TARGET)$(NC)"

release:
	@echo "$(GREEN)Building release Python extension...$(NC)"
	@maturin build --release
	@echo "$(GREEN)Release build complete$(NC)"
	@ls -lh $(DIST_DIR)/wheels/*.whl 2>/dev/null || true

develop:
	@echo "$(GREEN)Installing in development mode...$(NC)"
	@maturin develop --release
	@echo "$(GREEN)Development install complete$(NC)"

install: release
	@echo "$(GREEN)Installing wheel...$(NC)"
	@uv pip install --force-reinstall $(DIST_DIR)/wheels/*.whl
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
	@echo "$(GREEN)Saving benchmark baseline...$(NC)"
	@cargo bench -- --save-baseline main

bench-compare:
	@echo "$(GREEN)Comparing against baseline...$(NC)"
	@cargo bench -- --baseline main

compare: bench-compare
	@echo "$(GREEN)Performance comparison complete$(NC)"

# =============================================================================
# 🧹 CLEANUP
# =============================================================================
# help: 🧹 CLEANUP
# help: clean                 - Remove build artifacts
# help: clean-all             - Remove all build artifacts including wheels
.PHONY: clean clean-all

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
# 🔧 DEVELOPMENT HELPERS
# =============================================================================
# help: 🔧 DEVELOPMENT HELPERS
# help: verify                - Verify plugin installation
# help: check-all             - Run all checks (fmt, clippy, test)
# help: test-integration      - Run integration tests
# help: pre-commit            - Run pre-commit checks
.PHONY: verify check-all test-integration pre-commit

verify:
	@echo "$(GREEN)Verifying pii_filter installation...$(NC)"
	@python3 -c "import pii_filter; print('✅ pii_filter available')" || echo "⚠️  pii_filter not installed"

check-all: fmt-check clippy test
	@echo "$(GREEN)✔ All checks passed$(NC)"

test-integration:
	@echo "$(GREEN)Running integration tests...$(NC)"
	@cargo test --test '*' --release

pre-commit: check-all
	@echo "$(GREEN)✔ Ready to commit$(NC)"

# ---------------------------------------------------------------------------
# Default goal
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
