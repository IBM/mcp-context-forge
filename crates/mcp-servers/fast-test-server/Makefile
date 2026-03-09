# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   🦀 FAST-TEST-SERVER - Makefile
#   Ultra-fast MCP server in Rust for performance testing
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Usage: make <target>  or just `make help`
#
# help: 🦀 FAST-TEST-SERVER (Rust build & automation helpers)
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
BIN_NAME        := fast-test-server
VERSION         ?= $(shell cargo metadata --format-version 1 --no-deps 2>/dev/null | jq -r '.packages[0].version' || echo "0.1.0")
DIST_DIR        := target
RELEASE_BIN     := $(DIST_DIR)/release/$(BIN_NAME)
DEBUG_BIN       := $(DIST_DIR)/debug/$(BIN_NAME)

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
# help: fmt                   - Format code with rustfmt
# help: clippy                - Run clippy lints
# help: check                 - Run cargo check
.PHONY: fmt clippy check

fmt:
	@cargo fmt

clippy:
	@cargo clippy -- -D warnings

check:
	@cargo check

# =============================================================================
# 🧪 TESTS
# =============================================================================
# help: 🧪 TESTS
# help: test                  - Run all tests
# help: test-verbose          - Run tests with verbose output
.PHONY: test test-verbose

test:
	@cargo test

test-verbose:
	@cargo test -- --nocapture

# =============================================================================
# 🛠 BUILD
# =============================================================================
# help: 🛠 BUILD
# help: build                 - Build debug binary
# help: release               - Build optimized release binary
# help: install               - Install to ~/.cargo/bin
.PHONY: build release install

build:
	@cargo build
	@echo "$(C_GREEN)Debug binary: $(DEBUG_BIN)$(C_RESET)"

release:
	@cargo build --release
	@echo "$(C_GREEN)Release binary: $(RELEASE_BIN)$(C_RESET)"
	@ls -lh $(RELEASE_BIN)

install: release
	@cargo install --path .

# =============================================================================
# 🚀 RUN
# =============================================================================
# help: 🚀 RUN
# help: run                   - Run debug build on :9080
# help: run-release           - Run release build on :9080
# help: run-port PORT=9000    - Run on custom port
.PHONY: run run-release run-port

run: build
	@RUST_LOG=info $(DEBUG_BIN)

run-release: release
	@RUST_LOG=info $(RELEASE_BIN)

run-port: build
	@RUST_LOG=info BIND_ADDRESS=0.0.0.0:$(PORT) $(DEBUG_BIN)

# =============================================================================
# 🐳 CONTAINER (Docker/Podman auto-detection)
# =============================================================================
# help: 🐳 CONTAINER
# help: container-build       - Build container image (auto-detects Docker/Podman)
# help: container-run         - Run container on :9080 (foreground)
# help: container-run-detached - Run container on :9080 (background)
# help: container-stop        - Stop running container
# help: container-push        - Push image to registry
.PHONY: container-build container-run container-run-detached container-stop container-push

# Auto-detect container runtime (prefers Docker, set CONTAINER_RUNTIME=podman to override)
CONTAINER_RT := $(or $(CONTAINER_RUNTIME),$(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null))
CONTAINER_RT_NAME := $(notdir $(CONTAINER_RT))

IMAGE_NAME ?= mcpgateway/fast-test-server
IMAGE_TAG ?= $(VERSION)
IMAGE ?= $(IMAGE_NAME):$(IMAGE_TAG)

container-build:
	@echo "$(C_BLUE)➜ Building container with $(CONTAINER_RT_NAME)...$(C_RESET)"
	@$(CONTAINER_RT) build -f Containerfile -t $(IMAGE) .
	@$(CONTAINER_RT) images $(IMAGE)

container-run: container-build
	@echo "$(C_BLUE)➜ Running container on :9080...$(C_RESET)"
	@$(CONTAINER_RT) run --rm --name fast-test-server -p 9080:9080 $(IMAGE)

container-run-detached: container-build
	@echo "$(C_BLUE)➜ Running container in background on :9080...$(C_RESET)"
	@$(CONTAINER_RT) run -d --rm --name fast-test-server -p 9080:9080 $(IMAGE)
	@echo "$(C_GREEN)Container started. Use 'make container-stop' to stop.$(C_RESET)"

container-stop:
	@$(CONTAINER_RT) stop fast-test-server 2>/dev/null || true

container-push: container-build
	@echo "$(C_BLUE)➜ Pushing $(IMAGE) to registry...$(C_RESET)"
	@$(CONTAINER_RT) push $(IMAGE)

# Legacy aliases for backwards compatibility
.PHONY: docker-build docker-run
docker-build: container-build
docker-run: container-run

# =============================================================================
# 🧹 CLEANUP
# =============================================================================
# help: 🧹 CLEANUP
# help: clean                 - Remove build artifacts
.PHONY: clean

clean:
	@cargo clean
	@echo "Workspace clean ✔"

# =============================================================================
# 🚀 BENCHMARKING (uses REST API to bypass MCP session overhead)
# =============================================================================
# help: 🚀 BENCHMARKING
# help: bench                 - Run full benchmark suite (echo + time)
# help: bench-echo            - Benchmark /api/echo endpoint (1M requests)
# help: bench-time            - Benchmark /api/time endpoint (1M requests)
# help: bench-quick           - Quick benchmark (100K requests)
.PHONY: bench bench-echo bench-time bench-quick

