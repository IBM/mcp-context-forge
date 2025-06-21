# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   🐍 MCP CONTEXT FORGE - Makefile
#   (An enterprise-ready Model Context Protocol Gateway)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Author: Mihai Criveti
# Description: Build & automation helpers for the MCP Gateway project
# Usage: run `make` or `make help` to view available targets
#
# help: 🐍 MCP CONTEXT FORGE  (An enterprise-ready Model Context Protocol Gateway)
#
# ──────────────────────────────────────────────────────────────────────────
# Project variables
PROJECT_NAME      = mcpgateway
DOCS_DIR          = docs
HANDSDOWN_PARAMS  = -o $(DOCS_DIR)/ -n $(PROJECT_NAME) --name "MCP Gateway" --cleanup

TEST_DOCS_DIR ?= $(DOCS_DIR)/docs/test

# Project-wide clean-up targets
DIRS_TO_CLEAN := __pycache__ .pytest_cache .tox .ruff_cache .pyre .mypy_cache .pytype \
                 dist build site .eggs *.egg-info .cache htmlcov certs \
                 $(VENV_DIR).sbom $(COVERAGE_DIR) \
                 node_modules

FILES_TO_CLEAN := .coverage coverage.xml mcp.prof mcp.pstats \
                  $(PROJECT_NAME).sbom.json \
                  snakefood.dot packages.dot classes.dot \
                  $(DOCS_DIR)/pstats.png \
                  $(DOCS_DIR)/docs/test/sbom.md \
                  $(DOCS_DIR)/docs/test/{unittest,full,index,test}.md \
				  $(DOCS_DIR)/docs/images/coverage.svg $(LICENSES_MD) $(METRICS_MD)

COVERAGE_DIR ?= $(DOCS_DIR)/docs/coverage
LICENSES_MD  ?= $(DOCS_DIR)/docs/test/licenses.md
METRICS_MD   ?= $(DOCS_DIR)/docs/metrics/loc.md

# -----------------------------------------------------------------------------
# Container resource configuration
CONTAINER_MEMORY = 2048m
CONTAINER_CPUS   = 2

# Virtual-environment variables
VENVS_DIR := $(HOME)/.venv
VENV_DIR  := $(VENVS_DIR)/$(PROJECT_NAME)

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
	@echo -e "💡  Enter the venv using:\n    . $(VENV_DIR)/bin/activate\n"
	@. $(VENV_DIR)/bin/activate
	@echo "export MYPY_CACHE_DIR=/tmp/cache/mypy/$(PROJECT_NAME)"
	@echo "export PYTHONPYCACHEPREFIX=/tmp/cache/$(PROJECT_NAME)"

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
	@echo "⬆️   Updating installed dependencies…"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install -U .[dev]"

# help: check-env            - Verify all required env vars in .env are present
.PHONY: check-env
check-env:
	@echo "🔎  Checking .env against .env.example…"
	@missing=0; \
	for key in $$(grep -Ev '^\s*#|^\s*$$' .env.example | cut -d= -f1); do \
	  grep -q "^$$key=" .env || { echo "❌ Missing: $$key"; missing=1; }; \
	done; \
	if [ $$missing -eq 0 ]; then echo "✅  All environment variables are present."; fi


# =============================================================================
# ▶️ SERVE & TESTING
# =============================================================================
# help: ▶️ SERVE & TESTING
# help: serve                - Run production Gunicorn server on :4444
# help: certs                - Generate self-signed TLS cert & key in ./certs (won't overwrite)
# help: serve-ssl            - Run Gunicorn behind HTTPS on :4444 (uses ./certs)
# help: dev                  - Run fast-reload dev server (uvicorn)
# help: run                  - Execute helper script ./run.sh
# help: smoketest            - Run smoketest.py --verbose (build container, add MCP server, test endpoints)
# help: test                 - Run unit tests with pytest
# help: test-curl            - Smoke-test API endpoints with curl script
# help: pytest-examples      - Run README / examples through pytest-examples

.PHONY: serve serve-ssl dev run test test-curl pytest-examples certs clean

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
		echo "🔏  Existing certificates found in ./certs – skipping generation."; \
	else \
		echo "🔏  Generating self-signed certificate (1 year)…"; \
		mkdir -p certs; \
		openssl req -x509 -newkey rsa:4096 -sha256 -days 365 -nodes \
			-keyout certs/key.pem -out certs/cert.pem \
			-subj "/CN=localhost" \
			-addext "subjectAltName=DNS:localhost,IP:127.0.0.1"; \
		echo "✅  TLS certificate written to ./certs"; \
	fi
	chmod 640 certs/key.pem

## --- Testing -----------------------------------------------------------------
smoketest:
	@echo "🚀 Running smoketest…"
	@./smoketest.py --verbose || { echo "❌ Smoketest failed!"; exit 1; }
	@echo "✅ Smoketest passed!"

test:
	@echo "🧪 Running tests..."
	@test -d "$(VENV_DIR)" || make venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m pip install pytest pytest-asyncio pytest-cov -q && python3 -m pytest --maxfail=0 --disable-warnings -v"

pytest-examples:
	@echo "🧪 Testing README examples..."
	@test -d "$(VENV_DIR)" || make venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m pip install pytest pytest-examples -q && pytest -v test_readme.py"

test-curl:
	./test_endpoints.sh

## --- House-keeping -----------------------------------------------------------
# help: clean                - Remove caches, build artefacts, virtualenv, docs, certs, coverage, SBOM, etc.
.PHONY: clean
clean:
	@echo "🧹  Cleaning workspace…"
	@# Remove matching directories
	@for dir in $(DIRS_TO_CLEAN); do \
		find . -type d -name "$$dir" -exec rm -rf {} +; \
	done
	@# Remove listed files
	@rm -f $(FILES_TO_CLEAN)
	@# Delete Python bytecode
	@find . -name '*.py[cod]' -delete
	@echo "✅  Clean complete."


# =============================================================================
# 📊 COVERAGE & METRICS
# =============================================================================
# help: 📊 COVERAGE & METRICS
# help: coverage             - Run tests with coverage, emit md/HTML/XML + badge
# help: pip-licenses         - Produce dependency license inventory (markdown)
# help: scc                  - Quick LoC/complexity snapshot with scc
# help: scc-report           - Generate HTML LoC & per-file metrics with scc
.PHONY: coverage pip-licenses scc scc-report

coverage:
	@mkdir -p $(TEST_DOCS_DIR)
	@printf "# Unit tests\n\n" > $(DOCS_DIR)/docs/test/unittest.md
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pytest -p pytest_cov --reruns=1 --reruns-delay 30 \
			--md-report --md-report-output=$(DOCS_DIR)/docs/test/unittest.md \
			--dist loadgroup -n 8 -rA --cov-append --capture=tee-sys -v \
			--durations=120 --doctest-modules app/ --cov-report=term \
			--cov=app --ignore=test.py tests/ || true"
	@printf '\n## Coverage report\n\n' >> $(DOCS_DIR)/docs/test/unittest.md
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		coverage report --format=markdown -m --no-skip-covered \
		>> $(DOCS_DIR)/docs/test/unittest.md"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		coverage html -d $(COVERAGE_DIR) --include=app/*"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && coverage xml"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		coverage-badge -fo $(DOCS_DIR)/docs/images/coverage.svg"
	@echo "✅  Coverage artefacts: md, HTML in $(COVERAGE_DIR), XML & badge ✔"

