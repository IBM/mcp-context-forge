# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   📄 PANDOC-SERVER - Makefile
#   MCP server for pandoc document conversion
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Author : Mihai Criveti
# Usage  : make <target>   or just `make help`
#
# help: 📄 PANDOC-SERVER (Go MCP server for document conversion)
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
MODULE          := pandoc-server
BIN_NAME        := pandoc-server
VERSION         ?= $(shell git describe --tags --dirty --always 2>/dev/null || echo "v0.2.0")

DIST_DIR        := dist
COVERPROFILE    := $(DIST_DIR)/coverage.out
COVERHTML       := $(DIST_DIR)/coverage.html

GO              ?= go
GOOS            ?= $(shell $(GO) env GOOS)
GOARCH          ?= $(shell $(GO) env GOARCH)

LDFLAGS         := -s -w -X 'main.appVersion=$(VERSION)'

ifeq ($(shell test -t 1 && echo tty),tty)
C_GREEN := \033[38;5;82m
C_BLUE  := \033[38;5;75m
C_RESET := \033[0m
else
C_GREEN :=
C_BLUE  :=
C_RESET :=
endif

# =============================================================================
# 🔧 TOOLING
# =============================================================================
# help: 🔧 TOOLING
# help: tools                 - Install golangci-lint & staticcheck

GOBIN := $(shell $(GO) env GOPATH)/bin

.PHONY: tools
tools: $(GOBIN)/golangci-lint $(GOBIN)/staticcheck

$(GOBIN)/golangci-lint:
	@echo "$(C_BLUE)Installing golangci-lint...$(C_RESET)"
	@$(GO) install github.com/golangci/golangci-lint/cmd/golangci-lint@latest

$(GOBIN)/staticcheck:
	@echo "$(C_BLUE)Installing staticcheck...$(C_RESET)"
	@$(GO) install honnef.co/go/tools/cmd/staticcheck@latest

# =============================================================================
# 📂 MODULE & FORMAT
# =============================================================================
# help: 📂 MODULE & FORMAT
# help: tidy                  - go mod tidy + verify
# help: fmt                   - Run gofmt & goimports

.PHONY: tidy fmt

tidy:
	@echo "$(C_BLUE)Tidying dependencies...$(C_RESET)"
	@$(GO) mod tidy
	@$(GO) mod verify

fmt:
	@echo "$(C_BLUE)Formatting code...$(C_RESET)"
	@$(GO) fmt ./...
	@go run golang.org/x/tools/cmd/goimports@latest -w .

# =============================================================================
# 🔍 LINTING & STATIC ANALYSIS
# =============================================================================
# help: 🔍 LINTING & STATIC ANALYSIS
# help: vet                   - go vet
# help: staticcheck           - Run staticcheck
# help: lint                  - Run golangci-lint
# help: pre-commit            - Run all pre-commit hooks

.PHONY: vet staticcheck lint pre-commit

vet:
	@echo "$(C_BLUE)Running go vet...$(C_RESET)"
	@$(GO) vet ./...

staticcheck: tools
	@echo "$(C_BLUE)Running staticcheck...$(C_RESET)"
	@staticcheck ./...

lint: tools
	@echo "$(C_BLUE)Running golangci-lint...$(C_RESET)"
	@golangci-lint run

pre-commit:
	@command -v pre-commit >/dev/null 2>&1 || { \
	    echo '✖ pre-commit not installed → pip install --user pre-commit'; exit 1; }
	@pre-commit run --all-files --show-diff-on-failure

# =============================================================================
# 🧪 TESTS & COVERAGE
# =============================================================================
# help: 🧪 TESTS & COVERAGE
# help: test                  - Run unit tests (race)
# help: test-verbose          - Run tests with verbose output
# help: coverage              - Generate HTML coverage report
# help: test-integration      - Run integration tests

.PHONY: test test-verbose coverage test-integration

test:
	@echo "$(C_BLUE)Running tests...$(C_RESET)"
	@$(GO) test -race -timeout=90s ./...

test-verbose:
	@echo "$(C_BLUE)Running tests (verbose)...$(C_RESET)"
	@$(GO) test -v -race -timeout=90s ./...

coverage:
	@mkdir -p $(DIST_DIR)
	@echo "$(C_BLUE)Generating coverage report...$(C_RESET)"
	@$(GO) test ./... -covermode=count -coverprofile=$(COVERPROFILE)
	@$(GO) tool cover -html=$(COVERPROFILE) -o $(COVERHTML)
	@echo "$(C_GREEN)✔ HTML coverage → $(COVERHTML)$(C_RESET)"

test-integration: build
	@echo "$(C_BLUE)Running integration tests...$(C_RESET)"
	@./test_integration.sh

# =============================================================================
# 🛠 BUILD & RUN
# =============================================================================
# help: 🛠 BUILD & RUN
# help: build                 - Build binary into ./dist
# help: install               - go install into GOPATH/bin
# help: release               - Cross-compile (honours GOOS/GOARCH)
# help: run                   - Build then run (stdio transport)
# help: run-translate         - Run with ContextForge translate on :9000

.PHONY: build install release run run-translate

build: tidy
	@mkdir -p $(DIST_DIR)
	@echo "$(C_BLUE)Building $(BIN_NAME)...$(C_RESET)"
	@CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(DIST_DIR)/$(BIN_NAME) .
	@echo "$(C_GREEN)✔ Built → $(DIST_DIR)/$(BIN_NAME)$(C_RESET)"

install:
	@echo "$(C_BLUE)Installing $(BIN_NAME)...$(C_RESET)"
	@$(GO) install -trimpath -ldflags '$(LDFLAGS)' .
	@echo "$(C_GREEN)✔ Installed → $(GOBIN)/$(BIN_NAME)$(C_RESET)"

release:
	@mkdir -p $(DIST_DIR)/$(GOOS)-$(GOARCH)
	@echo "$(C_BLUE)Building release for $(GOOS)/$(GOARCH)...$(C_RESET)"
	@GOOS=$(GOOS) GOARCH=$(GOARCH) CGO_ENABLED=0 \
	  $(GO) build -trimpath -ldflags '$(LDFLAGS)' \
	  -o $(DIST_DIR)/$(GOOS)-$(GOARCH)/$(BIN_NAME) .
	@echo "$(C_GREEN)✔ Release → $(DIST_DIR)/$(GOOS)-$(GOARCH)/$(BIN_NAME)$(C_RESET)"

run: build
	@echo "$(C_BLUE)Starting $(BIN_NAME) (stdio)...$(C_RESET)"
	@$(DIST_DIR)/$(BIN_NAME)

run-translate: build
	@echo "$(C_BLUE)Starting $(BIN_NAME) with ContextForge on :9000...$(C_RESET)"
	@python3 -m mcpgateway.translate --stdio "$(DIST_DIR)/$(BIN_NAME)" --port 9000

# =============================================================================
# 🐳 DOCKER
# =============================================================================
# help: 🐳 DOCKER
# help: docker-build          - Build container image
# help: docker-run            - Run container (stdio)
# help: docker-test           - Test container with pandoc conversion

IMAGE ?= $(BIN_NAME):$(VERSION)

.PHONY: docker-build docker-run docker-test

docker-build:
	@echo "$(C_BLUE)Building Docker image $(IMAGE)...$(C_RESET)"
	@docker build --build-arg VERSION=$(VERSION) -t $(IMAGE) .
	@docker images $(IMAGE)
	@echo "$(C_GREEN)✔ Docker image → $(IMAGE)$(C_RESET)"

docker-run: docker-build
	@echo "$(C_BLUE)Running Docker container...$(C_RESET)"
	@docker run --rm -i $(IMAGE)

docker-test: docker-build
	@echo "$(C_BLUE)Testing Docker container...$(C_RESET)"
	@echo '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}' | \
	  docker run --rm -i $(IMAGE) | python3 -m json.tool

# =============================================================================
# 📚 PANDOC SPECIFIC TESTS
# =============================================================================
# help: 📚 PANDOC TESTS
# help: test-pandoc           - Test pandoc conversion
# help: test-formats          - Test listing formats
# help: test-health           - Test health check

.PHONY: test-pandoc test-formats test-health

test-pandoc: build
	@echo "$(C_BLUE)Testing pandoc conversion...$(C_RESET)"
	@echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"pandoc","arguments":{"from":"markdown","to":"html","input":"# Hello\\n\\nThis is **bold** text."}},"id":1}' | \
	  timeout 2 $(DIST_DIR)/$(BIN_NAME) 2>/dev/null | python3 -m json.tool | head -20

test-formats: build
	@echo "$(C_BLUE)Testing format listing...$(C_RESET)"
	@echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"list-formats","arguments":{"type":"input"}},"id":1}' | \
	  timeout 2 $(DIST_DIR)/$(BIN_NAME) 2>/dev/null | python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print('Input formats:', len(d['result']['content'][0]['text'].split()))"

