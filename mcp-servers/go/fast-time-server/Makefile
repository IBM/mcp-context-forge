# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   🦫 FAST-TIME-SERVER – Makefile
#   (single-file Go project: main.go + main_test.go)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Author : Mihai Criveti
# Usage  : make <target>   or just `make help`
#
# help: 🦫 FAST-TIME-SERVER (Go build & automation helpers)
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
MODULE          := github.com/yourorg/fast-time-server
BIN_NAME        := fast-time-server
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

build: tidy
	@mkdir -p $(DIST_DIR)
	@$(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(DIST_DIR)/$(BIN_NAME) .

install:
	@$(GO) install -trimpath -ldflags '$(LDFLAGS)' .

release:
	@mkdir -p $(DIST_DIR)/$(GOOS)-$(GOARCH)
	@GOOS=$(GOOS) GOARCH=$(GOARCH) CGO_ENABLED=0 \
	  $(GO) build -trimpath -ldflags '$(LDFLAGS)' \
	  -o $(DIST_DIR)/$(GOOS)-$(GOARCH)/$(BIN_NAME) .

# ────── run helpers ────────────────────────────────────────────────────────
run: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=stdio

run-stdio: run			# simple alias

run-http: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=http -addr=0.0.0.0:8080

run-sse: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=sse  -listen=0.0.0.0 -port=8080

run-dual: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=dual -port=8080

# =============================================================================
# 🐳 DOCKER
# =============================================================================
# help: 🐳 DOCKER
# help: docker-build          - Build container image
# help: docker-run            - Run container on :8080 (HTTP transport)
# help: docker-run-sse        - Run container on :8080 (SSE transport)
# help: docker-run-sse-auth   - Run SSE with Bearer token auth (TOKEN env or default)

IMAGE ?= $(BIN_NAME):$(VERSION)
TOKEN ?= secret123            # override:  make docker-run-sse-auth TOKEN=mytoken

docker-build:
	@docker build --build-arg VERSION=$(VERSION) -t $(IMAGE) .
	@docker images $(IMAGE)

docker-run: docker-build
	@docker run --rm -p 8080:8080 $(IMAGE) -transport=http -addr=0.0.0.0:8080

docker-run-sse: docker-build
	@docker run --rm -p 8080:8080 $(IMAGE) -transport=sse -listen=0.0.0.0 -port=8080

docker-run-sse-auth: docker-build
	@docker run --rm -p 8080:8080 \
	    -e AUTH_TOKEN=$(TOKEN) \
	    $(IMAGE) -transport=sse -listen=0.0.0.0 -port=8080 -auth-token=$(TOKEN)

# =============================================================================
# 🚀 BENCHMARKING (hey)
# =============================================================================
# help: 🚀 BENCHMARKING
# help: bench                 - Run HTTP load test using 'hey' on /http (run make dual first)

.PHONY: bench

bench:
	@command -v hey >/dev/null || { echo '"hey" not installed'; exit 1; }
	@echo "➜ load-test convert_time via /http"
	@hey -m POST -T 'application/json' \
	     -D payload.json \
	     -n 100000 -c 100 http://localhost:8080/http

# =============================================================================
# 🧹 CLEANUP
# =============================================================================
# help: 🧹 CLEANUP
# help: clean                 - Remove build & coverage artefacts

clean:
	@rm -rf $(DIST_DIR) $(COVERPROFILE) $(COVERHTML)
	@echo "Workspace clean ✔"

# ---------------------------------------------------------------------------
# Default goal
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
