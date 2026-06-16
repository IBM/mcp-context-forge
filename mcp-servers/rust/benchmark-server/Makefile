.PHONY: help fmt clippy check test build release run run-small run-large clean container-build container-run

BIN_NAME := benchmark-server
IMAGE ?= mcpgateway/benchmark-server:latest
CONTAINER_RT := $(or $(CONTAINER_RUNTIME),$(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null))

help:
	@printf '%s\n' "Targets: fmt clippy check test build release run run-small run-large clean container-build container-run"

fmt:
	@cargo fmt

clippy:
	@cargo clippy -- -D warnings

check:
	@cargo check

test:
	@cargo test

build:
	@cargo build

release:
	@cargo build --release

run: build
	@RUST_LOG=info target/debug/$(BIN_NAME)

run-small: build
	@RUST_LOG=info target/debug/$(BIN_NAME) -tools=10 -resources=10 -prompts=10

run-large: build
	@RUST_LOG=info target/debug/$(BIN_NAME) -tools=1000 -resources=1000 -prompts=500

clean:
	@cargo clean

container-build:
	@$(CONTAINER_RT) build -f Containerfile -t $(IMAGE) ../../..

container-run: container-build
	@$(CONTAINER_RT) run --rm -p 8080:8080 $(IMAGE)
