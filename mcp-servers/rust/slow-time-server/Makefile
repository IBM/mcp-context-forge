.PHONY: help fmt clippy check test build release run clean container-build container-run

BIN_NAME := slow-time-server
IMAGE ?= mcpgateway/slow-time-server:rust
CONTAINER_RT := $(or $(CONTAINER_RUNTIME),$(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null))
REPO_ROOT := $(abspath ../../..)

help:
	@printf '%s\n' "Targets: fmt clippy check test build release run clean container-build container-run"

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

clean:
	@cargo clean

container-build:
	@$(CONTAINER_RT) build -f $(REPO_ROOT)/mcp-servers/rust/slow-time-server/Containerfile -t $(IMAGE) $(REPO_ROOT)

container-run: container-build
	@$(CONTAINER_RT) run --rm -p 8081:8081 -e BIND_ADDRESS=0.0.0.0:8081 $(IMAGE)
