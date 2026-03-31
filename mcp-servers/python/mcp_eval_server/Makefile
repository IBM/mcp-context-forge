# Makefile for MCP Evaluation Server

.PHONY: help build run test clean lint format install dev-install

# Variables
IMAGE_NAME ?= mcp-eval-server
IMAGE_TAG ?= latest
CONTAINER_NAME ?= mcp-eval-server
PYTHON ?= python3

# Help target
help: ## Show this help message
	@echo "🎯 MCP Evaluation Server - Development Commands"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "🚀 Quick Start:"
	@echo "  make dev                 Start MCP server (stdio) with connection info"
	@echo "  make serve-http          Start HTTP server (JSON-RPC over HTTP)"
	@echo "  make example             Run evaluation example"
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
	@echo "🚀 Starting MCP Evaluation Server..."
	@echo "📡 Protocol: stdio (Model Context Protocol)"
	@echo "🔧 Mode: Development"
	@echo "📋 Available Tools: 29 evaluation tools"
	@echo ""
	@echo "💡 How to connect:"
	@echo "   1. MCP Client (Claude Desktop, etc.):"
	@echo "      - Server command: python -m mcp_eval_server.server"
	@echo "      - Working directory: $(PWD)"
	@echo "   2. Direct testing:"
	@echo "      - Run: make test-mcp"
	@echo "      - Or: make example"
	@echo ""
	@echo "🔑 API Keys (optional for LLM judges):"
	@echo "   export OPENAI_API_KEY='sk-...'"
	@echo "   export AZURE_OPENAI_KEY='...'"
	@echo ""
	@echo "⚡ Starting server (Ctrl+C to stop)..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	$(PYTHON) -m mcp_eval_server.server

# Testing with MCP client
test-mcp: ## Test MCP server functionality
	@echo "🧪 Testing MCP server with list_tools..."
	@echo ""
	echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}' | $(PYTHON) -m mcp_eval_server.server

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
	@echo "ℹ️  No repo-managed vulnerability scanner is configured for this image."

# Example usage
example: ## Run example evaluation
	@echo "🎯 Running example evaluation with rule-based judge..."
	@echo "📝 Evaluating: 'Paris is the capital of France.'"
	@echo "📊 Criteria: Factual accuracy (1-5 scale)"
	@echo ""
	@$(PYTHON) -c "import asyncio, json; from mcp_eval_server.tools.judge_tools import JudgeTools; import asyncio; exec('async def main():\n    jt = JudgeTools()\n    result = await jt.evaluate_response(response=\"Paris is the capital of France.\", criteria=[{\"name\": \"accuracy\", \"description\": \"Factual accuracy\", \"scale\": \"1-5\", \"weight\": 1.0}], rubric={\"criteria\": [], \"scale_description\": {\"1\": \"Wrong\", \"5\": \"Correct\"}}, judge_model=\"rule-based\")\n    print(json.dumps(result, indent=2))\nasyncio.run(main())')"
	@echo ""
	@echo "✅ Example completed! This shows rule-based evaluation without API keys."

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
	@if [ -z "$$OPENAI_API_KEY" ] && [ -z "$$AZURE_OPENAI_API_KEY" ]; then \
		echo "⚠️  WARNING: No API keys found for LLM judges"; \
		echo "📝 To use OpenAI judges: export OPENAI_API_KEY='sk-...'"; \
		echo "📝 To use Azure judges: export AZURE_OPENAI_API_KEY='...'"; \
		echo ""; \
		echo "✅ Rule-based judge available (no API key needed)"; \
	else \
		echo "✅ API keys configured for LLM judges"; \
	fi
	@echo ""
	@echo "📊 Available evaluation capabilities:"
	@echo "   • 4 Judge tools (evaluate, compare, rank, reference)"
	@echo "   • 4 Prompt tools (clarity, consistency, completeness, relevance)"
	@echo "   • 4 Agent tools (tool usage, task completion, reasoning, benchmarks)"
	@echo "   • 3 Quality tools (factuality, coherence, toxicity)"
	@echo "   • 3 Workflow tools (suites, execution, comparison)"
	@echo "   • 2 Calibration tools (agreement, optimization)"
	@echo "   • 9 Server tools (management, statistics, health)"
	@echo ""
	@echo "✅ Environment check complete"

