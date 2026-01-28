# HTTPX Client Benchmark Makefile
# ================================
#
# Usage:
#   make benchmark                    # Run single benchmark
#   make sweep                        # Run concurrency sweep
#   make help                         # Show all targets
#
# Configuration via environment:
#   URL=http://localhost:8101/health  # Target URL
#   DURATION=30                       # Seconds per pattern
#   CONCURRENCY=100                   # Number of workers
#   MAX_CONNECTIONS=100               # Connection pool size

# Default configuration
URL ?= http://localhost:8101/health
DURATION ?= 30
CONCURRENCY ?= 100
MAX_CONNECTIONS ?= 100
MAX_KEEPALIVE ?= 50
PATTERN ?= shared_with_limits
OUTPUT_DIR ?= results

# Python command (use uv if available)
PYTHON := $(shell command -v uv > /dev/null && echo "uv run python" || echo "python")

# Timestamp for result files
TIMESTAMP := $(shell date +%Y%m%d_%H%M%S)

.PHONY: help benchmark benchmark-all benchmark-json sweep sweep-quick \
        sweep-full clean setup check-server

# ============================================================================
# Help
# ============================================================================

help:
	@echo "HTTPX Client Benchmark Suite"
	@echo "============================"
	@echo ""
	@echo "Quick Start:"
	@echo "  make benchmark              Run single benchmark with defaults"
	@echo "  make sweep                  Run concurrency sweep (10 levels)"
	@echo "  make sweep-quick            Quick sweep (3 levels)"
	@echo ""
	@echo "Benchmark Patterns:"
	@echo "  make benchmark-per-request  Per-request client (anti-pattern)"
	@echo "  make benchmark-shared       Shared client with limits"
	@echo "  make benchmark-http2        HTTP/2 with shared client"
	@echo "  make benchmark-all          Run all patterns"
	@echo ""
	@echo "Output Options:"
	@echo "  make benchmark-json         Output as JSON"
	@echo "  make sweep-csv              Sweep with CSV output"
	@echo ""
	@echo "Configuration (via environment):"
	@echo "  URL=$(URL)"
	@echo "  DURATION=$(DURATION) seconds"
	@echo "  CONCURRENCY=$(CONCURRENCY) workers"
	@echo "  MAX_CONNECTIONS=$(MAX_CONNECTIONS) pool size"
	@echo ""
	@echo "Examples:"
	@echo "  make benchmark URL=http://localhost:4444/health DURATION=60"
	@echo "  make sweep CONCURRENCY=500 MAX_CONNECTIONS=200"
	@echo "  make benchmark-all DURATION=120"

# ============================================================================
# Setup
# ============================================================================

setup:
	@echo "Checking dependencies..."
	@$(PYTHON) -c "import httpx" || (echo "Installing httpx..." && pip install httpx)
	@echo "Dependencies OK"

check-server:
	@echo "Checking server at $(URL)..."
	@curl -sf $(URL) > /dev/null || (echo "ERROR: Cannot connect to $(URL)" && exit 1)
	@echo "Server OK"

$(OUTPUT_DIR):
	mkdir -p $(OUTPUT_DIR)

# ============================================================================
# Single Benchmarks
# ============================================================================

benchmark: check-server
	@echo "Running benchmark: $(PATTERN)"
	@echo "URL: $(URL)"
	@echo "Duration: $(DURATION)s, Concurrency: $(CONCURRENCY), Pool: $(MAX_CONNECTIONS)"
	@echo ""
	$(PYTHON) benchmark_httpx.py \
		--url "$(URL)" \
		--duration $(DURATION) \
		--concurrency $(CONCURRENCY) \
		--max-connections $(MAX_CONNECTIONS) \
		--max-keepalive $(MAX_KEEPALIVE) \
		--pattern $(PATTERN)

benchmark-per-request: PATTERN=per_request
benchmark-per-request: CONCURRENCY=50
benchmark-per-request: benchmark

benchmark-shared: PATTERN=shared_with_limits
benchmark-shared: benchmark

benchmark-http2: PATTERN=http2
benchmark-http2: benchmark

benchmark-all: check-server
	@echo "Running all benchmark patterns..."
	$(PYTHON) benchmark_httpx.py \
		--url "$(URL)" \
		--duration $(DURATION) \
		--concurrency $(CONCURRENCY) \
		--max-connections $(MAX_CONNECTIONS) \
		--pattern all

