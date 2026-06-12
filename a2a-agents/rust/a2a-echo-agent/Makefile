.PHONY: help fmt clippy check test build release run clean container-build container-run

BIN_NAME := a2a-echo-agent
IMAGE ?= mcpgateway/a2a-echo-agent:rust
CONTAINER_RT := $(or $(CONTAINER_RUNTIME),$(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null))

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

run:
	@RUST_LOG=info cargo run -p $(BIN_NAME)

clean:
	@cargo clean

container-build:
	@cd ../../.. && $(CONTAINER_RT) build -f a2a-agents/rust/a2a-echo-agent/Dockerfile -t $(IMAGE) .

container-run: container-build
	@$(CONTAINER_RT) run --rm -p 9100:9100 -e A2A_ECHO_ADDR=0.0.0.0:9100 $(IMAGE)
