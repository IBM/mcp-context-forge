# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   🐍 MCP CONTEXT FORGE - Makefile
#   (An enterprise-ready Model Context Protocol Gateway)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Authors: Mihai Criveti, Manav Gupta
# Description: Build & automation helpers for the MCP Gateway project
# Usage: run `make` or `make help` to view available targets
#
# help: 🐍 MCP CONTEXT FORGE  (An enterprise-ready Model Context Protocol Gateway)
#
# ──────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

# Read values from .env.make
-include .env.make

# Project variables
PROJECT_NAME      = mcpgateway
DOCS_DIR          = docs
HANDSDOWN_PARAMS  = -o $(DOCS_DIR)/ -n $(PROJECT_NAME) --name "MCP Gateway" --cleanup

TEST_DOCS_DIR ?= $(DOCS_DIR)/docs/test

# -----------------------------------------------------------------------------
# Project-wide clean-up targets
# -----------------------------------------------------------------------------
DIRS_TO_CLEAN := __pycache__ .pytest_cache .tox .ruff_cache .pyre .mypy_cache .pytype \
	dist build site .eggs *.egg-info .cache htmlcov certs \
	$(VENV_DIR) $(VENV_DIR).sbom $(COVERAGE_DIR) \
	node_modules

FILES_TO_CLEAN := .coverage coverage.xml mcp.prof mcp.pstats \
	$(PROJECT_NAME).sbom.json \
	snakefood.dot packages.dot classes.dot \
	$(DOCS_DIR)/pstats.png \
	$(DOCS_DIR)/docs/test/sbom.md \
	$(DOCS_DIR)/docs/test/{unittest,full,index,test}.md \
	$(DOCS_DIR)/docs/images/coverage.svg $(LICENSES_MD) $(METRICS_MD) \
	*.db *.sqlite *.sqlite3 mcp.db-journal *.py,cover \
	.depsorter_cache.json .depupdate.* \
	grype-results.sarif devskim-results.sarif \
	*.tar.gz *.tar.bz2 *.tar.xz *.zip *.deb \
	*.log mcpgateway.sbom.xml

COVERAGE_DIR ?= $(DOCS_DIR)/docs/coverage
LICENSES_MD  ?= $(DOCS_DIR)/docs/test/licenses.md
METRICS_MD   ?= $(DOCS_DIR)/docs/metrics/loc.md

# -----------------------------------------------------------------------------
# Container resource configuration
# -----------------------------------------------------------------------------
CONTAINER_MEMORY = 2048m
CONTAINER_CPUS   = 2

# Virtual-environment variables
VENVS_DIR := $(HOME)/.venv
VENV_DIR  := $(VENVS_DIR)/$(PROJECT_NAME)

# -----------------------------------------------------------------------------
# OS Specific
# -----------------------------------------------------------------------------
# The -r flag for xargs is GNU-specific and will fail on macOS
XARGS_FLAGS := $(shell [ "$$(uname)" = "Darwin" ] && echo "" || echo "-r")


# =============================================================================
# 📖 DYNAMIC HELP
# =============================================================================
.PHONY: help
help:
	@grep "^# help\:" Makefile | grep -v grep | sed 's/\# help\: //' | sed 's/\# help\://'

# -----------------------------------------------------------------------------
# 🔧 SYSTEM-LEVEL DEPENDENCIES
# -----------------------------------------------------------------------------
# help: 🔧 SYSTEM-LEVEL DEPENDENCIES (DEV BUILD ONLY)
# help: os-deps              - Install Graphviz, Pandoc, Trivy, SCC used for dev docs generation and security scan
OS_DEPS_SCRIPT := ./os_deps.sh

.PHONY: os-deps
os-deps: $(OS_DEPS_SCRIPT)
	@bash $(OS_DEPS_SCRIPT)


# -----------------------------------------------------------------------------
# 🔧 HELPER SCRIPTS
# -----------------------------------------------------------------------------
# Helper to ensure a Python package is installed in venv
define ensure_pip_package
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip show $(1) >/dev/null 2>&1 || \
		python3 -m pip install -q $(1)"
endef

# =============================================================================
# 🌱 VIRTUAL ENVIRONMENT & INSTALLATION
# =============================================================================
# help: 🌱 VIRTUAL ENVIRONMENT & INSTALLATION
# help: venv                 - Create a fresh virtual environment with uv & friends
# help: activate             - Activate the virtual environment in the current shell
# help: install              - Install project into the venv
# help: install-dev          - Install project (incl. dev deps) into the venv
# help: install-db           - Install project (incl. postgres and redis) into venv
# help: update               - Update all installed deps inside the venv
.PHONY: venv
venv:
	@rm -Rf "$(VENV_DIR)"
	@test -d "$(VENVS_DIR)" || mkdir -p "$(VENVS_DIR)"
	@python3 -m venv "$(VENV_DIR)"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m pip install --upgrade pip setuptools pdm uv"
	@echo -e "✅  Virtual env created.\n💡  Enter it with:\n    . $(VENV_DIR)/bin/activate\n"

.PHONY: activate
activate:
	@echo -e "💡  Enter the venv using:\n. $(VENV_DIR)/bin/activate\n"

.PHONY: install
install: venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install ."

.PHONY: install-db
install-db: venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install .[redis,postgres]"

.PHONY: install-dev
install-dev: venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install .[dev]"

.PHONY: update
update:
	@echo "⬆️   Updating installed dependencies..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install -U .[dev]"

# help: check-env            - Verify all required env vars in .env are present
.PHONY: check-env
check-env:
	@echo "🔎  Checking .env against .env.example..."
	@missing=0; \
	for key in $$(grep -Ev '^\s*#|^\s*$$' .env.example | cut -d= -f1); do \
	  grep -q "^$$key=" .env || { echo "❌ Missing: $$key"; missing=1; }; \
	done; \
	if [ $$missing -eq 0 ]; then echo "✅  All environment variables are present."; fi


# =============================================================================
# ▶️ SERVE
# =============================================================================
# help: ▶️ SERVE
# help: serve                - Run production Gunicorn server on :4444
# help: certs                - Generate self-signed TLS cert & key in ./certs (won't overwrite)
# help: serve-ssl            - Run Gunicorn behind HTTPS on :4444 (uses ./certs)
# help: dev                  - Run fast-reload dev server (uvicorn)
# help: run                  - Execute helper script ./run.sh

.PHONY: serve serve-ssl dev run certs

## --- Primary servers ---------------------------------------------------------
serve:
	./run-gunicorn.sh

serve-ssl: certs
	SSL=true CERT_FILE=certs/cert.pem KEY_FILE=certs/key.pem ./run-gunicorn.sh

dev:
	@$(VENV_DIR)/bin/uvicorn mcpgateway.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude='public/'
run:
	./run.sh

## --- Certificate helper ------------------------------------------------------
certs:                           ## Generate ./certs/cert.pem & ./certs/key.pem (idempotent)
	@if [ -f certs/cert.pem ] && [ -f certs/key.pem ]; then \
		echo "🔏  Existing certificates found in ./certs - skipping generation."; \
	else \
		echo "🔏  Generating self-signed certificate (1 year)..."; \
		mkdir -p certs; \
		openssl req -x509 -newkey rsa:4096 -sha256 -days 365 -nodes \
			-keyout certs/key.pem -out certs/cert.pem \
			-subj "/CN=localhost" \
			-addext "subjectAltName=DNS:localhost,IP:127.0.0.1"; \
		echo "✅  TLS certificate written to ./certs"; \
	fi
	chmod 640 certs/key.pem

## --- House-keeping -----------------------------------------------------------
# help: clean                - Remove caches, build artefacts, virtualenv, docs, certs, coverage, SBOM, database files, etc.
.PHONY: clean
clean:
	@echo "🧹  Cleaning workspace..."
	@bash -eu -o pipefail -c '\
		# Remove matching directories \
		for dir in $(DIRS_TO_CLEAN); do \
			find . -type d -name "$$dir" -exec rm -rf {} +; \
		done; \
		# Remove listed files \
		rm -f $(FILES_TO_CLEAN); \
		# Delete Python bytecode \
		find . -name "*.py[cod]" -delete; \
		# Delete coverage annotated files \
		find . -name "*.py,cover" -delete; \
	'
	@echo "✅  Clean complete."


# =============================================================================
# 🧪 TESTING
# =============================================================================
# help: 🧪 TESTING
# help: smoketest            - Run smoketest.py --verbose (build container, add MCP server, test endpoints)
# help: test                 - Run unit tests with pytest
# help: coverage             - Run tests with coverage, emit md/HTML/XML + badge, generate annotated files
# help: htmlcov              - (re)build just the HTML coverage report into docs
# help: test-curl            - Smoke-test API endpoints with curl script
# help: pytest-examples      - Run README / examples through pytest-examples
# help: doctest              - Run doctest on all modules with summary report
# help: doctest-verbose      - Run doctest with detailed output (-v flag)
# help: doctest-coverage     - Generate coverage report for doctest examples
# help: doctest-check        - Check doctest coverage percentage (fail if < 100%)

.PHONY: smoketest test coverage pytest-examples test-curl htmlcov doctest doctest-verbose doctest-coverage doctest-check

## --- Automated checks --------------------------------------------------------
smoketest:
	@echo "🚀 Running smoketest..."
	@bash -c '\
		./smoketest.py --verbose || { echo "❌ Smoketest failed!"; exit 1; }; \
		echo "✅ Smoketest passed!" \
	'

test:
	@echo "🧪 Running tests..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q pytest pytest-asyncio pytest-cov && \
		python3 -m pytest --maxfail=0 --disable-warnings -v"

coverage:
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(TEST_DOCS_DIR)
	@printf "# Unit tests\n\n" > $(DOCS_DIR)/docs/test/unittest.md
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pytest -p pytest_cov --reruns=1 --reruns-delay 30 \
			--md-report --md-report-output=$(DOCS_DIR)/docs/test/unittest.md \
			--dist loadgroup -n 8 -rA --cov-append --capture=tee-sys -v \
			--durations=120 --doctest-modules app/ --cov-report=term \
			--cov=mcpgateway --ignore=test.py tests/ || true"
	@printf '\n## Coverage report\n\n' >> $(DOCS_DIR)/docs/test/unittest.md
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		coverage report --format=markdown -m --no-skip-covered \
		>> $(DOCS_DIR)/docs/test/unittest.md"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && coverage html -d $(COVERAGE_DIR) --include=app/*"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && coverage xml"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && coverage-badge -fo $(DOCS_DIR)/docs/images/coverage.svg"
	@echo "🔍  Generating annotated coverage files..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && coverage annotate -d ."
	@echo "✅  Coverage artefacts: md, HTML in $(COVERAGE_DIR), XML, badge & annotated files (.py,cover) ✔"

htmlcov:
	@echo "📊  Generating HTML coverage report..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(COVERAGE_DIR)
	# If there's no existing coverage data, fall back to the full test-run
	@if [ ! -f .coverage ]; then \
		echo "ℹ️  No .coverage file found - running full coverage first..."; \
		$(MAKE) --no-print-directory coverage; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && coverage html -i -d $(COVERAGE_DIR)"
	@echo "✅  HTML coverage report ready → $(COVERAGE_DIR)/index.html"

pytest-examples:
	@echo "🧪 Testing README examples..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@test -f test_readme.py || { echo "⚠️  test_readme.py not found - skipping"; exit 0; }
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q pytest pytest-examples && \
		pytest -v test_readme.py"

test-curl:
	./test_endpoints.sh

## --- Doctest targets ---------------------------------------------------------
doctest:
	@echo "🧪 Running doctest on all modules..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pytest --doctest-modules mcpgateway/ --tb=short"

doctest-verbose:
	@echo "🧪 Running doctest with verbose output..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pytest --doctest-modules mcpgateway/ -v --tb=short"

doctest-coverage:
	@echo "📊 Generating doctest coverage report..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(TEST_DOCS_DIR)
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pytest --doctest-modules mcpgateway/ \
		--cov=mcpgateway --cov-report=term --cov-report=html:htmlcov-doctest \
		--cov-report=xml:coverage-doctest.xml"
	@echo "✅ Doctest coverage report generated in htmlcov-doctest/"

doctest-check:
	@echo "🔍 Checking doctest coverage..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pytest --doctest-modules mcpgateway/ --tb=no -q && \
		echo '✅ All doctests passing' || (echo '❌ Doctest failures detected' && exit 1)"

# =============================================================================
# 📊 METRICS
# =============================================================================
# help: 📊 METRICS
# help: pip-licenses         - Produce dependency license inventory (markdown)
# help: scc                  - Quick LoC/complexity snapshot with scc
# help: scc-report           - Generate HTML LoC & per-file metrics with scc
.PHONY: pip-licenses scc scc-report

pip-licenses:
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install pip-licenses"
	@mkdir -p $(dir $(LICENSES_MD))
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pip-licenses --format=markdown --with-authors --with-urls > $(LICENSES_MD)"
	@cat $(LICENSES_MD)
	@echo "📜  License inventory written to $(LICENSES_MD)"

scc:
	@command -v scc >/dev/null 2>&1 || { \
		echo "❌ scc not installed."; \
		echo "💡 Install with:"; \
		echo "   • macOS: brew install scc"; \
		echo "   • Linux: Download from https://github.com/boyter/scc/releases"; \
		exit 1; \
	}
	@scc --by-file -i py,sh .

scc-report:
	@command -v scc >/dev/null 2>&1 || { \
		echo "❌ scc not installed."; \
		echo "💡 Install with:"; \
		echo "   • macOS: brew install scc"; \
		echo "   • Linux: Download from https://github.com/boyter/scc/releases"; \
		exit 1; \
	}
	@mkdir -p $(dir $(METRICS_MD))
	@printf "# Lines of Code Report\n\n" > $(METRICS_MD)
	@scc . --format=html-table >> $(METRICS_MD)
	@printf "\n\n## Per-file metrics\n\n" >> $(METRICS_MD)
	@scc -i py,sh,yaml,toml,md --by-file . --format=html-table >> $(METRICS_MD)
	@echo "📊  LoC metrics captured in $(METRICS_MD)"

# =============================================================================
# 📚 DOCUMENTATION
# =============================================================================
# help: 📚 DOCUMENTATION & SBOM
# help: docs                 - Build docs (graphviz + handsdown + images + SBOM)
# help: images               - Generate architecture & dependency diagrams

# Pick the right "in-place" flag for sed (BSD vs GNU)
ifeq ($(shell uname),Darwin)
  SED_INPLACE := -i ''
else
  SED_INPLACE := -i
endif

.PHONY: docs
docs: images sbom
	@echo "📚  Generating documentation with handsdown..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q handsdown && \
		python3 -m handsdown --external https://github.com/IBM/mcp-context-forge/ \
		         -o $(DOCS_DIR)/docs \
		         -n app --name '$(PROJECT_NAME)' --cleanup"

	@cp README.md $(DOCS_DIR)/docs/index.md
	@echo "✅  Docs ready in $(DOCS_DIR)/docs"

.PHONY: images
images:
	@echo "🖼️   Generating documentation diagrams..."
	@mkdir -p $(DOCS_DIR)/docs/design/images
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q code2flow && \
		$(VENV_DIR)/bin/code2flow mcpgateway/ --output $(DOCS_DIR)/docs/design/images/code2flow.dot || true"
	@command -v dot >/dev/null 2>&1 || { \
		echo "⚠️  Graphviz (dot) not installed - skipping diagram generation"; \
		echo "💡  Install with: brew install graphviz (macOS) or apt-get install graphviz (Linux)"; \
	} && \
	dot -Tsvg -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=14 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=14 -Efontcolor=black $(DOCS_DIR)/docs/design/images/code2flow.dot -o $(DOCS_DIR)/docs/design/images/code2flow.svg || true
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q snakefood3 && \
		python3 -m snakefood3 . mcpgateway > snakefood.dot"
	@command -v dot >/dev/null 2>&1 && \
	dot -Tpng -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=12 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=10 -Efontcolor=black snakefood.dot -o $(DOCS_DIR)/docs/design/images/snakefood.png || true
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q pylint && \
		$(VENV_DIR)/bin/pyreverse --colorized mcpgateway || true"
	@command -v dot >/dev/null 2>&1 && \
	dot -Tsvg -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=14 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=14 -Efontcolor=black packages.dot -o $(DOCS_DIR)/docs/design/images/packages.svg || true && \
	dot -Tsvg -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=14 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=14 -Efontcolor=black classes.dot -o $(DOCS_DIR)/docs/design/images/classes.svg || true
	@rm -f packages.dot classes.dot snakefood.dot || true

# =============================================================================
# 🔍 LINTING & STATIC ANALYSIS
# =============================================================================
# help: 🔍 LINTING & STATIC ANALYSIS
# help: TARGET=<path>        - Override default target (mcpgateway)
# help: Usage Examples:
# help:   make lint                    - Run all linters on default targets (mcpgateway)
# help:   make lint TARGET=myfile.py   - Run file-aware linters on specific file
# help:   make lint myfile.py          - Run file-aware linters on a file (shortcut)
# help:   make lint-quick myfile.py    - Fast linters only (ruff, black, isort)
# help:   make lint-fix myfile.py      - Auto-fix formatting issues
# help:   make lint-changed            - Lint only git-changed files
# help: lint                 - Run the full linting suite (see targets below)
# help: black                - Reformat code with black
# help: autoflake            - Remove unused imports / variables with autoflake
# help: isort                - Organise & sort imports with isort
# help: flake8               - PEP-8 style & logical errors
# help: pylint               - Pylint static analysis
# help: markdownlint         - Lint Markdown files with markdownlint (requires markdownlint-cli)
# help: mypy                 - Static type-checking with mypy
# help: bandit               - Security scan with bandit
# help: pydocstyle           - Docstring style checker
# help: pycodestyle          - Simple PEP-8 checker
# help: pre-commit           - Run all configured pre-commit hooks
# help: ruff                 - Ruff linter + formatter
# help: ty                   - Ty type checker from astral
# help: pyright              - Static type-checking with Pyright
# help: radon                - Code complexity & maintainability metrics
# help: pyroma               - Validate packaging metadata
# help: importchecker        - Detect orphaned imports
# help: spellcheck           - Spell-check the codebase
# help: fawltydeps           - Detect undeclared / unused deps
# help: wily                 - Maintainability report
# help: pyre                 - Static analysis with Facebook Pyre
# help: pyrefly              - Static analysis with Facebook Pyrefly
# help: depend               - List dependencies in ≈requirements format
# help: snakeviz             - Profile & visualise with snakeviz
# help: pstats               - Generate PNG call-graph from cProfile stats
# help: spellcheck-sort      - Sort local spellcheck dictionary
# help: tox                  - Run tox across multi-Python versions
# help: sbom                 - Produce a CycloneDX SBOM and vulnerability scan
# help: pytype               - Flow-sensitive type checker
# help: check-manifest       - Verify sdist/wheel completeness
# help: unimport             - Unused import detection
# help: vulture              - Dead code detection

# Allow specific file/directory targeting
DEFAULT_TARGETS := mcpgateway
TARGET ?= $(DEFAULT_TARGETS)

# Add dummy targets for file arguments passed to lint commands only
# This prevents make from trying to build file targets when they're used as arguments
ifneq ($(filter lint lint-quick lint-fix lint-smart,$(MAKECMDGOALS)),)
  # Get all arguments after the first goal
  LINT_FILE_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  # Create dummy targets for each file argument
  $(LINT_FILE_ARGS):
	@:
endif

# List of individual lint targets
LINTERS := isort flake8 pylint mypy bandit pydocstyle pycodestyle pre-commit \
	ruff ty pyright radon pyroma pyrefly spellcheck importchecker \
		pytype check-manifest markdownlint vulture unimport

# Linters that work well with individual files/directories
FILE_AWARE_LINTERS := isort black flake8 pylint mypy bandit pydocstyle \
	pycodestyle ruff pyright vulture unimport markdownlint

.PHONY: lint $(LINTERS) black autoflake lint-py lint-yaml lint-json lint-md lint-strict \
	lint-count-errors lint-report lint-changed lint-staged lint-commit \
	lint-pre-commit lint-pre-push lint-parallel lint-cache-clear lint-stats \
	lint-complexity lint-watch lint-watch-quick \
	lint-install-hooks lint-quick lint-fix lint-smart lint-target lint-all


## --------------------------------------------------------------------------- ##
##  Main target with smart file/directory detection
## --------------------------------------------------------------------------- ##
lint:
	@# Handle multiple file arguments
	@file_args="$(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))"; \
	if [ -n "$$file_args" ]; then \
		echo "🎯 Running linters on specified files: $$file_args"; \
		for file in $$file_args; do \
			if [ ! -e "$$file" ]; then \
				echo "❌ File/directory not found: $$file"; \
				exit 1; \
			fi; \
			echo "🔍 Linting: $$file"; \
			$(MAKE) --no-print-directory lint-smart "$$file"; \
		done; \
	else \
		echo "🔍 Running full lint suite on: $(TARGET)"; \
		$(MAKE) --no-print-directory lint-all TARGET="$(TARGET)"; \
	fi


.PHONY: lint-target
lint-target:
	@# Check if target exists
	@if [ ! -e "$(TARGET)" ]; then \
		echo "❌ File/directory not found: $(TARGET)"; \
		exit 1; \
	fi
	@# Run only file-aware linters
	@echo "🔍 Running file-aware linters on: $(TARGET)"
	@set -e; for t in $(FILE_AWARE_LINTERS); do \
		echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
		echo "- $$t on $(TARGET)"; \
		$(MAKE) --no-print-directory $$t TARGET="$(TARGET)" || true; \
	done

.PHONY: lint-all
lint-all:
	@set -e; for t in $(LINTERS); do \
		echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
		echo "- $$t"; \
		$(MAKE) --no-print-directory $$t TARGET="$(TARGET)" || true; \
	done

## --------------------------------------------------------------------------- ##
##  Convenience targets
## --------------------------------------------------------------------------- ##

# Quick lint - only fast linters (ruff, black, isort)
.PHONY: lint-quick
lint-quick:
	@# Handle file arguments
	@target_file="$(word 2,$(MAKECMDGOALS))"; \
	if [ -n "$$target_file" ] && [ "$$target_file" != "" ]; then \
		actual_target="$$target_file"; \
	else \
		actual_target="$(TARGET)"; \
	fi; \
	echo "⚡ Quick lint of $$actual_target (ruff + black + isort)..."; \
	$(MAKE) --no-print-directory ruff-check TARGET="$$actual_target"; \
	$(MAKE) --no-print-directory black-check TARGET="$$actual_target"; \
	$(MAKE) --no-print-directory isort-check TARGET="$$actual_target"

# Fix formatting issues
.PHONY: lint-fix
lint-fix:
	@# Handle file arguments
	@target_file="$(word 2,$(MAKECMDGOALS))"; \
	if [ -n "$$target_file" ] && [ "$$target_file" != "" ]; then \
		actual_target="$$target_file"; \
	else \
		actual_target="$(TARGET)"; \
	fi; \
	for target in $$(echo $$actual_target); do \
		if [ ! -e "$$target" ]; then \
			echo "❌ File/directory not found: $$target"; \
			exit 1; \
		fi; \
	done; \
	echo "🔧 Fixing lint issues in $$actual_target..."; \
	$(MAKE) --no-print-directory black TARGET="$$actual_target"; \
	$(MAKE) --no-print-directory isort TARGET="$$actual_target"; \
	$(MAKE) --no-print-directory ruff-fix TARGET="$$actual_target"

# Smart linting based on file extension
.PHONY: lint-smart
lint-smart:
	@# Handle arguments passed to this target - FIXED VERSION
	@target_file="$(word 2,$(MAKECMDGOALS))"; \
	if [ -n "$$target_file" ] && [ "$$target_file" != "" ]; then \
		actual_target="$$target_file"; \
	else \
		actual_target="mcpgateway"; \
	fi; \
	if [ ! -e "$$actual_target" ]; then \
		echo "❌ File/directory not found: $$actual_target"; \
		exit 1; \
	fi; \
	case "$$actual_target" in \
		*.py) \
			echo "🐍 Python file detected: $$actual_target"; \
			$(MAKE) --no-print-directory lint-target TARGET="$$actual_target" ;; \
		*.yaml|*.yml) \
			echo "📄 YAML file detected: $$actual_target"; \
			$(MAKE) --no-print-directory yamllint TARGET="$$actual_target" ;; \
		*.json) \
			echo "📄 JSON file detected: $$actual_target"; \
			$(MAKE) --no-print-directory jsonlint TARGET="$$actual_target" ;; \
		*.md) \
			echo "📝 Markdown file detected: $$actual_target"; \
			$(MAKE) --no-print-directory markdownlint TARGET="$$actual_target" ;; \
		*.toml) \
			echo "📄 TOML file detected: $$actual_target"; \
			$(MAKE) --no-print-directory tomllint TARGET="$$actual_target" ;; \
		*.sh) \
			echo "🐚 Shell script detected: $$actual_target"; \
			$(MAKE) --no-print-directory shell-lint TARGET="$$actual_target" ;; \
		Makefile|*.mk) \
			echo "🔨 Makefile detected: $$actual_target"; \
			echo "ℹ️  Makefile linting not supported, skipping Python linters"; \
			echo "💡 Consider using shellcheck for shell portions if needed" ;; \
		*) \
			if [ -d "$$actual_target" ]; then \
				echo "📁 Directory detected: $$actual_target"; \
				$(MAKE) --no-print-directory lint-target TARGET="$$actual_target"; \
			else \
				echo "❓ Unknown file type, running Python linters"; \
				$(MAKE) --no-print-directory lint-target TARGET="$$actual_target"; \
			fi ;; \
	esac

	fi

