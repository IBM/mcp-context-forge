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
# help: check                 - Run cargo check
.PHONY: fmt fmt-check clippy check

fmt:
	@cargo fmt

fmt-check:
	@cargo fmt -- --check

clippy:
	@cargo clippy -- -D warnings

check:
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
	@cargo test

test-verbose:
	@cargo test -- --nocapture

test-python: develop
	@echo "$(C_BLUE)➜ Running Python tests...$(C_RESET)"
	@cd ../.. && pytest -k pii_filter -v

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
	@echo "$(C_BLUE)➜ Building debug Python extension...$(C_RESET)"
	@maturin build
	@echo "$(C_GREEN)Debug build complete$(C_RESET)"

release:
	@echo "$(C_BLUE)➜ Building release Python extension...$(C_RESET)"
	@maturin build --release
	@echo "$(C_GREEN)Release build complete$(C_RESET)"
	@ls -lh $(DIST_DIR)/wheels/*.whl 2>/dev/null || true

develop:
	@echo "$(C_BLUE)➜ Installing in development mode...$(C_RESET)"
	@maturin develop --release
	@echo "$(C_GREEN)Development install complete$(C_RESET)"

install: release
	@echo "$(C_BLUE)➜ Installing wheel...$(C_RESET)"
	@pip install --force-reinstall $(DIST_DIR)/wheels/*.whl
	@echo "$(C_GREEN)Installation complete$(C_RESET)"

# =============================================================================
# 📊 BENCHMARKS
# =============================================================================
# help: 📊 BENCHMARKS
# help: bench                 - Run Criterion benchmarks
# help: bench-baseline        - Save benchmark baseline
# help: bench-compare         - Compare against baseline
.PHONY: bench bench-baseline bench-compare

bench:
	@echo "$(C_BLUE)➜ Running benchmarks...$(C_RESET)"
	@cargo bench

bench-baseline:
	@echo "$(C_BLUE)➜ Saving benchmark baseline...$(C_RESET)"
	@cargo bench -- --save-baseline main

bench-compare:
	@echo "$(C_BLUE)➜ Comparing against baseline...$(C_RESET)"
	@cargo bench -- --baseline main

# =============================================================================
# 🧹 CLEANUP
# =============================================================================
# help: 🧹 CLEANUP
# help: clean                 - Remove build artifacts
# help: clean-all             - Remove all build artifacts including wheels
.PHONY: clean clean-all

clean:
	@cargo clean
	@echo "Workspace clean ✔"

clean-all: clean
	@rm -rf $(DIST_DIR)/wheels
	@rm -rf *.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "All artifacts removed ✔"

# =============================================================================
# 📚 DOCUMENTATION
# =============================================================================
# help: 📚 DOCUMENTATION
# help: doc                   - Generate Rust documentation
# help: doc-open              - Generate and open documentation
.PHONY: doc doc-open

doc:
	@cargo doc --no-deps

doc-open:
	@cargo doc --no-deps --open

# =============================================================================
# 🔧 DEVELOPMENT HELPERS
# =============================================================================
# help: 🔧 DEVELOPMENT HELPERS
# help: verify                - Run all checks (fmt, clippy, test)
# help: pre-commit            - Run pre-commit checks
.PHONY: verify pre-commit

verify: fmt clippy test
	@echo "$(C_GREEN)✔ All checks passed$(C_RESET)"

pre-commit: verify
	@echo "$(C_GREEN)✔ Ready to commit$(C_RESET)"

# ---------------------------------------------------------------------------
# Default goal
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