validate-models: ## Run comprehensive model validation and connectivity tests
	@echo "🔍 Running model validation and connectivity tests..."
	$(PYTHON) validate_models.py

test-all-providers: ## Test all LLM providers (OpenAI, Azure, Anthropic, Bedrock, Gemini, Watsonx, OLLAMA)
	@echo "🧪 Testing all LLM provider implementations..."
	$(PYTHON) test_all_providers.py

validate-config: ## Validate custom configuration files
	@echo "🔍 Validating configuration files..."
	@if [ -n "$$MCP_EVAL_MODELS_CONFIG" ]; then \
		echo "📄 Validating custom models config: $$MCP_EVAL_MODELS_CONFIG"; \
		$(PYTHON) -c "import yaml; yaml.safe_load(open('$$MCP_EVAL_MODELS_CONFIG')); print('✅ Configuration syntax valid')"; \
	else \
		echo "📄 Validating default models config"; \
		$(PYTHON) -c "import yaml; yaml.safe_load(open('mcp_eval_server/config/models.yaml')); print('✅ Configuration syntax valid')"; \
	fi

copy-config: ## Copy default configuration for customization
	@echo "📋 Copying default configuration files for customization..."
	@mkdir -p ./custom-config
	@cp mcp_eval_server/config/models.yaml ./custom-config/models.yaml
	@cp mcp_eval_server/config/rubrics.yaml ./custom-config/rubrics.yaml
	@cp mcp_eval_server/config/benchmarks.yaml ./custom-config/benchmarks.yaml
	@cp mcp_eval_server/config/judge_prompts.yaml ./custom-config/judge_prompts.yaml
	@echo "✅ Configuration files copied to ./custom-config/"
	@echo "💡 To use custom config: export MCP_EVAL_MODELS_CONFIG='./custom-config/models.yaml'"

show-config: ## Show current configuration status
	@echo "🔧 Current Configuration Status:"
	@echo "   Models config: $${MCP_EVAL_MODELS_CONFIG:-default (mcp_eval_server/config/models.yaml)}"
	@echo "   Default judge: $${DEFAULT_JUDGE_MODEL:-gpt-4o-mini}"
	@echo "   Config dir: $${MCP_EVAL_CONFIG_DIR:-default (mcp_eval_server/config/)}"
	@echo ""
	@echo "🔑 Environment Variables:"
	@echo "   OPENAI_API_KEY: $${OPENAI_API_KEY:+✅ configured}$${OPENAI_API_KEY:-❌ not set}"
	@echo "   AZURE_OPENAI_API_KEY: $${AZURE_OPENAI_API_KEY:+✅ configured}$${AZURE_OPENAI_API_KEY:-❌ not set}"
	@echo "   ANTHROPIC_API_KEY: $${ANTHROPIC_API_KEY:+✅ configured}$${ANTHROPIC_API_KEY:-❌ not set}"
	@echo "   OLLAMA_BASE_URL: $${OLLAMA_BASE_URL:-❌ not set}"