pip-licenses:
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install pip-licenses"
	@mkdir -p $(dir $(LICENSES_MD))
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pip-licenses --format=markdown --with-authors --with-urls > $(LICENSES_MD)"
	@cat $(LICENSES_MD)
	@echo "📜  License inventory written to $(LICENSES_MD)"

scc:
	@scc --by-file -i py,sh .

scc-report:
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
	@echo "📚  Generating documentation with handsdown…"
	uv handsdown --external https://github.com/yourorg/$(PROJECT_NAME)/ \
	             -o $(DOCS_DIR)/docs \
	             -n app --name "$(PROJECT_NAME)" --cleanup

	@echo "🔧  Rewriting GitHub links…"
	@find $(DOCS_DIR)/docs/app -type f \
	      -exec sed $(SED_INPLACE) 's#https://github.com/yourorg#https://github.com/ibm/mcp-context-forge#g' {} +

	@sed $(SED_INPLACE) 's#https://github.com/yourorg#https://github.com/ibm/mcp-context-forge#g' \
	      $(DOCS_DIR)/docs/README.md

	@cp README.md $(DOCS_DIR)/docs/index.md
	@echo "✅  Docs ready in $(DOCS_DIR)/docs"

.PHONY: images
images:
	@echo "🖼️   Generating documentation diagrams…"
	@mkdir -p $(DOCS_DIR)/docs/design/images
	@code2flow mcpgateway/ --output $(DOCS_DIR)/docs/design/images/code2flow.dot || true
	@dot -Tsvg -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=14 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=14 -Efontcolor=black $(DOCS_DIR)/docs/design/images/code2flow.dot -o $(DOCS_DIR)/docs/design/images/code2flow.svg || true
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python -m pip install snakefood3"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python -m snakefood3 . mcpgateway > snakefood.dot"
	@dot -Tpng -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=12 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=10 -Efontcolor=black snakefood.dot -o $(DOCS_DIR)/docs/design/images/snakefood.png || true
	@pyreverse --colorized mcpgateway || true
	@dot -Tsvg -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=14 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=14 -Efontcolor=black packages.dot -o $(DOCS_DIR)/docs/design/images/packages.svg || true
	@dot -Tsvg -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=14 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=14 -Efontcolor=black classes.dot -o $(DOCS_DIR)/docs/design/images/classes.svg || true
	@rm -f packages.dot classes.dot snakefood.dot || true

# =============================================================================
# 🔍 LINTING & STATIC ANALYSIS
# =============================================================================
# help: 🔍 LINTING & STATIC ANALYSIS
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
# help: depend               - List dependencies in ≈requirements format
# help: snakeviz             - Profile & visualise with snakeviz
# help: pstats               - Generate PNG call-graph from cProfile stats
# help: spellcheck-sort      - Sort local spellcheck dictionary
# help: tox                  - Run tox across multi-Python versions
# help: sbom                 - Produce a CycloneDX SBOM and vulnerability scan
# help: pytype               - Flow-sensitive type checker
# help: check-manifest       - Verify sdist/wheel completeness

# List of individual lint targets; lint loops over these
LINTERS := isort flake8 pylint mypy bandit pydocstyle pycodestyle pre-commit \
           ruff pyright radon pyroma pyre spellcheck importchecker \
		   pytype check-manifest markdownlint

.PHONY: lint $(LINTERS) black fawltydeps wily depend snakeviz pstats \
        spellcheck-sort tox pytype sbom


## --------------------------------------------------------------------------- ##
##  Master target
## --------------------------------------------------------------------------- ##
lint:
	@echo "🔍  Running full lint suite…"
	@set -e; for t in $(LINTERS); do \
	    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
	    echo "• $$t"; \
	    $(MAKE) $$t || true; \
	done

## --------------------------------------------------------------------------- ##
##  Individual targets (alphabetical)
## --------------------------------------------------------------------------- ##
autoflake:                          ## 🧹  Strip unused imports / vars
	@$(VENV_DIR)/bin/autoflake --in-place --remove-all-unused-imports \
	          --remove-unused-variables -r mcpgateway tests

black:                              ## 🎨  Reformat code with black
	@echo "🎨  black …" && $(VENV_DIR)/bin/black -l 200 mcpgateway tests

isort:                              ## 🔀  Sort imports
	@echo "🔀  isort …" && $(VENV_DIR)/bin/isort .

flake8:                             ## 🐍  flake8 checks
	@$(VENV_DIR)/bin/flake8 mcpgateway

pylint:                             ## 🐛  pylint checks
	@$(VENV_DIR)/bin/pylint mcpgateway

markdownlint:					    ## 📖  Markdown linting
	@$(VENV_DIR)/bin/markdownlint -c .markdownlint.json .

mypy:                               ## 🏷️  mypy type-checking
	@$(VENV_DIR)/bin/mypy mcpgateway

bandit:                             ## 🛡️  bandit security scan
	@$(VENV_DIR)/bin/bandit -r mcpgateway

pydocstyle:                         ## 📚  Docstring style
	@$(VENV_DIR)/bin/pydocstyle mcpgateway

pycodestyle:                        ## 📝  Simple PEP-8 checker
	@$(VENV_DIR)/bin/pycodestyle mcpgateway --max-line-length=200

pre-commit:                         ## 🪄  Run pre-commit hooks
	@$(VENV_DIR)/bin/pre-commit run --all-files --show-diff-on-failure

ruff:                               ## ⚡  Ruff lint + format
	@$(VENV_DIR)/bin/ruff check mcpgateway && $(VENV_DIR)/bin/ruff format mcpgateway tests

ty:                                 ## ⚡  Ty type checker
	@$(VENV_DIR)/bin/ty check mcpgateway tests

pyright:                            ## 🏷️  Pyright type-checking
	@$(VENV_DIR)/bin/pyright mcpgateway tests

radon:                              ## 📈  Complexity / MI metrics
	@$(VENV_DIR)/bin/radon mi -s mcpgateway tests && \
	$(VENV_DIR)/bin/radon cc -s mcpgateway tests && \
	$(VENV_DIR)/bin/radon hal mcpgateway tests && \
	$(VENV_DIR)/bin/radon raw -s mcpgateway tests

pyroma:                             ## 📦  Packaging metadata check
	@$(VENV_DIR)/bin/pyroma -d .

importchecker:                      ## 🧐  Orphaned import detector
	@$(VENV_DIR)/bin/importchecker .

spellcheck:                         ## 🔤  Spell-check
	@$(VENV_DIR)/bin/pyspelling || true

fawltydeps:                         ## 🏗️  Dependency sanity
	@$(VENV_DIR)/bin/fawltydeps --detailed --exclude 'docs/**' . || true

