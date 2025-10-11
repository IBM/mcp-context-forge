# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   🖥️  SYSTEM-MONITOR-SERVER - Makefile
#   (multi-package Go project with internal/, cmd/, pkg/ structure)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Author : Mihai Criveti
# Usage  : make <target>   or just `make help`
#
# help: 🖥️  SYSTEM-MONITOR-SERVER (Go build & automation helpers)
# ─────────────────────────────────────────────────────────────────────────

# =============================================================================
# 📖 DYNAMIC HELP
# =============================================================================
.PHONY: help
help:
	@grep '^# help\:' $(firstword $(MAKEFILE_LIST)) | sed 's/^# help\: //'

# =============================================================================
# 📦 PROJECT METADATA (variables, colours)
# =============================================================================
MODULE          := github.com/IBM/mcp-context-forge/mcp-servers/go/system-monitor-server
BIN_NAME        := system-monitor-server
VERSION         ?= $(shell git describe --tags --dirty --always 2>/dev/null || echo "v0.0.0-dev")

DIST_DIR        := dist
COVERPROFILE    := $(DIST_DIR)/coverage.out
COVERHTML       := $(DIST_DIR)/coverage.html

GO              ?= go
GOOS            ?= $(shell $(GO) env GOOS)
GOARCH          ?= $(shell $(GO) env GOARCH)

LDFLAGS         := -s -w -X 'main.appVersion=$(VERSION)'

ifeq ($(shell test -t 1 && echo tty),tty)
C_BLUE  := \033[38;5;75m
C_RESET := \033[0m
else
C_BLUE  :=
C_RESET :=
endif

# =============================================================================
# 🔧 TOOLING
# =============================================================================
# help: 🔧 TOOLING
# help: tools                 - Install / update golangci-lint & staticcheck

GOBIN := $(shell $(GO) env GOPATH)/bin

tools: $(GOBIN)/golangci-lint $(GOBIN)/staticcheck
$(GOBIN)/golangci-lint: ;	@$(GO) install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
$(GOBIN)/staticcheck:      ;	@$(GO) install honnef.co/go/tools/cmd/staticcheck@latest

# =============================================================================
# 📂 MODULE & FORMAT
# =============================================================================
# help: 📂 MODULE & FORMAT
# help: tidy                  - go mod tidy + verify
# help: fmt                   - Run gofmt & goimports

tidy:
	@$(GO) mod tidy
	@$(GO) mod verify

fmt:
	@$(GO) fmt ./...
	@go run golang.org/x/tools/cmd/goimports@latest -w .

# =============================================================================
# 🔍 LINTING & STATIC ANALYSIS
# =============================================================================
# help: 🔍 LINTING & STATIC ANALYSIS
# help: vet                   - go vet
# help: staticcheck           - Run staticcheck
# help: lint                  - Run golangci-lint
# help: pre-commit            - Run all configured pre-commit hooks
.PHONY: vet staticcheck lint pre-commit

vet:
	@$(GO) vet ./...

staticcheck: tools
	@staticcheck ./...

lint: tools
	@golangci-lint run

pre-commit:                 ## Run pre-commit hooks on all files
	@command -v pre-commit >/dev/null 2>&1 || { \
	    echo '✖ pre-commit not installed → pip install --user pre-commit'; exit 1; }
	@pre-commit run --all-files --show-diff-on-failure

# =============================================================================
# 🧪 TESTS & COVERAGE
# =============================================================================
# help: 🧪 TESTS & COVERAGE
# help: test                  - Run unit tests (race)
# help: coverage              - Generate HTML coverage report

test:
	@$(GO) test -race -timeout=90s ./...

coverage:
	@mkdir -p $(DIST_DIR)
	@$(GO) test ./... -covermode=count -coverprofile=$(COVERPROFILE)
	@$(GO) tool cover -html=$(COVERPROFILE) -o $(COVERHTML)
	@echo "$(C_BLUE)HTML coverage → $(COVERHTML)$(C_RESET)"

# =============================================================================
# 🛠 BUILD & RUN
# =============================================================================
# help: 🛠 BUILD & RUN
# help: build                 - Build binary into ./dist
# help: install               - go install into GOPATH/bin
# help: release               - Cross-compile (honours GOOS/GOARCH)
# help: run                   - Build then run (stdio transport)
# help: run-stdio             - Alias for "run"
# help: run-http              - Run HTTP  transport on :8080  (POST JSON-RPC)
# help: run-sse               - Run SSE   transport on :8080  (/sse, /messages)
# help: run-dual              - Run BOTH  SSE & HTTP on :8080 (/sse, /messages, /http)
# help: run-rest              - Run REST API on :8080  (/api/v1/*)

build: tidy
	@mkdir -p $(DIST_DIR)
	@$(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(DIST_DIR)/$(BIN_NAME) ./cmd/server

install:
	@$(GO) install -trimpath -ldflags '$(LDFLAGS)' ./cmd/server

release:
	@mkdir -p $(DIST_DIR)/$(GOOS)-$(GOARCH)
	@GOOS=$(GOOS) GOARCH=$(GOARCH) CGO_ENABLED=0 \
	  $(GO) build -trimpath -ldflags '$(LDFLAGS)' \
	  -o $(DIST_DIR)/$(GOOS)-$(GOARCH)/$(BIN_NAME) ./cmd/server

# ────── run helpers ────────────────────────────────────────────────────────
run: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=stdio -log-level=info

run-stdio: run			# simple alias

run-http: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=http -port=8080

run-sse: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=sse -port=8080

run-dual: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=dual -port=8080

run-rest: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=rest -port=8080

# =============================================================================
# 🐳 DOCKER
# =============================================================================
# help: 🐳 DOCKER
# help: docker-build          - Build container image
# help: docker-run            - Run container on :8080 (HTTP transport)
# help: docker-run-sse        - Run container on :8080 (SSE transport)

IMAGE ?= $(BIN_NAME):$(VERSION)

docker-build:
	@docker build --build-arg VERSION=$(VERSION) -t $(IMAGE) .
	@docker images $(IMAGE)

docker-run: docker-build
	@docker run --rm -p 8080:8080 $(IMAGE) -transport=http -port=8080

docker-run-sse: docker-build
	@docker run --rm -p 8080:8080 $(IMAGE) -transport=sse -port=8080

# =============================================================================
# 📚 MCP TOOLS TESTING
# =============================================================================
# help: 📚 MCP TOOLS
# help: test-metrics          - Test get_system_metrics tool
# help: test-processes        - Test list_processes tool
# help: test-health           - Test check_service_health tool
# help: test-mcp              - Test all MCP tools

.PHONY: test-metrics test-processes test-health test-mcp

test-metrics:
	@echo "$(C_BLUE)➜ Testing get_system_metrics...$(C_RESET)"
	@echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_system_metrics","arguments":{}},"id":1}' | $(DIST_DIR)/$(BIN_NAME)

test-processes:
	@echo "$(C_BLUE)➜ Testing list_processes...$(C_RESET)"
	@echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"list_processes","arguments":{"sort_by":"cpu","limit":5}},"id":2}' | $(DIST_DIR)/$(BIN_NAME)

test-health:
	@echo "$(C_BLUE)➜ Testing check_service_health...$(C_RESET)"
	@echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"check_service_health","arguments":{"services":[{"name":"local","type":"port","target":"localhost:22"}]}},"id":3}' | $(DIST_DIR)/$(BIN_NAME)