mcp-info: ## Show MCP connection information
	@echo "📡 MCP Evaluation Server Connection Guide"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "🔧 Server Command:"
	@echo "   python -m mcp_eval_server.server"
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
	@echo "     \"args\": [\"-m\", \"mcp_eval_server.server\"],"
	@echo "     \"cwd\": \"$(PWD)\""
	@echo "   }"
	@echo ""
	@echo "🛠️  Available Tools: 29 evaluation tools"
	@echo "   • judge.evaluate_response"
	@echo "   • judge.pairwise_comparison"
	@echo "   • prompt.evaluate_clarity"
	@echo "   • agent.evaluate_tool_use"
	@echo "   • quality.assess_toxicity"
	@echo "   • workflow.create_evaluation_suite"
	@echo "   • calibration.test_judge_agreement"
	@echo "   • server.get_available_judges"
	@echo "   • ...and 21 more tools"
	@echo ""
	@echo "🔑 Optional API Keys:"
	@echo "   export OPENAI_API_KEY='sk-...'     # For GPT-4, GPT-3.5 judges"
	@echo "   export AZURE_OPENAI_API_KEY='...'  # For Azure OpenAI judges"
	@echo ""
	@echo "⚡ Quick Test:"
	@echo "   make example                       # Run evaluation example"
	@echo "   make test-mcp                      # Test MCP protocol"
	@echo ""
	@echo "📚 Documentation:"
	@echo "   See README.md for comprehensive usage examples"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# HTTP/REST API Server Configuration
HTTP_PORT ?= 9000
REST_PORT ?= 8080
HTTP_HOST ?= localhost
BEARER_TOKEN ?= eval-server-token-123

# HTTP Server via mcpgateway.translate (MCP over HTTP)
serve-http: ## Run as HTTP server (MCP over HTTP with SSE)
	@echo "🌐 Starting MCP Evaluation Server as HTTP service..."
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
	   --stdio "python3 -m mcp_eval_server.server" \
	   --port $(HTTP_PORT) \
	   --host $(HTTP_HOST) \
	   --expose-sse

# REST API Server (Direct FastAPI)
serve-rest: ## Run native REST API server with FastAPI
	@echo "🚀 Starting MCP Evaluation Server as REST API service..."
	@echo "📡 Protocol: HTTP REST API"
	@echo "🔓 Authentication: None (open access)"
	@echo "🌍 URL: http://$(HTTP_HOST):$(REST_PORT)"
	@echo "📚 Interactive API docs: http://$(HTTP_HOST):$(REST_PORT)/docs"
	@echo "📝 OpenAPI schema: http://$(HTTP_HOST):$(REST_PORT)/openapi.json"
	@echo ""
	@echo "🔌 REST API Endpoints:"
	@echo "   GET  /                                    # Server info and health"
	@echo "   GET  /health                              # Health check"
	@echo "   GET  /tools                               # List all tools by category"
	@echo "   GET  /tools/categories                    # Get tool categories"
	@echo "   GET  /tools/{category}                    # List tools in category"
	@echo ""
	@echo "   📊 Judge Tools:"
	@echo "   POST /judge/evaluate                      # Evaluate single response"
	@echo "   POST /judge/compare                       # Pairwise comparison"
	@echo "   POST /judge/rank                          # Rank multiple responses"
	@echo "   POST /judge/reference                     # Evaluate vs reference"
	@echo ""
	@echo "   🎯 Quality & Analysis Tools:"
	@echo "   POST /quality/factuality                  # Check factual accuracy"
	@echo "   POST /quality/coherence                   # Analyze coherence"
	@echo "   POST /quality/toxicity                    # Detect toxicity"
	@echo "   POST /prompt/clarity                      # Evaluate prompt clarity"
	@echo "   POST /prompt/consistency                  # Test prompt consistency"
	@echo ""
	@echo "   🤖 Agent & RAG Tools:"
	@echo "   POST /agent/tool-use                      # Evaluate tool usage"
	@echo "   POST /agent/task-completion               # Measure task success"
	@echo "   POST /rag/retrieval-relevance             # Assess retrieval quality"
	@echo "   POST /rag/answer-groundedness             # Verify answer grounding"
	@echo ""
	@echo "   🛡️  Safety & Privacy Tools:"
	@echo "   POST /safety/harmful-content              # Detect harmful content"
	@echo "   POST /privacy/pii-detection               # Detect PII exposure"
	@echo "   POST /bias/demographic                    # Check demographic bias"
	@echo "   POST /robustness/adversarial              # Test adversarial inputs"
	@echo ""
	@echo "   ⚡ Performance & Workflow:"
	@echo "   POST /performance/latency                 # Measure response latency"
	@echo "   POST /workflow/create-suite               # Create evaluation suite"
	@echo "   POST /workflow/run-evaluation             # Execute evaluation suite"
	@echo ""
	@echo "⚡ Starting REST API server (Ctrl+C to stop)..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	$(PYTHON) -m mcp_eval_server.rest_server --port $(REST_PORT) --host $(HTTP_HOST)