wily:                               ## 📈  Maintainability report
	@git stash --quiet
	@wily build -n 10 . > /dev/null || true
	@wily report . || true
	@git stash pop --quiet

pyre:                               ## 🧠  Facebook Pyre analysis
	@$(VENV_DIR)/bin/pyre

depend:                             ## 📦  List dependencies
	pdm list --freeze

snakeviz:                           ## 🐍  Interactive profile visualiser
	@python3 -m cProfile -o mcp.prof app/server.py && snakeviz mcp.prof --server

pstats:                             ## 📊  Static call-graph image
	@python3 -m cProfile -o mcp.pstats app/server.py && \
	 gprof2dot -w -e 3 -n 3 -s -f pstats mcp.pstats | \
	 dot -Tpng -o $(DOCS_DIR)/pstats.png

spellcheck-sort: .spellcheck-en.txt ## 🔤  Sort spell-list
	sort -d -f -o $< $<

tox:                                ## 🧪  Multi-Python tox matrix (uv)
	@echo "🧪  Running tox with uv …"
	python -m tox -p auto $(TOXARGS)

sbom:								## 🛡️  Generate SBOM & security report
	@echo "🛡️   Generating SBOM & security report…"
	@rm -Rf "$(VENV_DIR).sbom"
	@python3 -m venv "$(VENV_DIR).sbom"
	@/bin/bash -c "source $(VENV_DIR).sbom/bin/activate && python3 -m pip install --upgrade pip setuptools pdm uv && python3 -m uv pip install .[dev]"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install cyclonedx-bom sbom2doc"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m cyclonedx_py environment --validate '$(VENV_DIR).sbom' --pyproject pyproject.toml --gather-license-texts > $(PROJECT_NAME).sbom.json"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && sbom2doc -i $(PROJECT_NAME).sbom.json -f markdown -o $(DOCS_DIR)/docs/test/sbom.md"
	@trivy sbom $(PROJECT_NAME).sbom.json | tee -a $(DOCS_DIR)/docs/test/sbom.md
	@/bin/bash -c "source $(VENV_DIR).sbom/bin/activate && python3 -m pdm outdated | tee -a $(DOCS_DIR)/docs/test/sbom.md"

pytype:								## 🧠  Pytype static type analysis
	@echo "🧠  Pytype analysis…"
	@$(VENV_DIR)/bin/pytype -V 3.12 -j auto mcpgateway tests

check-manifest:						## 📦  Verify MANIFEST.in completeness
	@echo "📦  Verifying MANIFEST.in completeness…"
	@$(VENV_DIR)/bin/check-manifest

# -----------------------------------------------------------------------------
# 📑 YAML / JSON / TOML LINTERS
# -----------------------------------------------------------------------------
# help: yamllint             - Lint YAML files (uses .yamllint)
# help: jsonlint             - Validate every *.json file with jq (‐‐exit-status)
# help: tomllint             - Validate *.toml files with tomlcheck
#
# ➊  Add the new linters to the master list
LINTERS += yamllint jsonlint tomllint

# ➋  Individual targets
.PHONY: yamllint jsonlint tomllint

yamllint:                         ## 📑 YAML linting
	@command -v yamllint >/dev/null 2>&1 || { \
	  echo '❌  yamllint not installed  ➜  pip install yamllint'; exit 1; }
	@echo '📑  yamllint …' && $(VENV_DIR)/bin/yamllint -c .yamllint .

jsonlint:                         ## 📑 JSON validation (jq)
	@command -v jq >/dev/null 2>&1 || { \
	  echo '❌  jq not installed  ➜  sudo apt-get install jq'; exit 1; }
	@echo '📑  jsonlint (jq) …'
	@find . -type f -name '*.json' -not -path './node_modules/*' -print0 \
	  | xargs -0 -I{} sh -c 'jq empty "{}"' \
	&& echo '✅  All JSON valid'

tomllint:                         ## 📑 TOML validation (tomlcheck)
	@command -v tomlcheck >/dev/null 2>&1 || { \
	  echo '❌  tomlcheck not installed  ➜  pip install tomlcheck'; exit 1; }
	@echo '📑  tomllint (tomlcheck) …'
	@find . -type f -name '*.toml' -print0 \
	  | xargs -0 -I{} $(VENV_DIR)/bin/tomlcheck "{}"

# =============================================================================
# 🕸️  WEBPAGE LINTERS & STATIC ANALYSIS
# =============================================================================
# help: 🕸️  WEBPAGE LINTERS & STATIC ANALYSIS (HTML/CSS/JS lint + security scans + formatting)
# help: install-web-linters  - Install HTMLHint, Stylelint, ESLint, Retire.js & Prettier via npm
# help: lint-web             - Run HTMLHint, Stylelint, ESLint, Retire.js and npm audit
# help: format-web           - Format HTML, CSS & JS files with Prettier
.PHONY: install-web-linters lint-web format-web

install-web-linters:
	@echo "🔧 Installing HTML/CSS/JS lint, security & formatting tools..."
	@if [ ! -f package.json ]; then \
	  echo "📦 Initializing npm project…"; \
	  npm init -y >/dev/null; \
	fi
	@npm install --no-save \
		htmlhint \
		stylelint stylelint-config-standard @stylistic/stylelint-config stylelint-order \
		eslint eslint-config-standard \
		retire \
		prettier

lint-web: install-web-linters
	@echo "🔍 Linting HTML files…"
	@npx htmlhint "mcpgateway/templates/**/*.html" || true
	@echo "🔍 Linting CSS files…"
	@npx stylelint "mcpgateway/static/**/*.css" || true
	@echo "🔍 Linting JS files…"
	@npx eslint "mcpgateway/static/**/*.js" || true
	@echo "🔒 Scanning for known JS/CSS library vulnerabilities with retire.js…"
	@npx retire --path mcpgateway/static || true
	@if [ -f package.json ]; then \
	  echo "🔒 Running npm audit (high severity)…"; \
	  npm audit --audit-level=high || true; \
	else \
	  echo "⚠️  Skipping npm audit: no package.json found"; \
	fi

format-web: install-web-linters
	@echo "🎨 Formatting HTML, CSS & JS with Prettier…"
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
	@echo "🔍  osv-scanner source scan…"
	@osv-scanner scan source --recursive .

# ─────────────── Container image scan ─────────────────────────────────────────
osv-scan-image:
	@echo "🔍  osv-scanner image scan…"
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
# help: sonar-submit-docker  - Run containerised Sonar Scanner CLI with Docker
# help: sonar-submit-podman  - Run containerised Sonar Scanner CLI with Podman
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
	@echo "🔧 Installing podman-compose …"
	python3 -m pip install --quiet podman-compose

sonar-deps-docker:
	@echo "🔧 Ensuring docker-compose is available …"
	@which docker-compose >/dev/null || python3 -m pip install --quiet docker-compose