## --------------------------------------------------------------------------- ##
##  Individual targets (alphabetical, updated to use TARGET)
## --------------------------------------------------------------------------- ##
autoflake:                          ## 🧹  Strip unused imports / vars
	@echo "🧹 autoflake $(TARGET)..."
	@$(VENV_DIR)/bin/autoflake --in-place --remove-all-unused-imports \
		--remove-unused-variables -r $(TARGET)

black:                              ## 🎨  Reformat code with black
	@echo "🎨  black $(TARGET)..." && $(VENV_DIR)/bin/black -l 200 $(TARGET)

# Black check mode (separate target)
black-check:
	@echo "🎨  black --check $(TARGET)..." && $(VENV_DIR)/bin/black -l 200 --check --diff $(TARGET)

isort:                              ## 🔀  Sort imports
	@echo "🔀  isort $(TARGET)..." && $(VENV_DIR)/bin/isort $(TARGET)

# Isort check mode (separate target)
isort-check:
	@echo "🔀  isort --check $(TARGET)..." && $(VENV_DIR)/bin/isort --check-only --diff $(TARGET)

flake8:                             ## 🐍  flake8 checks
	@echo "🐍 flake8 $(TARGET)..." && $(VENV_DIR)/bin/flake8 $(TARGET)

pylint:                             ## 🐛  pylint checks
	@echo "🐛 pylint $(TARGET)..." && $(VENV_DIR)/bin/pylint $(TARGET)

markdownlint:					    ## 📖  Markdown linting
	@# Install markdownlint-cli2 if not present
	@if ! command -v markdownlint-cli2 >/dev/null 2>&1; then \
		echo "📦 Installing markdownlint-cli2..."; \
		if command -v npm >/dev/null 2>&1; then \
			npm install -g markdownlint-cli2; \
		else \
			echo "❌ npm not found. Please install Node.js/npm first."; \
			echo "💡 Install with:"; \
			echo "   • macOS: brew install node"; \
			echo "   • Linux: sudo apt-get install nodejs npm"; \
			exit 1; \
		fi; \
	fi
	@if [ -f "$(TARGET)" ] && echo "$(TARGET)" | grep -qE '\.(md|markdown)$$'; then \
		echo "📖 markdownlint $(TARGET)..."; \
		markdownlint-cli2 "$(TARGET)" || true; \
	elif [ -d "$(TARGET)" ]; then \
		echo "📖 markdownlint $(TARGET)..."; \
		markdownlint-cli2 "$(TARGET)/**/*.md" || true; \
	else \
		echo "📖 markdownlint (default)..."; \
		markdownlint-cli2 "**/*.md" || true; \
	fi

mypy:                               ## 🏷️  mypy type-checking
	@echo "🏷️ mypy $(TARGET)..." && $(VENV_DIR)/bin/mypy $(TARGET)

bandit:                             ## 🛡️  bandit security scan
	@echo "🛡️ bandit $(TARGET)..."
	@if [ -d "$(TARGET)" ]; then \
		$(VENV_DIR)/bin/bandit -r $(TARGET); \
	else \
		$(VENV_DIR)/bin/bandit $(TARGET); \
	fi

pydocstyle:                         ## 📚  Docstring style
	@echo "📚 pydocstyle $(TARGET)..." && $(VENV_DIR)/bin/pydocstyle $(TARGET)

pycodestyle:                        ## 📝  Simple PEP-8 checker
	@echo "📝 pycodestyle $(TARGET)..." && $(VENV_DIR)/bin/pycodestyle $(TARGET) --max-line-length=200

pre-commit:                         ## 🪄  Run pre-commit hooks
	@echo "🪄  Running pre-commit hooks..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv install install-dev
	@if [ ! -f "$(VENV_DIR)/bin/pre-commit" ]; then \
		echo "📦  Installing pre-commit..."; \
		/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m pip install --quiet pre-commit"; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && pre-commit run --all-files --show-diff-on-failure"

ruff:                               ## ⚡  Ruff lint + format
	@echo "⚡ ruff $(TARGET)..." && $(VENV_DIR)/bin/ruff check $(TARGET) && $(VENV_DIR)/bin/ruff format $(TARGET)

# Separate ruff targets for different modes
ruff-check:
	@echo "⚡ ruff check $(TARGET)..." && $(VENV_DIR)/bin/ruff check $(TARGET)

ruff-fix:
	@echo "⚡ ruff check --fix $(TARGET)..." && $(VENV_DIR)/bin/ruff check --fix $(TARGET)

ruff-format:
	@echo "⚡ ruff format $(TARGET)..." && $(VENV_DIR)/bin/ruff format $(TARGET)

ty:                                 ## ⚡  Ty type checker
	@echo "⚡ ty $(TARGET)..." && $(VENV_DIR)/bin/ty check $(TARGET)

pyright:                            ## 🏷️  Pyright type-checking
	@echo "🏷️ pyright $(TARGET)..." && $(VENV_DIR)/bin/pyright $(TARGET)

radon:                              ## 📈  Complexity / MI metrics
	@$(VENV_DIR)/bin/radon mi -s $(TARGET) && \
	$(VENV_DIR)/bin/radon cc -s $(TARGET) && \
	$(VENV_DIR)/bin/radon hal $(TARGET) && \
	$(VENV_DIR)/bin/radon raw -s $(TARGET)

pyroma:                             ## 📦  Packaging metadata check
	@$(VENV_DIR)/bin/pyroma -d .

importchecker:                      ## 🧐  Orphaned import detector
	@$(VENV_DIR)/bin/importchecker .

spellcheck:                         ## 🔤  Spell-check
	@$(VENV_DIR)/bin/pyspelling || true

fawltydeps:                         ## 🏗️  Dependency sanity
	@$(VENV_DIR)/bin/fawltydeps --detailed --exclude 'docs/**' . || true

wily:                               ## 📈  Maintainability report
	@echo "📈  Maintainability report..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@git stash --quiet
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q wily && \
		python3 -m wily build -n 10 . > /dev/null || true && \
		python3 -m wily report . || true"
	@git stash pop --quiet

pyre:                               ## 🧠  Facebook Pyre analysis
	@$(VENV_DIR)/bin/pyre

pyrefly:                            ## 🧠  Facebook Pyrefly analysis (faster, rust)
	@echo "🧠 pyrefly $(TARGET)..." && $(VENV_DIR)/bin/pyrefly check $(TARGET)

depend:                             ## 📦  List dependencies
	@echo "📦  List dependencies"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q pdm && \
		python3 -m pdm list --freeze"

snakeviz:                           ## 🐍  Interactive profile visualiser
	@echo "🐍  Interactive profile visualiser..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q snakeviz && \
		python3 -m cProfile -o mcp.prof mcpgateway/main.py && \
		python3 -m snakeviz mcp.prof --server"

pstats:                             ## 📊  Static call-graph image
	@echo "📊  Static call-graph image"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q gprof2dot && \
		python3 -m cProfile -o mcp.pstats mcpgateway/main.py && \
		$(VENV_DIR)/bin/gprof2dot -w -e 3 -n 3 -s -f pstats mcp.pstats | \
		dot -Tpng -o $(DOCS_DIR)/pstats.png"

spellcheck-sort: .spellcheck-en.txt ## 🔤  Sort spell-list
	sort -d -f -o $< $<

tox:                                ## 🧪  Multi-Python tox matrix (uv)
	@echo "🧪  Running tox with uv ..."
	python3 -m tox -p auto $(TOXARGS)

sbom:								## 🛡️  Generate SBOM & security report
	@echo "🛡️   Generating SBOM & security report..."
	@rm -Rf "$(VENV_DIR).sbom"
	@python3 -m venv "$(VENV_DIR).sbom"
	@/bin/bash -c "source $(VENV_DIR).sbom/bin/activate && python3 -m pip install --upgrade pip setuptools pdm uv && python3 -m uv pip install .[dev]"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install cyclonedx-bom sbom2doc"
	@echo "🔍  Generating SBOM from environment..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m cyclonedx_py environment \
			--output-format XML \
			--output-file $(PROJECT_NAME).sbom.xml \
			--no-validate \
			'$(VENV_DIR).sbom/bin/python'"
	@echo "📁  Creating docs directory structure..."
	@mkdir -p $(DOCS_DIR)/docs/test
	@echo "📋  Converting SBOM to markdown..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		sbom2doc -i $(PROJECT_NAME).sbom.xml -f markdown -o $(DOCS_DIR)/docs/test/sbom.md"
	@echo "🔒  Running security scans..."
	@/bin/bash -c "if command -v trivy >/dev/null 2>&1; then \
		echo '## Trivy Vulnerability Scan' >> $(DOCS_DIR)/docs/test/sbom.md; \
		echo '' >> $(DOCS_DIR)/docs/test/sbom.md; \
		trivy sbom $(PROJECT_NAME).sbom.xml | tee -a $(DOCS_DIR)/docs/test/sbom.md; \
	else \
		echo '⚠️  trivy not found, skipping vulnerability scan'; \
		echo '## Security Scan' >> $(DOCS_DIR)/docs/test/sbom.md; \
		echo '' >> $(DOCS_DIR)/docs/test/sbom.md; \
		echo 'Trivy not available - install with: brew install trivy' >> $(DOCS_DIR)/docs/test/sbom.md; \
	fi"
	@echo "📊  Checking for outdated packages..."
	@/bin/bash -c "source $(VENV_DIR).sbom/bin/activate && \
		echo '## Outdated Packages' >> $(DOCS_DIR)/docs/test/sbom.md && \
		echo '' >> $(DOCS_DIR)/docs/test/sbom.md && \
		(python3 -m pdm outdated || echo 'PDM outdated check failed') | tee -a $(DOCS_DIR)/docs/test/sbom.md"
	@echo "✅  SBOM generation complete"
	@echo "📄  Files generated:"
	@echo "    - $(PROJECT_NAME).sbom.xml (CycloneDX XML format)"
	@echo "    - $(DOCS_DIR)/docs/test/sbom.md (Markdown report)"

pytype:								## 🧠  Pytype static type analysis
	@echo "🧠  Pytype analysis..."
	@$(VENV_DIR)/bin/pytype -V 3.12 -j auto $(TARGET)

check-manifest:						## 📦  Verify MANIFEST.in completeness
	@echo "📦  Verifying MANIFEST.in completeness..."
	@$(VENV_DIR)/bin/check-manifest

unimport:                           ## 📦  Unused import detection
	@echo "📦  unimport $(TARGET)…" && $(VENV_DIR)/bin/unimport --check --diff $(TARGET)

vulture:                            ## 🧹  Dead code detection
	@echo "🧹  vulture $(TARGET) …" && $(VENV_DIR)/bin/vulture $(TARGET) --min-confidence 80

# Shell script linting for individual files
shell-lint-file:                    ## 🐚  Lint shell script
	@if [ -f "$(TARGET)" ]; then \
		echo "🐚 Linting shell script: $(TARGET)"; \
		if command -v shellcheck >/dev/null 2>&1; then \
			shellcheck "$(TARGET)" || true; \
		else \
			echo "⚠️  shellcheck not installed - skipping"; \
		fi; \
		if command -v shfmt >/dev/null 2>&1; then \
			shfmt -d -i 4 -ci "$(TARGET)" || true; \
		elif [ -f "$(HOME)/go/bin/shfmt" ]; then \
			$(HOME)/go/bin/shfmt -d -i 4 -ci "$(TARGET)" || true; \
		else \
			echo "⚠️  shfmt not installed - skipping"; \
		fi; \
	else \
		echo "❌ $(TARGET) is not a file"; \
	fi

# -----------------------------------------------------------------------------
# 🔍 LINT CHANGED FILES (GIT INTEGRATION)
# -----------------------------------------------------------------------------
# help: lint-changed         - Lint only git-changed files
# help: lint-staged          - Lint only git-staged files
# help: lint-commit          - Lint files in specific commit (use COMMIT=hash)
.PHONY: lint-changed lint-staged lint-commit

lint-changed:							## 🔍 Lint only changed files (git)
	@echo "🔍 Linting changed files..."
	@changed_files=$$(git diff --name-only --diff-filter=ACM HEAD 2>/dev/null || true); \
	if [ -z "$$changed_files" ]; then \
		echo "ℹ️  No changed files to lint"; \
	else \
		echo "Changed files:"; \
		echo "$$changed_files" | sed 's/^/  - /'; \
		echo ""; \
		for file in $$changed_files; do \
			if [ -e "$$file" ]; then \
				echo "🎯 Linting: $$file"; \
				$(MAKE) --no-print-directory lint-smart "$$file"; \
			fi; \
		done; \
	fi

lint-staged:							## 🔍 Lint only staged files (git)
	@echo "🔍 Linting staged files..."
	@staged_files=$$(git diff --name-only --cached --diff-filter=ACM 2>/dev/null || true); \
	if [ -z "$$staged_files" ]; then \
		echo "ℹ️  No staged files to lint"; \
	else \
		echo "Staged files:"; \
		echo "$$staged_files" | sed 's/^/  - /'; \
		echo ""; \
		for file in $$staged_files; do \
			if [ -e "$$file" ]; then \
				echo "🎯 Linting: $$file"; \
				$(MAKE) --no-print-directory lint-smart "$$file"; \
			fi; \
		done; \
	fi

# Lint files in specific commit (use COMMIT=hash)
COMMIT ?= HEAD
lint-commit:							## 🔍 Lint files changed in commit
	@echo "🔍 Linting files changed in commit $(COMMIT)..."
	@commit_files=$$(git diff-tree --no-commit-id --name-only -r $(COMMIT) 2>/dev/null || true); \
	if [ -z "$$commit_files" ]; then \
		echo "ℹ️  No files found in commit $(COMMIT)"; \
	else \
		echo "Files in commit $(COMMIT):"; \
		echo "$$commit_files" | sed 's/^/  - /'; \
		echo ""; \
		for file in $$commit_files; do \
			if [ -e "$$file" ]; then \
				echo "🎯 Linting: $$file"; \
				$(MAKE) --no-print-directory lint-smart "$$file"; \
			fi; \
		done; \
	fi

# -----------------------------------------------------------------------------
# 👁️ WATCH MODE - LINT ON FILE CHANGES
# -----------------------------------------------------------------------------
# help: lint-watch           - Watch files for changes and auto-lint
# help: lint-watch-quick     - Watch files with quick linting only
.PHONY: lint-watch lint-watch-quick install-watchdog

install-watchdog:						## 📦 Install watchdog for file watching
	@echo "📦 Installing watchdog for file watching..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q watchdog"

# Watch mode - lint on file changes
lint-watch: install-watchdog			## 👁️ Watch for changes and auto-lint
	@echo "👁️ Watching $(TARGET) for changes (Ctrl+C to stop)..."
	@echo "💡 Will run 'make lint-smart' on changed Python files"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(VENV_DIR)/bin/watchmedo shell-command \
			--patterns='*.py;*.yaml;*.yml;*.json;*.md;*.toml' \
			--recursive \
			--command='echo \"📝 File changed: \$${watch_src_path}\" && make --no-print-directory lint-smart \"\$${watch_src_path}\"' \
			$(TARGET)"

# Watch mode with quick linting only
lint-watch-quick: install-watchdog		## 👁️ Watch for changes and quick-lint
	@echo "👁️ Quick-watching $(TARGET) for changes (Ctrl+C to stop)..."
	@echo "💡 Will run 'make lint-quick' on changed Python files"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(VENV_DIR)/bin/watchmedo shell-command \
			--patterns='*.py' \
			--recursive \
			--command='echo \"⚡ File changed: \$${watch_src_path}\" && make --no-print-directory lint-quick \"\$${watch_src_path}\"' \
			$(TARGET)"

# -----------------------------------------------------------------------------
# 🚨 STRICT LINTING WITH ERROR THRESHOLDS
# -----------------------------------------------------------------------------
# help: lint-strict          - Lint with error threshold (fail on errors)
# help: lint-count-errors    - Count and report linting errors
# help: lint-report          - Generate detailed linting report
.PHONY: lint-strict lint-count-errors lint-report

# Lint with error threshold
lint-strict:							## 🚨 Lint with strict error checking
	@echo "🚨 Running strict linting on $(TARGET)..."
	@mkdir -p $(DOCS_DIR)/reports
	@$(MAKE) lint TARGET="$(TARGET)" 2>&1 | tee $(DOCS_DIR)/reports/lint-report.txt
	@errors=$$(grep -ic "error\|failed\|❌" $(DOCS_DIR)/reports/lint-report.txt 2>/dev/null || echo 0); \
	warnings=$$(grep -ic "warning\|warn\|⚠️" $(DOCS_DIR)/reports/lint-report.txt 2>/dev/null || echo 0); \
	echo ""; \
	echo "📊 Linting Summary:"; \
	echo "   ❌ Errors: $$errors"; \
	echo "   ⚠️  Warnings: $$warnings"; \
	if [ $$errors -gt 0 ]; then \
		echo ""; \
		echo "❌ Linting failed with $$errors errors"; \
		echo "📄 Full report: $(DOCS_DIR)/reports/lint-report.txt"; \
		exit 1; \
	else \
		echo "✅ All linting checks passed!"; \
	fi

# Count errors from different linters
lint-count-errors:						## 📊 Count linting errors by tool
	@echo "📊 Counting linting errors by tool..."
	@mkdir -p $(DOCS_DIR)/reports
	@echo "# Linting Error Report - $$(date)" > $(DOCS_DIR)/reports/error-count.md
	@echo "" >> $(DOCS_DIR)/reports/error-count.md
	@echo "| Tool | Errors | Warnings |" >> $(DOCS_DIR)/reports/error-count.md
	@echo "|------|--------|----------|" >> $(DOCS_DIR)/reports/error-count.md
	@for tool in flake8 pylint mypy bandit ruff; do \
		echo "🔍 Checking $$tool errors..."; \
		errors=0; warnings=0; \
		if $(MAKE) --no-print-directory $$tool TARGET="$(TARGET)" 2>&1 | tee /tmp/$$tool.log >/dev/null; then \
			errors=$$(grep -c "error:" /tmp/$$tool.log 2>/dev/null || echo 0); \
			warnings=$$(grep -c "warning:" /tmp/$$tool.log 2>/dev/null || echo 0); \
		fi; \
		echo "| $$tool | $$errors | $$warnings |" >> $(DOCS_DIR)/reports/error-count.md; \
		rm -f /tmp/$$tool.log; \
	done
	@echo "" >> $(DOCS_DIR)/reports/error-count.md
	@echo "Generated: $$(date)" >> $(DOCS_DIR)/reports/error-count.md
	@cat $(DOCS_DIR)/reports/error-count.md
	@echo "📄 Report saved: $(DOCS_DIR)/reports/error-count.md"

# Generate comprehensive linting report
lint-report:							## 📋 Generate comprehensive linting report
	@echo "📋 Generating comprehensive linting report..."
	@mkdir -p $(DOCS_DIR)/reports
	@echo "# Comprehensive Linting Report" > $(DOCS_DIR)/reports/full-lint-report.md
	@echo "Generated: $$(date)" >> $(DOCS_DIR)/reports/full-lint-report.md
	@echo "" >> $(DOCS_DIR)/reports/full-lint-report.md
	@echo "## Target: $(TARGET)" >> $(DOCS_DIR)/reports/full-lint-report.md
	@echo "" >> $(DOCS_DIR)/reports/full-lint-report.md
	@echo "## Quick Summary" >> $(DOCS_DIR)/reports/full-lint-report.md
	@$(MAKE) --no-print-directory lint-quick TARGET="$(TARGET)" >> $(DOCS_DIR)/reports/full-lint-report.md 2>&1 || true
	@echo "" >> $(DOCS_DIR)/reports/full-lint-report.md
	@echo "## Detailed Analysis" >> $(DOCS_DIR)/reports/full-lint-report.md
	@$(MAKE) --no-print-directory lint TARGET="$(TARGET)" >> $(DOCS_DIR)/reports/full-lint-report.md 2>&1 || true
	@echo "" >> $(DOCS_DIR)/reports/full-lint-report.md
	@echo "## Error Count by Tool" >> $(DOCS_DIR)/reports/full-lint-report.md
	@$(MAKE) --no-print-directory lint-count-errors TARGET="$(TARGET)" >> $(DOCS_DIR)/reports/full-lint-report.md 2>&1 || true
	@echo "📄 Report generated: $(DOCS_DIR)/reports/full-lint-report.md"

# -----------------------------------------------------------------------------
# 🔧 PRE-COMMIT INTEGRATION
# -----------------------------------------------------------------------------
# help: lint-install-hooks   - Install git pre-commit hooks for linting
# help: lint-pre-commit      - Run linting as pre-commit check
# help: lint-pre-push        - Run linting as pre-push check
.PHONY: lint-install-hooks lint-pre-commit lint-pre-push

# Install git hooks for linting
lint-install-hooks:						## 🔧 Install git hooks for auto-linting
	@echo "🔧 Installing git pre-commit hooks for linting..."
	@if [ ! -d ".git" ]; then \
		echo "❌ Not a git repository"; \
		exit 1; \
	fi
	@echo '#!/bin/bash' > .git/hooks/pre-commit
	@echo '# Auto-generated pre-commit hook for linting' >> .git/hooks/pre-commit
	@echo 'echo "🔍 Running pre-commit linting..."' >> .git/hooks/pre-commit
	@echo 'make lint-pre-commit' >> .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo '#!/bin/bash' > .git/hooks/pre-push
	@echo '# Auto-generated pre-push hook for linting' >> .git/hooks/pre-push
	@echo 'echo "🔍 Running pre-push linting..."' >> .git/hooks/pre-push
	@echo 'make lint-pre-push' >> .git/hooks/pre-push
	@chmod +x .git/hooks/pre-push
	@echo "✅ Git hooks installed:"
	@echo "   📝 pre-commit: .git/hooks/pre-commit"
	@echo "   📤 pre-push: .git/hooks/pre-push"
	@echo "💡 To disable: rm .git/hooks/pre-commit .git/hooks/pre-push"

# Pre-commit hook (lint staged files)
lint-pre-commit:						## 🔍 Pre-commit linting check
	@echo "🔍 Pre-commit linting check..."
	@$(MAKE) --no-print-directory lint-staged
	@echo "✅ Pre-commit linting passed!"

# Pre-push hook (lint all changed files)
lint-pre-push:							## 🔍 Pre-push linting check
	@echo "🔍 Pre-push linting check..."
	@$(MAKE) --no-print-directory lint-changed
	@echo "✅ Pre-push linting passed!"

# -----------------------------------------------------------------------------
# 🎯 FILE TYPE SPECIFIC LINTING
# -----------------------------------------------------------------------------
# Lint only Python files in target
lint-py:								## 🐍 Lint only Python files
	@echo "🐍 Linting Python files in $(TARGET)..."
	@for target in $(DEFAULT_TARGETS); do \
		if [ -f "$$target" ] && echo "$$target" | grep -qE '\.py$$'; then \
			echo "🎯 Linting Python file: $$target"; \
			$(MAKE) --no-print-directory lint-target TARGET="$$target"; \
		elif [ -d "$$target" ]; then \
			echo "🔍 Finding Python files in: $$target"; \
			find "$$target" -name "*.py" -type f | while read f; do \
				echo "🎯 Linting: $$f"; \
				$(MAKE) --no-print-directory lint-target TARGET="$$f"; \
			done; \
		else \
			echo "⚠️  Skipping non-existent target: $$target"; \
		fi; \
	done
			echo "⚠️  Skipping non-existent target: $$target"; \
		fi; \
	done
		exit 1; \
	fi

# Lint only YAML files
lint-yaml:								## 📄 Lint only YAML files
	@echo "📄 Linting YAML files in $(TARGET)..."
	@for target in $(DEFAULT_TARGETS); do \
		if [ -f "$$target" ] && echo "$$target" | grep -qE '\.(yaml|yml)$$'; then \
			$(MAKE) --no-print-directory yamllint TARGET="$$target"; \
		elif [ -d "$$target" ]; then \
			find "$$target" -name "*.yaml" -o -name "*.yml" | while read f; do \
				echo "🎯 Linting: $$f"; \
				$(MAKE) --no-print-directory yamllint TARGET="$$f"; \
			done; \
		else \
			echo "⚠️  Skipping non-existent target: $$target"; \
		fi; \
	done
	fi

