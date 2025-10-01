# System Monitor Server Makefile
# This Makefile provides common build, test, and development tasks

.PHONY: help build test test-coverage coverage clean run install deps lint fmt vet

# Default target
help:
	@echo "Available targets:"
	@echo "  build         - Build the system-monitor-server binary"
	@echo "  test          - Run all tests"
	@echo "  test-coverage - Run comprehensive test suite with coverage report"
	@echo "  coverage      - Generate coverage report only"
	@echo "  clean         - Clean build artifacts"
	@echo "  run           - Run the server in stdio mode"
	@echo "  install       - Install the binary to GOPATH/bin"
	@echo "  deps          - Download and verify dependencies"
	@echo "  lint          - Run linters"
	@echo "  fmt           - Format code"
	@echo "  vet           - Run go vet"
	@echo "  docker        - Build Docker image"
	@echo "  examples      - Run example commands"

# Build the binary
build:
	@echo "Building system-monitor-server..."
	@go build -o system-monitor-server ./cmd/server
	@echo "Build complete: system-monitor-server"

# Run tests
test:
	@echo "Running tests..."
	@go test -v -race ./...
	@echo "Tests completed!"

# Run comprehensive test suite with coverage
test-coverage:
	@echo "Running comprehensive test suite with coverage..."
	@chmod +x ./test_coverage.sh
	@./test_coverage.sh

# Generate coverage report only
coverage:
	@echo "Generating coverage report..."
	@chmod +x ./test_coverage.sh
	@./test_coverage.sh

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	@rm -f system-monitor-server
	@rm -f coverage.out coverage.html
	@rm -rf coverage/
	@go clean

# Run the server in stdio mode
run: build
	@echo "Running system-monitor-server in stdio mode..."
	@./system-monitor-server -log-level=info

# Install the binary
install: build
	@echo "Installing system-monitor-server..."
	@go install ./cmd/server
	@echo "Installed to: $(shell go env GOPATH)/bin/system-monitor-server"

# Download dependencies
deps:
	@echo "Downloading dependencies..."
	@go mod download
	@go mod verify
	@echo "Dependencies downloaded and verified"

# Run linters
lint:
	@echo "Running linters..."
	@if command -v golangci-lint >/dev/null 2>&1; then \
		golangci-lint run; \
	else \
		echo "golangci-lint not found, installing..."; \
		go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest; \
		golangci-lint run; \
	fi

# Format code
fmt:
	@echo "Formatting code..."
	@go fmt ./...
	@if command -v goimports >/dev/null 2>&1; then \
		goimports -w .; \
	else \
		echo "goimports not found, installing..."; \
		go install golang.org/x/tools/cmd/goimports@latest; \
		goimports -w .; \
	fi

# Run go vet
vet:
	@echo "Running go vet..."
	@go vet ./...

# Build Docker image
docker:
	@echo "Building Docker image..."
	@docker build -t system-monitor-server:latest .
	@echo "Docker image built: system-monitor-server:latest"

# Run example commands
examples: build
	@echo "Running example commands..."
	@echo ""
	@echo "1. Get system metrics:"
	@echo 'echo '"'"'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_system_metrics","arguments":{}},"id":1}'"'"' | ./system-monitor-server'
	@echo ""
	@echo "2. List processes:"
	@echo 'echo '"'"'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"list_processes","arguments":{"sort_by":"cpu","limit":5}},"id":2}'"'"' | ./system-monitor-server'
	@echo ""
	@echo "3. Check service health:"
	@echo 'echo '"'"'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"check_service_health","arguments":{"services":[{"name":"web","type":"http","target":"http://localhost:8080/health"}]}},"id":3}'"'"' | ./system-monitor-server'

# Development server with hot reload
dev:
	@echo "Starting development server with hot reload..."
	@if command -v air >/dev/null 2>&1; then \
		air; \
	else \
		echo "air not found, installing..."; \
		go install github.com/cosmtrek/air@latest; \
		air; \
	fi

# Generate mocks for testing
mocks:
	@echo "Generating mocks..."
	@if command -v mockgen >/dev/null 2>&1; then \
		mockgen -source=internal/metrics/system.go -destination=internal/metrics/mocks/system_mock.go; \
		mockgen -source=internal/metrics/process.go -destination=internal/metrics/mocks/process_mock.go; \
		mockgen -source=internal/monitor/health_checker.go -destination=internal/monitor/mocks/health_checker_mock.go; \
		mockgen -source=internal/monitor/log_monitor.go -destination=internal/monitor/mocks/log_monitor_mock.go; \
	else \
		echo "mockgen not found, installing..."; \
		go install github.com/golang/mock/mockgen@latest; \
		mockgen -source=internal/metrics/system.go -destination=internal/metrics/mocks/system_mock.go; \
		mockgen -source=internal/metrics/process.go -destination=internal/metrics/mocks/process_mock.go; \
		mockgen -source=internal/monitor/health_checker.go -destination=internal/monitor/mocks/health_checker_mock.go; \
		mockgen -source=internal/monitor/log_monitor.go -destination=internal/monitor/mocks/log_monitor_mock.go; \
	fi

# Benchmark tests
bench:
	@echo "Running benchmarks..."
	@go test -bench=. -benchmem ./...

# Security scan
security:
	@echo "Running security scan..."
	@if command -v gosec >/dev/null 2>&1; then \
		gosec ./...; \
	else \
		echo "gosec not found, installing..."; \
		go install github.com/securecodewarrior/gosec/v2/cmd/gosec@latest; \
		gosec ./...; \
	fi

# All checks
check: fmt vet lint test security
	@echo "All checks passed!"

# Release build
release: clean
	@echo "Building release binaries..."
	@GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o system-monitor-server-linux-amd64 ./cmd/server
	@GOOS=darwin GOARCH=amd64 go build -ldflags="-s -w" -o system-monitor-server-darwin-amd64 ./cmd/server
	@GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o system-monitor-server-windows-amd64.exe ./cmd/server
	@echo "Release binaries built:"
	@ls -la system-monitor-server-*