## ─────────── Run SonarQube server (compose) ────────────────────────────
sonar-up-podman:
	@echo "🚀 Starting SonarQube (v$(SONARQUBE_VERSION)) with podman-compose …"
	SONARQUBE_VERSION=$(SONARQUBE_VERSION) \
	podman-compose -f podman-compose-sonarqube.yaml up -d
	@sleep 30 && podman ps | grep sonarqube || echo "⚠️  Server may still be starting."

sonar-up-docker:
	@echo "🚀 Starting SonarQube (v$(SONARQUBE_VERSION)) with docker-compose …"
	SONARQUBE_VERSION=$(SONARQUBE_VERSION) \
	docker-compose -f podman-compose-sonarqube.yaml up -d
	@sleep 30 && docker ps | grep sonarqube || echo "⚠️  Server may still be starting."

## ─────────── Containerised Scanner CLI (Docker / Podman) ───────────────
sonar-submit-docker:
	@echo "📡 Scanning code with containerised Sonar Scanner CLI (Docker) …"
	docker run --rm \
		-e SONAR_HOST_URL="$(SONAR_HOST_URL)" \
		$(if $(SONAR_TOKEN),-e SONAR_TOKEN="$(SONAR_TOKEN)",) \
		-v "$(PROJECT_BASEDIR):/usr/src" \
		$(SONAR_SCANNER_IMAGE) \
		-Dproject.settings=$(SONAR_PROPS)

sonar-submit-podman:
	@echo "📡 Scanning code with containerised Sonar Scanner CLI (Podman) …"
	podman run --rm \
		--network $(SONAR_NETWORK) \
		-e SONAR_HOST_URL="$(SONAR_HOST_URL)" \
		$(if $(SONAR_TOKEN),-e SONAR_TOKEN="$(SONAR_TOKEN)",) \
		-v "$(PROJECT_BASEDIR):/usr/src:Z" \
		$(SONAR_SCANNER_IMAGE) \
		-Dproject.settings=$(SONAR_PROPS)

## ─────────── Python wrapper (pysonar-scanner) ───────────────────────────
pysonar-scanner:
	@echo "🐍 Scanning code with pysonar-scanner (PyPI) …"
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
	@echo "4. **Copy the token NOW** – you will not see it again."
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
# help: trivy                - Scan container image for CVEs (HIGH/CRIT). Needs podman socket enabled
.PHONY: trivy
trivy:
	@systemctl --user enable --now podman.socket
	@echo "🔎  trivy vulnerability scan…"
	@trivy --format table --severity HIGH,CRITICAL image localhost/$(PROJECT_NAME)/$(PROJECT_NAME)

# help: dockle               - Lint the built container image via tarball (no daemon/socket needed)
.PHONY: dockle
DOCKLE_IMAGE ?= $(IMG):latest         # mcpgateway/mcpgateway:latest from your build
dockle:
	@echo "🔎  dockle scan (tar mode) on $(DOCKLE_IMAGE)…"
	@command -v dockle >/dev/null || { \
		echo '❌  Dockle not installed. See https://github.com/goodwithtech/dockle'; exit 1; }

	# Pick docker or podman—whichever is on PATH
	@CONTAINER_CLI=$$(command -v docker || command -v podman) ; \
	[ -n "$$CONTAINER_CLI" ] || { echo '❌  docker/podman not found.'; exit 1; }; \
	TARBALL=$$(mktemp /tmp/$(PROJECT_NAME)-dockle-XXXXXX.tar) ; \
	echo "📦  Saving image to $$TARBALL…" ; \
	"$$CONTAINER_CLI" save $(DOCKLE_IMAGE) -o "$$TARBALL" || { rm -f "$$TARBALL"; exit 1; }; \
	echo "🧪  Running Dockle…" ; \
	dockle --no-color --exit-code 1 --exit-level warn --input "$$TARBALL" ; \
	rm -f "$$TARBALL"

# help: hadolint             - Lint Containerfile/Dockerfile(s) with hadolint
.PHONY: hadolint
HADOFILES := Containerfile Dockerfile Dockerfile.*

# Which files to check (edit as you like)
HADOFILES := Containerfile Containerfile.* Dockerfile Dockerfile.*

hadolint:
	@echo "🔎  hadolint scan…"

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
		echo "ℹ️  No Containerfile/Dockerfile found – nothing to scan."; \
	fi


# help: pip-audit            - Audit Python dependencies for published CVEs
.PHONY: pip-audit
pip-audit:
	@echo "🔒  pip-audit vulnerability scan…"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m pip install --quiet --upgrade pip-audit && \
		pip-audit --progress-spinner ascii --strict || true"

# =============================================================================
# 📦 DEPENDENCY MANAGEMENT
# =============================================================================
# help: 📦 DEPENDENCY MANAGEMENT
# help: deps-update          - Run update-deps.py to update all dependencies in pyproject.toml and docs/requirements.txt
# help: containerfile-update - Update base image in Containerfile to latest tag

.PHONY: deps-update containerfile-update

deps-update:
	@echo "⬆️  Updating project dependencies via update-deps.py…"
	@test -f update-deps.py || { echo "❌ update-deps.py not found in root directory."; exit 1; }
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python update-deps.py"
	@echo "✅ Dependencies updated in pyproject.toml and docs/requirements.txt"

containerfile-update:
	@echo "⬆️  Updating base image in Containerfile to :latest tag…"
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
	@echo "✅  Package verified – ready to publish."