# Lint only JSON files
lint-json:								## 📄 Lint only JSON files
	@echo "📄 Linting JSON files in $(TARGET)..."
	@for target in $(DEFAULT_TARGETS); do \
		if [ -f "$$target" ] && echo "$$target" | grep -qE '\.json$$'; then \
			$(MAKE) --no-print-directory jsonlint TARGET="$$target"; \
		elif [ -d "$$target" ]; then \
			find "$$target" -name "*.json" | while read f; do \
				echo "🎯 Linting: $$f"; \
				$(MAKE) --no-print-directory jsonlint TARGET="$$f"; \
			done; \
		else \
			echo "⚠️  Skipping non-existent target: $$target"; \
		fi; \
	done
	fi

# Lint only Markdown files
lint-md:								## 📝 Lint only Markdown files
	@echo "📝 Linting Markdown files in $(TARGET)..."
	@for target in $(DEFAULT_TARGETS); do \
		if [ -f "$$target" ] && echo "$$target" | grep -qE '\.(md|markdown)$$'; then \
			$(MAKE) --no-print-directory markdownlint TARGET="$$target"; \
		elif [ -d "$$target" ]; then \
			find "$$target" -name "*.md" -o -name "*.markdown" | while read f; do \
				echo "🎯 Linting: $$f"; \
				$(MAKE) --no-print-directory markdownlint TARGET="$$f"; \
			done; \
		else \
			echo "⚠️  Skipping non-existent target: $$target"; \
		fi; \
	done
	fi

# -----------------------------------------------------------------------------
# 🚀 PERFORMANCE OPTIMIZATION
# -----------------------------------------------------------------------------
# help: lint-parallel        - Run linters in parallel for speed
# help: lint-cache-clear     - Clear linting caches
.PHONY: lint-parallel lint-cache-clear

# Parallel linting for better performance
lint-parallel:							## 🚀 Run linters in parallel
	@echo "🚀 Running linters in parallel on $(TARGET)..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q pytest-xdist"
	@# Run fast linters in parallel
	@$(MAKE) --no-print-directory ruff-check TARGET="$(TARGET)" & \
	$(MAKE) --no-print-directory black-check TARGET="$(TARGET)" & \
	$(MAKE) --no-print-directory isort-check TARGET="$(TARGET)" & \
	wait
	@echo "✅ Parallel linting completed!"

# Clear linting caches
lint-cache-clear:						## 🧹 Clear linting caches
	@echo "🧹 Clearing linting caches..."
	@rm -rf .mypy_cache .ruff_cache .pytest_cache __pycache__
	@find . -name "*.pyc" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Linting caches cleared!"

# -----------------------------------------------------------------------------
# 📊 LINTING STATISTICS AND METRICS
# -----------------------------------------------------------------------------
# help: lint-stats           - Show linting statistics
# help: lint-complexity      - Analyze code complexity
.PHONY: lint-stats lint-complexity

# Show linting statistics
lint-stats:								## 📊 Show linting statistics
	@echo "📊 Linting statistics for $(TARGET)..."
	@echo ""
	@echo "📁 File counts:"
	@if [ -d "$(TARGET)" ]; then \
		echo "   🐍 Python files: $$(find $(TARGET) -name '*.py' | wc -l)"; \
		echo "   📄 YAML files: $$(find $(TARGET) -name '*.yaml' -o -name '*.yml' | wc -l)"; \
		echo "   📄 JSON files: $$(find $(TARGET) -name '*.json' | wc -l)"; \
		echo "   📝 Markdown files: $$(find $(TARGET) -name '*.md' | wc -l)"; \
	elif [ -f "$(TARGET)" ]; then \
		echo "   📄 Single file: $(TARGET)"; \
	fi
	@echo ""
	@echo "🔍 Running quick analysis..."
	@$(MAKE) --no-print-directory lint-count-errors TARGET="$(TARGET)" 2>/dev/null || true

# Analyze code complexity
lint-complexity:						## 📈 Analyze code complexity
	@echo "📈 Analyzing code complexity for $(TARGET)..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q radon && \
		echo '📊 Cyclomatic Complexity:' && \
		$(VENV_DIR)/bin/radon cc $(TARGET) -s && \
		echo '' && \
		echo '📊 Maintainability Index:' && \
		$(VENV_DIR)/bin/radon mi $(TARGET) -s"

# -----------------------------------------------------------------------------
# 📑 GRYPE SECURITY/VULNERABILITY SCANNING
# -----------------------------------------------------------------------------
# help: grype-install        - Install Grype
# help: grype-scan           - Scan all files using grype
# help: grype-sarif          - Generate SARIF report
# help: security-scan        - Run Trivy and Grype security-scan
.PHONY: grype-install grype-scan grype-sarif security-scan

grype-install:
	@echo "📥 Installing Grype CLI..."
	@curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sudo sh -s -- -b /usr/local/bin

grype-scan:
	@command -v grype >/dev/null 2>&1 || { \
		echo "❌ grype not installed."; \
		echo "💡 Install with:"; \
		echo "   • curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sh -s -- -b /usr/local/bin"; \
		echo "   • Or run: make grype-install"; \
		exit 1; \
	}
	@echo "🔍 Grype vulnerability scan..."
	@grype $(IMG) --scope all-layers

grype-sarif:
	@command -v grype >/dev/null 2>&1 || { \
		echo "❌ grype not installed."; \
		echo "💡 Install with:"; \
		echo "   • curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sh -s -- -b /usr/local/bin"; \
		echo "   • Or run: make grype-install"; \
		exit 1; \
	}
	@echo "📄 Generating Grype SARIF report..."
	@grype $(IMG) --scope all-layers --output sarif --file grype-results.sarif

security-scan: trivy grype-scan
	@echo "✅ Multi-engine security scan complete"

# -----------------------------------------------------------------------------
# 📑 YAML / JSON / TOML LINTERS
# -----------------------------------------------------------------------------
# help: yamllint             - Lint YAML files (uses .yamllint)
# help: jsonlint             - Validate every *.json file with jq (--exit-status)
# help: tomllint             - Validate *.toml files with tomlcheck
#
# ➊  Add the new linters to the master list
LINTERS += yamllint jsonlint tomllint

# ➋  Individual targets
.PHONY: yamllint jsonlint tomllint

yamllint:                         ## 📑 YAML linting
	@echo '📑  yamllint ...'
	$(call ensure_pip_package,yamllint)
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q yamllint 2>/dev/null || true"
	@$(VENV_DIR)/bin/yamllint -c .yamllint .

jsonlint:                         ## 📑 JSON validation (jq)
	@command -v jq >/dev/null 2>&1 || { \
		echo "❌ jq not installed."; \
		echo "💡 Install with:"; \
		echo "   • macOS: brew install jq"; \
		echo "   • Linux: sudo apt-get install jq"; \
		exit 1; \
	}
	@echo '📑  jsonlint (jq) ...'
	@find . -type f -name '*.json' -not -path './node_modules/*' -print0 \
	  | xargs -0 -I{} sh -c 'jq empty "{}"' \
	&& echo '✅  All JSON valid'

tomllint:                         ## 📑 TOML validation (tomlcheck)
	@echo '📑  tomllint (tomlcheck) ...'
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q tomlcheck 2>/dev/null || true"
	@find . -type f -name '*.toml' -print0 \
	  | xargs -0 -I{} $(VENV_DIR)/bin/tomlcheck "{}"

# =============================================================================
# 🕸️  WEBPAGE LINTERS & STATIC ANALYSIS
# =============================================================================
# help: 🕸️  WEBPAGE LINTERS & STATIC ANALYSIS (HTML/CSS/JS lint + security scans + formatting)
# help: install-web-linters  - Install HTMLHint, Stylelint, ESLint, Retire.js, Prettier, JSHint, jscpd & markuplint via npm
# help: nodejsscan           - Run nodejsscan for JS security vulnerabilities
# help: lint-web             - Run HTMLHint, Stylelint, ESLint, Retire.js, nodejsscan and npm audit
# help: jshint               - Run JSHint for additional JavaScript analysis
# help: jscpd                - Detect copy-pasted code in JS/HTML/CSS files
# help: markuplint           - Modern HTML linting with markuplint
# help: format-web           - Format HTML, CSS & JS files with Prettier
.PHONY: install-web-linters nodejsscan lint-web jshint jscpd markuplint format-web

install-web-linters:
	@echo "🔧 Installing HTML/CSS/JS lint, security & formatting tools..."
	@if [ ! -f package.json ]; then \
	  echo "📦 Initializing npm project..."; \
	  npm init -y >/dev/null; \
	fi
	@npm install --no-save \
		htmlhint \
		stylelint stylelint-config-standard @stylistic/stylelint-config stylelint-order \
		eslint eslint-config-standard \
		retire \
		prettier \
		jshint \
		jscpd \
		markuplint

nodejsscan:
	@echo "🔒 Running nodejsscan for JavaScript security vulnerabilities..."
	$(call ensure_pip_package,nodejsscan)
	@$(VENV_DIR)/bin/nodejsscan --directory ./mcpgateway/static || true

lint-web: install-web-linters nodejsscan
	@echo "🔍 Linting HTML files..."
	@npx htmlhint "mcpgateway/templates/**/*.html" || true
	@echo "🔍 Linting CSS files..."
	@npx stylelint "mcpgateway/static/**/*.css" || true
	@echo "🔍 Linting JS files..."
	@npx eslint "mcpgateway/static/**/*.js" || true
	@echo "🔒 Scanning for known JS/CSS library vulnerabilities with retire.js..."
	@npx retire --path mcpgateway/static || true
	@if [ -f package.json ]; then \
	  echo "🔒 Running npm audit (high severity)..."; \
	  npm audit --audit-level=high || true; \
	else \
	  echo "⚠️  Skipping npm audit: no package.json found"; \
	fi

jshint: install-web-linters
	@echo "🔍 Running JSHint for JavaScript analysis..."
	@if [ -f .jshintrc ]; then \
	  echo "📋 Using .jshintrc configuration"; \
	  npx jshint --config .jshintrc mcpgateway/static/*.js || true; \
	else \
	  echo "📋 No .jshintrc found, using defaults with ES11"; \
	  npx jshint --esversion=11 mcpgateway/static/*.js || true; \
	fi

jscpd: install-web-linters
	@echo "🔍 Detecting copy-pasted code with jscpd..."
	@npx jscpd "mcpgateway/static/" "mcpgateway/templates/" || true

markuplint: install-web-linters
	@echo "🔍 Running markuplint for modern HTML validation..."
	@npx markuplint mcpgateway/templates/* || true

format-web: install-web-linters
	@echo "🎨 Formatting HTML, CSS & JS with Prettier..."
	@npx prettier --write "mcpgateway/templates/**/*.html" \
	                 "mcpgateway/static/**/*.css" \
	                 "mcpgateway/static/**/*.js"

################################################################################
# 🛡️  OSV-SCANNER  ▸  vulnerabilities scanner
################################################################################
# help: osv-install          - Install/upgrade osv-scanner (Go)
# help: osv-scan-source      - Scan source & lockfiles for CVEs
# help: osv-scan-image       - Scan the built container image for CVEs
# help: osv-scan             - Run all osv-scanner checks (source, image, licence)

.PHONY: osv-install osv-scan-source osv-scan-image osv-scan

osv-install:                  ## Install/upgrade osv-scanner
	go install github.com/google/osv-scanner/v2/cmd/osv-scanner@latest

# ─────────────── Source directory scan ────────────────────────────────────────
osv-scan-source:
	@command -v osv-scanner >/dev/null 2>&1 || { \
		echo "❌ osv-scanner not installed."; \
		echo "💡 Install with:"; \
		echo "   • go install github.com/google/osv-scanner/v2/cmd/osv-scanner@latest"; \
		echo "   • Or run: make osv-install"; \
		exit 1; \
	}
	@echo "🔍  osv-scanner source scan..."
	@osv-scanner scan source --recursive .

# ─────────────── Container image scan ─────────────────────────────────────────
osv-scan-image:
	@command -v osv-scanner >/dev/null 2>&1 || { \
		echo "❌ osv-scanner not installed."; \
		echo "💡 Install with:"; \
		echo "   • go install github.com/google/osv-scanner/v2/cmd/osv-scanner@latest"; \
		echo "   • Or run: make osv-install"; \
		exit 1; \
	}
	@echo "🔍  osv-scanner image scan..."
	@CONTAINER_CLI=$$(command -v docker || command -v podman) ; \
	  if [ -n "$$CONTAINER_CLI" ]; then \
	    osv-scanner scan image $(DOCKLE_IMAGE) || true ; \
	  else \
	    TARBALL=$$(mktemp /tmp/$(PROJECT_NAME)-osvscan-XXXXXX.tar) ; \
	    podman save --format=docker-archive $(DOCKLE_IMAGE) -o "$$TARBALL" ; \
	    osv-scanner scan image --archive "$$TARBALL" ; \
	    rm -f "$$TARBALL" ; \
	  fi

# ─────────────── Umbrella target ─────────────────────────────────────────────
osv-scan: osv-scan-source osv-scan-image
	@echo "✅  osv-scanner checks complete."

# =============================================================================
# 📡 SONARQUBE ANALYSIS (SERVER + SCANNERS)
# =============================================================================
# help: 📡 SONARQUBE ANALYSIS
# help: sonar-deps-podman    - Install podman-compose + supporting tools
# help: sonar-deps-docker    - Install docker-compose + supporting tools
# help: sonar-up-podman      - Launch SonarQube with podman-compose
# help: sonar-up-docker      - Launch SonarQube with docker-compose
# help: sonar-submit-docker  - Run containerized Sonar Scanner CLI with Docker
# help: sonar-submit-podman  - Run containerized Sonar Scanner CLI with Podman
# help: pysonar-scanner      - Run scan with Python wrapper (pysonar-scanner)
# help: sonar-info           - How to create a token & which env vars to export

.PHONY: sonar-deps-podman sonar-deps-docker sonar-up-podman sonar-up-docker \
	sonar-submit-docker sonar-submit-podman pysonar-scanner sonar-info

# ───── Configuration ─────────────────────────────────────────────────────
# server image tag
SONARQUBE_VERSION   ?= latest
SONAR_SCANNER_IMAGE ?= docker.io/sonarsource/sonar-scanner-cli:latest
# service name inside the container. Override for remote SQ
SONAR_HOST_URL      ?= http://sonarqube:9000
# compose network name (podman network ls)
SONAR_NETWORK       ?= mcp-context-forge_sonarnet
# analysis props file
SONAR_PROPS         ?= sonar-code.properties
# path mounted into scanner:
PROJECT_BASEDIR     ?= $(strip $(PWD))
# Optional auth token: export SONAR_TOKEN=xxxx
# ─────────────────────────────────────────────────────────────────────────

## ─────────── Dependencies (compose + misc) ─────────────────────────────
sonar-deps-podman:
	@echo "🔧 Installing podman-compose ..."
	python3 -m pip install --quiet podman-compose

sonar-deps-docker:
	@echo "🔧 Ensuring $(COMPOSE_CMD) is available ..."
	@command -v $(firstword $(COMPOSE_CMD)) >/dev/null || \
	  python3 -m pip install --quiet docker-compose

## ─────────── Run SonarQube server (compose) ────────────────────────────
sonar-up-podman:
	@echo "🚀 Starting SonarQube (v$(SONARQUBE_VERSION)) with podman-compose ..."
	SONARQUBE_VERSION=$(SONARQUBE_VERSION) \
	podman-compose -f podman-compose-sonarqube.yaml up -d
	@sleep 30 && podman ps | grep sonarqube || echo "⚠️  Server may still be starting."

sonar-up-docker:
	@echo "🚀 Starting SonarQube (v$(SONARQUBE_VERSION)) with $(COMPOSE_CMD) ..."
	SONARQUBE_VERSION=$(SONARQUBE_VERSION) \
	$(COMPOSE_CMD) -f podman-compose-sonarqube.yaml up -d
	@sleep 30 && $(COMPOSE_CMD) ps | grep sonarqube || \
	  echo "⚠️  Server may still be starting."

## ─────────── Containerized Scanner CLI (Docker / Podman) ───────────────
sonar-submit-docker:
	@echo "📡 Scanning code with containerized Sonar Scanner CLI (Docker) ..."
	docker run --rm \
		-e SONAR_HOST_URL="$(SONAR_HOST_URL)" \
		$(if $(SONAR_TOKEN),-e SONAR_TOKEN="$(SONAR_TOKEN)",) \
		-v "$(PROJECT_BASEDIR):/usr/src" \
		$(SONAR_SCANNER_IMAGE) \
		-Dproject.settings=$(SONAR_PROPS)

sonar-submit-podman:
	@echo "📡 Scanning code with containerized Sonar Scanner CLI (Podman) ..."
	podman run --rm \
		--network $(SONAR_NETWORK) \
		-e SONAR_HOST_URL="$(SONAR_HOST_URL)" \
		$(if $(SONAR_TOKEN),-e SONAR_TOKEN="$(SONAR_TOKEN)",) \
		-v "$(PROJECT_BASEDIR):/usr/src:Z" \
		$(SONAR_SCANNER_IMAGE) \
		-Dproject.settings=$(SONAR_PROPS)

## ─────────── Python wrapper (pysonar-scanner) ───────────────────────────
pysonar-scanner:
	@echo "🐍 Scanning code with pysonar-scanner (PyPI) ..."
	@test -f $(SONAR_PROPS) || { echo "❌ $(SONAR_PROPS) not found."; exit 1; }
	python3 -m pip install --upgrade --quiet pysonar-scanner
	python3 -m pysonar_scanner \
		-Dproject.settings=$(SONAR_PROPS) \
		-Dsonar.host.url=$(SONAR_HOST_URL) \
		$(if $(SONAR_TOKEN),-Dsonar.login=$(SONAR_TOKEN),)

## ─────────── Helper: how to create & use the token ──────────────────────
sonar-info:
	@echo
	@echo "───────────────────────────────────────────────────────────"
	@echo "🔑  HOW TO GENERATE A SONAR TOKEN & EXPORT ENV VARS"
	@echo "───────────────────────────────────────────────────────────"
	@echo "1. Open   $(SONAR_HOST_URL)   in your browser."
	@echo "2. Log in → click your avatar → **My Account → Security**."
	@echo "3. Under **Tokens**, enter a name (e.g. mcp-local) and press **Generate**."
	@echo "4. **Copy the token NOW** - you will not see it again."
	@echo
	@echo "Then in your shell:"
	@echo "   export SONAR_TOKEN=<paste-token>"
	@echo "   export SONAR_HOST_URL=$(SONAR_HOST_URL)"
	@echo
	@echo "Now you can run:"
	@echo "   make sonar-submit-docker   # or sonar-submit-podman / pysonar-scanner"
	@echo "───────────────────────────────────────────────────────────"


# =============================================================================
# 🛡️  SECURITY & PACKAGE SCANNING
# =============================================================================
# help: 🛡️ SECURITY & PACKAGE SCANNING
# help: trivy-install        - Install Trivy
# help: trivy                - Scan container image for CVEs (HIGH/CRIT). Needs podman socket enabled
.PHONY: trivy-install trivy

trivy-install:
	@echo "📥 Installing Trivy..."
	@curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

trivy:
	@command -v trivy >/dev/null 2>&1 || { \
		echo "❌ trivy not installed."; \
		echo "💡 Install with:"; \
		echo "   • macOS: brew install trivy"; \
		echo "   • Linux: curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin"; \
		echo "   • Or run: make trivy-install"; \
		exit 1; \
	}
	@if command -v systemctl >/dev/null 2>&1; then \
		systemctl --user enable --now podman.socket 2>/dev/null || true; \
	fi
	@echo "🔎  trivy vulnerability scan..."
	@trivy --format table --severity HIGH,CRITICAL image $(IMG)

# help: dockle               - Lint the built container image via tarball (no daemon/socket needed)
.PHONY: dockle
DOCKLE_IMAGE ?= $(IMG)         # mcpgateway/mcpgateway:latest
dockle:
	@echo "🔎  dockle scan (tar mode) on $(DOCKLE_IMAGE)..."
	@command -v dockle >/dev/null 2>&1 || { \
		echo "❌ dockle not installed."; \
		echo "💡 Install with:"; \
		echo "   • macOS: brew install goodwithtech/r/dockle"; \
		echo "   • Linux: Download from https://github.com/goodwithtech/dockle/releases"; \
		exit 1; \
	}

	# Pick docker or podman-whichever is on PATH
	@CONTAINER_CLI=$$(command -v docker || command -v podman) ; \
	[ -n "$$CONTAINER_CLI" ] || { echo '❌  docker/podman not found.'; exit 1; }; \
	TARBALL=$$(mktemp /tmp/$(PROJECT_NAME)-dockle-XXXXXX.tar) ; \
	echo "📦  Saving image to $$TARBALL..." ; \
	"$$CONTAINER_CLI" save $(DOCKLE_IMAGE) -o "$$TARBALL" || { rm -f "$$TARBALL"; exit 1; }; \
	echo "🧪  Running Dockle..." ; \
	dockle -af settings.py --no-color --exit-code 1 --exit-level warn --input "$$TARBALL" ; \
	rm -f "$$TARBALL"

# help: hadolint             - Lint Containerfile/Dockerfile(s) with hadolint
.PHONY: hadolint
# List of Containerfile/Dockerfile patterns to scan
HADOFILES := Containerfile Containerfile.* Dockerfile Dockerfile.*

hadolint:
	@echo "🔎  hadolint scan..."

	# ─── Ensure hadolint is installed ──────────────────────────────────────
	@if ! command -v hadolint >/dev/null 2>&1; then \
		echo "❌  hadolint not found."; \
		case "$$(uname -s)" in \
			Linux*)  echo "💡  Install with:"; \
			         echo "    sudo wget -O /usr/local/bin/hadolint \\"; \
			         echo "      https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-x86_64"; \
			         echo "    sudo chmod +x /usr/local/bin/hadolint";; \
			Darwin*) echo "💡  Install with Homebrew: brew install hadolint";; \
			*)       echo "💡  See other binaries: https://github.com/hadolint/hadolint/releases";; \
		esac; \
		exit 1; \
	fi

	# ─── Run hadolint on each existing file ───────────────────────────────
	@found=0; \
	for f in $(HADOFILES); do \
		if [ -f "$$f" ]; then \
			echo "📝  Scanning $$f"; \
			hadolint "$$f" || true; \
			found=1; \
		fi; \
	done; \
	if [ "$$found" -eq 0 ]; then \
		echo "ℹ️  No Containerfile/Dockerfile found - nothing to scan."; \
	fi


# =============================================================================
# 📦 DEPENDENCY MANAGEMENT
# =============================================================================
# help: 📦 DEPENDENCY MANAGEMENT
# help: deps-update          - Run update-deps.py to update all dependencies in pyproject.toml and docs/requirements.txt
# help: containerfile-update - Update base image in Containerfile to latest tag

.PHONY: deps-update containerfile-update

deps-update:
	@echo "⬆️  Updating project dependencies via update_dependencies.py..."
	@test -f ./.github/tools/update_dependencies.py || { echo "❌ update_dependencies.py not found in ./.github/tools."; exit 1; }
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 ./.github/tools/update_dependencies.py --ignore-dependency starlette --file pyproject.toml"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 ./.github/tools/update_dependencies.py --file docs/requirements.txt"
	@echo "✅ Dependencies updated in pyproject.toml and docs/requirements.txt"

containerfile-update:
	@echo "⬆️  Updating base image in Containerfile to :latest tag..."
	@test -f Containerfile || { echo "❌ Containerfile not found."; exit 1; }
	@sed -i.bak -E 's|^(FROM\s+\S+):[^\s]+|\1:latest|' Containerfile && rm -f Containerfile.bak
	@echo "✅ Base image updated to latest."


# =============================================================================
# 📦 PACKAGING & PUBLISHING
# =============================================================================
# help: 📦 PACKAGING & PUBLISHING
# help: dist                 - Clean-build wheel *and* sdist into ./dist
# help: wheel                - Build wheel only
# help: sdist                - Build source distribution only
# help: verify               - Build + twine + check-manifest + pyroma (no upload)
# help: publish              - Verify, then upload to PyPI (needs TWINE_* creds)
# =============================================================================
.PHONY: dist wheel sdist verify publish publish-testpypi

dist: clean                  ## Build wheel + sdist into ./dist
	@test -d "$(VENV_DIR)" || $(MAKE) --no-print-directory venv
	@/bin/bash -eu -c "\
	    source $(VENV_DIR)/bin/activate && \
	    python3 -m pip install --quiet --upgrade pip build && \
	    python3 -m build"
	@echo '🛠  Wheel & sdist written to ./dist'

