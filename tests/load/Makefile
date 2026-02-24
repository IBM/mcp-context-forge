# Makefile for Load Testing Framework
# Simplifies common load testing operations

.PHONY: help install test-dry test-small test-medium test-large test-production
.PHONY: generate-small generate-medium generate-large generate-production generate-massive
.PHONY: cleanup cleanup-all verify install-deps

# Default target
help:
	@echo "ContextForge Load Testing Framework"
	@echo "==================================="
	@echo ""
	@echo "Installation:"
	@echo "  make install-deps          Install required dependencies"
	@echo ""
	@echo "Dry Run (no data generated):"
	@echo "  make test-dry-small        Dry run with small profile (100 users)"
	@echo "  make test-dry-medium       Dry run with medium profile (10K users)"
	@echo "  make test-dry-production   Dry run with production profile (160K users)"
	@echo ""
	@echo "Generate Data:"
	@echo "  make generate-small        Generate small dataset (100 users, ~8K records, <1 min)"
	@echo "  make generate-medium       Generate medium dataset (10K users, ~1M records, <10 min)"
	@echo "  make generate-large        Generate large dataset (50K users, ~5M records, <20 min)"
	@echo "  make generate-production   Generate production dataset (160K users, ~156M records, <30 min)"
	@echo "  make generate-massive      Generate massive dataset (1M users, ~1B records, <2 hours)"
	@echo ""
	@echo "Verification:"
	@echo "  make verify                Verify data integrity"
	@echo "  make verify-verbose        Verify with verbose output"
	@echo ""
	@echo "Cleanup:"
	@echo "  make cleanup               Clean up test data (requires confirmation)"
	@echo "  make cleanup-force         Clean up without confirmation (DANGEROUS)"
	@echo "  make cleanup-dry           Show what would be cleaned up"
	@echo ""
	@echo "Testing:"
	@echo "  make test                  Full test cycle (generate small, verify, cleanup)"
	@echo "  make test-small            Test small profile end-to-end"
	@echo "  make test-medium           Test medium profile end-to-end"
	@echo ""
	@echo "Reports:"
	@echo "  make show-report           Display latest generation report"
	@echo "  make clean-reports         Remove all reports"

# Install dependencies
install-deps:
	@echo "Installing load testing dependencies..."
	pip install -r requirements.txt

# Python command (must run from project root)
PYTHON=cd ../.. && python

# Dry runs (no actual data generation)
test-dry-small:
	@echo "Dry run: Small profile (100 users)"
	$(PYTHON) -m tests.load.generate --profile small --dry-run

test-dry-medium:
	@echo "Dry run: Medium profile (10K users)"
	$(PYTHON) -m tests.load.generate --profile medium --dry-run

test-dry-production:
	@echo "Dry run: Production profile (160K users)"
	$(PYTHON) -m tests.load.generate --profile production --dry-run

# Generate data
generate-small:
	@echo "Generating small dataset (100 users, ~8K records)..."
	$(PYTHON) -m tests.load.generate --profile small

generate-medium:
	@echo "Generating medium dataset (10K users, ~1M records)..."
	$(PYTHON) -m tests.load.generate --profile medium

generate-large:
	@echo "Generating large dataset (50K users, ~5M records)..."
	$(PYTHON) -m tests.load.generate --profile large

generate-production:
	@echo "Generating production dataset (160K users, ~156M records)..."
	$(PYTHON) -m tests.load.generate --profile production

generate-massive:
	@echo "Generating massive dataset (1M users, ~1B records)..."
	@echo "WARNING: This will take ~2 hours and require significant disk space!"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(PYTHON) -m tests.load.generate --profile massive; \
	fi

# Verification
verify:
	@echo "Verifying data integrity..."
	$(PYTHON) -m tests.load.verify

verify-verbose:
	@echo "Verifying data integrity (verbose)..."
	$(PYTHON) -m tests.load.verify --verbose

# Cleanup
cleanup-dry:
	@echo "Showing what would be cleaned up..."
	$(PYTHON) -m tests.load.cleanup --all --dry-run

cleanup:
	@echo "Cleaning up test data..."
	$(PYTHON) -m tests.load.cleanup --all --confirm

cleanup-force:
	@echo "Cleaning up test data (no confirmation)..."
	@echo "This will delete all test data!"
	$(PYTHON) -m tests.load.cleanup --all --confirm

# Testing workflows
test: test-small

test-small:
	@echo "=== Testing Small Profile ==="
	@echo "1. Generating data..."
	$(PYTHON) -m tests.load.generate --profile small
	@echo ""
	@echo "2. Verifying integrity..."
	$(PYTHON) -m tests.load.verify --profile small
	@echo ""
	@echo "3. Cleaning up..."
	$(PYTHON) -m tests.load.cleanup --all --confirm
	@echo ""
	@echo "✓ Test complete!"

test-medium:
	@echo "=== Testing Medium Profile ==="
	@echo "WARNING: This will generate 10K users and ~1M records"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(PYTHON) -m tests.load.generate --profile medium && \
		$(PYTHON) -m tests.load.verify --profile medium && \
		$(PYTHON) -m tests.load.cleanup --all --confirm && \
		echo "✓ Test complete!"; \
	fi

# Reports
show-report:
	@echo "Latest generation report:"
	@if [ -f reports/small_load_report.json ]; then \
		cat reports/small_load_report.json | python -m json.tool; \
	elif [ -f reports/medium_load_report.json ]; then \
		cat reports/medium_load_report.json | python -m json.tool; \
	elif [ -f reports/production_load_report.json ]; then \
		cat reports/production_load_report.json | python -m json.tool; \
	else \
		echo "No reports found. Generate data first."; \
	fi

clean-reports:
	@echo "Removing all reports..."
	rm -f reports/*.json
	@echo "Reports cleaned"

# Statistics
stats:
	@echo "Database statistics:"
	@sqlite3 ../../mcp.db "SELECT 'Users: ' || COUNT(*) FROM email_users WHERE email LIKE '%loadtest.example.com';"
	@sqlite3 ../../mcp.db "SELECT 'Teams: ' || COUNT(*) FROM email_teams WHERE owner_email LIKE '%loadtest.example.com';"
	@sqlite3 ../../mcp.db "SELECT 'Tools: ' || COUNT(*) FROM tools WHERE created_by LIKE '%loadtest.example.com';"
	@sqlite3 ../../mcp.db "SELECT 'Resources: ' || COUNT(*) FROM resources WHERE created_by LIKE '%loadtest.example.com';"
	@sqlite3 ../../mcp.db "SELECT 'Prompts: ' || COUNT(*) FROM prompts WHERE created_by LIKE '%loadtest.example.com';"

# Database backup/restore (before large tests)
backup-db:
	@echo "Backing up database..."
	@if [ -f ../../mcp.db ]; then \
		cp ../../mcp.db ../../mcp.db.backup.$$(date +%Y%m%d_%H%M%S); \
		echo "Database backed up"; \
	else \
		echo "No database found"; \
	fi

restore-db:
	@echo "Restoring database from latest backup..."
	@LATEST=$$(ls -t ../../mcp.db.backup.* 2>/dev/null | head -1); \
	if [ -n "$$LATEST" ]; then \
		cp "$$LATEST" ../../mcp.db; \
		echo "Database restored from $$LATEST"; \
	else \
		echo "No backup found"; \
	fi

# Quick commands
quick-test: test-dry-small
full-test: test-small