publish: verify            ## Verify, then upload to PyPI
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && twine upload dist/*"
	@echo "🚀  Upload finished – check https://pypi.org/project/$(PROJECT_NAME)/"

publish-testpypi: verify   ## Verify, then upload to TestPyPI
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && twine upload --repository testpypi dist/*"
	@echo "🚀  Upload finished – check https://test.pypi.org/project/$(PROJECT_NAME)/"

# =============================================================================
# 🦭 PODMAN CONTAINER BUILD & RUN
# =============================================================================
# help: 🦭 PODMAN CONTAINER BUILD & RUN
# help: podman-dev           - Build development container image
# help: podman               - Build container image
# help: podman-prod          - Build production container image (using ubi-micro → scratch). Not supported on macOS.
# help: podman-run           - Run the container on HTTP  (port 4444)
# help: podman-run-shell     - Run the container on HTTP  (port 4444) and start a shell
# help: podman-run-ssl       - Run the container on HTTPS (port 4444, self-signed)
# help: podman-run-ssl-host  - Run the container on HTTPS with --network-host (port 4444, self-signed)
# help: podman-stop          - Stop & remove the container
# help: podman-test          - Quick curl smoke-test against the container
# help: podman-logs          - Follow container logs (⌃C to quit)

.PHONY: podman-dev podman podman-run podman-run-shell podman-run-ssl podman-stop podman-test

IMG               ?= $(PROJECT_NAME)/$(PROJECT_NAME)
IMG_DEV            = $(IMG)-dev
IMG_PROD           = $(IMG)

podman-dev:
	@echo "🦭  Building dev container…"
	podman build --ssh default --platform=linux/amd64 --squash \
	             -t $(IMG_DEV) .

podman:
	@echo "🦭  Building container using ubi9-minimal…"
	podman build --ssh default --platform=linux/amd64 --squash \
	             -t $(IMG_PROD) .
	podman images $(IMG_PROD)

podman-prod:
	@echo "🦭  Building production container from Containerfile.lite (ubi-micro → scratch)…"
	podman build --ssh default \
	             --platform=linux/amd64 \
	             --squash \
	             -f Containerfile.lite \
	             -t $(IMG_PROD) \
	             .
	podman images $(IMG_PROD)

## --------------------  R U N   (HTTP)  ---------------------------------------
podman-run:
	@echo "🚀  Starting podman container (HTTP)…"
	-podman stop $(PROJECT_NAME) 2>/dev/null || true
	-podman rm   $(PROJECT_NAME) 2>/dev/null || true
	podman run --name $(PROJECT_NAME) \
		--env-file=.env \
		-p 4444:4444 \
		--restart=always --memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl --fail http://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(IMG_PROD)
	@sleep 2 && podman logs $(PROJECT_NAME) | tail -n +1

podman-run-shell:
	@echo "🚀  Starting podman container shell…"
	podman run --name $(PROJECT_NAME)-shell \
		--env-file=.env \
		-p 4444:4444 \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		-it --rm $(IMG_PROD) \
		sh -c 'env; exec sh'

## --------------------  R U N   (HTTPS)  --------------------------------------
podman-run-ssl: certs
	@echo "🚀  Starting podman container (TLS)…"
	-podman stop $(PROJECT_NAME) 2>/dev/null || true
	-podman rm   $(PROJECT_NAME) 2>/dev/null || true
	podman run --name $(PROJECT_NAME) \
		--env-file=.env \
		-e SSL=true \
		-e CERT_FILE=certs/cert.pem \
		-e KEY_FILE=certs/key.pem \
		-v $(PWD)/certs:/app/certs:ro,Z \
		-p 4444:4444 \
		--restart=always --memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl -k --fail https://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(IMG_PROD)
	@sleep 2 && podman logs $(PROJECT_NAME) | tail -n +1

podman-run-ssl-host: certs
	@echo "🚀  Starting podman container (TLS) with host neworking…"
	-podman stop $(PROJECT_NAME) 2>/dev/null || true
	-podman rm   $(PROJECT_NAME) 2>/dev/null || true
	podman run --name $(PROJECT_NAME) \
		--network=host \
		--env-file=.env \
		-e SSL=true \
		-e CERT_FILE=certs/cert.pem \
		-e KEY_FILE=certs/key.pem \
		-v $(PWD)/certs:/app/certs:ro,Z \
		--restart=always --memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl -k --fail https://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(IMG_PROD)
	@sleep 2 && podman logs $(PROJECT_NAME) | tail -n +1

podman-stop:
	@echo "🛑  Stopping podman container…"
	-podman stop $(PROJECT_NAME) && podman rm $(PROJECT_NAME) || true

podman-test:
	@echo "🔬  Testing podman endpoint…"
	@echo "• HTTP  -> curl  http://localhost:4444/system/test"
	@echo "• HTTPS -> curl -k https://localhost:4444/system/test"

podman-logs:
	@echo "📜  Streaming podman logs (press Ctrl+C to exit)…"
	@podman logs -f $(PROJECT_NAME)

# help: podman-stats         - Show container resource stats (if supported)
.PHONY: podman-stats
podman-stats:
	@echo "📊  Showing Podman container stats…"
	@if podman info --format '{{.Host.CgroupManager}}' | grep -q 'cgroupfs'; then \
		echo "⚠️  podman stats not supported in rootless mode without cgroups v2 (e.g., WSL2)"; \
		echo "👉  Falling back to 'podman top'"; \
		podman top $(PROJECT_NAME); \
	else \
		podman stats --no-stream; \
	fi

# help: podman-top           - Show live top-level process info in container
.PHONY: podman-top
podman-top:
	@echo "🧠  Showing top-level processes in the Podman container…"
	podman top $(PROJECT_NAME)

# help: podman-shell         - Open an interactive shell inside the Podman container
.PHONY: podman-shell
podman-shell:
	@echo "🔧  Opening shell in Podman container…"
	@podman exec -it $(PROJECT_NAME) bash || podman exec -it $(PROJECT_NAME) /bin/sh

# =============================================================================
# 🐋 DOCKER BUILD & RUN
# =============================================================================
# help: 🐋 DOCKER BUILD & RUN
# help: docker-dev           - Build development Docker image
# help: docker               - Build production Docker image
# help: docker-prod          - Build production container image (using ubi-micro → scratch). Not supported on macOS.
# help: docker-run           - Run the container on HTTP  (port 4444)
# help: docker-run-ssl       - Run the container on HTTPS (port 4444, self-signed)
# help: docker-run-ssl-host  - Run the container on HTTPS with --network-host (port 4444, self-signed)
# help: docker-stop          - Stop & remove the container
# help: docker-test          - Quick curl smoke-test against the container
# help: docker-logs          - Follow container logs (⌃C to quit)

.PHONY: docker-dev docker docker-run docker-run-ssl docker-stop docker-test

IMG_DOCKER_DEV  = $(IMG)-dev:latest
IMG_DOCKER_PROD = $(IMG):latest

docker-dev:
	@echo "🐋  Building dev Docker image…"
	docker build --platform=linux/amd64 -t $(IMG_DOCKER_DEV) .

docker:
	@echo "🐋  Building production Docker image…"
	docker build --platform=linux/amd64 -t $(IMG_DOCKER_PROD) -f Containerfile .

docker-prod:
	@echo "🦭  Building production container from Containerfile.lite (ubi-micro → scratch)…"
	docker build \
	             --platform=linux/amd64 \
	             -f Containerfile.lite \
	             -t $(IMG_PROD) \
	             .
	docker images $(IMG_PROD)

## --------------------  R U N   (HTTP)  ---------------------------------------
docker-run:
	@echo "🚀  Starting Docker container (HTTP)…"
	-docker stop $(PROJECT_NAME) 2>/dev/null || true
	-docker rm   $(PROJECT_NAME) 2>/dev/null || true
	docker run --name $(PROJECT_NAME) \
		--env-file=.env \
		-p 4444:4444 \
		--restart=always --memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl --fail http://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(IMG_DOCKER_PROD)
	@sleep 2 && docker logs $(PROJECT_NAME) | tail -n +1

## --------------------  R U N   (HTTPS)  --------------------------------------
docker-run-ssl: certs
	@echo "🚀  Starting Docker container (TLS)…"
	-docker stop $(PROJECT_NAME) 2>/dev/null || true
	-docker rm   $(PROJECT_NAME) 2>/dev/null || true
	docker run --name $(PROJECT_NAME) \
		--env-file=.env \
		-e SSL=true \
		-e CERT_FILE=certs/cert.pem \
		-e KEY_FILE=certs/key.pem \
		-v $(PWD)/certs:/app/certs:ro \
		-p 4444:4444 \
		--restart=always --memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl -k --fail https://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(IMG_DOCKER_PROD)
	@sleep 2 && docker logs $(PROJECT_NAME) | tail -n +1

docker-run-ssl-host: certs
	@echo "🚀  Starting Docker container (TLS) with host neworking…"
	-docker stop $(PROJECT_NAME) 2>/dev/null || true
	-docker rm   $(PROJECT_NAME) 2>/dev/null || true
	docker run --name $(PROJECT_NAME) \
		--env-file=.env \
		--network=host \
		-e SSL=true \
		-e CERT_FILE=certs/cert.pem \
		-e KEY_FILE=certs/key.pem \
		-v $(PWD)/certs:/app/certs:ro \
		-p 4444:4444 \
		--restart=always --memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl -k --fail https://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(IMG_DOCKER_PROD)
	@sleep 2 && docker logs $(PROJECT_NAME) | tail -n +1

docker-stop:
	@echo "🛑  Stopping Docker container…"
	-docker stop $(PROJECT_NAME) && docker rm $(PROJECT_NAME) || true

docker-test:
	@echo "🔬  Testing Docker endpoint…"
	@echo "• HTTP  -> curl  http://localhost:4444/system/test"
	@echo "• HTTPS -> curl -k https://localhost:4444/system/test"


docker-logs:
	@echo "📜  Streaming Docker logs (press Ctrl+C to exit)…"
	@docker logs -f $(PROJECT_NAME)

# help: docker-stats         - Show container resource usage stats (non-streaming)
.PHONY: docker-stats
docker-stats:
	@echo "📊  Showing Docker container stats…"
	@docker stats --no-stream || { echo "⚠️  Failed to fetch docker stats. Falling back to 'docker top'…"; docker top $(PROJECT_NAME); }

# help: docker-top           - Show top-level process info in Docker container
.PHONY: docker-top
docker-top:
	@echo "🧠  Showing top-level processes in the Docker container…"
	docker top $(PROJECT_NAME)

# help: docker-shell         - Open an interactive shell inside the Docker container
.PHONY: docker-shell
docker-shell:
	@echo "🔧  Opening shell in Docker container…"
	@docker exec -it $(PROJECT_NAME) bash || docker exec -it $(PROJECT_NAME) /bin/sh


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

# ─────────────────────────────────────────────────────────────────────────────
# You may **force** a specific binary by exporting COMPOSE_CMD, e.g.:
#   export COMPOSE_CMD=podman-compose          # classic wrapper
#   export COMPOSE_CMD="podman compose"        # Podman v4/v5 built-in
#   export COMPOSE_CMD="docker compose"        # Docker CLI plugin (v2)
#
# If COMPOSE_CMD is empty, we autodetect in this order:
#   1. podman-compose   2. podman compose   3. docker compose
# ─────────────────────────────────────────────────────────────────────────────
COMPOSE_CMD ?=
ifeq ($(strip $(COMPOSE_CMD)),)
  COMPOSE_CMD := $(shell \
    command -v podman-compose    >/dev/null 2>&1 && echo podman-compose   || \
    command -v "podman compose" >/dev/null 2>&1 && echo "podman compose" || \
    echo "docker compose" )
endif
COMPOSE_FILE ?= docker-compose.yml

define COMPOSE
$(COMPOSE_CMD) -f $(COMPOSE_FILE)
endef

.PHONY: compose-up compose-restart compose-build compose-pull \
        compose-logs compose-ps compose-shell compose-stop compose-down \
        compose-rm compose-clean

compose-up:
	@echo "🚀  Using $(COMPOSE_CMD); starting stack..."
	$(COMPOSE) up -d

compose-restart:
	@echo "🔄  Restarting stack (build + pull if needed)…"
	$(COMPOSE) up -d --pull=missing --build

compose-build:
	$(COMPOSE) build

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

# Removes **containers + named volumes** – irreversible!
compose-clean:
	$(COMPOSE) down -v


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
#     • .env.ce   – IBM Cloud / Code Engine deployment vars
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
	@bash -eu -o pipefail -c '\
		echo "🔍  Verifying required IBM Cloud variables (.env.ce)…"; \
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
			echo "⚠️   IBMCLOUD_API_KEY not set – interactive SSO login will be used"; \
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
	@echo "☁️  Detecting OS and installing IBM Cloud CLI…"
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
	@echo "✅ CLI installed. Installing required plugins…"
	@ibmcloud plugin install container-registry -f
	@ibmcloud plugin install code-engine -f
	@ibmcloud --version

ibmcloud-login:
	@echo "🔐 Starting IBM Cloud login…"
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
	@echo "🎯 Targeting region and resource group…"
	@ibmcloud target -r "$(IBMCLOUD_REGION)" -g "$(IBMCLOUD_RESOURCE_GROUP)"
	@ibmcloud target

ibmcloud-ce-login:
	@echo "🎯 Targeting Code Engine project '$(IBMCLOUD_PROJECT)' in region '$(IBMCLOUD_REGION)'…"
	@ibmcloud ce project select --name "$(IBMCLOUD_PROJECT)"

ibmcloud-list-containers:
	@echo "📦 Listing Code Engine images"
	ibmcloud cr images
	@echo "📦 Listing Code Engine applications…"
	@ibmcloud ce application list

ibmcloud-tag:
	@echo "🏷️  Tagging image $(IBMCLOUD_IMG_PROD) → $(IBMCLOUD_IMAGE_NAME)"
	podman tag $(IBMCLOUD_IMG_PROD) $(IBMCLOUD_IMAGE_NAME)
	podman images | head -3

ibmcloud-push:
	@echo "📤 Logging into IBM Container Registry and pushing image…"
	@ibmcloud cr login
	podman push $(IBMCLOUD_IMAGE_NAME)

ibmcloud-deploy:
	@echo "🚀 Deploying image to Code Engine as '$(IBMCLOUD_CODE_ENGINE_APP)' using registry secret $(IBMCLOUD_REGISTRY_SECRET)…"
	@if ibmcloud ce application get --name $(IBMCLOUD_CODE_ENGINE_APP) > /dev/null 2>&1; then \
		echo "🔁 Updating existing app…"; \
		ibmcloud ce application update --name $(IBMCLOUD_CODE_ENGINE_APP) \
			--image $(IBMCLOUD_IMAGE_NAME) \
			--cpu $(IBMCLOUD_CPU) --memory $(IBMCLOUD_MEMORY) \
			--registry-secret $(IBMCLOUD_REGISTRY_SECRET); \
	else \
		echo "🆕 Creating new app…"; \
		ibmcloud ce application create --name $(IBMCLOUD_CODE_ENGINE_APP) \
			--image $(IBMCLOUD_IMAGE_NAME) \
			--cpu $(IBMCLOUD_CPU) --memory $(IBMCLOUD_MEMORY) \
			--port 4444 \
			--registry-secret $(IBMCLOUD_REGISTRY_SECRET); \
	fi

ibmcloud-ce-logs:
	@echo "📜 Streaming logs for '$(IBMCLOUD_CODE_ENGINE_APP)'…"
	@ibmcloud ce application logs --name $(IBMCLOUD_CODE_ENGINE_APP) --follow

ibmcloud-ce-status:
	@echo "📈 Application status for '$(IBMCLOUD_CODE_ENGINE_APP)'…"
	@ibmcloud ce application get --name $(IBMCLOUD_CODE_ENGINE_APP)

ibmcloud-ce-rm:
	@echo "🗑️  Deleting Code Engine app: $(IBMCLOUD_CODE_ENGINE_APP)…"
	@ibmcloud ce application delete --name $(IBMCLOUD_CODE_ENGINE_APP) -f


# =============================================================================
# 🧪 MINIKUBE LOCAL CLUSTER
# =============================================================================
# A self‑contained block with sensible defaults, overridable via the CLI.
# App is accessible after: kubectl port-forward svc/mcp-context-forge 8080:80
# Examples:
#   make minikube-start MINIKUBE_DRIVER=podman
#   make minikube-image-load TAG=v0.1.2
#
#   # Push via the internal registry (registry addon):
#   # 1️⃣ Discover the randomized host‑port (docker driver only):
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
MINIKUBE_DRIVER  ?= docker         # docker | podman | hyperkit | virtualbox …
MINIKUBE_CPUS    ?= 4              # vCPUs to allocate
MINIKUBE_MEMORY  ?= 6g             # RAM (supports m / g suffix)
# Enabled addons – tweak to suit your workflow (`minikube addons list`).
# • ingress / ingress-dns      – Ingress controller + CoreDNS wildcard hostnames
# • metrics-server             – HPA / kubectl top
# • dashboard                  – Web UI (make minikube-dashboard)
# • registry                   – Local Docker registry, *dynamic* host-port
# • registry-aliases           – Adds handy DNS names inside the cluster
MINIKUBE_ADDONS  ?= ingress ingress-dns metrics-server dashboard registry registry-aliases
# OCI image tag to preload into the cluster.
# • By default we point to the *local* image built via `make docker-prod`, e.g.
#   mcpgateway/mcpgateway:latest.  Override with IMAGE=<repo:tag> to use a
#   remote registry (e.g. ghcr.io/ibm/mcp-context-forge:v0.1.1).
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
# help: minikube-dashboard      - Print & (best‑effort) open the Kubernetes dashboard URL
# help: minikube-image-load     - Load $(IMAGE) into Minikube container runtime
# help: minikube-k8s-apply      - Apply manifests from k8s/ - access with `kubectl port-forward svc/mcp-context-forge 8080:80`
# help: minikube-status         - Cluster + addon health overview
# help: minikube-context        - Switch kubectl context to Minikube
# help: minikube-ssh            - SSH into the Minikube VM
# help: minikube-reset          - 🚨 delete ➜ start ➜ apply ➜ status (idempotent dev helper)
# help: minikube-registry-url 	- Echo the dynamic registry URL (e.g. http://localhost:32790)

.PHONY: minikube-install helm-install minikube-start minikube-stop minikube-delete \
        minikube-tunnel minikube-dashboard minikube-image-load minikube-k8s-apply \
        minikube-status minikube-context minikube-ssh minikube-reset minikube-registry-url

# -----------------------------------------------------------------------------
# 🚀  INSTALLATION HELPERS
# -----------------------------------------------------------------------------
minikube-install:
	@echo "💻 Detecting OS and installing Minikube + kubectl…"
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
	@echo "🚀 Starting Minikube profile '$(MINIKUBE_PROFILE)' (driver=$(MINIKUBE_DRIVER)) …"
	minikube start -p $(MINIKUBE_PROFILE) \
	  --driver=$(MINIKUBE_DRIVER) \
	  --cpus=$(MINIKUBE_CPUS) --memory=$(MINIKUBE_MEMORY)
	@echo "🔌 Enabling addons: $(MINIKUBE_ADDONS)"
	@for addon in $(MINIKUBE_ADDONS); do \
	  minikube addons enable $$addon -p $(MINIKUBE_PROFILE); \
	done

minikube-stop:
	@echo "🛑 Stopping Minikube …"
	minikube stop -p $(MINIKUBE_PROFILE)

minikube-delete:
	@echo "🗑 Deleting Minikube profile '$(MINIKUBE_PROFILE)' …"
	minikube delete -p $(MINIKUBE_PROFILE)

# -----------------------------------------------------------------------------
# 🛠  UTILITIES
# -----------------------------------------------------------------------------
minikube-tunnel:
	@echo "🌐 Starting minikube tunnel (Ctrl+C to quit) …"
	minikube -p $(MINIKUBE_PROFILE) tunnel

minikube-dashboard:
	@echo "📊 Fetching dashboard URL …"
	@minikube dashboard -p $(MINIKUBE_PROFILE) --url | { \
	  read url; \
	  echo "🔗 Dashboard: $$url"; \
	  ( command -v xdg-open >/dev/null && xdg-open $$url >/dev/null 2>&1 ) || \
	  ( command -v open     >/dev/null && open $$url     >/dev/null 2>&1 ) || true; \
	}

minikube-context:
	@echo "🎯 Switching kubectl context to Minikube …"
	kubectl config use-context minikube

minikube-ssh:
	@echo "🔧 Connecting to Minikube VM (exit with Ctrl+D) …"
	minikube ssh -p $(MINIKUBE_PROFILE)

# -----------------------------------------------------------------------------
# 📦  IMAGE & MANIFEST HANDLING
# -----------------------------------------------------------------------------
minikube-image-load:
	@echo "📦 Loading $(IMAGE) into Minikube …"
	@if ! docker image inspect $(IMAGE) >/dev/null 2>&1; then \
	  echo "❌ $(IMAGE) not found locally. Build or pull it first."; exit 1; \
	fi
	minikube image load $(IMAGE) -p $(MINIKUBE_PROFILE)

minikube-k8s-apply:
	@echo "🧩 Applying k8s manifests in ./k8s …"
	@kubectl apply -f k8s/ --recursive

# -----------------------------------------------------------------------------
# 🔍  Utility: print the current registry URL (host‑port) – works after cluster
#             + registry addon are up.
# -----------------------------------------------------------------------------
minikube-registry-url:
	@echo "📦 Internal registry URL:" && \
	minikube -p $(MINIKUBE_PROFILE) service registry -n kube-system --url || \
	echo "⚠️  Registry addon not ready – run make minikube-start first."

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
	@echo "📦 Installing Helm CLI…"
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
# 🚢 ARGO CD – GITOPS
# TODO: change default to custom namespace (e.g. mcp-gitops)
# =============================================================================
# help: 🚢 ARGO CD – GITOPS
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
	@echo "🔧 Installing Argo CD CLI…"
	@if command -v argocd >/dev/null 2>&1; then echo "✅ argocd already present"; \
	elif [ "$$(uname)" = "Darwin" ];  then brew install argocd; \
	elif [ "$$(uname)" = "Linux" ];   then curl -sSL -o /tmp/argocd \
	     https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64 && \
	     sudo install -m 555 /tmp/argocd /usr/local/bin/argocd; \
	else echo "❌ Unsupported OS – install argocd manually"; exit 1; fi

argocd-install:
	@echo "🚀 Installing Argo CD into Minikube…"
	kubectl create namespace $(ARGOCD_NS) --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -n $(ARGOCD_NS) \
	  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
	@echo "⏳ Waiting for Argo CD server pod…"
	kubectl -n $(ARGOCD_NS) rollout status deploy/argocd-server

argocd-password:
	@kubectl -n $(ARGOCD_NS) get secret argocd-initial-admin-secret \
	  -o jsonpath='{.data.password}' | base64 -d ; echo

argocd-forward:
	@echo "🌐 Port-forward http://localhost:$(ARGOCD_PORT) → svc/argocd-server:443 (Ctrl-C to stop)…"
	kubectl -n $(ARGOCD_NS) port-forward svc/argocd-server $(ARGOCD_PORT):443

argocd-login: argocd-cli-install
	@echo "🔐 Logging into Argo CD CLI…"
	@PASS=$$(kubectl -n $(ARGOCD_NS) get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d); \
	argocd login localhost:$(ARGOCD_PORT) --username admin --password $$PASS --insecure

argocd-app-bootstrap:
	@echo "🚀 Creating Argo CD application $(ARGOCD_APP)…"
	-argocd app create $(ARGOCD_APP) \
	    --repo $(GIT_REPO) \
	    --path $(GIT_PATH) \
	    --dest-server https://kubernetes.default.svc \
	    --dest-namespace default \
	    --sync-policy automated \
	    --revision HEAD || true
	argocd app sync $(ARGOCD_APP)

argocd-app-sync:
	@echo "🔄  Syncing Argo CD application $(ARGOCD_APP)…"
	argocd app sync $(ARGOCD_APP)

# =============================================================================
# 🏠 LOCAL PYPI SERVER
# Currently blocked by: https://github.com/pypiserver/pypiserver/issues/630
# =============================================================================
# help: 🏠 LOCAL PYPI SERVER
# help: local-pypi-install     - Install pypiserver for local testing
# help: local-pypi-start       - Start local PyPI server on :8084 (no auth)
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
	@echo "🚀  Starting local PyPI server on http://localhost:8084..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	export PYPISERVER_BOTTLE_MEMFILE_MAX_OVERRIDE_BYTES=10485760 && \
	pypi-server run -p 8084 -a . -P . $(LOCAL_PYPI_DIR) --hash-algo=sha256 & echo \$! > $(LOCAL_PYPI_PID)"
	@sleep 2
	@echo "✅  Local PyPI server started at http://localhost:8084"
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
	@if ! curl -s http://localhost:8084 >/dev/null 2>&1; then \
		echo "❌  Local PyPI server not running on port 8084. Run 'make local-pypi-start' first."; \
		exit 1; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	twine upload --verbose --repository-url http://localhost:8084 --skip-existing dist/*"
	@echo "✅  Package uploaded to local PyPI"
	@echo "🌐  Browse packages: http://localhost:8084"

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
		if curl -s http://localhost:8084 >/dev/null 2>&1; then \
			echo "🌐  Server on port 8084: http://localhost:8084"; \
		elif curl -s $(LOCAL_PYPI_URL) >/dev/null 2>&1; then \
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
		echo "$pids" | xargs -r kill 2>/dev/null || true; \
		sleep 1; \
		echo "$pids" | xargs -r kill -9 2>/dev/null || true; \
	fi
	@# Force kill anything using the port
	@if lsof -ti :$(DEVPI_PORT) >/dev/null 2>&1; then \
		echo "⚠️   Port $(DEVPI_PORT) still in use, force killing..."; \
		lsof -ti :$(DEVPI_PORT) | xargs -r kill -9 2>/dev/null || true; \
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
#      override on the CLI:  make VER=0.2.1 devpi-delete
# ─────────────────────────────────────────────────────────────────────────────
VER ?= $(shell python -c "import tomllib, pathlib; \
print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])" \
2>/dev/null || echo 0.0.0)

devpi-delete: devpi-setup-user                 ## Delete mcp-contextforge-gateway==$(VER) from index
	@echo "🗑️   Removing mcp-contextforge-gateway==$(VER) from $(DEVPI_INDEX)…"
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
SHELL_SCRIPTS := $(shell find . -type f -name '*.sh' -not -path './node_modules/*')

.PHONY: shell-linters-install shell-lint shfmt-fix shellcheck bashate

shell-linters-install:     ## 🔧  Install shellcheck, shfmt, bashate
	@echo "🔧  Installing/ensuring shell linters are present…"
	@set -e ; \
	# -------- ShellCheck -------- \
	if ! command -v shellcheck >/dev/null 2>&1 ; then \
	  echo "🛠  Installing ShellCheck…" ; \
	  case "$$(uname -s)" in \
	    Darwin)  brew install shellcheck ;; \
	    Linux)   { command -v apt-get && sudo apt-get update -qq && sudo apt-get install -y shellcheck ; } || \
	             { command -v dnf && sudo dnf install -y ShellCheck ; } || \
	             { command -v pacman && sudo pacman -Sy --noconfirm shellcheck ; } || true ;; \
	    *) echo "⚠️  Please install ShellCheck manually" ;; \
	  esac ; \
	fi ; \
	# -------- shfmt (Go) -------- \
	if ! command -v shfmt >/dev/null 2>&1 ; then \
	  echo "🛠  Installing shfmt…" ; \
	  GO111MODULE=on go install mvdan.cc/sh/v3/cmd/shfmt@latest || \
	  { echo "⚠️  go not found – install Go or brew/apt shfmt package manually"; } ; \
	  export PATH=$$PATH:$$HOME/go/bin ; \
	fi ; \
	# -------- bashate (pip) ----- \
	if ! $(VENV_DIR)/bin/bashate -h >/dev/null 2>&1 ; then \
	  echo "🛠  Installing bashate (into venv)…" ; \
	  test -d "$(VENV_DIR)" || $(MAKE) venv ; \
	  /bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m pip install --quiet bashate" ; \
	fi
	@echo "✅  Shell linters ready."

# -----------------------------------------------------------------------------

shell-lint: shell-linters-install  ## 🔍  Run shfmt, ShellCheck & bashate
	@echo "🔍  Running shfmt (diff-only)…"
	@shfmt -d -i 4 -ci $(SHELL_SCRIPTS) || true
	@echo "🔍  Running ShellCheck…"
	@shellcheck $(SHELL_SCRIPTS) || true
	@echo "🔍  Running bashate…"
	@$(VENV_DIR)/bin/bashate -C $(SHELL_SCRIPTS) || true
	@echo "✅  Shell lint complete."


shfmt-fix: shell-linters-install   ## 🎨  Auto-format *.sh in place
	@echo "🎨  Formatting shell scripts with shfmt -w…"
	@shfmt -w -i 4 -ci $(SHELL_SCRIPTS)
	@echo "✅  shfmt formatting done."