serve-rest-public: ## Run REST API server accessible from any IP
	@echo "🌐 Starting MCP Evaluation Server as PUBLIC REST API service..."
	@echo "⚠️  WARNING: Server will be accessible from ANY IP address!"
	@echo "📡 Protocol: HTTP REST API"
	@echo "🔓 Authentication: None (open access)"
	@echo "🌍 URL: http://0.0.0.0:$(REST_PORT) (accessible from any IP)"
	@echo "📚 Interactive API docs: http://0.0.0.0:$(REST_PORT)/docs"
	@echo ""
	@echo "⚡ Starting PUBLIC REST API server (Ctrl+C to stop)..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	$(PYTHON) -m mcp_eval_server.rest_server --port $(REST_PORT) --host 0.0.0.0

# Hybrid Server (runs both MCP and REST)
serve-hybrid: ## Show guide for running both MCP and REST simultaneously
	@echo "🎯 MCP Evaluation Server - Dual Protocol Guide"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "💡 To run both MCP and REST simultaneously, use two terminals:"
	@echo ""
	@echo "🖥️  Terminal 1 - MCP Server (stdio):"
	@echo "   make dev"
	@echo "   # or: python -m mcp_eval_server.server"
	@echo ""
	@echo "🖥️  Terminal 2 - REST API Server:"
	@echo "   make serve-rest"
	@echo "   # or: python -m mcp_eval_server.rest_server"
	@echo ""
	@echo "📡 Access Methods:"
	@echo "   🔌 MCP Protocol: Configure in Claude Desktop or MCP clients"
	@echo "   🌐 REST API: http://localhost:$(REST_PORT)"
	@echo "   📚 API Docs: http://localhost:$(REST_PORT)/docs"
	@echo ""
	@echo "🧪 Testing:"
	@echo "   make test-mcp               # Test MCP protocol"
	@echo "   make test-rest              # Test REST API"
	@echo "   make test-all-apis          # Test both protocols"
	@echo ""
	@echo "💡 Both servers share the same evaluation tools and judges!"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

serve-dual: ## Start both MCP and REST servers (requires two terminals)
	@echo "🚀 Starting MCP Evaluation Server in Dual Mode..."
	@echo "📡 This will start the REST API server"
	@echo "💡 To start MCP server simultaneously, run in another terminal:"
	@echo "   make dev"
	@echo ""
	@echo "⚡ Starting REST API server (Ctrl+C to stop)..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	$(PYTHON) -m mcp_eval_server.rest_server --port $(REST_PORT) --host $(HTTP_HOST)

serve-http-public: ## Run HTTP server accessible from any IP
	@echo "🌐 Starting MCP Evaluation Server as PUBLIC HTTP service..."
	@echo "⚠️  WARNING: Server will be accessible from ANY IP address!"
	@echo "📡 Protocol: HTTP with Server-Sent Events (SSE)"
	@echo "🔓 Authentication: None (open access)"
	@echo "🌍 URL: http://0.0.0.0:$(HTTP_PORT) (accessible from any IP)"
	@echo ""
	@echo "⚡ Starting PUBLIC HTTP server (Ctrl+C to stop)..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	python3 -m mcpgateway.translate \
	   --stdio "python3 -m mcp_eval_server.server" \
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
	@echo "3️⃣  Testing evaluation via JSON-RPC..."
	@curl -s -X POST \
	      -H "Content-Type: application/json" \
	      -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "judge.evaluate_response", "arguments": {"response": "Test response", "criteria": [{"name": "quality", "description": "Overall quality", "scale": "1-5", "weight": 1.0}], "rubric": {"criteria": [], "scale_description": {"1": "Poor", "5": "Good"}}, "judge_model": "rule-based"}}}' \
	      "http://$(HTTP_HOST):$(HTTP_PORT)/" || echo "❌ Evaluation failed"
	@echo ""
	@echo "✅ HTTP testing complete!"