wheel:                       ## Build wheel only
	@test -d "$(VENV_DIR)" || $(MAKE) --no-print-directory venv
	@/bin/bash -eu -c "\
	    source $(VENV_DIR)/bin/activate && \
	    python3 -m pip install --quiet --upgrade pip build && \
	    python3 -m build -w"
	@echo '🛠  Wheel written to ./dist'

sdist:                       ## Build source distribution only
	@test -d "$(VENV_DIR)" || $(MAKE) --no-print-directory venv
	@/bin/bash -eu -c "\
	    source $(VENV_DIR)/bin/activate && \
	    python3 -m pip install --quiet --upgrade pip build && \
	    python3 -m build -s"
	@echo '🛠  Source distribution written to ./dist'

verify: dist               ## Build, run metadata & manifest checks
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	twine check dist/* && \
	check-manifest && \
	pyroma -d ."
	@echo "✅  Package verified - ready to publish."

publish: verify            ## Verify, then upload to PyPI
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && twine upload dist/*"
	@echo "🚀  Upload finished - check https://pypi.org/project/$(PROJECT_NAME)/"

publish-testpypi: verify   ## Verify, then upload to TestPyPI
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && twine upload --repository testpypi dist/*"
	@echo "🚀  Upload finished - check https://test.pypi.org/project/$(PROJECT_NAME)/"

# Allow override via environment
ifdef FORCE_DOCKER
  CONTAINER_RUNTIME := docker
endif

ifdef FORCE_PODMAN
  CONTAINER_RUNTIME := podman
endif

# Support for CI/CD environments
ifdef CI
  # Many CI systems have docker command that's actually podman
  CONTAINER_RUNTIME := $(shell $(CONTAINER_RUNTIME) --version | grep -q podman && echo podman || echo docker)
endif


# =============================================================================
# 🐳 CONTAINER RUNTIME CONFIGURATION
# =============================================================================

# Auto-detect container runtime if not specified - DEFAULT TO DOCKER
CONTAINER_RUNTIME ?= $(shell command -v docker >/dev/null 2>&1 && echo docker || echo podman)

# Alternative: Always default to docker unless explicitly overridden
# CONTAINER_RUNTIME ?= docker

print-runtime:
	@echo Using container runtime: $(CONTAINER_RUNTIME)
# Base image name (without any prefix)
IMAGE_BASE := mcpgateway/mcpgateway
IMAGE_TAG := latest

# Handle runtime-specific image naming
ifeq ($(CONTAINER_RUNTIME),podman)
  # Podman adds localhost/ prefix for local builds
  IMAGE_LOCAL := localhost/$(IMAGE_BASE):$(IMAGE_TAG)
  IMAGE_LOCAL_DEV := localhost/$(IMAGE_BASE)-dev:$(IMAGE_TAG)
  IMAGE_PUSH := $(IMAGE_BASE):$(IMAGE_TAG)
else
  # Docker doesn't add prefix
  IMAGE_LOCAL := $(IMAGE_BASE):$(IMAGE_TAG)
  IMAGE_LOCAL_DEV := $(IMAGE_BASE)-dev:$(IMAGE_TAG)
  IMAGE_PUSH := $(IMAGE_BASE):$(IMAGE_TAG)
endif

print-image:
	@echo "🐳 Container Runtime: $(CONTAINER_RUNTIME)"
	@echo "Using image: $(IMAGE_LOCAL)"
	@echo "Development image: $(IMAGE_LOCAL_DEV)"
	@echo "Push image: $(IMAGE_PUSH)"

# Legacy compatibility
IMG := $(IMAGE_LOCAL)
IMG-DEV := $(IMAGE_LOCAL_DEV)

# Function to get the actual image name as it appears in image list
define get_image_name
$(shell $(CONTAINER_RUNTIME) images --format "{{.Repository}}:{{.Tag}}" | grep -E "(localhost/)?$(IMAGE_BASE):$(IMAGE_TAG)" | head -1)
endef

# Function to normalize image name for operations
define normalize_image
$(if $(findstring localhost/,$(1)),$(1),$(if $(filter podman,$(CONTAINER_RUNTIME)),localhost/$(1),$(1)))
endef

# =============================================================================
# 🐳 UNIFIED CONTAINER OPERATIONS
# =============================================================================
# help: 🐳 UNIFIED CONTAINER OPERATIONS (Auto-detects Docker/Podman)
# help: container-build      - Build image using detected runtime
# help: container-run        - Run container using detected runtime
# help: container-run-host   - Run container using detected runtime with host networking
# help: container-run-ssl    - Run container with TLS using detected runtime
# help: container-run-ssl-host - Run container with TLS and host networking
# help: container-push       - Push image (handles localhost/ prefix)
# help: container-stop       - Stop & remove the container
# help: container-logs       - Stream container logs
# help: container-shell      - Open shell in running container
# help: container-info       - Show runtime and image configuration
# help: container-health     - Check container health status
# help: image-list           - List all matching container images
# help: image-clean          - Remove all project images
# help: image-retag          - Fix image naming consistency issues
# help: use-docker           - Switch to Docker runtime
# help: use-podman           - Switch to Podman runtime
# help: show-runtime         - Show current container runtime

.PHONY: container-build container-run container-run-ssl container-run-ssl-host \
        container-push container-info container-stop container-logs container-shell \
        container-health image-list image-clean image-retag container-check-image \
        container-build-multi use-docker use-podman show-runtime print-runtime \
        print-image container-validate-env container-check-ports container-wait-healthy


# Containerfile to use (can be overridden)
#CONTAINER_FILE ?= Containerfile
CONTAINER_FILE ?= $(shell [ -f "Containerfile.lite" ] && echo "Containerfile.lite" || echo "Dockerfile")


# Define COMMA for the conditional Z flag
COMMA := ,

container-info:
	@echo "🐳 Container Runtime Configuration"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Runtime:        $(CONTAINER_RUNTIME)"
	@echo "Base Image:     $(IMAGE_BASE)"
	@echo "Tag:            $(IMAGE_TAG)"
	@echo "Local Image:    $(IMAGE_LOCAL)"
	@echo "Push Image:     $(IMAGE_PUSH)"
	@echo "Actual Image:   $(call get_image_name)"
	@echo "Container File: $(CONTAINER_FILE)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Auto-detect platform based on uname
PLATFORM ?= linux/$(shell uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')

container-build:
	@echo "🔨 Building with $(CONTAINER_RUNTIME) for platform $(PLATFORM)..."
	$(CONTAINER_RUNTIME) build \
		--platform=$(PLATFORM) \
		-f $(CONTAINER_FILE) \
		--tag $(IMAGE_BASE):$(IMAGE_TAG) \
		.
	@echo "✅ Built image: $(call get_image_name)"
	$(CONTAINER_RUNTIME) images $(IMAGE_BASE):$(IMAGE_TAG)

container-run: container-check-image
	@echo "🚀 Running with $(CONTAINER_RUNTIME)..."
	-$(CONTAINER_RUNTIME) stop $(PROJECT_NAME) 2>/dev/null || true
	-$(CONTAINER_RUNTIME) rm $(PROJECT_NAME) 2>/dev/null || true
	$(CONTAINER_RUNTIME) run --name $(PROJECT_NAME) \
		--env-file=.env \
		-p 4444:4444 \
		--restart=always \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl --fail http://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(call get_image_name)
	@sleep 2
	@echo "✅ Container started"
	@echo "🔍 Health check status:"
	@$(CONTAINER_RUNTIME) inspect $(PROJECT_NAME) --format='{{.State.Health.Status}}' 2>/dev/null || echo "No health check configured"

container-run-host: container-check-image
	@echo "🚀 Running with $(CONTAINER_RUNTIME)..."
	-$(CONTAINER_RUNTIME) stop $(PROJECT_NAME) 2>/dev/null || true
	-$(CONTAINER_RUNTIME) rm $(PROJECT_NAME) 2>/dev/null || true
	$(CONTAINER_RUNTIME) run --name $(PROJECT_NAME) \
		--env-file=.env \
		--network=host \
		-p 4444:4444 \
		--restart=always \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl --fail http://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(call get_image_name)
	@sleep 2
	@echo "✅ Container started"
	@echo "🔍 Health check status:"
	@$(CONTAINER_RUNTIME) inspect $(PROJECT_NAME) --format='{{.State.Health.Status}}' 2>/dev/null || echo "No health check configured"


container-run-ssl: certs container-check-image
	@echo "🚀 Running with $(CONTAINER_RUNTIME) (TLS)..."
	-$(CONTAINER_RUNTIME) stop $(PROJECT_NAME) 2>/dev/null || true
	-$(CONTAINER_RUNTIME) rm $(PROJECT_NAME) 2>/dev/null || true
	$(CONTAINER_RUNTIME) run --name $(PROJECT_NAME) \
		--env-file=.env \
		-e SSL=true \
		-e CERT_FILE=certs/cert.pem \
		-e KEY_FILE=certs/key.pem \
		-v $(PWD)/certs:/app/certs:ro$(if $(filter podman,$(CONTAINER_RUNTIME)),$(COMMA)Z,) \
		-p 4444:4444 \
		--restart=always \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl -k --fail https://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(call get_image_name)
	@sleep 2
	@echo "✅ Container started with TLS"

container-run-ssl-host: certs container-check-image
	@echo "🚀 Running with $(CONTAINER_RUNTIME) (TLS, host network)..."
	-$(CONTAINER_RUNTIME) stop $(PROJECT_NAME) 2>/dev/null || true
	-$(CONTAINER_RUNTIME) rm $(PROJECT_NAME) 2>/dev/null || true
	$(CONTAINER_RUNTIME) run --name $(PROJECT_NAME) \
		--network=host \
		--env-file=.env \
		-e SSL=true \
		-e CERT_FILE=certs/cert.pem \
		-e KEY_FILE=certs/key.pem \
		-v $(PWD)/certs:/app/certs:ro$(if $(filter podman,$(CONTAINER_RUNTIME)),$(COMMA)Z,) \
		--restart=always \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl -k --fail https://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(call get_image_name)
	@sleep 2
	@echo "✅ Container started with TLS (host networking)"

container-push: container-check-image
	@echo "📤 Preparing to push image..."
	@# For Podman, we need to remove localhost/ prefix for push
	@if [ "$(CONTAINER_RUNTIME)" = "podman" ]; then \
		actual_image=$$($(CONTAINER_RUNTIME) images --format "{{.Repository}}:{{.Tag}}" | grep -E "$(IMAGE_BASE):$(IMAGE_TAG)" | head -1); \
		if echo "$$actual_image" | grep -q "^localhost/"; then \
			echo "🏷️  Tagging for push (removing localhost/ prefix)..."; \
			$(CONTAINER_RUNTIME) tag "$$actual_image" $(IMAGE_PUSH); \
		fi; \
	fi
	$(CONTAINER_RUNTIME) push $(IMAGE_PUSH)
	@echo "✅ Pushed: $(IMAGE_PUSH)"

container-check-image:
	@echo "🔍 Checking for image..."
	@if [ "$(CONTAINER_RUNTIME)" = "podman" ]; then \
		if ! $(CONTAINER_RUNTIME) image exists $(IMAGE_LOCAL) 2>/dev/null && \
		   ! $(CONTAINER_RUNTIME) image exists $(IMAGE_BASE):$(IMAGE_TAG) 2>/dev/null; then \
			echo "❌ Image not found: $(IMAGE_LOCAL)"; \
			echo "💡 Run 'make container-build' first"; \
			exit 1; \
		fi; \
	else \
		if ! $(CONTAINER_RUNTIME) images -q $(IMAGE_LOCAL) 2>/dev/null | grep -q . && \
		   ! $(CONTAINER_RUNTIME) images -q $(IMAGE_BASE):$(IMAGE_TAG) 2>/dev/null | grep -q .; then \
			echo "❌ Image not found: $(IMAGE_LOCAL)"; \
			echo "💡 Run 'make container-build' first"; \
			exit 1; \
		fi; \
	fi
	@echo "✅ Image found"

container-stop:
	@echo "🛑 Stopping container..."
	-$(CONTAINER_RUNTIME) stop $(PROJECT_NAME) 2>/dev/null || true
	-$(CONTAINER_RUNTIME) rm $(PROJECT_NAME) 2>/dev/null || true
	@echo "✅ Container stopped and removed"

container-logs:
	@echo "📜 Streaming logs (Ctrl+C to exit)..."
	$(CONTAINER_RUNTIME) logs -f $(PROJECT_NAME)

container-shell:
	@echo "🔧 Opening shell in container..."
	@if ! $(CONTAINER_RUNTIME) ps -q -f name=$(PROJECT_NAME) | grep -q .; then \
		echo "❌ Container $(PROJECT_NAME) is not running"; \
		echo "💡 Run 'make container-run' first"; \
		exit 1; \
	fi
	@$(CONTAINER_RUNTIME) exec -it $(PROJECT_NAME) /bin/bash 2>/dev/null || \
	$(CONTAINER_RUNTIME) exec -it $(PROJECT_NAME) /bin/sh

container-health:
	@echo "🏥 Checking container health..."
	@if ! $(CONTAINER_RUNTIME) ps -q -f name=$(PROJECT_NAME) | grep -q .; then \
		echo "❌ Container $(PROJECT_NAME) is not running"; \
		exit 1; \
	fi
	@echo "Status: $$($(CONTAINER_RUNTIME) inspect $(PROJECT_NAME) --format='{{.State.Health.Status}}' 2>/dev/null || echo 'No health check')"
	@echo "Logs:"
	@$(CONTAINER_RUNTIME) inspect $(PROJECT_NAME) --format='{{range .State.Health.Log}}{{.Output}}{{end}}' 2>/dev/null || true

container-build-multi:
	@echo "🔨 Building multi-architecture image..."
	@if [ "$(CONTAINER_RUNTIME)" = "docker" ]; then \
		if ! docker buildx inspect $(PROJECT_NAME)-builder >/dev/null 2>&1; then \
			echo "📦 Creating buildx builder..."; \
			docker buildx create --name $(PROJECT_NAME)-builder; \
		fi; \
		docker buildx use $(PROJECT_NAME)-builder; \
		docker buildx build \
			--platform=linux/amd64,linux/arm64 \
			-f $(CONTAINER_FILE) \
			--tag $(IMAGE_BASE):$(IMAGE_TAG) \
			--push \
			.; \
	elif [ "$(CONTAINER_RUNTIME)" = "podman" ]; then \
		echo "📦 Building manifest with Podman..."; \
		$(CONTAINER_RUNTIME) build --platform=linux/amd64,linux/arm64 \
			-f $(CONTAINER_FILE) \
			--manifest $(IMAGE_BASE):$(IMAGE_TAG) \
			.; \
		echo "💡 To push: podman manifest push $(IMAGE_BASE):$(IMAGE_TAG)"; \
	else \
		echo "❌ Multi-arch builds require Docker buildx or Podman"; \
		exit 1; \
	fi

# Helper targets for debugging image issues
image-list:
	@echo "📋 Images matching $(IMAGE_BASE):"
	@$(CONTAINER_RUNTIME) images --format "table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Created}}\t{{.Size}}" | \
		grep -E "(IMAGE|$(IMAGE_BASE))" || echo "No matching images found"

image-clean:
	@echo "🧹 Removing all $(IMAGE_BASE) images..."
	@$(CONTAINER_RUNTIME) images --format "{{.Repository}}:{{.Tag}}" | \
		grep -E "(localhost/)?$(IMAGE_BASE)" | \
		xargs $(XARGS_FLAGS) $(CONTAINER_RUNTIME) rmi -f 2>/dev/null
	@echo "✅ Images cleaned"

# Fix image naming issues
image-retag:
	@echo "🏷️  Retagging images for consistency..."
	@if [ "$(CONTAINER_RUNTIME)" = "podman" ]; then \
		if $(CONTAINER_RUNTIME) image exists $(IMAGE_BASE):$(IMAGE_TAG) 2>/dev/null; then \
			$(CONTAINER_RUNTIME) tag $(IMAGE_BASE):$(IMAGE_TAG) $(IMAGE_LOCAL) 2>/dev/null || true; \
		fi; \
	else \
		if $(CONTAINER_RUNTIME) images -q $(IMAGE_LOCAL) 2>/dev/null | grep -q .; then \
			$(CONTAINER_RUNTIME) tag $(IMAGE_LOCAL) $(IMAGE_BASE):$(IMAGE_TAG) 2>/dev/null || true; \
		fi; \
	fi
	@echo "✅ Images retagged"  # This always shows success

# Runtime switching helpers
use-docker:
	@echo "export CONTAINER_RUNTIME=docker"
	@echo "💡 Run: export CONTAINER_RUNTIME=docker"

use-podman:
	@echo "export CONTAINER_RUNTIME=podman"
	@echo "💡 Run: export CONTAINER_RUNTIME=podman"

show-runtime:
	@echo "Current runtime: $(CONTAINER_RUNTIME)"
	@echo "Detected from: $$(command -v $(CONTAINER_RUNTIME) || echo 'not found')"  # Added
	@echo "To switch: make use-docker or make use-podman"

# =============================================================================
# 🐳 ENHANCED CONTAINER OPERATIONS
# =============================================================================
# help: 🐳 ENHANCED CONTAINER OPERATIONS
# help: container-validate     - Pre-flight validation checks
# help: container-debug        - Run container with debug logging
# help: container-dev          - Run with source mounted for development
# help: container-check-ports  - Check if required ports are available

# Pre-flight validation
.PHONY: container-validate container-check-ports

container-validate: container-validate-env container-check-ports
	@echo "✅ All validations passed"

container-validate-env:
	@echo "🔍 Validating environment..."
	@test -f .env || { echo "❌ Missing .env file"; exit 1; }
	@grep -q "^MCP_" .env || { echo "⚠️  No MCP_ variables found in .env"; }
	@echo "✅ Environment validated"

container-check-ports:
	@echo "🔍 Checking port availability..."
	@if ! command -v lsof >/dev/null 2>&1; then \
		echo "⚠️  lsof not installed - skipping port check"; \
		echo "💡  Install with: brew install lsof (macOS) or apt-get install lsof (Linux)"; \
		exit 0; \
	fi
	@failed=0; \
	for port in 4444 8000 8080; do \
		if lsof -Pi :$$port -sTCP:LISTEN -t >/dev/null 2>&1; then \
			echo "❌ Port $$port is already in use"; \
			lsof -Pi :$$port -sTCP:LISTEN; \
			failed=1; \
		else \
			echo "✅ Port $$port is available"; \
		fi; \
	done; \
	test $$failed -eq 0

# Development container with mounted source
container-dev: container-check-image container-validate
	@echo "🔧 Running development container with mounted source..."
	-$(CONTAINER_RUNTIME) stop $(PROJECT_NAME)-dev 2>/dev/null || true
	-$(CONTAINER_RUNTIME) rm $(PROJECT_NAME)-dev 2>/dev/null || true
	$(CONTAINER_RUNTIME) run --name $(PROJECT_NAME)-dev \
		--env-file=.env \
		-e DEBUG=true \
		-e LOG_LEVEL=DEBUG \
		-v $(PWD)/mcpgateway:/app/mcpgateway:ro$(if $(filter podman,$(CONTAINER_RUNTIME)),$(COMMA)Z,) \
		-p 8000:8000 \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		-it --rm $(call get_image_name) \
		uvicorn mcpgateway.main:app --host 0.0.0.0 --port 8000 --reload

# Debug mode with verbose logging
container-debug: container-check-image
	@echo "🐛 Running container in debug mode..."
	$(CONTAINER_RUNTIME) run --name $(PROJECT_NAME)-debug \
		--env-file=.env \
		-e DEBUG=true \
		-e LOG_LEVEL=DEBUG \
		-e PYTHONFAULTHANDLER=1 \
		-p 4444:4444 \
		-it --rm $(call get_image_name)

# Enhanced run targets that include validation and health waiting
container-run-safe: container-validate container-run
	@$(MAKE) container-wait-healthy

container-run-ssl-safe: container-validate container-run-ssl
	@$(MAKE) container-wait-healthy

container-wait-healthy:
	@echo "⏳ Waiting for container to be healthy..."
	@for i in $$(seq 1 30); do \
		if $(CONTAINER_RUNTIME) inspect $(PROJECT_NAME) --format='{{.State.Health.Status}}' 2>/dev/null | grep -q healthy; then \
			echo "✅ Container is healthy"; \
			exit 0; \
		fi; \
		echo "⏳ Waiting for container health... ($$i/30)"; \
		sleep 2; \
	done; \
	echo "⚠️  Container not healthy after 60 seconds"; \
	exit 1

# =============================================================================
# 🦭 PODMAN CONTAINER BUILD & RUN
# =============================================================================
# help: 🦭 PODMAN CONTAINER BUILD & RUN
# help: podman-dev           - Build development container image
# help: podman               - Build container image
# help: podman-prod          - Build production container image (using ubi-micro → scratch). Not supported on macOS.
# help: podman-run           - Run the container on HTTP  (port 4444)
# help: podman-run-host      - Run the container on HTTP  (port 4444) with --network-host
# help: podman-run-shell     - Run the container on HTTP  (port 4444) and start a shell
# help: podman-run-ssl       - Run the container on HTTPS (port 4444, self-signed)
# help: podman-run-ssl-host  - Run the container on HTTPS with --network-host (port 4444, self-signed)
# help: podman-stop          - Stop & remove the container
# help: podman-test          - Quick curl smoke-test against the container
# help: podman-logs          - Follow container logs (⌃C to quit)
# help: podman-stats         - Show container resource stats (if supported)
# help: podman-top           - Show live top-level process info in container

.PHONY: podman-dev podman podman-prod podman-build podman-run podman-run-shell \
	podman-run-host podman-run-ssl podman-run-ssl-host podman-stop podman-test \
	podman-logs podman-stats podman-top podman-shell

podman-dev:
	@$(MAKE) container-build CONTAINER_RUNTIME=podman CONTAINER_FILE=Containerfile

podman:
	@$(MAKE) container-build CONTAINER_RUNTIME=podman CONTAINER_FILE=Containerfile

podman-prod:
	@$(MAKE) container-build CONTAINER_RUNTIME=podman CONTAINER_FILE=Containerfile.lite

podman-build:
	@$(MAKE) container-build CONTAINER_RUNTIME=podman

podman-run:
	@$(MAKE) container-run CONTAINER_RUNTIME=podman

podman-run-host:
	@$(MAKE) container-run-host CONTAINER_RUNTIME=podman

podman-run-shell:
	@echo "🚀  Starting podman container shell..."
	podman run --name $(PROJECT_NAME)-shell \
		--env-file=.env \
		-p 4444:4444 \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		-it --rm $(call get_image_name) \
		sh -c 'env; exec sh'

podman-run-ssl:
	@$(MAKE) container-run-ssl CONTAINER_RUNTIME=podman

podman-run-ssl-host:
	@$(MAKE) container-run-ssl-host CONTAINER_RUNTIME=podman

podman-stop:
	@$(MAKE) container-stop CONTAINER_RUNTIME=podman

podman-test:
	@echo "🔬  Testing podman endpoint..."
	@echo "- HTTP  -> curl  http://localhost:4444/system/test"
	@echo "- HTTPS -> curl -k https://localhost:4444/system/test"

podman-logs:
	@$(MAKE) container-logs CONTAINER_RUNTIME=podman

podman-stats:
	@echo "📊  Showing Podman container stats..."
	@if podman info --format '{{.Host.CgroupManager}}' | grep -q 'cgroupfs'; then \
		echo "⚠️  podman stats not supported in rootless mode without cgroups v2 (e.g., WSL2)"; \
		echo "👉  Falling back to 'podman top'"; \
		podman top $(PROJECT_NAME); \
	else \
		podman stats --no-stream; \
	fi

podman-top:
	@echo "🧠  Showing top-level processes in the Podman container..."
	podman top


# =============================================================================
# 🐋 DOCKER BUILD & RUN
# =============================================================================
# help: 🐋 DOCKER BUILD & RUN
# help: docker-dev           - Build development Docker image
# help: docker               - Build production Docker image
# help: docker-prod          - Build production container image (using ubi-micro → scratch). Not supported on macOS.
# help: docker-run           - Run the container on HTTP  (port 4444)
# help: docker-run-host      - Run the container on HTTP  (port 4444) with --network-host
# help: docker-run-ssl       - Run the container on HTTPS (port 4444, self-signed)
# help: docker-run-ssl-host  - Run the container on HTTPS with --network-host (port 4444, self-signed)
# help: docker-stop          - Stop & remove the container
# help: docker-test          - Quick curl smoke-test against the container
# help: docker-logs          - Follow container logs (⌃C to quit)

.PHONY: docker-dev docker docker-prod docker-build docker-run docker-run-host docker-run-ssl \
	docker-run-ssl-host docker-stop docker-test docker-logs docker-stats \
	docker-top docker-shell

docker-dev:
	@$(MAKE) container-build CONTAINER_RUNTIME=docker CONTAINER_FILE=Containerfile

docker:
	@$(MAKE) container-build CONTAINER_RUNTIME=docker CONTAINER_FILE=Containerfile

docker-prod:
	@DOCKER_CONTENT_TRUST=1 $(MAKE) container-build CONTAINER_RUNTIME=docker CONTAINER_FILE=Containerfile.lite

docker-build:
	@$(MAKE) container-build CONTAINER_RUNTIME=docker

docker-run:
	@$(MAKE) container-run CONTAINER_RUNTIME=docker

docker-run-host:
	@$(MAKE) container-run-host CONTAINER_RUNTIME=docker

docker-run-ssl:
	@$(MAKE) container-run-ssl CONTAINER_RUNTIME=docker

docker-run-ssl-host:
	@$(MAKE) container-run-ssl-host CONTAINER_RUNTIME=docker

docker-stop:
	@$(MAKE) container-stop CONTAINER_RUNTIME=docker

docker-test:
	@echo "🔬  Testing Docker endpoint..."
	@echo "- HTTP  -> curl  http://localhost:4444/system/test"
	@echo "- HTTPS -> curl -k https://localhost:4444/system/test"

docker-logs:
	@$(MAKE) container-logs CONTAINER_RUNTIME=docker

# help: docker-stats         - Show container resource usage stats (non-streaming)
docker-stats:
	@echo "📊  Showing Docker container stats..."
	@docker stats --no-stream || { echo "⚠️  Failed to fetch docker stats. Falling back to 'docker top'..."; docker top $(PROJECT_NAME); }

# help: docker-top           - Show top-level process info in Docker container
docker-top:
	@echo "🧠  Showing top-level processes in the Docker container..."
	docker top $(PROJECT_NAME)

# help: docker-shell         - Open an interactive shell inside the Docker container
docker-shell:
	@$(MAKE) container-shell CONTAINER_RUNTIME=docker

# =============================================================================
# 🛠️  COMPOSE STACK (Docker Compose v2, podman compose or podman-compose)
# =============================================================================
# help: 🛠️ COMPOSE STACK     - Build / start / stop the multi-service stack
# help: compose-up           - Bring the whole stack up (detached)
# help: compose-restart      - Recreate changed containers, pulling / building as needed
# help: compose-build        - Build (or rebuild) images defined in the compose file
# help: compose-pull         - Pull the latest images only
# help: compose-logs         - Tail logs from all services (Ctrl-C to exit)
# help: compose-ps           - Show container status table
# help: compose-shell        - Open an interactive shell in the "gateway" container
# help: compose-stop         - Gracefully stop the stack (keep containers)
# help: compose-down         - Stop & remove containers (keep named volumes)
# help: compose-rm           - Remove *stopped* containers
# help: compose-clean        - ✨ Down **and** delete named volumes (data-loss ⚠)
# help: compose-validate      - Validate compose file syntax
# help: compose-exec          - Execute command in service (use SERVICE=name CMD='...')
# help: compose-logs-service  - Tail logs from specific service (use SERVICE=name)
# help: compose-restart-service - Restart specific service (use SERVICE=name)
# help: compose-scale         - Scale service to N instances (use SERVICE=name SCALE=N)
# help: compose-up-safe       - Start stack with validation and health check

# ─────────────────────────────────────────────────────────────────────────────
# You may **force** a specific binary by exporting COMPOSE_CMD, e.g.:
#   export COMPOSE_CMD=podman-compose          # classic wrapper
#   export COMPOSE_CMD="podman compose"        # Podman v4/v5 built-in
#   export COMPOSE_CMD="docker compose"        # Docker CLI plugin (v2)
#
# If COMPOSE_CMD is empty, we autodetect in this order:
#   1. docker compose   2. podman compose   3. podman-compose
# ─────────────────────────────────────────────────────────────────────────────

# Define the compose file location
COMPOSE_FILE ?= docker-compose.yml

# Fixed compose command detection
COMPOSE_CMD ?=
ifeq ($(strip $(COMPOSE_CMD)),)
  # Check for docker compose (v2) first
  COMPOSE_CMD := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || true)
  # If not found, check for podman compose
  ifeq ($(strip $(COMPOSE_CMD)),)
	COMPOSE_CMD := $(shell podman compose version >/dev/null 2>&1 && echo "podman compose" || true)
  endif
  # If still not found, check for podman-compose
  ifeq ($(strip $(COMPOSE_CMD)),)
	COMPOSE_CMD := $(shell command -v podman-compose >/dev/null 2>&1 && echo "podman-compose" || echo "docker compose")
  endif
endif

# Alternative: Always default to docker compose unless explicitly overridden
# COMPOSE_CMD ?= docker compose

define COMPOSE
$(COMPOSE_CMD) -f $(COMPOSE_FILE)
endef

.PHONY: compose-up compose-restart compose-build compose-pull \
	compose-logs compose-ps compose-shell compose-stop compose-down \
	compose-rm compose-clean compose-validate compose-exec \
	compose-logs-service compose-restart-service compose-scale compose-up-safe

# Validate compose file
compose-validate:
	@echo "🔍 Validating compose file..."
	@if [ ! -f "$(COMPOSE_FILE)" ]; then \
		echo "❌ Compose file not found: $(COMPOSE_FILE)"; \
		exit 1; \
	fi
	$(COMPOSE) config --quiet
	@echo "✅ Compose file is valid"

compose-up: compose-validate
	@echo "🚀  Using $(COMPOSE_CMD); starting stack..."
	IMAGE_LOCAL=$(call get_image_name) $(COMPOSE) up -d

compose-restart:
	@echo "🔄  Restarting stack..."
	$(COMPOSE) pull
	$(COMPOSE) build
	IMAGE_LOCAL=$(IMAGE_LOCAL) $(COMPOSE) up -d

compose-build:
	IMAGE_LOCAL=$(call get_image_name) $(COMPOSE) build

compose-pull:
	$(COMPOSE) pull

compose-logs:
	$(COMPOSE) logs -f

compose-ps:
	$(COMPOSE) ps

compose-shell:
	$(COMPOSE) exec gateway /bin/sh

compose-stop:
	$(COMPOSE) stop

compose-down:
	$(COMPOSE) down

compose-rm:
	$(COMPOSE) rm -f

# Removes **containers + named volumes** - irreversible!
compose-clean:
	$(COMPOSE) down -v

# Execute in service container
compose-exec:
	@if [ -z "$(SERVICE)" ] || [ -z "$(CMD)" ]; then \
		echo "❌ Usage: make compose-exec SERVICE=gateway CMD='command'"; \
		exit 1; \
	fi
	@echo "🔧 Executing in service $(SERVICE): $(CMD)"
	$(COMPOSE) exec $(SERVICE) $(CMD)

# Service-specific operations
compose-logs-service:
	@test -n "$(SERVICE)" || { echo "Usage: make compose-logs-service SERVICE=gateway"; exit 1; }
	$(COMPOSE) logs -f $(SERVICE)

compose-restart-service:
	@test -n "$(SERVICE)" || { echo "Usage: make compose-restart-service SERVICE=gateway"; exit 1; }
	$(COMPOSE) restart $(SERVICE)

compose-scale:
	@test -n "$(SERVICE)" && test -n "$(SCALE)" || { \
		echo "Usage: make compose-scale SERVICE=worker SCALE=3"; exit 1; }
	$(COMPOSE) up -d --scale $(SERVICE)=$(SCALE)

# Compose with validation and health check
compose-up-safe: compose-validate compose-up
	@echo "⏳ Waiting for services to be healthy..."
	@sleep 5
	@$(COMPOSE) ps
	@echo "✅ Stack started safely"

# =============================================================================
# ☁️ IBM CLOUD CODE ENGINE
# =============================================================================
# help: ☁️ IBM CLOUD CODE ENGINE
# help: ibmcloud-check-env          - Verify all required IBM Cloud env vars are set
# help: ibmcloud-cli-install        - Auto-install IBM Cloud CLI + required plugins (OS auto-detected)
# help: ibmcloud-login              - Login to IBM Cloud CLI using IBMCLOUD_API_KEY (--sso)
# help: ibmcloud-ce-login           - Set Code Engine target project and region
# help: ibmcloud-list-containers    - List deployed Code Engine apps
# help: ibmcloud-tag                - Tag container image for IBM Container Registry
# help: ibmcloud-push               - Push image to IBM Container Registry
# help: ibmcloud-deploy             - Deploy (or update) container image in Code Engine
# help: ibmcloud-ce-logs            - Stream logs for the deployed application
# help: ibmcloud-ce-status          - Get deployment status
# help: ibmcloud-ce-rm              - Delete the Code Engine application

.PHONY: ibmcloud-check-env ibmcloud-cli-install ibmcloud-login ibmcloud-ce-login \
	ibmcloud-list-containers ibmcloud-tag ibmcloud-push ibmcloud-deploy \
	ibmcloud-ce-logs ibmcloud-ce-status ibmcloud-ce-rm

# ─────────────────────────────────────────────────────────────────────────────
# 📦  Load environment file with IBM Cloud Code Engine configuration
#     - .env.ce   - IBM Cloud / Code Engine deployment vars
# ─────────────────────────────────────────────────────────────────────────────
-include .env.ce

# Export only the IBM-specific variables (those starting with IBMCLOUD_)
export $(shell grep -E '^IBMCLOUD_' .env.ce 2>/dev/null | sed -E 's/^\s*([^=]+)=.*/\1/')

