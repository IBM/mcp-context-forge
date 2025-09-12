# Calculator Server Makefile
# Go-based MCP Server for Mathematical Computations

.PHONY: all build test clean deps install lint fmt vet coverage help run docker

# Variables
BINARY_NAME=calculator-server
MAIN_PATH=./cmd/server
BUILD_DIR=./dist
COVERAGE_DIR=./coverage
COVERAGE_FILE=$(COVERAGE_DIR)/coverage.out
VERSION?=1.0.0
BUILD_TIME=$(shell date -u '+%Y-%m-%d_%H:%M:%S_UTC')
COMMIT_HASH=$(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# Go parameters
GOOS?=$(shell go env GOOS)
GOARCH?=$(shell go env GOARCH)
GO_BUILD_FLAGS=-ldflags="-X main.Version=$(VERSION) -X main.BuildTime=$(BUILD_TIME) -X main.CommitHash=$(COMMIT_HASH)"

# Colors for output
RED=\033[0;31m
GREEN=\033[0;32m
YELLOW=\033[1;33m
BLUE=\033[0;34m
NC=\033[0m # No Color

##@ General

help: ## Display this help message
	@echo "Calculator Server - Go MCP Server for Mathematical Computations"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "Usage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

all: deps fmt vet test build ## Run all build steps (deps, fmt, vet, test, build)

##@ Development

deps: ## Download and install dependencies
	@echo "$(BLUE)Installing dependencies...$(NC)"
	go mod download
	go mod tidy
	@echo "$(GREEN)Dependencies installed successfully$(NC)"

fmt: ## Format code using gofmt
	@echo "$(BLUE)Formatting code...$(NC)"
	go fmt ./...
	@echo "$(GREEN)Code formatted successfully$(NC)"

lint: ## Run golangci-lint (requires golangci-lint to be installed)
	@echo "$(BLUE)Running linter...$(NC)"
	@if which golangci-lint > /dev/null; then \
		golangci-lint run; \
		echo "$(GREEN)Linting completed successfully$(NC)"; \
	else \
		echo "$(YELLOW)golangci-lint not found, skipping...$(NC)"; \
		echo "$(YELLOW)Install it with: curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/master/install.sh | sh -s -- -b \$$(go env GOPATH)/bin v1.54.2$(NC)"; \
	fi

vet: ## Run go vet
	@echo "$(BLUE)Running go vet...$(NC)"
	go vet ./...
	@echo "$(GREEN)Vet completed successfully$(NC)"

##@ Testing

test: ## Run tests
	@echo "$(BLUE)Running tests...$(NC)"
	go test -v ./...
	@echo "$(GREEN)Tests completed successfully$(NC)"

test-short: ## Run short tests
	@echo "$(BLUE)Running short tests...$(NC)"
	go test -short ./...
	@echo "$(GREEN)Short tests completed successfully$(NC)"

coverage: ## Generate test coverage report
	@echo "$(BLUE)Generating coverage report...$(NC)"
	@mkdir -p $(COVERAGE_DIR)
	go test -v -race -coverprofile=$(COVERAGE_FILE) ./...
	go tool cover -html=$(COVERAGE_FILE) -o $(COVERAGE_DIR)/coverage.html
	go tool cover -func=$(COVERAGE_FILE) | grep total | awk '{print $$3}' > $(COVERAGE_DIR)/coverage.txt
	@echo "$(GREEN)Coverage report generated:$(NC)"
	@echo "  HTML: $(COVERAGE_DIR)/coverage.html"
	@echo "  Text: $(COVERAGE_DIR)/coverage.txt"
	@echo "  Coverage: $$(cat $(COVERAGE_DIR)/coverage.txt)"

test-race: ## Run tests with race detection
	@echo "$(BLUE)Running tests with race detection...$(NC)"
	go test -race ./...
	@echo "$(GREEN)Race tests completed successfully$(NC)"

benchmark: ## Run benchmarks
	@echo "$(BLUE)Running benchmarks...$(NC)"
	go test -bench=. -benchmem ./...
	@echo "$(GREEN)Benchmarks completed successfully$(NC)"

##@ Building

build: deps ## Build the application
	@echo "$(BLUE)Building $(BINARY_NAME)...$(NC)"
	@mkdir -p $(BUILD_DIR)
	CGO_ENABLED=0 GOOS=$(GOOS) GOARCH=$(GOARCH) go build $(GO_BUILD_FLAGS) -o $(BUILD_DIR)/$(BINARY_NAME) $(MAIN_PATH)
	@echo "$(GREEN)Build completed: $(BUILD_DIR)/$(BINARY_NAME)$(NC)"

build-all: ## Build for multiple platforms
	@echo "$(BLUE)Building for multiple platforms...$(NC)"
	@mkdir -p $(BUILD_DIR)

	# Linux AMD64
	@echo "Building for Linux AMD64..."
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build $(GO_BUILD_FLAGS) -o $(BUILD_DIR)/$(BINARY_NAME)-linux-amd64 $(MAIN_PATH)

	# Linux ARM64
	@echo "Building for Linux ARM64..."
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build $(GO_BUILD_FLAGS) -o $(BUILD_DIR)/$(BINARY_NAME)-linux-arm64 $(MAIN_PATH)

	# macOS AMD64
	@echo "Building for macOS AMD64..."
	CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build $(GO_BUILD_FLAGS) -o $(BUILD_DIR)/$(BINARY_NAME)-darwin-amd64 $(MAIN_PATH)

	# macOS ARM64 (M1/M2)
	@echo "Building for macOS ARM64..."
	CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build $(GO_BUILD_FLAGS) -o $(BUILD_DIR)/$(BINARY_NAME)-darwin-arm64 $(MAIN_PATH)

	# Windows AMD64
	@echo "Building for Windows AMD64..."
	CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build $(GO_BUILD_FLAGS) -o $(BUILD_DIR)/$(BINARY_NAME)-windows-amd64.exe $(MAIN_PATH)

	@echo "$(GREEN)Multi-platform build completed$(NC)"
	@ls -la $(BUILD_DIR)/

install: build ## Install the binary to $GOPATH/bin
	@echo "$(BLUE)Installing $(BINARY_NAME)...$(NC)"
	go install $(GO_BUILD_FLAGS) $(MAIN_PATH)
	@echo "$(GREEN)$(BINARY_NAME) installed to $$(go env GOPATH)/bin$(NC)"

##@ Running

run: build ## Build and run the server
	@echo "$(BLUE)Starting calculator server...$(NC)"
	$(BUILD_DIR)/$(BINARY_NAME) -transport=stdio

run-dev: ## Run the server without building (for development)
	@echo "$(BLUE)Starting calculator server in development mode...$(NC)"
	go run $(MAIN_PATH) -transport=stdio

##@ Docker

docker-build: ## Build Docker image
	@echo "$(BLUE)Building Docker image...$(NC)"
	docker build -t calculator-server:$(VERSION) -t calculator-server:latest .
	@echo "$(GREEN)Docker image built successfully$(NC)"

docker-run: ## Run Docker container
	@echo "$(BLUE)Running Docker container...$(NC)"
	docker run -i calculator-server:latest -transport=stdio

docker-push: ## Push Docker image to registry (requires login)
	@echo "$(BLUE)Pushing Docker image to registry...$(NC)"
	docker push calculator-server:$(VERSION)
	docker push calculator-server:latest
	@echo "$(GREEN)Docker image pushed successfully$(NC)"

##@ Quality Assurance

quality: fmt vet lint test coverage ## Run all quality checks
	@echo "$(GREEN)All quality checks completed successfully$(NC)"

pre-commit: quality build ## Run pre-commit checks
	@echo "$(GREEN)Pre-commit checks completed successfully$(NC)"

ci: deps fmt vet test coverage build ## Run CI pipeline
	@echo "$(GREEN)CI pipeline completed successfully$(NC)"

##@ Utilities

clean: ## Clean build artifacts and cache
	@echo "$(BLUE)Cleaning...$(NC)"
	rm -rf $(BUILD_DIR)
	rm -rf $(COVERAGE_DIR)
	go clean -cache
	go clean -testcache
	go clean -modcache
	@echo "$(GREEN)Cleanup completed$(NC)"

clean-build: ## Clean only build artifacts
	@echo "$(BLUE)Cleaning build artifacts...$(NC)"
	rm -rf $(BUILD_DIR)
	@echo "$(GREEN)Build artifacts cleaned$(NC)"

deps-update: ## Update dependencies
	@echo "$(BLUE)Updating dependencies...$(NC)"
	go get -u ./...
	go mod tidy
	@echo "$(GREEN)Dependencies updated$(NC)"

deps-audit: ## Audit dependencies for security vulnerabilities
	@echo "$(BLUE)Auditing dependencies...$(NC)"
	@if which govulncheck > /dev/null; then \
		govulncheck ./...; \
		echo "$(GREEN)Dependency audit completed$(NC)"; \
	else \
		echo "$(YELLOW)govulncheck not found, installing...$(NC)"; \
		go install golang.org/x/vuln/cmd/govulncheck@latest; \
		govulncheck ./...; \
		echo "$(GREEN)Dependency audit completed$(NC)"; \
	fi

version: ## Show version information
	@echo "Version: $(VERSION)"
	@echo "Build Time: $(BUILD_TIME)"
	@echo "Commit Hash: $(COMMIT_HASH)"
	@echo "Go Version: $$(go version)"
	@echo "Platform: $(GOOS)/$(GOARCH)"

##@ Release

release: clean quality build-all ## Create a release build
	@echo "$(BLUE)Creating release $(VERSION)...$(NC)"
	@mkdir -p $(BUILD_DIR)/release
	@for binary in $(BUILD_DIR)/$(BINARY_NAME)-*; do \
		echo "Packaging $$(basename $$binary)..."; \
		tar -czf $(BUILD_DIR)/release/$$(basename $$binary).tar.gz -C $(BUILD_DIR) $$(basename $$binary); \
	done
	@echo "$(GREEN)Release $(VERSION) created in $(BUILD_DIR)/release/$(NC)"
	@ls -la $(BUILD_DIR)/release/

##@ Documentation

docs: ## Generate documentation
	@echo "$(BLUE)Generating documentation...$(NC)"
	@if which godoc > /dev/null; then \
		echo "Starting godoc server at http://localhost:6060"; \
		echo "Navigate to http://localhost:6060/pkg/calculator-server/ to view documentation"; \
		godoc -http=:6060; \
	else \
		echo "$(YELLOW)godoc not found, installing...$(NC)"; \
		go install golang.org/x/tools/cmd/godoc@latest; \
		echo "Starting godoc server at http://localhost:6060"; \
		godoc -http=:6060; \
	fi

##@ Examples

example-basic: build ## Run basic math example
	@echo "$(BLUE)Running basic math example...$(NC)"
	@echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"basic_math","arguments":{"operation":"add","operands":[5,3,2],"precision":2}}}' | $(BUILD_DIR)/$(BINARY_NAME) -transport=stdio

example-expression: build ## Run expression evaluation example
	@echo "$(BLUE)Running expression evaluation example...$(NC)"
	@echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"expression_eval","arguments":{"expression":"sqrt(x^2 + y^2)","variables":{"x":3,"y":4}}}}' | $(BUILD_DIR)/$(BINARY_NAME) -transport=stdio

example-stats: build ## Run statistics example
	@echo "$(BLUE)Running statistics example...$(NC)"
	@echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"statistics","arguments":{"data":[1,2,3,4,5,6,7,8,9,10],"operation":"mean"}}}' | $(BUILD_DIR)/$(BINARY_NAME) -transport=stdio

