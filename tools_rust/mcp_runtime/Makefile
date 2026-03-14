# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   CONTEXTFORGE MCP RUNTIME - Makefile
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Description: Build, test, lint, and coverage helpers for the Rust MCP runtime
# Usage: run `make` or `make help` to view available targets
#
# help: CONTEXTFORGE MCP RUNTIME
#
# ──────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

CARGO ?= cargo
RUSTUP ?= rustup
FEATURE_RMCP := rmcp-upstream-client
CLIPPY_FLAGS ?= -W clippy::pedantic
CLIPPY_CONF_DIR ?= $(CURDIR)
RUN_ARGS ?=
export CLIPPY_CONF_DIR

.DEFAULT_GOAL := help

# =============================================================================
# DYNAMIC HELP
# =============================================================================
.PHONY: help
help:
	@grep "^# help:" Makefile | grep -v grep | sed 's/# help: //' | sed 's/# help://'

# =============================================================================
# BUILD
# =============================================================================

.PHONY: build build-release build-rmcp build-release-rmcp run run-rmcp run-release run-release-rmcp clean

# help: build b                    - Run cargo build
build b:
	@echo "Running cargo build..."
	@$(CARGO) build

# help: build-release br           - Run cargo build --release
build-release br:
	@echo "Running cargo build --release..."
	@$(CARGO) build --release

# help: build-rmcp                 - Run cargo build with rmcp upstream client feature
build-rmcp:
	@echo "Running cargo build --features $(FEATURE_RMCP)..."
	@$(CARGO) build --features $(FEATURE_RMCP)

# help: build-release-rmcp         - Run cargo build --release with rmcp upstream client feature
build-release-rmcp:
	@echo "Running cargo build --release --features $(FEATURE_RMCP)..."
	@$(CARGO) build --release --features $(FEATURE_RMCP)

# help: run                        - Run cargo run (override with RUN_ARGS='...')
run:
	@echo "Running cargo run $(RUN_ARGS)..."
	@$(CARGO) run -- $(RUN_ARGS)

# help: run-rmcp                   - Run cargo run with rmcp upstream client feature
run-rmcp:
	@echo "Running cargo run --features $(FEATURE_RMCP) $(RUN_ARGS)..."
	@$(CARGO) run --features $(FEATURE_RMCP) -- $(RUN_ARGS)

# help: run-release                - Run cargo run --release
run-release:
	@echo "Running cargo run --release $(RUN_ARGS)..."
	@$(CARGO) run --release -- $(RUN_ARGS)

# help: run-release-rmcp           - Run cargo run --release with rmcp upstream client feature
run-release-rmcp:
	@echo "Running cargo run --release --features $(FEATURE_RMCP) $(RUN_ARGS)..."
	@$(CARGO) run --release --features $(FEATURE_RMCP) -- $(RUN_ARGS)

# help: clean                      - Remove cargo build artifacts
clean:
	@echo "Running cargo clean..."
	@$(CARGO) clean

# =============================================================================
# TEST
# =============================================================================

.PHONY: test test-release test-rmcp test-release-rmcp doc-test

# help: test t                     - Run cargo test
test t:
	@echo "Running cargo test..."
	@$(CARGO) test

# help: test-release tr            - Run cargo test --release
test-release tr:
	@echo "Running cargo test --release..."
	@$(CARGO) test --release

# help: test-rmcp                  - Run cargo test with rmcp upstream client feature
test-rmcp:
	@echo "Running cargo test --features $(FEATURE_RMCP)..."
	@$(CARGO) test --features $(FEATURE_RMCP)

# help: test-release-rmcp          - Run cargo test --release with rmcp upstream client feature
test-release-rmcp:
	@echo "Running cargo test --release --features $(FEATURE_RMCP)..."
	@$(CARGO) test --release --features $(FEATURE_RMCP)

