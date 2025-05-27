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
	uvicorn mcpgateway.main:app --reload --reload-exclude='public/'

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
test:
	@echo "🧪 Running tests..."
	@test -d "$(VENV_DIR)" || make venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python -m pip install pytest pytest-asyncio pytest-cov -q && python -m pytest --maxfail=0 --disable-warnings -v"

pytest-examples:
	@echo "🧪 Testing README examples..."
	@test -d "$(VENV_DIR)" || make venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python -m pip install pytest pytest-examples -q && pytest -v test_readme.py"

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
	@python3 -m pip install snakefood3
	@python3 -m snakefood3 app > snakefood.dot
	@dot -Tpng -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=12 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=10 -Efontcolor=black snakefood.dot -o $(DOCS_DIR)/docs/design/images/snakefood.png || true
	@pyreverse --colorized app || true
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
		   pytype check-manifest

.PHONY: lint $(LINTERS) black fawltydeps wily depend snakeviz pstats \
        spellcheck-sort tox \
		pytype check-manifest

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
	autoflake --in-place --remove-all-unused-imports \
	          --remove-unused-variables -r mcpgateway

black:                              ## 🎨  Reformat code with black
	@echo "🎨  black …" && black -l 200 mcpgateway

isort:                              ## 🔀  Sort imports
	@echo "🔀  isort …" && isort .

flake8:                             ## 🐍  flake8 checks
	flake8 mcpgateway

pylint:                             ## 🐛  pylint checks
	pylint mcpgateway

mypy:                               ## 🏷️  mypy type-checking
	mypy mcpgateway

bandit:                             ## 🛡️  bandit security scan
	bandit -r mcpgateway

pydocstyle:                         ## 📚  Docstring style
	pydocstyle mcpgateway

pycodestyle:                        ## 📝  Simple PEP-8 checker
	pycodestyle mcpgateway --max-line-length=200

pre-commit:                         ## 🪄  Run pre-commit hooks
	pre-commit run --all-files --show-diff-on-failure

ruff:                               ## ⚡  Ruff lint + format
	ruff check mcpgateway && ruff format mcpgateway

ty:                               ## ⚡  Ty type checker
	ty check mcpgateway

pyright:                            ## 🏷️  Pyright type-checking
	pyright mcpgateway

radon:                              ## 📈  Complexity / MI metrics
	radon mi -s mcpgateway && \
	radon cc -s mcpgateway && \
	radon hal mcpgateway && \
	radon raw -s mcpgateway

pyroma:                             ## 📦  Packaging metadata check
	pyroma -d .

importchecker:                      ## 🧐  Orphaned import detector
	importchecker .

spellcheck:                         ## 🔤  Spell-check
	pyspelling || true

fawltydeps:                         ## 🏗️  Dependency sanity
	fawltydeps --detailed --exclude 'docs/**' . || true

wily:                               ## 📈  Maintainability report
	@git stash --quiet
	@wily build -n 10 . > /dev/null || true
	@wily report . || true
	@git stash pop --quiet

pyre:                               ## 🧠  Facebook Pyre analysis
	pyre

depend:                             ## 📦  List dependencies
	pdm list --freeze

snakeviz:                           ## 🐍  Interactive profile visualiser
	@python -m cProfile -o mcp.prof app/server.py && snakeviz mcp.prof --server

pstats:                             ## 📊  Static call-graph image
	@python -m cProfile -o mcp.pstats app/server.py && \
	 gprof2dot -w -e 3 -n 3 -s -f pstats mcp.pstats | \
	 dot -Tpng -o $(DOCS_DIR)/pstats.png

spellcheck-sort: .spellcheck-en.txt ## 🔤  Sort spell-list
	sort -d -f -o $< $<

tox:                                ## 🧪  Multi-Python tox matrix
	@echo "🧪  Running tox …"
	uv pip install tox-travis tox-pdm
	pdm add -G dev
	pdm python install 3.11 3.12
	python -m tox -p 2

.PHONY: sbom
sbom:
	@echo "🛡️   Generating SBOM & security report…"
	@rm -Rf "$(VENV_DIR).sbom"
	@python3 -m venv "$(VENV_DIR).sbom"
	@/bin/bash -c "source $(VENV_DIR).sbom/bin/activate && python3 -m pip install --upgrade pip setuptools pdm uv && python3 -m uv pip install .[dev]"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install cyclonedx-bom sbom2doc"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python -m cyclonedx_py environment --validate '$(VENV_DIR).sbom' --pyproject pyproject.toml --gather-license-texts > $(PROJECT_NAME).sbom.json"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && sbom2doc -i $(PROJECT_NAME).sbom.json -f markdown -o $(DOCS_DIR)/docs/test/sbom.md"
	@trivy sbom $(PROJECT_NAME).sbom.json | tee -a $(DOCS_DIR)/docs/test/sbom.md
	@/bin/bash -c "source $(VENV_DIR).sbom/bin/activate && python3 -m pdm outdated | tee -a $(DOCS_DIR)/docs/test/sbom.md"

pytype:
	@echo "🧠  Pytype analysis…"
	pytype -V 3.12 -j auto mcpgateway

check-manifest:
	@echo "📦  Verifying MANIFEST.in completeness…"
	check-manifest

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
	python -m pysonar_scanner \
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
		python -m pip install --quiet --upgrade pip-audit && \
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
.PHONY: dist wheel sdist verify publish

dist: clean                ## Build wheel + sdist
	python -m build
	@echo "🛠  Wheel & sdist written to ./dist"

wheel:                     ## Build wheel only
	python -m build -w
	@echo "🛠  Wheel written to ./dist"

sdist:                     ## Build source distribution only
	python -m build -s
	@echo "🛠  Source distribution written to ./dist"

verify: dist               ## Build, run metadata & manifest checks
	twine check dist/*                 # metadata sanity
	check-manifest                     # sdist completeness
	pyroma -d .                        # metadata quality score
	@echo "✅  Package verified – ready to publish."

publish: verify            ## Verify, then upload to PyPI
	twine upload dist/*               # creds via env vars or ~/.pypirc
	@echo "🚀  Upload finished – check https://pypi.org/project/$(PROJECT_NAME)/"

# =============================================================================
# 🦭 PODMAN CONTAINER BUILD & RUN
# =============================================================================
# help: 🦭 PODMAN CONTAINER BUILD & RUN
# help: podman-dev           - Build development container image
# help: podman               - Build production container image
# help: podman-run           - Run the container on HTTP  (port 4444)
# help: podman-run-shell     - Run the container on HTTP  (port 4444) and start a shell
# help: podman-run-ssl       - Run the container on HTTPS (port 4444, self-signed)
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
# help: docker-run           - Run the container on HTTP  (port 4444)
# help: docker-run-ssl       - Run the container on HTTPS (port 4444, self-signed)
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
