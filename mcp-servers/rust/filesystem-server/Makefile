.DEFAULT_GOAL := help

# Variables
BIN_NAME := filesystem-server
RELEASE_BIN := target/release/$(BIN_NAME)
DEBUG_BIN := target/debug/$(BIN_NAME)

# Targets
.PHONY: help build release debug test test-lib test-integration coverage fmt clippy check clean install run run-release container-build container-run container-stop docker-build docker-run

help:
	@echo "$(BIN_NAME) - Makefile targets:"
	@echo "  build              - Build debug binary"
	@echo "  release            - Build optimized release binary"
	@echo "  debug              - Build and run debug binary"
	@echo "  test               - Run all tests"
	@echo "  test-lib           - Run library tests only"
	@echo "  test-integration   - Run integration tests"
	@echo "  coverage           - Generate coverage report"
	@echo "  fmt                - Format code with rustfmt"
	@echo "  clippy             - Run clippy linter"
	@echo "  check              - Run cargo check"
	@echo "  clean              - Remove build artifacts"
	@echo "  install            - Install binary to ~/.cargo/bin"
	@echo "  run                - Run debug binary (ROOTS=/folder1 /folder2 ...)"
	@echo "  run-release        - Run release binary (ROOTS=/folder1 /folder2 ...)"
	@echo "  container-build    - Build container image"
	@echo "  container-run      - Run container"
	@echo "  container-stop     - Stop container"

build:
	cargo build

release:
	cargo build --release

debug: build
	$(DEBUG_BIN)

test:
	cargo test

test-lib:
	cargo test --lib

test-integration:
	cargo test --test integration_test

coverage:
	@command -v cargo-llvm-cov >/dev/null || cargo install cargo-llvm-cov
	cargo llvm-cov --open

fmt:
	cargo fmt

clippy:
	cargo clippy -- -D warnings

check:
	cargo check

clean:
	cargo clean

install: release
	cargo install --path .

run: build
	RUST_LOG=info $(DEBUG_BIN) --roots "$(ROOTS)"

run-release: release
	RUST_LOG=info $(RELEASE_BIN) --roots "$(ROOTS)"

container-build:
	docker build -f Dockerfile -t $(BIN_NAME) .

container-run: container-build
	docker run --rm -p 8084:8084 $(BIN_NAME) --roots /tmp

container-stop:
	docker stop $(BIN_NAME) 2>/dev/null || true

# Backwards compatibility aliases
docker-build: container-build
docker-run: container-run
