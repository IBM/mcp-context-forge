# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   Rate Limiter Engine - Makefile
#   High-performance rate limiter engine (Rust + PyO3)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# help: Rate Limiter Engine (Rust + Python extension build & automation)
# ─────────────────────────────────────────────────────────────────────────

.PHONY: help
help:
	@grep '^# help\:' $(firstword $(MAKEFILE_LIST)) | sed 's/^# help\: //'

PACKAGE_NAME := rate_limiter
PROJECT_PYTHON := $(abspath ../../.venv/bin/python)

GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m

# =============================================================================
# 🔍 LINTING & FORMAT
# =============================================================================
# help: fmt                   - Format Rust code with rustfmt
# help: fmt-check             - Check Rust code formatting (CI)
# help: clippy                - Run clippy lints
.PHONY: fmt fmt-check clippy

fmt:
	cargo fmt

fmt-check:
	cargo fmt -- --check

clippy:
	cargo clippy -- -D warnings

# =============================================================================
# 🧪 TESTS
# =============================================================================
# help: test                  - Run Rust unit tests
# help: test-verbose          - Run Rust tests with verbose output
# help: test-python           - Run Python wrapper tests
# help: test-all              - Run both Rust and Python tests
.PHONY: test test-verbose test-python test-all test-integration

test:
	@echo "$(GREEN)Running rate_limiter Rust tests...$(NC)"
	cargo test

test-verbose:
	@echo "$(GREEN)Running rate_limiter Rust tests (verbose)...$(NC)"
	cargo test -- --nocapture

test-python:
	@echo "$(GREEN)Running Python wrapper tests...$(NC)"
	cd ../.. && uv run pytest -k rate_limiter -v

test-integration:
	@echo "$(GREEN)Running integration tests (requires Redis)...$(NC)"
	cd ../.. && uv run pytest tests/integration/test_rate_limiter.py -v

test-all: test test-python

# =============================================================================
# 🛠 BUILD
# =============================================================================
# help: stub-gen              - Generate Python type stubs (.pyi files)
# help: build                 - Build release extension (no install)
# help: install               - Build and install wheel into project venv
.PHONY: stub-gen build install uninstall

stub-gen:
	@echo "$(GREEN)Generating Python type stubs...$(NC)"
	@PYO3_PYTHON="$(PROJECT_PYTHON)" cargo run --bin stub_gen
	@echo "$(GREEN)Stubs generated$(NC)"

build: stub-gen
	@echo "$(GREEN)Building $(PACKAGE_NAME)...$(NC)"
	@cd ../.. && uv run maturin build --release --manifest-path plugins_rust/rate_limiter/Cargo.toml
	@echo "$(GREEN)Build complete$(NC)"

install: stub-gen
	@echo "$(GREEN)Installing $(PACKAGE_NAME)...$(NC)"
	@cd ../.. && uv run maturin develop --release --manifest-path plugins_rust/rate_limiter/Cargo.toml
	@echo "$(GREEN)Installation complete$(NC)"

uninstall:
	@echo "$(YELLOW)Uninstalling $(PACKAGE_NAME)...$(NC)"
	@cd ../.. && uv pip uninstall -y mcpgateway-rate-limiter 2>/dev/null || true

# =============================================================================
# 📊 BENCHMARKS
# =============================================================================
# help: bench                 - Run Criterion benchmarks
# help: bench-compare         - Compare against saved baseline
# help: compare              - Run Python vs Rust hook-path comparison
# help: compare-quick        - Run a quick Python vs Rust comparison
# help: compare-detailed     - Run a detailed Python vs Rust comparison
.PHONY: bench bench-baseline bench-compare compare compare-quick compare-detailed

bench:
	@echo "$(GREEN)Running benchmarks...$(NC)"
	cargo bench

bench-baseline:
	cargo bench --bench rate_limiter -- --save-baseline main

bench-compare:
	cargo bench --bench rate_limiter -- --baseline main

compare: install
	@echo "$(GREEN)Running Python vs Rust hook-path comparison...$(NC)"
	@cd ../.. && uv run python3 plugins_rust/rate_limiter/compare_performance.py

compare-quick: install
	@echo "$(GREEN)Running quick Python vs Rust hook-path comparison...$(NC)"
	@cd ../.. && uv run python3 plugins_rust/rate_limiter/compare_performance.py --iterations 250 --warmup 25

compare-detailed: install
	@echo "$(GREEN)Running detailed Python vs Rust hook-path comparison...$(NC)"
	@cd ../.. && uv run python3 plugins_rust/rate_limiter/compare_performance.py --iterations 5000 --warmup 500

# =============================================================================
# 🧹 CLEANUP
# =============================================================================
.PHONY: clean clean-all

clean:
	cargo clean
	rm -rf target/ coverage/
	find . -name "*.whl" -delete

clean-all: clean

# =============================================================================
# 📚 DOCUMENTATION
# =============================================================================
.PHONY: doc doc-open

doc:
	cargo doc --no-deps --document-private-items

doc-open: doc
	cargo doc --no-deps --document-private-items --open

# =============================================================================
# 🔧 DEVELOPMENT HELPERS
# =============================================================================
# help: verify                - Verify plugin installation
# help: check-all             - Run fmt-check + clippy + test
.PHONY: verify check-all pre-commit

verify:
	@cd ../.. && uv run python -c "import rate_limiter_rust; print('✅ rate_limiter_rust available')" || echo "⚠️  rate_limiter_rust not installed — run: make install"

check-all: fmt-check clippy test
	@echo "$(GREEN)✔ All checks passed$(NC)"

pre-commit: check-all

.DEFAULT_GOAL := help
