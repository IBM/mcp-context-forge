# {{ cookiecutter.project_name }} - Makefile

.PHONY: help tidy fmt vet lint staticcheck test coverage build run clean tools

BIN_NAME ?= {{ cookiecutter.bin_name }}
DIST_DIR ?= dist
GO       ?= go

help: ## Show help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(firstword $(MAKEFILE_LIST)) | sed 's/:.*## /\t- /'

tools: ## Install linters
	@$(GO) install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
	@$(GO) install honnef.co/go/tools/cmd/staticcheck@latest

tidy: ## go mod tidy + verify
	@$(GO) mod tidy && $(GO) mod verify

fmt: ## gofmt + goimports
	@$(GO) fmt ./...
	@go run golang.org/x/tools/cmd/goimports@latest -w .

vet: ## go vet
	@$(GO) vet ./...

staticcheck: ## staticcheck
	@staticcheck ./...

lint: ## golangci-lint
	@golangci-lint run

test: ## unit tests
	@$(GO) test -race -timeout=90s ./...

coverage: ## HTML coverage report
	@mkdir -p $(DIST_DIR)
	@$(GO) test ./... -covermode=count -coverprofile=$(DIST_DIR)/coverage.out
	@$(GO) tool cover -html=$(DIST_DIR)/coverage.out -o $(DIST_DIR)/coverage.html
	@echo "HTML coverage -> $(DIST_DIR)/coverage.html"

build: ## Build binary
	@mkdir -p $(DIST_DIR)
	@CGO_ENABLED=0 $(GO) build -trimpath -ldflags "-s -w" -o $(DIST_DIR)/$(BIN_NAME) .

run: build ## Build then run (stdio)
	@$(DIST_DIR)/$(BIN_NAME)

clean: ## Clean dist
	@rm -rf $(DIST_DIR)