BENCH_N ?= 1000000
BENCH_C ?= 200

bench: bench-echo bench-time

bench-echo:
	@command -v hey >/dev/null || { echo '"hey" not installed: go install github.com/rakyll/hey@latest'; exit 1; }
	@echo "$(C_BLUE)➜ Benchmarking /api/echo ($(BENCH_N) requests, $(BENCH_C) concurrent)...$(C_RESET)"
	@hey -m POST -T 'application/json' \
	     -d '{"message":"hello"}' \
	     -n $(BENCH_N) -c $(BENCH_C) http://localhost:9080/api/echo

bench-time:
	@command -v hey >/dev/null || { echo '"hey" not installed: go install github.com/rakyll/hey@latest'; exit 1; }
	@echo "$(C_BLUE)➜ Benchmarking /api/time ($(BENCH_N) requests, $(BENCH_C) concurrent)...$(C_RESET)"
	@hey -n $(BENCH_N) -c $(BENCH_C) 'http://localhost:9080/api/time?tz=America/New_York'

bench-quick:
	@command -v hey >/dev/null || { echo '"hey" not installed: go install github.com/rakyll/hey@latest'; exit 1; }
	@echo "$(C_BLUE)➜ Quick benchmark /api/echo (100K requests)...$(C_RESET)"
	@hey -m POST -T 'application/json' \
	     -d '{"message":"hello"}' \
	     -n 100000 -c 100 http://localhost:9080/api/echo

# =============================================================================
# 🦗 LOCUST LOAD TESTING (MCP protocol with session management)
# =============================================================================
# help: 🦗 LOCUST LOAD TESTING
# help: locust-ui             - Start Locust web UI (server on PORT, default 9080)
# help: locust-mcp            - MCP protocol test (3000 users, 60s)
# help: locust-rest           - REST API test (3000 users, 60s)
# help: locust-both           - Run both MCP and REST tests sequentially
.PHONY: locust-ui locust-mcp locust-rest locust-both

# Default port (9080 to avoid conflict with gateway/nginx on 8080)
PORT ?= 9080
LOCUST_USERS ?= 3000
LOCUST_SPAWN ?= 100
LOCUST_TIME ?= 60s

locust-ui:
	@echo "$(C_BLUE)➜ Starting Locust Web UI (distributed, auto-detect CPUs)...$(C_RESET)"
	@echo "$(C_BLUE)  Open: http://localhost:8089$(C_RESET)"
	@echo "$(C_BLUE)  Server should be running on :$(PORT)$(C_RESET)"
	@uv run locust -f locustfile.py --host=http://localhost:$(PORT) \
	        --processes=-1 --class-picker

locust-mcp:
	@echo "$(C_BLUE)➜ Running MCP protocol test ($(LOCUST_USERS) users, $(LOCUST_TIME), auto CPUs)...$(C_RESET)"
	@echo "$(C_BLUE)  Target: http://localhost:$(PORT)/mcp$(C_RESET)"
	@uv run locust -f locustfile.py --host=http://localhost:$(PORT) \
	        --users=$(LOCUST_USERS) --spawn-rate=$(LOCUST_SPAWN) \
	        --run-time=$(LOCUST_TIME) --headless \
	        --processes=-1 \
	        RustMCPUser

locust-rest:
	@echo "$(C_BLUE)➜ Running REST API test ($(LOCUST_USERS) users, $(LOCUST_TIME), auto CPUs)...$(C_RESET)"
	@echo "$(C_BLUE)  Target: http://localhost:$(PORT)/api/*$(C_RESET)"
	@uv run locust -f locustfile.py --host=http://localhost:$(PORT) \
	        --users=$(LOCUST_USERS) --spawn-rate=$(LOCUST_SPAWN) \
	        --run-time=$(LOCUST_TIME) --headless \
	        --processes=-1 \
	        RustRESTUser

locust-both: locust-mcp locust-rest
	@echo "$(C_GREEN)✔ Both tests completed$(C_RESET)"

# =============================================================================
# 📚 TEST COMMANDS
# =============================================================================
# help: 📚 TEST COMMANDS
# help: test-tools            - Test tools/list endpoint
# help: test-echo             - Test echo tool
# help: test-time             - Test get_system_time tool
.PHONY: test-tools test-echo test-time

test-tools:
	@echo "$(C_BLUE)➜ Testing tools/list...$(C_RESET)"
	@curl -s -X POST http://localhost:9080/mcp \
	     -H 'Content-Type: application/json' \
	     -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' | jq .

test-echo:
	@echo "$(C_BLUE)➜ Testing echo tool...$(C_RESET)"
	@curl -s -X POST http://localhost:9080/mcp \
	     -H 'Content-Type: application/json' \
	     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"echo","arguments":{"message":"Hello, World!"}},"id":1}' | jq .

test-time:
	@echo "$(C_BLUE)➜ Testing get_system_time tool...$(C_RESET)"
	@curl -s -X POST http://localhost:9080/mcp \
	     -H 'Content-Type: application/json' \
	     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_system_time","arguments":{"timezone":"America/New_York"}},"id":1}' | jq .

# ---------------------------------------------------------------------------
# Default goal
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