benchmark-json: check-server $(OUTPUT_DIR)
	@echo "Running benchmark with JSON output..."
	$(PYTHON) benchmark_httpx.py \
		--url "$(URL)" \
		--duration $(DURATION) \
		--concurrency $(CONCURRENCY) \
		--max-connections $(MAX_CONNECTIONS) \
		--pattern $(PATTERN) \
		--output json > $(OUTPUT_DIR)/benchmark_$(TIMESTAMP).json
	@echo "Results saved to $(OUTPUT_DIR)/benchmark_$(TIMESTAMP).json"

# ============================================================================
# Sweep Benchmarks
# ============================================================================

sweep: check-server
	@echo "Running concurrency sweep..."
	@echo "URL: $(URL)"
	@echo "Duration: $(DURATION)s per level"
	@echo ""
	$(PYTHON) benchmark_sweep.py \
		--url "$(URL)" \
		--duration $(DURATION)

sweep-quick: check-server
	@echo "Running quick concurrency sweep (3 levels)..."
	$(PYTHON) benchmark_sweep.py \
		--url "$(URL)" \
		--duration $(DURATION) \
		--quick

sweep-full: check-server
	@echo "Running full concurrency sweep (extended levels)..."
	$(PYTHON) benchmark_sweep.py \
		--url "$(URL)" \
		--duration $(DURATION) \
		--levels "10:50,50:100,100:100,200:200,500:200,500:500,1000:500,1000:1000,2000:1000,3000:1000,5000:2000"

sweep-csv: check-server $(OUTPUT_DIR)
	@echo "Running sweep with CSV output..."
	$(PYTHON) benchmark_sweep.py \
		--url "$(URL)" \
		--duration $(DURATION) \
		--output $(OUTPUT_DIR)/sweep_$(TIMESTAMP).csv
	@echo "Results saved to $(OUTPUT_DIR)/sweep_$(TIMESTAMP).csv"

sweep-json: check-server $(OUTPUT_DIR)
	@echo "Running sweep with JSON output..."
	$(PYTHON) benchmark_sweep.py \
		--url "$(URL)" \
		--duration $(DURATION) \
		--output $(OUTPUT_DIR)/sweep_$(TIMESTAMP).json
	@echo "Results saved to $(OUTPUT_DIR)/sweep_$(TIMESTAMP).json"

# ============================================================================
# Specialized Tests
# ============================================================================

# Test against MCP Gateway
benchmark-gateway: URL=http://localhost:4444/health
benchmark-gateway: benchmark

sweep-gateway: URL=http://localhost:4444/health
sweep-gateway: sweep

# High-concurrency stress test (2 minutes)
stress-test: check-server
	@echo "Running 2-minute stress test..."
	$(PYTHON) benchmark_httpx.py \
		--url "$(URL)" \
		--duration 120 \
		--concurrency 3000 \
		--max-connections 1000 \
		--pattern shared_with_limits

# Compare HTTP/1.1 vs HTTP/2
compare-http2: check-server
	@echo "Comparing HTTP/1.1 vs HTTP/2..."
	@echo ""
	@echo "=== HTTP/1.1 ==="
	$(PYTHON) benchmark_httpx.py \
		--url "$(URL)" \
		--duration $(DURATION) \
		--concurrency $(CONCURRENCY) \
		--max-connections $(MAX_CONNECTIONS) \
		--pattern shared_with_limits
	@echo ""
	@echo "=== HTTP/2 ==="
	$(PYTHON) benchmark_httpx.py \
		--url "$(URL)" \
		--duration $(DURATION) \
		--concurrency $(CONCURRENCY) \
		--max-connections $(MAX_CONNECTIONS) \
		--pattern http2

# ============================================================================
# Cleanup
# ============================================================================

clean:
	rm -rf $(OUTPUT_DIR)
	rm -rf __pycache__
	rm -f *.pyc

# ============================================================================
# CI/CD Integration
# ============================================================================

ci-benchmark: check-server $(OUTPUT_DIR)
	@echo "Running CI benchmark suite..."
	$(PYTHON) benchmark_sweep.py \
		--url "$(URL)" \
		--duration 30 \
		--quick \
		--output $(OUTPUT_DIR)/ci_benchmark_$(TIMESTAMP).json
	@echo "CI Results: $(OUTPUT_DIR)/ci_benchmark_$(TIMESTAMP).json"
