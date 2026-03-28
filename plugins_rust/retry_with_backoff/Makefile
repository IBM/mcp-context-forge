# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   🦀 RETRY-WITH-BACKOFF - Makefile
#   Rust-accelerated retry state manager for the retry-with-backoff plugin
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Usage: make <target>  or just `make help`
#
# help: 🦀 RETRY-WITH-BACKOFF (Rust + Python extension build & automation)
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
PACKAGE_NAME    := retry_with_backoff
VERSION         ?= $(shell cargo metadata --format-version 1 --no-deps 2>/dev/null | jq -r '.packages[0].version' || echo "0.1.0")
DIST_DIR        := target
PYTHON          ?= python3

# Colors for output
BLUE  := \033[0;34m
GREEN := \033[0;32m
YELLOW:= \033[0;33m
RED   := \033[0;31m
NC    := \033[0m # No Color

# =============================================================================
# 🔍 LINTING & FORMAT
# =============================================================================
# help: 🔍 LINTING & FORMAT
# help: fmt                   - Format Rust code with rustfmt
# help: fmt-check             - Check Rust code formatting (CI)
# help: clippy                - Run clippy lints
# help: cargo-check           - Run cargo check
.PHONY: fmt fmt-check clippy cargo-check

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
	@echo "$(GREEN)Running retry_with_backoff tests...$(NC)"
	cargo test

test-verbose:
	@echo "$(GREEN)Running retry_with_backoff tests (verbose)...$(NC)"
	cargo test -- --nocapture

test-python:
	@echo "$(GREEN)Running Python unit tests...$(NC)"
	cd ../.. && uv run pytest -k retry_with_backoff -v

test-all: test test-python

# =============================================================================
# 📊 COVERAGE
# =============================================================================
# help: 📊 COVERAGE
# help: coverage-tools        - Install cargo-llvm-cov and llvm-tools-preview
# help: coverage              - Generate code coverage report with llvm-cov
# help: coverage-summary      - Generate code coverage summary (aliases: cs, cov-sum)
.PHONY: coverage-tools coverage cov cv coverage-summary cs cov-sum

coverage-tools:
	@echo "$(GREEN)Installing cargo-llvm-cov and llvm-tools-preview...$(NC)"
	@cargo install cargo-llvm-cov
	@rustup component add llvm-tools-preview
	@echo "$(GREEN)Coverage tools installed$(NC)"

coverage cov cv: coverage-tools
	@echo "$(GREEN)Generating code coverage report...$(NC)"
	@cargo llvm-cov --html --ignore-filename-regex "src/bin/.*"
	@echo "$(GREEN)Coverage report generated at target/llvm-cov/html/index.html$(NC)"
	@xdg-open target/llvm-cov/html/index.html 2>/dev/null || true

coverage-summary cs cov-sum: coverage-tools
	@echo "$(GREEN)Generating code coverage summary...$(NC)"
	@cargo llvm-cov --summary-only --ignore-filename-regex "src/bin/.*"

# =============================================================================
# 🛠 BUILD (maturin for Python extension)
# =============================================================================
# help: 🛠 BUILD
# help: build                 - Build release extension (no install)
# help: build-target          - Build for specific target (use TARGET=...)
# help: stub-gen              - Generate Python type stubs (.pyi files)
# help: install               - Build and install wheel
.PHONY: stub-gen build build-target install

stub-gen:
	@echo "$(GREEN)Generating Python type stubs...$(NC)"
	@cargo run --bin stub_gen
	@echo "$(GREEN)Type stubs generated$(NC)"

build: stub-gen
	@echo "$(GREEN)Building $(PACKAGE_NAME)...$(NC)"
	@cd ../.. && uv run maturin build --release --manifest-path plugins_rust/retry_with_backoff/Cargo.toml
	@echo "$(GREEN)Build complete$(NC)"

build-target: stub-gen
	@echo "$(GREEN)Building for target: $(TARGET)...$(NC)"
	@uv run maturin build --release --target $(TARGET)
	@echo "$(GREEN)Build complete for $(TARGET)$(NC)"

install: stub-gen
	@echo "$(GREEN)Installing $(PACKAGE_NAME) plugin...$(NC)"
	@cd ../.. && uv run maturin develop --release --manifest-path plugins_rust/retry_with_backoff/Cargo.toml
	@echo "$(GREEN)Installation complete$(NC)"

# =============================================================================
# 📊 BENCHMARKS
# =============================================================================
# help: 📊 BENCHMARKS
# help: bench                 - Run Criterion benchmarks (skipped — no benches)
# help: bench-compare         - Compare against baseline
# help: benchmark             - Run Rust vs Python performance comparison
# help: benchmark-quick       - Quick benchmark (100 iterations, 10 warmup)
.PHONY: bench bench-baseline bench-compare compare benchmark benchmark-quick

bench:
	@echo "$(YELLOW)No Criterion benchmarks defined for $(PACKAGE_NAME) — skipping$(NC)"

bench-baseline:
	@echo "$(YELLOW)No benchmarks defined for $(PACKAGE_NAME) — skipping$(NC)"

bench-compare:
	@echo "$(YELLOW)No benchmarks defined for $(PACKAGE_NAME) — skipping$(NC)"

compare: install
	@echo "$(GREEN)Running performance comparison (Python vs Rust)...$(NC)"
	@echo "$(YELLOW)Installing plugin first...$(NC)"
	@$(MAKE) --no-print-directory install
	@echo ""
	@echo "$(YELLOW)Running comparison script...$(NC)"
	cd ../../ && uv run python3 plugins_rust/retry_with_backoff/compare_performance.py

benchmark: install
	@echo "$(GREEN)Running Rust vs Python performance comparison...$(NC)"
	@echo ""
	cd ../../ && uv run python3 plugins_rust/retry_with_backoff/compare_performance.py

benchmark-quick: install
	@echo "$(GREEN)Running quick performance comparison (100 iterations)...$(NC)"
	@echo ""
	cd ../../ && uv run python3 plugins_rust/retry_with_backoff/compare_performance.py --iterations 100 --warmup 10

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
# 🔧 DEVELOPMENT HELPERS
# =============================================================================
# help: 🔧 DEVELOPMENT HELPERS
# help: verify                - Verify plugin installation
# help: check-all             - Run all checks (fmt, clippy, test)
.PHONY: verify check-all

verify:
	@echo "$(GREEN)Verifying $(PACKAGE_NAME) installation...$(NC)"
	@uv run python -c "import retry_with_backoff_rust; print('✅ retry_with_backoff_rust available')" || echo "⚠️  retry_with_backoff_rust not installed"

check-all: fmt-check clippy test
	@echo "$(GREEN)✔ All checks passed$(NC)"

# ---------------------------------------------------------------------------
# Default goal
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
