# MCP Gateway Performance Testing Makefile
# Simple entrypoint for all performance testing operations

.PHONY: help install check test quick heavy baseline compare clean list

# Default target
help:
	@echo "MCP Gateway Performance Testing"
	@echo "================================"
	@echo ""
	@echo "Quick Start:"
	@echo "  make install     - Install dependencies (hey)"
	@echo "  make test        - Run standard performance tests"
	@echo "  make quick       - Quick smoke test (100 requests)"
	@echo "  make heavy       - Heavy load test (50K requests)"
	@echo ""
	@echo "Advanced Testing:"
	@echo "  make test-optimized        - Test with optimized server profile"
	@echo "  make test-production       - Test production infrastructure"
	@echo "  make test-scaling          - Test with 4 instances"
	@echo "  make compare-postgres      - Compare PostgreSQL 15 vs 17"
	@echo ""
	@echo "Comprehensive Tests:"
	@echo "  make test-database         - Database connection pool tests"
	@echo "  make test-gateway-core     - Gateway core functionality tests"
	@echo "  make test-all-scenarios    - Run all test scenarios"
	@echo "  make test-percentile       - PostgreSQL percentile performance benchmark"
	@echo ""
	@echo "Plugin Tests:"
	@echo "  make test-plugins          - Plugin tests with summary table output"
	@echo "  make test-plugins-details  - Plugin tests with detailed output"
	@echo ""
	@echo "Baseline Management:"
	@echo "  make baseline              - Save current as baseline"
	@echo "  make save-baseline         - Save existing results as baseline"
	@echo "  make compare               - Compare with baseline"
	@echo "  make list-baselines        - List saved baselines"
	@echo "  make baseline-plugins      - Save current plugin profiles directory as baseline
	@echo "  make compare-plugins       - Compare current plugin profiles with baseline"
	@echo ""
	@echo "Utilities:"
	@echo "  make list-profiles         - List all available profiles"
	@echo "  make check                 - Check service health"
	@echo "  make clean                 - Clean test result files"
	@echo "  make clean-results         - Remove all result directories"
	@echo "  make clean-all             - Deep clean (results + baselines + reports)"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs                  - Open main documentation"
	@echo ""

# Installation
install:
	@echo "Installing performance testing dependencies..."
	@command -v hey >/dev/null 2>&1 || (echo "Installing hey..." && go install github.com/rakyll/hey@latest)
	@command -v python3 >/dev/null 2>&1 || (echo "Python 3 required but not found" && exit 1)
	@pip install pyyaml >/dev/null 2>&1 || echo "Installing pyyaml..." && pip install pyyaml
	@echo "✅ Dependencies installed"

# Health check
check:
	@./utils/check-services.sh

# Basic Tests
test:
	@echo "Running standard performance tests (medium profile)..."
	@timeout 600 ./run-advanced.sh -p medium

quick:
	@echo "Running quick smoke test..."
	@./run-advanced.sh -p smoke --skip-report

heavy:
	@echo "Running heavy load test..."
	@timeout 1200 ./run-advanced.sh -p heavy

# Server Profile Tests
test-minimal:
	@./run-advanced.sh -p medium --server-profile minimal

test-optimized:
	@./run-advanced.sh -p medium --server-profile optimized

test-memory:
	@./run-advanced.sh -p medium --server-profile memory_optimized

test-io:
	@./run-advanced.sh -p medium --server-profile io_optimized

# Infrastructure Tests
test-development:
	@./run-advanced.sh -p medium --infrastructure development

test-staging:
	@./run-advanced.sh -p heavy --infrastructure staging

test-production:
	@timeout 1200 ./run-advanced.sh -p heavy --infrastructure production

# New comprehensive tests
test-database:
	@echo "Running database connection pool tests..."
	@./scenarios/database-benchmark.sh

test-gateway-core:
	@echo "Running gateway core functionality tests..."
	@./scenarios/gateway-core-benchmark.sh

test-all-scenarios:
	@echo "Running all test scenarios..."
	@./scenarios/tools-benchmark.sh
	@./scenarios/resources-benchmark.sh
	@./scenarios/prompts-benchmark.sh
	@./scenarios/gateway-core-benchmark.sh
	@./scenarios/database-benchmark.sh

