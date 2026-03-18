# A2A Rust service: build, test, coverage.
# Usage: make test, make coverage, make coverage-check

.PHONY: test test-unit test-integration coverage coverage-check build clean

CARGO ?= cargo

test: test-unit test-integration

test-unit:
	$(CARGO) test --lib

test-integration:
	$(CARGO) test --test integration

build:
	$(CARGO) build --release

clean:
	$(CARGO) clean

# Generate HTML coverage report. Install cargo-llvm-cov if missing.
# Run after implementation is done; use coverage-check to enforce 100%.
coverage:
	@command -v cargo-llvm-cov >/dev/null 2>&1 || { echo "Installing cargo-llvm-cov..."; $(CARGO) install cargo-llvm-cov; }
	$(CARGO) llvm-cov --html --ignore-filename-regex 'tests/'
	@echo "Coverage report: target/llvm-cov/html/index.html"

# Run tests with coverage and fail if any line is uncovered (100% line coverage).
# Use once implementation is complete: make coverage-check
coverage-check:
	@command -v cargo-llvm-cov >/dev/null 2>&1 || { echo "Installing cargo-llvm-cov..."; $(CARGO) install cargo-llvm-cov; }
	$(CARGO) llvm-cov --lib --test integration --no-clean --fail-uncovered-lines 0 --ignore-filename-regex 'tests/'
