# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   MCP STDIO WRAPPER - Makefile
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Description: Build & automation helpers for the MCP STDIO Wrapper project
# Usage: run `make` or `make help` to view available targets
#
# help: MCP STDIO WRAPPER
#
# ──────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

# =============================================================================
# DYNAMIC HELP
# =============================================================================
.PHONY: help
help:
	@grep "^# help:" Makefile | grep -v grep | sed 's/# help: //' | sed 's/# help://'
	
.PHONY: clean-cache
# help: clean-cache		- Clean uv cache for pyo3 module
clean-cache:
	find ~/.cache/uv -name deny_filter* -exec rm -rf \{\} \; || echo "not found"
	find .venv -name deny_filter* -exec rm -rf \{\} \; || echo "not found"
	@uv cache clean deny_filter

# =============================================================================
# BUILD
# =============================================================================

.PHONY: build build-release

# help: build b			- Run cargo build
build b: clean-cache
	@echo "Running build..."
	@cargo run --bin stub_gen
	@uv run maturin build
	


# help: build-release br	- Run cargo build --release
build-release br: clean-cache
	@echo "Running build release..."
	@cargo run --bin stub_gen --release
	@uv run maturin build --release

# =============================================================================
# TEST
# =============================================================================

.PHONY: test

# help: test t			- Run cargo test
test t:
	@echo "Running cargo test..."
	@cargo test
	@uv run pytest -v -s 

# =============================================================================
# CARGO CHECKS
# =============================================================================

.PHONY: cargo-check cargo-check-tests clippy-pedantic-src clippy-pedantic-tests

# help: check			- Run cargo check on the project
check chk c:
	@echo "Running cargo check..."
	@cargo check

# help: check-test		- Run cargo check on tests
check-test check-tests chkt ct:
	@echo "Running cargo check on tests..."
	@cargo check --tests
# help: pedantic		- Run clippy with pedantic lints on src/

pedantic ped p:
	@echo "Running clippy with pedantic lints on src/..."
	@cargo fmt
	@cargo clippy -- -W clippy::pedantic

# help: pedanticx pedx px	- Run clippy --fix with pedantic lints on src/
pedanticx pedx px:
	@echo "Running clippy with pedantic lints on src/..."
	@cargo fmt
	@cargo clippy --fix -- -W clippy::pedantic

# help: pedantic-test		- Run clippy with pedantic lints on tests/
lint pedantic-test pedantic-tests pedt pt:
	@echo "Running clippy with pedantic lints on tests/..."
	@cargo fmt
	@cargo clippy --tests -- -W clippy::pedantic

# help: pedantic-testx		- Run clippy --fix with pedantic lints on tests/
pedantic-testx pedantic-testsx pedtx ptx:
	@echo "Running clippy with pedantic lints on tests/..."
	@cargo fmt
	@cargo clippy --tests --fix -- -W clippy::pedantic

# help: coverage		- Generate code coverage report with llvm-cov
coverage cov cv:
	@echo "Generating code coverage report..."
	@cargo install cargo-llvm-cov
	@rustup component add llvm-tools-preview
	@cargo llvm-cov --summary-only --no-clean --ignore-filename-regex "src/bin/.*" 
	@echo "Coverage report generated at target/llvm-cov/html/index.html"
	#@xdg-open target/llvm-cov/html/index.html

# help: licenses		- Check licenses
licenses license lic l:
	@echo Check licenses
	@command -v cargo-deny &> /dev/null || cargo install cargo-deny
	@cargo deny check licenses