## Optional / defaulted ENV variables:
IBMCLOUD_CPU            ?= 1      # vCPU allocation for Code Engine app
IBMCLOUD_MEMORY         ?= 4G     # Memory allocation for Code Engine app
IBMCLOUD_REGISTRY_SECRET ?= $(IBMCLOUD_PROJECT)-registry-secret

## Required ENV variables:
# IBMCLOUD_REGION              = IBM Cloud region (e.g. us-south)
# IBMCLOUD_PROJECT             = Code Engine project name
# IBMCLOUD_RESOURCE_GROUP      = IBM Cloud resource group name (e.g. default)
# IBMCLOUD_CODE_ENGINE_APP     = Code Engine app name
# IBMCLOUD_IMAGE_NAME          = Full image path (e.g. us.icr.io/namespace/app:tag)
# IBMCLOUD_IMG_PROD            = Local container image name
# IBMCLOUD_API_KEY             = IBM Cloud IAM API key (optional, use --sso if not set)

ibmcloud-check-env:
	@test -f .env.ce || { \
		echo "❌ Missing required .env.ce file!"; \
		exit 1; \
	}
	@bash -eu -o pipefail -c '\
		echo "🔍  Verifying required IBM Cloud variables (.env.ce)..."; \
		missing=0; \
		for var in IBMCLOUD_REGION IBMCLOUD_PROJECT IBMCLOUD_RESOURCE_GROUP \
		           IBMCLOUD_CODE_ENGINE_APP IBMCLOUD_IMAGE_NAME IBMCLOUD_IMG_PROD \
		           IBMCLOUD_CPU IBMCLOUD_MEMORY IBMCLOUD_REGISTRY_SECRET; do \
			if [ -z "$${!var}" ]; then \
				echo "❌  Missing: $$var"; \
				missing=1; \
			fi; \
		done; \
		if [ -z "$$IBMCLOUD_API_KEY" ]; then \
			echo "⚠️   IBMCLOUD_API_KEY not set - interactive SSO login will be used"; \
		else \
			echo "🔑  IBMCLOUD_API_KEY found"; \
		fi; \
		if [ "$$missing" -eq 0 ]; then \
			echo "✅  All required variables present in .env.ce"; \
		else \
			echo "💡  Add the missing keys to .env.ce before continuing."; \
			exit 1; \
		fi'

ibmcloud-cli-install:
	@echo "☁️  Detecting OS and installing IBM Cloud CLI..."
	@if grep -qi microsoft /proc/version 2>/dev/null; then \
		echo "🔧 Detected WSL2"; \
		curl -fsSL https://clis.cloud.ibm.com/install/linux | sh; \
	elif [ "$$(uname)" = "Darwin" ]; then \
		echo "🍏 Detected macOS"; \
		curl -fsSL https://clis.cloud.ibm.com/install/osx | sh; \
	elif [ "$$(uname)" = "Linux" ]; then \
		echo "🐧 Detected Linux"; \
		curl -fsSL https://clis.cloud.ibm.com/install/linux | sh; \
	elif command -v powershell.exe >/dev/null; then \
		echo "🪟 Detected Windows"; \
		powershell.exe -Command "iex (New-Object Net.WebClient).DownloadString('https://clis.cloud.ibm.com/install/powershell')"; \
	else \
		echo "❌ Unsupported OS"; exit 1; \
	fi
	@echo "✅ CLI installed. Installing required plugins..."
	@ibmcloud plugin install container-registry -f
	@ibmcloud plugin install code-engine -f
	@ibmcloud --version

ibmcloud-login:
	@echo "🔐 Starting IBM Cloud login..."
	@echo "──────────────────────────────────────────────"
	@echo "👤  User:               $(USER)"
	@echo "📍  Region:             $(IBMCLOUD_REGION)"
	@echo "🧵  Resource Group:     $(IBMCLOUD_RESOURCE_GROUP)"
	@if [ -n "$(IBMCLOUD_API_KEY)" ]; then \
		echo "🔑  Auth Mode:          API Key (with --sso)"; \
	else \
		echo "🔑  Auth Mode:          Interactive (--sso)"; \
	fi
	@echo "──────────────────────────────────────────────"
	@if [ -z "$(IBMCLOUD_REGION)" ] || [ -z "$(IBMCLOUD_RESOURCE_GROUP)" ]; then \
		echo "❌ IBMCLOUD_REGION or IBMCLOUD_RESOURCE_GROUP is missing. Aborting."; \
		exit 1; \
	fi
	@if [ -n "$(IBMCLOUD_API_KEY)" ]; then \
		ibmcloud login --apikey "$(IBMCLOUD_API_KEY)" --sso -r "$(IBMCLOUD_REGION)" -g "$(IBMCLOUD_RESOURCE_GROUP)"; \
	else \
		ibmcloud login --sso -r "$(IBMCLOUD_REGION)" -g "$(IBMCLOUD_RESOURCE_GROUP)"; \
	fi
	@echo "🎯 Targeting region and resource group..."
	@ibmcloud target -r "$(IBMCLOUD_REGION)" -g "$(IBMCLOUD_RESOURCE_GROUP)"
	@ibmcloud target

ibmcloud-ce-login:
	@echo "🎯 Targeting Code Engine project '$(IBMCLOUD_PROJECT)' in region '$(IBMCLOUD_REGION)'..."
	@ibmcloud ce project select --name "$(IBMCLOUD_PROJECT)"

ibmcloud-list-containers:
	@echo "📦 Listing Code Engine images"
	ibmcloud cr images
	@echo "📦 Listing Code Engine applications..."
	@ibmcloud ce application list

ibmcloud-tag:
	@echo "🏷️  Tagging image $(IBMCLOUD_IMG_PROD) → $(IBMCLOUD_IMAGE_NAME)"
	podman tag $(IBMCLOUD_IMG_PROD) $(IBMCLOUD_IMAGE_NAME)
	podman images | head -3

ibmcloud-push:
	@echo "📤 Logging into IBM Container Registry and pushing image..."
	@ibmcloud cr login
	podman push $(IBMCLOUD_IMAGE_NAME)

ibmcloud-deploy:
	@echo "🚀 Deploying image to Code Engine as '$(IBMCLOUD_CODE_ENGINE_APP)' using registry secret $(IBMCLOUD_REGISTRY_SECRET)..."
	@if ibmcloud ce application get --name $(IBMCLOUD_CODE_ENGINE_APP) > /dev/null 2>&1; then \
		echo "🔁 Updating existing app..."; \
		ibmcloud ce application update --name $(IBMCLOUD_CODE_ENGINE_APP) \
			--image $(IBMCLOUD_IMAGE_NAME) \
			--cpu $(IBMCLOUD_CPU) --memory $(IBMCLOUD_MEMORY) \
			--registry-secret $(IBMCLOUD_REGISTRY_SECRET); \
	else \
		echo "🆕 Creating new app..."; \
		ibmcloud ce application create --name $(IBMCLOUD_CODE_ENGINE_APP) \
			--image $(IBMCLOUD_IMAGE_NAME) \
			--cpu $(IBMCLOUD_CPU) --memory $(IBMCLOUD_MEMORY) \
			--port 4444 \
			--registry-secret $(IBMCLOUD_REGISTRY_SECRET); \
	fi

ibmcloud-ce-logs:
	@echo "📜 Streaming logs for '$(IBMCLOUD_CODE_ENGINE_APP)'..."
	@ibmcloud ce application logs --name $(IBMCLOUD_CODE_ENGINE_APP) --follow

ibmcloud-ce-status:
	@echo "📈 Application status for '$(IBMCLOUD_CODE_ENGINE_APP)'..."
	@ibmcloud ce application get --name $(IBMCLOUD_CODE_ENGINE_APP)

ibmcloud-ce-rm:
	@echo "🗑️  Deleting Code Engine app: $(IBMCLOUD_CODE_ENGINE_APP)..."
	@ibmcloud ce application delete --name $(IBMCLOUD_CODE_ENGINE_APP) -f


# =============================================================================
# 🧪 MINIKUBE LOCAL CLUSTER
# =============================================================================
# A self-contained block with sensible defaults, overridable via the CLI.
# App is accessible after: kubectl port-forward svc/mcp-context-forge 8080:80
# Examples:
#   make minikube-start MINIKUBE_DRIVER=podman
#   make minikube-image-load TAG=v0.1.2
#
#   # Push via the internal registry (registry addon):
#   # 1️⃣ Discover the randomized host-port (docker driver only):
#   REG_URL=$(shell minikube -p $(MINIKUBE_PROFILE) service registry -n kube-system --url)
#   # 2️⃣ Tag & push:
#   docker build -t $${REG_URL}/$(PROJECT_NAME):dev .
#   docker push $${REG_URL}/$(PROJECT_NAME):dev
#   # 3️⃣ Reference in manifests:
#   image: $${REG_URL}/$(PROJECT_NAME):dev
#
#   # If you built a prod image via:
#   #     make docker-prod   # ⇒ mcpgateway/mcpgateway:latest
#   # Tag & push it into Minikube:
#   docker tag mcpgateway/mcpgateway:latest $${REG_URL}/mcpgateway:latest
#   docker push $${REG_URL}/mcpgateway:latest
#   # Override the Make target variable or patch your Helm values:
#   make minikube-k8s-apply IMAGE=$${REG_URL}/mcpgateway:latest
# -----------------------------------------------------------------------------

# ▸ Tunables (export or pass on the command line)
MINIKUBE_PROFILE ?= mcpgw          # Profile/cluster name
MINIKUBE_DRIVER  ?= docker         # docker | podman | hyperkit | virtualbox ...
MINIKUBE_CPUS    ?= 4              # vCPUs to allocate
MINIKUBE_MEMORY  ?= 6g             # RAM (supports m / g suffix)
# Enabled addons - tweak to suit your workflow (`minikube addons list`).
# - ingress / ingress-dns      - Ingress controller + CoreDNS wildcard hostnames
# - metrics-server             - HPA / kubectl top
# - dashboard                  - Web UI (make minikube-dashboard)
# - registry                   - Local Docker registry, *dynamic* host-port
# - registry-aliases           - Adds handy DNS names inside the cluster
MINIKUBE_ADDONS  ?= ingress ingress-dns metrics-server dashboard registry registry-aliases
# OCI image tag to preload into the cluster.
# - By default we point to the *local* image built via `make docker-prod`, e.g.
#   mcpgateway/mcpgateway:latest.  Override with IMAGE=<repo:tag> to use a
#   remote registry (e.g. ghcr.io/ibm/mcp-context-forge:v0.4.0).
TAG              ?= latest         # override with TAG=<ver>
IMAGE            ?= $(IMG):$(TAG)  # or IMAGE=ghcr.io/ibm/mcp-context-forge:$(TAG)

# -----------------------------------------------------------------------------
# 🆘  HELP TARGETS (parsed by `make help`)
# -----------------------------------------------------------------------------
# help: 🧪 MINIKUBE LOCAL CLUSTER
# help: minikube-install        - Install Minikube + kubectl (macOS / Linux / Windows)
# help: minikube-start          - Start cluster + enable $(MINIKUBE_ADDONS)
# help: minikube-stop           - Stop the cluster
# help: minikube-delete         - Delete the cluster completely
# help: minikube-tunnel         - Run "minikube tunnel" (LoadBalancer) in foreground
# help: minikube-port-forward   - Run kubectl port-forward -n mcp-private svc/mcp-stack-mcpgateway 8080:80
# help: minikube-dashboard      - Print & (best-effort) open the Kubernetes dashboard URL
# help: minikube-image-load     - Load $(IMAGE) into Minikube container runtime
# help: minikube-k8s-apply      - Apply manifests from deployment/k8s/ - access with `kubectl port-forward svc/mcp-context-forge 8080:80`
# help: minikube-status         - Cluster + addon health overview
# help: minikube-context        - Switch kubectl context to Minikube
# help: minikube-ssh            - SSH into the Minikube VM
# help: minikube-reset          - 🚨 delete ➜ start ➜ apply ➜ status (idempotent dev helper)
# help: minikube-registry-url 	- Echo the dynamic registry URL (e.g. http://localhost:32790)

.PHONY: minikube-install helm-install minikube-start minikube-stop minikube-delete \
	minikube-tunnel minikube-dashboard minikube-image-load minikube-k8s-apply \
	minikube-status minikube-context minikube-ssh minikube-reset minikube-registry-url \
	minikube-port-forward

# -----------------------------------------------------------------------------
# 🚀  INSTALLATION HELPERS
# -----------------------------------------------------------------------------
minikube-install:
	@echo "💻 Detecting OS and installing Minikube + kubectl..."
	@if [ "$(shell uname)" = "Darwin" ]; then \
	  brew install minikube kubernetes-cli; \
	elif [ "$(shell uname)" = "Linux" ]; then \
	  curl -Lo minikube https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 && \
	  chmod +x minikube && sudo mv minikube /usr/local/bin/; \
	  curl -Lo kubectl "https://dl.k8s.io/release/$$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
	  chmod +x kubectl && sudo mv kubectl /usr/local/bin/; \
	elif command -v powershell.exe >/dev/null; then \
	  powershell.exe -NoProfile -Command "choco install -y minikube kubernetes-cli"; \
	else \
	  echo "❌ Unsupported OS. Install manually ↗"; exit 1; \
	fi

# -----------------------------------------------------------------------------
# ⏯  LIFECYCLE COMMANDS
# -----------------------------------------------------------------------------
minikube-start:
	@echo "🚀 Starting Minikube profile '$(MINIKUBE_PROFILE)' (driver=$(MINIKUBE_DRIVER)) ..."
	minikube start -p $(MINIKUBE_PROFILE) \
	  --driver=$(MINIKUBE_DRIVER) \
	  --cpus=$(MINIKUBE_CPUS) --memory=$(MINIKUBE_MEMORY)
	@echo "🔌 Enabling addons: $(MINIKUBE_ADDONS)"
	@for addon in $(MINIKUBE_ADDONS); do \
	  minikube addons enable $$addon -p $(MINIKUBE_PROFILE); \
	done

minikube-stop:
	@echo "🛑 Stopping Minikube ..."
	minikube stop -p $(MINIKUBE_PROFILE)

minikube-delete:
	@echo "🗑 Deleting Minikube profile '$(MINIKUBE_PROFILE)' ..."
	minikube delete -p $(MINIKUBE_PROFILE)

# -----------------------------------------------------------------------------
# 🛠  UTILITIES
# -----------------------------------------------------------------------------
minikube-tunnel:
	@echo "🌐 Starting minikube tunnel (Ctrl+C to quit) ..."
	minikube -p $(MINIKUBE_PROFILE) tunnel

minikube-port-forward:
	@echo "🔌 Forwarding http://localhost:8080 → svc/mcp-stack-mcpgateway:80 in namespace mcp-private  (Ctrl+C to stop)..."
	kubectl port-forward -n mcp-private svc/mcp-stack-mcpgateway 8080:80

minikube-dashboard:
	@echo "📊 Fetching dashboard URL ..."
	@minikube dashboard -p $(MINIKUBE_PROFILE) --url | { \
	  read url; \
	  echo "🔗 Dashboard: $$url"; \
	  ( command -v xdg-open >/dev/null && xdg-open $$url >/dev/null 2>&1 ) || \
	  ( command -v open     >/dev/null && open $$url     >/dev/null 2>&1 ) || true; \
	}

minikube-context:
	@echo "🎯 Switching kubectl context to Minikube ..."
	kubectl config use-context minikube

