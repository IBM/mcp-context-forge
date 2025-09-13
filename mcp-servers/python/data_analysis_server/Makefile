# Makefile for MCP Data Analysis Server

.PHONY: help build run test clean lint format install dev-install

# Variables
IMAGE_NAME ?= mcp-data-analysis-server
IMAGE_TAG ?= latest
CONTAINER_NAME ?= mcp-data-analysis-server
PYTHON ?= python3

# Help target
help: ## Show this help message
	@echo "🎯 MCP Data Analysis Server - Development Commands"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "🚀 Quick Start:"
	@echo "  make dev                 Start MCP server (stdio) with connection info"
	@echo "  make serve-http          Start HTTP server (JSON-RPC over HTTP)"
	@echo "  make example             Run data analysis example"
	@echo "  make mcp-info            Show MCP connection guide"
	@echo "  make http-info           Show HTTP server connection guide"
	@echo ""
	@echo "📋 Available Commands:"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "📚 For detailed usage, see README.md or run 'make mcp-info'"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Development setup
install: ## Install package in development mode
	$(PYTHON) -m pip install -e .

dev-install: ## Install with development dependencies
	$(PYTHON) -m pip install -e ".[dev]"

# Code quality
format: ## Format code with black and ruff
	black .
	ruff --fix .

lint: ## Run linting checks
	ruff check .
	mypy src/data_analysis_server

# Testing
test: ## Run all tests
	pytest tests/ -v --cov=data_analysis_server --cov-report=term-missing

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
		-v analysis-cache:/app/data/cache \
		-v analysis-results:/app/data/results \
		$(IMAGE_NAME):$(IMAGE_TAG)

run-docker: ## Run container with Docker
	docker run --rm -it \
		--name $(CONTAINER_NAME) \
		--env-file .env \
		-v analysis-cache:/app/data/cache \
		-v analysis-results:/app/data/results \
		$(IMAGE_NAME):$(IMAGE_TAG)

compose-up: ## Start services with docker-compose
	docker-compose up -d

compose-down: ## Stop services with docker-compose
	docker-compose down

compose-logs: ## View container logs
	docker-compose logs -f

# Development server
dev: ## Run development server locally
	@echo "🚀 Starting MCP Data Analysis Server..."
	@echo "📡 Protocol: stdio (Model Context Protocol)"
	@echo "🔧 Mode: Development"
	@echo "📊 Available Tools: 7 data analysis tools"
	@echo ""
	@echo "💡 How to connect:"
	@echo "   1. MCP Client (Claude Desktop, etc.):"
	@echo "      - Server command: python -m data_analysis_server.server"
	@echo "      - Working directory: $(PWD)"
	@echo "   2. Direct testing:"
	@echo "      - Run: make test-mcp"
	@echo "      - Or: make example"
	@echo ""
	@echo "📊 Available Tools:"
	@echo "   • load_data - Load and preview datasets from various formats"
	@echo "   • analyze_data - Perform statistical analysis on datasets"
	@echo "   • transform_data - Clean and transform data"
	@echo "   • query_data - Execute SQL-like queries on datasets"
	@echo "   • visualize_data - Create charts and plots"
	@echo "   • statistical_test - Perform hypothesis tests"
	@echo "   • time_series_analysis - Analyze time series data"
	@echo ""
	@echo "⚡ Starting server (Ctrl+C to stop)..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	$(PYTHON) -m data_analysis_server.server

# Testing with MCP client
test-mcp: ## Test MCP server functionality
	@echo "🧪 Testing MCP server with list_tools..."
	@echo ""
	echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}' | $(PYTHON) -m data_analysis_server.server

# Cleanup
clean: ## Clean up containers and volumes
	podman rm -f $(CONTAINER_NAME) 2>/dev/null || true
	podman rmi -f $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true

clean-docker: ## Clean up with Docker
	docker rm -f $(CONTAINER_NAME) 2>/dev/null || true
	docker rmi -f $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true

clean-volumes: ## Remove data volumes
	podman volume rm analysis-cache analysis-results 2>/dev/null || true

# Security scanning
scan: ## Scan container for vulnerabilities
	trivy image $(IMAGE_NAME):$(IMAGE_TAG)

