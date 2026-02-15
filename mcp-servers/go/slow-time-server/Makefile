# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   SLOW-TIME-SERVER - Makefile
#   (single-file Go project: main.go + main_test.go)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Author : Mihai Criveti
# Usage  : make <target>   or just `make help`
#
# help: SLOW-TIME-SERVER (Go build & automation helpers)
# ─────────────────────────────────────────────────────────────────────────

# =============================================================================
# DYNAMIC HELP
# =============================================================================
.PHONY: help
help:
	@grep '^# help\:' $(firstword $(MAKEFILE_LIST)) | sed 's/^# help\: //'

# =============================================================================
# PROJECT METADATA
# =============================================================================
MODULE          := github.com/yourorg/slow-time-server
BIN_NAME        := slow-time-server
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
# TOOLING
# =============================================================================
# help: TOOLING
# help: tools                 - Install / update golangci-lint & staticcheck

GOBIN := $(shell $(GO) env GOPATH)/bin

tools: $(GOBIN)/golangci-lint $(GOBIN)/staticcheck
$(GOBIN)/golangci-lint: ;	@$(GO) install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
$(GOBIN)/staticcheck:      ;	@$(GO) install honnef.co/go/tools/cmd/staticcheck@latest

# =============================================================================
# MODULE & FORMAT
# =============================================================================
# help: MODULE & FORMAT
# help: tidy                  - go mod tidy + verify
# help: fmt                   - Run gofmt & goimports

tidy:
	@$(GO) mod tidy
	@$(GO) mod verify

fmt:
	@$(GO) fmt ./...
	@go run golang.org/x/tools/cmd/goimports@latest -w .

# =============================================================================
# LINTING & STATIC ANALYSIS
# =============================================================================
# help: LINTING & STATIC ANALYSIS
# help: vet                   - go vet
# help: staticcheck           - Run staticcheck
# help: lint                  - Run golangci-lint
.PHONY: vet staticcheck lint

vet:
	@$(GO) vet ./...

staticcheck: tools
	@staticcheck ./...

lint: tools
	@golangci-lint run

# =============================================================================
# TESTS & COVERAGE
# =============================================================================
# help: TESTS & COVERAGE
# help: test                  - Run unit tests (race)
# help: coverage              - Generate HTML coverage report

test:
	@$(GO) test -race -timeout=90s ./...

coverage:
	@mkdir -p $(DIST_DIR)
	@$(GO) test ./... -covermode=count -coverprofile=$(COVERPROFILE)
	@$(GO) tool cover -html=$(COVERPROFILE) -o $(COVERHTML)
	@echo "$(C_BLUE)HTML coverage -> $(COVERHTML)$(C_RESET)"

# =============================================================================
# BUILD & RUN
# =============================================================================
# help: BUILD & RUN
# help: build                 - Build binary into ./dist
# help: install               - go install into GOPATH/bin
# help: run                   - Build then run (stdio transport)
# help: run-stdio             - Alias for "run"
# help: run-http              - Run HTTP  transport on :8081
# help: run-sse               - Run SSE   transport on :8081
# help: run-dual              - Run BOTH  SSE & HTTP on :8081
# help: run-rest              - Run REST API on :8081

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

run-stdio: run

run-http: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=http -addr=0.0.0.0:8081

run-sse: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=sse  -listen=0.0.0.0 -port=8081

run-dual: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=dual -port=8081

run-rest: build
	@$(DIST_DIR)/$(BIN_NAME) -transport=rest -port=8081

# =============================================================================
# DOCKER
# =============================================================================
# help: DOCKER
# help: docker-build          - Build container image
# help: docker-run            - Run container on :8081 (dual transport)
# help: docker-run-slow       - Run with 30s latency for timeout testing

IMAGE ?= $(BIN_NAME):$(VERSION)

docker-build:
	@docker build --build-arg VERSION=$(VERSION) -t $(IMAGE) .
	@docker images $(IMAGE)

docker-run: docker-build
	@docker run --rm -p 8081:8081 $(IMAGE)

docker-run-slow: docker-build
	@docker run --rm -p 8081:8081 \
	    -e DEFAULT_LATENCY=30s \
	    $(IMAGE)

# =============================================================================
# CLEANUP
# =============================================================================
# help: CLEANUP
# help: clean                 - Remove build & coverage artefacts

clean:
	@rm -rf $(DIST_DIR) $(COVERPROFILE) $(COVERHTML)
	@echo "Workspace clean"

# ---------------------------------------------------------------------------
# Default goal
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