minikube-ssh:
	@echo "🔧 Connecting to Minikube VM (exit with Ctrl+D) ..."
	minikube ssh -p $(MINIKUBE_PROFILE)

# -----------------------------------------------------------------------------
# 📦  IMAGE & MANIFEST HANDLING
# -----------------------------------------------------------------------------
minikube-image-load:
	@echo "📦 Loading $(IMAGE) into Minikube ..."
	@if ! docker image inspect $(IMAGE) >/dev/null 2>&1; then \
	  echo "❌ $(IMAGE) not found locally. Build or pull it first."; exit 1; \
	fi
	minikube image load $(IMAGE) -p $(MINIKUBE_PROFILE)

minikube-k8s-apply:
	@echo "🧩 Applying k8s manifests in ./k8s ..."
	@kubectl apply -f deployment/k8s/ --recursive

# -----------------------------------------------------------------------------
# 🔍  Utility: print the current registry URL (host-port) - works after cluster
#             + registry addon are up.
# -----------------------------------------------------------------------------
minikube-registry-url:
	@echo "📦 Internal registry URL:" && \
	minikube -p $(MINIKUBE_PROFILE) service registry -n kube-system --url || \
	echo "⚠️  Registry addon not ready - run make minikube-start first."

# -----------------------------------------------------------------------------
# 📊  INSPECTION & RESET
# -----------------------------------------------------------------------------
minikube-status:
	@echo "📊 Minikube cluster status:" && minikube status -p $(MINIKUBE_PROFILE)
	@echo "\n📦 Addon status:" && minikube addons list | grep -E "$(subst $(space),|,$(MINIKUBE_ADDONS))"
	@echo "\n🚦 Ingress controller:" && kubectl get pods -n ingress-nginx -o wide || true
	@echo "\n🔍 Dashboard:" && kubectl get pods -n kubernetes-dashboard -o wide || true
	@echo "\n🧩 Services:" && kubectl get svc || true
	@echo "\n🌐 Ingress:" && kubectl get ingress || true

minikube-reset: minikube-delete minikube-start minikube-image-load minikube-k8s-apply minikube-status
	@echo "✅ Minikube reset complete!"

# -----------------------------------------------------------------------------
# 🛠️ HELM CHART TASKS
# -----------------------------------------------------------------------------
# help: 🛠️ HELM CHART TASKS
# help: helm-install         - Install Helm 3 CLI
# help: helm-lint            - Lint the Helm chart (static analysis)
# help: helm-package         - Package the chart into dist/ as mcp-stack-<ver>.tgz
# help: helm-deploy          - Upgrade/Install chart into Minikube (profile mcpgw)
# help: helm-delete          - Uninstall the chart release from Minikube
# -----------------------------------------------------------------------------

.PHONY: helm-install helm-lint helm-package helm-deploy helm-delete

CHART_DIR      ?= charts/mcp-stack
RELEASE_NAME   ?= mcp-stack
NAMESPACE      ?= mcp
VALUES         ?= $(CHART_DIR)/values.yaml

helm-install:
	@echo "📦 Installing Helm CLI..."
	@if [ "$(shell uname)" = "Darwin" ]; then \
	  brew install helm; \
	elif [ "$(shell uname)" = "Linux" ]; then \
	  curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash; \
	elif command -v powershell.exe >/dev/null; then \
	  powershell.exe -NoProfile -Command "choco install -y kubernetes-helm"; \
	else \
	  echo "❌ Unsupported OS. Install Helm manually ↗"; exit 1; \
	fi

helm-lint:
	@echo "🔍 Helm lint..."
	helm lint $(CHART_DIR)

helm-package:
	@echo "📦 Packaging chart into ./dist ..."
	@mkdir -p dist
	helm package $(CHART_DIR) -d dist

helm-deploy: helm-lint
	@echo "🚀 Deploying $(RELEASE_NAME) into Minikube (ns=$(NAMESPACE))..."
	helm upgrade --install $(RELEASE_NAME) $(CHART_DIR) \
	  --namespace $(NAMESPACE) --create-namespace \
	  -f $(VALUES) \
	  --wait
	@echo "✅ Deployed."
	@echo "\n📊 Release status:"
	helm status $(RELEASE_NAME) -n $(NAMESPACE)
	@echo "\n📦 Pods:"
	kubectl get pods -n $(NAMESPACE)

helm-delete:
	@echo "🗑  Deleting $(RELEASE_NAME) release..."
	helm uninstall $(RELEASE_NAME) -n $(NAMESPACE) || true


# =============================================================================
# 🚢 ARGO CD - GITOPS
# TODO: change default to custom namespace (e.g. mcp-gitops)
# =============================================================================
# help: 🚢 ARGO CD - GITOPS
# help: argocd-cli-install   - Install Argo CD CLI locally
# help: argocd-install       - Install Argo CD into Minikube (ns=$(ARGOCD_NS))
# help: argocd-password      - Echo initial admin password
# help: argocd-forward       - Port-forward API/UI to http://localhost:$(ARGOCD_PORT)
# help: argocd-login         - Log in to Argo CD CLI (requires argocd-forward)
# help: argocd-app-bootstrap - Create & auto-sync $(ARGOCD_APP) from $(GIT_REPO)/$(GIT_PATH)
# help: argocd-app-sync      - Manual re-sync of the application
# -----------------------------------------------------------------------------

ARGOCD_NS   ?= argocd
ARGOCD_PORT ?= 8083
ARGOCD_APP  ?= mcp-gateway
GIT_REPO    ?= https://github.com/ibm/mcp-context-forge.git
GIT_PATH    ?= k8s

.PHONY: argocd-cli-install argocd-install argocd-password argocd-forward \
	argocd-login argocd-app-bootstrap argocd-app-sync

argocd-cli-install:
	@echo "🔧 Installing Argo CD CLI..."
	@if command -v argocd >/dev/null 2>&1; then echo "✅ argocd already present"; \
	elif [ "$$(uname)" = "Darwin" ];  then brew install argocd; \
	elif [ "$$(uname)" = "Linux" ];   then curl -sSL -o /tmp/argocd \
	     https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64 && \
	     sudo install -m 555 /tmp/argocd /usr/local/bin/argocd; \
	else echo "❌ Unsupported OS - install argocd manually"; exit 1; fi

argocd-install:
	@echo "🚀 Installing Argo CD into Minikube..."
	kubectl create namespace $(ARGOCD_NS) --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -n $(ARGOCD_NS) \
	  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
	@echo "⏳ Waiting for Argo CD server pod..."
	kubectl -n $(ARGOCD_NS) rollout status deploy/argocd-server

argocd-password:
	@kubectl -n $(ARGOCD_NS) get secret argocd-initial-admin-secret \
	  -o jsonpath='{.data.password}' | base64 -d ; echo

argocd-forward:
	@echo "🌐 Port-forward http://localhost:$(ARGOCD_PORT) → svc/argocd-server:443 (Ctrl-C to stop)..."
	kubectl -n $(ARGOCD_NS) port-forward svc/argocd-server $(ARGOCD_PORT):443

argocd-login: argocd-cli-install
	@echo "🔐 Logging into Argo CD CLI..."
	@PASS=$$(kubectl -n $(ARGOCD_NS) get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d); \
	argocd login localhost:$(ARGOCD_PORT) --username admin --password $$PASS --insecure

argocd-app-bootstrap:
	@echo "🚀 Creating Argo CD application $(ARGOCD_APP)..."
	-argocd app create $(ARGOCD_APP) \
	    --repo $(GIT_REPO) \
	    --path $(GIT_PATH) \
	    --dest-server https://kubernetes.default.svc \
	    --dest-namespace default \
	    --sync-policy automated \
	    --revision HEAD || true
	argocd app sync $(ARGOCD_APP)

argocd-app-sync:
	@echo "🔄  Syncing Argo CD application $(ARGOCD_APP)..."
	argocd app sync $(ARGOCD_APP)

# =============================================================================
# 🏠 LOCAL PYPI SERVER
# Currently blocked by: https://github.com/pypiserver/pypiserver/issues/630
# =============================================================================
# help: 🏠 LOCAL PYPI SERVER
# help: local-pypi-install     - Install pypiserver for local testing
# help: local-pypi-start       - Start local PyPI server on :8085 (no auth)
# help: local-pypi-start-auth  - Start local PyPI server with basic auth (admin/admin)
# help: local-pypi-stop        - Stop local PyPI server
# help: local-pypi-upload      - Upload existing package to local PyPI (no auth)
# help: local-pypi-upload-auth - Upload existing package to local PyPI (with auth)
# help: local-pypi-test        - Install package from local PyPI
# help: local-pypi-clean       - Full cycle: build → upload → install locally

.PHONY: local-pypi-install local-pypi-start local-pypi-start-auth local-pypi-stop local-pypi-upload \
	local-pypi-upload-auth local-pypi-test local-pypi-clean

LOCAL_PYPI_DIR := $(HOME)/local-pypi
LOCAL_PYPI_URL := http://localhost:8085
LOCAL_PYPI_PID := /tmp/pypiserver.pid
LOCAL_PYPI_AUTH := $(LOCAL_PYPI_DIR)/.htpasswd

local-pypi-install:
	@echo "📦  Installing pypiserver..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && pip install 'pypiserver>=2.3.0' passlib"
	@mkdir -p $(LOCAL_PYPI_DIR)

local-pypi-start: local-pypi-install local-pypi-stop
	@echo "🚀  Starting local PyPI server on http://localhost:8085..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	export PYPISERVER_BOTTLE_MEMFILE_MAX_OVERRIDE_BYTES=10485760 && \
	pypi-server run -p 8085 -a . -P . $(LOCAL_PYPI_DIR) --hash-algo=sha256 & echo \$! > $(LOCAL_PYPI_PID)"
	@sleep 2
	@echo "✅  Local PyPI server started at http://localhost:8085"
	@echo "📂  Package directory: $(LOCAL_PYPI_DIR)"
	@echo "🔓  No authentication required (open mode)"

local-pypi-start-auth: local-pypi-install local-pypi-stop
	@echo "🚀  Starting local PyPI server with authentication on $(LOCAL_PYPI_URL)..."
	@echo "🔐  Creating htpasswd file (admin/admin)..."
	@mkdir -p $(LOCAL_PYPI_DIR)
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	python3 -c \"import passlib.hash; print('admin:' + passlib.hash.sha256_crypt.hash('admin'))\" > $(LOCAL_PYPI_AUTH)"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	export PYPISERVER_BOTTLE_MEMFILE_MAX_OVERRIDE_BYTES=10485760 && \
	pypi-server run -p 8085 -P $(LOCAL_PYPI_AUTH) -a update,download,list $(LOCAL_PYPI_DIR) --hash-algo=sha256 & echo \$! > $(LOCAL_PYPI_PID)"
	@sleep 2
	@echo "✅  Local PyPI server started at $(LOCAL_PYPI_URL)"
	@echo "📂  Package directory: $(LOCAL_PYPI_DIR)"
	@echo "🔐  Username: admin, Password: admin"

local-pypi-stop:
	@echo "🛑  Stopping local PyPI server..."
	@if [ -f $(LOCAL_PYPI_PID) ]; then \
		kill $(cat $(LOCAL_PYPI_PID)) 2>/dev/null || true; \
		rm -f $(LOCAL_PYPI_PID); \
	fi
	@# Kill any pypi-server processes on ports 8084 and 8085
	@pkill -f "pypi-server.*808[45]" 2>/dev/null || true
	@# Wait a moment for cleanup
	@sleep 1
	@if lsof -i :8084 >/dev/null 2>&1; then \
		echo "⚠️   Port 8084 still in use, force killing..."; \
		sudo fuser -k 8084/tcp 2>/dev/null || true; \
	fi
	@if lsof -i :8085 >/dev/null 2>&1; then \
		echo "⚠️   Port 8085 still in use, force killing..."; \
		sudo fuser -k 8085/tcp 2>/dev/null || true; \
	fi
	@sleep 1
	@echo "✅  Server stopped"