# Example usage
example: ## Run data analysis example
	@echo "🎯 Running example data analysis..."
	@echo "📊 Loading sample sales data and performing basic analysis"
	@echo ""
	@$(PYTHON) -c "import asyncio, json; from data_analysis_server.core.data_loader import DataLoader; from data_analysis_server.core.analyzer import DataAnalyzer; exec('async def main():\n    loader = DataLoader()\n    analyzer = DataAnalyzer()\n    # Load sample data\n    result = await loader.load_data(\"sample_data/sales_data.csv\", {\"format\": \"csv\"})\n    print(\"✅ Loaded sample sales data:\")\n    print(json.dumps(result, indent=2)[:500] + \"...\")\n    # Perform basic analysis\n    analysis = await analyzer.analyze_data(\"sales_data\", {\"analysis_type\": \"descriptive\", \"columns\": [\"Revenue\"]})\n    print(\"\\n📈 Basic statistics:\")\n    print(json.dumps(analysis, indent=2))\nasyncio.run(main())')"
	@echo ""
	@echo "✅ Example completed! This shows basic data loading and analysis."

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
	@echo "🔍 Checking environment configuration..."
	@echo ""
	@echo "📊 Available data analysis capabilities:"
	@echo "   • Data Loading: CSV, JSON, Excel, Parquet formats"
	@echo "   • Statistical Analysis: Descriptive statistics, correlation, regression"
	@echo "   • Data Transformation: Cleaning, filtering, aggregation"
	@echo "   • Visualization: Matplotlib, Seaborn, Plotly charts"
	@echo "   • Query Engine: SQL-like operations on datasets"
	@echo "   • Time Series: Trend analysis, seasonality detection"
	@echo "   • Hypothesis Testing: t-tests, chi-square, ANOVA"
	@echo ""
	@echo "✅ Environment check complete"

mcp-info: ## Show MCP connection information
	@echo "📡 MCP Data Analysis Server Connection Guide"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "🔧 Server Command:"
	@echo "   python -m data_analysis_server.server"
	@echo ""
	@echo "📂 Working Directory:"
	@echo "   $(PWD)"
	@echo ""
	@echo "📡 Protocol: stdio (Model Context Protocol)"
	@echo "🌐 Transport: Standard input/output (no HTTP port)"
	@echo ""
	@echo "🔌 MCP Client Configuration:"
	@echo "   {"
	@echo "     \"command\": \"python\","
	@echo "     \"args\": [\"-m\", \"data_analysis_server.server\"],"
	@echo "     \"cwd\": \"$(PWD)\""
	@echo "   }"
	@echo ""
	@echo "🛠️  Available Tools: 7 data analysis tools"
	@echo "   • load_data - Load datasets from files or URLs"
	@echo "   • analyze_data - Statistical analysis and summaries"
	@echo "   • transform_data - Data cleaning and transformation"
	@echo "   • query_data - SQL-like queries on datasets"
	@echo "   • visualize_data - Generate charts and plots"
	@echo "   • statistical_test - Hypothesis testing"
	@echo "   • time_series_analysis - Time series analysis and forecasting"
	@echo ""
	@echo "⚡ Quick Test:"
	@echo "   make example                       # Run data analysis example"
	@echo "   make test-mcp                      # Test MCP protocol"
	@echo ""
	@echo "📚 Documentation:"
	@echo "   See README.md for comprehensive usage examples"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# HTTP/REST API Server Configuration
HTTP_PORT ?= 9000
HTTP_HOST ?= localhost

# HTTP Server via mcpgateway.translate (MCP over HTTP)
serve-http: ## Run as HTTP server (MCP over HTTP with SSE)
	@echo "🌐 Starting MCP Data Analysis Server as HTTP service..."
	@echo "📡 Protocol: HTTP with Server-Sent Events (SSE)"
	@echo "🔓 Authentication: None (open access)"
	@echo "🌍 URL: http://$(HTTP_HOST):$(HTTP_PORT)"
	@echo ""
	@echo "🔌 HTTP Endpoints:"
	@echo "   GET  /                          # Server info and available tools"
	@echo "   POST /                          # MCP JSON-RPC endpoint"
	@echo "   GET  /sse                       # Server-sent events stream"
	@echo ""
	@echo "📚 Example usage:"
	@echo "   curl http://$(HTTP_HOST):$(HTTP_PORT)/"
	@echo ""
	@echo "💡 MCP JSON-RPC call:"
	@echo "   curl -X POST -H 'Content-Type: application/json' \\"
	@echo "        -d '{\"jsonrpc\": \"2.0\", \"id\": 1, \"method\": \"tools/list\", \"params\": {}}' \\"
	@echo "        http://$(HTTP_HOST):$(HTTP_PORT)/"
	@echo ""
	@echo "⚡ Starting HTTP server (Ctrl+C to stop)..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	python3 -m mcpgateway.translate \
	   --stdio "python3 -m data_analysis_server.server" \
	   --port $(HTTP_PORT) \
	   --host $(HTTP_HOST) \
	   --expose-sse