example-http: build ## Run HTTP server example
	@echo "$(BLUE)Starting HTTP server example...$(NC)"
	@echo "Server will start on http://localhost:8080"
	@echo "Test with: curl -X POST http://localhost:8080/mcp -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}'"
	@echo "Health check: curl http://localhost:8080/health"
	@echo "Press Ctrl+C to stop the server"
	@$(BUILD_DIR)/$(BINARY_NAME) -transport=http -port=8080

example-http-config: build ## Run HTTP server with config file
	@echo "$(BLUE)Starting HTTP server with config file...$(NC)"
	@echo "Using config.sample.yaml configuration"
	@echo "Server will start on configured host:port"
	@echo "Press Ctrl+C to stop the server"
	@$(BUILD_DIR)/$(BINARY_NAME) -config=config.sample.yaml -transport=http

test-config: ## Test configuration file loading
	@echo "$(BLUE)Testing configuration file loading...$(NC)"
	@if [ -f config.sample.yaml ]; then \
		echo "YAML config found, testing..."; \
		go run $(MAIN_PATH) -config=config.sample.yaml -transport=stdio < /dev/null || echo "Config test completed"; \
	else \
		echo "$(YELLOW)config.sample.yaml not found$(NC)"; \
	fi

.DEFAULT_GOAL := help