test-rest: ## Test REST API endpoints
	@echo "🧪 Testing REST API endpoints..."
	@echo "📍 Server URL: http://$(HTTP_HOST):$(REST_PORT)"
	@echo ""
	@echo "1️⃣  Testing server info and health..."
	@curl -s "http://$(HTTP_HOST):$(REST_PORT)/" | jq . || echo "❌ Server info failed"
	@echo ""
	@curl -s "http://$(HTTP_HOST):$(REST_PORT)/health" | jq . || echo "❌ Health check failed"
	@echo ""
	@echo "2️⃣  Testing tools discovery..."
	@curl -s "http://$(HTTP_HOST):$(REST_PORT)/tools/categories" | jq . || echo "❌ Categories failed"
	@echo ""
	@curl -s "http://$(HTTP_HOST):$(REST_PORT)/tools" | jq '.judge | keys' || echo "❌ Tools list failed"
	@echo ""
	@echo "3️⃣  Testing judge evaluation..."
	@curl -s -X POST \
	      -H "Content-Type: application/json" \
	      -d '{"response": "Paris is the capital of France", "criteria": [{"name": "accuracy", "description": "Factual accuracy", "scale": "1-5", "weight": 1.0}], "rubric": {"criteria": [], "scale_description": {"1": "Wrong", "5": "Correct"}}, "judge_model": "rule-based"}' \
	      "http://$(HTTP_HOST):$(REST_PORT)/judge/evaluate" | jq .overall_score || echo "❌ Judge evaluation failed"
	@echo ""
	@echo "4️⃣  Testing quality assessment..."
	@curl -s -X POST \
	      -H "Content-Type: application/json" \
	      -d '{"content": "This is a test message", "toxicity_categories": ["profanity", "hate_speech"], "sensitivity_level": "moderate", "judge_model": "rule-based"}' \
	      "http://$(HTTP_HOST):$(REST_PORT)/quality/toxicity" | jq .toxicity_detected || echo "❌ Quality assessment failed"
	@echo ""
	@echo "5️⃣  Testing prompt evaluation..."
	@curl -s -X POST \
	      -H "Content-Type: application/json" \
	      -d '{"prompt_text": "Write a summary of the following text", "target_model": "general", "judge_model": "rule-based"}' \
	      "http://$(HTTP_HOST):$(REST_PORT)/prompt/clarity" | jq .overall_clarity_score || echo "❌ Prompt evaluation failed"
	@echo ""
	@echo "✅ REST API testing complete!"

test-all-apis: ## Test both HTTP and REST API endpoints
	@echo "🧪 Testing all API endpoints..."
	@echo ""
	@echo "━━━━━━ HTTP/MCP API Testing ━━━━━━"
	@$(MAKE) test-http || true
	@echo ""
	@echo "━━━━━━ REST API Testing ━━━━━━"
	@$(MAKE) test-rest || true
	@echo ""
	@echo "✅ All API testing complete!"

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