serve-http-public: ## Run HTTP server accessible from any IP
	@echo "🌐 Starting MCP Data Analysis Server as PUBLIC HTTP service..."
	@echo "⚠️  WARNING: Server will be accessible from ANY IP address!"
	@echo "📡 Protocol: HTTP with Server-Sent Events (SSE)"
	@echo "🔓 Authentication: None (open access)"
	@echo "🌍 URL: http://0.0.0.0:$(HTTP_PORT) (accessible from any IP)"
	@echo ""
	@echo "⚡ Starting PUBLIC HTTP server (Ctrl+C to stop)..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	python3 -m mcpgateway.translate \
	   --stdio "python3 -m data_analysis_server.server" \
	   --port $(HTTP_PORT) \
	   --host 0.0.0.0 \
	   --expose-sse

test-http: ## Test HTTP server endpoints (MCP over HTTP)
	@echo "🧪 Testing HTTP server endpoints..."
	@echo "📍 Server URL: http://$(HTTP_HOST):$(HTTP_PORT)"
	@echo ""
	@echo "1️⃣  Testing server info..."
	@curl -s "http://$(HTTP_HOST):$(HTTP_PORT)/" | head -10 || echo "❌ Server info failed"
	@echo ""
	@echo ""
	@echo "2️⃣  Testing tools list via JSON-RPC..."
	@curl -s -X POST \
	      -H "Content-Type: application/json" \
	      -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}' \
	      "http://$(HTTP_HOST):$(HTTP_PORT)/" | head -20 || echo "❌ Tools list failed"
	@echo ""
	@echo ""
	@echo "3️⃣  Testing data loading via JSON-RPC..."
	@curl -s -X POST \
	      -H "Content-Type: application/json" \
	      -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "load_data", "arguments": {"file_path": "sample_data/sales_data.csv", "options": {"format": "csv", "preview_rows": 5}}}}' \
	      "http://$(HTTP_HOST):$(HTTP_PORT)/" || echo "❌ Data loading failed"
	@echo ""
	@echo "✅ HTTP testing complete!"

http-info: ## Show HTTP server connection information
	@echo "📡 MCP Data Analysis Server - HTTP Mode Connection Guide"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "🌐 HTTP Server Configuration:"
	@echo "   Host: $(HTTP_HOST)"
	@echo "   Port: $(HTTP_PORT)"
	@echo "   URL:  http://$(HTTP_HOST):$(HTTP_PORT)"
	@echo ""
	@echo "🔓 Authentication: None (open access)"
	@echo ""
	@echo "📡 Available Endpoints:"
	@echo "   GET  /                                 # Server info and tool discovery"
	@echo "   POST /                                 # MCP JSON-RPC endpoint (all tools)"
	@echo "   GET  /sse                              # Server-sent events stream"
	@echo ""
	@echo "🧪 Testing Commands:"
	@echo "   make serve-http                        # Start local HTTP server"
	@echo "   make serve-http-public                 # Start server accessible from any IP"
	@echo "   make test-http                         # Test HTTP endpoints"
	@echo ""
	@echo "🔧 Custom Configuration:"
	@echo "   make serve-http HTTP_PORT=8080         # Custom port"
	@echo "   make serve-http HTTP_HOST=0.0.0.0      # Public access"
	@echo ""
	@echo "💡 Example JSON-RPC Requests:"
	@echo ""
	@echo "   # List tools"
	@echo "   curl -X POST -H 'Content-Type: application/json' \\"
	@echo "        -d '{\"jsonrpc\": \"2.0\", \"id\": 1, \"method\": \"tools/list\", \"params\": {}}' \\"
	@echo "        http://$(HTTP_HOST):$(HTTP_PORT)/"
	@echo ""
	@echo "   # Load data"
	@echo "   curl -X POST -H 'Content-Type: application/json' \\"
	@echo "        -d '{\"jsonrpc\": \"2.0\", \"id\": 2, \"method\": \"tools/call\",' \\"
	@echo "        -d '     \"params\": {\"name\": \"load_data\",' \\"
	@echo "        -d '                 \"arguments\": {\"file_path\": \"data.csv\", \"options\": {\"format\": \"csv\"}}}}' \\"
	@echo "        http://$(HTTP_HOST):$(HTTP_PORT)/"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

generate-token: ## Generate a secure bearer token
	@echo "🔐 Generating secure bearer token..."
	@TOKEN=$$(python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters + string.digits + '-_') for _ in range(32)))"); \
	echo "🔑 Generated token: $$TOKEN"; \
	echo ""; \
	echo "💡 To use this token:"; \
	echo "   export BEARER_TOKEN=$$TOKEN"; \
	echo "   make serve-http BEARER_TOKEN=$$TOKEN"; \
	echo ""; \
	echo "🔒 Keep this token secure and don't commit it to version control!"