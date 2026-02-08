# MCP LangChain Agent - Development Makefile
# ==========================================

.PHONY: help install install-dev test lint format clean run dev docker health check-env setup-env

# Default target
help: ## Show this help message
	@echo "MCP LangChain Agent Development Commands"
	@echo "======================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Development Environment
install: ## Install production dependencies
	pip install -e .

install-dev: ## Install development dependencies
	pip install -e ".[dev]"
	pip install pre-commit
	pre-commit install

# LLM Provider Dependencies
install-azure: ## Install Azure OpenAI dependencies
	pip install -e ".[azure]"

install-bedrock: ## Install AWS Bedrock dependencies
	pip install -e ".[bedrock]"

install-ollama: ## Install OLLAMA dependencies
	pip install -e ".[ollama]"

install-anthropic: ## Install Anthropic dependencies
	pip install -e ".[anthropic]"

install-all-providers: ## Install all LLM provider dependencies
	pip install -e ".[all-providers]"

setup-env: ## Setup environment from template
	@if [ ! -f .env ]; then \
		echo "Creating .env from template..."; \
		cp .env.example .env; \
		echo "✅ Created .env file - please edit with your configuration"; \
	else \
		echo "✅ .env file already exists"; \
	fi

# Code Quality
lint: ## Run all linting checks
	@echo "🔍 Running linting checks..."
	ruff check .
	mypy .
	bandit -r . -f json -o bandit-report.json || bandit -r .

format: ## Format code with black and ruff
	@echo "🎨 Formatting code..."
	ruff format .
	ruff check --fix .

# Testing
test: ## Run all tests
	@echo "🧪 Running tests..."
	pytest -v --cov=. --cov-report=html --cov-report=term

test-fast: ## Run tests without coverage
	pytest -v -x

# Environment Validation
check-env: ## Validate environment configuration
	@echo "🔍 Checking environment configuration..."
	@python3 -c "from config import validate_environment; import json; result = validate_environment(); print(json.dumps(result, indent=2)); exit(0 if result['valid'] else 1)"

# Application Management
run: check-env ## Run the agent in production mode
	@echo "🚀 Starting MCP LangChain Agent..."
	uvicorn app:app --host 127.0.0.1 --port 8000

dev: check-env ## Run the agent in development mode with auto-reload
	@echo "🔧 Starting MCP LangChain Agent in development mode..."
	uvicorn app:app --host 127.0.0.1 --port 8000 --reload

# Health Checks
health: ## Check agent health status
	@echo "🏥 Checking agent health..."
	@curl -s http://localhost:8000/health | jq . || echo "Agent not responding"

ready: ## Check agent readiness
	@echo "⚡ Checking agent readiness..."
	@curl -s http://localhost:8000/ready | jq . || echo "Agent not ready"

tools: ## List available tools
	@echo "🔧 Listing available tools..."
	@curl -s http://localhost:8000/list_tools | jq . || echo "Cannot list tools"

# Testing Endpoints
test-chat: ## Test basic chat completion
	@echo "💬 Testing chat completion..."
	@curl -X POST http://localhost:8000/v1/chat/completions \
		-H "Content-Type: application/json" \
		-d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hello! What tools do you have?"}]}' \
		| jq .

test-a2a: ## Test A2A endpoint
	@echo "🤖 Testing A2A endpoint..."
	@curl -X POST http://localhost:8000/a2a \
		-H "Content-Type: application/json" \
		-d '{"jsonrpc": "2.0", "id": "1", "method": "list_tools", "params": {}}' \
		| jq .

# Docker Support
docker-build: ## Build Docker image
	docker build -t mcp-langchain-agent .

docker-run: ## Run Docker container
	docker run -p 8000:8000 --env-file .env mcp-langchain-agent

# Cleanup
clean: ## Clean up generated files
	@echo "🧹 Cleaning up..."
	rm -rf __pycache__ .pytest_cache .mypy_cache .coverage htmlcov
	rm -rf build dist *.egg-info
	rm -f bandit-report.json

# Documentation
docs: ## Generate documentation
	@echo "📚 Generating documentation..."
	@echo "Available endpoints:"
	@echo "  GET  /health           - Health check"
	@echo "  GET  /ready            - Readiness check"
	@echo "  GET  /list_tools       - Available tools"
	@echo "  POST /v1/chat/completions - OpenAI-compatible chat"
	@echo "  POST /a2a              - A2A JSON-RPC endpoint"

# Development Workflow
all: clean install-dev lint test ## Full development workflow
	@echo "✅ All checks passed!"

ci: lint test ## CI pipeline checks
	@echo "✅ CI checks passed!"

# Quick Development Commands
serve: dev ## Alias for dev command

start: run ## Alias for run command

# Environment Management
env-example: ## Show example environment configuration
	@python3 -c "from config import get_example_env; print(get_example_env())"

# Provider-specific environment setup
setup-azure: ## Setup Azure OpenAI environment
	@echo "Setting up Azure OpenAI environment..."
	@cp examples/azure-openai.env .env
	@echo "✅ Created .env for Azure OpenAI - please edit with your credentials"

setup-bedrock: ## Setup AWS Bedrock environment
	@echo "Setting up AWS Bedrock environment..."
	@cp examples/aws-bedrock.env .env
	@echo "✅ Created .env for AWS Bedrock - please edit with your credentials"

setup-ollama: ## Setup OLLAMA environment
	@echo "Setting up OLLAMA environment..."
	@cp examples/ollama.env .env
	@echo "✅ Created .env for OLLAMA - please edit with your model preferences"

setup-anthropic: ## Setup Anthropic environment
	@echo "Setting up Anthropic environment..."
	@cp examples/anthropic.env .env
	@echo "✅ Created .env for Anthropic - please edit with your API key"

# Security
security: ## Run security checks
	@echo "🔒 Running security checks..."
	bandit -r . -f json -o bandit-report.json
	@echo "Security report saved to bandit-report.json"

# Dependencies
update-deps: ## Update dependencies
	pip install --upgrade pip
	pip install --upgrade -r requirements.txt

# Status
status: ## Show development status
	@echo "📊 MCP LangChain Agent Status"
	@echo "============================="
	@echo "Python: $$(python3 --version)"
	@echo "FastAPI: $$(python3 -c 'import fastapi; print(fastapi.__version__)')"
	@echo "LangChain: $$(python3 -c 'import langchain; print(langchain.__version__)')"
	@echo "Working Directory: $$(pwd)"
	@echo "Environment File: $$([ -f .env ] && echo '✅ Present' || echo '❌ Missing')"
	@echo "Gateway Status: $$(curl -s http://localhost:4444/health >/dev/null && echo '✅ Running' || echo '❌ Not running')"