test-mcp: build test-metrics test-processes test-health
	@echo "\n$(C_BLUE)✔ MCP Tools Test Complete$(C_RESET)"

# =============================================================================
# 🚀 BENCHMARKING
# =============================================================================
# help: 🚀 BENCHMARKING
# help: bench                 - Run Go benchmarks
# help: bench-http            - Run HTTP load test using 'hey' (run make run-http first)

.PHONY: bench bench-http

bench:
	@$(GO) test -bench=. -benchmem ./...

bench-http:
	@command -v hey >/dev/null || { echo '"hey" not installed'; exit 1; }
	@echo "➜ load-test list_processes via /http"
	@hey -m POST -T 'application/json' \
	     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"list_processes","arguments":{"limit":10}},"id":1}' \
	     -n 10000 -c 50 http://localhost:8080/

# =============================================================================
# 🔒 SECURITY & QUALITY
# =============================================================================
# help: 🔒 SECURITY & QUALITY
# help: security              - Run gosec security scanner
# help: check                 - Run all checks (fmt, vet, lint, test, security)

.PHONY: security check

security:
	@command -v gosec >/dev/null || $(GO) install github.com/securecodewarrior/gosec/v2/cmd/gosec@latest
	@gosec -quiet ./...

check: fmt vet lint test security
	@echo "$(C_BLUE)✔ All checks passed!$(C_RESET)"

# =============================================================================
# 🧹 CLEANUP
# =============================================================================
# help: 🧹 CLEANUP
# help: clean                 - Remove build & coverage artefacts

clean:
	@rm -rf $(DIST_DIR) $(COVERPROFILE) $(COVERHTML)
	@rm -f $(BIN_NAME) coverage.out coverage.html
	@rm -rf coverage/
	@$(GO) clean
	@echo "Workspace clean ✔"

# ---------------------------------------------------------------------------
# Default goal
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
