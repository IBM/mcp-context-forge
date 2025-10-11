.PHONY: tidy fmt test build run clean help

BIN ?= benchmark-server
GO  ?= go

help: ## Show this help message
	@echo "$(BIN) - Makefile targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

tidy: ## Download and tidy dependencies
	$(GO) mod tidy && $(GO) mod verify

fmt: ## Format Go code
	$(GO) fmt ./... && go run golang.org/x/tools/cmd/goimports@latest -w .

test: ## Run tests
	$(GO) test -race -timeout=90s ./...

build: ## Build the binary
	CGO_ENABLED=0 $(GO) build -trimpath -ldflags "-s -w" -o dist/$(BIN) .

run: build ## Build and run with default settings
	./dist/$(BIN)

run-small: build ## Run with small dataset (10 items each)
	./dist/$(BIN) -tools=10 -resources=10 -prompts=10

run-medium: build ## Run with medium dataset (100 items each)
	./dist/$(BIN) -tools=100 -resources=100 -prompts=100

run-large: build ## Run with large dataset (1000 items each)
	./dist/$(BIN) -tools=1000 -resources=1000 -prompts=1000

run-xlarge: build ## Run with extra large dataset (10000 items each)
	./dist/$(BIN) -tools=10000 -resources=10000 -prompts=10000

run-sse: build ## Run with SSE transport on port 8080
	./dist/$(BIN) -transport=sse -port=8080

run-http: build ## Run with HTTP transport on port 8080
	./dist/$(BIN) -transport=http -port=8080

clean: ## Remove build artifacts
	rm -rf dist