test-ha:
	@./run-advanced.sh -p heavy --infrastructure production_ha

# Scaling Tests
test-scaling:
	@echo "Testing with 4 gateway instances..."
	@./run-advanced.sh -p heavy --instances 4

test-single:
	@./run-advanced.sh -p heavy --instances 1

# Database Comparison
compare-postgres:
	@echo "Comparing PostgreSQL versions..."
	@./run-advanced.sh -p medium --postgres-version 15-alpine --save-baseline pg15_comparison.json
	@./run-advanced.sh -p medium --postgres-version 17-alpine --compare-with pg15_comparison.json

test-pg15:
	@./run-advanced.sh -p medium --postgres-version 15-alpine

test-pg16:
	@./run-advanced.sh -p medium --postgres-version 16-alpine

test-pg17:
	@./run-advanced.sh -p medium --postgres-version 17-alpine

# Plugin tests
test-plugins:
	@echo "Running plugin performance tests..."
	@LOG_LEVEL=ERROR python test_plugins_performance.py 2>/dev/null

test-plugins-details:
	@echo "Running plugin performance tests with detailed output..."
	@LOG_LEVEL=ERROR python test_plugins_performance.py --details 2>/dev/null

# Baseline Management
baseline:
	@echo "Saving current results as baseline..."
	@./run-advanced.sh -p medium --save-baseline current_baseline_$$(date +%Y%m%d).json

baseline-production:
	@./run-advanced.sh -p heavy --infrastructure production --save-baseline production_baseline.json

compare:
	@if [ ! -f baselines/production_baseline.json ]; then \
		echo "❌ No production baseline found. Run 'make baseline-production' first."; \
		exit 1; \
	fi
	@./run-advanced.sh -p heavy --infrastructure production --compare-with production_baseline.json

compare-with:
ifndef BASELINE
	@echo "Usage: make compare-with BASELINE=filename.json"
	@exit 1
endif
	@./run-advanced.sh -p medium --compare-with $(BASELINE)

list-baselines:
	@./utils/baseline_manager.py list

save-baseline:
ifndef BASELINE
	@echo "Usage: make save-baseline BASELINE=name RESULTS=results_dir [PROFILE=profile] [SERVER_PROFILE=profile]"
	@echo "Example: make save-baseline BASELINE=optimized-4instance RESULTS=/tmp/sample_results2 SERVER_PROFILE=optimized"
	@exit 1
endif
ifndef RESULTS
	@echo "Usage: make save-baseline BASELINE=name RESULTS=results_dir [PROFILE=profile] [SERVER_PROFILE=profile]"
	@echo "Example: make save-baseline BASELINE=optimized-4instance RESULTS=/tmp/sample_results2 SERVER_PROFILE=optimized"
	@exit 1
endif
	@echo "Saving baseline '$(BASELINE)' from $(RESULTS)..."
	@mkdir -p baselines
	@python3 utils/baseline_manager.py save $(RESULTS) --output baselines/$(BASELINE).json $(if $(PROFILE),--profile $(PROFILE)) $(if $(SERVER_PROFILE),--server-profile $(SERVER_PROFILE)) $(if $(INFRASTRUCTURE),--infrastructure $(INFRASTRUCTURE))
	@echo "✅ Baseline saved to baselines/$(BASELINE).json"

baseline-plugins:
	@echo "Saving current results as baseline..."
	@$(MAKE) test-plugins
	@cp -r plugins/prof plugins/prof_baseline

compare-plugins:
	@echo "Comparing current results against baseline..."
	@$(MAKE) test-plugins
	@python ./utils/analyze_profiles.py plugins/prof_baseline plugins/prof --compare-all

# Profile Management
list-profiles:
	@echo ""
	@echo "=== Load Profiles ==="
	@python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); [print(f'  {k:12} - {v.get(\"description\",\"\")}') for k,v in c.get('profiles',{}).items()]"
	@echo ""
	@echo "=== Server Profiles ==="
	@python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); [print(f'  {k:20} - {v.get(\"description\",\"\")}') for k,v in c.get('server_profiles',{}).items()]"
	@echo ""
	@echo "=== Infrastructure Profiles ==="
	@python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); [print(f'  {k:20} - {v.get(\"description\",\"\")}') for k,v in c.get('infrastructure_profiles',{}).items()]"
	@echo ""