local-pypi-upload:
	@echo "📤  Uploading existing package to local PyPI (no auth)..."
	@if [ ! -d "dist" ] || [ -z "$$(ls -A dist/ 2>/dev/null)" ]; then \
		echo "❌  No dist/ directory or files found. Run 'make dist' first."; \
		exit 1; \
	fi
	@if ! curl -s $(LOCAL_PYPI_URL) >/dev/null 2>&1; then \
		echo "❌  Local PyPI server not running on port 8085. Run 'make local-pypi-start' first."; \
		exit 1; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	twine upload --verbose --repository-url $(LOCAL_PYPI_URL) --skip-existing dist/*"
	@echo "✅  Package uploaded to local PyPI"
	@echo "🌐  Browse packages: $(LOCAL_PYPI_URL)"

local-pypi-upload-auth:
	@echo "📤  Uploading existing package to local PyPI with auth..."
	@if [ ! -d "dist" ] || [ -z "$$(ls -A dist/ 2>/dev/null)" ]; then \
		echo "❌  No dist/ directory or files found. Run 'make dist' first."; \
		exit 1; \
	fi
	@if ! curl -s $(LOCAL_PYPI_URL) >/dev/null 2>&1; then \
		echo "❌  Local PyPI server not running on port 8085. Run 'make local-pypi-start-auth' first."; \
		exit 1; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	twine upload --verbose --repository-url $(LOCAL_PYPI_URL) --username admin --password admin --skip-existing dist/*"
	@echo "✅  Package uploaded to local PyPI"
	@echo "🌐  Browse packages: $(LOCAL_PYPI_URL)"

local-pypi-test:
	@echo "📥  Installing from local PyPI..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	pip install --index-url $(LOCAL_PYPI_URL)/simple/ \
	            --extra-index-url https://pypi.org/simple/ \
	            --force-reinstall $(PROJECT_NAME)"
	@echo "✅  Installed from local PyPI"

local-pypi-clean: clean dist local-pypi-start-auth local-pypi-upload-auth local-pypi-test
	@echo "🎉  Full local PyPI cycle complete!"
	@echo "📊  Package info:"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && pip show $(PROJECT_NAME)"

# Convenience target to restart server
local-pypi-restart: local-pypi-stop local-pypi-start

local-pypi-restart-auth: local-pypi-stop local-pypi-start-auth

# Show server status
local-pypi-status:
	@echo "🔍  Local PyPI server status:"
	@if [ -f $(LOCAL_PYPI_PID) ] && kill -0 $(cat $(LOCAL_PYPI_PID)) 2>/dev/null; then \
		echo "✅  Server running (PID: $(cat $(LOCAL_PYPI_PID)))"; \
		if curl -s $(LOCAL_PYPI_URL) >/dev/null 2>&1; then \
			echo "🌐  Server on port 8085: $(LOCAL_PYPI_URL)"; \
		fi; \
		echo "📂  Directory: $(LOCAL_PYPI_DIR)"; \
	else \
		echo "❌  Server not running"; \
	fi

# Debug target - run server in foreground with verbose logging
local-pypi-debug:
	@echo "🐛  Running local PyPI server in debug mode (Ctrl+C to stop)..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	export PYPISERVER_BOTTLE_MEMFILE_MAX_OVERRIDE_BYTES=10485760 && \
	export BOTTLE_CHILD=true && \
	pypi-server run -p 8085 --disable-fallback -a . -P . --server=auto $(LOCAL_PYPI_DIR) -v"


# =============================================================================
# 🏠 LOCAL DEVPI SERVER
# TODO: log in background, better cleanup/delete logic
# =============================================================================
# help: 🏠 LOCAL DEVPI SERVER
# help: devpi-install        - Install devpi server and client
# help: devpi-init           - Initialize devpi server (first time only)
# help: devpi-start          - Start devpi server
# help: devpi-stop           - Stop devpi server
# help: devpi-setup-user     - Create user and dev index
# help: devpi-upload         - Upload existing package to devpi
# help: devpi-test           - Install package from devpi
# help: devpi-clean          - Full cycle: build → upload → install locally
# help: devpi-status         - Show devpi server status
# help: devpi-web            - Open devpi web interface
# help: devpi-delete         - Delete mcp-contextforge-gateway==<ver> from devpi index


.PHONY: devpi-install devpi-init devpi-start devpi-stop devpi-setup-user devpi-upload \
	devpi-delete devpi-test devpi-clean devpi-status devpi-web devpi-restart

DEVPI_HOST := localhost
DEVPI_PORT := 3141
DEVPI_URL := http://$(DEVPI_HOST):$(DEVPI_PORT)
DEVPI_USER := $(USER)
DEVPI_PASS := dev123
DEVPI_INDEX := $(DEVPI_USER)/dev
DEVPI_DATA_DIR := $(HOME)/.devpi
DEVPI_PID := /tmp/devpi-server.pid

devpi-install:
	@echo "📦  Installing devpi server and client..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	pip install devpi-server devpi-client devpi-web"
	@echo "✅  DevPi installed"

devpi-init: devpi-install
	@echo "🔧  Initializing devpi server (first time setup)..."
	@if [ -d "$(DEVPI_DATA_DIR)/server" ] && [ -f "$(DEVPI_DATA_DIR)/server/.serverversion" ]; then \
		echo "⚠️   DevPi already initialized at $(DEVPI_DATA_DIR)"; \
	else \
		mkdir -p $(DEVPI_DATA_DIR)/server; \
		/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		devpi-init --serverdir=$(DEVPI_DATA_DIR)/server"; \
		echo "✅  DevPi server initialized at $(DEVPI_DATA_DIR)/server"; \
	fi

devpi-start: devpi-init devpi-stop
	@echo "🚀  Starting devpi server on $(DEVPI_URL)..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	devpi-server --serverdir=$(DEVPI_DATA_DIR)/server \
	             --host=$(DEVPI_HOST) \
	             --port=$(DEVPI_PORT) &"
	@# Wait for server to start and get the PID
	@sleep 3
	@ps aux | grep "[d]evpi-server" | grep "$(DEVPI_PORT)" | awk '{print $2}' > $(DEVPI_PID) || true
	@# Wait a bit more and test if server is responding
	@sleep 2
	@if curl -s $(DEVPI_URL) >/dev/null 2>&1; then \
		if [ -s $(DEVPI_PID) ]; then \
			echo "✅  DevPi server started at $(DEVPI_URL)"; \
			echo "📊  PID: $(cat $(DEVPI_PID))"; \
		else \
			echo "✅  DevPi server started at $(DEVPI_URL)"; \
		fi; \
		echo "🌐  Web interface: $(DEVPI_URL)"; \
		echo "📂  Data directory: $(DEVPI_DATA_DIR)"; \
	else \
		echo "❌  Failed to start devpi server or server not responding"; \
		echo "🔍  Check logs with: make devpi-logs"; \
		exit 1; \
	fi

devpi-stop:
	@echo "🛑  Stopping devpi server..."
	@# Kill process by PID if exists
	@if [ -f $(DEVPI_PID) ] && [ -s $(DEVPI_PID) ]; then \
		pid=$(cat $(DEVPI_PID)); \
		if kill -0 $pid 2>/dev/null; then \
			echo "🔄  Stopping devpi server (PID: $pid)"; \
			kill $pid 2>/dev/null || true; \
			sleep 2; \
			kill -9 $pid 2>/dev/null || true; \
		fi; \
		rm -f $(DEVPI_PID); \
	fi
	@# Kill any remaining devpi-server processes
	@pids=$(pgrep -f "devpi-server.*$(DEVPI_PORT)" 2>/dev/null || true); \
	if [ -n "$pids" ]; then \
		echo "🔄  Killing remaining devpi processes: $pids"; \
		echo "$pids" | xargs $(XARGS_FLAGS) kill 2>/dev/null || true; \
		sleep 1; \
		echo "$pids" | xargs $(XARGS_FLAGS) kill -9 2>/dev/null || true; \
	fi
	@# Force kill anything using the port
	@if lsof -ti :$(DEVPI_PORT) >/dev/null 2>&1; then \
		echo "⚠️   Port $(DEVPI_PORT) still in use, force killing..."; \
		lsof -ti :$(DEVPI_PORT) | xargs $(XARGS_FLAGS) kill -9 2>/dev/null || true; \
		sleep 1; \
	fi
	@echo "✅  DevPi server stopped"

devpi-setup-user: devpi-start
	@echo "👤  Setting up devpi user and index..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	devpi use $(DEVPI_URL) && \
	(devpi user -c $(DEVPI_USER) password=$(DEVPI_PASS) email=$(DEVPI_USER)@localhost.local 2>/dev/null || \
	 echo 'User $(DEVPI_USER) already exists') && \
	devpi login $(DEVPI_USER) --password=$(DEVPI_PASS) && \
	(devpi index -c dev bases=root/pypi volatile=True 2>/dev/null || \
	 echo 'Index dev already exists') && \
	devpi use $(DEVPI_INDEX)"
	@echo "✅  User '$(DEVPI_USER)' and index 'dev' configured"
	@echo "📝  Login: $(DEVPI_USER) / $(DEVPI_PASS)"
	@echo "📍  Using index: $(DEVPI_INDEX)"

devpi-upload: dist devpi-setup-user		## Build wheel/sdist, then upload
	@echo "📤  Uploading existing package to devpi..."
	@if [ ! -d "dist" ] || [ -z "$$(ls -A dist/ 2>/dev/null)" ]; then \
		echo "❌  No dist/ directory or files found. Run 'make dist' first."; \
		exit 1; \
	fi
	@if ! curl -s $(DEVPI_URL) >/dev/null 2>&1; then \
		echo "❌  DevPi server not running. Run 'make devpi-start' first."; \
		exit 1; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	devpi use $(DEVPI_INDEX) && \
	devpi upload dist/*"
	@echo "✅  Package uploaded to devpi"
	@echo "🌐  Browse packages: $(DEVPI_URL)/$(DEVPI_INDEX)"

devpi-test:
	@echo "📥  Installing package mcp-contextforge-gateway from devpi..."
	@if ! curl -s $(DEVPI_URL) >/dev/null 2>&1; then \
		echo "❌  DevPi server not running. Run 'make devpi-start' first."; \
		exit 1; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	pip install --index-url $(DEVPI_URL)/$(DEVPI_INDEX)/+simple/ \
	            --extra-index-url https://pypi.org/simple/ \
	            --force-reinstall mcp-contextforge-gateway"
	@echo "✅  Installed mcp-contextforge-gateway from devpi"

devpi-clean: clean dist devpi-upload devpi-test
	@echo "🎉  Full devpi cycle complete!"
	@echo "📊  Package info:"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && pip show mcp-contextforge-gateway"

devpi-status:
	@echo "🔍  DevPi server status:"
	@if curl -s $(DEVPI_URL) >/dev/null 2>&1; then \
		echo "✅  Server running at $(DEVPI_URL)"; \
		if [ -f $(DEVPI_PID) ] && [ -s $(DEVPI_PID) ]; then \
			echo "📊  PID: $$(cat $(DEVPI_PID))"; \
		fi; \
		echo "📂  Data directory: $(DEVPI_DATA_DIR)"; \
		/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		devpi use $(DEVPI_URL) >/dev/null 2>&1 && \
		devpi user --list 2>/dev/null || echo '📝  Not logged in'"; \
	else \
		echo "❌  Server not running"; \
	fi

devpi-web:
	@echo "🌐  Opening devpi web interface..."
	@if curl -s $(DEVPI_URL) >/dev/null 2>&1; then \
		echo "📱  Web interface: $(DEVPI_URL)"; \
		which open >/dev/null 2>&1 && open $(DEVPI_URL) || \
		which xdg-open >/dev/null 2>&1 && xdg-open $(DEVPI_URL) || \
		echo "🔗  Open $(DEVPI_URL) in your browser"; \
	else \
		echo "❌  DevPi server not running. Run 'make devpi-start' first."; \
	fi

devpi-restart: devpi-stop devpi-start
	@echo "🔄  DevPi server restarted"

# Advanced targets for devpi management
devpi-reset: devpi-stop
	@echo "⚠️   Resetting devpi server (this will delete all data)..."
	@read -p "Are you sure? This will delete all packages and users [y/N]: " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		rm -rf $(DEVPI_DATA_DIR); \
		echo "✅  DevPi data reset. Run 'make devpi-init' to reinitialize."; \
	else \
		echo "❌  Reset cancelled."; \
	fi

devpi-backup:
	@echo "💾  Backing up devpi data..."
	@timestamp=$$(date +%Y%m%d-%H%M%S); \
	backup_file="$(HOME)/devpi-backup-$$timestamp.tar.gz"; \
	tar -czf "$$backup_file" -C $(HOME) .devpi 2>/dev/null && \
	echo "✅  Backup created: $$backup_file" || \
	echo "❌  Backup failed"

devpi-logs:
	@echo "📋  DevPi server logs:"
	@if [ -f "$(DEVPI_DATA_DIR)/server/devpi.log" ]; then \
		tail -f "$(DEVPI_DATA_DIR)/server/devpi.log"; \
	elif [ -f "$(DEVPI_DATA_DIR)/server/.xproc/devpi-server/xprocess.log" ]; then \
		tail -f "$(DEVPI_DATA_DIR)/server/.xproc/devpi-server/xprocess.log"; \
	elif [ -f "$(DEVPI_DATA_DIR)/server/devpi-server.log" ]; then \
		tail -f "$(DEVPI_DATA_DIR)/server/devpi-server.log"; \
	else \
		echo "❌  No log file found. Checking if server is running..."; \
		ps aux | grep "[d]evpi-server" || echo "Server not running"; \
		echo "📂  Expected log location: $(DEVPI_DATA_DIR)/server/devpi.log"; \
	fi

# Configuration helper - creates pip.conf for easy devpi usage
devpi-configure-pip:
	@echo "⚙️   Configuring pip to use devpi by default..."
	@mkdir -p $(HOME)/.pip
	@echo "[global]" > $(HOME)/.pip/pip.conf
	@echo "index-url = $(DEVPI_URL)/$(DEVPI_INDEX)/+simple/" >> $(HOME)/.pip/pip.conf
	@echo "extra-index-url = https://pypi.org/simple/" >> $(HOME)/.pip/pip.conf
	@echo "trusted-host = $(DEVPI_HOST)" >> $(HOME)/.pip/pip.conf
	@echo "" >> $(HOME)/.pip/pip.conf
	@echo "[search]" >> $(HOME)/.pip/pip.conf
	@echo "index = $(DEVPI_URL)/$(DEVPI_INDEX)/" >> $(HOME)/.pip/pip.conf
	@echo "✅  Pip configured to use devpi at $(DEVPI_URL)/$(DEVPI_INDEX)"
	@echo "📝  Config file: $(HOME)/.pip/pip.conf"

# Remove pip devpi configuration
devpi-unconfigure-pip:
	@echo "🔧  Removing devpi from pip configuration..."
	@if [ -f "$(HOME)/.pip/pip.conf" ]; then \
		rm "$(HOME)/.pip/pip.conf"; \
		echo "✅  Pip configuration reset to defaults"; \
	else \
		echo "ℹ️   No pip configuration found"; \
	fi

# ─────────────────────────────────────────────────────────────────────────────
# 📦  Version helper (defaults to the version in pyproject.toml)
#      override on the CLI:  make VER=0.4.0 devpi-delete
# ─────────────────────────────────────────────────────────────────────────────
VER ?= $(shell python3 -c "import tomllib, pathlib; \
print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])" \
2>/dev/null || echo 0.0.0)

devpi-delete: devpi-setup-user                 ## Delete mcp-contextforge-gateway==$(VER) from index
	@echo "🗑️   Removing mcp-contextforge-gateway==$(VER) from $(DEVPI_INDEX)..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		devpi use $(DEVPI_INDEX) && \
		devpi remove -y mcp-contextforge-gateway==$(VER) || true"
	@echo "✅  Delete complete (if it existed)"


# =============================================================================
# 🐚 LINT SHELL FILES
# =============================================================================
# help: 🐚 LINT SHELL FILES
# help: shell-linters-install - Install ShellCheck, shfmt & bashate (best-effort per OS)
# help: shell-lint            - Run shfmt (check-only) + ShellCheck + bashate on every *.sh
# help: shfmt-fix             - AUTO-FORMAT all *.sh in-place with shfmt -w
# -----------------------------------------------------------------------------

# ──────────────────────────
# Which shell files to scan
# ──────────────────────────
SHELL_SCRIPTS := $(shell find . -type f -name '*.sh' \
	-not -path './node_modules/*' \
	-not -path './.venv/*' \
	-not -path './venv/*' \
	-not -path './$(VENV_DIR)/*' \
	-not -path './.git/*' \
	-not -path './dist/*' \
	-not -path './build/*' \
	-not -path './.tox/*')

# Define shfmt binary location
SHFMT := $(shell command -v shfmt 2>/dev/null || echo "$(HOME)/go/bin/shfmt")

.PHONY: shell-linters-install shell-lint shfmt-fix shellcheck bashate

shell-linters-install:     ## 🔧  Install shellcheck, shfmt, bashate
	@echo "🔧  Installing/ensuring shell linters are present..."
	@set -e ; \
	# -------- ShellCheck -------- \
	if ! command -v shellcheck >/dev/null 2>&1 ; then \
	  echo "🛠  Installing ShellCheck..." ; \
	  case "$$(uname -s)" in \
	    Darwin)  brew install shellcheck ;; \
	    Linux)   { command -v apt-get && sudo apt-get update -qq && sudo apt-get install -y shellcheck ; } || \
	             { command -v dnf && sudo dnf install -y ShellCheck ; } || \
	             { command -v pacman && sudo pacman -Sy --noconfirm shellcheck ; } || true ;; \
	    *) echo "⚠️  Please install ShellCheck manually" ;; \
	  esac ; \
	fi ; \
	# -------- shfmt (Go) -------- \
	if ! command -v shfmt >/dev/null 2>&1 && [ ! -f "$(HOME)/go/bin/shfmt" ] ; then \
	  echo "🛠  Installing shfmt..." ; \
	  if command -v go >/dev/null 2>&1; then \
	    GO111MODULE=on go install mvdan.cc/sh/v3/cmd/shfmt@latest; \
	    echo "✅  shfmt installed to $(HOME)/go/bin/shfmt"; \
	  else \
	    case "$$(uname -s)" in \
	      Darwin)  brew install shfmt ;; \
	      Linux)   { command -v apt-get && sudo apt-get update -qq && sudo apt-get install -y shfmt ; } || \
	               { echo "⚠️  Go not found - install Go or shfmt package manually"; } ;; \
	      *) echo "⚠️  Please install shfmt manually" ;; \
	    esac ; \
	  fi ; \
	else \
	  echo "✅  shfmt already installed at: $$(command -v shfmt || echo $(HOME)/go/bin/shfmt)"; \
	fi ; \
	# -------- bashate (pip) ----- \
	if ! $(VENV_DIR)/bin/bashate -h >/dev/null 2>&1 ; then \
	  echo "🛠  Installing bashate (into venv)..." ; \
	  test -d "$(VENV_DIR)" || $(MAKE) venv ; \
	  /bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m pip install --quiet bashate" ; \
	fi
	@echo "✅  Shell linters ready."

# -----------------------------------------------------------------------------

shell-lint: shell-linters-install  ## 🔍  Run shfmt, ShellCheck & bashate
	@echo "🔍  Running shfmt (diff-only)..."
	@if command -v shfmt >/dev/null 2>&1; then \
		shfmt -d -i 4 -ci $(SHELL_SCRIPTS) || true; \
	elif [ -f "$(SHFMT)" ]; then \
		$(SHFMT) -d -i 4 -ci $(SHELL_SCRIPTS) || true; \
	else \
		echo "⚠️  shfmt not installed - skipping"; \
		echo "💡  Install with: go install mvdan.cc/sh/v3/cmd/shfmt@latest"; \
	fi
	@echo "🔍  Running ShellCheck..."
	@command -v shellcheck >/dev/null 2>&1 || { \
		echo "⚠️  shellcheck not installed - skipping"; \
		echo "💡  Install with: brew install shellcheck (macOS) or apt-get install shellcheck (Linux)"; \
	} && shellcheck $(SHELL_SCRIPTS) || true
	@echo "🔍  Running bashate..."
	@$(VENV_DIR)/bin/bashate $(SHELL_SCRIPTS) || true
	@echo "✅  Shell lint complete."


shfmt-fix: shell-linters-install   ## 🎨  Auto-format *.sh in place
	@echo "🎨  Formatting shell scripts with shfmt -w..."
	@if command -v shfmt >/dev/null 2>&1; then \
		shfmt -w -i 4 -ci $(SHELL_SCRIPTS); \
	elif [ -f "$(SHFMT)" ]; then \
		$(SHFMT) -w -i 4 -ci $(SHELL_SCRIPTS); \
	else \
		echo "❌  shfmt not found in PATH or $(HOME)/go/bin/"; \
		echo "💡  Install with: go install mvdan.cc/sh/v3/cmd/shfmt@latest"; \
		echo "    Or: brew install shfmt (macOS)"; \
		exit 1; \
	fi
	@echo "✅  shfmt formatting done."


# 🛢️  ALEMBIC DATABASE MIGRATIONS
# =============================================================================
# help: 🛢️  ALEMBIC DATABASE MIGRATIONS
# help: alembic-install   - Install Alembic CLI (and SQLAlchemy) in the current env
# help: db-init           - Initialize alembic migrations
# help: db-migrate        - Create a new migration
# help: db-upgrade        - Upgrade database to latest migration
# help: db-downgrade      - Downgrade database by one revision
# help: db-current        - Show current database revision
# help: db-history        - Show migration history
# help: db-heads          - Show available heads
# help: db-show           - Show a specific revision
# help: db-stamp          - Stamp database with a specific revision
# help: db-reset          - Reset database (CAUTION: drops all data)
# help: db-status         - Show detailed database status
# help: db-check          - Check if migrations are up to date
# help: db-fix-head       - Fix multiple heads issue
# -----------------------------------------------------------------------------

# Database migration commands
ALEMBIC_CONFIG = mcpgateway/alembic.ini

.PHONY: alembic-install db-init db-migrate db-upgrade db-downgrade db-current db-history db-heads db-show db-stamp db-reset db-status db-check db-fix-head

alembic-install:
	@echo "➜ Installing Alembic ..."
	pip install --quiet alembic sqlalchemy

.PHONY: db-init
db-init: ## Initialize alembic migrations
	@echo "🗄️ Initializing database migrations..."
	alembic -c $(ALEMBIC_CONFIG) init alembic

.PHONY: db-migrate
db-migrate: ## Create a new migration
	@echo "�️ Creating new migration..."
	@read -p "Enter migration message: " msg; \
	alembic -c $(ALEMBIC_CONFIG) revision --autogenerate -m "$$msg"

.PHONY: db-upgrade
db-upgrade: ## Upgrade database to latest migration
	@echo "🗄️ Upgrading database..."
	alembic -c $(ALEMBIC_CONFIG) upgrade head

.PHONY: db-downgrade
db-downgrade: ## Downgrade database by one revision
	@echo "�️ Downgrading database..."
	alembic -c $(ALEMBIC_CONFIG) downgrade -1

.PHONY: db-current
db-current: ## Show current database revision
	@echo "🗄️ Current database revision:"
	@alembic -c $(ALEMBIC_CONFIG) current

.PHONY: db-history
db-history: ## Show migration history
	@echo "🗄️ Migration history:"
	@alembic -c $(ALEMBIC_CONFIG) history

.PHONY: db-heads
db-heads: ## Show available heads
	@echo "�️ Available heads:"
	@alembic -c $(ALEMBIC_CONFIG) heads

.PHONY: db-show
db-show: ## Show a specific revision
	@read -p "Enter revision ID: " rev; \
	alembic -c $(ALEMBIC_CONFIG) show $$rev

.PHONY: db-stamp
db-stamp: ## Stamp database with a specific revision
	@read -p "Enter revision to stamp: " rev; \
	alembic -c $(ALEMBIC_CONFIG) stamp $$rev

.PHONY: db-reset
db-reset: ## Reset database (CAUTION: drops all data)
	@echo "⚠️  WARNING: This will drop all data!"
	@read -p "Are you sure? (y/N): " confirm; \
	if [ "$$confirm" = "y" ]; then \
		alembic -c $(ALEMBIC_CONFIG) downgrade base && \
		alembic -c $(ALEMBIC_CONFIG) upgrade head; \
		echo "✅ Database reset complete"; \
	else \
		echo "❌ Database reset cancelled"; \
	fi

.PHONY: db-status
db-status: ## Show detailed database status
	@echo "�️ Database Status:"
	@echo "Current revision:"
	@alembic -c $(ALEMBIC_CONFIG) current
	@echo ""
	@echo "Pending migrations:"
	@alembic -c $(ALEMBIC_CONFIG) history -r current:head

.PHONY: db-check
db-check: ## Check if migrations are up to date
	@echo "🗄️ Checking migration status..."
	@if alembic -c $(ALEMBIC_CONFIG) current | grep -q "(head)"; then \
		echo "✅ Database is up to date"; \
	else \
		echo "⚠️  Database needs migration"; \
		echo "Run 'make db-upgrade' to apply pending migrations"; \
		exit 1; \
	fi

.PHONY: db-fix-head
db-fix-head: ## Fix multiple heads issue
	@echo "�️ Fixing multiple heads..."
	alembic -c $(ALEMBIC_CONFIG) merge -m "merge heads"


# =============================================================================
# 🎭 UI TESTING (PLAYWRIGHT)
# =============================================================================
# help: 🎭 UI TESTING (PLAYWRIGHT)
# help: playwright-install   - Install Playwright browsers (chromium by default)
# help: playwright-install-all - Install all Playwright browsers (chromium, firefox, webkit)
# help: test-ui              - Run Playwright UI tests with visible browser
# help: test-ui-headless     - Run Playwright UI tests in headless mode
# help: test-ui-debug        - Run Playwright UI tests with Playwright Inspector
# help: test-ui-smoke        - Run UI smoke tests only (fast subset)
# help: test-ui-parallel     - Run UI tests in parallel using pytest-xdist
# help: test-ui-report       - Run UI tests and generate HTML report
# help: test-ui-coverage     - Run UI tests with coverage for admin endpoints
# help: test-ui-record       - Run UI tests and record videos (headless)
# help: test-ui-update-snapshots - Update visual regression snapshots
# help: test-ui-clean        - Clean up Playwright test artifacts

.PHONY: playwright-install playwright-install-all test-ui test-ui-headless test-ui-debug test-ui-smoke test-ui-parallel test-ui-report test-ui-coverage test-ui-record test-ui-update-snapshots test-ui-clean

# Playwright test variables
PLAYWRIGHT_DIR := tests/playwright
PLAYWRIGHT_REPORTS := $(PLAYWRIGHT_DIR)/reports
PLAYWRIGHT_SCREENSHOTS := $(PLAYWRIGHT_DIR)/screenshots
PLAYWRIGHT_VIDEOS := $(PLAYWRIGHT_DIR)/videos

## --- Playwright Setup -------------------------------------------------------
playwright-install:
	@echo "🎭 Installing Playwright browsers (chromium)..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pip install -e '.[playwright]' 2>/dev/null || pip install playwright pytest-playwright && \
		playwright install chromium"
	@echo "✅ Playwright chromium browser installed!"

playwright-install-all:
	@echo "🎭 Installing all Playwright browsers..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pip install -e '.[playwright]' 2>/dev/null || pip install playwright pytest-playwright && \
		playwright install"
	@echo "✅ All Playwright browsers installed!"

## --- UI Test Execution ------------------------------------------------------
test-ui: playwright-install
	@echo "🎭 Running UI tests with visible browser..."
	@echo "💡 Make sure the dev server is running: make dev"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(PLAYWRIGHT_SCREENSHOTS) $(PLAYWRIGHT_REPORTS)
	@if ! curl -s http://localhost:8000/health >/dev/null 2>&1; then \
		echo "❌ Dev server not running on http://localhost:8000"; \
		echo "💡 Start it with: make dev"; \
		exit 1; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		export TEST_BASE_URL=http://localhost:8000 && \
		python -m pytest tests/playwright/ -v --headed --screenshot=only-on-failure \
		--browser chromium || { echo '❌ UI tests failed!'; exit 1; }"
	@echo "✅ UI tests completed!"

test-ui-headless: playwright-install
	@echo "🎭 Running UI tests in headless mode..."
	@echo "💡 Make sure the dev server is running: make dev"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(PLAYWRIGHT_SCREENSHOTS) $(PLAYWRIGHT_REPORTS)
	@if ! curl -s http://localhost:8000/health >/dev/null 2>&1; then \
		echo "❌ Dev server not running on http://localhost:8000"; \
		echo "💡 Start it with: make dev"; \
		exit 1; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		export TEST_BASE_URL=http://localhost:8000 && \
		pytest $(PLAYWRIGHT_DIR)/ -v --screenshot=only-on-failure \
		--browser chromium || { echo '❌ UI tests failed!'; exit 1; }"
	@echo "✅ UI tests completed!"

test-ui-debug: playwright-install
	@echo "🎭 Running UI tests with Playwright Inspector..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(PLAYWRIGHT_SCREENSHOTS) $(PLAYWRIGHT_REPORTS)
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		PWDEBUG=1 pytest $(PLAYWRIGHT_DIR)/ -v -s --headed \
		--browser chromium"

test-ui-smoke: playwright-install
	@echo "🎭 Running UI smoke tests..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pytest $(PLAYWRIGHT_DIR)/ -v -m smoke --headed \
		--browser chromium || { echo '❌ UI smoke tests failed!'; exit 1; }"
	@echo "✅ UI smoke tests passed!"

test-ui-parallel: playwright-install
	@echo "🎭 Running UI tests in parallel..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pip install -q pytest-xdist && \
		pytest $(PLAYWRIGHT_DIR)/ -v -n auto --dist loadscope \
		--browser chromium || { echo '❌ UI tests failed!'; exit 1; }"
	@echo "✅ UI parallel tests completed!"

## --- UI Test Reporting ------------------------------------------------------
test-ui-report: playwright-install
	@echo "🎭 Running UI tests with HTML report..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(PLAYWRIGHT_REPORTS)
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pip install -q pytest-html && \
		pytest $(PLAYWRIGHT_DIR)/ -v --screenshot=only-on-failure \
		--html=$(PLAYWRIGHT_REPORTS)/report.html --self-contained-html \
		--browser chromium || true"
	@echo "✅ UI test report generated: $(PLAYWRIGHT_REPORTS)/report.html"
	@echo "   Open with: open $(PLAYWRIGHT_REPORTS)/report.html"

test-ui-coverage: playwright-install
	@echo "🎭 Running UI tests with coverage..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(PLAYWRIGHT_REPORTS)
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pytest $(PLAYWRIGHT_DIR)/ -v --cov=mcpgateway.admin \
		--cov-report=html:$(PLAYWRIGHT_REPORTS)/coverage \
		--cov-report=term --browser chromium || true"
	@echo "✅ UI coverage report: $(PLAYWRIGHT_REPORTS)/coverage/index.html"

test-ui-record: playwright-install
	@echo "🎭 Running UI tests with video recording..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(PLAYWRIGHT_VIDEOS)
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pytest $(PLAYWRIGHT_DIR)/ -v --video=on \
		--browser chromium || true"
	@echo "✅ Test videos saved in: $(PLAYWRIGHT_VIDEOS)/"

## --- UI Test Utilities ------------------------------------------------------
test-ui-update-snapshots: playwright-install
	@echo "🎭 Updating visual regression snapshots..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pytest $(PLAYWRIGHT_DIR)/ -v --update-snapshots \
		--browser chromium"
	@echo "✅ Snapshots updated!"

test-ui-clean:
	@echo "🧹 Cleaning Playwright test artifacts..."
	@rm -rf $(PLAYWRIGHT_SCREENSHOTS)/*.png
	@rm -rf $(PLAYWRIGHT_VIDEOS)/*.webm
	@rm -rf $(PLAYWRIGHT_REPORTS)/*
	@rm -rf test-results/
	@rm -f playwright-report-*.html test-results-*.xml
	@echo "✅ Playwright artifacts cleaned!"

## --- Combined Testing -------------------------------------------------------
test-all: test test-ui-headless
	@echo "✅ All tests completed (unit + UI)!"

# Add UI tests to your existing test suite if needed
test-full: coverage test-ui-report
	@echo "📊 Full test suite completed with coverage and UI tests!"


# =============================================================================
# 🔒 SECURITY TOOLS
# =============================================================================
# help: 🔒 SECURITY TOOLS
# help: security-all        - Run all security tools (semgrep, dodgy, gitleaks, etc.)
# help: security-report     - Generate comprehensive security report in docs/security/
# help: security-fix        - Auto-fix security issues where possible (pyupgrade, etc.)
# help: semgrep             - Static analysis for security patterns
# help: dodgy               - Check for suspicious code patterns (passwords, keys)
# help: dlint               - Best practices linter for Python
# help: pyupgrade           - Upgrade Python syntax to newer versions
# help: interrogate         - Check docstring coverage
# help: prospector          - Comprehensive Python code analysis
# help: pip-audit           - Audit Python dependencies for published CVEs
# help: gitleaks-install    - Install gitleaks secret scanner
# help: gitleaks            - Scan git history for secrets
# help: devskim-install-dotnet - Install .NET SDK and DevSkim CLI (security patterns scanner)
# help: devskim             - Run DevSkim static analysis for security anti-patterns

# List of security tools to run with security-all
SECURITY_TOOLS := semgrep dodgy dlint interrogate prospector pip-audit devskim

.PHONY: security-all security-report security-fix $(SECURITY_TOOLS) gitleaks-install gitleaks pyupgrade devskim-install-dotnet devskim

## --------------------------------------------------------------------------- ##
##  Master security target
## --------------------------------------------------------------------------- ##
security-all:
	@echo "🔒  Running full security tool suite..."
	@set -e; for t in $(SECURITY_TOOLS); do \
	    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
	    echo "- $$t"; \
	    $(MAKE) $$t || true; \
	done
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "🔍  Running gitleaks (if installed)..."
	@command -v gitleaks >/dev/null 2>&1 && $(MAKE) gitleaks || echo "⚠️  gitleaks not installed - run 'make gitleaks-install'"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "✅  Security scan complete!"

## --------------------------------------------------------------------------- ##
##  Individual security tools
## --------------------------------------------------------------------------- ##
semgrep:                            ## 🔍 Security patterns & anti-patterns
	@echo "🔍  semgrep - scanning for security patterns..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q semgrep && \
		$(VENV_DIR)/bin/semgrep --config=auto $(TARGET) --exclude-rule python.lang.compatibility.python37.python37-compatibility-importlib2 || true"

dodgy:                              ## 🔐 Suspicious code patterns
	@echo "🔐  dodgy - scanning for hardcoded secrets..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q dodgy && \
		$(VENV_DIR)/bin/dodgy $(TARGET) || true"

dlint:                              ## 📏 Python best practices
	@echo "📏  dlint - checking Python best practices..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q dlint && \
		$(VENV_DIR)/bin/python -m flake8 --select=DUO mcpgateway"

pyupgrade:                          ## ⬆️  Upgrade Python syntax
	@echo "⬆️  pyupgrade - checking for syntax upgrade opportunities..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q pyupgrade && \
		find $(TARGET) -name '*.py' -exec $(VENV_DIR)/bin/pyupgrade --py312-plus --diff {} + || true"
	@echo "💡  To apply changes, run: find $(TARGET) -name '*.py' -exec $(VENV_DIR)/bin/pyupgrade --py312-plus {} +"

interrogate:                        ## 📝 Docstring coverage
	@echo "📝  interrogate - checking docstring coverage..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q interrogate && \
		$(VENV_DIR)/bin/interrogate -vv mcpgateway || true"

prospector:                         ## 🔬 Comprehensive code analysis
	@echo "🔬  prospector - running comprehensive analysis..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q prospector[with_everything] && \
		$(VENV_DIR)/bin/prospector mcpgateway || true"

pip-audit:                          ## 🔒 Audit Python dependencies for CVEs
	@echo "🔒  pip-audit vulnerability scan..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install --quiet --upgrade pip-audit && \
		pip-audit --strict || true"

## --------------------------------------------------------------------------- ##
##  Gitleaks (Go binary - separate installation)
## --------------------------------------------------------------------------- ##
gitleaks-install:                   ## 📥 Install gitleaks secret scanner
	@echo "📥 Installing gitleaks..."
	@if [ "$$(uname)" = "Darwin" ]; then \
		brew install gitleaks; \
	elif [ "$$(uname)" = "Linux" ]; then \
		VERSION=$$(curl -s https://api.github.com/repos/gitleaks/gitleaks/releases/latest | grep '"tag_name"' | cut -d '"' -f 4); \
		curl -sSfL https://github.com/gitleaks/gitleaks/releases/download/$$VERSION/gitleaks_$${VERSION#v}_linux_x64.tar.gz | tar -xz -C /tmp; \
		sudo mv /tmp/gitleaks /usr/local/bin/; \
		sudo chmod +x /usr/local/bin/gitleaks; \
	else \
		echo "❌ Unsupported OS. Download from https://github.com/gitleaks/gitleaks/releases"; \
		exit 1; \
	fi
	@echo "✅  gitleaks installed successfully!"

gitleaks:                           ## 🔍 Scan for secrets in git history
	@command -v gitleaks >/dev/null 2>&1 || { \
		echo "❌ gitleaks not installed."; \
		echo "💡 Install with:"; \
		echo "   • macOS: brew install gitleaks"; \
		echo "   • Linux: Run 'make gitleaks-install'"; \
		echo "   • Or download from https://github.com/gitleaks/gitleaks/releases"; \
		exit 1; \
	}
	@echo "🔍 Scanning for secrets with gitleaks..."
	@gitleaks detect --source . -v || true
	@echo "💡 To scan git history: gitleaks detect --source . --log-opts='--all'"

## --------------------------------------------------------------------------- ##
##  DevSkim (.NET-based security patterns scanner)
## --------------------------------------------------------------------------- ##
devskim-install-dotnet:             ## 📦 Install .NET SDK and DevSkim CLI
	@echo "📦 Installing .NET SDK and DevSkim CLI..."
	@if [ "$$(uname)" = "Darwin" ]; then \
		echo "🍏 Installing .NET SDK for macOS..."; \
		brew install --cask dotnet-sdk || brew upgrade --cask dotnet-sdk; \
	elif [ "$$(uname)" = "Linux" ]; then \
		echo "🐧 Installing .NET SDK for Linux..."; \
		if command -v apt-get >/dev/null 2>&1; then \
			wget -q https://packages.microsoft.com/config/ubuntu/$$(lsb_release -rs)/packages-microsoft-prod.deb -O /tmp/packages-microsoft-prod.deb 2>/dev/null || \
			wget -q https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb -O /tmp/packages-microsoft-prod.deb; \
			sudo dpkg -i /tmp/packages-microsoft-prod.deb; \
			sudo apt-get update; \
			sudo apt-get install -y dotnet-sdk-9.0 || sudo apt-get install -y dotnet-sdk-8.0 || sudo apt-get install -y dotnet-sdk-7.0; \
			rm -f /tmp/packages-microsoft-prod.deb; \
		elif command -v dnf >/dev/null 2>&1; then \
			sudo dnf install -y dotnet-sdk-9.0 || sudo dnf install -y dotnet-sdk-8.0; \
		else \
			echo "❌ Unsupported Linux distribution. Please install .NET SDK manually."; \
			echo "   Visit: https://dotnet.microsoft.com/download"; \
			exit 1; \
		fi; \
	else \
		echo "❌ Unsupported OS. Please install .NET SDK manually."; \
		echo "   Visit: https://dotnet.microsoft.com/download"; \
		exit 1; \
	fi
	@echo "🔧 Installing DevSkim CLI tool..."
	@export PATH="$$PATH:$$HOME/.dotnet/tools" && \
		dotnet tool install --global Microsoft.CST.DevSkim.CLI || \
		dotnet tool update --global Microsoft.CST.DevSkim.CLI
	@echo "✅  DevSkim installed successfully!"
	@echo "💡  You may need to add ~/.dotnet/tools to your PATH:"
	@echo "    export PATH=\"\$$PATH:\$$HOME/.dotnet/tools\""

devskim:                            ## 🛡️  Run DevSkim security patterns analysis
	@echo "🛡️  Running DevSkim static analysis..."
	@if command -v devskim >/dev/null 2>&1 || [ -f "$$HOME/.dotnet/tools/devskim" ]; then \
		export PATH="$$PATH:$$HOME/.dotnet/tools" && \
		echo "📂 Scanning mcpgateway/ for security anti-patterns..." && \
		devskim analyze --source-code mcpgateway --output-file devskim-results.sarif -f sarif && \
		echo "" && \
		echo "📊 Detailed findings:" && \
		devskim analyze --source-code mcpgateway -f text && \
		echo "" && \
		echo "📄 SARIF report saved to: devskim-results.sarif" && \
		echo "💡 To view just the summary: devskim analyze --source-code mcpgateway -f text | grep -E '(Critical|Important|Moderate|Low)' | sort | uniq -c"; \
	else \
		echo "❌ DevSkim not found in PATH or ~/.dotnet/tools/"; \
		echo "💡 Install with:"; \
		echo "   • Run 'make devskim-install-dotnet'"; \
		echo "   • Or install .NET SDK and run: dotnet tool install --global Microsoft.CST.DevSkim.CLI"; \
		echo "   • Then add to PATH: export PATH=\"\$$PATH:\$$HOME/.dotnet/tools\""; \
	fi

## --------------------------------------------------------------------------- ##
##  Security reporting and advanced targets
## --------------------------------------------------------------------------- ##
security-report:                    ## 📊 Generate comprehensive security report
	@echo "📊 Generating security report..."
	@mkdir -p $(DOCS_DIR)/docs/security
	@echo "# Security Scan Report - $$(date)" > $(DOCS_DIR)/docs/security/report.md
	@echo "" >> $(DOCS_DIR)/docs/security/report.md
	@echo "## Code Security Patterns (semgrep)" >> $(DOCS_DIR)/docs/security/report.md
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q semgrep && \
		$(VENV_DIR)/bin/semgrep --config=auto $(TARGET) --quiet || true" >> $(DOCS_DIR)/docs/security/report.md 2>&1
	@echo "" >> $(DOCS_DIR)/docs/security/report.md
	@echo "## Suspicious Code Patterns (dodgy)" >> $(DOCS_DIR)/docs/security/report.md
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q dodgy && \
		$(VENV_DIR)/bin/dodgy $(TARGET) || true" >> $(DOCS_DIR)/docs/security/report.md 2>&1
	@echo "" >> $(DOCS_DIR)/docs/security/report.md
	@echo "## DevSkim Security Anti-patterns" >> $(DOCS_DIR)/docs/security/report.md
	@if command -v devskim >/dev/null 2>&1 || [ -f "$$HOME/.dotnet/tools/devskim" ]; then \
		export PATH="$$PATH:$$HOME/.dotnet/tools" && \
		devskim analyze --source-code mcpgateway --format text >> $(DOCS_DIR)/docs/security/report.md 2>&1 || true; \
	else \
		echo "DevSkim not installed - skipping" >> $(DOCS_DIR)/docs/security/report.md; \
	fi
	@echo "✅ Security report saved to $(DOCS_DIR)/docs/security/report.md"

security-fix:                       ## 🔧 Auto-fix security issues where possible
	@echo "🔧 Attempting to auto-fix security issues..."
	@echo "➤ Upgrading Python syntax with pyupgrade..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install -q pyupgrade && \
		find $(TARGET) -name '*.py' -exec $(VENV_DIR)/bin/pyupgrade --py312-plus {} +"
	@echo "➤ Updating dependencies to latest secure versions..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install --upgrade pip setuptools && \
		python3 -m pip list --outdated"
	@echo "✅ Auto-fixes applied where possible"
	@echo "⚠️  Manual review still required for:"
	@echo "   - Dependency updates (run 'make update')"
	@echo "   - Secrets in code (review dodgy/gitleaks output)"
	@echo "   - Security patterns (review semgrep output)"
	@echo "   - DevSkim findings (review devskim-results.sarif)"


# =============================================================================
# 🛡️ SNYK - Comprehensive vulnerability scanning and SBOM generation
# =============================================================================
# help: 🛡️ SNYK - Comprehensive vulnerability scanning and SBOM generation
# help: snyk-auth           - Authenticate Snyk CLI with your Snyk account
# help: snyk-test           - Test for open-source vulnerabilities and license issues
# help: snyk-code-test      - Test source code for security issues (SAST)
# help: snyk-container-test - Test container images for vulnerabilities
# help: snyk-iac-test       - Test Infrastructure as Code files for security issues
# help: snyk-aibom          - Generate AI Bill of Materials for Python projects
# help: snyk-sbom           - Generate Software Bill of Materials (SBOM)
# help: snyk-monitor        - Enable continuous monitoring on Snyk platform
# help: snyk-all            - Run all Snyk security scans (test, code-test, container-test, iac-test, sbom)
# help: snyk-helm-test       - Test Helm charts for security issues

.PHONY: snyk-auth snyk-test snyk-code-test snyk-container-test snyk-iac-test snyk-aibom snyk-sbom snyk-monitor snyk-all snyk-helm-test

## --------------------------------------------------------------------------- ##
##  Snyk Authentication
## --------------------------------------------------------------------------- ##
snyk-auth:                          ## 🔑 Authenticate with Snyk (required before first use)
	@echo "🔑 Authenticating with Snyk..."
	@command -v snyk >/dev/null 2>&1 || { \
		echo "❌ Snyk CLI not installed."; \
		echo "💡 Install with:"; \
		echo "   • npm: npm install -g snyk"; \
		echo "   • Homebrew: brew install snyk"; \
		echo "   • Direct: curl -sSL https://static.snyk.io/cli/latest/snyk-linux -o /usr/local/bin/snyk && chmod +x /usr/local/bin/snyk"; \
		exit 1; \
	}
	@snyk auth
	@echo "✅ Snyk authentication complete!"

## --------------------------------------------------------------------------- ##
##  Snyk Dependency Testing
## --------------------------------------------------------------------------- ##
snyk-test:                          ## 🔍 Test for open-source vulnerabilities
	@echo "🔍 Running Snyk open-source vulnerability scan..."
	@command -v snyk >/dev/null 2>&1 || { echo "❌ Snyk CLI not installed. Run 'make snyk-auth' for install instructions."; exit 1; }
	@echo "📦 Testing Python dependencies..."
	@if [ -f "requirements.txt" ]; then \
		snyk test --file=requirements.txt --severity-threshold=high --org=$${SNYK_ORG:-} || true; \
	fi
	@if [ -f "pyproject.toml" ]; then \
		echo "📦 Testing pyproject.toml dependencies..."; \
		snyk test --file=pyproject.toml --severity-threshold=high --org=$${SNYK_ORG:-} || true; \
	fi
	@if [ -f "requirements-dev.txt" ]; then \
		echo "📦 Testing dev dependencies..."; \
		snyk test --file=requirements-dev.txt --severity-threshold=high --dev --org=$${SNYK_ORG:-} || true; \
	fi
	@echo "💡 Run 'snyk monitor' to continuously monitor this project"

## --------------------------------------------------------------------------- ##
##  Snyk Code (SAST) Testing
## --------------------------------------------------------------------------- ##
snyk-code-test:                     ## 🔐 Test source code for security issues
	@echo "🔐 Running Snyk Code static analysis..."
	@command -v snyk >/dev/null 2>&1 || { echo "❌ Snyk CLI not installed. Run 'make snyk-auth' for install instructions."; exit 1; }
	@echo "📂 Scanning mcpgateway/ for security issues..."
	@snyk code test mcpgateway/ \
		--severity-threshold=high \
		--org=$${SNYK_ORG:-} \
		--json-file-output=snyk-code-results.json || true
	@echo "📊 Summary of findings:"
	@snyk code test mcpgateway/ --severity-threshold=high || true
	@echo "📄 Detailed results saved to: snyk-code-results.json"
	@echo "💡 To include ignored issues, add: --include-ignores"

## --------------------------------------------------------------------------- ##
##  Snyk Container Testing
## --------------------------------------------------------------------------- ##
snyk-container-test:                ## 🐳 Test container images for vulnerabilities
	@echo "🐳 Running Snyk container vulnerability scan..."
	@command -v snyk >/dev/null 2>&1 || { echo "❌ Snyk CLI not installed. Run 'make snyk-auth' for install instructions."; exit 1; }
	@echo "🔍 Testing container image $(IMAGE_NAME):$(IMAGE_TAG)..."
	@snyk container test $(IMAGE_NAME):$(IMAGE_TAG) \
		--file=$(CONTAINERFILE) \
		--severity-threshold=high \
		--exclude-app-vulns \
		--org=$${SNYK_ORG:-} \
		--json-file-output=snyk-container-results.json || true
	@echo "📊 Summary of container vulnerabilities:"
	@snyk container test $(IMAGE_NAME):$(IMAGE_TAG) --file=$(CONTAINERFILE) --severity-threshold=high || true
	@echo "📄 Detailed results saved to: snyk-container-results.json"
	@echo "💡 To include application vulnerabilities, remove --exclude-app-vulns"
	@echo "💡 To exclude base image vulns, add: --exclude-base-image-vulns"

## --------------------------------------------------------------------------- ##
##  Snyk Infrastructure as Code Testing
## --------------------------------------------------------------------------- ##
snyk-iac-test:                      ## 🏗️ Test IaC files for security issues
	@echo "🏗️ Running Snyk Infrastructure as Code scan..."
	@command -v snyk >/dev/null 2>&1 || { echo "❌ Snyk CLI not installed. Run 'make snyk-auth' for install instructions."; exit 1; }
	@echo "📂 Scanning for IaC security issues..."
	@if [ -f "docker-compose.yml" ] || [ -f "docker-compose.yaml" ]; then \
		echo "🐳 Testing docker-compose files..."; \
		snyk iac test docker-compose*.y*ml \
			--severity-threshold=medium \
			--org=$${SNYK_ORG:-} \
			--json-file-output=snyk-iac-compose-results.json || true; \
	fi
	@if [ -f "Dockerfile" ] || [ -f "Containerfile" ]; then \
		echo "📦 Testing Dockerfile/Containerfile..."; \
		snyk iac test $(CONTAINERFILE) \
			--severity-threshold=medium \
			--org=$${SNYK_ORG:-} \
			--json-file-output=snyk-iac-docker-results.json || true; \
	fi
	@if [ -f "Makefile" ]; then \
		echo "🔧 Testing Makefile..."; \
		snyk iac test Makefile \
			--severity-threshold=medium \
			--org=$${SNYK_ORG:-} || true; \
	fi
	@if [ -d "charts/mcp-stack" ]; then \
		echo "⎈ Testing Helm charts..."; \
		snyk iac test charts/mcp-stack/ \
			--severity-threshold=medium \
			--org=$${SNYK_ORG:-} \
			--json-file-output=snyk-helm-results.json || true; \
	fi
	@echo "💡 To generate a report, add: --report"

## --------------------------------------------------------------------------- ##
##  Snyk AI Bill of Materials
## --------------------------------------------------------------------------- ##
snyk-aibom:                         ## 🤖 Generate AI Bill of Materials
	@echo "🤖 Generating AI Bill of Materials..."
	@command -v snyk >/dev/null 2>&1 || { echo "❌ Snyk CLI not installed. Run 'make snyk-auth' for install instructions."; exit 1; }
	@echo "📊 Scanning for AI models, datasets, and tools..."
	@snyk aibom \
		--org=$${SNYK_ORG:-} \
		--json-file-output=aibom.json \
		mcpgateway/ || { \
			echo "⚠️  AIBOM generation failed. This feature requires:"; \
			echo "   • Python project with AI/ML dependencies"; \
			echo "   • Snyk plan that supports AIBOM"; \
			echo "   • Proper authentication (run 'make snyk-auth')"; \
		}
	@if [ -f "aibom.json" ]; then \
		echo "📄 AI BOM saved to: aibom.json"; \
		echo "🔍 Summary:"; \
		cat aibom.json | jq -r '.models[]?.name' 2>/dev/null | sort | uniq | sed 's/^/   • /' || true; \
	fi
	@echo "💡 To generate HTML report, add: --html"

## --------------------------------------------------------------------------- ##
##  Snyk Software Bill of Materials
## --------------------------------------------------------------------------- ##
snyk-sbom:                          ## 📋 Generate Software Bill of Materials
	@echo "📋 Generating Software Bill of Materials (SBOM)..."
	@command -v snyk >/dev/null 2>&1 || { echo "❌ Snyk CLI not installed. Run 'make snyk-auth' for install instructions."; exit 1; }
	@echo "📦 Generating SBOM for mcpgateway..."
	@snyk sbom \
		--format=cyclonedx1.5+json \
		--file=pyproject.toml \
		--name=mcpgateway \
		--version=$(shell grep -m1 version pyproject.toml | cut -d'"' -f2 || echo "0.0.0") \
		--org=$${SNYK_ORG:-} \
		--json-file-output=sbom-cyclonedx.json \
		. || true
	@if [ -f "sbom-cyclonedx.json" ]; then \
		echo "✅ CycloneDX SBOM saved to: sbom-cyclonedx.json"; \
		echo "📊 Component summary:"; \
		cat sbom-cyclonedx.json | jq -r '.components[].name' 2>/dev/null | wc -l | xargs echo "   • Total components:"; \
		cat sbom-cyclonedx.json | jq -r '.vulnerabilities[]?.id' 2>/dev/null | wc -l | xargs echo "   • Known vulnerabilities:"; \
	fi
	@echo "📦 Generating SPDX format SBOM..."
	@snyk sbom \
		--format=spdx2.3+json \
		--file=pyproject.toml \
		--name=mcpgateway \
		--org=$${SNYK_ORG:-} \
		--json-file-output=sbom-spdx.json \
		. || true
	@if [ -f "sbom-spdx.json" ]; then \
		echo "✅ SPDX SBOM saved to: sbom-spdx.json"; \
	fi
	@echo "💡 Supported formats: cyclonedx1.4+json|cyclonedx1.4+xml|cyclonedx1.5+json|cyclonedx1.5+xml|cyclonedx1.6+json|cyclonedx1.6+xml|spdx2.3+json"
	@echo "💡 To test an SBOM for vulnerabilities: snyk sbom test --file=sbom-cyclonedx.json"

## --------------------------------------------------------------------------- ##
##  Snyk Combined Security Report
## --------------------------------------------------------------------------- ##
snyk-all:                           ## 🔐 Run all Snyk security scans
	@echo "🔐 Running complete Snyk security suite..."
	@$(MAKE) snyk-test
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@$(MAKE) snyk-code-test
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@$(MAKE) snyk-container-test
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@$(MAKE) snyk-iac-test
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@$(MAKE) snyk-sbom
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "✅ Snyk security scan complete!"
	@echo "📊 Results saved to:"
	@ls -la snyk-*.json sbom-*.json 2>/dev/null || echo "   No result files found"

## --------------------------------------------------------------------------- ##
##  Snyk Monitoring (Continuous)
## --------------------------------------------------------------------------- ##
snyk-monitor:                       ## 📡 Enable continuous monitoring on Snyk platform
	@echo "📡 Setting up continuous monitoring..."
	@command -v snyk >/dev/null 2>&1 || { echo "❌ Snyk CLI not installed. Run 'make snyk-auth' for install instructions."; exit 1; }
	@snyk monitor \
		--org=$${SNYK_ORG:-} \
		--project-name=mcpgateway \
		--project-environment=production \
		--project-lifecycle=production \
		--project-business-criticality=high \
		--project-tags=security:high,team:platform
	@echo "✅ Project is now being continuously monitored on Snyk platform"
	@echo "🌐 View results at: https://app.snyk.io"


## --------------------------------------------------------------------------- ##
##  Snyk Helm Chart Testing
## --------------------------------------------------------------------------- ##
snyk-helm-test:                     ## ⎈ Test Helm charts for security issues
	@echo "⎈ Running Snyk Helm chart security scan..."
	@command -v snyk >/dev/null 2>&1 || { echo "❌ Snyk CLI not installed. Run 'make snyk-auth' for install instructions."; exit 1; }
	@if [ -d "charts/mcp-stack" ]; then \
		echo "📂 Scanning charts/mcp-stack/ for security issues..."; \
		snyk iac test charts/mcp-stack/ \
			--severity-threshold=medium \
			--org=$${SNYK_ORG:-} \
			--json-file-output=snyk-helm-results.json || true; \
		echo "📄 Detailed results saved to: snyk-helm-results.json"; \
	else \
		echo "⚠️  No Helm charts found in charts/mcp-stack/"; \
	fi

# ==============================================================================
# 🔍 HEADER MANAGEMENT - Check and fix Python file headers
# ==============================================================================
# help: 🔍 HEADER MANAGEMENT - Check and fix Python file headers
# help: check-headers          - Check all Python file headers (dry run - default)
# help: check-headers-diff     - Check headers and show diff preview
# help: check-headers-debug    - Check headers with debug information
# help: check-header           - Check specific file/directory (use: path=...)
# help: fix-all-headers        - Fix ALL files with incorrect headers (modifies files!)
# help: fix-all-headers-no-encoding - Fix headers without encoding line requirement
# help: fix-all-headers-custom - Fix with custom config (year=YYYY license=... shebang=...)
# help: interactive-fix-headers - Fix headers with prompts before each change
# help: fix-header             - Fix specific file/directory (use: path=... authors=...)
# help: pre-commit-check-headers - Check headers for pre-commit hooks
# help: pre-commit-fix-headers - Fix headers for pre-commit hooks

.PHONY: check-headers fix-all-headers interactive-fix-headers fix-header check-headers-diff check-header \
        check-headers-debug fix-all-headers-no-encoding fix-all-headers-custom \
        pre-commit-check-headers pre-commit-fix-headers

## --------------------------------------------------------------------------- ##
##  Check modes (no modifications)
## --------------------------------------------------------------------------- ##
check-headers:                      ## 🔍 Check all Python file headers (dry run - default)
	@echo "🔍 Checking Python file headers (dry run - no files will be modified)..."
	@python3 .github/tools/fix_file_headers.py

check-headers-diff:                 ## 🔍 Check headers and show diff preview
	@echo "🔍 Checking Python file headers with diff preview..."
	@python3 .github/tools/fix_file_headers.py --show-diff

check-headers-debug:                ## 🔍 Check headers with debug information
	@echo "🔍 Checking Python file headers with debug info..."
	@python3 .github/tools/fix_file_headers.py --debug

check-header:                       ## 🔍 Check specific file/directory (use: path=... debug=1 diff=1)
	@if [ -z "$(path)" ]; then \
		echo "❌ Error: 'path' parameter is required"; \
		echo "💡 Usage: make check-header path=<file_or_directory> [debug=1] [diff=1]"; \
		exit 1; \
	fi
	@echo "🔍 Checking headers in $(path) (dry run)..."
	@extra_args=""; \
	if [ "$(debug)" = "1" ]; then \
		extra_args="$$extra_args --debug"; \
	fi; \
	if [ "$(diff)" = "1" ]; then \
		extra_args="$$extra_args --show-diff"; \
	fi; \
	python3 .github/tools/fix_file_headers.py --check --path "$(path)" $$extra_args

## --------------------------------------------------------------------------- ##
##  Fix modes (will modify files)
## --------------------------------------------------------------------------- ##
fix-all-headers:                    ## 🔧 Fix ALL files with incorrect headers (⚠️ modifies files!)
	@echo "⚠️  WARNING: This will modify all Python files with incorrect headers!"
	@echo "🔧 Automatically fixing all Python file headers..."
	@python3 .github/tools/fix_file_headers.py --fix-all

fix-all-headers-no-encoding:        ## 🔧 Fix headers without encoding line requirement
	@echo "🔧 Fixing headers without encoding line requirement..."
	@python3 .github/tools/fix_file_headers.py --fix-all --no-encoding

fix-all-headers-custom:             ## 🔧 Fix with custom config (year=YYYY license=... shebang=...)
	@echo "🔧 Fixing headers with custom configuration..."
	@if [ -n "$(year)" ]; then \
		extra_args="$$extra_args --copyright-year $(year)"; \
	fi; \
	if [ -n "$(license)" ]; then \
		extra_args="$$extra_args --license $(license)"; \
	fi; \
	if [ -n "$(shebang)" ]; then \
		extra_args="$$extra_args --require-shebang $(shebang)"; \
	fi; \
	python3 .github/tools/fix_file_headers.py --fix-all $$extra_args

interactive-fix-headers:            ## 💬 Fix headers with prompts before each change
	@echo "💬 Interactively fixing Python file headers..."
	@echo "You will be prompted before each change."
	@python3 .github/tools/fix_file_headers.py --interactive

fix-header:                         ## 🔧 Fix specific file/directory (use: path=... authors=... shebang=... encoding=no)
	@if [ -z "$(path)" ]; then \
		echo "❌ Error: 'path' parameter is required"; \
		echo "💡 Usage: make fix-header path=<file_or_directory> [authors=\"Name1, Name2\"] [shebang=auto|always|never] [encoding=no]"; \
		exit 1; \
	fi
	@echo "🔧 Fixing headers in $(path)"
	@echo "⚠️  This will modify the file(s)!"
	@extra_args=""; \
	if [ -n "$(authors)" ]; then \
		echo "   Authors: $(authors)"; \
		extra_args="$$extra_args --authors \"$(authors)\""; \
	fi; \
	if [ -n "$(shebang)" ]; then \
		echo "   Shebang requirement: $(shebang)"; \
		extra_args="$$extra_args --require-shebang $(shebang)"; \
	fi; \
	if [ "$(encoding)" = "no" ]; then \
		echo "   Encoding line: not required"; \
		extra_args="$$extra_args --no-encoding"; \
	fi; \
	eval python3 .github/tools/fix_file_headers.py --fix --path "$(path)" $$extra_args

## --------------------------------------------------------------------------- ##
##  Pre-commit integration
## --------------------------------------------------------------------------- ##
pre-commit-check-headers:           ## 🪝 Check headers for pre-commit hooks
	@echo "🪝 Checking headers for pre-commit..."
	@python3 .github/tools/fix_file_headers.py --check

pre-commit-fix-headers:             ## 🪝 Fix headers for pre-commit hooks
	@echo "🪝 Fixing headers for pre-commit..."
	@python3 .github/tools/fix_file_headers.py --fix-all