# help: doc-test                   - Run cargo test --doc
doc-test:
	@echo "Running cargo test --doc..."
	@$(CARGO) test --doc

# =============================================================================
# CARGO CHECKS
# =============================================================================

.PHONY: check check-test check-rmcp check-all-targets

# help: check chk c                - Run cargo check
check chk c:
	@echo "Running cargo check..."
	@$(CARGO) check

# help: check-test ct              - Run cargo check --tests
check-test ct:
	@echo "Running cargo check --tests..."
	@$(CARGO) check --tests

# help: check-rmcp                 - Run cargo check with rmcp upstream client feature
check-rmcp:
	@echo "Running cargo check --features $(FEATURE_RMCP)..."
	@$(CARGO) check --features $(FEATURE_RMCP)

# help: check-all-targets          - Run cargo check --all-targets --all-features
check-all-targets:
	@echo "Running cargo check --all-targets --all-features..."
	@$(CARGO) check --all-targets --all-features

# =============================================================================
# FORMAT & LINT
# =============================================================================

.PHONY: fmt fmt-check clippy clippy-tests clippy-rmcp clippy-all clippy-fix lint lint-rmcp

# help: fmt                        - Run cargo fmt
fmt:
	@echo "Running cargo fmt..."
	@$(CARGO) fmt

# help: fmt-check                  - Run cargo fmt --check
fmt-check:
	@echo "Running cargo fmt --check..."
	@$(CARGO) fmt --check

# help: clippy                     - Run cargo clippy on all targets
clippy:
	@echo "Running cargo clippy --all-targets..."
	@$(CARGO) clippy --all-targets -- $(CLIPPY_FLAGS)

# help: clippy-tests               - Run cargo clippy on test targets
clippy-tests:
	@echo "Running cargo clippy --tests..."
	@$(CARGO) clippy --tests -- $(CLIPPY_FLAGS)

# help: clippy-rmcp                - Run cargo clippy with rmcp upstream client feature
clippy-rmcp:
	@echo "Running cargo clippy --all-targets --features $(FEATURE_RMCP)..."
	@$(CARGO) clippy --all-targets --features $(FEATURE_RMCP) -- $(CLIPPY_FLAGS)

# help: clippy-all                 - Run cargo clippy on all targets and all features
clippy-all:
	@echo "Running cargo clippy --all-targets --all-features..."
	@$(CARGO) clippy --all-targets --all-features -- $(CLIPPY_FLAGS)

# help: clippy-fix                 - Run cargo clippy --fix on all targets
clippy-fix:
	@echo "Running cargo clippy --fix --all-targets..."
	@$(CARGO) clippy --fix --all-targets --allow-dirty --allow-staged -- $(CLIPPY_FLAGS)

# help: lint                       - Run fmt-check, clippy, and tests
lint:
	@$(MAKE) fmt-check
	@$(MAKE) clippy
	@$(MAKE) test

# help: lint-rmcp                  - Run fmt-check, clippy-rmcp, and test-rmcp
lint-rmcp:
	@$(MAKE) fmt-check
	@$(MAKE) clippy-rmcp
	@$(MAKE) test-rmcp

# =============================================================================
# COVERAGE & TOOLING
# =============================================================================

.PHONY: coverage setup-coverage deny

# help: setup-coverage             - Install llvm coverage prerequisites
setup-coverage:
	@echo "Installing llvm coverage prerequisites..."
	@$(RUSTUP) component add llvm-tools-preview
	@$(CARGO) install cargo-llvm-cov --locked

# help: coverage cov               - Generate HTML coverage report with llvm-cov
coverage cov:
	@echo "Generating coverage report..."
	@$(MAKE) setup-coverage
	@$(CARGO) llvm-cov --html --all-features
	@echo "Coverage report generated at target/llvm-cov/html/index.html"

# help: deny                       - Run cargo deny checks if installed
deny:
	@echo "Running cargo deny..."
	@cargo deny check
