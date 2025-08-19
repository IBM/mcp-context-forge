# Makefile for MCP Evaluation Server

.PHONY: help build run test clean lint format install dev-install

# Variables
IMAGE_NAME ?= mcp-eval-server
IMAGE_TAG ?= latest
CONTAINER_NAME ?= mcp-eval-server
PYTHON ?= python3

# Help target
help: ## Show this help message
	@echo "MCP Evaluation Server - Make targets:"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Development setup
install: ## Install package in development mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with development dependencies
	$(PYTHON) -m pip install -e ".[dev]"

# Code quality
format: ## Format code with black and isort
	black .
	isort .

lint: ## Run linting checks
	flake8 mcp_eval_server tests
	mypy mcp_eval_server

# Testing
test: ## Run all tests
	pytest tests/ -v --cov=mcp_eval_server --cov-report=term-missing

test-fast: ## Run tests without coverage
	pytest tests/ -v

# Container operations
build: ## Build container image
	podman build -f Containerfile -t $(IMAGE_NAME):$(IMAGE_TAG) .

build-docker: ## Build container image with Docker
	docker build -f Containerfile -t $(IMAGE_NAME):$(IMAGE_TAG) .

run: ## Run container with environment file
	podman run --rm -it \
		--name $(CONTAINER_NAME) \
		--env-file .env \
		-v eval-cache:/app/data/cache \
		-v eval-results:/app/data/results \
		$(IMAGE_NAME):$(IMAGE_TAG)

run-docker: ## Run container with Docker
	docker run --rm -it \
		--name $(CONTAINER_NAME) \
		--env-file .env \
		-v eval-cache:/app/data/cache \
		-v eval-results:/app/data/results \
		$(IMAGE_NAME):$(IMAGE_TAG)

compose-up: ## Start services with docker-compose
	docker-compose up -d

compose-down: ## Stop services with docker-compose
	docker-compose down

compose-logs: ## View container logs
	docker-compose logs -f

# Development server
dev: ## Run development server locally
	$(PYTHON) -m mcp_eval_server.server

# Testing with MCP client
test-mcp: ## Test MCP server functionality
	echo '{"method": "tools/list", "params": {}}' | $(PYTHON) -m mcp_eval_server.server

# Cleanup
clean: ## Clean up containers and volumes
	podman rm -f $(CONTAINER_NAME) 2>/dev/null || true
	podman rmi -f $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true

clean-docker: ## Clean up with Docker
	docker rm -f $(CONTAINER_NAME) 2>/dev/null || true
	docker rmi -f $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true

clean-volumes: ## Remove data volumes
	podman volume rm eval-cache eval-results 2>/dev/null || true

# Security scanning
scan: ## Scan container for vulnerabilities
	trivy image $(IMAGE_NAME):$(IMAGE_TAG)

# Example usage
example: ## Run example evaluation
	@$(PYTHON) -c "import asyncio, json; from mcp_eval_server.tools.judge_tools import JudgeTools; import asyncio; exec('async def main():\n    jt = JudgeTools()\n    result = await jt.evaluate_response(response=\"Paris is the capital of France.\", criteria=[{\"name\": \"accuracy\", \"description\": \"Factual accuracy\", \"scale\": \"1-5\", \"weight\": 1.0}], rubric={\"criteria\": [], \"scale_description\": {\"1\": \"Wrong\", \"5\": \"Correct\"}}, judge_model=\"rule-based\")\n    print(json.dumps(result, indent=2))\nasyncio.run(main())')"

# Documentation
docs: ## Generate documentation
	mkdocs build

docs-serve: ## Serve documentation locally
	mkdocs serve

# Release
release: test lint build ## Run tests, lint, and build for release
	@echo "Release build completed successfully"

# Check environment
check-env: ## Check required environment variables
	@echo "Checking environment configuration..."
	@if [ -z "$$OPENAI_API_KEY" ] && [ -z "$$AZURE_OPENAI_KEY" ]; then \
		echo "WARNING: No API keys found. Set OPENAI_API_KEY or AZURE_OPENAI_KEY"; \
		echo "Example: export OPENAI_API_KEY='sk-...'"; \
	else \
		echo "✓ API keys configured"; \
	fi
	@echo "✓ Environment check complete"