http-info: ## Show HTTP server connection information
	@echo "📡 MCP Evaluation Server - HTTP Mode Connection Guide"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "🌐 HTTP Server Configuration:"
	@echo "   Host: $(HTTP_HOST)"
	@echo "   Port: $(HTTP_PORT)"
	@echo "   URL:  http://$(HTTP_HOST):$(HTTP_PORT)"
	@echo ""
	@echo "🔓 Authentication: None (open access for now)"
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
	@echo "   # Evaluate response"
	@echo "   curl -X POST -H 'Content-Type: application/json' \\"
	@echo "        -d '{\"jsonrpc\": \"2.0\", \"id\": 2, \"method\": \"tools/call\",' \\"
	@echo "        -d '     \"params\": {\"name\": \"judge.evaluate_response\",' \\"
	@echo "        -d '                 \"arguments\": {\"response\": \"Test\", \"criteria\": [...]}}}' \\"
	@echo "        http://$(HTTP_HOST):$(HTTP_PORT)/"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

rest-info: ## Show REST API connection information
	@echo "📡 MCP Evaluation Server - REST API Connection Guide"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "🚀 REST API Server Configuration:"
	@echo "   Host: $(HTTP_HOST)"
	@echo "   Port: $(REST_PORT)"
	@echo "   URL:  http://$(HTTP_HOST):$(REST_PORT)"
	@echo "   Docs: http://$(HTTP_HOST):$(REST_PORT)/docs"
	@echo ""
	@echo "🔓 Authentication: None (open access)"
	@echo ""
	@echo "📡 Core Endpoints:"
	@echo "   GET  /                                 # Server info and health"
	@echo "   GET  /health                          # Health check"
	@echo "   GET  /tools                           # List all tools by category"
	@echo "   GET  /tools/categories                # Get tool categories"
	@echo "   GET  /tools/{category}                # List tools in specific category"
	@echo ""
	@echo "📊 Judge & Evaluation Endpoints:"
	@echo "   POST /judge/evaluate                  # Single response evaluation"
	@echo "   POST /judge/compare                   # Pairwise comparison"
	@echo "   POST /judge/rank                      # Rank multiple responses"
	@echo "   POST /judge/reference                 # Evaluate vs reference"
	@echo ""
	@echo "🎯 Quality & Analysis Endpoints:"
	@echo "   POST /quality/factuality              # Check factual accuracy"
	@echo "   POST /quality/coherence               # Analyze logical coherence"
	@echo "   POST /quality/toxicity                # Detect harmful content"
	@echo "   POST /prompt/clarity                  # Evaluate prompt clarity"
	@echo "   POST /prompt/consistency              # Test prompt consistency"
	@echo "   POST /prompt/completeness             # Measure completeness"
	@echo "   POST /prompt/relevance                # Assess relevance"
	@echo ""
	@echo "🤖 Agent & RAG Endpoints:"
	@echo "   POST /agent/tool-use                  # Evaluate tool usage"
	@echo "   POST /agent/task-completion           # Measure task success"
	@echo "   POST /agent/reasoning                 # Analyze reasoning quality"
	@echo "   POST /agent/benchmark                 # Run agent benchmarks"
	@echo "   POST /rag/retrieval-relevance         # Assess retrieval quality"
	@echo "   POST /rag/context-utilization         # Check context usage"
	@echo "   POST /rag/answer-groundedness         # Verify answer grounding"
	@echo "   POST /rag/hallucination-detection     # Detect hallucinations"
	@echo ""
	@echo "🛡️  Safety & Privacy Endpoints:"
	@echo "   POST /safety/harmful-content          # Detect harmful content"
	@echo "   POST /safety/instruction-following    # Check instruction adherence"
	@echo "   POST /safety/refusal-appropriateness  # Evaluate refusal behavior"
	@echo "   POST /safety/value-alignment          # Assess value alignment"
	@echo "   POST /privacy/pii-detection           # Detect PII exposure"
	@echo "   POST /privacy/data-minimization       # Assess data minimization"
	@echo "   POST /privacy/consent-compliance      # Check consent compliance"
	@echo "   POST /bias/demographic                # Check demographic bias"
	@echo "   POST /bias/representation-fairness    # Measure representation fairness"
	@echo "   POST /bias/cultural-sensitivity       # Assess cultural sensitivity"
	@echo "   POST /robustness/adversarial          # Test adversarial inputs"
	@echo "   POST /robustness/input-sensitivity    # Measure input sensitivity"
	@echo "   POST /robustness/prompt-injection     # Test injection resistance"
	@echo ""
	@echo "🌍 Multilingual & Performance Endpoints:"
	@echo "   POST /multilingual/translation-quality       # Assess translation quality"
	@echo "   POST /multilingual/cross-lingual-consistency # Check consistency across languages"
	@echo "   POST /multilingual/cultural-adaptation       # Evaluate cultural adaptation"
	@echo "   POST /multilingual/language-mixing           # Detect language mixing"
	@echo "   POST /performance/latency                     # Measure response latency"
	@echo "   POST /performance/computational-efficiency    # Assess efficiency"
	@echo "   POST /performance/throughput-scaling         # Test throughput scaling"
	@echo "   POST /performance/memory-usage               # Monitor memory usage"
	@echo ""
	@echo "⚡ Workflow & Calibration Endpoints:"
	@echo "   POST /workflow/create-suite           # Create evaluation suite"
	@echo "   POST /workflow/run-evaluation         # Execute evaluation suite"
	@echo "   POST /workflow/compare-evaluations    # Compare evaluation results"
	@echo "   POST /calibration/judge-agreement     # Test judge agreement"
	@echo "   POST /calibration/optimize-rubrics    # Optimize evaluation rubrics"
	@echo ""
	@echo "🧪 Testing Commands:"
	@echo "   make serve-rest                       # Start local REST API server"
	@echo "   make serve-rest-public                # Start server accessible from any IP"
	@echo "   make test-rest                        # Test REST API endpoints"
	@echo "   make test-all-apis                    # Test both HTTP and REST APIs"
	@echo ""
	@echo "🔧 Custom Configuration:"
	@echo "   make serve-rest REST_PORT=3000        # Custom port"
	@echo "   make serve-rest HTTP_HOST=0.0.0.0     # Public access"
	@echo ""
	@echo "💡 Example REST API Calls:"
	@echo ""
	@echo "   # Evaluate response quality"
	@echo "   curl -X POST -H 'Content-Type: application/json' \\"
	@echo "        -d '{\"response\": \"Paris is the capital of France\",' \\"
	@echo "        -d '     \"criteria\": [{\"name\": \"accuracy\", \"description\": \"Factual accuracy\", \"scale\": \"1-5\", \"weight\": 1.0}],' \\"
	@echo "        -d '     \"rubric\": {\"criteria\": [], \"scale_description\": {\"1\": \"Wrong\", \"5\": \"Correct\"}},' \\"
	@echo "        -d '     \"judge_model\": \"rule-based\"}' \\"
	@echo "        http://$(HTTP_HOST):$(REST_PORT)/judge/evaluate"
	@echo ""
	@echo "   # Check content toxicity"
	@echo "   curl -X POST -H 'Content-Type: application/json' \\"
	@echo "        -d '{\"content\": \"This is a test message\",' \\"
	@echo "        -d '     \"toxicity_categories\": [\"profanity\", \"hate_speech\"],' \\"
	@echo "        -d '     \"sensitivity_level\": \"moderate\"}' \\"
	@echo "        http://$(HTTP_HOST):$(REST_PORT)/quality/toxicity"
	@echo ""
	@echo "   # Evaluate prompt clarity"
	@echo "   curl -X POST -H 'Content-Type: application/json' \\"
	@echo "        -d '{\"prompt_text\": \"Write a summary of the following text\",' \\"
	@echo "        -d '     \"target_model\": \"general\"}' \\"
	@echo "        http://$(HTTP_HOST):$(REST_PORT)/prompt/clarity"
	@echo ""
	@echo "📚 Interactive Documentation:"
	@echo "   Visit http://$(HTTP_HOST):$(REST_PORT)/docs for Swagger UI"
	@echo "   OpenAPI schema: http://$(HTTP_HOST):$(REST_PORT)/openapi.json"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