test-health: build
	@echo "$(C_BLUE)Testing health check...$(C_RESET)"
	@echo '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"health","arguments":{}},"id":1}' | \
	  timeout 2 $(DIST_DIR)/$(BIN_NAME) 2>/dev/null | python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print('pandoc' in d['result']['content'][0]['text'] and '✔ Health check passed' or '✖ Health check failed')"

# =============================================================================
# 🧹 CLEANUP
# =============================================================================
# help: 🧹 CLEANUP
# help: clean                 - Remove build & coverage artifacts
# help: clean-all             - Clean + remove tool binaries

.PHONY: clean clean-all

clean:
	@echo "$(C_BLUE)Cleaning build artifacts...$(C_RESET)"
	@rm -rf $(DIST_DIR) $(COVERPROFILE) $(COVERHTML)
	@echo "$(C_GREEN)✔ Workspace clean$(C_RESET)"

clean-all: clean
	@echo "$(C_BLUE)Removing tool binaries...$(C_RESET)"
	@rm -f $(GOBIN)/golangci-lint $(GOBIN)/staticcheck
	@echo "$(C_GREEN)✔ All clean$(C_RESET)"

# =============================================================================
# 🚀 QUICK DEVELOPMENT
# =============================================================================
# help: 🚀 QUICK DEVELOPMENT
# help: dev                   - Format, test, and build
# help: check                 - Run all checks (vet, lint, test)
# help: all                   - Full pipeline (fmt, check, build, test-pandoc)

.PHONY: dev check all

dev: fmt test build
	@echo "$(C_GREEN)✔ Development build complete$(C_RESET)"

check: vet lint test
	@echo "$(C_GREEN)✔ All checks passed$(C_RESET)"

all: fmt check build test-pandoc test-formats test-health
	@echo "$(C_GREEN)✔ Full pipeline complete$(C_RESET)"

# ---------------------------------------------------------------------------
# Default goal
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