list-server-profiles:
	@./run-advanced.sh --list-server-profiles

list-infrastructure:
	@./run-advanced.sh --list-infrastructure

# Utilities
clean:
	@echo "Cleaning test results..."
	@find results/ -name "*.txt" -o -name "*.csv" -o -name "*.log" 2>/dev/null | xargs rm -f || true
	@rm -f docker-compose.perf.yml docker-compose.backup_*.yml nginx.conf 2>/dev/null || true
	@echo "✅ Clean complete"

clean-results:
	@echo "Removing all test result directories..."
	@find results/ -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} + 2>/dev/null || true
	@rm -rf plugins/prof 2>/dev/null || true
	@echo "✅ All results cleaned"

clean-all: clean-results
	@echo "Cleaning baselines and reports..."
	@rm -rf baselines/*.json reports/*.html plugins/prof plugins/prof_baseline 2>/dev/null || true
	@echo "✅ Deep clean complete"

# PostgreSQL Percentile Performance Benchmark
test-percentile:
	@echo "🚀 Running PostgreSQL Percentile Performance Benchmark..."
	@echo ""
	@if [ -f run_percentile_benchmark.sh ]; then \
		bash run_percentile_benchmark.sh; \
	else \
		echo "Running pytest directly..."; \
		pytest  test_postgresql_percentile_performance.py -v -s; \
	fi

test-percentile-quick:
	@echo "🚀 Running Quick PostgreSQL Percentile Test..."
	@pytest test_postgresql_percentile_performance.py -v -s -k "10-100"

test-percentile-accuracy:
	@echo "🚀 Testing Percentile Calculation Accuracy..."
	@pytest test_postgresql_percentile_performance.py::TestPostgreSQLPercentilePerformance::test_percentile_accuracy -v -s


# Documentation
docs:
	@echo "Opening main documentation..."
	@echo ""
	@echo "📚 Available Documentation:"
	@echo "  README.md                    - Main overview"
	@echo "  QUICK_REFERENCE.md           - Command cheat sheet"
	@echo "  SERVER_PROFILES_GUIDE.md     - Server profile details"
	@echo "  PERFORMANCE_STRATEGY.md      - Complete strategy"
	@echo "  README_AUTOMATION.md         - Automation guide"
	@echo "  IMPLEMENTATION_STATUS.md     - Implementation status"
	@echo ""

# Generate report from existing results
report:
ifndef RESULTS_DIR
	@echo "Usage: make report RESULTS_DIR=results/medium_20241009_123456"
	@exit 1
endif
	@python3 utils/report_generator.py --results-dir $(RESULTS_DIR) --config config.yaml

# Development helpers
dev-test:
	@./run-advanced.sh -p smoke --skip-monitoring --no-restore

watch-logs:
	@docker-compose logs -f gateway

# Complete workflow examples
workflow-optimize:
	@echo "🔍 Optimization Workflow"
	@echo "1. Baseline with standard config..."
	@./run-advanced.sh -p medium --save-baseline standard_baseline.json
	@echo ""
	@echo "2. Test with optimized config..."
	@./run-advanced.sh -p medium --server-profile optimized --compare-with standard_baseline.json
	@echo ""
	@echo "✅ Review comparison report to decide if optimization is worth it"

workflow-upgrade:
	@echo "🔍 PostgreSQL Upgrade Workflow"
	@echo "1. Baseline with PG 15..."
	@./run-advanced.sh -p medium --postgres-version 15-alpine --save-baseline pg15_pre_upgrade.json
	@echo ""
	@echo "2. Test with PG 17..."
	@./run-advanced.sh -p medium --postgres-version 17-alpine --compare-with pg15_pre_upgrade.json
	@echo ""
	@echo "✅ Review comparison report to evaluate upgrade impact"

workflow-capacity:
	@echo "🔍 Capacity Planning Workflow"
	@echo "Testing with different instance counts..."
	@./run-advanced.sh -p heavy --instances 1 --save-baseline capacity_1x.json
	@./run-advanced.sh -p heavy --instances 2 --save-baseline capacity_2x.json
	@./run-advanced.sh -p heavy --instances 4 --save-baseline capacity_4x.json
	@echo ""
	@echo "✅ Review baselines to determine optimal instance count"

.DEFAULT_GOAL := help
