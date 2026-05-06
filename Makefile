# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   🐍 ContextForge AI Gateway - Makefile
#   (AI Gateway, registry, and proxy for MCP, A2A, and REST/gRPC APIs)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Authors: Mihai Criveti, Manav Gupta
# Description: Build & automation helpers for ContextForge project
# Usage: run `make` or `make help` to view available targets
#
# help: 🐍 ContextForge AI Gateway  (AI Gateway, registry, and proxy for MCP, A2A, and REST/gRPC APIs)
#
# ──────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

# Read values from .env.make
-include .env.make

# Rust build configuration (set to 1 to enable Rust builds, 0 to disable)
# Default is disabled to avoid requiring Rust toolchain for standard builds
ENABLE_RUST_BUILD ?= 0
ENABLE_RUST_MCP_RMCP_BUILD ?=
RUST_MCP_BUILD ?= 0
RUST_MCP_MODE ?= off
RUST_MCP_LOG ?= warn

# Project variables
PROJECT_NAME      = mcpgateway
DOCS_DIR          = docs
HANDSDOWN_PARAMS  = -o $(DOCS_DIR)/ -n $(PROJECT_NAME) --name "ContextForge" --cleanup

TEST_DOCS_DIR ?= $(DOCS_DIR)/docs/test
MCP_2025_TEST_DIR ?= tests/compliance/mcp_2025_11_25
MCP_2025_ARTIFACTS_DIR ?= artifacts/mcp-2025-11-25
MCP_2025_MARKER ?= mcp20251125
MCP_2025_PYTEST_ARGS ?=
MCP_2025_BASE_URL ?=
MCP_2025_RPC_PATH ?= /mcp/
MCP_2025_BEARER_TOKEN ?=

# Virtual-environment variables
VENV_DIR ?= $(CURDIR)/.venv

# -----------------------------------------------------------------------------
# Project-wide clean-up targets
# -----------------------------------------------------------------------------
COVERAGE_DIR ?= $(DOCS_DIR)/docs/coverage
LICENSES_MD  ?= $(DOCS_DIR)/docs/test/licenses.md
METRICS_MD   ?= $(DOCS_DIR)/docs/metrics/loc.md

DIRS_TO_CLEAN := __pycache__ .pytest_cache .tox .ruff_cache .pyre .mypy_cache .pytype \
	dist build site .eggs *.egg-info .cache htmlcov certs \
	$(VENV_DIR) $(VENV_DIR).sbom $(COVERAGE_DIR) htmlcov-doctest htmlcov_ai_normalizer \
	node_modules .mutmut-cache html

FILES_TO_CLEAN := .coverage .coverage.* coverage.xml mcp.prof mcp.pstats mcp.db-* \
	$(PROJECT_NAME).sbom.json \
	snakefood.dot packages.dot classes.dot \
	$(DOCS_DIR)/pstats.png \
	$(DOCS_DIR)/docs/test/sbom.md \
	$(LICENSE_CHECK_REPORT) \
	$(DOCS_DIR)/docs/test/{unittest,full,index,test}.md \
	$(DOCS_DIR)/docs/images/coverage.svg $(LICENSES_MD) $(METRICS_MD) \
	*.db *.sqlite *.sqlite3 mcp.db-journal *.py,cover \
	.depsorter_cache.json .depupdate.* \
	devskim-results.sarif \
	*.tar.gz *.tar.bz2 *.tar.xz *.zip *.deb \
	*.log mcpgateway.sbom.xml

# Extra cleanup targets that are easiest to remove by explicit path/pattern.
EXTRA_DIRS_TO_CLEAN := reports test-results tests/playwright/reports \
	tests/playwright/screenshots tests/playwright/videos \
	tests/jmeter/results tests/async/profiles tests/async/reports \
	tests/migration/reports tests/migration/logs .jmeter

EXTRA_FILES_TO_CLEAN := docs/docs/security/report.md \
	playwright-report-*.html test-results-*.xml \
	logs/db-queries.jsonl \
	snyk-code-results.json snyk-container-results.json \
	snyk-iac-compose-results.json snyk-iac-docker-results.json \
	snyk-helm-results.json aibom.json sbom-cyclonedx.json sbom-spdx.json

COVERAGE_DIR ?= $(DOCS_DIR)/docs/coverage
LICENSES_MD  ?= $(DOCS_DIR)/docs/test/licenses.md
LICENSE_CHECK_REPORT ?= $(DOCS_DIR)/docs/test/license-check-report.json
LICENSE_CHECK_POLICY ?= license-policy.toml
LICENSE_CHECK_INCLUDE_DEV_GROUPS ?= false
LICENSE_CHECK_SUMMARY_ONLY ?= false
METRICS_MD   ?= $(DOCS_DIR)/docs/metrics/loc.md

# -----------------------------------------------------------------------------
# Container resource configuration
# -----------------------------------------------------------------------------
CONTAINER_MEMORY = 2048m
CONTAINER_CPUS   = 2

# -----------------------------------------------------------------------------
# OS Specific
# -----------------------------------------------------------------------------
# The -r flag for xargs is GNU-specific and will fail on macOS
XARGS_FLAGS := $(shell [ "$$(uname)" = "Darwin" ] && echo "" || echo "-r")

# -----------------------------------------------------------------------------
#  Allow override of the image to be used in various docker compose
#  up and down actions
# -----------------------------------------------------------------------------
ifndef IMAGE_LOCAL
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
endif

# =============================================================================
# 📖 DYNAMIC HELP
# =============================================================================
.PHONY: help
help:
	@grep "^# help\:" Makefile | grep -v grep | sed 's/\# help\: //' | sed 's/\# help\://'
	@if grep -q "^# deprecated:" Makefile; then \
		printf '\n\033[33m⚠️  DEPRECATED TARGETS (still work, will be removed in stated version)\033[0m\n'; \
		grep "^# deprecated:" Makefile | sed 's/^# deprecated: //' | while IFS= read -r line; do \
			printf '  \033[2;33m%s\033[0m\n' "$$line"; \
		done; \
	fi

# -----------------------------------------------------------------------------
# 🔧 SYSTEM-LEVEL DEPENDENCIES
# -----------------------------------------------------------------------------
# help: 🔧 SYSTEM-LEVEL DEPENDENCIES (DEV BUILD ONLY)
# help: os-deps              - Install Graphviz, Pandoc, SCC used for dev docs generation
OS_DEPS_SCRIPT := ./os_deps.sh

.PHONY: os-deps
os-deps: $(OS_DEPS_SCRIPT)
	@bash $(OS_DEPS_SCRIPT)


# -----------------------------------------------------------------------------
# 🔧 HELPER SCRIPTS
# -----------------------------------------------------------------------------

# Boolean normalizer: returns non-empty only for explicit truth values.
# Usage: $(if $(call is_true,$(VAR)),yes-branch,no-branch)
is_true = $(filter 1 true yes,$(1))

# Deprecation warning for aliased targets.
# Usage: $(call deprecated_target,old-name,replacement invocation,removal-version)
define deprecated_target
	@printf '\n  ⚠️  WARNING: "%s" is deprecated. Use "%s" instead.\n' '$(1)' '$(2)'
	@printf '     This alias will be removed in v%s.\n\n' '$(3)'
endef

# Helper to ensure a Python package is installed in venv (uses uv to avoid pip corruption)
define ensure_pip_package
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip show $(1) >/dev/null 2>&1 || \
		$(UV_BIN) pip install -q $(1)"
endef

# =============================================================================
# 🌱 VIRTUAL ENVIRONMENT & INSTALLATION
# =============================================================================
# help: 🌱 VIRTUAL ENVIRONMENT & INSTALLATION
# help: uv                   - Ensure uv is installed or install it if needed
# help: venv                 - Create a fresh virtual environment with uv & friends
# help: activate             - Activate the virtual environment in the current shell
# help: install              - Install project into the venv
# help: install-dev          - Install project (incl. dev deps) into the venv
# help: install-db           - Install project (incl. postgres and redis) into venv
# help: update               - Update all installed deps inside the venv
.PHONY: uv
uv:
	@if ! type uv >/dev/null 2>&1 && ! test -x "$(HOME)/.local/bin/uv"; then \
		echo "❌ 'uv' not found."; \
		if type brew >/dev/null 2>&1; then \
			echo "💡 Install 'uv' via Homebrew or another trusted package manager:"; \
			echo "   brew install uv"; \
			exit 1; \
		else \
			echo "💡 Install uv from a trusted package manager or pinned release:"; \
			echo "   https://docs.astral.sh/uv/getting-started/installation/"; \
			exit 1; \
		fi; \
	fi

# UV_BIN: prefer uv in PATH, fallback to ~/.local/bin/uv
UV_BIN := $(shell type -p uv 2>/dev/null || echo "$(HOME)/.local/bin/uv")
export UV_BIN

# ----------------------------------------------------------------------------
# Virtual environment execution policy
# ----------------------------------------------------------------------------
# Targets in this Makefile deliberately split how they use `uv`:
#
#   * Execution: invoke tools via `$(VENV_DIR)/bin/<tool>` directly (e.g.
#     pytest, black, ruff, pylint, python). `uv run` — even with `--active` —
#     has historically resolved against an unexpected environment when the
#     caller has already `source`d the project venv, producing confusing
#     "works on my machine" failures. Direct invocation removes the ambiguity:
#     the tool that runs is unambiguously the one installed in $(VENV_DIR).
#
#   * Package management: continue to use `uv pip install` / `uv pip show` /
#     `uv pip list`. These are intentionally NOT rewritten to
#     `$(VENV_DIR)/bin/pip` because `uv venv` does not seed `pip` into the
#     created environment (no `--seed` flag is passed in the `venv` target
#     above), so `$(VENV_DIR)/bin/pip` simply does not exist. `uv pip` is also
#     materially faster than vanilla pip and is the supported way to manage
#     packages in a uv-managed venv.
#
# If you add a new target: use `$(VENV_DIR)/bin/<tool>` to *run* something and
# `uv pip ...` to *install* something. Do not reintroduce `uv run`.
#
# Exception — tools invoked via `uvx`: `black`, `isort`, `ruff`, `pylint`,
# `vulture`, `interrogate`, `radon`, `yamllint`, `tomlcheck`, and
# `detect-secrets` are invoked through `uv tool run <spec>` with pinned
# versions (see the pins just below). This isolates the tool versions from
# whatever is resolved into $(VENV_DIR) by the dev dependency group, so CI
# and local runs always use the same version regardless of when the venv was
# last rebuilt. These targets still depend on the `uv` target so `uvx` is
# guaranteed present. `detect-secrets` is special-cased to use a git-URL
# spec because the project uses IBM's hardened fork, which is not published
# to PyPI — see DETECT_SECRETS_SPEC below.
#
# Sub-exception — pylint needs project context: unlike the pure-AST tools
# (ruff, black, isort, vulture, interrogate, radon), pylint does deep type
# inference via astroid and relies on being able to *import* the project
# modules and their runtime dependencies (pydantic, fastapi, …) to avoid
# false positives like E1133 (not-an-iterable) and spurious W0246
# (useless-parent-delegation) suppressions from pylint-pydantic that only
# activate when the pydantic class hierarchy is resolvable. The `pylint` and
# `images`/pyreverse targets therefore pass `--with-editable .` to `uv tool
# run` so the project and its deps are installed into pylint's isolated
# tool environment. This costs ~5–10s of resolve/install on a cold uvx
# cache but restores the inference behavior that the previous
# venv-installed pylint (via `pip install -e .[dev]`) had for free.
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Pinned linter/formatter versions (invoked via `uvx`)
# ----------------------------------------------------------------------------
# Bump these in lockstep with the lower bounds in pyproject.toml's dev group
# so editors (which typically use the venv-installed version) and Makefile
# targets (which use these pins via uvx) stay aligned.
BLACK_VERSION           ?= 26.3.1
ISORT_VERSION           ?= 6.1.0
RUFF_VERSION            ?= 0.15.1
PYLINT_VERSION          ?= 3.3.9
PYLINT_PYDANTIC_VERSION ?= 0.3.5
VULTURE_VERSION         ?= 2.14
INTERROGATE_VERSION     ?= 1.7.0
RADON_VERSION           ?= 6.0.1
YAMLLINT_VERSION        ?= 1.38.0
TOMLCHECK_VERSION       ?= 0.2.3
PYSPELLING_VERSION      ?= 2.11

# detect-secrets: pinned to IBM's hardened fork (Tag 0.13.1+ibm.64.dss).
# Uses a git-URL + commit SHA rather than a PyPI version because the IBM
# fork is not published to PyPI.
DETECT_SECRETS_SPEC     ?= git+https://github.com/ibm/detect-secrets.git@076672a9a01abdfc7ecee2e7d14f08cdccb73976

.PHONY: venv
venv: uv
	@rm -Rf "$(VENV_DIR)"
	@mkdir -p "$(VENV_DIR)"
	@$(UV_BIN) venv "$(VENV_DIR)"
	@echo -e "✅  Virtual env created.\n💡  Enter it with:\n    . $(VENV_DIR)/bin/activate\n"

.PHONY: activate
activate:
	@echo -e "💡  Enter the venv using:\n. $(VENV_DIR)/bin/activate\n"

.PHONY: install
install: venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install ."

.PHONY: install-db
install-db: venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install .[redis,postgres]"

.PHONY: install-dev
install-dev: venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install --group dev '.[plugins]'"
	@if [ "$(ENABLE_RUST_BUILD)" = "1" ]; then \
		echo "🦀 Building Rust..."; \
		$(MAKE) rust-dev || echo "⚠️  Rust not available (optional)"; \
	else \
		echo "⏭️  Rust builds disabled (set ENABLE_RUST_BUILD=1 to enable)"; \
	fi
	@$(MAKE) build-ui

# help: build-ui              - Build Admin UI JS bundle with Vite (requires npm; set SKIP_UI_BUILD=1 to bypass)
.PHONY: build-ui
build-ui:
	@if [ "$(SKIP_UI_BUILD)" = "1" ]; then \
		echo "⏭️  SKIP_UI_BUILD=1 — skipping Admin UI build (the Admin UI will not load at runtime)"; \
	elif command -v npm >/dev/null 2>&1; then \
		echo "🔨 Building Admin UI bundle..."; \
		if [ -f package-lock.json ]; then \
			npm ci --no-audit --no-fund; \
		else \
			echo "ℹ️  package-lock.json not found — falling back to 'npm install'"; \
			npm install --no-audit --no-fund; \
		fi && \
		npm run vite:build; \
	else \
		echo "❌ npm not found — install Node.js (https://nodejs.org) to build the Admin UI."; \
		echo "   Without the bundle, /admin will fail to load at runtime."; \
		echo "   To bypass this step intentionally, re-run with SKIP_UI_BUILD=1."; \
		exit 1; \
	fi

.PHONY: update
update:
	@echo "⬆️   Updating installed dependencies..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install -U --group dev ."

# help: check-env            - Verify all required env vars in .env are present
.PHONY: check-env check-env-dev

# Validate .env in production mode
check-env:
	@echo "🔎  Validating .env against .env.example using Python (prod)..."
	@python -m mcpgateway.scripts.validate_env .env.example

# Validate .env in development mode (warnings do not fail)
check-env-dev:
	@echo "🔎  Validating .env (dev, warnings do not fail)..."
	@python -c "import sys; from mcpgateway.scripts import validate_env as ve; sys.exit(ve.main(env_file='.env', exit_on_warnings=False))"



# =============================================================================
# ▶️ SERVE
# =============================================================================
# help: ▶️ SERVE
# help: serve                - Run production Gunicorn server on :4444
# help: certs                - Generate self-signed TLS cert & key in ./certs (won't overwrite)
# help: certs-passphrase     - Generate self-signed cert with passphrase-protected key
# help: certs-remove-passphrase - Remove passphrase from encrypted key
# help: certs-jwt            - Generate JWT RSA keys in ./certs/jwt/ (idempotent)
# help: certs-jwt-ecdsa      - Generate JWT ECDSA keys in ./certs/jwt/ (idempotent)
# help: certs-all            - Generate both TLS certs and JWT keys (combo target)
# help: certs-mcp-ca         - Generate MCP CA for plugin mTLS (./certs/mcp/ca/)
# help: certs-mcp-gateway    - Generate gateway client certificate (./certs/mcp/gateway/)
# help: certs-mcp-plugin     - Generate plugin server certificate (requires PLUGIN_NAME=name)
# help: certs-mcp-all        - Generate complete MCP mTLS infrastructure (reads plugins from config.yaml)
# help: certs-mcp-check      - Check expiry dates of MCP certificates
# help: serve-ssl            - Run Gunicorn behind HTTPS on :4444 (uses ./certs)
# help: dev                  - Run fast-reload dev server (uvicorn)
# help: dev-echo             - Run dev server with SQL query logging (N+1 debugging)
# help: dev-remote           - Run dev server with remote debugging (debugpy on port 5678)
# help: stop                 - Stop all mcpgateway server processes
# help: stop-dev             - Stop uvicorn dev server (port 8000)
# help: stop-serve           - Stop gunicorn production server (port 4444)
# help: run                  - Execute helper script ./run.sh

.PHONY: serve serve-ssl serve-granian serve-granian-ssl serve-granian-http2 dev dev-remote stop stop-dev stop-serve run \
        certs certs-jwt certs-jwt-ecdsa certs-all certs-mcp-ca certs-mcp-gateway certs-mcp-plugin certs-mcp-all certs-mcp-check \
        js-build

## --- JS build ----------------------------------------------------------------
js-build:                        ## Install npm dependencies and build JS bundle with Vite
	@if command -v npm >/dev/null 2>&1; then \
		npm install --no-audit --no-fund && npm run vite:build; \
	else \
		echo "WARNING: npm not found — skipping JS bundle build (admin UI may not load)"; \
	fi

## --- Primary servers ---------------------------------------------------------
serve: install js-build                  ## Run production server with Gunicorn + Uvicorn (default)
	./run-gunicorn.sh

serve-ssl: js-build certs        ## Run Gunicorn with TLS enabled
	SSL=true CERT_FILE=certs/cert.pem KEY_FILE=certs/key.pem ./run-gunicorn.sh

serve-granian: js-build          ## Run production server with Granian (Rust-based, alternative)
	./run-granian.sh

serve-granian-ssl: js-build certs ## Run Granian with TLS enabled
	SSL=true CERT_FILE=certs/cert.pem KEY_FILE=certs/key.pem ./run-granian.sh

serve-granian-http2: js-build certs ## Run Granian with HTTP/2 and TLS
	SSL=true GRANIAN_HTTP=2 CERT_FILE=certs/cert.pem KEY_FILE=certs/key.pem ./run-granian.sh

dev: js-build
	@TEMPLATES_AUTO_RELOAD=true $(VENV_DIR)/bin/uvicorn mcpgateway.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude='public/'

.PHONY: dev-echo
dev-echo: js-build               ## Run dev server with SQL query logging enabled
	@echo "🔍 Starting dev server with SQL query logging (N+1 detection)"
	@echo "   Docs: docs/docs/development/db-performance.md"
	@SQLALCHEMY_ECHO=true TEMPLATES_AUTO_RELOAD=true $(VENV_DIR)/bin/uvicorn mcpgateway.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude='public/'

dev-remote: DEBUG_IP = 127.0.0.1
dev-remote: DEBUG_WAIT = --wait-for-client
dev-remote: js-build             ## Run dev server with remote debugging (debugpy on port 5678, remote: make dev-remote DEBUG_IP=0.0.0.0 DEBUG_WAIT=)
	@TEMPLATES_AUTO_RELOAD=true $(VENV_DIR)/bin/python -m debugpy \
		--listen $(DEBUG_IP):5678 \
		$(DEBUG_WAIT) \
		$(VENV_DIR)/bin/uvicorn mcpgateway.main:app \
		--host 0.0.0.0 --port 8000 --reload --reload-exclude='public/'

stop:                            ## Stop all mcpgateway server processes
	@echo "Stopping all mcpgateway processes..."
	@if [ -f /tmp/mcpgateway-gunicorn.lock ]; then kill -9 $$(cat /tmp/mcpgateway-gunicorn.lock) 2>/dev/null || true; rm -f /tmp/mcpgateway-gunicorn.lock; fi
	@if [ -f /tmp/mcpgateway-granian.lock ]; then kill -9 $$(cat /tmp/mcpgateway-granian.lock) 2>/dev/null || true; rm -f /tmp/mcpgateway-granian.lock; fi
	@lsof -ti:8000 2>/dev/null | xargs -r kill -9 || true
	@lsof -ti:4444 2>/dev/null | xargs -r kill -9 || true
	@echo "Done."

stop-dev:                        ## Stop uvicorn dev server (port 8000)
	@lsof -ti:8000 2>/dev/null | xargs -r kill -9 || true

stop-serve:                      ## Stop gunicorn production server (port 4444)
	@if [ -f /tmp/mcpgateway-gunicorn.lock ]; then kill -9 $$(cat /tmp/mcpgateway-gunicorn.lock) 2>/dev/null || true; rm -f /tmp/mcpgateway-gunicorn.lock; fi
	@lsof -ti:4444 2>/dev/null | xargs -r kill -9 || true

run: js-build
	./run.sh

## --- Certificate helper ------------------------------------------------------
.PHONY: certs
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
	@echo "🔐  Setting file permissions for container access..."
	@chmod 644 certs/cert.pem  # Public certificate - world-readable is OK
	@chmod 640 certs/key.pem   # Private key - owner+group only, no world access
	@echo "🔧  Setting group to 0 (root) for container access (requires sudo)..."
	@sudo chgrp 0 certs/key.pem certs/cert.pem || \
		(echo "⚠️  Warning: Could not set group to 0 (container may not be able to read key)" && \
		 echo "   Run manually: sudo chgrp 0 certs/key.pem certs/cert.pem")

.PHONY: certs-passphrase
certs-passphrase:                ## Generate self-signed cert with passphrase-protected key
	@if [ -f certs/cert.pem ] && [ -f certs/key-encrypted.pem ]; then \
		echo "🔏  Existing passphrase-protected certificates found - skipping."; \
	else \
		echo "🔏  Generating passphrase-protected certificate (1 year)..."; \
		mkdir -p certs; \
		read -sp "Enter passphrase for private key: " PASSPHRASE; echo; \
		read -sp "Confirm passphrase: " PASSPHRASE2; echo; \
		if [ "$$PASSPHRASE" != "$$PASSPHRASE2" ]; then \
			echo "❌  Passphrases do not match!"; \
			exit 1; \
		fi; \
		openssl genrsa -aes256 -passout pass:"$$PASSPHRASE" -out certs/key-encrypted.pem 4096; \
		openssl req -x509 -sha256 -days 365 \
			-key certs/key-encrypted.pem \
			-passin pass:"$$PASSPHRASE" \
			-out certs/cert.pem \
			-subj "/CN=localhost" \
			-addext "subjectAltName=DNS:localhost,IP:127.0.0.1"; \
		echo "✅  Passphrase-protected certificate created (AES-256)"; \
	fi
	@echo "🔐  Setting file permissions for container access..."
	@chmod 644 certs/cert.pem          # Public certificate - world-readable is OK
	@chmod 640 certs/key-encrypted.pem # Private key - owner+group only, no world access
	@echo "🔧  Setting group to 0 (root) for container access (requires sudo)..."
	@sudo chgrp 0 certs/key-encrypted.pem certs/cert.pem || \
		(echo "⚠️  Warning: Could not set group to 0 (container may not be able to read key)" && \
		 echo "   Run manually: sudo chgrp 0 certs/key-encrypted.pem certs/cert.pem")
	@echo "📁  Certificate: ./certs/cert.pem"
	@echo "📁  Encrypted Key: ./certs/key-encrypted.pem"
	@echo ""
	@echo "💡  To use this certificate:"
	@echo "   1. Set KEY_FILE_PASSWORD environment variable"
	@echo "   2. Run: KEY_FILE_PASSWORD='your-passphrase' SSL=true CERT_FILE=certs/cert.pem KEY_FILE=certs/key-encrypted.pem make serve-ssl"

.PHONY: certs-remove-passphrase
certs-remove-passphrase:         ## Remove passphrase from encrypted key (creates key.pem from key-encrypted.pem)
	@if [ ! -f certs/key-encrypted.pem ]; then \
		echo "❌  No encrypted key found at certs/key-encrypted.pem"; \
		echo "💡  Generate one with: make certs-passphrase"; \
		exit 1; \
	fi
	@echo "🔓  Removing passphrase from private key..."
	@openssl rsa -in certs/key-encrypted.pem -out certs/key.pem
	@chmod 640 certs/key.pem
	@echo "🔧  Setting group to 0 (root) for container access (requires sudo)..."
	@sudo chgrp 0 certs/key.pem || \
		(echo "⚠️  Warning: Could not set group to 0 (container may not be able to read key)" && \
		 echo "   Run manually: sudo chgrp 0 certs/key.pem")
	@echo "✅  Passphrase removed - unencrypted key saved to certs/key.pem"
	@echo "⚠️   Keep this file secure! It contains your unencrypted private key."

.PHONY: certs-jwt
certs-jwt:                       ## Generate JWT RSA keys in ./certs/jwt/ (idempotent)
	@if [ -f certs/jwt/private.pem ] && [ -f certs/jwt/public.pem ]; then \
		echo "🔐  Existing JWT RSA keys found in ./certs/jwt - skipping generation."; \
	else \
		echo "🔐  Generating JWT RSA key pair (4096-bit)..."; \
		mkdir -p certs/jwt; \
		openssl genrsa -out certs/jwt/private.pem 4096; \
		openssl rsa -in certs/jwt/private.pem -pubout -out certs/jwt/public.pem; \
		echo "✅  JWT RSA keys written to ./certs/jwt"; \
	fi
	@chmod 600 certs/jwt/private.pem
	@chmod 644 certs/jwt/public.pem
	@echo "🔒  Permissions set: private.pem (600), public.pem (644)"

.PHONY: certs-jwt-ecdsa
certs-jwt-ecdsa:                 ## Generate JWT ECDSA keys in ./certs/jwt/ (idempotent)
	@if [ -f certs/jwt/ec_private.pem ] && [ -f certs/jwt/ec_public.pem ]; then \
		echo "🔐  Existing JWT ECDSA keys found in ./certs/jwt - skipping generation."; \
	else \
		echo "🔐  Generating JWT ECDSA key pair (P-256 curve)..."; \
		mkdir -p certs/jwt; \
		openssl ecparam -genkey -name prime256v1 -noout -out certs/jwt/ec_private.pem; \
		openssl ec -in certs/jwt/ec_private.pem -pubout -out certs/jwt/ec_public.pem; \
		echo "✅  JWT ECDSA keys written to ./certs/jwt"; \
	fi
	@chmod 600 certs/jwt/ec_private.pem
	@chmod 644 certs/jwt/ec_public.pem
	@echo "🔒  Permissions set: ec_private.pem (600), ec_public.pem (644)"

.PHONY: certs-all
certs-all: certs certs-jwt       ## Generate both TLS certificates and JWT RSA keys
	@echo "🎯  All certificates and keys generated successfully!"
	@echo "📁  TLS:  ./certs/{cert,key}.pem"
	@echo "📁  JWT:  ./certs/jwt/{private,public}.pem"
	@echo "💡  Use JWT_ALGORITHM=RS256 with JWT_PUBLIC_KEY_PATH=certs/jwt/public.pem"

## --- MCP Plugin mTLS Certificate Management ----------------------------------
# Default validity period for MCP certificates (in days)
MCP_CERT_DAYS ?= 825

# Plugin configuration file for automatic certificate generation
MCP_PLUGIN_CONFIG ?= plugins/external/config.yaml

.PHONY: certs-mcp-ca
certs-mcp-ca:                    ## Generate CA for MCP plugin mTLS
	@if [ -f certs/mcp/ca/ca.key ] && [ -f certs/mcp/ca/ca.crt ]; then \
		echo "🔐  Existing MCP CA found in ./certs/mcp/ca - skipping generation."; \
		echo "⚠️   To regenerate, delete ./certs/mcp/ca and run again."; \
	else \
		echo "🔐  Generating MCP Certificate Authority ($(MCP_CERT_DAYS) days validity)..."; \
		mkdir -p certs/mcp/ca; \
		openssl genrsa -out certs/mcp/ca/ca.key 4096; \
		openssl req -new -x509 -key certs/mcp/ca/ca.key -out certs/mcp/ca/ca.crt \
			-days $(MCP_CERT_DAYS) \
			-subj "/CN=ContextForge-CA/O=ContextForge/OU=Plugins"; \
		echo "01" > certs/mcp/ca/ca.srl; \
		echo "✅  MCP CA created: ./certs/mcp/ca/ca.{key,crt}"; \
	fi
	@chmod 600 certs/mcp/ca/ca.key
	@chmod 644 certs/mcp/ca/ca.crt
	@echo "🔒  Permissions set: ca.key (600), ca.crt (644)"

.PHONY: certs-mcp-gateway
certs-mcp-gateway: certs-mcp-ca  ## Generate gateway client certificate
	@if [ -f certs/mcp/gateway/client.key ] && [ -f certs/mcp/gateway/client.crt ]; then \
		echo "🔐  Existing gateway client certificate found - skipping generation."; \
	else \
		echo "🔐  Generating gateway client certificate ($(MCP_CERT_DAYS) days)..."; \
		mkdir -p certs/mcp/gateway; \
		openssl genrsa -out certs/mcp/gateway/client.key 4096; \
		openssl req -new -key certs/mcp/gateway/client.key \
			-out certs/mcp/gateway/client.csr \
			-subj "/CN=mcp-gateway-client/O=MCPGateway/OU=Gateway"; \
		openssl x509 -req -in certs/mcp/gateway/client.csr \
			-CA certs/mcp/ca/ca.crt -CAkey certs/mcp/ca/ca.key \
			-CAcreateserial -out certs/mcp/gateway/client.crt \
			-days $(MCP_CERT_DAYS) -sha256; \
		rm certs/mcp/gateway/client.csr; \
		cp certs/mcp/ca/ca.crt certs/mcp/gateway/ca.crt; \
		echo "✅  Gateway client certificate created: ./certs/mcp/gateway/"; \
	fi
	@chmod 600 certs/mcp/gateway/client.key
	@chmod 644 certs/mcp/gateway/client.crt certs/mcp/gateway/ca.crt
	@echo "🔒  Permissions set: client.key (600), client.crt (644), ca.crt (644)"

.PHONY: certs-mcp-plugin
certs-mcp-plugin: certs-mcp-ca   ## Generate plugin server certificate (PLUGIN_NAME=name)
	@if [ -z "$(PLUGIN_NAME)" ]; then \
		echo "❌  ERROR: PLUGIN_NAME not set"; \
		echo "💡  Usage: make certs-mcp-plugin PLUGIN_NAME=my-plugin"; \
		exit 1; \
	fi
	@if [ -f certs/mcp/plugins/$(PLUGIN_NAME)/server.key ] && \
	    [ -f certs/mcp/plugins/$(PLUGIN_NAME)/server.crt ]; then \
		echo "🔐  Existing certificate for plugin '$(PLUGIN_NAME)' found - skipping."; \
	else \
		echo "🔐  Generating server certificate for plugin '$(PLUGIN_NAME)' ($(MCP_CERT_DAYS) days)..."; \
		mkdir -p certs/mcp/plugins/$(PLUGIN_NAME); \
		openssl genrsa -out certs/mcp/plugins/$(PLUGIN_NAME)/server.key 4096; \
		openssl req -new -key certs/mcp/plugins/$(PLUGIN_NAME)/server.key \
			-out certs/mcp/plugins/$(PLUGIN_NAME)/server.csr \
			-subj "/CN=mcp-plugin-$(PLUGIN_NAME)/O=MCPGateway/OU=Plugins"; \
		openssl x509 -req -in certs/mcp/plugins/$(PLUGIN_NAME)/server.csr \
			-CA certs/mcp/ca/ca.crt -CAkey certs/mcp/ca/ca.key \
			-CAcreateserial -out certs/mcp/plugins/$(PLUGIN_NAME)/server.crt \
			-days $(MCP_CERT_DAYS) -sha256 \
			-extfile <(printf "subjectAltName=DNS:$(PLUGIN_NAME),DNS:mcp-plugin-$(PLUGIN_NAME),DNS:localhost"); \
		rm certs/mcp/plugins/$(PLUGIN_NAME)/server.csr; \
		cp certs/mcp/ca/ca.crt certs/mcp/plugins/$(PLUGIN_NAME)/ca.crt; \
		echo "✅  Plugin '$(PLUGIN_NAME)' certificate created: ./certs/mcp/plugins/$(PLUGIN_NAME)/"; \
	fi
	@chmod 600 certs/mcp/plugins/$(PLUGIN_NAME)/server.key
	@chmod 644 certs/mcp/plugins/$(PLUGIN_NAME)/server.crt certs/mcp/plugins/$(PLUGIN_NAME)/ca.crt
	@echo "🔒  Permissions set: server.key (600), server.crt (644), ca.crt (644)"

.PHONY: certs-mcp-all
certs-mcp-all: certs-mcp-ca certs-mcp-gateway  ## Generate complete mTLS infrastructure
	@echo "🔐  Generating certificates for plugins..."
	@# Read plugin names from config file if it exists
	@if [ -f "$(MCP_PLUGIN_CONFIG)" ]; then \
		echo "📋  Reading plugin names from $(MCP_PLUGIN_CONFIG)"; \
		python3 -c "import yaml; \
			config = yaml.safe_load(open('$(MCP_PLUGIN_CONFIG)')); \
			plugins = [p['name'] for p in config.get('plugins', []) if p.get('kind') == 'external']; \
			print('\n'.join(plugins))" 2>/dev/null | while read plugin_name; do \
			if [ -n "$$plugin_name" ]; then \
				echo "   Generating for: $$plugin_name"; \
				$(MAKE) certs-mcp-plugin PLUGIN_NAME="$$plugin_name"; \
			fi; \
		done || echo "⚠️   PyYAML not installed or config parse failed, generating example plugins..."; \
	fi
	@# Fallback to example plugins if no config or parsing failed
	@if [ ! -f "$(MCP_PLUGIN_CONFIG)" ] || ! python3 -c "import yaml" 2>/dev/null; then \
		echo "🔐  Generating certificates for example plugins..."; \
		$(MAKE) certs-mcp-plugin PLUGIN_NAME=example-plugin-a; \
		$(MAKE) certs-mcp-plugin PLUGIN_NAME=example-plugin-b; \
	fi
	@echo ""
	@echo "🎯  MCP mTLS infrastructure generated successfully!"
	@echo "📁  Structure:"
	@echo "    certs/mcp/ca/          - Certificate Authority"
	@echo "    certs/mcp/gateway/     - Gateway client certificate"
	@echo "    certs/mcp/plugins/*/   - Plugin server certificates"
	@echo ""
	@echo "💡  Generate additional plugin certificates with:"
	@echo "    make certs-mcp-plugin PLUGIN_NAME=your-plugin-name"
	@echo ""
	@echo "💡  Certificate validity: $(MCP_CERT_DAYS) days"
	@echo "    To change: make certs-mcp-all MCP_CERT_DAYS=365"

.PHONY: certs-mcp-check
certs-mcp-check:                 ## Check expiry dates of MCP certificates
	@echo "🔍  Checking MCP certificate expiry dates..."
	@echo ""
	@if [ -f certs/mcp/ca/ca.crt ]; then \
		echo "📋 CA Certificate:"; \
		openssl x509 -in certs/mcp/ca/ca.crt -noout -enddate | sed 's/notAfter=/   Expires: /'; \
		echo ""; \
	fi
	@if [ -f certs/mcp/gateway/client.crt ]; then \
		echo "📋 Gateway Client Certificate:"; \
		openssl x509 -in certs/mcp/gateway/client.crt -noout -enddate | sed 's/notAfter=/   Expires: /'; \
		echo ""; \
	fi
	@if [ -d certs/mcp/plugins ]; then \
		echo "📋 Plugin Certificates:"; \
		for plugin_dir in certs/mcp/plugins/*; do \
			if [ -f "$$plugin_dir/server.crt" ]; then \
				plugin_name=$$(basename "$$plugin_dir"); \
				expiry=$$(openssl x509 -in "$$plugin_dir/server.crt" -noout -enddate | sed 's/notAfter=//'); \
				echo "   $$plugin_name: $$expiry"; \
			fi; \
		done; \
		echo ""; \
	fi
	@echo "💡  To regenerate expired certificates, delete the cert directory and run make certs-mcp-all"

## --- gRPC Protocol Buffer Generation -----------------------------------------
# help: grpc-proto           - Generate Python gRPC stubs from .proto files
.PHONY: grpc-proto
grpc-proto:                          ## Generate gRPC stubs for external plugin transport
	@echo "🔧  Generating gRPC protocol buffer stubs..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip show grpcio-tools >/dev/null 2>&1 || \
		$(UV_BIN) pip install -q grpcio-tools"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m grpc_tools.protoc \
			-I mcpgateway/plugins/framework/external/grpc/proto \
			--python_out=mcpgateway/plugins/framework/external/grpc/proto \
			--pyi_out=mcpgateway/plugins/framework/external/grpc/proto \
			--grpc_python_out=mcpgateway/plugins/framework/external/grpc/proto \
			mcpgateway/plugins/framework/external/grpc/proto/plugin_service.proto"
	@echo "🔧  Fixing imports in generated files..."
	@if [ "$$(uname)" = "Darwin" ]; then \
		sed -i '' 's/^import plugin_service_pb2/from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2/' \
			mcpgateway/plugins/framework/external/grpc/proto/plugin_service_pb2_grpc.py; \
	else \
		sed -i 's/^import plugin_service_pb2/from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2/' \
			mcpgateway/plugins/framework/external/grpc/proto/plugin_service_pb2_grpc.py; \
	fi
	@echo "🔧  Adding noqa comments to generated files..."
	@if [ "$$(uname)" = "Darwin" ]; then \
		sed -i '' '1s/^/# noqa: D100, D101, D102, D103, D104, D107, D400, D415\n# ruff: noqa\n# type: ignore\n# pylint: skip-file\n# Generated by protoc - do not edit\n/' \
			mcpgateway/plugins/framework/external/grpc/proto/plugin_service_pb2.py \
			mcpgateway/plugins/framework/external/grpc/proto/plugin_service_pb2_grpc.py \
			mcpgateway/plugins/framework/external/grpc/proto/plugin_service_pb2.pyi; \
	else \
		sed -i '1s/^/# noqa: D100, D101, D102, D103, D104, D107, D400, D415\n# ruff: noqa\n# type: ignore\n# pylint: skip-file\n# Generated by protoc - do not edit\n/' \
			mcpgateway/plugins/framework/external/grpc/proto/plugin_service_pb2.py \
			mcpgateway/plugins/framework/external/grpc/proto/plugin_service_pb2_grpc.py \
			mcpgateway/plugins/framework/external/grpc/proto/plugin_service_pb2.pyi; \
	fi
	@echo "✅  gRPC stubs generated in mcpgateway/plugins/framework/external/grpc/proto/"

## --- House-keeping -----------------------------------------------------------
# help: clean                - Remove caches, build artefacts, virtualenv, docs, certs, coverage, SBOM, database files, etc.
.PHONY: clean
clean:
	@echo "🧹  Cleaning workspace..."
	@set +e; \
	for dir in $(DIRS_TO_CLEAN); do \
		find . -type d -name "$$dir" -prune -exec rm -rf {} +; \
	done; \
	set -e
	@rm -f $(FILES_TO_CLEAN)
	@rm -rf $(EXTRA_DIRS_TO_CLEAN)
	@rm -f $(EXTRA_FILES_TO_CLEAN)
	@find . -name "*.py[cod]" -delete
	@find . -name "*.py,cover" -delete
	@echo "✅  Clean complete."


# =============================================================================
# 🧪 TESTING
# =============================================================================
# help: 🧪 TESTING
# help: smoketest            - Run smoketest.py --verbose (build container, add MCP server, test endpoints)
# help: test-protocol-compliance - MCP protocol compliance harness: full (target, transport) matrix across reference + gateway (K=<filter> to pick one)
# help: test-protocol-compliance-reference - Protocol compliance harness, reference server only (fast, always-on)
# help: test-protocol-compliance-gateway - Protocol compliance harness, gateway-proxy + gateway-virtual targets (requires working gateway boot)
# help: test-protocol-compliance-matrix - Protocol compliance matrix across every runnable engine; summary table (pass MATRIX_ARGS='--format markdown --out X' to override)
# help: test-mcp-protocol-e2e - MCP protocol E2E via FastMCP client against live gateway (K=<filter> to pick one; MCP_E2E_CLIENT_TIMEOUT env to extend the 5s client timeout)
# help: test-mcp-cli         - [DEPRECATED] Alias for test-mcp-protocol-e2e (accepts same K=<filter>)
# help: test-mcp-rbac        - RBAC + multi-transport MCP protocol tests (needs live gateway + SSE)
# help: test-mcp-access-matrix - MCP role/access matrix (Rust transport, edge/full mode)
# help: test-mcp-plugin-parity - MCP plugin parity E2E for current Python or Rust stack
# help: test-mcp-session-isolation - MCP session/auth isolation tests for Rust public transport
# help: test-e2e-sso         - E2E tests requiring a live SSO identity provider (Keycloak or Entra ID)
# help: test-live-gateway    - Run ALL live-gateway tests (mcp + sso + protocol_compliance + e2e_rust)
# help: test                 - Run unit tests with pytest
# help: test-verbose         - Run tests sequentially with real-time test name output
# help: test-profile         - Run tests and show slowest 20 tests (durations >= 1s)
# help: coverage             - Run tests with coverage, emit HTML/XML + badge
# help: coverage-pytest      - Run pytest unit tests with coverage collection
# help: coverage-annotated   - Run coverage and generate annotated source files (.py,cover)
# help: test-docs            - Run coverage and generate docs/docs/test/unittest.md report
# help: htmlcov              - (re)build just the HTML coverage report into docs
# help: test-curl            - Smoke-test API endpoints with curl script
# help: pytest-examples      - Run README / examples through pytest-examples
# help: doctest              - Run doctest on all modules with summary report
# help: doctest-verbose      - Run doctest with detailed output (-v flag)
# help: doctest-coverage     - Generate coverage report for doctest examples
# help: doctest-check        - Check doctest coverage percentage (fail if < 100%)
# help: test-db-perf         - Run database performance and N+1 query detection tests
# help: test-db-perf-verbose - Run database performance tests with full SQL query output
# help: 2025-11-25        - Run full MCP 2025-11-25 compliance suite (manual)
# help: 2025-11-25-core   - Run MCP core compliance subset
# help: 2025-11-25-tasks  - Run MCP tasks compliance subset
# help: 2025-11-25-auth   - Run MCP authorization compliance subset
# help: 2025-11-25-report - Run MCP suite and emit JUnit XML + Markdown reports
# help: dev-query-log        - Run dev server with query logging to file (N+1 detection)
# help: query-log-tail       - Tail the database query log file
# help: query-log-analyze    - Analyze query log for N+1 patterns and slow queries
# help: query-log-clear      - Clear database query log files

.PHONY: smoketest test-mcp-cli test-mcp-rbac test-mcp-plugin-parity test-mcp-access-matrix test-mcp-session-isolation test-mcp-session-isolation-load test-e2e-sso test-live-gateway test test-verbose test-profile coverage test-docs pytest-examples test-curl htmlcov doctest doctest-verbose doctest-coverage doctest-check test-db-perf test-db-perf-verbose 2025-11-25 2025-11-25-core 2025-11-25-tasks 2025-11-25-auth 2025-11-25-report dev-query-log query-log-tail query-log-analyze query-log-clear load-test load-test-ui load-test-light load-test-heavy load-test-sustained load-test-stress load-test-report load-test-compose load-test-timeserver load-test-fasttime load-test-1000 load-test-summary load-test-baseline load-test-baseline-ui load-test-baseline-stress load-test-agentgateway-mcp-server-time

# Dirs/files always excluded from standard pytest runs.
# tests/live_gateway/ — see tests/live_gateway/README.md. Subsuites need
# a running gateway (`make testing-up`), Keycloak/Entra (sso/), the Rust
# transport (e2e_rust/), or specific protocol setup (protocol_compliance/).
# Invoke via `make test-live-gateway` (everything) or a targeted helper
# (test-mcp-protocol-e2e, test-mcp-rbac, test-mcp-plugin-parity,
# test-mcp-access-matrix, test-mcp-session-isolation, test-e2e-sso,
# test-protocol-compliance{,-reference,-gateway}).
PYTEST_IGNORE := tests/fuzz tests/manual test.py \
    tests/live_gateway

# Expand to --ignore=<path> flags for pytest CLI
PYTEST_IGNORE_FLAGS := $(foreach p,$(PYTEST_IGNORE),--ignore=$(p))

## --- Automated checks --------------------------------------------------------
smoketest:
	@echo "🚀 Running smoketest..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv install install-dev
	@$(VENV_DIR)/bin/python ./smoketest.py --verbose || { echo "❌ Smoketest failed!"; exit 1; }
	@echo "✅ Smoketest passed!"

test-mcp-protocol-e2e: uv  ## MCP protocol E2E via FastMCP client (K=<filter> to pick one)
	@echo "🔌 Running MCP protocol E2E tests against $${MCP_CLI_BASE_URL:-http://localhost:8080}..."
	@echo "   Env: MCP_CLI_BASE_URL (gateway URL)  JWT_SECRET_KEY  PLATFORM_ADMIN_EMAIL"
	@echo "   Timeout: $${MCP_E2E_CLIENT_TIMEOUT:-5.0}s per client operation (override MCP_E2E_CLIENT_TIMEOUT)"
	@if [ -n "$(K)" ]; then echo "   Filter: -k \"$(K)\""; fi
	@$(UV_BIN) run pytest tests/live_gateway/mcp/test_mcp_protocol_e2e.py $(if $(K),-k "$(K)") -v -s --tb=short \
		|| { echo "❌ MCP protocol E2E tests failed!"; exit 1; }
	@echo "✅ MCP protocol E2E tests passed!"

test-mcp-cli:  ## [DEPRECATED] Alias for test-mcp-protocol-e2e (subprocess + mcp-cli path removed)
	@echo "⚠️  'make test-mcp-cli' is deprecated — use 'make test-mcp-protocol-e2e'."
	@echo "   The mcp-cli + mcpgateway.wrapper subprocess path was replaced by the FastMCP client."
	@$(MAKE) test-mcp-protocol-e2e

test-protocol-compliance: uv  ## MCP protocol compliance harness — full (target, transport) matrix (K=<filter> to pick one)
	@echo "📜 Running MCP protocol compliance harness (tests/live_gateway/protocol_compliance)..."
	@if [ -n "$(K)" ]; then echo "   Filter: -k \"$(K)\""; fi
	@$(UV_BIN) run pytest tests/live_gateway/protocol_compliance $(if $(K),-k "$(K)") -v --tb=short \
		|| { echo "❌ protocol compliance harness failed!"; exit 1; }
	@echo "✅ protocol compliance harness passed!"

test-protocol-compliance-reference: uv  ## Protocol compliance harness — reference server only (fast, always-on)
	@echo "📜 Running MCP protocol compliance harness (reference target only)..."
	@$(UV_BIN) run pytest tests/live_gateway/protocol_compliance -k "reference-stdio" -v --tb=short \
		|| { echo "❌ reference-target compliance harness failed!"; exit 1; }
	@echo "✅ reference-target compliance harness passed!"

test-protocol-compliance-gateway: uv  ## Protocol compliance harness — gateway-proxy + gateway-virtual (needs in-process gateway boot to succeed)
	@echo "📜 Running MCP protocol compliance harness (gateway targets)..."
	@$(UV_BIN) run pytest tests/live_gateway/protocol_compliance -k "gateway_proxy or gateway_virtual" -v --tb=short \
		|| { echo "❌ gateway-target compliance harness failed!"; exit 1; }
	@echo "✅ gateway-target compliance harness passed!"

test-protocol-compliance-matrix: uv  ## MCP compliance matrix across every runnable engine (reference, python, rust_edge, rust_full) with aggregated summary
	@$(UV_BIN) run python scripts/compliance_matrix.py $(MATRIX_ARGS)

test-mcp-rbac: uv  ## RBAC + multi-transport MCP protocol tests (needs live gateway + SSE)
	@echo "🔐 Running RBAC + multi-transport MCP protocol tests against $${MCP_CLI_BASE_URL:-http://localhost:8080}..."
	@echo "   Requires: docker-compose stack with SSE gateway registered"
	@$(UV_BIN) run playwright install --with-deps chromium >/dev/null
	@$(UV_BIN) run pytest -p playwright tests/live_gateway/mcp/test_mcp_rbac_transport.py -v -s --tb=short \
		|| { echo "❌ MCP RBAC transport tests failed!"; exit 1; }
	@echo "✅ MCP RBAC transport tests passed!"

test-mcp-access-matrix: uv  ## Detailed Rust MCP role/access matrix test with strong tool/resource/prompt sentinels
	@echo "🧪 Running MCP role/access matrix tests against $${MCP_CLI_BASE_URL:-http://localhost:8080}..."
	@echo "   Requires: docker-compose stack rebuilt in Rust edge/full mode"
	@$(UV_BIN) run pytest tests/live_gateway/e2e_rust/test_mcp_access_matrix.py -v -s --tb=short \
		|| { echo "❌ MCP role/access matrix tests failed!"; exit 1; }
	@echo "✅ MCP role/access matrix tests passed!"

test-mcp-plugin-parity: uv  ## MCP plugin parity E2E for current Python or Rust stack using a test-specific plugin config
	@echo "🧪 Running MCP plugin parity tests against $${MCP_CLI_BASE_URL:-http://localhost:8080}..."
	@echo "   Requires: stack started with PLUGINS_CONFIG_FILE=plugins/plugin_parity_config.yaml"
	@$(UV_BIN) run pytest tests/live_gateway/mcp/test_mcp_plugin_parity.py -v -s --tb=short \
		|| { echo "❌ MCP plugin parity tests failed!"; exit 1; }
	@echo "✅ MCP plugin parity tests passed!"

test-mcp-session-isolation: uv  ## MCP session/auth isolation tests for the Rust public transport path
	@echo "🧪 Running MCP session/auth isolation tests against $${MCP_CLI_BASE_URL:-http://localhost:8080}..."
	@echo "   Requires: docker-compose stack rebuilt in Rust edge/full mode"
	@$(UV_BIN) run pytest tests/live_gateway/e2e_rust/test_mcp_session_isolation.py -v -s --tb=short \
		|| { echo "❌ MCP session/auth isolation tests failed!"; exit 1; }
	@echo "✅ MCP session/auth isolation tests passed!"

test-e2e-sso: uv  ## E2E tests requiring a live SSO identity provider (Keycloak or Entra ID)
	@echo "🔐 Running SSO-dependent E2E tests against $${MCP_CLI_BASE_URL:-http://localhost:8080}..."
	@echo "   Requires one of:"
	@echo "     - Keycloak: 'docker compose --profile sso up -d' (for test_oauth_jwks_e2e.py)"
	@echo "     - Entra ID: AZURE_CLIENT_ID/AZURE_CLIENT_SECRET/AZURE_TENANT_ID env vars (for test_entra_id_integration.py)"
	@$(UV_BIN) run pytest -p playwright tests/live_gateway/sso/ -v -s --tb=short \
		|| { echo "❌ SSO E2E tests failed!"; exit 1; }
	@echo "✅ SSO E2E tests passed!"

test-live-gateway: uv  ## Run ALL live-gateway tests (mcp + sso + protocol_compliance)
	@echo "🌐 Running all tests in tests/live_gateway/ ..."
	@echo "   Requires: live ContextForge gateway (typically 'make testing-up') and any"
	@echo "             extra services per subsuite — see tests/live_gateway/README.md."
	@echo "   Tests probe BASE_URL ($${MCP_CLI_BASE_URL:-http://localhost:8080}) and self-skip when unreachable."
	@$(UV_BIN) run --extra plugins pytest -p playwright tests/live_gateway/ -v --tb=short \
		|| { echo "❌ Live-gateway test suite failed!"; exit 1; }
	@echo "✅ Live-gateway test suite finished."

MCP_ISOLATION_LOCUSTFILE ?= tests/loadtest/locustfile_mcp_isolation.py
MCP_ISOLATION_LOAD_HOST ?= http://localhost:8080
MCP_ISOLATION_LOAD_USERS ?= 12
MCP_ISOLATION_LOAD_SPAWN_RATE ?= 3
MCP_ISOLATION_LOAD_RUN_TIME ?= 60s

test-mcp-session-isolation-load: ## Multi-user MCP session/auth isolation correctness load test
	@echo "🧪 Running MCP session/auth isolation load test against $(MCP_ISOLATION_LOAD_HOST)..."
	@echo "   Requires: docker-compose stack rebuilt in Rust full mode"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -eu -o pipefail -c 'source $(VENV_DIR)/bin/activate && \
		locust -f $(MCP_ISOLATION_LOCUSTFILE) \
			--host=$(MCP_ISOLATION_LOAD_HOST) \
			--users=$(MCP_ISOLATION_LOAD_USERS) \
			--spawn-rate=$(MCP_ISOLATION_LOAD_SPAWN_RATE) \
			--run-time=$(MCP_ISOLATION_LOAD_RUN_TIME) \
			--headless \
			--stop-timeout=30 \
			--exit-code-on-error=1 \
			--only-summary'

test: uv
	@echo "🧪 Running tests..."
	@DATABASE_URL='sqlite:///:memory:' \
	 TEST_DATABASE_URL='sqlite:///:memory:' \
	 ARGON2ID_TIME_COST=1 \
	 ARGON2ID_MEMORY_COST=1024 \
	 $(UV_BIN) run --extra plugins pytest -n auto --maxfail=0 -v --durations=5 \
		$(PYTEST_IGNORE_FLAGS)

test-verbose: uv
	@echo "🧪 Running tests (verbose, sequential)..."
	@DATABASE_URL='sqlite:///:memory:' \
	 TEST_DATABASE_URL='sqlite:///:memory:' \
	 ARGON2ID_TIME_COST=1 \
	 ARGON2ID_MEMORY_COST=1024 \
	 $(UV_BIN) run --extra plugins pytest --maxfail=0 -v --tb=short --instafail $(PYTEST_IGNORE_FLAGS)

test-profile: uv
	@echo "🧪 Running tests with profiling (showing slowest tests)..."
	@DATABASE_URL='sqlite:///:memory:' \
	 TEST_DATABASE_URL='sqlite:///:memory:' \
	 ARGON2ID_TIME_COST=1 \
	 ARGON2ID_MEMORY_COST=1024 \
	 $(UV_BIN) run --extra plugins pytest -n 16 --durations=20 --durations-min=1.0 --disable-warnings -v $(PYTEST_IGNORE_FLAGS)

.PHONY: coverage-pytest
coverage-pytest: uv
	@mkdir -p $(TEST_DOCS_DIR)
	@DATABASE_URL='sqlite:///:memory:' \
	 TEST_DATABASE_URL='sqlite:///:memory:' \
	 BASIC_AUTH_PASSWORD='TestCoveragePassw0rd!42' \
	 PLATFORM_ADMIN_PASSWORD='TestCoveragePassw0rd!42' \
	 DEFAULT_USER_PASSWORD='TestCoveragePassw0rd!42' \
	 JWT_SECRET_KEY='coverage-test-jwt-secret-key-1234567890' \
	 AUTH_ENCRYPTION_SECRET='coverage-test-auth-encryption-1234567890' \
	 $(UV_BIN) run --extra plugins pytest -p pytest_cov --reruns=1 --reruns-delay 30 \
		--dist loadgroup -n auto -rfE --cov-append --capture=fd -v \
		--durations=120 --cov-report=term --cov=mcpgateway \
		$(PYTEST_IGNORE_FLAGS) tests/ || true

coverage: coverage-pytest
	@DATABASE_URL='sqlite:///:memory:' \
	 TEST_DATABASE_URL='sqlite:///:memory:' \
	 BASIC_AUTH_PASSWORD='TestCoveragePassw0rd!42' \
	 PLATFORM_ADMIN_PASSWORD='TestCoveragePassw0rd!42' \
	 DEFAULT_USER_PASSWORD='TestCoveragePassw0rd!42' \
	 JWT_SECRET_KEY='coverage-test-jwt-secret-key-1234567890' \
	 AUTH_ENCRYPTION_SECRET='coverage-test-auth-encryption-1234567890' \
	 $(UV_BIN) run --extra plugins pytest -p pytest_cov --reruns=1 --reruns-delay 30 \
		--dist loadgroup -n auto -rfE --cov-append --capture=fd -v \
		--durations=120 --doctest-modules mcpgateway/ --cov-report=term \
		--cov=mcpgateway mcpgateway/ || true
	@$(UV_BIN) run coverage html -d $(COVERAGE_DIR) --include=mcpgateway/*
	@$(UV_BIN) run coverage xml
	@$(UV_BIN) run coverage report -m --no-skip-covered
	@echo "✅  Coverage artefacts: HTML in $(COVERAGE_DIR) & XML ✔"

.PHONY: coverage-annotated
coverage-annotated: coverage
	@echo "🔍  Generating annotated coverage files..."
	@$(UV_BIN) run coverage annotate -d .
	@echo "✅  Annotated files (.py,cover) generated ✔"

test-docs: uv
	@echo "📝  Generating test documentation (docs/docs/test/unittest.md)..."
	@mkdir -p $(TEST_DOCS_DIR)
	@printf "# Unit tests\n\n" > $(DOCS_DIR)/docs/test/unittest.md
	@DATABASE_URL='sqlite:///:memory:' \
	 TEST_DATABASE_URL='sqlite:///:memory:' \
	 $(UV_BIN) run --extra plugins pytest -p pytest_cov --reruns=1 --reruns-delay 30 \
		--dist loadgroup -n 8 -rA --cov-append --capture=fd -v \
		--durations=120 --doctest-modules mcpgateway/ --cov-report=term \
		--cov=mcpgateway mcpgateway/ || true
	@DATABASE_URL='sqlite:///:memory:' \
	 TEST_DATABASE_URL='sqlite:///:memory:' \
	 $(UV_BIN) run --extra plugins pytest -p pytest_cov --reruns=1 --reruns-delay 30 \
		--md-report --md-report-output=$(DOCS_DIR)/docs/test/unittest.md \
		--dist loadgroup -n 8 -rA --cov-append --capture=fd -v \
		--durations=120 --cov-report=term --cov=mcpgateway \
		$(PYTEST_IGNORE_FLAGS) tests/ || true
	@printf '\n## Coverage report\n\n' >> $(DOCS_DIR)/docs/test/unittest.md
	@$(UV_BIN) run coverage report --format=markdown -m --no-skip-covered \
		>> $(DOCS_DIR)/docs/test/unittest.md
	@echo "✅  Test docs generated → $(DOCS_DIR)/docs/test/unittest.md"

htmlcov: uv
	@echo "📊  Generating HTML coverage report..."
	@mkdir -p $(COVERAGE_DIR)
	@if [ ! -f .coverage ]; then \
		echo "ℹ️  No .coverage file found - running full coverage first..."; \
		$(MAKE) --no-print-directory coverage; \
	fi
	@$(UV_BIN) run coverage html -i -d $(COVERAGE_DIR)
	@echo "✅  HTML coverage report ready → $(COVERAGE_DIR)/index.html"

diff-cover: uv
	@echo "📊  Running diff-cover against main branch..."
	@if [ ! -f coverage.xml ]; then \
		echo "ℹ️  No coverage.xml found - running coverage first..."; \
		$(MAKE) --no-print-directory coverage; \
	fi
	@$(UV_BIN) run diff-cover coverage.xml --compare-branch=main --fail-under=90

pytest-examples: uv
	@echo "🧪 Testing README examples..."
	@test -f test_readme.py || { echo "⚠️  test_readme.py not found - skipping"; exit 0; }
	@$(UV_BIN) run pytest -v test_readme.py

test-curl:
	./test_endpoints.sh

## --- Doctest targets ---------------------------------------------------------
doctest: uv
	@echo "🧪 Running doctest on all modules..."
	@JWT_SECRET_KEY=secret \
	 $(UV_BIN) run pytest --doctest-modules mcpgateway/ --ignore=mcpgateway/utils/pagination.py --tb=short --no-cov --disable-warnings -n 4

doctest-verbose: uv
	@echo "🧪 Running doctest with verbose output..."
	@JWT_SECRET_KEY=secret \
	 $(UV_BIN) run pytest --doctest-modules mcpgateway/ --ignore=mcpgateway/utils/pagination.py -v --tb=short --no-cov --disable-warnings -n 4

doctest-coverage: uv
	@echo "📊 Generating doctest coverage report..."
	@mkdir -p $(TEST_DOCS_DIR)
	@$(UV_BIN) run pytest --doctest-modules mcpgateway/ \
		--cov=mcpgateway --cov-report=term --cov-report=html:htmlcov-doctest \
		--cov-report=xml:coverage-doctest.xml
	@echo "✅ Doctest coverage report generated in htmlcov-doctest/"

doctest-check: uv
	@echo "🔍 Checking doctest coverage..."
	@$(UV_BIN) run pytest --doctest-modules mcpgateway/ --tb=no -q && \
		echo '✅ All doctests passing' || (echo '❌ Doctest failures detected' && exit 1)

## --- Database Performance Testing --------------------------------------------
test-db-perf: uv  ## Run database performance and N+1 detection tests
	@echo "🔍 Running database performance tests..."
	@echo "   Tip: Use 'make dev-echo' to debug queries in dev server"
	@echo "   Docs: docs/docs/development/db-performance.md"
	@DATABASE_URL='sqlite:///:memory:' \
	 TEST_DATABASE_URL='sqlite:///:memory:' \
	 $(UV_BIN) run pytest tests/performance/test_db_query_patterns.py -v --tb=short

test-db-perf-verbose: uv  ## Run database performance tests with full SQL query output
	@echo "🔍 Running database performance tests with query logging..."
	@echo "   All SQL queries will be printed to help identify N+1 patterns"
	@DATABASE_URL='sqlite:///:memory:' \
	 TEST_DATABASE_URL='sqlite:///:memory:' \
	 SQLALCHEMY_ECHO=true \
	 $(UV_BIN) run pytest tests/performance/test_db_query_patterns.py -v -s --tb=short

# Shared env-var prefix for the 2025-11-25 compliance series.
# Defined as a make variable so each target stays compact while keeping
# the env identical across subset runs (-core / -tasks / -auth / -report).
MCP_2025_TEST_ENV := \
	DATABASE_URL='sqlite:///:memory:' \
	TEST_DATABASE_URL='sqlite:///:memory:' \
	ARGON2ID_TIME_COST=1 \
	ARGON2ID_MEMORY_COST=1024 \
	MCP_COMPLIANCE_BASE_URL='$(MCP_2025_BASE_URL)' \
	MCP_COMPLIANCE_RPC_PATH='$(MCP_2025_RPC_PATH)' \
	MCP_COMPLIANCE_BEARER_TOKEN='$(MCP_2025_BEARER_TOKEN)'

2025-11-25: uv  ## Run full MCP 2025-11-25 compliance suite
	@echo "🧪 Running MCP 2025-11-25 compliance suite..."
	@test -d "$(MCP_2025_TEST_DIR)" || { echo "❌ Compliance suite path not found: $(MCP_2025_TEST_DIR)"; echo "   Update MCP_2025_TEST_DIR or add the suite first."; exit 1; }
	@$(MCP_2025_TEST_ENV) \
	 $(UV_BIN) run pytest $(MCP_2025_TEST_DIR) -v --maxfail=0 -m "$(MCP_2025_MARKER)" $(MCP_2025_PYTEST_ARGS)

2025-11-25-core: uv  ## Run MCP core compliance subset
	@echo "🧪 Running MCP 2025-11-25 core compliance subset..."
	@test -d "$(MCP_2025_TEST_DIR)" || { echo "❌ Compliance suite path not found: $(MCP_2025_TEST_DIR)"; echo "   Update MCP_2025_TEST_DIR or add the suite first."; exit 1; }
	@$(MCP_2025_TEST_ENV) \
	 $(UV_BIN) run pytest $(MCP_2025_TEST_DIR) -v --maxfail=0 -m "$(MCP_2025_MARKER) and mcp_core" $(MCP_2025_PYTEST_ARGS)

2025-11-25-tasks: uv  ## Run MCP tasks compliance subset
	@echo "🧪 Running MCP 2025-11-25 tasks compliance subset..."
	@test -d "$(MCP_2025_TEST_DIR)" || { echo "❌ Compliance suite path not found: $(MCP_2025_TEST_DIR)"; echo "   Update MCP_2025_TEST_DIR or add the suite first."; exit 1; }
	@$(MCP_2025_TEST_ENV) \
	 $(UV_BIN) run pytest $(MCP_2025_TEST_DIR) -v --maxfail=0 -m "$(MCP_2025_MARKER) and mcp_tasks" $(MCP_2025_PYTEST_ARGS)

2025-11-25-auth: uv  ## Run MCP authorization compliance subset
	@echo "🧪 Running MCP 2025-11-25 authorization compliance subset..."
	@test -d "$(MCP_2025_TEST_DIR)" || { echo "❌ Compliance suite path not found: $(MCP_2025_TEST_DIR)"; echo "   Update MCP_2025_TEST_DIR or add the suite first."; exit 1; }
	@$(MCP_2025_TEST_ENV) \
	 $(UV_BIN) run pytest $(MCP_2025_TEST_DIR) -v --maxfail=0 -m "$(MCP_2025_MARKER) and mcp_auth" $(MCP_2025_PYTEST_ARGS)

2025-11-25-report: uv  ## Run MCP suite and emit JUnit XML + Markdown reports
	@echo "🧪 Running MCP 2025-11-25 suite with report artifacts..."
	@test -d "$(MCP_2025_TEST_DIR)" || { echo "❌ Compliance suite path not found: $(MCP_2025_TEST_DIR)"; echo "   Update MCP_2025_TEST_DIR or add the suite first."; exit 1; }
	@mkdir -p "$(MCP_2025_ARTIFACTS_DIR)"
	@$(MCP_2025_TEST_ENV) \
	 $(UV_BIN) run pytest $(MCP_2025_TEST_DIR) -v --maxfail=0 -m "$(MCP_2025_MARKER)" \
		--junitxml=$(MCP_2025_ARTIFACTS_DIR)/junit.xml \
		--md-report --md-report-output=$(MCP_2025_ARTIFACTS_DIR)/report.md \
		$(MCP_2025_PYTEST_ARGS)
	@echo "✅ Compliance artifacts:"
	@echo "   - $(MCP_2025_ARTIFACTS_DIR)/junit.xml"
	@echo "   - $(MCP_2025_ARTIFACTS_DIR)/report.md"

dev-query-log:                   ## Run dev server with query logging to file
	@echo "📊 Starting dev server with database query logging"
	@echo "   Logs: logs/db-queries.log (text), logs/db-queries.jsonl (JSON)"
	@echo "   Use 'make query-log-tail' in another terminal to watch queries"
	@echo "   Docs: docs/docs/development/db-performance.md"
	@mkdir -p logs
	@DB_QUERY_LOG_ENABLED=true TEMPLATES_AUTO_RELOAD=true $(VENV_DIR)/bin/uvicorn mcpgateway.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude='public/'

query-log-tail:                  ## Tail the database query log file
	@echo "📊 Tailing logs/db-queries.log (Ctrl+C to stop)"
	@echo "   Start server with 'make dev-query-log' to generate queries"
	@tail -f logs/db-queries.log 2>/dev/null || echo "No log file yet. Start server with 'make dev-query-log' first."

query-log-analyze:               ## Analyze query log for N+1 patterns
	@echo "📊 Analyzing database query log..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 -m mcpgateway.utils.analyze_query_log"

query-log-clear:                 ## Clear database query log files
	@echo "🗑️  Clearing database query logs..."
	@rm -f logs/db-queries.log logs/db-queries.jsonl
	@echo "✅ Query logs cleared"


# =============================================================================
# 📊 LOAD TESTING - Database population and performance testing
# =============================================================================
# help: 📊 LOAD TESTING
# help: generate-small       - Generate small load test data (100 users, ~74K records, <1 min)
# help: generate-medium      - Generate medium load test data (10K users, ~70M records, ~10 min)
# help: generate-large       - Generate large load test data (100K users, ~700M records, ~1-2 hours)
# help: generate-massive     - Generate massive load test data (1M users, billions of records, ~10-20 hours)
# help: generate-clean       - Clean all generated load test data and reports
# help: generate-report      - Display most recent load test report

.PHONY: generate-small generate-medium generate-large generate-massive generate-clean generate-report

generate-small:                            ## Generate small load test dataset (100 users)
	@echo "📊 Generating small load test data..."
	@echo "   Target: 100 users, ~74K records"
	@echo "   Time: <1 minute"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m tests.load.generate --profile small"
	@echo ""
	@echo "✅ Small load test data generated!"
	@echo "📄 Report: reports/small_load_report.json"

generate-medium:                           ## Generate medium load test dataset (10K users)
	@echo "📊 Generating medium load test data..."
	@echo "   Target: 10K users, ~70M records"
	@echo "   Time: ~10 minutes"
	@echo "   ⚠️  Recommended: Use PostgreSQL for better performance"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m tests.load.generate --profile medium"
	@echo ""
	@echo "✅ Medium load test data generated!"
	@echo "📄 Report: reports/medium_load_report.json"

generate-large:                            ## Generate large load test dataset (100K users)
	@echo "📊 Generating large load test data..."
	@echo "   Target: 100K users, ~700M records"
	@echo "   Time: ~1-2 hours"
	@echo "   ⚠️  REQUIRED: PostgreSQL"
	@echo "   ⚠️  Recommended: 16GB+ RAM, SSD storage"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m tests.load.generate --profile large"
	@echo ""
	@echo "✅ Large load test data generated!"
	@echo "📄 Report: reports/large_load_report.json"

generate-massive:                          ## Generate massive load test dataset (1M users)
	@echo "📊 Generating massive load test data..."
	@echo "   Target: 1M users, billions of records"
	@echo "   Time: ~10-20 hours"
	@echo "   ⚠️  REQUIRED: PostgreSQL with high-performance config"
	@echo "   ⚠️  REQUIRED: 32GB+ RAM, SSD storage, multi-core CPU"
	@echo ""
	@read -p "This will take 10-20 hours. Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		test -d "$(VENV_DIR)" || $(MAKE) venv; \
		/bin/bash -c "source $(VENV_DIR)/bin/activate && \
			python -m tests.load.generate --profile massive"; \
		echo ""; \
		echo "✅ Massive load test data generated!"; \
		echo "📄 Report: reports/massive_load_report.json"; \
	else \
		echo "❌ Cancelled"; \
		exit 1; \
	fi

generate-clean:                            ## Clean all generated load test data
	@echo "🧹 Cleaning load test data..."
	@rm -f reports/*_load_report.json
	@echo "✅ Load test reports cleaned!"
	@echo ""
	@echo "⚠️  Note: This does NOT clean the database itself."
	@echo "   To clean database, use: make clean-db"

generate-report:                           ## Display most recent load test report
	@echo "📊 Most Recent Load Test Reports:"
	@echo ""
	@for report in reports/*_load_report.json; do \
		if [ -f "$$report" ]; then \
			echo "📄 $$report:"; \
			jq -r '"  Profile: \(.profile)\n  Duration: \(.duration_seconds)s\n  Records: \(.total_generated | tonumber | tostring) total\n  Rate: \(.records_per_second | floor | tostring) records/sec\n  Timestamp: \(.timestamp)"' "$$report" 2>/dev/null || \
			cat "$$report" | head -20; \
			echo ""; \
		fi; \
	done || echo "❌ No reports found. Run 'make generate-small' first."

# =============================================================================
# 📊 REST API POPULATION - Populate via HTTP endpoints (full write path)
# =============================================================================
# help: 📊 REST API POPULATION
# help: populate-tiny        - Populate via REST API (50 each, ~500 entities, ~30 sec)
# help: populate-small       - Populate via REST API (100 users, ~3K entities, ~2 min)
# help: populate-medium      - Populate via REST API (10K users, ~300K entities, ~1 hr)
# help: populate-large       - Populate via REST API (500K users, ~13M entities, ~4-12 hrs)
# help: populate-dry         - Preview what would be created (no requests sent)
# help: populate-verify      - Verify populated data via GET endpoints
# help: populate-clean       - Delete all loadtest.example.com entities via API
# help: populate-report      - Show latest population report

.PHONY: populate-tiny populate-small populate-medium populate-large populate-dry populate-verify populate-clean populate-report

populate-tiny:                             ## Populate via REST API - tiny (50 each)
	@echo "📊 Populating via REST API (tiny profile)..."
	@echo "   Target: 50 of each entity type, ~500 entities"
	@echo "   Time: ~30 seconds"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m tests.populate --profile tiny"
	@echo ""
	@echo "✅ Tiny API population complete!"
	@echo "📄 Report: reports/tiny_populate_report.json"

populate-small:                            ## Populate via REST API - small (100 users)
	@echo "📊 Populating via REST API (small profile)..."
	@echo "   Target: 100 users, ~3K entities"
	@echo "   Time: ~2 minutes"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m tests.populate --profile small"
	@echo ""
	@echo "✅ Small API population complete!"
	@echo "📄 Report: reports/small_populate_report.json"

populate-medium:                           ## Populate via REST API - medium (10K users)
	@echo "📊 Populating via REST API (medium profile)..."
	@echo "   Target: 10K users, ~300K entities"
	@echo "   Time: ~30-60 minutes"
	@echo "   ⚠️  Recommended: PostgreSQL backend"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m tests.populate --profile medium"
	@echo ""
	@echo "✅ Medium API population complete!"
	@echo "📄 Report: reports/medium_populate_report.json"

populate-large:                            ## Populate via REST API - large (500K users)
	@echo "📊 Populating via REST API (large profile)..."
	@echo "   Target: 500K users, ~13M entities"
	@echo "   Time: ~4-12 hours"
	@echo "   ⚠️  REQUIRED: PostgreSQL backend"
	@echo ""
	@read -p "This will take several hours. Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		test -d "$(VENV_DIR)" || $(MAKE) venv; \
		/bin/bash -c "source $(VENV_DIR)/bin/activate && \
			python -m tests.populate --profile large"; \
		echo ""; \
		echo "✅ Large API population complete!"; \
		echo "📄 Report: reports/large_populate_report.json"; \
	else \
		echo "❌ Cancelled"; \
		exit 1; \
	fi

populate-dry:                              ## Preview what populate-small would create
	@echo "📊 Population dry run (no requests sent)..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m tests.populate --profile small --dry-run"

populate-verify:                           ## Verify populated data via GET endpoints
	@echo "🔍 Verifying populated data via REST API..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m tests.populate.verify"

populate-clean:                            ## Delete all loadtest.example.com entities via API
	@echo "🧹 Cleaning up loadtest data via REST API..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python -m tests.populate.cleanup --confirm"

populate-report:                           ## Show latest population report
	@echo "📊 Most Recent Population Reports:"
	@echo ""
	@for report in reports/*_populate_report.json; do \
		if [ -f "$$report" ]; then \
			echo "📄 $$report:"; \
			jq -r '"  Profile: \(.profile)\n  Duration: \(.duration_seconds)s\n  Created: \(.total_created) entities\n  Errors: \(.total_errors)\n  Rate: \(.requests_per_second) req/s\n  Timestamp: \(.timestamp)"' "$$report" 2>/dev/null || \
			cat "$$report" | head -20; \
			echo ""; \
		fi; \
	done || echo "❌ No reports found. Run 'make populate-small' first."

# =============================================================================
# 📊 MONITORING STACK - Prometheus + Grafana + Exporters
# =============================================================================
# help: 📊 MONITORING STACK
# help: monitoring-up          - Start monitoring stack (Grafana, Prometheus, Loki, Tempo)
# help: monitoring-down        - Stop monitoring stack
# help: monitoring-clean       - Stop and remove all monitoring data (volumes)
# help: monitoring-status      - Show status of monitoring services
# help: monitoring-logs        - Show monitoring stack logs
# help: monitoring-lite-up    - Start lite monitoring (excludes pgAdmin, Redis CLI)
# help: monitoring-lite-down  - Stop lite monitoring stack

# Compose command for monitoring (requires --profile support)
# podman-compose < 1.1.0 doesn't support --profile, so prefer docker compose or podman compose
COMPOSE_CMD_MONITOR := $(shell \
	if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then \
		echo "docker compose"; \
	elif command -v podman &>/dev/null && podman compose version &>/dev/null 2>&1; then \
		echo "podman compose"; \
	else \
		echo "docker-compose"; \
	fi)

NGINX_PORT_SPECS := nginx:NGINX_PORT:8080
LANGFUSE_PORT_SPECS := langfuse-web:LANGFUSE_PORT:3100 langfuse-worker:LANGFUSE_WORKER_PORT:3130
MONITORING_PORT_SPECS := postgres_exporter:POSTGRES_EXPORTER_PORT:9187 redis_exporter:REDIS_EXPORTER_PORT:9121 pgbouncer_exporter:PGBOUNCER_EXPORTER_PORT:9127 nginx_exporter:NGINX_EXPORTER_PORT:9113 cadvisor:CADVISOR_PORT:8085 prometheus:PROMETHEUS_PORT:9090 loki:LOKI_PORT:3101 tempo:TEMPO_PORT:3200 tempo:TEMPO_OTLP_GRPC_PORT:4317 tempo:TEMPO_OTLP_HTTP_PORT:4318 grafana:GRAFANA_PORT:3000 pgadmin:PGADMIN_PORT:5050 redis_commander:REDIS_COMMANDER_PORT:8081

define CHECK_PORT_SPECS
	@PORT_SPECS='$(1)'; \
	for spec in $$PORT_SPECS; do \
		service=$${spec%%:*}; \
		rest=$${spec#*:}; \
		env_var=$${rest%%:*}; \
		default_port=$${rest##*:}; \
		port=$${!env_var:-}; \
		if [ -z "$$port" ]; then port=$$default_port; fi; \
		echo "🔎 Preflight: checking host port $$port ($$service)"; \
		if $(COMPOSE_CMD_MONITOR) ps --services --status running 2>/dev/null | grep -qx "$$service"; then \
			echo "ℹ️  Port $$port is already bound by this compose project's $$service; reusing it."; \
			continue; \
		fi; \
		if command -v ss >/dev/null 2>&1; then \
			if ss -H -ltn "sport = :$$port" | grep -q .; then \
				echo "⚠️  Host port $$port for $$service is already in use."; \
				ss -ltnp "sport = :$$port" || ss -ltn "sport = :$$port"; \
				echo "   Override with $$env_var=<free-port> or stop the conflicting service."; \
				exit 1; \
			fi; \
		elif command -v lsof >/dev/null 2>&1; then \
			if lsof -nP -iTCP:$$port -sTCP:LISTEN >/dev/null 2>&1; then \
				echo "⚠️  Host port $$port for $$service is already in use."; \
				lsof -nP -iTCP:$$port -sTCP:LISTEN || true; \
				echo "   Override with $$env_var=<free-port> or stop the conflicting service."; \
				exit 1; \
			fi; \
		else \
			echo "ℹ️  Skipping port check for $$service (ss/lsof not found)."; \
		fi; \
	done
endef

.PHONY: monitoring-up
monitoring-up:                             ## Start monitoring stack (Prometheus, Grafana, exporters)
	@echo "📊 Starting monitoring stack..."
	$(call CHECK_PORT_SPECS,$(NGINX_PORT_SPECS) $(MONITORING_PORT_SPECS))
	# Enable OTEL tracing + JSON console logs for the monitoring profile (Tempo + Loki correlation)
	LOG_FORMAT=json \
	OTEL_ENABLE_OBSERVABILITY=true \
	OTEL_TRACES_EXPORTER=otlp \
	OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317 \
	$(COMPOSE_CMD_MONITOR) --profile monitoring up -d
	@# Nginx resolves gateway backends when it starts; recreate it after gateway churn.
	$(COMPOSE_CMD_MONITOR) up -d --no-deps --force-recreate nginx
	@echo "⏳ Waiting for Grafana to be ready..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		if curl -s -o /dev/null -w '' http://localhost:$${GRAFANA_PORT:-3000}/api/health 2>/dev/null; then break; fi; \
		sleep 2; \
	done
	@# Configure Grafana: star dashboard and set as home
	@curl -s -X POST -u admin:changeme "http://localhost:$${GRAFANA_PORT:-3000}/api/user/stars/dashboard/uid/mcp-gateway-overview" >/dev/null 2>&1 || true
	@curl -s -X PUT -u admin:changeme -H "Content-Type: application/json" -d '{"homeDashboardUID": "mcp-gateway-overview"}' "http://localhost:$${GRAFANA_PORT:-3000}/api/org/preferences" >/dev/null 2>&1 || true
	@curl -s -X PUT -u admin:changeme -H "Content-Type: application/json" -d '{"homeDashboardUID": "mcp-gateway-overview"}' "http://localhost:$${GRAFANA_PORT:-3000}/api/user/preferences" >/dev/null 2>&1 || true
	@echo ""
	@echo "✅ Monitoring stack started!"
	@echo ""
	@echo "   🌐 Grafana:    http://localhost:$${GRAFANA_PORT:-3000} (admin/changeme)"
	@echo "   🔥 Prometheus: http://localhost:$${PROMETHEUS_PORT:-9090}"
	@echo "   🧵 Tempo:      http://localhost:$${TEMPO_PORT:-3200} (OTLP: $${TEMPO_OTLP_GRPC_PORT:-4317} gRPC, $${TEMPO_OTLP_HTTP_PORT:-4318} HTTP)"
	@echo ""
	@echo "   ★ ContextForge Overview (home dashboard):"
	@echo "      • Gateway replicas, Nginx, PostgreSQL, Redis status"
	@echo "      • Request rate, error rate, P95 latency"
	@echo "      • Nginx connections and throughput"
	@echo "      • Database queries and cache hit ratio"
	@echo "      • Redis memory, ops/sec, hit rate"
	@echo "      • Container CPU and memory usage"
	@echo ""
	@echo "   🔎 Tracing:"
	@echo "      • Grafana Explore → Tempo datasource"
	@echo ""
	@echo "   Run load test: make load-test-ui"

.PHONY: monitoring-down
monitoring-down:                           ## Stop monitoring stack
	@echo "📊 Stopping monitoring stack..."
	$(COMPOSE_CMD_MONITOR) --profile monitoring down --remove-orphans
	@echo "✅ Monitoring stack stopped."

.PHONY: monitoring-status
monitoring-status:                         ## Show status of monitoring services
	@echo "📊 Monitoring stack status:"
	@$(COMPOSE_CMD_MONITOR) ps --filter "label=com.docker.compose.profiles=monitoring" 2>/dev/null || \
		$(COMPOSE_CMD_MONITOR) ps | grep -E "(prometheus|grafana|loki|promtail|tempo|exporter|cadvisor)" || \
		echo "   No monitoring services running. Start with 'make monitoring-up'"

.PHONY: monitoring-logs
monitoring-logs:                           ## Show monitoring stack logs
	$(COMPOSE_CMD_MONITOR) --profile monitoring logs -f --tail=100

.PHONY: monitoring-clean
monitoring-clean:                          ## Stop and remove all monitoring data (volumes)
	@echo "📊 Stopping and cleaning monitoring stack..."
	$(COMPOSE_CMD_MONITOR) --profile monitoring down -v --remove-orphans
	@echo "✅ Monitoring stack stopped and volumes removed."

# =============================================================================
# help: 🔭 LANGFUSE LLM OBSERVABILITY
# help: langfuse-up              - Start Langfuse stack (trace viz, evals, cost tracking)
# help: langfuse-down            - Stop Langfuse stack
# help: langfuse-status          - Show status of Langfuse services
# help: langfuse-logs            - Show Langfuse stack logs
# help: langfuse-reset-data      - Stop the Langfuse stack and remove only Langfuse data volumes
# help: langfuse-clean-including-contextforge - Stop the combined stack and remove Langfuse + ContextForge volumes
# help: langfuse-monitoring-up   - Start Langfuse + monitoring (gateway traces go to Langfuse)

LANGFUSE_COMPOSE := $(COMPOSE_CMD_MONITOR) -f docker-compose.yml -f docker-compose.with-langfuse.yml
LANGFUSE_DATA_VOLUMES := langfuse-postgres-data langfuse-clickhouse-data langfuse-clickhouse-logs langfuse-minio-data langfuse-redis-data

define VERIFY_LANGFUSE_GATEWAY_EXPORT
	@echo "🔎 Verifying gateway OTLP exporter is wired to Langfuse..."
	@$(LANGFUSE_COMPOSE) exec -T gateway /bin/sh -c '\
		env | grep -q "^OTEL_ENABLE_OBSERVABILITY=true$$" && \
		env | grep -q "^OTEL_EXPORTER_OTLP_PROTOCOL=http$$" && \
		env | grep -q "^LANGFUSE_OTEL_ENDPOINT=" \
	' || { \
		echo "❌ Gateway is not running with the Langfuse OTLP overlay."; \
		echo "   Expected OTEL_ENABLE_OBSERVABILITY=true, OTEL_EXPORTER_OTLP_PROTOCOL=http, and LANGFUSE_OTEL_ENDPOINT inside the gateway container."; \
		exit 1; \
	}
	@expected_endpoint=$$($(LANGFUSE_COMPOSE) exec -T gateway /bin/sh -c 'printf "%s" "$$LANGFUSE_OTEL_ENDPOINT"'); \
	found_endpoint=0; \
	for i in 1 2 3 4 5 6 7 8 9 10; do \
		if $(LANGFUSE_COMPOSE) logs gateway --tail=400 2>/dev/null | grep -F "Endpoint: $$expected_endpoint" >/dev/null; then \
			found_endpoint=1; \
			break; \
		fi; \
		sleep 2; \
	done; \
	if [ "$$found_endpoint" -ne 1 ]; then \
		echo "❌ Gateway did not initialize OpenTelemetry with the expected Langfuse endpoint ($$expected_endpoint)."; \
		echo "   Rebuild the gateway image if the running container is stale, then rerun make langfuse-up."; \
		exit 1; \
	fi
endef

.PHONY: langfuse-up
langfuse-up:                               ## Start Langfuse LLM observability stack
	@echo "🔭 Starting Langfuse LLM observability stack..."
	@if [ -z "$${LANGFUSE_PUBLIC_KEY:-}" ] || [ -z "$${LANGFUSE_SECRET_KEY:-}" ]; then \
		echo "⚠️  LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set in the shell."; \
		echo "   Using compose-local dev defaults: pk-lf-contextforge / sk-lf-contextforge"; \
		echo "   Override them via env when you want a different local project or external Langfuse."; \
	fi
	$(call CHECK_PORT_SPECS,$(NGINX_PORT_SPECS) $(LANGFUSE_PORT_SPECS))
	OTEL_ENABLE_OBSERVABILITY=true \
	OTEL_EXPORTER_OTLP_PROTOCOL=http \
	$(LANGFUSE_COMPOSE) up -d
	@# Force the gateway under the Langfuse overlay so a prior monitoring-only run
	@# cannot leave Tempo-only OTLP settings behind.
	$(LANGFUSE_COMPOSE) up -d --force-recreate gateway
	@# Nginx resolves gateway backends when it starts; recreate it after gateway churn.
	$(LANGFUSE_COMPOSE) up -d --no-deps --force-recreate nginx
	@# Bring up the same lightweight MCP/A2A test targets used by the live smoke
	@# suites so Langfuse runs can generate real end-to-end tool traffic without
	@# depending on stale registrations from the testing profile.
	$(LANGFUSE_COMPOSE) up -d fast_test_server register_fast_test a2a_echo_agent register_a2a_echo
	$(VERIFY_LANGFUSE_GATEWAY_EXPORT)
	@echo "⏳ Waiting for Langfuse to be ready..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		if curl -s -o /dev/null -w '' http://localhost:$${LANGFUSE_PORT:-3100}/api/public/health 2>/dev/null; then break; fi; \
		sleep 3; \
	done
	@echo ""
	@echo "✅ Langfuse LLM observability started!"
	@echo ""
	@echo "   🔭 Langfuse UI:    http://localhost:$${LANGFUSE_PORT:-3100}"
	@echo "   📧 Login email:    $${LANGFUSE_INIT_USER_EMAIL:-admin@example.com}"
	@echo "   🔐 Password:       $${LANGFUSE_INIT_USER_PASSWORD:-changeme}"
	@echo "   🌐 Gateway:        http://localhost:$${NGINX_PORT:-8080}"
	@echo ""
	@echo "   OTEL traces from ContextForge → Langfuse (OTLP/HTTP)"
	@echo "   Project: ContextForge Gateway (auto-provisioned)"
	@echo ""

.PHONY: langfuse-down
langfuse-down:                             ## Stop Langfuse stack
	@echo "🔭 Stopping Langfuse stack..."
	$(LANGFUSE_COMPOSE) down --remove-orphans
	@echo "✅ Langfuse stack stopped."

.PHONY: langfuse-status
langfuse-status:                           ## Show status of Langfuse services
	@echo "🔭 Langfuse stack status:"
	@$(LANGFUSE_COMPOSE) ps 2>/dev/null | grep -E "(langfuse)" || \
		echo "   No Langfuse services running. Start with 'make langfuse-up'"
	@echo ""
	@echo "🔍 Langfuse health:"
	@curl -sf http://localhost:$${LANGFUSE_PORT:-3100}/api/public/health 2>/dev/null && echo "" || \
		echo "   Langfuse UI not reachable at http://localhost:$${LANGFUSE_PORT:-3100}"

.PHONY: langfuse-logs
langfuse-logs:                             ## Show Langfuse stack logs
	$(LANGFUSE_COMPOSE) logs -f --tail=100

.PHONY: langfuse-reset-data
langfuse-reset-data:                       ## Stop the Langfuse stack and remove only Langfuse data volumes
	@echo "🔭 Resetting Langfuse data volumes (ContextForge data preserved)..."
	$(LANGFUSE_COMPOSE) down --remove-orphans
	@for logical_volume in $(LANGFUSE_DATA_VOLUMES); do \
		matches=$$(docker volume ls --format '{{.Name}}' | grep -E "(^|_)$${logical_volume}$$" || true); \
		if [ -z "$$matches" ]; then \
			echo "   • $$logical_volume: not present"; \
			continue; \
		fi; \
		echo "$$matches" | while IFS= read -r volume_name; do \
			[ -n "$$volume_name" ] || continue; \
			echo "   • removing $$volume_name"; \
			docker volume rm "$$volume_name" >/dev/null; \
		done; \
	done
	@echo "✅ Langfuse data volumes removed."
	@echo "   Re-run 'make langfuse-up' to start with a fresh Langfuse project."

.PHONY: langfuse-clean-including-contextforge
langfuse-clean-including-contextforge:     ## Stop the combined stack and remove Langfuse + ContextForge volumes
	@echo "🔭 Stopping and cleaning the combined Langfuse + ContextForge stack..."
	$(LANGFUSE_COMPOSE) down -v --remove-orphans
	@echo "✅ Combined stack stopped and volumes removed."

.PHONY: langfuse-clean
langfuse-clean:                            ## Deprecated ambiguous alias
	@echo "❌ 'make langfuse-clean' is ambiguous and has been removed."
	@echo "   Use 'make langfuse-reset-data' to wipe only Langfuse data."
	@echo "   Use 'make langfuse-clean-including-contextforge' to wipe the full combined stack, including ContextForge data."
	@exit 1

.PHONY: langfuse-monitoring-up
langfuse-monitoring-up:                    ## Start Langfuse + full monitoring stack (Grafana, Prometheus, Tempo)
	@echo "🔭📊 Starting Langfuse + monitoring stack..."
	@echo "   Gateway OTLP traces will be sent to Langfuse."
	@echo "   Grafana/Tempo remain available for infrastructure metrics and optional collector fan-out."
	$(call CHECK_PORT_SPECS,$(NGINX_PORT_SPECS) $(LANGFUSE_PORT_SPECS) $(MONITORING_PORT_SPECS))
	LOG_FORMAT=json \
	OTEL_ENABLE_OBSERVABILITY=true \
	OTEL_EXPORTER_OTLP_PROTOCOL=http \
	$(LANGFUSE_COMPOSE) --profile monitoring up -d
	@# Force the gateway under the Langfuse overlay so a prior monitoring-only run
	@# cannot leave Tempo-only OTLP settings behind.
	$(LANGFUSE_COMPOSE) up -d --force-recreate gateway
	@# Nginx resolves gateway backends when it starts; recreate it after gateway churn.
	$(LANGFUSE_COMPOSE) up -d --no-deps --force-recreate nginx
	$(VERIFY_LANGFUSE_GATEWAY_EXPORT)
	@echo "⏳ Waiting for services to be ready..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		if curl -s -o /dev/null -w '' http://localhost:$${GRAFANA_PORT:-3000}/api/health 2>/dev/null; then break; fi; \
		sleep 2; \
	done
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		if curl -s -o /dev/null -w '' http://localhost:$${LANGFUSE_PORT:-3100}/api/public/health 2>/dev/null; then break; fi; \
		sleep 3; \
	done
	@echo ""
	@echo "✅ Langfuse + monitoring stack started!"
	@echo ""
	@echo "   🔭 Langfuse UI:    http://localhost:$${LANGFUSE_PORT:-3100} ($${LANGFUSE_INIT_USER_EMAIL:-admin@example.com} / $${LANGFUSE_INIT_USER_PASSWORD:-changeme})"
	@echo "   🌐 Grafana:        http://localhost:$${GRAFANA_PORT:-3000} (admin/changeme)"
	@echo "   🔥 Prometheus:     http://localhost:$${PROMETHEUS_PORT:-9090}"
	@echo "   🧵 Tempo:          http://localhost:$${TEMPO_PORT:-3200}"
	@echo "   🌐 Gateway:        http://localhost:$${NGINX_PORT:-8080}"
	@echo ""
	@echo "   OTEL traces → Langfuse (LLM analytics at :$${LANGFUSE_PORT:-3100})"
	@echo "   Note: For dual-export to Tempo, use infra/monitoring/otel-collector/collector.langfuse-tempo.yaml"
	@echo ""

.PHONY: langfuse-monitoring-down
langfuse-monitoring-down:                  ## Stop Langfuse + monitoring stack
	@echo "🔭📊 Stopping Langfuse + monitoring stack..."
	$(LANGFUSE_COMPOSE) --profile monitoring down --remove-orphans
	@echo "✅ Langfuse + monitoring stack stopped."

# =============================================================================
# help: 🧪 TESTING STACK (Locust + A2A echo + fast_test_server)
# help: testing-up            - Start testing stack (Locust + A2A echo + fast_test_server)
# help: testing-down          - Stop testing stack
# help: testing-status        - Show status of testing services
# help: testing-logs          - Show testing stack logs

TESTING_LOCUST_WORKERS ?= 1
# Used by docker-compose testing profile to run Locust as the host user so it
# can write reports to ./reports on bind mounts without EACCES.
HOST_UID ?= $(shell id -u 2>/dev/null || echo 1000)
HOST_GID ?= $(shell id -g 2>/dev/null || echo 1000)

.PHONY: testing-up
testing-up:                                ## Start testing stack (Locust + A2A echo + fast_test_server)
	@echo "🧪 Starting testing stack (fast_test_server)..."
	@echo "   🦗 Locust workers: $(TESTING_LOCUST_WORKERS) (override: TESTING_LOCUST_WORKERS=4 make testing-up)"
	@mkdir -p reports
	@echo "   Using image $(IMAGE_LOCAL)"
	HOST_UID=$(HOST_UID) HOST_GID=$(HOST_GID) \
	LOCUST_EXPECT_WORKERS=$(TESTING_LOCUST_WORKERS) \
	$(COMPOSE_CMD_MONITOR) --profile testing --profile inspector --profile sso up -d --scale locust_worker=$(TESTING_LOCUST_WORKERS)
	@echo ""
	@echo "✅ Testing stack started!"
	@echo ""
	@echo "Service              URL                           Purpose"
	@echo "──────────────────────────────────────────────────────────────────────────"
	@echo "Gateway (nginx)      http://localhost:8080         API proxy"
	@echo "Locust Web UI        http://localhost:8089         Load testing (master+workers)"
	@echo "Fast Test Server     http://localhost:8880         MCP benchmark target"
	@echo "A2A Echo Agent       http://localhost:9100         A2A protocol target"
	@echo "MCP Inspector        http://localhost:6274         Interactive MCP client"
	@echo "Keycloak             http://localhost:8180         SSO / OAuth 2.1 provider (realm: mcp-gateway)"
	@echo ""
	@echo "   🔒 For DAST security scanning, also start ZAP: make testing-zap-up"
	@echo ""
	@echo "   📝 Auto-registered:"
	@echo "      • MCP gateway: fast_test (from fast_test_server)"
	@echo "      • A2A agent:   a2a-echo-agent"
	@echo ""
	@echo "   Next:"
	@echo "      • Open Locust: http://localhost:8089 (default host is http://nginx:80)"

.PHONY: testing-up-rust
testing-up-rust:                           ## Start testing stack with RUST_MCP_MODE=edge
	@RUST_MCP_MODE=edge RUST_MCP_LOG=$(RUST_MCP_LOG) $(MAKE) testing-up

.PHONY: testing-up-rust-shadow
testing-up-rust-shadow:                    ## Start testing stack with RUST_MCP_MODE=shadow
	@RUST_MCP_MODE=shadow RUST_MCP_LOG=$(RUST_MCP_LOG) $(MAKE) testing-up

.PHONY: testing-up-rust-full
testing-up-rust-full:                      ## Start testing stack with RUST_MCP_MODE=full
	@RUST_MCP_MODE=full RUST_MCP_LOG=$(RUST_MCP_LOG) $(MAKE) testing-up

.PHONY: testing-rebuild-rust
testing-rebuild-rust:                      ## Rebuild Rust image with no cache, then start testing stack in edge mode
	@$(MAKE) testing-down
	@$(MAKE) compose-clean
	@$(MAKE) docker-prod-rust-no-cache
	@RUST_MCP_MODE=edge RUST_MCP_LOG=$(RUST_MCP_LOG) $(MAKE) testing-up

.PHONY: testing-rebuild-rust-shadow
testing-rebuild-rust-shadow:               ## Rebuild Rust image with no cache, then start testing stack in shadow mode
	@$(MAKE) testing-down
	@$(MAKE) compose-clean
	@$(MAKE) docker-prod-rust-no-cache
	@RUST_MCP_MODE=shadow RUST_MCP_LOG=$(RUST_MCP_LOG) $(MAKE) testing-up

.PHONY: testing-rebuild-rust-full
testing-rebuild-rust-full:                 ## Rebuild Rust image with no cache, then start testing stack in full mode
	@$(MAKE) testing-down
	@$(MAKE) compose-clean
	@$(MAKE) docker-prod-rust-no-cache
	@RUST_MCP_MODE=full RUST_MCP_LOG=$(RUST_MCP_LOG) $(MAKE) testing-up

.PHONY: testing-down
testing-down:                              ## Stop testing stack
	@echo "🧪 Stopping testing stack..."
	$(COMPOSE_CMD_MONITOR) --profile testing --profile inspector --profile dast --profile sso down --remove-orphans
	@echo "✅ Testing stack stopped."

.PHONY: testing-status
testing-status:                            ## Show status of testing services
	@echo "🧪 Testing stack status:"
	@$(COMPOSE_CMD_MONITOR) ps | grep -E "(fast_test|a2a_echo_agent|locust|mcp_inspector)" || \
		echo "   No testing services running. Start with 'make testing-up'"
	@WORKERS=$$($(COMPOSE_CMD_MONITOR) ps | grep -c "locust_worker" || true); \
		echo "   🦗 Locust workers: $$WORKERS"

.PHONY: testing-logs
testing-logs:                              ## Show testing stack logs
	$(COMPOSE_CMD_MONITOR) --profile testing --profile inspector logs -f --tail=100

.PHONY: testing-zap-up
testing-zap-up:                            ## Start OWASP ZAP DAST daemon (requires testing stack)
	@echo "🔒 Starting OWASP ZAP DAST daemon..."
	$(COMPOSE_CMD_MONITOR) --profile dast up -d
	@echo ""
	@echo "✅ ZAP DAST daemon started!"
	@echo ""
	@echo "   OWASP ZAP API:    http://localhost:8090"
	@echo "   OWASP ZAP API UI: http://localhost:8090/UI"
	@echo ""
	@echo "   Run security tests: make test-zap"

.PHONY: testing-zap-down
testing-zap-down:                          ## Stop OWASP ZAP DAST daemon
	@echo "🔒 Stopping ZAP DAST daemon..."
	$(COMPOSE_CMD_MONITOR) --profile dast down --remove-orphans
	@echo "✅ ZAP stopped."

# =============================================================================
# help: 🔍 MCP INSPECTOR (Interactive MCP Client)
# help: inspector-up           - Start MCP Inspector (http://localhost:6274)
# help: inspector-down         - Stop MCP Inspector
# help: inspector-logs         - Show MCP Inspector logs
# help: inspector-status       - Show status of MCP Inspector

.PHONY: inspector-up inspector-down inspector-logs inspector-status

inspector-up:                              ## Start MCP Inspector (interactive MCP client)
	@echo "🔍 Starting MCP Inspector..."
	$(COMPOSE_CMD_MONITOR) --profile inspector up -d
	@echo ""
	@echo "✅ MCP Inspector started!"
	@echo ""
	@echo "   🔍 Inspector UI:  http://localhost:6274"
	@echo ""
	@echo "   To connect to the gateway's virtual server:"
	@echo "      1. Select transport: Streamable HTTP"
	@echo "      2. Enter URL: http://nginx:80/servers/9779b6698cbd4b4995ee04a4fab38737/mcp"
	@echo "      3. Add header — Authorization: Bearer <token>"
	@echo ""
	@echo "   Generate a JWT token:"
	@echo "      python -m mcpgateway.utils.create_jwt_token \\"
	@echo "        --username admin@example.com --exp 10080 --secret my-test-key-but-now-longer-than-32-bytes --algo HS256"
	@echo ""

inspector-down:                            ## Stop MCP Inspector
	@echo "🔍 Stopping MCP Inspector..."
	$(COMPOSE_CMD_MONITOR) --profile inspector down --remove-orphans
	@echo "✅ MCP Inspector stopped."

inspector-logs:                            ## Show MCP Inspector logs
	$(COMPOSE_CMD_MONITOR) --profile inspector logs -f --tail=100

inspector-status:                          ## Show status of MCP Inspector
	@echo "🔍 MCP Inspector status:"
	@$(COMPOSE_CMD_MONITOR) ps | grep -E "(mcp_inspector)" || \
		echo "   Not running. Start with 'make inspector-up'"

# =============================================================================
# help: 🤖 A2A DEMO AGENTS (Issue #2002 Authentication Testing)
# help: demo-a2a-up           - Start all 3 A2A demo agents (basic, bearer, apikey) with auto-registration
# help: demo-a2a-down         - Stop all A2A demo agents
# help: demo-a2a-status       - Show status of A2A demo agents
# help: demo-a2a-basic        - Start only Basic Auth demo agent (port 9001)
# help: demo-a2a-bearer       - Start only Bearer Token demo agent (port 9002)
# help: demo-a2a-apikey       - Start only X-API-Key demo agent (port 9003)

# A2A Demo Agent configuration
DEMO_A2A_BASIC_PORT ?= 9001
DEMO_A2A_BEARER_PORT ?= 9002
DEMO_A2A_APIKEY_PORT ?= 9003
DEMO_A2A_BASIC_PID := /tmp/demo-a2a-basic.pid
DEMO_A2A_BEARER_PID := /tmp/demo-a2a-bearer.pid
DEMO_A2A_APIKEY_PID := /tmp/demo-a2a-apikey.pid

.PHONY: demo-a2a-up demo-a2a-down demo-a2a-status demo-a2a-basic demo-a2a-bearer demo-a2a-apikey

demo-a2a-up:                               ## Start all 3 A2A demo agents with auto-registration
	@echo "🤖 Starting A2A demo agents for authentication testing (Issue #2002)..."
	@test -x "$(VENV_DIR)/bin/python" || $(MAKE) install-dev
	@echo ""
	@# Start Basic Auth agent (PYTHONUNBUFFERED=1 ensures print output is captured immediately)
	@echo "Starting Basic Auth agent on port $(DEMO_A2A_BASIC_PORT)..."
	@PYTHONUNBUFFERED=1 $(VENV_DIR)/bin/python scripts/demo_a2a_agent_auth.py \
		--auth-type basic --port $(DEMO_A2A_BASIC_PORT) --auto-register > /tmp/demo-a2a-basic.log 2>&1 & echo $$! > $(DEMO_A2A_BASIC_PID)
	@sleep 1
	@# Start Bearer Token agent
	@echo "Starting Bearer Token agent on port $(DEMO_A2A_BEARER_PORT)..."
	@PYTHONUNBUFFERED=1 $(VENV_DIR)/bin/python scripts/demo_a2a_agent_auth.py \
		--auth-type bearer --port $(DEMO_A2A_BEARER_PORT) --auto-register > /tmp/demo-a2a-bearer.log 2>&1 & echo $$! > $(DEMO_A2A_BEARER_PID)
	@sleep 1
	@# Start X-API-Key agent
	@echo "Starting X-API-Key agent on port $(DEMO_A2A_APIKEY_PORT)..."
	@PYTHONUNBUFFERED=1 $(VENV_DIR)/bin/python scripts/demo_a2a_agent_auth.py \
		--auth-type apikey --port $(DEMO_A2A_APIKEY_PORT) --auto-register > /tmp/demo-a2a-apikey.log 2>&1 & echo $$! > $(DEMO_A2A_APIKEY_PID)
	@sleep 2
	@echo ""
	@echo "✅ A2A demo agents started!"
	@echo ""
	@echo "   🔐 Basic Auth:    http://localhost:$(DEMO_A2A_BASIC_PORT)  (log: /tmp/demo-a2a-basic.log)"
	@echo "   🎫 Bearer Token:  http://localhost:$(DEMO_A2A_BEARER_PORT)  (log: /tmp/demo-a2a-bearer.log)"
	@echo "   🔑 X-API-Key:     http://localhost:$(DEMO_A2A_APIKEY_PORT)  (log: /tmp/demo-a2a-apikey.log)"
	@echo ""
	@echo "   View credentials: cat /tmp/demo-a2a-*.log | grep -A5 'Configuration:'"
	@echo "   Stop agents:      make demo-a2a-down"
	@echo ""

demo-a2a-down:                             ## Stop all A2A demo agents
	@echo "🤖 Stopping A2A demo agents..."
	@# Send SIGTERM first to allow graceful unregistration
	@-if [ -f $(DEMO_A2A_BASIC_PID) ]; then kill -15 $$(cat $(DEMO_A2A_BASIC_PID)) 2>/dev/null || true; fi
	@-if [ -f $(DEMO_A2A_BEARER_PID) ]; then kill -15 $$(cat $(DEMO_A2A_BEARER_PID)) 2>/dev/null || true; fi
	@-if [ -f $(DEMO_A2A_APIKEY_PID) ]; then kill -15 $$(cat $(DEMO_A2A_APIKEY_PID)) 2>/dev/null || true; fi
	@sleep 2
	@# Force kill any remaining processes
	@-if [ -f $(DEMO_A2A_BASIC_PID) ]; then kill -9 $$(cat $(DEMO_A2A_BASIC_PID)) 2>/dev/null || true; rm -f $(DEMO_A2A_BASIC_PID); fi
	@-if [ -f $(DEMO_A2A_BEARER_PID) ]; then kill -9 $$(cat $(DEMO_A2A_BEARER_PID)) 2>/dev/null || true; rm -f $(DEMO_A2A_BEARER_PID); fi
	@-if [ -f $(DEMO_A2A_APIKEY_PID) ]; then kill -9 $$(cat $(DEMO_A2A_APIKEY_PID)) 2>/dev/null || true; rm -f $(DEMO_A2A_APIKEY_PID); fi
	@echo "✅ A2A demo agents stopped."

demo-a2a-status:                           ## Show status of A2A demo agents
	@echo "🤖 A2A demo agent status:"
	@echo ""
	@if [ -f $(DEMO_A2A_BASIC_PID) ] && kill -0 $$(cat $(DEMO_A2A_BASIC_PID)) 2>/dev/null; then \
		echo "   ✅ Basic Auth (port $(DEMO_A2A_BASIC_PORT)):   running (PID $$(cat $(DEMO_A2A_BASIC_PID)))"; \
	else \
		echo "   ❌ Basic Auth (port $(DEMO_A2A_BASIC_PORT)):   stopped"; \
		rm -f $(DEMO_A2A_BASIC_PID) 2>/dev/null || true; \
	fi
	@if [ -f $(DEMO_A2A_BEARER_PID) ] && kill -0 $$(cat $(DEMO_A2A_BEARER_PID)) 2>/dev/null; then \
		echo "   ✅ Bearer Token (port $(DEMO_A2A_BEARER_PORT)): running (PID $$(cat $(DEMO_A2A_BEARER_PID)))"; \
	else \
		echo "   ❌ Bearer Token (port $(DEMO_A2A_BEARER_PORT)): stopped"; \
		rm -f $(DEMO_A2A_BEARER_PID) 2>/dev/null || true; \
	fi
	@if [ -f $(DEMO_A2A_APIKEY_PID) ] && kill -0 $$(cat $(DEMO_A2A_APIKEY_PID)) 2>/dev/null; then \
		echo "   ✅ X-API-Key (port $(DEMO_A2A_APIKEY_PORT)):    running (PID $$(cat $(DEMO_A2A_APIKEY_PID)))"; \
	else \
		echo "   ❌ X-API-Key (port $(DEMO_A2A_APIKEY_PORT)):    stopped"; \
		rm -f $(DEMO_A2A_APIKEY_PID) 2>/dev/null || true; \
	fi
	@echo ""

demo-a2a-basic:                            ## Start only Basic Auth demo agent
	@echo "🔐 Starting Basic Auth demo agent on port $(DEMO_A2A_BASIC_PORT)..."
	@test -x "$(VENV_DIR)/bin/python" || $(MAKE) install-dev
	$(VENV_DIR)/bin/python scripts/demo_a2a_agent_auth.py --auth-type basic --port $(DEMO_A2A_BASIC_PORT) --auto-register

demo-a2a-bearer:                           ## Start only Bearer Token demo agent
	@echo "🎫 Starting Bearer Token demo agent on port $(DEMO_A2A_BEARER_PORT)..."
	@test -x "$(VENV_DIR)/bin/python" || $(MAKE) install-dev
	$(VENV_DIR)/bin/python scripts/demo_a2a_agent_auth.py --auth-type bearer --port $(DEMO_A2A_BEARER_PORT) --auto-register

demo-a2a-apikey:                           ## Start only X-API-Key demo agent
	@echo "🔑 Starting X-API-Key demo agent on port $(DEMO_A2A_APIKEY_PORT)..."
	@test -x "$(VENV_DIR)/bin/python" || $(MAKE) install-dev
	$(VENV_DIR)/bin/python scripts/demo_a2a_agent_auth.py --auth-type apikey --port $(DEMO_A2A_APIKEY_PORT) --auto-register

# =============================================================================
# help: 🛡️  RESILIENCE TESTING STACK (slow-time-server)
# help: resilience-up          - Start slow-time-server for timeout/circuit breaker testing
# help: resilience-down        - Stop resilience testing stack
# help: resilience-logs        - Show resilience stack logs
# help: resilience-locust      - Run Locust load test against slow-time-server (10 users, 120s)
# help: resilience-locust-ui   - Start Locust web UI for slow-time-server
# help: test-secrets-detection-plugin - Validate the secrets detection plugin end to end
# help: test-pii-filter-plugin        - Validate the PII filter plugin changes
# help: resilience-jmeter      - Run JMeter baseline test against slow-time-server (20 threads, 5min)

RESILIENCE_HOST ?= http://localhost:8889
RESILIENCE_LOCUSTFILE := tests/loadtest/locustfile_slow_time_server.py
RESILIENCE_JMETER_PLAN := tests/jmeter/slow_time_server_baseline.jmx

.PHONY: resilience-up
resilience-up:                             ## Start slow-time-server for resilience testing
	@echo "Starting resilience testing stack (slow-time-server on port 8889)..."
	$(COMPOSE_CMD_MONITOR) --profile resilience up -d
	@echo ""
	@echo "Resilience stack started!"
	@echo ""
	@echo "   Slow Time Server: $(RESILIENCE_HOST)"
	@echo "     REST API:       $(RESILIENCE_HOST)/api/v1/time?delay=5"
	@echo "     MCP SSE:        $(RESILIENCE_HOST)/sse"
	@echo "     MCP HTTP:       $(RESILIENCE_HOST)/http"
	@echo "     API Docs:       $(RESILIENCE_HOST)/api/v1/docs"
	@echo "     Health:         $(RESILIENCE_HOST)/health"
	@echo ""
	@echo "   Run: make resilience-locust  or  make resilience-jmeter"

.PHONY: resilience-down
resilience-down:                           ## Stop resilience testing stack
	@echo "Stopping resilience testing stack..."
	$(COMPOSE_CMD_MONITOR) --profile resilience down --remove-orphans
	@echo "Resilience stack stopped."

.PHONY: resilience-logs
resilience-logs:                           ## Show resilience stack logs
	$(COMPOSE_CMD_MONITOR) --profile resilience logs -f --tail=100

.PHONY: resilience-locust
resilience-locust:                         ## Run Locust load test against slow-time-server (10 users, 120s)
	@echo "Running resilience Locust load test..."
	@echo "   Host: $(RESILIENCE_HOST)"
	@echo "   Users: 10, Duration: 120s"
	@echo "   Requires: make resilience-up"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p reports
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		locust -f $(RESILIENCE_LOCUSTFILE) \
			--host=$(RESILIENCE_HOST) \
			--users=10 \
			--spawn-rate=2 \
			--run-time=120s \
			--headless \
			--html=reports/loadtest_resilience.html \
			--csv=reports/loadtest_resilience \
			--only-summary"
	@echo "Report: reports/loadtest_resilience.html"

.PHONY: resilience-locust-ui
resilience-locust-ui:                      ## Start Locust web UI for slow-time-server
	@echo "Starting Locust web UI for resilience testing..."
	@echo "   Open http://localhost:8090 in your browser"
	@echo "   Host: $(RESILIENCE_HOST)"
	@echo "   Requires: make resilience-up"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		locust -f $(RESILIENCE_LOCUSTFILE) \
			--host=$(RESILIENCE_HOST) \
			--web-host=0.0.0.0 --web-port=8090"

.PHONY: resilience-jmeter
resilience-jmeter: jmeter-check            ## Run JMeter baseline test against slow-time-server (20 threads, 5min)
	@echo "Running resilience JMeter baseline test..."
	@echo "   Slow Time Server: $(RESILIENCE_HOST)"
	@echo "   Threads: 20, Duration: 5 minutes"
	@echo "   Requires: make resilience-up"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n -t $(RESILIENCE_JMETER_PLAN) \
		-JSLOW_TIME_URL=$(RESILIENCE_HOST) \
		-JTHREADS=20 -JRAMP_UP=30 -JDURATION=300 \
		-l $(JMETER_RESULTS_DIR)/resilience_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/resilience_$$TIMESTAMP \
		$(JMETER_SUMMARISER) $(JMETER_OPTS)
	@echo "Report: $(JMETER_RESULTS_DIR)/resilience_*/index.html"

# =============================================================================
# help: 🎯 BENCHMARK STACK (Go benchmark-server)
# help: benchmark-up           - Start benchmark stack (MCP servers + auto-registration)
# help: benchmark-down         - Stop benchmark stack
# help: benchmark-clean        - Stop and remove all benchmark data (volumes)
# help: benchmark-status       - Show status of benchmark services
# help: benchmark-logs         - Show benchmark stack logs
# help: bench-compare          - Run performance comparisons for Rust plugins
# help:
# help: Environment variables:
# help:   BENCHMARK_SERVER_COUNT  - Number of MCP servers to spawn (default: 10)

# Benchmark configuration (override via environment)
BENCHMARK_SERVER_COUNT ?= 10
BENCHMARK_START_PORT ?= 9000

.PHONY: benchmark-up
benchmark-up:                              ## Start benchmark stack (MCP servers + registration)
	@echo "🎯 Starting benchmark stack ($(BENCHMARK_SERVER_COUNT) MCP servers on ports $(BENCHMARK_START_PORT)-$$(($(BENCHMARK_START_PORT) + $(BENCHMARK_SERVER_COUNT) - 1)))..."
	BENCHMARK_SERVER_COUNT=$(BENCHMARK_SERVER_COUNT) BENCHMARK_START_PORT=$(BENCHMARK_START_PORT) \
		$(COMPOSE_CMD_MONITOR) --profile benchmark up -d
	@echo ""
	@echo "✅ Benchmark stack started!"
	@echo ""
	@echo "   🚀 Benchmark Servers: http://localhost:$(BENCHMARK_START_PORT)-$$(($(BENCHMARK_START_PORT) + $(BENCHMARK_SERVER_COUNT) - 1))"
	@echo "      • MCP endpoint:  http://localhost:<port>/mcp"
	@echo "      • Health:        http://localhost:<port>/health"
	@echo "      • Version:       http://localhost:<port>/version"
	@echo ""
	@echo "   📝 Registered as 'benchmark-$(BENCHMARK_START_PORT)' through 'benchmark-$$(($(BENCHMARK_START_PORT) + $(BENCHMARK_SERVER_COUNT) - 1))' gateways"
	@echo ""
	@echo "   Run load test: make load-test-ui"
	@echo ""
	@echo "   💡 Configure server count: BENCHMARK_SERVER_COUNT=50 make benchmark-up"

.PHONY: benchmark-down
benchmark-down:                            ## Stop benchmark stack
	@echo "🎯 Stopping benchmark stack..."
	$(COMPOSE_CMD_MONITOR) --profile benchmark down --remove-orphans
	@echo "✅ Benchmark stack stopped."

.PHONY: benchmark-clean
benchmark-clean:                           ## Stop and remove all benchmark data (volumes)
	@echo "🎯 Stopping and cleaning benchmark stack..."
	$(COMPOSE_CMD_MONITOR) --profile benchmark down -v --remove-orphans
	@echo "✅ Benchmark stack stopped and volumes removed."

.PHONY: benchmark-status
benchmark-status:                          ## Show status of benchmark services
	@echo "🎯 Benchmark stack status:"
	@$(COMPOSE_CMD_MONITOR) ps | grep -E "(benchmark)" || \
		echo "   No benchmark services running. Start with 'make benchmark-up'"

.PHONY: benchmark-logs
benchmark-logs:                            ## Show benchmark stack logs
	$(COMPOSE_CMD_MONITOR) --profile benchmark logs -f --tail=100


# =============================================================================
# 🖼️  EMBEDDED / EMBEDDED / IFRAME STACK - iframe mode with benchmark servers
# =============================================================================
# help: 🖼️  EMBEDDED / EMBEDDED / IFRAME STACK
# help: embedded-up              - Start embedded stack (iframe mode + benchmark servers)
# help: embedded-down            - Stop embedded stack
# help: embedded-clean           - Stop and remove all embedded data (volumes)
# help: embedded-status          - Show status of embedded services
# help: embedded-logs            - Show embedded stack logs
# help:
# help: Environment variables:
# help:   BENCHMARK_SERVER_COUNT  - Number of MCP servers to spawn (default: 10)

EMBEDDED_COMPOSE := $(COMPOSE_CMD) -f docker-compose.yml -f docker-compose-embedded.yml --profile benchmark

.PHONY: embedded-up
embedded-up:                               ## Start embedded stack (iframe mode + benchmark servers)
	@if [ ! -f "docker-compose-embedded.yml" ]; then \
		echo "❌ Compose override file not found: docker-compose-embedded.yml"; \
		exit 1; \
	fi
	@echo "🖼️  Starting embedded stack (iframe mode + $(BENCHMARK_SERVER_COUNT) benchmark servers)..."
	BENCHMARK_SERVER_COUNT=$(BENCHMARK_SERVER_COUNT) BENCHMARK_START_PORT=$(BENCHMARK_START_PORT) \
		$(EMBEDDED_COMPOSE) up -d
	@echo ""
	@echo "✅ Embedded stack started!"
	@echo ""
	@echo "Service              URL                           Purpose"
	@echo "──────────────────────────────────────────────────────────────────────────"
	@echo "iframe Harness       http://localhost:8889         UI inside iframe"
	@echo "Gateway (nginx)      http://localhost:8080         API proxy"
	@echo "Gateway Admin UI     http://localhost:8080/admin/  Direct admin access"
	@echo "Benchmark Servers    http://localhost:9000-9099    MCP benchmark targets"
	@echo ""
	@echo "   📝 $(BENCHMARK_SERVER_COUNT) benchmark servers auto-registered (50 tools each = $$(($(BENCHMARK_SERVER_COUNT) * 50)) tools)"
	@echo ""
	@echo "   🔧 Embedded settings:"
	@echo "      • UI mode:       embedded (iframe-safe)"
	@echo "      • Default role:  developer"
	@echo "      • Public visibility: disabled"
	@echo ""
	@echo "   💡 Configure: BENCHMARK_SERVER_COUNT=50 make embedded-up"

.PHONY: embedded-down
embedded-down:                             ## Stop embedded stack
	@echo "🖼️  Stopping embedded stack..."
	$(EMBEDDED_COMPOSE) down --remove-orphans
	@echo "✅ Embedded stack stopped."

.PHONY: embedded-clean
embedded-clean:                            ## Stop and remove all embedded data (volumes)
	@echo "🖼️  Stopping and cleaning embedded stack..."
	$(EMBEDDED_COMPOSE) down -v --remove-orphans
	@echo "✅ Embedded stack stopped and volumes removed."

.PHONY: embedded-status
embedded-status:                           ## Show status of embedded services
	@echo "🖼️  Embedded stack status:"
	@$(EMBEDDED_COMPOSE) ps || \
		echo "   No embedded services running. Start with 'make embedded-up'"

.PHONY: embedded-logs
embedded-logs:                             ## Show embedded stack logs
	$(EMBEDDED_COMPOSE) logs -f --tail=100

# =============================================================================
# 🚀 PERFORMANCE TESTING STACK - High-capacity configuration
# =============================================================================
# help: 🚀 PERFORMANCE TESTING STACK
# help: performance-up         - Start performance stack (7 gateways, PostgreSQL replica, monitoring)
# help: performance-down       - Stop performance stack
# help: performance-clean      - Stop and remove all performance data (volumes)
# help: performance-logs       - Show performance stack logs

# Compose command for performance testing (uses docker-compose-performance.yml)
COMPOSE_CMD_PERF := $(shell \
	if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then \
		echo "docker compose -f docker-compose-performance.yml"; \
	elif command -v podman &>/dev/null && podman compose version &>/dev/null 2>&1; then \
		echo "podman compose -f docker-compose-performance.yml"; \
	else \
		echo "docker-compose -f docker-compose-performance.yml"; \
	fi)

.PHONY: performance-up
performance-up:                            ## Start performance stack (7 gateways, PostgreSQL replica, monitoring)
	@echo "🚀 Starting performance testing stack..."
	@echo "   • 7 gateway replicas"
	@echo "   • PostgreSQL primary + read replica (streaming replication)"
	@echo "   • PgBouncer with load balancing"
	@echo "   • Full monitoring stack"
	@echo ""
	# Enable OTEL tracing + JSON console logs for the monitoring profile (Tempo + Loki correlation)
	LOG_FORMAT=json \
	OTEL_ENABLE_OBSERVABILITY=true \
	OTEL_TRACES_EXPORTER=otlp \
	OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317 \
	$(COMPOSE_CMD_PERF) --profile monitoring --profile replica up -d
	@echo "⏳ Waiting for Grafana to be ready..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12; do \
		if curl -s -o /dev/null -w '' http://localhost:3000/api/health 2>/dev/null; then break; fi; \
		sleep 3; \
	done
	@# Configure Grafana: star dashboard and set as home
	@curl -s -X POST -u admin:changeme 'http://localhost:3000/api/user/stars/dashboard/uid/mcp-gateway-overview' >/dev/null 2>&1 || true
	@curl -s -X PUT -u admin:changeme -H "Content-Type: application/json" -d '{"homeDashboardUID": "mcp-gateway-overview"}' 'http://localhost:3000/api/org/preferences' >/dev/null 2>&1 || true
	@curl -s -X PUT -u admin:changeme -H "Content-Type: application/json" -d '{"homeDashboardUID": "mcp-gateway-overview"}' 'http://localhost:3000/api/user/preferences' >/dev/null 2>&1 || true
	@echo ""
	@echo "✅ Performance stack started!"
	@echo ""
	@echo "   🌐 Grafana:    http://localhost:3000 (admin/changeme)"
	@echo "   🔥 Prometheus: http://localhost:9090"
	@echo "   🧵 Tempo:      http://localhost:3200 (OTLP: 4317 gRPC, 4318 HTTP)"
	@echo "   🐘 PostgreSQL: Primary + Read Replica (load balanced via PgBouncer)"
	@echo ""
	@echo "   📊 Key Dashboards:"
	@echo "      • ContextForge Overview - main dashboard (set as home)"
	@echo "      • PostgreSQL Replication - primary/replica stats, lag, distribution"
	@echo "      • PostgreSQL Database - detailed DB metrics"
	@echo "      • PgBouncer - connection pool stats"
	@echo ""
	@echo "   🏋️ Configuration:"
	@echo "      • 7 gateway replicas (vs 3 in standard)"
	@echo "      • PostgreSQL read replica for read scaling"
	@echo "      • PgBouncer round-robin across primary + replica"
	@echo ""
	@echo "   Run load test: make load-test-ui"

.PHONY: performance-down
performance-down:                          ## Stop performance stack
	@echo "🚀 Stopping performance stack..."
	$(COMPOSE_CMD_PERF) --profile monitoring --profile replica down --remove-orphans
	@echo "✅ Performance stack stopped."

.PHONY: performance-logs
performance-logs:                          ## Show performance stack logs
	$(COMPOSE_CMD_PERF) --profile monitoring --profile replica logs -f --tail=100

.PHONY: performance-clean
performance-clean:                         ## Stop and remove all performance data (volumes)
	@echo "🚀 Stopping and cleaning performance stack..."
	$(COMPOSE_CMD_PERF) --profile monitoring --profile replica down -v
	@echo "✅ Performance stack stopped and volumes removed."

# =============================================================================
# 🔥 HTTP LOAD TESTING - Locust-based traffic generation
# =============================================================================
# help: 🔥 HTTP LOAD TESTING (Locust)
# help: load-test             - Run HTTP load test (4000 users, 5m, headless, summary only)
# help: load-test-cli         - Run HTTP load test with live stats (same as UI but headless)
# help: load-test-ui          - Start Locust web UI (4000 users, 200 spawn/s)
# help: load-test-light       - Light load test (10 users, 30s)
# help: load-test-heavy       - Heavy load test (200 users, 120s)
# help: load-test-sustained   - Sustained load test (25 users, 300s)
# help: load-test-stress      - Stress test (500 users, 60s, minimal wait)
# help: load-test-spin-detector - CPU spin loop detector (spike/drop pattern, issue #2360)
# help: load-test-report      - Show last load test HTML report
# help: load-test-compose     - Light load test for compose stack (port 4444)
# help: load-test-compose-docker - Light load test using containerized Locust (no local Locust required)
# help: load-test-timeserver  - Load test fast_time_server (5 users, 30s)
# help: load-test-fasttime    - Load test fast_time MCP tools (50 users, 60s)
# help: load-test-1000        - High-load test (1000 users, 120s)
# help: load-test-summary     - Parse CSV reports and show summary statistics

# Default load test configuration (optimized for 4000+ users)
LOADTEST_HOST ?= http://localhost:8080
LOADTEST_USERS ?= 4000
LOADTEST_SPAWN_RATE ?= 200
LOADTEST_RUN_TIME ?= 5m
LOADTEST_PROCESSES ?= -1
LOADTEST_UI_PORT ?= 8090
LOADTEST_LOCUSTFILE := tests/loadtest/locustfile.py
LOADTEST_HTML_REPORT := reports/locust_report.html
LOADTEST_CSV_PREFIX := reports/locust

# Secrets Detection Benchmark Configuration
# These values are tuned for focused plugin performance comparison
SECRET_DETECTION_LOCUSTFILE := tests/loadtest/locustfile_secret_detection.py
SECRET_DETECTION_LOADTEST_HOST ?= http://localhost:8080
SECRET_DETECTION_LOADTEST_USERS ?= 100          # Moderate load to isolate plugin overhead
SECRET_DETECTION_LOADTEST_SPAWN_RATE ?= 10      # Gradual ramp-up for stable measurements
SECRET_DETECTION_LOADTEST_RUN_TIME ?= 60s       # 1 minute per phase (Rust + Python)
SECRET_DETECTION_BENCH_GATEWAY_REPLICAS ?= 1    # Single replica for consistent comparison
SECRET_DETECTION_BENCH_GUNICORN_WORKERS ?= 2    # Minimal workers to highlight plugin impact
SECRET_DETECTION_BENCH_CPU_LIMIT ?= 1           # 1 core limit to amplify performance differences
SECRET_DETECTION_BENCH_CPU_RESERVATION ?= 0.5   # Reserve half core for baseline
SECRET_DETECTION_BENCH_MEM_LIMIT ?= 3G          # Generous memory to avoid OOM
SECRET_DETECTION_BENCH_MEM_RESERVATION ?= 1G    # Reserve 1GB baseline
# Auto-detect c-ares resolver availability (empty string if unavailable)
LOADTEST_GEVENT_RESOLVER := $(shell python3 -c "from gevent.resolver.cares import Resolver; print('ares')" 2>/dev/null || echo "")

load-test:                                 ## Run HTTP load test (4000 users, 5m, headless)
	@echo "🔥 Running HTTP load test with Locust..."
	@echo "   Host: $(LOADTEST_HOST)"
	@echo "   Users: $(LOADTEST_USERS)"
	@echo "   Spawn rate: $(LOADTEST_SPAWN_RATE)/s"
	@echo "   Duration: $(LOADTEST_RUN_TIME)"
	@echo "   Workers: $(LOADTEST_PROCESSES) (-1 = auto-detect CPUs)"
	@echo ""
	@# Check ulimits and warn if below threshold
	@NOFILE=$$(ulimit -n 2>/dev/null || echo 0); \
	NPROC=$$(ulimit -u 2>/dev/null || echo 0); \
	if [ "$$NOFILE" -lt 10000 ]; then \
		echo "   ⚠️  WARNING: ulimit -n ($$NOFILE) is below 10000 - may cause connection failures"; \
		echo "   💡 Fix: Add to /etc/security/limits.conf and restart shell"; \
		echo ""; \
	fi; \
	if [ "$$NPROC" -lt 10000 ]; then \
		echo "   ⚠️  WARNING: ulimit -u ($$NPROC) is below 10000 - may limit worker processes"; \
		echo ""; \
	fi
	@echo "   💡 Tip: Start server first with 'make dev' in another terminal"
	@echo "   💡 Tip: For best results, run: sudo scripts/tune-loadtest.sh"
	@echo ""
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p reports
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		ulimit -n 65536 2>/dev/null || true && \
		$(if $(LOADTEST_GEVENT_RESOLVER),GEVENT_RESOLVER=$(LOADTEST_GEVENT_RESOLVER)) \
		locust -f $(LOADTEST_LOCUSTFILE) \
			--host=$(LOADTEST_HOST) \
			--users=$(LOADTEST_USERS) \
			--spawn-rate=$(LOADTEST_SPAWN_RATE) \
			--run-time=$(LOADTEST_RUN_TIME) \
			--processes=$(LOADTEST_PROCESSES) \
			--headless \
			--html=$(LOADTEST_HTML_REPORT) \
			--csv=$(LOADTEST_CSV_PREFIX) \
			--only-summary"
	@echo ""
	@echo "✅ Load test complete!"
	@echo "📄 HTML Report: $(LOADTEST_HTML_REPORT)"
	@echo "📊 CSV Reports: $(LOADTEST_CSV_PREFIX)_*.csv"

load-test-ui:                              ## Start Locust web UI at http://localhost:$(LOADTEST_UI_PORT)
	@echo "🔥 Starting Locust Web UI (optimized for 4000+ users)..."
	@echo "   🌐 Open http://localhost:$(LOADTEST_UI_PORT) in your browser"
	@echo "   🎯 Default host: $(LOADTEST_HOST)"
	@echo "   👥 Default users: $(LOADTEST_USERS), spawn rate: $(LOADTEST_SPAWN_RATE)/s"
	@echo "   ⏱️  Default run time: $(LOADTEST_RUN_TIME)"
	@echo "   🚀 Workers: $(LOADTEST_PROCESSES) (-1 = auto-detect CPUs)"
	@echo ""
	@# Check ulimits and warn if below threshold
	@NOFILE=$$(ulimit -n 2>/dev/null || echo 0); \
	NPROC=$$(ulimit -u 2>/dev/null || echo 0); \
	if [ "$$NOFILE" -lt 10000 ]; then \
		echo "   ⚠️  WARNING: ulimit -n ($$NOFILE) is below 10000 - may cause connection failures"; \
		echo "   💡 Fix: Add to /etc/security/limits.conf and restart shell:"; \
		echo "      *  soft  nofile  65536"; \
		echo "      *  hard  nofile  65536"; \
		echo ""; \
	fi; \
	if [ "$$NPROC" -lt 10000 ]; then \
		echo "   ⚠️  WARNING: ulimit -u ($$NPROC) is below 10000 - may limit worker processes"; \
		echo ""; \
	fi
	@echo "   💡 For best results, run: sudo scripts/tune-loadtest.sh"
	@echo "   💡 Use 'User classes' dropdown to select FastTimeUser, etc."
	@echo "   💡 Start benchmark servers first: make benchmark-up"
	@echo ""
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		ulimit -n 65536 2>/dev/null || true && \
		$(if $(LOADTEST_GEVENT_RESOLVER),GEVENT_RESOLVER=$(LOADTEST_GEVENT_RESOLVER)) \
		locust -f $(LOADTEST_LOCUSTFILE) \
			--host=$(LOADTEST_HOST) \
			--users=$(LOADTEST_USERS) \
			--spawn-rate=$(LOADTEST_SPAWN_RATE) \
			--run-time=$(LOADTEST_RUN_TIME) \
			--processes=$(LOADTEST_PROCESSES) \
			--web-port=$(LOADTEST_UI_PORT) \
			--class-picker"

.PHONY: load-test-cli
load-test-cli:                             ## Run HTTP load test with live stats (same as UI but headless)
	@echo "🔥 Running HTTP load test with live stats (CLI mode)..."
	@echo "   Host: $(LOADTEST_HOST)"
	@echo "   Users: $(LOADTEST_USERS)"
	@echo "   Spawn rate: $(LOADTEST_SPAWN_RATE)/s"
	@echo "   Duration: $(LOADTEST_RUN_TIME)"
	@echo "   Workers: $(LOADTEST_PROCESSES) (-1 = auto-detect CPUs)"
	@echo ""
	@echo "   💡 Tip: Start server first with 'make dev' in another terminal"
	@echo "   💡 Tip: For best results, run: sudo scripts/tune-loadtest.sh"
	@echo ""
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p reports
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		ulimit -n 65536 2>/dev/null || true && \
		$(if $(LOADTEST_GEVENT_RESOLVER),GEVENT_RESOLVER=$(LOADTEST_GEVENT_RESOLVER)) \
		locust -f $(LOADTEST_LOCUSTFILE) \
			--host=$(LOADTEST_HOST) \
			--users=$(LOADTEST_USERS) \
			--spawn-rate=$(LOADTEST_SPAWN_RATE) \
			--run-time=$(LOADTEST_RUN_TIME) \
			--processes=$(LOADTEST_PROCESSES) \
			--headless \
			--html=$(LOADTEST_HTML_REPORT) \
			--csv=$(LOADTEST_CSV_PREFIX)"
	@echo ""
	@echo "✅ Load test complete!"
	@echo "📄 HTML Report: $(LOADTEST_HTML_REPORT)"
	@echo "📊 CSV Reports: $(LOADTEST_CSV_PREFIX)_*.csv"

load-test-light:                           ## Light load test (10 users, 30s)
	@echo "🔥 Running LIGHT load test..."
	@$(MAKE) load-test LOADTEST_USERS=10 LOADTEST_SPAWN_RATE=2 LOADTEST_RUN_TIME=30s

load-test-heavy:                           ## Heavy load test (200 users, 120s)
	@echo "🔥 Running HEAVY load test..."
	@echo "   ⚠️  This will generate significant load on your server"
	@$(MAKE) load-test LOADTEST_USERS=200 LOADTEST_SPAWN_RATE=20 LOADTEST_RUN_TIME=120s

load-test-sustained:                       ## Sustained load test (25 users, 300s)
	@echo "🔥 Running SUSTAINED load test (5 minutes)..."
	@$(MAKE) load-test LOADTEST_USERS=25 LOADTEST_SPAWN_RATE=5 LOADTEST_RUN_TIME=300s

load-test-stress:                          ## Stress test (500 users, 60s)
	@echo "🔥 Running STRESS test..."
	@echo "   ⚠️  WARNING: This will generate EXTREME load!"
	@echo "   ⚠️  Your server may become unresponsive"
	@echo ""
	@read -p "Continue with stress test? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(MAKE) load-test LOADTEST_USERS=500 LOADTEST_SPAWN_RATE=50 LOADTEST_RUN_TIME=60s; \
	else \
		echo "❌ Cancelled"; \
	fi

SPIN_DETECTOR_RUN_TIME ?= 300m
SPIN_DETECTOR_WORKERS ?= $(LOADTEST_PROCESSES)

.PHONY: load-test-spin-detector
load-test-spin-detector:                   ## CPU spin loop detector (spike/drop pattern, issue #2360)
	@echo "🔄 CPU SPIN LOOP DETECTOR (Escalating load pattern)"
	@echo "   Issue: https://github.com/IBM/mcp-context-forge/issues/2360"
	@echo ""
	@echo "   ESCALATING PATTERN (1000/s spawn rate):"
	@echo "   ┌─────────┬─────────┬────────────┬────────────┐"
	@echo "   │ Wave    │ Users   │ Duration   │ Pause      │"
	@echo "   ├─────────┼─────────┼────────────┼────────────┤"
	@echo "   │ 1       │  4,000  │ 30 seconds │ 10 seconds │"
	@echo "   │ 2       │  6,000  │ 45 seconds │ 15 seconds │"
	@echo "   │ 3       │  8,000  │ 60 seconds │ 20 seconds │"
	@echo "   │ 4       │ 10,000  │ 75 seconds │ 30 seconds │"
	@echo "   │ 5       │ 10,000  │ 90 seconds │ 30 seconds │"
	@echo "   └─────────┴─────────┴────────────┴────────────┘"
	@echo "   → Repeats until timeout (Ctrl+C to stop early)"
	@echo ""
	@echo "   🎯 Target: $(LOADTEST_HOST)"
	@echo "   ⏱️  Runtime: $(SPIN_DETECTOR_RUN_TIME) (override: SPIN_DETECTOR_RUN_TIME=60m)"
	@echo "   👷 Workers: $(SPIN_DETECTOR_WORKERS) (-1 = auto-detect CPUs)"
	@echo "   📊 Shows RPS + Failure % during load phases"
	@echo "   🔐 Authentication: JWT (auto-generated from .env settings)"
	@echo "   🔇 Verbose logs off (set LOCUST_VERBOSE=1 to enable)"
	@echo ""
	@echo "   💡 Prerequisites:"
	@echo "      docker compose up -d   # Gateway on port 8080 (via nginx)"
	@echo ""
	@echo "   📈 MONITORING (run in another terminal):"
	@echo "      watch -n 2 'docker stats --no-stream | grep gateway'"
	@echo ""
	@echo "   ✅ PASS: CPU drops to <10% during pause phases"
	@echo "   ❌ FAIL: CPU stays at 100%+ per worker during pauses"
	@echo ""
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p reports
	@echo "Starting in 3 seconds... (Ctrl+C to cancel)"
	@sleep 3
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		cd tests/loadtest && \
		ulimit -n 65536 2>/dev/null || true && \
		$(if $(LOADTEST_GEVENT_RESOLVER),GEVENT_RESOLVER=$(LOADTEST_GEVENT_RESOLVER)) \
		LOCUST_WORKERS=$(SPIN_DETECTOR_WORKERS) \
		locust -f locustfile_spin_detector.py \
			--host=$(LOADTEST_HOST) \
			--headless \
			--run-time=$(SPIN_DETECTOR_RUN_TIME) \
			--processes=$(SPIN_DETECTOR_WORKERS) \
			--html=../../reports/spin_detector_report.html \
			--csv=../../reports/spin_detector \
			--only-summary"
	@echo ""
	@echo "📄 HTML Report: reports/spin_detector_report.html"
	@echo "📋 Log file: /tmp/spin_detector.log"
	@echo "   Monitor: tail -f /tmp/spin_detector.log"

load-test-report:                          ## Show last load test HTML report
	@if [ -f "$(LOADTEST_HTML_REPORT)" ]; then \
		echo "📊 Opening load test report: $(LOADTEST_HTML_REPORT)"; \
		if command -v xdg-open &> /dev/null; then \
			xdg-open $(LOADTEST_HTML_REPORT); \
		elif command -v open &> /dev/null; then \
			open $(LOADTEST_HTML_REPORT); \
		else \
			echo "Open $(LOADTEST_HTML_REPORT) in your browser"; \
		fi; \
	else \
		echo "❌ No report found. Run 'make load-test' first."; \
	fi

load-test-compose:                         ## Light load test for compose stack (10 users, 30s, port 4444)
	@echo "🐳 Running compose-optimized load test..."
	@echo "   Host: http://localhost:4444"
	@echo "   Users: 10, Duration: 30s"
	@echo "   💡 Requires: make compose-up"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p reports
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		locust -f $(LOADTEST_LOCUSTFILE) \
			--host=http://localhost:4444 \
			--users=10 \
			--spawn-rate=2 \
			--run-time=30s \
			--headless \
			--html=reports/loadtest_compose.html \
			--csv=reports/loadtest_compose \
			--only-summary"
	@echo "✅ Report: reports/loadtest_compose.html"

.PHONY: load-test-compose-docker
load-test-compose-docker:                  ## Light load test using containerized Locust (10 users, 30s)
	@echo "🐳 Running compose load test with CONTAINERIZED Locust..."
	@echo "   Target: http://nginx:80 (docker network)"
	@echo "   Users: 10, Duration: 30s"
	@echo "   💡 Requires: make testing-up"
	@mkdir -p reports
	@# Ensure a JWT exists in the shared locust_token volume (no host-side python/locust required)
	@HOST_UID=$(HOST_UID) HOST_GID=$(HOST_GID) \
		$(COMPOSE_CMD_MONITOR) --profile testing run --rm locust_token >/dev/null 2>&1 || true
	@HOST_UID=$(HOST_UID) HOST_GID=$(HOST_GID) \
		LOCUST_MODE=headless LOCUST_USERS=10 LOCUST_SPAWN_RATE=2 LOCUST_RUN_TIME=30s \
		$(COMPOSE_CMD_MONITOR) --profile testing run --rm locust
	@echo "✅ Reports: reports/locust_report.html and reports/locust_*.csv"

load-test-timeserver:                      ## Load test fast_time_server tools (5 users, 30s)
	@echo "⏰ Running time server load test..."
	@echo "   Host: http://localhost:4444"
	@echo "   Users: 5, Duration: 30s"
	@echo "   💡 Requires: docker compose --profile with-fast-time up -d"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p reports
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		locust -f $(LOADTEST_LOCUSTFILE) \
			--host=http://localhost:4444 \
			--users=5 \
			--spawn-rate=1 \
			--run-time=30s \
			--headless \
			--html=reports/loadtest_timeserver.html \
			--csv=reports/loadtest_timeserver \
			FastTimeUser \
			--only-summary"
	@echo "✅ Report: reports/loadtest_timeserver.html"

load-test-fasttime:                        ## Load test fast_time MCP tools (50 users, 60s)
	@echo "⏰ Running FastTime MCP server load test..."
	@echo "   Host: http://localhost:4444"
	@echo "   Users: 50, Duration: 60s"
	@echo "   💡 Requires: docker compose --profile with-fast-time up -d"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p reports
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		locust -f $(LOADTEST_LOCUSTFILE) \
			--host=http://localhost:4444 \
			--users=50 \
			--spawn-rate=10 \
			--run-time=60s \
			--headless \
			--html=reports/loadtest_fasttime.html \
			--csv=reports/loadtest_fasttime \
			FastTimeUser \
			--only-summary"
	@echo "✅ Report: reports/loadtest_fasttime.html"


.PHONY: load-test-secret-detection-compare
load-test-secret-detection-compare:        ## Focused secrets-detection benchmark: Rust run first, then forced Python fallback
	@echo "🔐 Running focused secrets-detection benchmark..."
	@echo "   Host: $(SECRET_DETECTION_LOADTEST_HOST)"
	@echo "   Users: $(SECRET_DETECTION_LOADTEST_USERS)"
	@echo "   Spawn rate: $(SECRET_DETECTION_LOADTEST_SPAWN_RATE)/s"
	@echo "   Duration: $(SECRET_DETECTION_LOADTEST_RUN_TIME)"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@VENV_DIR="$(VENV_DIR)" \
	COMPOSE_CMD="$(COMPOSE_CMD)" \
	IMAGE_LOCAL_NAME="$(call get_image_name)" \
	SECRET_DETECTION_LOADTEST_HOST="$(SECRET_DETECTION_LOADTEST_HOST)" \
	SECRET_DETECTION_LOADTEST_USERS="$(SECRET_DETECTION_LOADTEST_USERS)" \
	SECRET_DETECTION_LOADTEST_SPAWN_RATE="$(SECRET_DETECTION_LOADTEST_SPAWN_RATE)" \
	SECRET_DETECTION_LOADTEST_RUN_TIME="$(SECRET_DETECTION_LOADTEST_RUN_TIME)" \
	SECRET_DETECTION_BENCH_GATEWAY_REPLICAS="$(SECRET_DETECTION_BENCH_GATEWAY_REPLICAS)" \
	SECRET_DETECTION_BENCH_GUNICORN_WORKERS="$(SECRET_DETECTION_BENCH_GUNICORN_WORKERS)" \
	SECRET_DETECTION_BENCH_CPU_LIMIT="$(SECRET_DETECTION_BENCH_CPU_LIMIT)" \
	SECRET_DETECTION_BENCH_CPU_RESERVATION="$(SECRET_DETECTION_BENCH_CPU_RESERVATION)" \
	SECRET_DETECTION_BENCH_MEM_LIMIT="$(SECRET_DETECTION_BENCH_MEM_LIMIT)" \
	SECRET_DETECTION_BENCH_MEM_RESERVATION="$(SECRET_DETECTION_BENCH_MEM_RESERVATION)" \
	bash tests/loadtest/run_secret_detection_compare.sh

load-test-1000:                            ## High-load test (1000 users, 120s) - requires tuned compose
	@echo "🔥 Running HIGH LOAD test (1000 users, ~1000 RPS)..."
	@echo "   Host: http://localhost:4444"
	@echo "   Users: 1000, Spawn: 50/s, Duration: 120s"
	@echo "   ⚠️  Requires tuned compose stack (make compose-down && make compose-up)"
	@read -p "Continue? [y/N] " -n 1 -r; echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		test -d "$(VENV_DIR)" || $(MAKE) venv; \
		mkdir -p reports; \
		/bin/bash -c "source $(VENV_DIR)/bin/activate && \
			locust -f $(LOADTEST_LOCUSTFILE) \
				--host=http://localhost:4444 \
				--users=1000 \
				--spawn-rate=50 \
				--run-time=120s \
				--headless \
				--html=reports/loadtest_1000.html \
				--csv=reports/loadtest_1000 \
				--only-summary"; \
		echo "✅ Report: reports/loadtest_1000.html"; \
	else \
		echo "❌ Cancelled"; \
	fi

load-test-summary:                         ## Parse CSV reports and show summary statistics
	@if [ -f "$(LOADTEST_CSV_PREFIX)_stats.csv" ]; then \
		echo ""; \
		echo "===================================================================================================="; \
		echo "LOAD TEST SUMMARY (from $(LOADTEST_CSV_PREFIX)_stats.csv)"; \
		echo "===================================================================================================="; \
		echo ""; \
		python3 -c " \
import csv; \
import sys; \
with open('$(LOADTEST_CSV_PREFIX)_stats.csv') as f: \
    reader = list(csv.DictReader(f)); \
    if not reader: \
        print('No data found'); \
        sys.exit(0); \
    agg = [r for r in reader if r.get('Name') == 'Aggregated']; \
    if agg: \
        a = agg[0]; \
        print('OVERALL METRICS'); \
        print('-' * 100); \
        print(f\"  Total Requests:     {int(float(a.get('Request Count', 0))):,}\"); \
        print(f\"  Total Failures:     {int(float(a.get('Failure Count', 0))):,}\"); \
        print(f\"  Requests/sec:       {float(a.get('Requests/s', 0)):.2f}\"); \
        print(); \
        print('  Response Times (ms):'); \
        print(f\"    Average:          {float(a.get('Average Response Time', 0)):.2f}\"); \
        print(f\"    Min:              {float(a.get('Min Response Time', 0)):.2f}\"); \
        print(f\"    Max:              {float(a.get('Max Response Time', 0)):.2f}\"); \
        print(f\"    Median (p50):     {float(a.get('50%', 0)):.2f}\"); \
        print(f\"    p90:              {float(a.get('90%', 0)):.2f}\"); \
        print(f\"    p95:              {float(a.get('95%', 0)):.2f}\"); \
        print(f\"    p99:              {float(a.get('99%', 0)):.2f}\"); \
    print(); \
    print('ENDPOINT BREAKDOWN (Top 15)'); \
    print('-' * 100); \
    print(f\"{'Endpoint':<40} {'Reqs':>8} {'Fails':>7} {'Avg':>8} {'Min':>8} {'Max':>8} {'p95':>8}\"); \
    print('-' * 100); \
    endpoints = [r for r in reader if r.get('Name') != 'Aggregated'][:15]; \
    for e in endpoints: \
        name = e.get('Name', '')[:38] + '..' if len(e.get('Name', '')) > 40 else e.get('Name', ''); \
        print(f\"{name:<40} {int(float(e.get('Request Count', 0))):>8,} {int(float(e.get('Failure Count', 0))):>7,} {float(e.get('Average Response Time', 0)):>8.1f} {float(e.get('Min Response Time', 0)):>8.1f} {float(e.get('Max Response Time', 0)):>8.1f} {float(e.get('95%', 0)):>8.1f}\"); \
"; \
		echo ""; \
		echo "===================================================================================================="; \
		echo ""; \
		echo "📊 Full reports:"; \
		echo "   HTML: $(LOADTEST_HTML_REPORT)"; \
		echo "   CSV:  $(LOADTEST_CSV_PREFIX)_stats.csv"; \
	else \
		echo "❌ No CSV report found at $(LOADTEST_CSV_PREFIX)_stats.csv"; \
		echo "   Run 'make load-test' first to generate reports."; \
	fi

# --- Baseline Load Tests (individual components without gateway) ---
# help: load-test-baseline     - Baseline test: Fast Time Server REST API (1000 users, 3min)
# help: load-test-baseline-ui  - Baseline test with Locust Web UI
# help: load-test-baseline-stress - Baseline stress test (2000 users, 3min)

BASELINE_HOST ?= http://localhost:8888

load-test-baseline:                        ## Baseline test: Fast Time Server REST API (1000 users, 3min)
	@echo "📊 Running BASELINE load test (Fast Time Server REST API)..."
	@echo "   Host: $(BASELINE_HOST)"
	@echo "   Users: 1000, Duration: 3 minutes"
	@echo "   💡 Requires: docker compose --profile with-fast-time up -d"
	@echo "   📝 This tests the MCP server directly WITHOUT the gateway"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c 'source $(VENV_DIR)/bin/activate && \
		cd tests/loadtest && \
		locust -f locustfile_baseline.py \
			--host=$(BASELINE_HOST) \
			--users=1000 \
			--spawn-rate=100 \
			--run-time=180s \
			--headless \
			--csv=baseline \
			--html=baseline_report.html'
	@echo ""
	@echo "📊 Baseline report: tests/loadtest/baseline_report.html"

load-test-baseline-ui:                     ## Baseline test with Locust Web UI (class picker enabled)
	@echo "📊 Starting BASELINE load test Web UI..."
	@echo "   🌐 Open http://localhost:8089 in your browser"
	@echo "   🎯 Host: $(BASELINE_HOST)"
	@echo "   👥 Defaults: 1000 users, 100 spawn/s, 3 min"
	@echo "   🎛️  Class picker enabled - select which tests to run"
	@echo "   💡 Requires: docker compose --profile with-fast-time up -d"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c 'source $(VENV_DIR)/bin/activate && \
		cd tests/loadtest && \
		locust -f locustfile_baseline.py \
			--host=$(BASELINE_HOST) \
			--users=1000 \
			--spawn-rate=100 \
			--run-time=180s \
			--class-picker'

load-test-baseline-stress:                 ## Baseline stress test (2000 users, 3min)
	@echo "📊 Running BASELINE STRESS test..."
	@echo "   Host: $(BASELINE_HOST)"
	@echo "   Users: 2000, Duration: 3 minutes"
	@echo "   ⚠️  This will generate high load on the MCP server"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c 'source $(VENV_DIR)/bin/activate && \
		cd tests/loadtest && \
		locust -f locustfile_baseline.py \
			--host=$(BASELINE_HOST) \
			--users=2000 \
			--spawn-rate=200 \
			--run-time=180s \
			--headless \
			--csv=baseline_stress \
			--html=baseline_stress_report.html'

# --- AgentGateway MCP Server Time Load Test ---
# help: load-test-agentgateway-mcp-server-time - Load test external MCP server at localhost:3000

AGENTGATEWAY_MCP_HOST ?= http://localhost:3000

load-test-agentgateway-mcp-server-time:    ## Load test external MCP server (localhost-get-system-time)
	@echo "⏰ Running AgentGateway MCP Server Time load test..."
	@echo "   🌐 Open http://localhost:8089 in your browser"
	@echo "   🎯 Host: $(AGENTGATEWAY_MCP_HOST)"
	@echo "   👥 Defaults: 50 users, 10 spawn/s, 60s"
	@echo "   🔧 Tool: localhost-get-system-time"
	@echo "   🎛️  Class picker enabled - select which tests to run"
	@echo ""
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c 'source $(VENV_DIR)/bin/activate && \
		cd tests/loadtest && \
		locust -f locustfile_agentgateway_mcp_server_time.py \
			--host=$(AGENTGATEWAY_MCP_HOST) \
			--users=50 \
			--spawn-rate=10 \
			--run-time=60s \
			--class-picker'

# --- MCP Streamable HTTP Protocol Load Test ---
# help: load-test-mcp-protocol       - MCP-only protocol test (150 users, 2min) — measures pure MCP RPS
# help: load-test-mcp-protocol-ui    - MCP-only protocol test with Locust Web UI (class picker)
# help: load-test-mcp-protocol-heavy - MCP-only protocol heavy test (500 users, 5min)

MCP_PROTOCOL_LOCUSTFILE ?= tests/loadtest/locustfile_mcp_protocol.py
MCP_RATE_LIMITER_LOCUSTFILE ?= tests/loadtest/locustfile_rate_limiter_backend_correctness.py
MCP_RATE_LIMITER_SCALE_LOCUSTFILE ?= tests/loadtest/locustfile_rate_limiter_scale.py
MCP_RATE_LIMITER_REDIS_CAPACITY_LOCUSTFILE ?= tests/loadtest/locustfile_rate_limiter_redis_capacity.py
RL_ALGORITHM ?= fixed_window
RL_USERS ?= 100
RL_SPAWN_RATE ?= 10
RL_REQS_PER_SECOND ?= 0.25
RL_PROMPT_ID ?=
RATE_LIMITER_FORCE_PYTHON ?=
MCP_PROTOCOL_HOST ?= http://localhost:4444
MCP_BENCHMARK_HOST ?= http://localhost:8080
MCP_BENCHMARK_SERVER_ID ?= 9779b6698cbd4b4995ee04a4fab38737
MCP_BENCHMARK_USERS ?= 125
MCP_BENCHMARK_SPAWN_RATE ?= 30
MCP_BENCHMARK_RUN_TIME ?= 60s
MCP_BENCHMARK_HIGH_USERS ?= 300
MCP_BENCHMARK_HIGH_SPAWN_RATE ?= 50
MCP_BENCHMARK_HIGH_RUN_TIME ?= 60s
MCP_BENCHMARK_WORKERS ?= 4
MCP_BENCHMARK_MIXED_MASTER_PORT ?= 5567
MCP_BENCHMARK_TOOLS_MASTER_PORT ?= 5569
MCP_BENCHMARK_LOCUST_LOG_LEVEL ?= ERROR
MCP_BENCHMARK_WORKER_LOG_DIR ?= reports/mcp_benchmark_workers
RL_LIMIT_PER_MIN ?= 30

load-test-mcp-protocol:                    ## MCP Streamable HTTP protocol test (150 users, 2min)
	@echo "🔬 Running MCP STREAMABLE HTTP protocol load test..."
	@echo "   Host: $(MCP_PROTOCOL_HOST)"
	@echo "   Users: 150, Spawn: 30/s, Duration: 2 minutes"
	@echo "   📝 Tests ONLY MCP protocol path: /servers/{id}/mcp"
	@echo "   💡 Requires: gateway + at least one MCP server connected"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p reports
	@/bin/bash -c 'source $(VENV_DIR)/bin/activate && \
		locust -f $(MCP_PROTOCOL_LOCUSTFILE) \
			--host=$(MCP_PROTOCOL_HOST) \
			--users=150 \
			--spawn-rate=30 \
			--run-time=120s \
			--headless \
			--html=reports/loadtest_mcp_protocol.html \
			--csv=reports/loadtest_mcp_protocol \
			--processes=-1'

load-test-mcp-protocol-ui:                 ## MCP Streamable HTTP protocol test with Web UI
	@echo "🔬 Starting MCP STREAMABLE HTTP protocol load test Web UI..."
	@echo "   🌐 Open http://localhost:8089 in your browser"
	@echo "   🎯 Host: $(MCP_PROTOCOL_HOST)"
	@echo "   👥 Defaults: 150 users, 30 spawn/s, 2 min"
	@echo "   🎛️  Class picker enabled - select which MCP user types to run"
	@echo "   📝 Tests ONLY MCP protocol path: /servers/{id}/mcp"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c 'source $(VENV_DIR)/bin/activate && \
		locust -f $(MCP_PROTOCOL_LOCUSTFILE) \
			--host=$(MCP_PROTOCOL_HOST) \
			--users=150 \
			--spawn-rate=30 \
			--run-time=120s \
			--class-picker'

# help: benchmark-mcp-mixed      - Quick mixed MCP benchmark against the testing stack
# help: benchmark-mcp-tools      - Quick tools-only MCP benchmark against the testing stack
# help: benchmark-mcp-mixed-300  - Distributed 300-user mixed MCP benchmark
# help: benchmark-mcp-tools-300  - Distributed 300-user tools-only MCP benchmark

.PHONY: benchmark-mcp-mixed
benchmark-mcp-mixed:                        ## Quick mixed MCP benchmark against the testing stack
	@echo "📊 Running mixed MCP benchmark..."
	@echo "   Host: $(MCP_BENCHMARK_HOST)"
	@echo "   Server: $(MCP_BENCHMARK_SERVER_ID)"
	@echo "   Users: $(MCP_BENCHMARK_USERS), Spawn: $(MCP_BENCHMARK_SPAWN_RATE)/s, Duration: $(MCP_BENCHMARK_RUN_TIME)"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -eu -o pipefail -c 'source $(VENV_DIR)/bin/activate && \
		LOCUST_LOG_LEVEL=$(MCP_BENCHMARK_LOCUST_LOG_LEVEL) MCP_SERVER_ID=$(MCP_BENCHMARK_SERVER_ID) \
		locust -f $(MCP_PROTOCOL_LOCUSTFILE) \
			--host=$(MCP_BENCHMARK_HOST) \
			--users=$(MCP_BENCHMARK_USERS) \
			--spawn-rate=$(MCP_BENCHMARK_SPAWN_RATE) \
			--run-time=$(MCP_BENCHMARK_RUN_TIME) \
			--headless \
			--only-summary'

.PHONY: benchmark-mcp-tools
benchmark-mcp-tools:                        ## Quick tools-only MCP benchmark against the testing stack
	@echo "📊 Running tools-only MCP benchmark..."
	@echo "   Host: $(MCP_BENCHMARK_HOST)"
	@echo "   Server: $(MCP_BENCHMARK_SERVER_ID)"
	@echo "   Users: $(MCP_BENCHMARK_USERS), Spawn: $(MCP_BENCHMARK_SPAWN_RATE)/s, Duration: $(MCP_BENCHMARK_RUN_TIME)"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -eu -o pipefail -c 'source $(VENV_DIR)/bin/activate && \
		LOCUST_LOG_LEVEL=$(MCP_BENCHMARK_LOCUST_LOG_LEVEL) MCP_SERVER_ID=$(MCP_BENCHMARK_SERVER_ID) \
		locust -f $(MCP_PROTOCOL_LOCUSTFILE) \
			--host=$(MCP_BENCHMARK_HOST) \
			--users=$(MCP_BENCHMARK_USERS) \
			--spawn-rate=$(MCP_BENCHMARK_SPAWN_RATE) \
			--run-time=$(MCP_BENCHMARK_RUN_TIME) \
			--headless \
			--only-summary \
			MCPToolCallerUser'

# help: benchmark-rate-limiter   - Rate limiter correctness test: unique users, controlled pacing
.PHONY: benchmark-rate-limiter
benchmark-rate-limiter:                     ## Rate limiter correctness test (1 user, 1 req/s, 2 min — shows memory vs Redis difference)
	@echo "🚦 Running rate limiter correctness test..."
	@echo "   Host:     $(MCP_BENCHMARK_HOST)"
	@echo "   Server:   $(MCP_BENCHMARK_SERVER_ID)"
	@echo "   User:     1  (admin@example.com, 1 req/s = 60 req/min = 2x the $(RL_LIMIT_PER_MIN)/m limit)"
	@echo "   Duration: 120s"
	@echo ""
	@echo "   Memory backend: ~0%  failures  (each instance sees ~20 req/min < limit)"
	@echo "   Redis backend:  ~50% failures  (shared counter: 60 req/min > $(RL_LIMIT_PER_MIN)/m limit)"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -eu -o pipefail -c 'source $(VENV_DIR)/bin/activate && \
		LOCUST_LOG_LEVEL=ERROR \
		RL_LIMIT_PER_MIN=$(RL_LIMIT_PER_MIN) \
		MCP_SERVER_ID=$(MCP_BENCHMARK_SERVER_ID) \
		locust -f $(MCP_RATE_LIMITER_LOCUSTFILE) \
			--host=$(MCP_BENCHMARK_HOST) \
			--users=1 \
			--spawn-rate=1 \
			--run-time=120s \
			--headless \
			--only-summary \
			RateLimitedUser || true'


# help: benchmark-rate-limiter-scale  - Multi-user scale test showing Redis memory divergence across algorithms
.PHONY: benchmark-rate-limiter-scale
RL_RUN_TIME ?= 300s
benchmark-rate-limiter-scale:               ## Scale test: RL_USERS unique users (default 100), Redis memory timeline per algorithm
	@echo "📈 Running rate limiter scale test (resource divergence)..."
	@echo "   Algorithm: $(RL_ALGORITHM)  (must match plugins/config.yaml)"
	@echo "   Users:     $(RL_USERS) unique identities  (each creates own Redis key)"
	@echo "   Spawn:     $(RL_SPAWN_RATE) users/s"
	@echo "   Limit:     $(RL_LIMIT_PER_MIN) req/min per user"
	@echo "   Duration:  $(RL_RUN_TIME)  (includes ~40s bootstrap for user registration)"
	@echo ""
	@echo "   Redis memory diverges between algorithms as users ramp up:"
	@echo "     fixed_window:   ~0.1-0.3 KiB/key  (single integer)"
	@echo "     sliding_window: ~1-3 KiB/key       (sorted set, $(RL_LIMIT_PER_MIN) entries)"
	@echo "     token_bucket:   ~0.2 KiB/key       (hash: tokens + last_refill)"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -eu -o pipefail -c 'source $(VENV_DIR)/bin/activate && \
		LOCUST_LOG_LEVEL=ERROR \
		RL_ALGORITHM=$(RL_ALGORITHM) \
		RL_LIMIT_PER_MIN=$(RL_LIMIT_PER_MIN) \
		RL_USERS=$(RL_USERS) \
		RL_SPAWN_RATE=$(RL_SPAWN_RATE) \
		RL_RUN_TIME=$(RL_RUN_TIME) \
		MCP_SERVER_ID=$(MCP_BENCHMARK_SERVER_ID) \
		locust -f $(MCP_RATE_LIMITER_SCALE_LOCUSTFILE) \
			--host=$(MCP_BENCHMARK_HOST) \
			--users=$(RL_USERS) \
			--spawn-rate=$(RL_SPAWN_RATE) \
			--run-time=$(RL_RUN_TIME) \
			--headless \
			--only-summary \
			ScaleComparisonUser || true'


# help: benchmark-rate-limiter-redis-capacity  - Multi-instance prompt-path concurrency benchmark for Redis rate limiting
.PHONY: benchmark-rate-limiter-redis-capacity
benchmark-rate-limiter-redis-capacity:      ## Capacity test: 3 gateways + Redis on prompt_pre_fetch path
	@echo "🚀 Running rate limiter Redis capacity test..."
	@echo "   Host:        $(MCP_BENCHMARK_HOST)"
	@echo "   Topology:    nginx -> 3 gateways -> shared Redis"
	@echo "   Path:        REST /prompts/{id} (prompt_pre_fetch)"
	@echo "   Users:       $(RL_USERS)"
	@echo "   Spawn rate:  $(RL_SPAWN_RATE)/s"
	@echo "   Pace:        $(RL_REQS_PER_SECOND) req/s per user"
	@echo "   Duration:    $(RL_RUN_TIME)"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -eu -o pipefail -c 'source $(VENV_DIR)/bin/activate && \
		LOCUST_LOG_LEVEL=ERROR \
		RATE_LIMITER_FORCE_PYTHON=$(RATE_LIMITER_FORCE_PYTHON) \
		RL_USERS=$(RL_USERS) \
		RL_SPAWN_RATE=$(RL_SPAWN_RATE) \
		RL_RUN_TIME=$(RL_RUN_TIME) \
		RL_REQS_PER_SECOND=$(RL_REQS_PER_SECOND) \
		RL_LIMIT_PER_MIN=$(RL_LIMIT_PER_MIN) \
		RL_PROMPT_ID=$(RL_PROMPT_ID) \
		locust -f $(MCP_RATE_LIMITER_REDIS_CAPACITY_LOCUSTFILE) \
			--host=$(MCP_BENCHMARK_HOST) \
			--users=$(RL_USERS) \
			--spawn-rate=$(RL_SPAWN_RATE) \
			--run-time=$(RL_RUN_TIME) \
			--headless \
			--only-summary \
			CapacityPromptUser || true'

# help: benchmark-rate-limiter-capacity-rust  - Capacity test with Rust engine enabled (default)
.PHONY: benchmark-rate-limiter-capacity-rust
benchmark-rate-limiter-capacity-rust:       ## Capacity test with Rust engine
	RATE_LIMITER_FORCE_PYTHON=0 $(MAKE) benchmark-rate-limiter-redis-capacity

# help: benchmark-rate-limiter-capacity-python  - Capacity test with Python fallback (forced)
.PHONY: benchmark-rate-limiter-capacity-python
benchmark-rate-limiter-capacity-python:     ## Capacity test with Python fallback
	RATE_LIMITER_FORCE_PYTHON=1 $(MAKE) benchmark-rate-limiter-redis-capacity

.PHONY: benchmark-mcp-mixed-300
benchmark-mcp-mixed-300:                    ## Distributed 300-user mixed MCP benchmark
	@echo "📊 Running distributed mixed MCP benchmark..."
	@echo "   Host: $(MCP_BENCHMARK_HOST)"
	@echo "   Server: $(MCP_BENCHMARK_SERVER_ID)"
	@echo "   Users: $(MCP_BENCHMARK_HIGH_USERS), Spawn: $(MCP_BENCHMARK_HIGH_SPAWN_RATE)/s, Duration: $(MCP_BENCHMARK_HIGH_RUN_TIME), Workers: $(MCP_BENCHMARK_WORKERS)"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(MCP_BENCHMARK_WORKER_LOG_DIR)
	@/bin/bash -eu -o pipefail -c 'source $(VENV_DIR)/bin/activate; \
		pids=""; \
		cleanup() { \
			for pid in $$pids; do kill $$pid 2>/dev/null || true; done; \
			wait $$pids 2>/dev/null || true; \
		}; \
		trap cleanup EXIT INT TERM; \
		for i in $$(seq 1 $(MCP_BENCHMARK_WORKERS)); do \
			LOCUST_LOG_LEVEL=$(MCP_BENCHMARK_LOCUST_LOG_LEVEL) MCP_SERVER_ID=$(MCP_BENCHMARK_SERVER_ID) \
			locust -f $(MCP_PROTOCOL_LOCUSTFILE) \
				--worker \
				--master-host=127.0.0.1 \
				--master-port=$(MCP_BENCHMARK_MIXED_MASTER_PORT) \
				> $(MCP_BENCHMARK_WORKER_LOG_DIR)/mixed_worker_$$i.log 2>&1 & \
			pids="$$pids $$!"; \
		done; \
		LOCUST_LOG_LEVEL=$(MCP_BENCHMARK_LOCUST_LOG_LEVEL) MCP_SERVER_ID=$(MCP_BENCHMARK_SERVER_ID) \
		locust -f $(MCP_PROTOCOL_LOCUSTFILE) \
			--host=$(MCP_BENCHMARK_HOST) \
			--master \
			--headless \
			--expect-workers=$(MCP_BENCHMARK_WORKERS) \
			--master-bind-port=$(MCP_BENCHMARK_MIXED_MASTER_PORT) \
			--users=$(MCP_BENCHMARK_HIGH_USERS) \
			--spawn-rate=$(MCP_BENCHMARK_HIGH_SPAWN_RATE) \
			--run-time=$(MCP_BENCHMARK_HIGH_RUN_TIME) \
			--only-summary'

.PHONY: benchmark-mcp-tools-300
benchmark-mcp-tools-300:                    ## Distributed 300-user tools-only MCP benchmark
	@echo "📊 Running distributed tools-only MCP benchmark..."
	@echo "   Host: $(MCP_BENCHMARK_HOST)"
	@echo "   Server: $(MCP_BENCHMARK_SERVER_ID)"
	@echo "   Users: $(MCP_BENCHMARK_HIGH_USERS), Spawn: $(MCP_BENCHMARK_HIGH_SPAWN_RATE)/s, Duration: $(MCP_BENCHMARK_HIGH_RUN_TIME), Workers: $(MCP_BENCHMARK_WORKERS)"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p $(MCP_BENCHMARK_WORKER_LOG_DIR)
	@/bin/bash -eu -o pipefail -c 'source $(VENV_DIR)/bin/activate; \
		pids=""; \
		cleanup() { \
			for pid in $$pids; do kill $$pid 2>/dev/null || true; done; \
			wait $$pids 2>/dev/null || true; \
		}; \
		trap cleanup EXIT INT TERM; \
		for i in $$(seq 1 $(MCP_BENCHMARK_WORKERS)); do \
			LOCUST_LOG_LEVEL=$(MCP_BENCHMARK_LOCUST_LOG_LEVEL) MCP_SERVER_ID=$(MCP_BENCHMARK_SERVER_ID) \
			locust -f $(MCP_PROTOCOL_LOCUSTFILE) \
				--worker \
				--master-host=127.0.0.1 \
				--master-port=$(MCP_BENCHMARK_TOOLS_MASTER_PORT) \
				> $(MCP_BENCHMARK_WORKER_LOG_DIR)/tools_worker_$$i.log 2>&1 & \
			pids="$$pids $$!"; \
		done; \
		LOCUST_LOG_LEVEL=$(MCP_BENCHMARK_LOCUST_LOG_LEVEL) MCP_SERVER_ID=$(MCP_BENCHMARK_SERVER_ID) \
		locust -f $(MCP_PROTOCOL_LOCUSTFILE) \
			--host=$(MCP_BENCHMARK_HOST) \
			--master \
			--headless \
			--expect-workers=$(MCP_BENCHMARK_WORKERS) \
			--master-bind-port=$(MCP_BENCHMARK_TOOLS_MASTER_PORT) \
			--users=$(MCP_BENCHMARK_HIGH_USERS) \
			--spawn-rate=$(MCP_BENCHMARK_HIGH_SPAWN_RATE) \
			--run-time=$(MCP_BENCHMARK_HIGH_RUN_TIME) \
			--only-summary \
			MCPToolCallerUser'

load-test-mcp-protocol-heavy:              ## MCP Streamable HTTP protocol heavy test (500 users, 5min)
	@echo "🔬 Running MCP STREAMABLE HTTP protocol HEAVY load test..."
	@echo "   Host: $(MCP_PROTOCOL_HOST)"
	@echo "   Users: 500, Spawn: 50/s, Duration: 5 minutes"
	@echo "   ⚠️  This will generate sustained MCP protocol load"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@mkdir -p reports
	@/bin/bash -c 'source $(VENV_DIR)/bin/activate && \
		locust -f $(MCP_PROTOCOL_LOCUSTFILE) \
			--host=$(MCP_PROTOCOL_HOST) \
			--users=500 \
			--spawn-rate=50 \
			--run-time=300s \
			--headless \
			--html=reports/loadtest_mcp_protocol_heavy.html \
			--csv=reports/loadtest_mcp_protocol_heavy \
			--processes=-1'

# =============================================================================
# 🔴 OCP DEPLOYMENT & BENCHMARK
# =============================================================================
# Make targets wrap Ansible playbooks in ansible/ocp/playbooks/.
# All logic lives in the playbooks — Make provides a simpler interface.
# Requires: pip install ansible && ansible-galaxy collection install kubernetes.core

# OCP_NS is used as both the namespace and the Helm release name (kept identical for simplicity)
OCP_NS ?=
BENCH_USERS ?= 125
BENCH_SPAWN ?= 30
BENCH_RUNTIME ?= 60s
OCP_INVENTORY ?= ansible/ocp/inventory/cluster.yml

define check_ansible
@command -v ansible-playbook >/dev/null 2>&1 || \
	(echo "ERROR: ansible-playbook not found." && \
	 echo "Install with: pip install ansible && ansible-galaxy collection install kubernetes.core" && \
	 exit 1)
endef

ocp-install-operator:                        ## Install CrunchyData PGO operator (one-time, cluster-wide, requires OCP_CLUSTER)
	$(check_ansible)
	@if [ -z "$(OCP_CLUSTER)" ]; then echo "Usage: make ocp-install-operator OCP_CLUSTER=<api-url>"; echo "Example: make ocp-install-operator OCP_CLUSTER=https://api.my-cluster.example.com:6443"; exit 1; fi
	@CURRENT=$$(oc whoami --show-server 2>/dev/null) || (echo "ERROR: Not logged in. Run: oc login $(OCP_CLUSTER)" && exit 1); \
		if [ "$$CURRENT" != "$(OCP_CLUSTER)" ]; then \
			echo "ERROR: Currently logged into $$CURRENT but OCP_CLUSTER=$(OCP_CLUSTER)"; \
			echo "Run: oc login $(OCP_CLUSTER)"; exit 1; \
		fi
	@/bin/bash -c 'read -p "Install CrunchyData PGO operator on $(OCP_CLUSTER)? [y/N]: " ans; [ "$$ans" = "y" ] || [ "$$ans" = "Y" ] || (echo "Aborted." && exit 1)'
	ansible-playbook ansible/ocp/playbooks/install-operator.yml \
		-i $(OCP_INVENTORY) \
		-e skip_confirm=true

ocp-setup:                                   ## Set up OCP namespace and CrunchyData Postgres (requires OCP_NS)
	$(check_ansible)
	@if [ -z "$(OCP_NS)" ]; then echo "Usage: make ocp-setup OCP_NS=<namespace>"; exit 1; fi
	@/bin/bash -c 'read -p "Run ocp-setup for namespace $(OCP_NS)? [y/N]: " ans; [ "$$ans" = "y" ] || [ "$$ans" = "Y" ] || (echo "Aborted." && exit 1)'
	ansible-playbook ansible/ocp/playbooks/setup.yml \
		-i $(OCP_INVENTORY) \
		-e ocp_namespace=$(OCP_NS) \
		-e skip_confirm=true

ocp-deploy:                                  ## Deploy ContextForge on OCP (requires OCP_NS)
	$(check_ansible)
	@if [ -z "$(OCP_NS)" ]; then echo "Usage: make ocp-deploy OCP_NS=<namespace>"; exit 1; fi
	@/bin/bash -c 'read -p "Run ocp-deploy for namespace $(OCP_NS)? [y/N]: " ans; [ "$$ans" = "y" ] || [ "$$ans" = "Y" ] || (echo "Aborted." && exit 1)'
	ansible-playbook ansible/ocp/playbooks/deploy.yml \
		-i $(OCP_INVENTORY) \
		-e ocp_namespace=$(OCP_NS) \
		-e skip_confirm=true

ocp-benchmark-setup:                         ## Enable Locust and configure server ID for benchmark (requires OCP_NS)
	$(check_ansible)
	@if [ -z "$(OCP_NS)" ]; then echo "Usage: make ocp-benchmark-setup OCP_NS=<namespace>"; exit 1; fi
	@/bin/bash -c 'read -p "Run ocp-benchmark-setup for namespace $(OCP_NS)? [y/N]: " ans; [ "$$ans" = "y" ] || [ "$$ans" = "Y" ] || (echo "Aborted." && exit 1)'
	ansible-playbook ansible/ocp/playbooks/benchmark-setup.yml \
		-i $(OCP_INVENTORY) \
		-e ocp_namespace=$(OCP_NS) \
		-e skip_confirm=true

ocp-benchmark:                               ## Run MCP benchmark on OCP (requires OCP_NS; optional BENCH_USERS, BENCH_SPAWN, BENCH_RUNTIME)
	$(check_ansible)
	@if [ -z "$(OCP_NS)" ]; then echo "Usage: make ocp-benchmark OCP_NS=<namespace> [BENCH_USERS=500 BENCH_SPAWN=50 BENCH_RUNTIME=60s]"; exit 1; fi
	ansible-playbook ansible/ocp/playbooks/benchmark.yml \
		-i $(OCP_INVENTORY) \
		-e ocp_namespace=$(OCP_NS) \
		-e bench_users=$(BENCH_USERS) \
		-e bench_spawn=$(BENCH_SPAWN) \
		-e bench_runtime=$(BENCH_RUNTIME) \
		-e skip_confirm=true

ocp-uninstall:                               ## Uninstall the ContextForge Helm release on OCP (requires OCP_NS)
	$(check_ansible)
	@if [ -z "$(OCP_NS)" ]; then echo "Usage: make ocp-uninstall OCP_NS=<namespace>"; exit 1; fi
	@/bin/bash -c 'read -p "Run ocp-uninstall for namespace $(OCP_NS)? [y/N]: " ans; [ "$$ans" = "y" ] || [ "$$ans" = "Y" ] || (echo "Aborted." && exit 1)'
	ansible-playbook ansible/ocp/playbooks/uninstall.yml \
		-i $(OCP_INVENTORY) \
		-e ocp_namespace=$(OCP_NS) \
		-e skip_confirm=true

# =============================================================================
# 📊 JMETER PERFORMANCE TESTING
# =============================================================================
# help: 📊 JMETER PERFORMANCE TESTING
# help: jmeter-install                - Download and install JMeter 5.6.3 locally
# help: jmeter-ui                     - Launch JMeter GUI for interactive test editing
# help: jmeter-rest-baseline          - Run REST API baseline test (1,000 RPS, 10min)
# help: jmeter-mcp-baseline           - Run MCP JSON-RPC baseline test (1,000 RPS, 15min)
# help: jmeter-mcp-servers-baseline   - Run MCP test servers baseline (fast_time, fast_test)
# help: jmeter-load                   - Run load test (4,000 RPS, 30min)
# help: jmeter-stress                 - Run stress test (ramp to 10,000 RPS)
# help: jmeter-spike                  - Run spike test (1K→10K→1K recovery)
# help: jmeter-soak                   - Run 24-hour soak test (2,000 RPS)
# help: jmeter-sse                    - Run SSE streaming baseline (1,000 connections)
# help: jmeter-websocket              - Run WebSocket baseline (500 connections)
# help: jmeter-admin-ui               - Run Admin UI baseline (50 users)
# help: jmeter-report                 - Generate HTML report from last JTL file
# help: jmeter-compare                - Compare current vs baseline results

JMETER_VERSION := 5.6.3
JMETER_HOME := $(CURDIR)/.jmeter/apache-jmeter-$(JMETER_VERSION)
JMETER_BIN := $(if $(wildcard $(JMETER_HOME)/bin/jmeter),$(JMETER_HOME)/bin/jmeter,$(shell which jmeter 2>/dev/null))
JMETER_DIR := tests/jmeter
JMETER_FRAGMENT_DIR := $(CURDIR)/$(JMETER_DIR)/fragments
JMETER_RESULTS_DIR := $(JMETER_DIR)/results
JMETER_RENDERED_DIR := $(CURDIR)/.jmeter/rendered
JMETER_RENDER := python3 $(JMETER_DIR)/render_fragments.py --out $(JMETER_RENDERED_DIR)
JMETER_GATEWAY_URL ?= http://localhost:8080
export JMETER_OPTS ?= -Djava.util.prefs.userRoot=/tmp/jmeter-prefs -Djava.util.prefs.systemRoot=/tmp/jmeter-prefs
JMETER_JWT_SECRET ?= $(or $(JWT_SECRET_KEY),my-test-key-but-now-longer-than-32-bytes)
JMETER_TOKEN ?= $(shell python3 -m mcpgateway.utils.create_jwt_token --data '{"sub":"admin@example.com","is_admin":true,"teams":null}' --exp 10080 --secret $(JMETER_JWT_SECRET) 2>/dev/null || echo "")
JMETER_SERVER_ID ?=
JMETER_FAST_TIME_URL ?= http://localhost:8888
JMETER_FAST_TEST_URL ?= http://localhost:8880
JMETER_SUMMARISER ?= -Jsummariser.interval=10

.PHONY: jmeter-install jmeter-ui jmeter-check jmeter-quick jmeter-clean
.PHONY: jmeter-rest-baseline jmeter-mcp-baseline jmeter-mcp-servers-baseline
.PHONY: jmeter-load jmeter-stress jmeter-spike jmeter-soak
.PHONY: jmeter-sse jmeter-websocket jmeter-admin-ui
.PHONY: jmeter-report jmeter-compare

jmeter-install:                            ## Download and install JMeter 5.6.3 locally
	@echo "📦 Installing JMeter $(JMETER_VERSION)..."
	@mkdir -p .jmeter
	@if [ -d "$(JMETER_HOME)" ]; then \
		echo "✅ JMeter $(JMETER_VERSION) already installed at $(JMETER_HOME)"; \
	else \
		echo "   Downloading apache-jmeter-$(JMETER_VERSION).tgz..."; \
		curl -fsSL "https://dlcdn.apache.org/jmeter/binaries/apache-jmeter-$(JMETER_VERSION).tgz" -o .jmeter/jmeter.tgz; \
		echo "   Extracting..."; \
		tar -xzf .jmeter/jmeter.tgz -C .jmeter/; \
		rm .jmeter/jmeter.tgz; \
		echo "✅ JMeter $(JMETER_VERSION) installed to $(JMETER_HOME)"; \
	fi
	@echo ""
	@echo "To use: export PATH=\$$PATH:$(JMETER_HOME)/bin"
	@echo "Or run: make jmeter-ui"

jmeter-ui: jmeter-check                    ## Launch JMeter GUI for interactive test editing
	@echo "🖥️  Launching JMeter GUI..."
	@echo "   Test plans: $(JMETER_DIR)/*.jmx"
	@$(JMETER_BIN) -t $(JMETER_DIR)/rest_api_baseline.jmx &
	@echo "✅ JMeter GUI started"

jmeter-check:                              ## Check if JMeter 5.x is installed (required for HTML reports)
	@if [ -x "$(JMETER_HOME)/bin/jmeter" ]; then \
		JMETER_CMD="$(JMETER_HOME)/bin/jmeter"; \
	elif which jmeter >/dev/null 2>&1; then \
		JMETER_CMD="jmeter"; \
	else \
		echo "❌ JMeter not found. Install with:"; \
		echo "   make jmeter-install     (recommended - installs $(JMETER_VERSION) locally)"; \
		echo "   brew install jmeter     (macOS)"; \
		exit 1; \
	fi; \
	VERSION=$$($$JMETER_CMD --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1); \
	MAJOR=$$(echo "$$VERSION" | cut -d. -f1); \
	if [ -z "$$MAJOR" ] || [ "$$MAJOR" -lt 5 ]; then \
		echo "❌ JMeter 5.x+ required for HTML report generation (-e -o flags)"; \
		echo "   Found: $$VERSION"; \
		echo "   Run: make jmeter-install"; \
		exit 1; \
	fi; \
	echo "✅ JMeter $$VERSION found"

jmeter-quick: jmeter-check                 ## Quick 10-second test to verify setup and generate report
	@echo "⚡ Running quick JMeter test (10 seconds)..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@$(JMETER_RENDER)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_RENDERED_DIR)/rest_api_baseline.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL=$(JMETER_GATEWAY_URL) \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JTHREADS=5 -JRAMP_UP=2 -JDURATION=10 \
		-l $(JMETER_RESULTS_DIR)/quick_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/quick_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/quick_*/index.html"

jmeter-rest-baseline: jmeter-check         ## Run REST API baseline test (1,000 RPS, 10min)
	@echo "📊 Running REST API baseline test..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@echo "   Target: 1,000 RPS for 10 minutes"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@$(JMETER_RENDER)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_RENDERED_DIR)/rest_api_baseline.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL=$(JMETER_GATEWAY_URL) \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JTHREADS=100 -JRAMP_UP=60 -JDURATION=600 \
		-l $(JMETER_RESULTS_DIR)/rest_baseline_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/rest_baseline_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/rest_baseline_*/index.html"

jmeter-mcp-baseline: jmeter-check          ## Run MCP JSON-RPC baseline test (1,000 RPS, 15min)
	@echo "📊 Running MCP JSON-RPC baseline test..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@echo "   Server ID: $(JMETER_SERVER_ID)"
	@echo "   Target: 1,000 RPS for 15 minutes"
	@if [ -z "$(JMETER_SERVER_ID)" ]; then \
		echo "❌ JMETER_SERVER_ID required. Set with: make jmeter-mcp-baseline JMETER_SERVER_ID=<id>"; \
		exit 1; \
	fi
	@mkdir -p $(JMETER_RESULTS_DIR)
	@$(JMETER_RENDER)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_RENDERED_DIR)/mcp_jsonrpc_baseline.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL=$(JMETER_GATEWAY_URL) \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JSERVER_ID=$(JMETER_SERVER_ID) \
		-JTHREADS=200 -JRAMP_UP=60 -JDURATION=900 \
		-l $(JMETER_RESULTS_DIR)/mcp_baseline_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/mcp_baseline_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/mcp_baseline_*/index.html"

jmeter-mcp-servers-baseline: jmeter-check  ## Run MCP test servers baseline (fast_time, fast_test)
	@echo "📊 Running MCP test servers baseline..."
	@echo "   Fast Time Server: $(JMETER_FAST_TIME_URL)"
	@echo "   Fast Test Server: $(JMETER_FAST_TEST_URL)"
	@echo "   Target: 2,000 RPS per server for 10 minutes"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_DIR)/mcp_test_servers_baseline.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JFAST_TIME_URL=$(JMETER_FAST_TIME_URL) \
		-JFAST_TEST_URL=$(JMETER_FAST_TEST_URL) \
		-JTHREADS=200 -JDURATION=600 \
		-l $(JMETER_RESULTS_DIR)/mcp_servers_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/mcp_servers_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/mcp_servers_*/index.html"

jmeter-load: jmeter-check                  ## Run load test (1,000 users, 30min)
	@echo "🔥 Running load test..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@echo "   Target: 1,000 concurrent users for 30 minutes"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@$(JMETER_RENDER)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_RENDERED_DIR)/load_test.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL=$(JMETER_GATEWAY_URL) \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JSERVER_ID=$(JMETER_SERVER_ID) \
		-JTHREADS=1000 -JRAMP_UP=60 -JDURATION=1800 \
		-l $(JMETER_RESULTS_DIR)/load_test_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/load_test_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/load_test_*/index.html"

jmeter-stress: jmeter-check                ## Run stress test (ramp to 10,000 RPS)
	@echo "💥 Running stress test..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@echo "   Target: Ramp from 1K to 10K RPS over 30 minutes"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@$(JMETER_RENDER)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_RENDERED_DIR)/stress_test.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL=$(JMETER_GATEWAY_URL) \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JMAX_THREADS=2000 \
		-l $(JMETER_RESULTS_DIR)/stress_test_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/stress_test_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/stress_test_*/index.html"

jmeter-spike: jmeter-check                 ## Run spike test (1K→10K→1K recovery)
	@echo "⚡ Running spike test..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@echo "   Pattern: 1K RPS → 10K RPS spike → recovery to 1K RPS"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@$(JMETER_RENDER)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_RENDERED_DIR)/spike_test.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL=$(JMETER_GATEWAY_URL) \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JBASE_THREADS=200 -JPEAK_THREADS=2000 \
		-l $(JMETER_RESULTS_DIR)/spike_test_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/spike_test_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/spike_test_*/index.html"

jmeter-soak: jmeter-check                  ## Run 24-hour soak test (2,000 RPS)
	@echo "🔄 Running 24-hour soak test..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@echo "   Target: 2,000 RPS sustained for 24 hours"
	@echo "   ⚠️  This test runs for 24 hours - use screen/tmux!"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@$(JMETER_RENDER)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_RENDERED_DIR)/soak_test.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL=$(JMETER_GATEWAY_URL) \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JSERVER_ID=$(JMETER_SERVER_ID) \
		-JTHREADS=400 -JDURATION=86400 \
		-l $(JMETER_RESULTS_DIR)/soak_test_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/soak_test_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/soak_test_*/index.html"

jmeter-sse: jmeter-check                   ## Run SSE streaming baseline (1,000 connections)
	@echo "📡 Running SSE streaming baseline..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@echo "   Target: 1,000 concurrent SSE connections for 10 minutes"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_DIR)/sse_streaming_baseline.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL=$(JMETER_GATEWAY_URL) \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JSERVER_ID=$(JMETER_SERVER_ID) \
		-JCONNECTIONS=1000 -JDURATION=600 \
		-l $(JMETER_RESULTS_DIR)/sse_baseline_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/sse_baseline_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/sse_baseline_*/index.html"

jmeter-websocket: jmeter-check             ## Run WebSocket baseline (500 connections)
	@echo "🔌 Running WebSocket baseline..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@echo "   Target: 500 concurrent WebSocket connections"
	@echo "   Note: Requires JMeter WebSocket plugin for full support"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_DIR)/websocket_baseline.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL="ws://$$(echo $(JMETER_GATEWAY_URL) | sed 's|http://||' | sed 's|https://||')" \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JSERVER_ID=$(JMETER_SERVER_ID) \
		-JCONNECTIONS=500 -JDURATION=600 \
		-l $(JMETER_RESULTS_DIR)/websocket_baseline_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/websocket_baseline_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/websocket_baseline_*/index.html"

jmeter-admin-ui: jmeter-check              ## Run Admin UI baseline (50 users)
	@echo "🖥️  Running Admin UI baseline..."
	@echo "   Gateway: $(JMETER_GATEWAY_URL)"
	@echo "   Target: 50 concurrent admin users with think time"
	@mkdir -p $(JMETER_RESULTS_DIR)
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	$(JMETER_BIN) -n $(JMETER_SUMMARISER) -t $(JMETER_DIR)/admin_ui_baseline.jmx \
		-JJMETER_FRAGMENT_DIR=$(JMETER_FRAGMENT_DIR) \
		-JGATEWAY_URL=$(JMETER_GATEWAY_URL) \
		-JTOKEN="$(JMETER_TOKEN)" \
		-JUSERS=50 -JDURATION=300 \
		-JTHINK_TIME_MIN=3000 -JTHINK_TIME_MAX=5000 \
		-l $(JMETER_RESULTS_DIR)/admin_ui_baseline_$$TIMESTAMP.jtl \
		-e -o $(JMETER_RESULTS_DIR)/admin_ui_baseline_$$TIMESTAMP/
	@echo "📄 Report: $(JMETER_RESULTS_DIR)/admin_ui_baseline_*/index.html"

jmeter-report: jmeter-check                ## Generate HTML report from last JTL file
	@echo "📄 Generating HTML report from latest JTL file..."
	@LATEST_JTL=$$(find $(JMETER_RESULTS_DIR) -maxdepth 1 -name "*.jtl" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-); \
	if [ -z "$$LATEST_JTL" ]; then \
		echo "❌ No JTL files found in $(JMETER_RESULTS_DIR)"; \
		echo "   Run a JMeter test first (e.g., make jmeter-rest-baseline)"; \
		exit 1; \
	fi; \
	REPORT_DIR="$${LATEST_JTL%.jtl}_report"; \
	echo "   Input: $$LATEST_JTL"; \
	echo "   Output: $$REPORT_DIR/"; \
	rm -rf "$$REPORT_DIR"; \
	$(JMETER_BIN) -g "$$LATEST_JTL" -o "$$REPORT_DIR"; \
	echo "✅ Report generated: $$REPORT_DIR/index.html"

jmeter-clean:                              ## Clean JMeter results directory
	@echo "🧹 Cleaning JMeter results..."
	@rm -rf $(JMETER_RESULTS_DIR)/*
	@echo "✅ Results directory cleaned: $(JMETER_RESULTS_DIR)"

jmeter-compare:                            ## Compare current vs baseline results
	@echo "📈 Comparing JMeter results..."
	@echo "   Results directory: $(JMETER_RESULTS_DIR)"
	@JTLS=$$(ls -t $(JMETER_RESULTS_DIR)/*.jtl 2>/dev/null | head -2); \
	if [ $$(echo "$$JTLS" | wc -w) -lt 2 ]; then \
		echo "❌ Need at least 2 JTL files to compare"; \
		echo "   Found: $$(ls $(JMETER_RESULTS_DIR)/*.jtl 2>/dev/null | wc -l) file(s)"; \
		exit 1; \
	fi; \
	CURRENT=$$(echo "$$JTLS" | head -1); \
	BASELINE=$$(echo "$$JTLS" | tail -1); \
	echo "   Current:  $$CURRENT"; \
	echo "   Baseline: $$BASELINE"; \
	echo ""; \
	echo "=== Summary Comparison ==="; \
	for JTL in $$CURRENT $$BASELINE; do \
		echo ""; \
		echo "File: $$(basename $$JTL)"; \
		echo "  Samples: $$(tail -n +2 $$JTL | wc -l)"; \
		echo "  Errors:  $$(tail -n +2 $$JTL | awk -F',' '{if($$8=="false")print}' | wc -l)"; \
	done

# =============================================================================
# 🧬 MUTATION TESTING
# =============================================================================
# help: 🧬 MUTATION TESTING
# help: mutmut-install       - Install mutmut in development virtualenv
# help: mutmut-run           - Run mutation testing (sample of 20 mutants for quick results)
# help: mutmut-run-full      - Run FULL mutation testing (all 11,000+ mutants - takes hours!)
# help: mutmut-results       - Display mutation testing summary and surviving mutants
# help: mutmut-html          - Generate browsable HTML report of mutation results
# help: mutmut-ci            - CI-friendly mutation testing with score threshold enforcement
# help: mutmut-clean         - Clean mutmut cache and results

.PHONY: mutmut-install mutmut-run mutmut-results mutmut-html mutmut-ci mutmut-clean

mutmut-install:
	@echo "📥 Installing mutmut..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q mutmut==3.3.1"

mutmut-run: mutmut-install
	@echo "🧬 Running mutation testing (sample mode - 20 mutants)..."
	@echo "⏳ This should take about 2-3 minutes..."
	@echo "📝 Target: mcpgateway/ directory"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		cd $(PWD) && \
		PYTHONPATH=$(PWD) python run_mutmut.py --sample"

.PHONY: mutmut-run-full
mutmut-run-full: mutmut-install
	@echo "🧬 Running FULL mutation testing (all mutants)..."
	@echo "⏰ WARNING: This will take a VERY long time (hours)!"
	@echo "📝 Target: mcpgateway/ directory (11,000+ mutants)"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		cd $(PWD) && \
		PYTHONPATH=$(PWD) python run_mutmut.py --full"

mutmut-results:
	@echo "📊 Mutation testing results:"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		mutmut results || echo '⚠️  No mutation results found. Run make mutmut-run first.'"

mutmut-html:
	@echo "📄 Generating HTML mutation report..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		mutmut html || echo '⚠️  No mutation results found. Run make mutmut-run first.'"
	@[ -f html/index.html ] && echo "✅ Report available at: file://$$(pwd)/html/index.html" || true

mutmut-ci: mutmut-install
	@echo "🔍 CI mutation testing with threshold check..."
	@echo "⚠️  Excluding gateway_service.py (uses Python 3.11+ except* syntax)"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		cd $(PWD) && \
		PYTHONPATH=$(PWD) mutmut run && \
		python3 -c 'import subprocess, sys; \
			result = subprocess.run([\"mutmut\", \"results\"], capture_output=True, text=True); \
			import re; \
			match = re.search(r\"killed: (\\d+) out of (\\d+)\", result.stdout); \
			if match: \
				killed, total = int(match.group(1)), int(match.group(2)); \
				score = (killed / total * 100) if total > 0 else 0; \
				print(f\"Mutation score: {score:.1f}% ({killed}/{total} killed)\"); \
				sys.exit(0 if score >= 75 else 1); \
			else: \
				print(\"Could not parse mutation results\"); \
				sys.exit(1)' || \
		{ echo '❌ Mutation score below 75% threshold'; exit 1; }"

mutmut-clean:
	@echo "🧹 Cleaning mutmut cache..."
	@rm -rf .mutmut-cache
	@rm -rf html
	@echo "✅ Mutmut cache cleaned."

# =============================================================================
# 📊 METRICS
# =============================================================================
# help: 📊 METRICS
# help: pip-licenses         - Produce dependency license inventory (markdown)
# help: license-check         - Check repo licenses with policy file (`pyproject`, pip, Go, Rust).
# help:                      - Set LICENSE_CHECK_INCLUDE_DEV_GROUPS=true to include dev groups.
# help:                      - Set LICENSE_CHECK_SUMMARY_ONLY=true for compact output.
# help: scc                  - Quick LoC/complexity snapshot with scc
# help: scc-report           - Generate HTML LoC & per-file metrics with scc
.PHONY: ensure-pip-licenses pip-licenses license-check scc scc-report

ensure-pip-licenses:
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install -q pip-licenses"

pip-licenses: ensure-pip-licenses
	@mkdir -p $(dir $(LICENSES_MD))
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		pip-licenses --format=markdown --with-authors --with-urls > $(LICENSES_MD)"
	@cat $(LICENSES_MD)
	@echo "📜  License inventory written to $(LICENSES_MD)"

license-check: ensure-pip-licenses
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		python3 scripts/license_checker.py \
		--config $(LICENSE_CHECK_POLICY) \
		--report-json $(LICENSE_CHECK_REPORT) \
		$(if $(filter true,$(strip $(LICENSE_CHECK_INCLUDE_DEV_GROUPS))),--include-dev-groups) \
		$(if $(filter true,$(strip $(LICENSE_CHECK_SUMMARY_ONLY))),--summary-only)"

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
# help: docs-assets           - Sync logo/icon SVGs from mcpgateway/static to docs
# help: docs-serve            - Sync assets and serve docs locally with mkdocs
# help: images               - Generate architecture & dependency diagrams

# Pick the right "in-place" flag for sed (BSD vs GNU)
ifeq ($(shell uname),Darwin)
  SED_INPLACE := -i ''
else
  SED_INPLACE := -i
endif

.PHONY: docs-assets
docs-assets:
	@echo "🖼️   Syncing logo assets to docs..."
	@mkdir -p $(DOCS_DIR)/docs/images
	@cp mcpgateway/static/contextforge-logo_horizontal_color.svg \
	    mcpgateway/static/contextforge-logo_horizontal_white.svg \
	    mcpgateway/static/contextforge-logo_horizontal_black.svg \
	    mcpgateway/static/contextforge-logo_vertical_white.svg \
	    mcpgateway/static/contextforge-logo_vertical_black.svg \
	    mcpgateway/static/contextforge-icon_white.svg \
	    mcpgateway/static/contextforge-icon_black.svg \
	    $(DOCS_DIR)/docs/images/
	@echo "✅  Logo assets synced"

.PHONY: docs-serve
docs-serve: docs-assets
ifeq ($(shell uname),Darwin)
	@cd $(DOCS_DIR) && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib mkdocs serve
else
	@cd $(DOCS_DIR) && mkdocs serve
endif

.PHONY: docs
docs: docs-assets images sbom
	@echo "📚  Generating documentation with handsdown..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q handsdown && \
		python3 -m handsdown --external https://github.com/IBM/mcp-context-forge/ \
		         -o $(DOCS_DIR)/docs \
		         -n app --name '$(PROJECT_NAME)' --cleanup"

	# FIXME - need some changes to index before just copying it from root
	# @cp README.md $(DOCS_DIR)/docs/index.md
	@echo "✅  Docs ready in $(DOCS_DIR)/docs"

.PHONY: images
images:
	@echo "🖼️   Generating documentation diagrams..."
	@mkdir -p $(DOCS_DIR)/docs/design/images
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q code2flow && \
		$(VENV_DIR)/bin/code2flow mcpgateway/ --output $(DOCS_DIR)/docs/design/images/code2flow.dot || true"
	@command -v dot >/dev/null 2>&1 || { \
		echo "⚠️  Graphviz (dot) not installed - skipping diagram generation"; \
		echo "💡  Install with: brew install graphviz (macOS) or apt-get install graphviz (Linux)"; \
	} && \
	dot -Tsvg -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=14 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=14 -Efontcolor=black $(DOCS_DIR)/docs/design/images/code2flow.dot -o $(DOCS_DIR)/docs/design/images/code2flow.svg || true
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q snakefood3 && \
		python3 -m snakefood3 . mcpgateway > snakefood.dot"
	@command -v dot >/dev/null 2>&1 && \
	dot -Tpng -Gbgcolor=transparent -Gfontname="Arial" -Nfontname="Arial" -Nfontsize=12 -Nfontcolor=black -Nfillcolor=white -Nshape=box -Nstyle="filled,rounded" -Ecolor=gray -Efontname="Arial" -Efontsize=10 -Efontcolor=black snakefood.dot -o $(DOCS_DIR)/docs/design/images/snakefood.png || true
	@$(UV_BIN) tool run --with-editable . --from pylint==$(PYLINT_VERSION) pyreverse --colorized mcpgateway || true
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
# help: black                - Reformat code with black (CHECK=1 for dry-run)
# help: autoflake            - Remove unused imports / variables with autoflake
# help: isort                - Organise & sort imports with isort (CHECK=1 for dry-run)
# help: pylint               - Pylint static analysis
# help: markdownlint         - Lint Markdown files with markdownlint (requires markdownlint-cli)
# help: mypy                 - Static type-checking with mypy
# help: bandit               - Security scan with bandit
# help: pydocstyle           - Docstring style checker
# help: pycodestyle          - Simple PEP-8 checker
# help: pre-commit           - Run all configured pre-commit hooks
# help: ruff                 - Ruff linter (RUFF_MODE=check|fix|format, RUFF_SELECT=rules)
# help: ty                   - Ty type checker from astral
# help: pyright              - Static type-checking with Pyright
# help: radon                - Code complexity & maintainability metrics
# help: pyroma               - Validate packaging metadata
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
# help: vulture              - Dead code detection
# help: linting-workflow-actionlint  - Lint GitHub Actions workflows (actionlint; shellcheck disabled)
# help: linting-workflow-zizmor      - Security-focused linting of GitHub Actions workflows
# help: linting-workflow-reviewdog   - Run reviewdog locally (non-PR reporter mode)
# help: linting-workflow-commitlint  - Validate commit messages (Conventional Commits)
# help: linting-python-fixit         - Run Fixit Python linter (modernization suggestions)
# help: linting-python-xenon         - Run Xenon complexity threshold checks
# help: linting-python-refurb        - Run Refurb Python modernization linter
# help: linting-docs-codespell       - Spell-check repository text with codespell
# help: linting-docs-markdown-links  - Check Markdown links (default: README.md)
# help: linting-web-depcheck         - Check unused/missing Node.js dependencies
# help: linting-helm-lint            - Run Helm chart lint
# help: linting-helm-chart-testing   - Run chart-testing lint (ct) for Helm chart
# help: linting-helm-unittest        - Run Helm chart unit tests via helm-unittest plugin
# help: linting-go-gosec             - Run gosec on discovered Go modules
# help: linting-go-govulncheck       - Run govulncheck on discovered Go modules
# help: linting-security-checkov     - Run Checkov IaC security scan
# help: linting-security-kube-linter - Run kube-linter against Kubernetes/Helm manifests
# help: linting-coverage-diff-cover  - Run diff-cover against changed lines
# help: linting-full                 - Run passing linting gates used by CI

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
LINTERS := isort pylint mypy bandit pydocstyle pycodestyle \
	ruff ty pyright radon pyroma pyrefly spellcheck \
		pytype check-manifest markdownlint vulture

# Linters that work well with individual files/directories
FILE_AWARE_LINTERS := isort black pylint mypy bandit pydocstyle \
	pycodestyle ruff pyright vulture markdownlint

.PHONY: lint $(LINTERS) black black-check isort-check ruff-check ruff-fix ruff-format autoflake lint-py lint-yaml lint-json lint-md lint-strict \
	lint-count-errors lint-report lint-changed lint-staged lint-commit \
	lint-pre-commit lint-pre-push lint-parallel lint-cache-clear lint-stats \
	lint-complexity lint-watch lint-watch-quick \
	lint-install-hooks lint-quick lint-fix lint-smart lint-target lint-all \
	lint-actionlint lint-chart-testing lint-helm-unittest lint-commitlint \
	linting-python-env \
	linting-workflow-actionlint linting-workflow-zizmor linting-workflow-reviewdog linting-workflow-commitlint \
	linting-python-fixit linting-python-xenon linting-python-refurb \
	linting-docs-codespell linting-docs-markdown-links linting-web-depcheck \
	linting-helm-lint linting-helm-chart-testing linting-helm-unittest \
	linting-go-gosec linting-go-govulncheck \
	linting-security-checkov linting-security-kube-linter \
	linting-coverage-diff-cover linting-full


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
	$(MAKE) --no-print-directory ruff RUFF_MODE=check TARGET="$$actual_target"; \
	$(MAKE) --no-print-directory black CHECK=1 TARGET="$$actual_target"; \
	$(MAKE) --no-print-directory isort CHECK=1 TARGET="$$actual_target"

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
	$(MAKE) --no-print-directory ruff RUFF_MODE=fix TARGET="$$actual_target"

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

# Temporary roots for ad-hoc linting tools
LINT_TMP_ROOT ?= /tmp/mcp-context-forge-lint
LINT_GO_ROOT ?= $(LINT_TMP_ROOT)/go
LINT_HELM_ROOT ?= $(LINT_TMP_ROOT)/helm
LINT_NODE_ROOT ?= $(LINT_TMP_ROOT)/node
LINT_PY_VENV ?= $(LINT_TMP_ROOT)/py-venv
LINT_GO_TOOLCHAIN ?= go1.26.2

# Tool target defaults
LINT_ZIZMOR_TARGET ?= .github/workflows
LINT_XENON_TARGET ?= mcpgateway
LINT_FIXIT_TARGET ?= mcpgateway
LINT_REFURB_TARGET ?= mcpgateway
LINT_CODESPELL_TARGET ?= .
LINT_CODESPELL_SKIP ?= ./.git,./.venv,./coverage,./docs/docs/coverage,./uv.lock,./package-lock.json,./docs/docs/design/images/*
LINT_MARKDOWN_LINKS_TARGET ?= README.md
LINT_DEPCHECK_TARGET ?= .
LINT_CHECKOV_TARGET ?= .
LINT_KUBE_LINTER_TARGET ?= charts/mcp-stack
LINT_GO_MODULE_SEARCH_DIRS ?= mcp-servers a2a-agents

# Passing gates only (used by CI workflow linting-full)
LINTING_FULL_TARGETS := linting-workflow-actionlint linting-workflow-reviewdog linting-workflow-commitlint linting-helm-lint linting-helm-chart-testing linting-helm-unittest linting-go-gosec linting-go-govulncheck

# Tools requiring auth/login (e.g. safety, OSSF scorecard) are intentionally excluded.

linting-python-env:
	@command -v python3 >/dev/null 2>&1 || { echo "❌ python3 not found"; exit 1; }
	@mkdir -p "$(LINT_TMP_ROOT)"
	@if [ ! -x "$(LINT_PY_VENV)/bin/python" ]; then \
		python3 -m venv "$(LINT_PY_VENV)"; \
	fi

.PHONY: linting-workflow-actionlint
linting-workflow-actionlint:         ## 🧭  GitHub Actions workflow linting
	@echo "🧭 actionlint ($(LINT_ZIZMOR_TARGET); shellcheck integration disabled)..."
	@command -v go >/dev/null 2>&1 || { echo "❌ go not found"; exit 1; }
	@/bin/bash -c "set -euo pipefail; \
		export GOPATH='$(LINT_GO_ROOT)/gopath'; \
		export GOMODCACHE='$(LINT_GO_ROOT)/gopath/pkg/mod'; \
		export GOCACHE='$(LINT_GO_ROOT)/gocache'; \
		mkdir -p '$(LINT_GO_ROOT)/gopath' '$(LINT_GO_ROOT)/gopath/pkg/mod' '$(LINT_GO_ROOT)/gocache'; \
		go run github.com/rhysd/actionlint/cmd/actionlint@latest -shellcheck="

.PHONY: linting-workflow-zizmor
linting-workflow-zizmor:             ## 🔐  GitHub Actions security linting
	@echo "🔐 zizmor scan of $(LINT_ZIZMOR_TARGET)..."
	@$(MAKE) --no-print-directory linting-python-env
	@"$(LINT_PY_VENV)/bin/python" -m pip install -q --disable-pip-version-check zizmor
	@"$(LINT_PY_VENV)/bin/zizmor" "$(LINT_ZIZMOR_TARGET)"

.PHONY: linting-workflow-reviewdog
linting-workflow-reviewdog:          ## 🐶  reviewdog in local reporter mode
	@echo "🐶 reviewdog local run (input: actionlint)..."
	@command -v go >/dev/null 2>&1 || { echo "❌ go not found"; exit 1; }
	@/bin/bash -c "set -euo pipefail; \
		export GOPATH='$(LINT_GO_ROOT)/gopath'; \
		export GOMODCACHE='$(LINT_GO_ROOT)/gopath/pkg/mod'; \
		export GOCACHE='$(LINT_GO_ROOT)/gocache'; \
		export GOBIN='$(LINT_GO_ROOT)/bin'; \
		mkdir -p '$(LINT_GO_ROOT)/gopath' '$(LINT_GO_ROOT)/gopath/pkg/mod' '$(LINT_GO_ROOT)/gocache' '$(LINT_GO_ROOT)/bin'; \
		go install github.com/reviewdog/reviewdog/cmd/reviewdog@latest >/dev/null; \
		go run github.com/rhysd/actionlint/cmd/actionlint@latest -shellcheck= -oneline | \
			'$(LINT_GO_ROOT)/bin/reviewdog' -name=actionlint -efm='%f:%l:%c: %m' -reporter=local"

.PHONY: linting-python-fixit
linting-python-fixit:                ## 🧪  Fixit Python linting
	@echo "🧪 fixit lint of $(LINT_FIXIT_TARGET)..."
	@$(MAKE) --no-print-directory linting-python-env
	@"$(LINT_PY_VENV)/bin/python" -m pip install -q --disable-pip-version-check fixit
	@"$(LINT_PY_VENV)/bin/python" -c "import sys; from concurrent.futures import ThreadPoolExecutor; import trailrunner.core; trailrunner.core.Trailrunner.DEFAULT_EXECUTOR = ThreadPoolExecutor; from fixit.cli import main; sys.argv=['fixit','lint','$(LINT_FIXIT_TARGET)']; raise SystemExit(main())"

.PHONY: linting-python-xenon
linting-python-xenon:                ## 📈  Xenon complexity checks
	@echo "📈 xenon complexity scan of $(LINT_XENON_TARGET)..."
	@$(MAKE) --no-print-directory linting-python-env
	@"$(LINT_PY_VENV)/bin/python" -m pip install -q --disable-pip-version-check xenon
	@"$(LINT_PY_VENV)/bin/xenon" --max-absolute C --max-modules C --max-average C "$(LINT_XENON_TARGET)"

.PHONY: linting-python-refurb
linting-python-refurb:               ## 🧼  Refurb modernization checks
	@echo "🧼 refurb scan of $(LINT_REFURB_TARGET)..."
	@$(MAKE) --no-print-directory linting-python-env
	@"$(LINT_PY_VENV)/bin/python" -m pip install -q --disable-pip-version-check refurb mypy pydantic
	@"$(LINT_PY_VENV)/bin/refurb" "$(LINT_REFURB_TARGET)"


.PHONY: linting-docs-codespell
linting-docs-codespell:              ## 🔤  Spell-check repository text
	@echo "🔤 codespell scan of $(LINT_CODESPELL_TARGET)..."
	@$(MAKE) --no-print-directory linting-python-env
	@"$(LINT_PY_VENV)/bin/python" -m pip install -q --disable-pip-version-check codespell
	@"$(LINT_PY_VENV)/bin/codespell" --skip="$(LINT_CODESPELL_SKIP)" "$(LINT_CODESPELL_TARGET)"

.PHONY: linting-docs-markdown-links
linting-docs-markdown-links:         ## 🔗  Markdown link checking
	@echo "🔗 markdown-link-check on $(LINT_MARKDOWN_LINKS_TARGET)..."
	@command -v node >/dev/null 2>&1 || { echo "❌ node not found"; exit 1; }
	@command -v npm >/dev/null 2>&1 || { echo "❌ npm not found"; exit 1; }
	@mkdir -p "$(LINT_NODE_ROOT)/markdown-link-check" "$(LINT_NODE_ROOT)/npm-cache"
	@/bin/bash -c "set -euo pipefail; cd '$(LINT_NODE_ROOT)/markdown-link-check'; \
		if [ ! -f package.json ]; then npm init -y >/dev/null 2>&1; fi; \
		npm_config_cache='$(LINT_NODE_ROOT)/npm-cache' npm install --silent markdown-link-check"
	@PATH="$(LINT_NODE_ROOT)/markdown-link-check/node_modules/.bin:$$PATH" \
		markdown-link-check "$(LINT_MARKDOWN_LINKS_TARGET)"

.PHONY: linting-web-depcheck
linting-web-depcheck:                ## 🧩  Node dependency hygiene
	@echo "🧩 depcheck scan of $(LINT_DEPCHECK_TARGET)..."
	@command -v node >/dev/null 2>&1 || { echo "❌ node not found"; exit 1; }
	@command -v npm >/dev/null 2>&1 || { echo "❌ npm not found"; exit 1; }
	@mkdir -p "$(LINT_NODE_ROOT)/depcheck" "$(LINT_NODE_ROOT)/npm-cache"
	@/bin/bash -c "set -euo pipefail; cd '$(LINT_NODE_ROOT)/depcheck'; \
		if [ ! -f package.json ]; then npm init -y >/dev/null 2>&1; fi; \
		npm_config_cache='$(LINT_NODE_ROOT)/npm-cache' npm install --silent depcheck"
	@PATH="$(LINT_NODE_ROOT)/depcheck/node_modules/.bin:$$PATH" depcheck "$(LINT_DEPCHECK_TARGET)"

.PHONY: linting-helm-lint
linting-helm-lint:                   ## ⎈  Helm lint wrapper
	@$(MAKE) --no-print-directory helm-lint

.PHONY: linting-helm-chart-testing
linting-helm-chart-testing:          ## ⎈  chart-testing lint (relaxed local defaults)
	@echo "⎈ chart-testing lint..."
	@command -v go >/dev/null 2>&1 || { echo "❌ go not found"; exit 1; }
	@/bin/bash -c "set -euo pipefail; \
		export GOPATH='$(LINT_GO_ROOT)/gopath'; \
		export GOMODCACHE='$(LINT_GO_ROOT)/gopath/pkg/mod'; \
		export GOCACHE='$(LINT_GO_ROOT)/gocache'; \
		mkdir -p '$(LINT_GO_ROOT)/gopath' '$(LINT_GO_ROOT)/gopath/pkg/mod' '$(LINT_GO_ROOT)/gocache'; \
		go run github.com/helm/chart-testing/v3/ct@latest lint \
			--charts $(CHART_DIR) \
			--validate-chart-schema=false \
			--validate-yaml=false \
			--validate-maintainers=false \
			--check-version-increment=false"

.PHONY: linting-helm-unittest
linting-helm-unittest:               ## 🧪  Helm template unit tests
	@echo "🧪 helm-unittest..."
	@command -v helm >/dev/null 2>&1 || { echo "❌ helm not found"; exit 1; }
	@/bin/bash -c "set -euo pipefail; \
		export HELM_PLUGINS='$(LINT_HELM_ROOT)/plugins'; \
		export HELM_DATA_HOME='$(LINT_HELM_ROOT)/data'; \
		export HELM_CACHE_HOME='$(LINT_HELM_ROOT)/cache'; \
		export HELM_CONFIG_HOME='$(LINT_HELM_ROOT)/config'; \
		mkdir -p '$(LINT_HELM_ROOT)/plugins' '$(LINT_HELM_ROOT)/data' '$(LINT_HELM_ROOT)/cache' '$(LINT_HELM_ROOT)/config'; \
		if ! helm plugin list 2>/dev/null | grep -q '^unittest[[:space:]]'; then \
			helm plugin install https://github.com/helm-unittest/helm-unittest --version v0.5.2 --verify=false >/dev/null; \
		fi; \
		helm unittest $(CHART_DIR)"

.PHONY: linting-go-gosec
linting-go-gosec:                    ## 🔒  Go security static analysis
	@echo "🔒 gosec scan of discovered Go modules..."
	@command -v go >/dev/null 2>&1 || { echo "❌ go not found"; exit 1; }
	@export GOPATH='$(LINT_GO_ROOT)/gopath'; \
		export GOMODCACHE='$(LINT_GO_ROOT)/gopath/pkg/mod'; \
		export GOCACHE='$(LINT_GO_ROOT)/gocache'; \
		export GOBIN='$(LINT_GO_ROOT)/bin'; \
		export GOTOOLCHAIN='$(LINT_GO_TOOLCHAIN)'; \
		mkdir -p '$(LINT_GO_ROOT)/gopath' '$(LINT_GO_ROOT)/gopath/pkg/mod' '$(LINT_GO_ROOT)/gocache' '$(LINT_GO_ROOT)/bin'; \
		go install github.com/securego/gosec/v2/cmd/gosec@latest >/dev/null; \
		mods="$$( { find $(LINT_GO_MODULE_SEARCH_DIRS) -name go.mod -not -path '*/templates/*' -exec dirname {} ';' 2>/dev/null || true; } | sort -u )"; \
		if [ -z "$$mods" ]; then echo 'ℹ️  No Go modules found'; exit 0; fi; \
		while IFS= read -r d; do \
			[ -n "$$d" ] || continue; \
			echo "→ gosec $$d"; \
			(cd "$$d" && "$(LINT_GO_ROOT)/bin/gosec" ./...); \
		done <<< "$$mods"

.PHONY: linting-go-govulncheck
linting-go-govulncheck:              ## 🔎  Go vulnerability checks
	@echo "🔎 govulncheck scan of discovered Go modules..."
	@command -v go >/dev/null 2>&1 || { echo "❌ go not found"; exit 1; }
	@export GOPATH='$(LINT_GO_ROOT)/gopath'; \
		export GOMODCACHE='$(LINT_GO_ROOT)/gopath/pkg/mod'; \
		export GOCACHE='$(LINT_GO_ROOT)/gocache'; \
		export GOBIN='$(LINT_GO_ROOT)/bin'; \
		export GOTOOLCHAIN='$(LINT_GO_TOOLCHAIN)'; \
		mkdir -p '$(LINT_GO_ROOT)/gopath' '$(LINT_GO_ROOT)/gopath/pkg/mod' '$(LINT_GO_ROOT)/gocache' '$(LINT_GO_ROOT)/bin'; \
		go install golang.org/x/vuln/cmd/govulncheck@latest >/dev/null; \
		mods="$$( { find $(LINT_GO_MODULE_SEARCH_DIRS) -name go.mod -not -path '*/templates/*' -exec dirname {} ';' 2>/dev/null || true; } | sort -u )"; \
		if [ -z "$$mods" ]; then echo 'ℹ️  No Go modules found'; exit 0; fi; \
		while IFS= read -r d; do \
			[ -n "$$d" ] || continue; \
			echo "→ govulncheck $$d"; \
			(cd "$$d" && "$(LINT_GO_ROOT)/bin/govulncheck" ./...); \
		done <<< "$$mods"

.PHONY: linting-security-checkov
linting-security-checkov:            ## 🛡️  IaC security scanning with Checkov
	@echo "🛡️ checkov scan of $(LINT_CHECKOV_TARGET)..."
	@$(MAKE) --no-print-directory linting-python-env
	@"$(LINT_PY_VENV)/bin/python" -m pip install -q --disable-pip-version-check checkov
	@"$(LINT_PY_VENV)/bin/checkov" -d "$(LINT_CHECKOV_TARGET)" --quiet

.PHONY: linting-security-kube-linter
linting-security-kube-linter:        ## 🧱  Kubernetes best-practice linting
	@echo "🧱 kube-linter scan of $(LINT_KUBE_LINTER_TARGET)..."
	@command -v go >/dev/null 2>&1 || { echo "❌ go not found"; exit 1; }
	@/bin/bash -c "set -euo pipefail; \
		export GOPATH='$(LINT_GO_ROOT)/gopath'; \
		export GOMODCACHE='$(LINT_GO_ROOT)/gopath/pkg/mod'; \
		export GOCACHE='$(LINT_GO_ROOT)/gocache'; \
		export GOBIN='$(LINT_GO_ROOT)/bin'; \
		export GOTOOLCHAIN='$(LINT_GO_TOOLCHAIN)'; \
		mkdir -p '$(LINT_GO_ROOT)/gopath' '$(LINT_GO_ROOT)/gopath/pkg/mod' '$(LINT_GO_ROOT)/gocache' '$(LINT_GO_ROOT)/bin'; \
		go install golang.stackrox.io/kube-linter/cmd/kube-linter@latest >/dev/null; \
		'$(LINT_GO_ROOT)/bin/kube-linter' lint '$(LINT_KUBE_LINTER_TARGET)'"

.PHONY: linting-coverage-diff-cover
linting-coverage-diff-cover:         ## 📊  Changed-lines coverage gate
	@$(MAKE) --no-print-directory diff-cover

.PHONY: linting-full
linting-full: $(LINTING_FULL_TARGETS) ## ✅ Passing lint gates for CI
	@echo "✅ linting-full passed"

# Backward-compatible aliases (keep previous names working)
lint-actionlint: linting-workflow-actionlint
	@:

lint-chart-testing: linting-helm-chart-testing
	@:

lint-helm-unittest: linting-helm-unittest
	@:

lint-commitlint: linting-workflow-commitlint
	@:

## --------------------------------------------------------------------------- ##
##  Individual targets (alphabetical, updated to use TARGET)
## --------------------------------------------------------------------------- ##
autoflake:                          ## 🧹  Strip unused imports / vars
	@echo "🧹 autoflake $(TARGET)..."
	@$(VENV_DIR)/bin/autoflake --in-place --remove-all-unused-imports \
		--remove-unused-variables -r $(TARGET)

CHECK ?=

black: uv                           ## 🎨  Reformat code with black (CHECK=1 for dry-run)
	@if [ -n "$(call is_true,$(CHECK))" ]; then \
		echo "🎨  black --check $(TARGET)..." && $(UV_BIN) tool run black==$(BLACK_VERSION) -l 200 --check --diff $(TARGET); \
	else \
		echo "🎨  black $(TARGET)..." && $(UV_BIN) tool run black==$(BLACK_VERSION) -l 200 $(TARGET); \
	fi

isort: uv                           ## 🔀  Sort imports (CHECK=1 for dry-run)
	@if [ -n "$(call is_true,$(CHECK))" ]; then \
		echo "🔀  isort --check $(TARGET)..." && $(UV_BIN) tool run isort==$(ISORT_VERSION) --check-only --diff $(TARGET); \
	else \
		echo "🔀  isort $(TARGET)..." && $(UV_BIN) tool run isort==$(ISORT_VERSION) $(TARGET); \
	fi

# --- Deprecated aliases (use CHECK=1 instead) ---
# deprecated: black-check       - Use "make black CHECK=1" instead (v1.2.0)
# deprecated: isort-check       - Use "make isort CHECK=1" instead (v1.2.0)
black-check:
	$(call deprecated_target,black-check,make black CHECK=1,1.2.0)
	@$(MAKE) --no-print-directory black CHECK=1 TARGET="$(TARGET)"

isort-check:
	$(call deprecated_target,isort-check,make isort CHECK=1,1.2.0)
	@$(MAKE) --no-print-directory isort CHECK=1 TARGET="$(TARGET)"


pylint: uv                             ## 🐛  pylint checks
	@echo "🐛 pylint $(TARGET) (parallel)..."
	@rcfile=".pylintrc"; \
	 if [ -f ".pylintrc.$(TARGET)" ]; then rcfile=".pylintrc.$(TARGET)"; fi; \
	 $(UV_BIN) tool run --with-editable . --with pylint-pydantic==$(PYLINT_PYDANTIC_VERSION) pylint==$(PYLINT_VERSION) -j 0 --rcfile=$$rcfile --fail-on E --fail-under 10 $(TARGET)


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
		$(VENV_DIR)/bin/bandit -c pyproject.toml -r $(TARGET); \
	else \
		$(VENV_DIR)/bin/bandit -c pyproject.toml $(TARGET); \
	fi

pydocstyle:                         ## 📚  Docstring style
	@echo "📚 pydocstyle $(TARGET)..." && $(VENV_DIR)/bin/pydocstyle $(TARGET)

pycodestyle:                        ## 📝  Simple PEP-8 checker
	@echo "📝 pycodestyle $(TARGET)..." && $(VENV_DIR)/bin/pycodestyle $(TARGET) --max-line-length=200

.PHONY: pre-commit
pre-commit: uv                     ## 🪄  Run pre-commit tool
	@echo "🪄  Running pre-commit hooks..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@if [ ! -x "$(VENV_DIR)/bin/pre-commit" ]; then \
		echo "📦 Installing pre-commit in $(VENV_DIR)..."; \
		$(UV_BIN) pip install --python "$(VENV_DIR)/bin/python" --quiet pre-commit; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		mkdir -p '$(CURDIR)/.cache/pre-commit-home' \
			'$(CURDIR)/.cache/xdg-cache' \
			'$(CURDIR)/.cache/xdg-data' \
			'$(CURDIR)/.cache/virtualenv-app-data' \
			'$(CURDIR)/.cache/go-cache' \
			'$(CURDIR)/.cache/go-mod' \
			'$(CURDIR)/.cache/go-build' \
			'$(CURDIR)/.cache/pip-cache' \
			'$(CURDIR)/.cache/tmp'; \
		PRE_COMMIT_HOME='$(CURDIR)/.cache/pre-commit-home' \
		XDG_CACHE_HOME='$(CURDIR)/.cache/xdg-cache' \
		XDG_DATA_HOME='$(CURDIR)/.cache/xdg-data' \
		VIRTUALENV_OVERRIDE_APP_DATA='$(CURDIR)/.cache/virtualenv-app-data' \
		PATH='/usr/bin:$$PATH' \
		TMPDIR='$(CURDIR)/.cache/tmp' \
		PIP_CACHE_DIR='$(CURDIR)/.cache/pip-cache' \
		PIP_USE_PEP517='0' \
		PIP_NO_BUILD_ISOLATION='1' \
		GOPATH='$(CURDIR)/.cache/go-cache' \
		GOMODCACHE='$(CURDIR)/.cache/go-mod' \
		GOCACHE='$(CURDIR)/.cache/go-build' \
		$(VENV_DIR)/bin/pre-commit run --config .pre-commit-lite.yaml --all-files --show-diff-on-failure"

RUFF_MODE   ?= check
RUFF_SELECT ?=

ruff: uv                            ## ⚡  Ruff linter (RUFF_MODE=check|fix|format, RUFF_SELECT=rules)
	@ruff_cmd=""; \
	case "$(RUFF_MODE)" in \
		check)  ruff_cmd="check" ;; \
		fix)    ruff_cmd="check --fix" ;; \
		format) ruff_cmd="format" ;; \
		*)      printf 'ERROR: RUFF_MODE must be check, fix, or format (got "%s")\n' '$(RUFF_MODE)'; exit 1 ;; \
	esac; \
	select_flag=""; \
	if [ -n "$(RUFF_SELECT)" ]; then select_flag="--select $(RUFF_SELECT)"; fi; \
	echo "⚡ ruff $$ruff_cmd $$select_flag $(TARGET)..."; \
	$(UV_BIN) tool run ruff==$(RUFF_VERSION) $$ruff_cmd $$select_flag $(TARGET)

# --- Deprecated aliases (use RUFF_MODE= instead) ---
# deprecated: ruff-check        - Use "make ruff RUFF_MODE=check" instead (v1.2.0)
# deprecated: ruff-fix          - Use "make ruff RUFF_MODE=fix" instead (v1.2.0)
# deprecated: ruff-format       - Use "make ruff RUFF_MODE=format" instead (v1.2.0)
ruff-check:
	$(call deprecated_target,ruff-check,make ruff RUFF_MODE=check,1.2.0)
	@$(MAKE) --no-print-directory ruff RUFF_MODE=check TARGET="$(TARGET)"

ruff-fix:
	$(call deprecated_target,ruff-fix,make ruff RUFF_MODE=fix,1.2.0)
	@$(MAKE) --no-print-directory ruff RUFF_MODE=fix TARGET="$(TARGET)"

ruff-format:
	$(call deprecated_target,ruff-format,make ruff RUFF_MODE=format,1.2.0)
	@$(MAKE) --no-print-directory ruff RUFF_MODE=format TARGET="$(TARGET)"

future-proof-ruff: uv               ## ⚡  Ruff G+BLE rules on files diverged from main
	@changed=$$(git diff --name-only --diff-filter=ACM main -- '*.py' 2>/dev/null || true); \
	if [ -z "$$changed" ]; then \
		echo "ℹ️  No Python files diverged from main"; \
	else \
		echo "⚡ ruff check --select G,BLE on $$(echo $$changed | wc -w | tr -d ' ') file(s)..."; \
		$(UV_BIN) tool run ruff==$(RUFF_VERSION) check --select G,BLE $$changed; \
	fi

ty:                                 ## ⚡  Ty type checker
	@echo "⚡ ty $(TARGET)..." && $(VENV_DIR)/bin/ty check $(TARGET)

pyright:                            ## 🏷️  Pyright type-checking
	@echo "🏷️ pyright $(TARGET)..." && $(VENV_DIR)/bin/pyright $(TARGET)

radon: uv                           ## 📈  Complexity / MI metrics
	@$(UV_BIN) tool run radon==$(RADON_VERSION) mi -s $(TARGET) && \
	$(UV_BIN) tool run radon==$(RADON_VERSION) cc -s $(TARGET) && \
	$(UV_BIN) tool run radon==$(RADON_VERSION) hal $(TARGET) && \
	$(UV_BIN) tool run radon==$(RADON_VERSION) raw -s $(TARGET)

pyroma:                             ## 📦  Packaging metadata check
	@$(VENV_DIR)/bin/pyroma -d .

spellcheck:                         ## 🔤  Spell-check
	@$(UV_BIN) tool run --with 'lxml>=6.1.0' pyspelling==$(PYSPELLING_VERSION) || true

.PHONY: fawltydeps
fawltydeps:                         ## 🏗️  Dependency sanity
	@$(VENV_DIR)/bin/fawltydeps --detailed --exclude 'docs/**' . || true

.PHONY: wily
wily:                               ## 📈  Maintainability report
	@echo "📈  Maintainability report..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@git stash --quiet
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q wily && \
		python3 -m wily build -n 10 . > /dev/null || true && \
		python3 -m wily report . || true"
	@git stash pop --quiet

.PHONY: pyre
pyre:                               ## 🧠  Facebook Pyre analysis
	@$(VENV_DIR)/bin/pyre

pyrefly:                            ## 🧠  Facebook Pyrefly analysis (faster, rust)
	@echo "🧠 pyrefly $(TARGET)..." && $(VENV_DIR)/bin/pyrefly check $(TARGET)

.PHONY: depend
depend:                             ## 📦  List dependencies
	@echo "📦  List dependencies"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q pdm && \
		python3 -m pdm list --freeze"

.PHONY: snakeviz
snakeviz:                           ## 🐍  Interactive profile visualiser
	@echo "🐍  Interactive profile visualiser..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q snakeviz && \
		python3 -m cProfile -o mcp.prof mcpgateway/main.py && \
		python3 -m snakeviz mcp.prof --server"

.PHONY: pstats
pstats:                             ## 📊  Static call-graph image
	@echo "📊  Static call-graph image"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q gprof2dot && \
		python3 -m cProfile -o mcp.pstats mcpgateway/main.py && \
		$(VENV_DIR)/bin/gprof2dot -w -e 3 -n 3 -s -f pstats mcp.pstats | \
		dot -Tpng -o $(DOCS_DIR)/pstats.png"

.PHONY: spellcheck-sort
spellcheck-sort: .spellcheck-en.txt ## 🔤  Sort spell-list
	sort -d -f -o $< $<

.PHONY: tox
tox:                                ## 🧪  Multi-Python tox matrix (uv)
	@echo "🧪  Running tox with uv across Python 3.11, 3.12, 3.13..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q tox tox-uv && \
		python3 -m tox -p auto $(TOXARGS)"

.PHONY: sbom
sbom: uv							## 🛡️  Generate SBOM & security report
	@echo "🛡️   Generating SBOM & security report..."
	@rm -Rf "$(VENV_DIR).sbom"
	@$(UV_BIN) venv "$(VENV_DIR).sbom"
	@/bin/bash -c "source $(VENV_DIR).sbom/bin/activate && $(UV_BIN) pip install .[dev]"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install -q cyclonedx-bom sbom2doc"
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
	@echo "🔒  Recording local scan guidance..."
	@echo '## Security Scan' >> $(DOCS_DIR)/docs/test/sbom.md
	@echo '' >> $(DOCS_DIR)/docs/test/sbom.md
	@echo 'Review the generated SBOM separately before publishing the image.' >> $(DOCS_DIR)/docs/test/sbom.md
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

vulture: uv                         ## 🧹  Dead code detection
	@echo "🧹  vulture $(TARGET) …" && $(UV_BIN) tool run vulture==$(VULTURE_VERSION) $(TARGET) --min-confidence 80 --exclude "*_pb2.py,*_pb2_grpc.py"

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
# help: lint-changed         - Lint only git-changed files (uses lint-smart per file)
# help: lint-staged          - Lint only git-staged files (uses lint-smart per file)
# help: lint-commit          - Lint files in specific commit (COMMIT=hash)
.PHONY: lint-changed lint-staged lint-commit

# Generic "lint files from a git command" macro.
# $(1) = human label (e.g., "changed", "staged", "in commit abc123")
# $(2) = shell command that produces a newline-delimited file list
define lint_git_files
	@echo "🔍 Linting $(1) files..."; \
	file_list=$$($(2) 2>/dev/null || true); \
	if [ -z "$$file_list" ]; then \
		echo "ℹ️  No $(1) files to lint"; \
	else \
		echo "$(1) files:"; \
		printf '  - %s\n' $$file_list; \
		echo ""; \
		for file in $$file_list; do \
			if [ -e "$$file" ]; then \
				echo "🎯 Linting: $$file"; \
				$(MAKE) --no-print-directory lint-smart "$$file"; \
			fi; \
		done; \
	fi
endef

lint-changed:							## 🔍 Lint only changed files (git)
	$(call lint_git_files,changed,git diff --name-only --diff-filter=ACM HEAD)

lint-staged:							## 🔍 Lint only staged files (git)
	$(call lint_git_files,staged,git diff --name-only --cached --diff-filter=ACM)

COMMIT ?= HEAD
lint-commit:							## 🔍 Lint files changed in commit (COMMIT=hash)
	$(call lint_git_files,in commit $(COMMIT),git diff-tree --no-commit-id --name-only -r $(COMMIT))

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
		$(UV_BIN) pip install -q watchdog"

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
	@for tool in pylint mypy bandit ruff; do \
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
		$(UV_BIN) pip install -q pytest-xdist"
	@# Run fast linters in parallel
	@$(MAKE) --no-print-directory ruff RUFF_MODE=check TARGET="$(TARGET)" & \
	$(MAKE) --no-print-directory black CHECK=1 TARGET="$(TARGET)" & \
	$(MAKE) --no-print-directory isort CHECK=1 TARGET="$(TARGET)" & \
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
lint-complexity: uv					## 📈 Analyze code complexity
	@echo "📈 Analyzing code complexity for $(TARGET)..."
	@echo '📊 Cyclomatic Complexity:'
	@$(UV_BIN) tool run radon==$(RADON_VERSION) cc $(TARGET) -s
	@echo ''
	@echo '📊 Maintainability Index:'
	@$(UV_BIN) tool run radon==$(RADON_VERSION) mi $(TARGET) -s

# -----------------------------------------------------------------------------
# 📑 CONTAINER SECURITY REVIEW
# -----------------------------------------------------------------------------
# help: security-scan        - Show current local container review guidance
.PHONY: security-scan

security-scan:
	@echo "ℹ️  No repo-managed local container vulnerability scanner is configured."
	@echo "ℹ️  Review the generated SBOM and use your preferred pinned scanner separately."

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

yamllint: uv                      ## 📑 YAML linting
	@echo '📑  yamllint ...'
	@$(UV_BIN) tool run yamllint==$(YAMLLINT_VERSION) -c .yamllint .

jsonlint:                         ## 📑 JSON validation (jq)
	@command -v jq >/dev/null 2>&1 || { \
		echo "❌ jq not installed."; \
		echo "💡 Install with:"; \
		echo "   • macOS: brew install jq"; \
		echo "   • Linux: sudo apt-get install jq"; \
		exit 1; \
	}
	@echo '📑  jsonlint (jq) ...'
	@find . -type f -name '*.json' \
	  -not -path './node_modules/*' \
	  -not -path './.venv/*' \
	  -not -path './.git/*' \
	  -not -path './.cache/*' \
	  -not -path './coverage/*' \
	  -not -path './.depupdate.*' \
	  -print0 \
	  | xargs -0 -I{} sh -c 'jq empty "{}"' \
	&& echo '✅  All JSON valid'

tomllint: uv                      ## 📑 TOML validation (tomlcheck)
	@echo '📑  tomllint (tomlcheck) ...'
	@find . -type f -name '*.toml' \
	  -not -path './.cache/*' \
	  -not -path './mcp-servers/templates/*' \
	  -print0 \
	  | xargs -0 -I{} $(UV_BIN) tool run tomlcheck==$(TOMLCHECK_VERSION) "{}"

# =============================================================================
# 🕸️  WEBPAGE LINTERS & STATIC ANALYSIS
# =============================================================================
# help: 🕸️  WEBPAGE LINTERS & STATIC ANALYSIS (HTML/CSS/JS lint + security scans + formatting)
# help: nodejsscan           - Run nodejsscan for JS security vulnerabilities
# help: lint-web             - Run HTMLHint, Stylelint, ESLint, Retire.js, nodejsscan and npm audit
# help: eslint               - Run ESLint for JavaScript standard style and prettifying
# help: jshint               - Run JSHint for additional JavaScript analysis
# help: jscpd                - Detect copy-pasted code in JS/HTML/CSS files
# help: markuplint           - Modern HTML linting with markuplint
# help: format-web           - Format HTML, CSS & JS files with Prettier
.PHONY: nodejsscan eslint lint-web jshint jscpd markuplint format-web

nodejsscan:
	@echo "🔒 Running nodejsscan for JavaScript security vulnerabilities..."
	@uvx nodejsscan --directory ./mcpgateway/static --directory ./mcpgateway/templates || true

eslint:
	@echo "🔍 Linting JS files..."
	@npm install --no-save
	@find mcpgateway/static -name "*.js" -print0 | { xargs -0 npx eslint || true; }

lint-web: eslint nodejsscan
	@echo "🔍 Linting HTML files..."
	@find mcpgateway/templates -name "*.html" -exec npx htmlhint {} + 2>/dev/null || true
	@echo "🔍 Linting CSS files..."
	@find mcpgateway/static -name "*.css" -exec npx stylelint {} + 2>/dev/null || true
	@echo "🔒 Scanning for known JS/CSS library vulnerabilities with retire.js..."
	@cd mcpgateway/static && npx retire . 2>/dev/null || true
	@if [ -f package.json ]; then \
	  echo "🔒 Running npm audit (high severity)..."; \
	  npm audit --audit-level=high || true; \
	else \
	  echo "⚠️  Skipping npm audit: no package.json found"; \
	fi

jshint:
	@echo "🔍 Running JSHint for JavaScript analysis..."
	@if [ -f .jshintrc ]; then \
	  echo "📋 Using .jshintrc configuration"; \
	  npx --yes jshint --config .jshintrc mcpgateway/static/*.js || true; \
	else \
	  echo "📋 No .jshintrc found, using defaults with ES11"; \
	  npx --yes jshint --esversion=11 mcpgateway/static/*.js || true; \
	fi

jscpd:
	@echo "🔍 Detecting copy-pasted code with jscpd..."
	@npx --yes jscpd "mcpgateway/static/" "mcpgateway/templates/" || true

markuplint:
	@echo "🔍 Running markuplint for modern HTML validation..."
	@npx --yes markuplint mcpgateway/templates/* || true

format-web:
	@echo "🎨 Formatting HTML, CSS & JS with Prettier..."
	@npx --yes prettier --write "mcpgateway/templates/**/*.html" \
	                 "mcpgateway/static/**/*.css" \
	                 "mcpgateway/static/**/*.js"

# =============================================================================
# 🧪 JAVASCRIPT UNIT TESTING (Vitest)
# =============================================================================
# help: 🧪 JAVASCRIPT UNIT TESTING (Vitest)
# help: test-js              - Run JavaScript unit tests with Vitest
# help: test-js-coverage     - Run JS tests with Istanbul coverage report
# help: test-js-watch        - Run Vitest in watch mode (re-runs on file changes)
# help: test-js-ui           - Run Vitest with interactive browser UI

.PHONY: test-js test-js-coverage test-js-watch test-js-ui

test-js:
	@echo "🧪 Running JavaScript unit tests with Vitest..."
	@npm install --no-save
	@npx vitest run

test-js-coverage:
	@echo "📊 Running JavaScript tests with Istanbul coverage..."
	@npm install --no-save
	@npx vitest run --coverage

test-js-watch:
	@echo "👀 Running Vitest in watch mode..."
	@npm install --no-save
	@npx vitest

test-js-ui:
	@echo "🎭 Running Vitest with interactive UI..."
	@npm install --no-save
	@npx vitest --ui

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
sonar-deps-podman: uv
	@echo "🔧 Installing podman-compose ..."
	$(UV_BIN) tool install --quiet podman-compose

sonar-deps-docker: uv
	@echo "🔧 Ensuring $(COMPOSE_CMD) is available ..."
	@command -v $(firstword $(COMPOSE_CMD)) >/dev/null || \
	  $(UV_BIN) tool install --quiet docker-compose

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
.PHONY: sonar-submit-docker
sonar-submit-docker:
	@echo "📡 Scanning code with containerized Sonar Scanner CLI (Docker) ..."
	docker run --rm \
		-e SONAR_HOST_URL="$(SONAR_HOST_URL)" \
		$(if $(SONAR_TOKEN),-e SONAR_TOKEN="$(SONAR_TOKEN)",) \
		-v "$(PROJECT_BASEDIR):/usr/src" \
		$(SONAR_SCANNER_IMAGE) \
		-Dproject.settings=$(SONAR_PROPS)

.PHONY: sonar-submit-podman
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
.PHONY: pysonar-scanner
pysonar-scanner: uv
	@echo "🐍 Scanning code with pysonar-scanner (PyPI) ..."
	@test -f $(SONAR_PROPS) || { echo "❌ $(SONAR_PROPS) not found."; exit 1; }
	uvx pysonar-scanner \
		-Dproject.settings=$(SONAR_PROPS) \
		-Dsonar.host.url=$(SONAR_HOST_URL) \
		$(if $(SONAR_TOKEN),-Dsonar.login=$(SONAR_TOKEN),)

## ─────────── Helper: how to create & use the token ──────────────────────
.PHONY: sonar-info
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
HADOFILES := Containerfile.* Dockerfile Dockerfile.*

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

.PHONY: deps-update

deps-update:
	@echo "⬆️  Updating project dependencies via update_dependencies.py..."
	@test -f ./.github/tools/update_dependencies.py || { echo "❌ update_dependencies.py not found in ./.github/tools."; exit 1; }
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 ./.github/tools/update_dependencies.py --ignore-dependency starlette --file pyproject.toml"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 ./.github/tools/update_dependencies.py --file docs/requirements.txt"
	@echo "✅ Dependencies updated in pyproject.toml and docs/requirements.txt"


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

dist: clean uv               ## Build wheel + sdist into ./dist (optionally includes Rust)
	@echo "📦 Building Python package..."
	@$(UV_BIN) build
	@if [ "$(ENABLE_RUST_BUILD)" = "1" ]; then \
		echo "🦀 Building Rust..."; \
		$(MAKE) rust-build || { echo "⚠️  Rust build failed, continuing without Rust"; exit 0; }; \
		echo '🦀 Rust wheels built successfully'; \
	else \
		echo "⏭️  Rust builds disabled (ENABLE_RUST_BUILD=0)"; \
	fi
	@echo '🛠  Python wheel & sdist written to ./dist'
	@echo ''
	@echo '💡 To publish both Python and Rust packages:'
	@echo '   make publish         # Publish Python package'
	@echo '   make rust-release-publish  # Publish Rust wheels (if configured)'

wheel: uv                    ## Build wheel only (Python + optionally Rust)
	@echo "📦 Building Python wheel..."
	@$(UV_BIN) build --wheel
	@if [ "$(ENABLE_RUST_BUILD)" = "1" ]; then \
		echo "🦀 Building Rust wheels..."; \
		$(MAKE) rust-build || { echo "⚠️  Rust build failed, continuing without Rust"; exit 0; }; \
		echo '🦀 Rust wheels built successfully'; \
	else \
		echo "⏭️  Rust builds disabled (ENABLE_RUST_BUILD=0)"; \
	fi
	@echo '🛠  Python wheel written to ./dist'

sdist: uv                    ## Build source distribution only
	@echo "📦 Building source distribution..."
	@$(UV_BIN) build --sdist
	@echo '🛠  Source distribution written to ./dist'

verify: dist uv            ## Build, run metadata & manifest checks
	@uvx twine check dist/* && uvx check-manifest && uvx pyroma -d .
	@echo "✅  Package verified - ready to publish."

publish: verify uv         ## Verify, then upload to PyPI
	@uvx twine upload dist/*
	@echo "🚀  Upload finished - check https://pypi.org/project/$(PROJECT_NAME)/"

publish-testpypi: verify uv ## Verify, then upload to TestPyPI
	@uvx twine upload --repository testpypi dist/*
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
# help: container-build-multi - Build multiplatform image (amd64/arm64/s390x,ppc64le) locally
# help: container-inspect-manifest - Inspect multiplatform manifest in registry
# help: container-build-rust - Build image WITH Rust plugins (ENABLE_RUST_BUILD=1)
# help: container-build-rust-lite - Build lite image WITH Rust plugins
# help: container-rust       - Build with Rust and run container (all-in-one)
# help: container-run        - Run container (CONTAINER_SSL=1 CONTAINER_HOST_NET=1 CONTAINER_JWT=1 CONTAINER_HTTP_SERVER=granian|gunicorn)
# help: container-push       - Push image (handles localhost/ prefix)
# help: container-stop       - Stop & remove the container
# help: container-logs       - Stream container logs
# help: container-shell      - Open shell in running container
# help: container-info       - Show runtime and image configuration
# help: container-health     - Check container health status
# help: image-list           - List all matching container images
# help: image-clean          - Remove all project images
# help: docker-nuke          - Remove ALL containers, images, volumes, networks, and build cache (destructive!)
# help: image-retag          - Fix image naming consistency issues
# help: use-docker           - Switch to Docker runtime
# help: use-podman           - Switch to Podman runtime
# help: show-runtime         - Show current container runtime

.PHONY: container-build container-build-rust container-build-rust-lite container-rust \
        container-run container-run-ssl container-run-ssl-host \
        container-run-ssl-jwt container-push container-info container-stop container-logs container-shell \
        container-health image-list image-clean image-retag container-check-image \
        container-build-multi container-inspect-manifest use-docker use-podman show-runtime print-runtime \
        print-image container-validate-env container-check-ports container-wait-healthy


# Containerfile to use (can be overridden). Defaults to Containerfile.lite (the
# multi-stage production build); falls back to Dockerfile if absent.
CONTAINER_FILE ?= $(shell [ -f "Containerfile.lite" ] && echo "Containerfile.lite" || echo "Dockerfile")


# Define COMMA for the conditional Z flag
COMMA := ,

.PHONY: container-info
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
	@RUST_BUILD_VALUE="$(ENABLE_RUST_BUILD)"; RMCP_BUILD_VALUE="$(ENABLE_RUST_MCP_RMCP_BUILD)"; RUST_ARG=""; RMCP_ARG=""; PROFILING_ARG=""; \
	if [ "$(RUST_MCP_BUILD)" = "1" ] || [ "$(RUST_MCP_BUILD)" = "true" ]; then \
		RUST_BUILD_VALUE="1"; \
		if [ -z "$$RMCP_BUILD_VALUE" ] || [ "$$RMCP_BUILD_VALUE" = "0" ] || [ "$$RMCP_BUILD_VALUE" = "false" ]; then \
			RMCP_BUILD_VALUE="1"; \
		fi; \
	fi; \
	if [ "$$RUST_BUILD_VALUE" = "1" ] || [ "$$RUST_BUILD_VALUE" = "true" ]; then \
		echo "🦀 Building container WITH Rust plugins..."; \
		RUST_ARG="--build-arg ENABLE_RUST=true"; \
		if [ "$$RMCP_BUILD_VALUE" = "1" ] || [ "$$RMCP_BUILD_VALUE" = "true" ]; then \
			echo "🦀 Enabling rmcp support in the Rust MCP runtime..."; \
			RMCP_ARG="--build-arg ENABLE_RUST_MCP_RMCP=true"; \
		else \
			RMCP_ARG="--build-arg ENABLE_RUST_MCP_RMCP=false"; \
		fi; \
	else \
		echo "⏭️  Building container WITHOUT Rust plugins (set RUST_MCP_BUILD=1 or ENABLE_RUST_BUILD=1 to enable)"; \
		RUST_ARG="--build-arg ENABLE_RUST=false"; \
		RMCP_ARG="--build-arg ENABLE_RUST_MCP_RMCP=false"; \
	fi; \
	if [ "$(ENABLE_PROFILING_BUILD)" = "1" ]; then \
		echo "📊 Building container WITH profiling tools (memray)..."; \
		PROFILING_ARG="--build-arg ENABLE_PROFILING=true"; \
	else \
		PROFILING_ARG="--build-arg ENABLE_PROFILING=false"; \
	fi; \
	$(CONTAINER_RUNTIME) build \
		--platform=$(PLATFORM) \
		-f $(CONTAINER_FILE) \
		$$RUST_ARG \
		$$RMCP_ARG \
		$$PROFILING_ARG \
		$(DOCKER_BUILD_ARGS) \
		--tag $(IMAGE_BASE):$(IMAGE_TAG) \
		.
	@echo "✅ Built image: $(call get_image_name)"
	$(CONTAINER_RUNTIME) images $(IMAGE_BASE):$(IMAGE_TAG)

container-build-rust:
	@echo "🦀 Building container WITH Rust plugins..."
	$(MAKE) container-build ENABLE_RUST_BUILD=1

container-build-rust-lite:
	@echo "🦀 Building lite container WITH Rust plugins..."
	$(MAKE) container-build ENABLE_RUST_BUILD=1

container-rust: container-build-rust
	@echo "🦀 Building and running container with Rust plugins..."
	$(MAKE) container-run

CONTAINER_SSL        ?=
CONTAINER_HOST_NET   ?=
CONTAINER_JWT        ?=
CONTAINER_HTTP_SERVER ?=

.PHONY: container-run
container-run: container-check-image  ## Run container (CONTAINER_SSL=1 CONTAINER_HOST_NET=1 CONTAINER_JWT=1 CONTAINER_HTTP_SERVER=granian|gunicorn)
	$(if $(call is_true,$(CONTAINER_SSL)),@test -d certs || $(MAKE) --no-print-directory certs,)
	$(if $(call is_true,$(CONTAINER_JWT)),@test -d certs/jwt || $(MAKE) --no-print-directory certs-jwt,)
	@printf '🚀 Running with %s%s%s%s%s...\n' \
		'$(CONTAINER_RUNTIME)' \
		'$(if $(call is_true,$(CONTAINER_SSL)), (TLS),)' \
		'$(if $(call is_true,$(CONTAINER_HOST_NET)), (host network),)' \
		'$(if $(call is_true,$(CONTAINER_JWT)), (JWT asymmetric),)' \
		'$(if $(CONTAINER_HTTP_SERVER), + $(CONTAINER_HTTP_SERVER),)'
	-$(CONTAINER_RUNTIME) stop $(PROJECT_NAME) 2>/dev/null || true
	-$(CONTAINER_RUNTIME) rm $(PROJECT_NAME) 2>/dev/null || true
	$(CONTAINER_RUNTIME) run --name $(PROJECT_NAME) \
		$(if $(or $(call is_true,$(CONTAINER_SSL)),$(call is_true,$(CONTAINER_JWT))),--user $(shell id -u):$(shell id -g),) \
		$(if $(call is_true,$(CONTAINER_HOST_NET)),--network=host,) \
		--env-file=.env \
		$(if $(CONTAINER_HTTP_SERVER),-e HTTP_SERVER=$(CONTAINER_HTTP_SERVER),) \
		$(if $(call is_true,$(CONTAINER_SSL)),-e SSL=true -e CERT_FILE=certs/cert.pem -e KEY_FILE=certs/key.pem,) \
		$(if $(call is_true,$(CONTAINER_JWT)),-e JWT_ALGORITHM=RS256 -e JWT_PUBLIC_KEY_PATH=/app/certs/jwt/public.pem -e JWT_PRIVATE_KEY_PATH=/app/certs/jwt/private.pem,) \
		$(if $(or $(call is_true,$(CONTAINER_SSL)),$(call is_true,$(CONTAINER_JWT))),-v $(PWD)/certs:/app/certs:ro$(if $(filter podman,$(CONTAINER_RUNTIME)),$(COMMA)Z,),) \
		-p 4444:4444 \
		--restart=always \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl $(if $(call is_true,$(CONTAINER_SSL)),-k,) --fail $(if $(call is_true,$(CONTAINER_SSL)),https,http)://localhost:4444/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(call get_image_name)
	@sleep 2
	@printf '✅ Container started%s%s%s\n' \
		'$(if $(call is_true,$(CONTAINER_SSL)), with TLS,)' \
		'$(if $(call is_true,$(CONTAINER_JWT)), + JWT asymmetric,)' \
		'$(if $(CONTAINER_HTTP_SERVER), ($(CONTAINER_HTTP_SERVER)),)'
	$(if $(call is_true,$(CONTAINER_JWT)),@echo "🔐 JWT Algorithm: RS256",)
	$(if $(call is_true,$(CONTAINER_JWT)),@echo "📁 Keys mounted: /app/certs/jwt/{private$(COMMA)public}.pem",)

# --- Deprecated container-run aliases ---
# deprecated: container-run-host        - Use "make container-run CONTAINER_HOST_NET=1" instead (v1.2.0)
# deprecated: container-run-ssl         - Use "make container-run CONTAINER_SSL=1" instead (v1.2.0)
# deprecated: container-run-ssl-host    - Use "make container-run CONTAINER_SSL=1 CONTAINER_HOST_NET=1" instead (v1.2.0)
# deprecated: container-run-ssl-jwt     - Use "make container-run CONTAINER_SSL=1 CONTAINER_JWT=1" instead (v1.2.0)
# deprecated: container-run-granian     - Use "make container-run CONTAINER_HTTP_SERVER=granian" instead (v1.2.0)
# deprecated: container-run-gunicorn    - Use "make container-run CONTAINER_HTTP_SERVER=gunicorn" instead (v1.2.0)
# deprecated: container-run-granian-ssl - Use "make container-run CONTAINER_SSL=1 CONTAINER_HTTP_SERVER=granian" instead (v1.2.0)
# deprecated: container-run-gunicorn-ssl - Use "make container-run CONTAINER_SSL=1 CONTAINER_HTTP_SERVER=gunicorn" instead (v1.2.0)
.PHONY: container-run-host container-run-ssl container-run-ssl-host container-run-ssl-jwt \
	container-run-granian container-run-gunicorn container-run-granian-ssl container-run-gunicorn-ssl

container-run-host: container-check-image
	$(call deprecated_target,container-run-host,make container-run CONTAINER_HOST_NET=1,1.2.0)
	@$(MAKE) --no-print-directory container-run CONTAINER_HOST_NET=1

container-run-ssl: container-check-image
	$(call deprecated_target,container-run-ssl,make container-run CONTAINER_SSL=1,1.2.0)
	@$(MAKE) --no-print-directory container-run CONTAINER_SSL=1

container-run-ssl-host: container-check-image
	$(call deprecated_target,container-run-ssl-host,make container-run CONTAINER_SSL=1 CONTAINER_HOST_NET=1,1.2.0)
	@$(MAKE) --no-print-directory container-run CONTAINER_SSL=1 CONTAINER_HOST_NET=1

container-run-ssl-jwt: container-check-image
	$(call deprecated_target,container-run-ssl-jwt,make container-run CONTAINER_SSL=1 CONTAINER_JWT=1,1.2.0)
	@$(MAKE) --no-print-directory container-run CONTAINER_SSL=1 CONTAINER_JWT=1

container-run-granian: container-check-image
	$(call deprecated_target,container-run-granian,make container-run CONTAINER_HTTP_SERVER=granian,1.2.0)
	@$(MAKE) --no-print-directory container-run CONTAINER_HTTP_SERVER=granian

container-run-gunicorn: container-check-image
	$(call deprecated_target,container-run-gunicorn,make container-run CONTAINER_HTTP_SERVER=gunicorn,1.2.0)
	@$(MAKE) --no-print-directory container-run CONTAINER_HTTP_SERVER=gunicorn

container-run-granian-ssl: container-check-image
	$(call deprecated_target,container-run-granian-ssl,make container-run CONTAINER_SSL=1 CONTAINER_HTTP_SERVER=granian,1.2.0)
	@$(MAKE) --no-print-directory container-run CONTAINER_SSL=1 CONTAINER_HTTP_SERVER=granian

container-run-gunicorn-ssl: container-check-image
	$(call deprecated_target,container-run-gunicorn-ssl,make container-run CONTAINER_SSL=1 CONTAINER_HTTP_SERVER=gunicorn,1.2.0)
	@$(MAKE) --no-print-directory container-run CONTAINER_SSL=1 CONTAINER_HTTP_SERVER=gunicorn

.PHONY: container-push
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

.PHONY: container-stop
container-stop:
	@echo "🛑 Stopping container..."
	-$(CONTAINER_RUNTIME) stop $(PROJECT_NAME) 2>/dev/null || true
	-$(CONTAINER_RUNTIME) rm $(PROJECT_NAME) 2>/dev/null || true
	@echo "✅ Container stopped and removed"

.PHONY: container-logs
container-logs:
	@echo "📜 Streaming logs (Ctrl+C to exit)..."
	$(CONTAINER_RUNTIME) logs -f $(PROJECT_NAME)

.PHONY: container-shell
container-shell:
	@echo "🔧 Opening shell in container..."
	@if ! $(CONTAINER_RUNTIME) ps -q -f name=$(PROJECT_NAME) | grep -q .; then \
		echo "❌ Container $(PROJECT_NAME) is not running"; \
		echo "💡 Run 'make container-run' first"; \
		exit 1; \
	fi
	@$(CONTAINER_RUNTIME) exec -it $(PROJECT_NAME) /bin/bash 2>/dev/null || \
	$(CONTAINER_RUNTIME) exec -it $(PROJECT_NAME) /bin/sh

.PHONY: container-health
container-health:
	@echo "🏥 Checking container health..."
	@if ! $(CONTAINER_RUNTIME) ps -q -f name=$(PROJECT_NAME) | grep -q .; then \
		echo "❌ Container $(PROJECT_NAME) is not running"; \
		exit 1; \
	fi
	@echo "Status: $$($(CONTAINER_RUNTIME) inspect $(PROJECT_NAME) --format='{{.State.Health.Status}}' 2>/dev/null || echo 'No health check')"
	@echo "Logs:"
	@$(CONTAINER_RUNTIME) inspect $(PROJECT_NAME) --format='{{range .State.Health.Log}}{{.Output}}{{end}}' 2>/dev/null || true

# Default platforms if not specified
PLATFORMS ?= linux/amd64,linux/arm64,linux/s390x,linux/ppc64le

.PHONY: container-build-multi
container-build-multi:
	@echo "🔨 Building multi-architecture image for platforms: $(PLATFORMS)..."
	@echo "💡 Note: Multiplatform images require a registry. Use REGISTRY= to push, or omit to validate only."
	@echo "💡 Tip: Override platforms with PLATFORMS='linux/amd64,linux/arm64' to build specific architectures."
	@if [ "$(CONTAINER_RUNTIME)" = "docker" ]; then \
		if ! docker buildx inspect $(PROJECT_NAME)-builder >/dev/null 2>&1; then \
			echo "📦 Creating buildx builder with docker-container driver..."; \
			docker buildx create --name $(PROJECT_NAME)-builder --driver docker-container; \
		fi; \
		docker buildx use $(PROJECT_NAME)-builder; \
		if [ -n "$(REGISTRY)" ]; then \
			docker buildx build \
				--platform=$(PLATFORMS) \
				-f $(CONTAINER_FILE) \
				--tag $(REGISTRY)/$(IMAGE_BASE):$(IMAGE_TAG) \
				--push \
				.; \
			echo "✅ Multiplatform image pushed to $(REGISTRY)/$(IMAGE_BASE):$(IMAGE_TAG)"; \
		else \
			docker buildx build \
				--platform=$(PLATFORMS) \
				-f $(CONTAINER_FILE) \
				--tag $(IMAGE_BASE):$(IMAGE_TAG) \
				.; \
			echo "✅ Multiplatform build validated (no push - set REGISTRY= to push)"; \
		fi; \
	elif [ "$(CONTAINER_RUNTIME)" = "podman" ]; then \
		echo "📦 Building manifest with Podman..."; \
		$(CONTAINER_RUNTIME) build --platform=$(PLATFORMS) \
			-f $(CONTAINER_FILE) \
			--manifest $(IMAGE_BASE):$(IMAGE_TAG) \
			.; \
		echo "✅ Multiplatform manifest built: $(IMAGE_BASE):$(IMAGE_TAG)"; \
	else \
		echo "❌ Multi-arch builds require Docker buildx or Podman"; \
		exit 1; \
	fi

# Inspect multiplatform manifest in a registry
.PHONY: container-inspect-manifest
container-inspect-manifest:
	@echo "🔍 Inspecting multiplatform manifest..."
	@if [ -z "$(REGISTRY)" ]; then \
		echo "Usage: make container-inspect-manifest REGISTRY=ghcr.io/org/repo:tag"; \
		echo "Example: make container-inspect-manifest REGISTRY=ghcr.io/ibm/mcp-context-forge:latest"; \
	elif [ "$(CONTAINER_RUNTIME)" = "docker" ]; then \
		docker buildx imagetools inspect $(REGISTRY); \
	elif [ "$(CONTAINER_RUNTIME)" = "podman" ]; then \
		$(CONTAINER_RUNTIME) manifest inspect $(REGISTRY); \
	else \
		echo "❌ Manifest inspection requires Docker buildx or Podman"; \
		exit 1; \
	fi

# Helper targets for debugging image issues
.PHONY: image-list
image-list:
	@echo "📋 Images matching $(IMAGE_BASE):"
	@$(CONTAINER_RUNTIME) images --format "table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Created}}\t{{.Size}}" | \
		grep -E "(IMAGE|$(IMAGE_BASE))" || echo "No matching images found"

.PHONY: image-clean
image-clean:
	@echo "🧹 Removing all $(IMAGE_BASE) images..."
	@$(CONTAINER_RUNTIME) images --format "{{.Repository}}:{{.Tag}}" | \
		grep -E "(localhost/)?$(IMAGE_BASE)" | \
		xargs $(XARGS_FLAGS) $(CONTAINER_RUNTIME) rmi -f 2>/dev/null
	@echo "✅ Images cleaned"

.PHONY: docker-nuke
docker-nuke:
	@echo "⚠️  This will remove ALL containers, images, volumes, networks, and build cache."
	@echo "    Runtime: $(CONTAINER_RUNTIME)"
	@printf "    Continue? [y/N] "; read ans; \
	if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
		echo "🛑 Stopping and removing all containers..."; \
		$(CONTAINER_RUNTIME) ps -qa | xargs $(XARGS_FLAGS) $(CONTAINER_RUNTIME) rm -f 2>/dev/null || true; \
		echo "🗑️  Removing all images..."; \
		$(CONTAINER_RUNTIME) images -q | xargs $(XARGS_FLAGS) $(CONTAINER_RUNTIME) rmi -f 2>/dev/null || true; \
		echo "💾 Removing all volumes..."; \
		$(CONTAINER_RUNTIME) volume ls -q | xargs $(XARGS_FLAGS) $(CONTAINER_RUNTIME) volume rm -f 2>/dev/null || true; \
		echo "🌐 Pruning networks..."; \
		$(CONTAINER_RUNTIME) network prune -f 2>/dev/null || true; \
		echo "🏗️  Pruning build cache..."; \
		$(CONTAINER_RUNTIME) builder prune -af 2>/dev/null || true; \
		echo "🧹 Running system prune..."; \
		$(CONTAINER_RUNTIME) system prune -af 2>/dev/null || true; \
		echo "✅ Docker environment nuked."; \
	else \
		echo "❌ Cancelled"; \
	fi

# Fix image naming issues
.PHONY: image-retag
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
.PHONY: use-docker
use-docker:
	@echo "export CONTAINER_RUNTIME=docker"
	@echo "💡 Run: export CONTAINER_RUNTIME=docker"

.PHONY: use-podman
use-podman:
	@echo "export CONTAINER_RUNTIME=podman"
	@echo "💡 Run: export CONTAINER_RUNTIME=podman"

.PHONY: show-runtime
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
.PHONY: container-dev
container-dev: container-check-image container-validate
	@echo "🔧 Running development container with mounted source..."
	-$(CONTAINER_RUNTIME) stop $(PROJECT_NAME)-dev 2>/dev/null || true
	-$(CONTAINER_RUNTIME) rm $(PROJECT_NAME)-dev 2>/dev/null || true
	$(CONTAINER_RUNTIME) run --name $(PROJECT_NAME)-dev \
		--env-file=.env \
		-e DEBUG=true \
		-e LOG_LEVEL=DEBUG \
		-e TEMPLATES_AUTO_RELOAD=true \
		-v $(PWD)/mcpgateway:/app/mcpgateway:ro$(if $(filter podman,$(CONTAINER_RUNTIME)),$(COMMA)Z,) \
		-p 8000:8000 \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		-it --rm $(call get_image_name) \
		uvicorn mcpgateway.main:app --host 0.0.0.0 --port 8000 --reload

# Debug mode with verbose logging
.PHONY: container-debug
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
	@$(MAKE) container-build CONTAINER_RUNTIME=podman

podman:
	@$(MAKE) container-build CONTAINER_RUNTIME=podman

podman-prod:
	@$(MAKE) container-build CONTAINER_RUNTIME=podman

podman-build:
	@$(MAKE) container-build CONTAINER_RUNTIME=podman

podman-run:
	@$(MAKE) container-run CONTAINER_RUNTIME=podman

.PHONY: podman-run-host
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

.PHONY: podman-run-ssl
podman-run-ssl:
	@$(MAKE) container-run-ssl CONTAINER_RUNTIME=podman

.PHONY: podman-run-ssl-host
podman-run-ssl-host:
	@$(MAKE) container-run-ssl-host CONTAINER_RUNTIME=podman

.PHONY: podman-stop
podman-stop:
	@$(MAKE) container-stop CONTAINER_RUNTIME=podman

.PHONY: podman-test
podman-test:
	@echo "🔬  Testing podman endpoint..."
	@echo "- HTTP  -> curl  http://localhost:4444/system/test"
	@echo "- HTTPS -> curl -k https://localhost:4444/system/test"

.PHONY: podman-logs
podman-logs:
	@$(MAKE) container-logs CONTAINER_RUNTIME=podman

.PHONY: podman-stats
podman-stats:
	@echo "📊  Showing Podman container stats..."
	@if podman info --format '{{.Host.CgroupManager}}' | grep -q 'cgroupfs'; then \
		echo "⚠️  podman stats not supported in rootless mode without cgroups v2 (e.g., WSL2)"; \
		echo "👉  Falling back to 'podman top'"; \
		podman top $(PROJECT_NAME); \
	else \
		podman stats --no-stream; \
	fi

.PHONY: podman-top
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
# help: docker-prod-profiling - Build production image WITH profiling tools (memray, py-spy) for debugging
# help: docker-run           - Run the container on HTTP  (port 4444)
# help: docker-run-host      - Run the container on HTTP  (port 4444) with --network-host
# help: docker-run-ssl       - Run the container on HTTPS (port 4444, self-signed)
# help: docker-run-ssl-host  - Run the container on HTTPS with --network-host (port 4444, self-signed)
# help: docker-stop          - Stop & remove the container
# help: docker-test          - Quick curl smoke-test against the container
# help: docker-logs          - Follow container logs (⌃C to quit)

.PHONY: docker-dev docker docker-prod docker-prod-profiling docker-build docker-run docker-run-host docker-run-ssl \
	docker-run-ssl-host docker-stop docker-test docker-logs docker-stats \
	docker-top docker-shell

docker-dev:
	@$(MAKE) container-build CONTAINER_RUNTIME=docker

docker:
	@$(MAKE) container-build CONTAINER_RUNTIME=docker

docker-prod:
	@DOCKER_CONTENT_TRUST=1 $(MAKE) container-build CONTAINER_RUNTIME=docker

docker-prod-rust:
	@DOCKER_CONTENT_TRUST=1 $(MAKE) container-build CONTAINER_RUNTIME=docker RUST_MCP_BUILD=1

docker-prod-rust-no-cache:
	@DOCKER_CONTENT_TRUST=1 $(MAKE) container-build CONTAINER_RUNTIME=docker RUST_MCP_BUILD=1 DOCKER_BUILD_ARGS="--no-cache"

# Build production image with profiling tools (memray) for performance debugging
# Usage: make docker-prod-profiling
# Then run with SYS_PTRACE capability:
#   docker run --cap-add=SYS_PTRACE ...
# Inside container:
#   memray attach <PID> -o /tmp/profile.bin
#   memray flamegraph /tmp/profile.bin -o flamegraph.html
docker-prod-profiling:
	@echo "📊 Building production image WITH profiling tools..."
	@DOCKER_CONTENT_TRUST=1 $(MAKE) container-build CONTAINER_RUNTIME=docker ENABLE_PROFILING_BUILD=1

docker-build:
	@$(MAKE) container-build CONTAINER_RUNTIME=docker

docker-run:
	@$(MAKE) container-run CONTAINER_RUNTIME=docker

docker-run-host:
	@$(MAKE) container-run-host CONTAINER_RUNTIME=docker

docker-run-ssl:
	@$(MAKE) container-run-ssl CONTAINER_RUNTIME=docker

.PHONY: docker-run-ssl-host
docker-run-ssl-host:
	@$(MAKE) container-run-ssl-host CONTAINER_RUNTIME=docker

.PHONY: docker-stop
docker-stop:
	@$(MAKE) container-stop CONTAINER_RUNTIME=docker

.PHONY: docker-test
docker-test:
	@echo "🔬  Testing Docker endpoint..."
	@echo "- HTTP  -> curl  http://localhost:4444/system/test"
	@echo "- HTTPS -> curl -k https://localhost:4444/system/test"

.PHONY: docker-logs
docker-logs:
	@$(MAKE) container-logs CONTAINER_RUNTIME=docker

# help: docker-stats         - Show container resource usage stats (non-streaming)
.PHONY: docker-stats
docker-stats:
	@echo "📊  Showing Docker container stats..."
	@docker stats --no-stream || { echo "⚠️  Failed to fetch docker stats. Falling back to 'docker top'..."; docker top $(PROJECT_NAME); }

# help: docker-top           - Show top-level process info in Docker container
.PHONY: docker-top
docker-top:
	@echo "🧠  Showing top-level processes in the Docker container..."
	docker top $(PROJECT_NAME)

# help: docker-shell         - Open an interactive shell inside the Docker container
.PHONY: docker-shell
docker-shell:
	@$(MAKE) container-shell CONTAINER_RUNTIME=docker

# =============================================================================
# 🛠️  COMPOSE STACK (Docker Compose v2, podman compose or podman-compose)
# =============================================================================
# help: 🛠️ COMPOSE STACK     - Build / start / stop the multi-service stack
# help: compose-up            - Bring the whole stack up (detached)
# help: compose-sso           - Start stack with Keycloak SSO profile enabled
# help: compose-sso-monitoring - Start stack with SSO + monitoring profiles
# help: compose-sso-testing   - Start stack with SSO + testing (+ inspector) profiles
# help: compose-sso-down      - Stop & remove SSO-profile containers (keep named volumes)
# help: compose-sso-clean     - ✨ Down SSO stack and delete named volumes (data-loss ⚠)
# help: sso-test-login        - Run SSO smoke checks against compose stack
# help: compose-lite-up       - Start lite stack (reduced resources for local dev)
# help: compose-lite-down     - Stop lite stack
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
# help: compose-tls           - 🔐 Start stack with TLS (HTTP:8080 + HTTPS:8443, auto-generates certs)
# help: compose-tls-https     - 🔒 Start stack with TLS, force HTTPS redirect (HTTPS:8443 only)
# help: compose-tls-down      - Stop TLS-enabled stack
# help: compose-tls-logs      - Tail logs from TLS stack
# help: compose-tls-ps        - Show TLS stack status

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

# Profile detection (for platform-specific services)
ifeq ($(PLATFORM),linux/amd64)
    PROFILE = --profile with-fast-time
endif

define COMPOSE
$(COMPOSE_CMD) -f $(COMPOSE_FILE) $(PROFILE)
endef

.PHONY: compose-up compose-sso compose-sso-monitoring compose-sso-testing compose-sso-down compose-sso-clean sso-test-login \
	compose-lite-up compose-restart compose-build compose-pull \
	compose-logs compose-ps compose-shell compose-stop compose-down \
	compose-lite-down compose-rm compose-clean compose-validate compose-exec \
	compose-logs-service compose-restart-service compose-scale compose-up-safe \
	monitoring-lite-up monitoring-lite-down \
	embedded-up embedded-down embedded-clean embedded-status embedded-logs

# Validate compose file
.PHONY: compose-validate
compose-validate:
	@echo "🔍 Validating compose file..."
	@if [ ! -f "$(COMPOSE_FILE)" ]; then \
		echo "❌ Compose file not found: $(COMPOSE_FILE)"; \
		exit 1; \
	fi
	$(COMPOSE) config --quiet
	@echo "✅ Compose file is valid"

compose-upgrade-pg18: compose-validate
	@echo "⚠️  This will upgrade Postgres 17 -> 18"
	@echo "⚠️  Make sure you have a backup!"
	@read -p "Continue? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	@echo "🔄 Running Postgres upgrade..."
	$(COMPOSE) -f $(COMPOSE_FILE) -f compose.upgrade.yml run --rm pg-upgrade
	@echo "🔧 Copying pg_hba.conf from old cluster..."
	@$(COMPOSE) -f $(COMPOSE_FILE) -f compose.upgrade.yml run --rm pg-upgrade sh -c \
		"cp /var/lib/postgresql/OLD/pg_hba.conf /var/lib/postgresql/18/docker/pg_hba.conf && \
		 echo '✅ pg_hba.conf copied successfully'"
	@echo "✅ Upgrade complete!"
	@echo "📝 Next steps:"
	@echo "   1. Update docker-compose.yml to use postgres:18"
	@echo "   2. Run: make compose-up"

compose-up: compose-validate
	@echo "🚀  Using $(COMPOSE_CMD); starting stack..."
	IMAGE_LOCAL=$(call get_image_name) $(COMPOSE) up -d

compose-sso: compose-validate
	@if [ ! -f "docker-compose.sso.yml" ]; then \
		echo "❌ Compose override file not found: docker-compose.sso.yml"; \
		exit 1; \
	fi
	@echo "🔐 Starting stack with SSO profile (Keycloak)..."
	IMAGE_LOCAL=$(call get_image_name) \
	$(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.sso.yml --profile sso up -d
	@echo "✅ SSO stack started."
	@echo "   Gateway:  http://localhost:8080"
	@echo "   Keycloak: http://localhost:8180 (admin/changeme)"

compose-sso-monitoring: compose-validate
	@if [ ! -f "docker-compose.sso.yml" ]; then \
		echo "❌ Compose override file not found: docker-compose.sso.yml"; \
		exit 1; \
	fi
	@echo "🔐📊 Starting stack with SSO + monitoring profiles..."
	LOG_FORMAT=json \
	OTEL_ENABLE_OBSERVABILITY=true \
	OTEL_TRACES_EXPORTER=otlp \
	OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317 \
	IMAGE_LOCAL=$(call get_image_name) \
	$(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.sso.yml --profile sso --profile monitoring up -d
	@echo "✅ SSO + monitoring stack started."

compose-sso-testing: compose-validate
	@if [ ! -f "docker-compose.sso.yml" ]; then \
		echo "❌ Compose override file not found: docker-compose.sso.yml"; \
		exit 1; \
	fi
	@echo "🔐🧪 Starting stack with SSO + testing (+ inspector) profiles..."
	@echo "   🦗 Locust workers: $(TESTING_LOCUST_WORKERS) (override: TESTING_LOCUST_WORKERS=4 make compose-sso-testing)"
	@mkdir -p reports
	HOST_UID=$(HOST_UID) HOST_GID=$(HOST_GID) \
	LOCUST_EXPECT_WORKERS=$(TESTING_LOCUST_WORKERS) \
	IMAGE_LOCAL=$(call get_image_name) \
	$(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.sso.yml --profile sso --profile testing --profile inspector up -d --scale locust_worker=$(TESTING_LOCUST_WORKERS)
	@echo "✅ SSO + testing stack started."

compose-sso-down: compose-validate
	@if [ ! -f "docker-compose.sso.yml" ]; then \
		echo "❌ Compose override file not found: docker-compose.sso.yml"; \
		exit 1; \
	fi
	@echo "🛑 Stopping SSO stack..."
	@$(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.sso.yml --profile sso stop -t 10 2>/dev/null || true
	$(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.sso.yml --profile sso down --remove-orphans
	@echo "✅ SSO stack stopped."

compose-sso-clean: compose-validate
	@if [ ! -f "docker-compose.sso.yml" ]; then \
		echo "❌ Compose override file not found: docker-compose.sso.yml"; \
		exit 1; \
	fi
	@echo "🧹 Stopping SSO stack and removing volumes..."
	@$(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.sso.yml --profile sso stop -t 10 2>/dev/null || true
	$(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.sso.yml --profile sso down -v --remove-orphans
	@echo "✅ SSO stack and volumes removed."

sso-test-login:
	@echo "🧪 Running SSO smoke checks..."
	@COMPOSE_CMD="$(COMPOSE_CMD)" ./scripts/test-sso-flow.sh

.PHONY: compose-lite-up
compose-lite-up: ## 💻 Start lite stack (docker-compose.yml + docker-compose.override.lite.yml)
	@if [ ! -f "docker-compose.override.lite.yml" ]; then \
		echo "❌ Compose override file not found: docker-compose.override.lite.yml"; \
		exit 1; \
	fi
	@echo "🚀  Starting lite stack (with override)..."
	IMAGE_LOCAL=$(call get_image_name) $(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.override.lite.yml up -d

.PHONY: compose-restart
compose-restart:
	@echo "🔄  Restarting stack..."
	$(COMPOSE) pull
	$(COMPOSE) build
	IMAGE_LOCAL=$(IMAGE_LOCAL) $(COMPOSE) up -d

.PHONY: compose-build
compose-build:
	IMAGE_LOCAL=$(call get_image_name) $(COMPOSE) build

.PHONY: compose-pull
compose-pull:
	$(COMPOSE) pull

.PHONY: compose-logs
compose-logs:
	$(COMPOSE) logs -f

.PHONY: compose-ps
compose-ps:
	$(COMPOSE) ps

.PHONY: compose-shell
compose-shell:
	$(COMPOSE) exec gateway /bin/sh

.PHONY: compose-stop
compose-stop:
	$(COMPOSE) stop

.PHONY: compose-down
compose-down:
	$(COMPOSE) down --remove-orphans

.PHONY: compose-lite-down
compose-lite-down: ## 💻 Stop lite stack (docker-compose.yml + docker-compose.override.lite.yml)
	@echo "🛑  Stopping lite stack..."
	@$(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.override.lite.yml stop -t 10 2>/dev/null || true
	$(COMPOSE_CMD) -f docker-compose.yml -f docker-compose.override.lite.yml down --remove-orphans
	@echo "✅ Lite stack stopped."

.PHONY: monitoring-lite-up
monitoring-lite-up: ## 📊 Start lite monitoring (essential only: Prometheus, Grafana, exporters - excludes pgAdmin, Redis CLI)
	@echo "📊 Starting lite monitoring stack (docker-compose.yml + docker-compose.override.lite.yml)..."
	LOG_FORMAT=json \
	OTEL_ENABLE_OBSERVABILITY=true \
	OTEL_TRACES_EXPORTER=otlp \
	OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317 \
	$(COMPOSE_CMD_MONITOR) -f docker-compose.yml -f docker-compose.override.lite.yml --profile monitoring-lite up -d
	@echo "⏳ Waiting for Grafana to be ready..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		if curl -s -o /dev/null -w '' http://localhost:3000/api/health 2>/dev/null; then echo "✅ Grafana ready"; break; fi; \
		echo "  Attempt $$i: Grafana not ready yet..."; \
		sleep 2; \
	done
	@curl -s -X POST -u admin:changeme 'http://localhost:3000/api/user/stars/dashboard/uid/mcp-gateway-overview' >/dev/null 2>&1 || true
	@curl -s -X PUT -u admin:changeme -H "Content-Type: application/json" -d '{"homeDashboardUID": "mcp-gateway-overview"}' 'http://localhost:3000/api/org/preferences' >/dev/null 2>&1 || true
	@curl -s -X PUT -u admin:changeme -H "Content-Type: application/json" -d '{"homeDashboardUID": "mcp-gateway-overview"}' 'http://localhost:3000/api/user/preferences' >/dev/null 2>&1 || true
	@echo ""
	@echo "✅ Lite monitoring stack started!"
	@echo "📊 Grafana:    http://localhost:3000 (admin/changeme)"
	@echo "📈 Prometheus: http://localhost:9090"

.PHONY: monitoring-lite-down
monitoring-lite-down: ## 📊 Stop lite monitoring stack
	@echo "📊 Stopping lite monitoring stack..."
	@$(COMPOSE_CMD_MONITOR) -f docker-compose.yml -f docker-compose.override.lite.yml --profile monitoring-lite stop -t 10 2>/dev/null || true
	$(COMPOSE_CMD_MONITOR) -f docker-compose.yml -f docker-compose.override.lite.yml --profile monitoring-lite down --remove-orphans
	@echo "✅ Lite monitoring stack stopped."

.PHONY: compose-rm
compose-rm:
	$(COMPOSE) rm -f

# Removes **containers + named volumes** - irreversible!
.PHONY: compose-clean
compose-clean:
	$(COMPOSE) down -v

# Execute in service container
.PHONY: compose-exec
compose-exec:
	@if [ -z "$(SERVICE)" ] || [ -z "$(CMD)" ]; then \
		echo "❌ Usage: make compose-exec SERVICE=gateway CMD='command'"; \
		exit 1; \
	fi
	@echo "🔧 Executing in service $(SERVICE): $(CMD)"
	$(COMPOSE) exec $(SERVICE) $(CMD)

# Service-specific operations
.PHONY: compose-logs-service
compose-logs-service:
	@test -n "$(SERVICE)" || { echo "Usage: make compose-logs-service SERVICE=gateway"; exit 1; }
	$(COMPOSE) logs -f $(SERVICE)

.PHONY: compose-restart-service
compose-restart-service:
	@test -n "$(SERVICE)" || { echo "Usage: make compose-restart-service SERVICE=gateway"; exit 1; }
	$(COMPOSE) restart $(SERVICE)

.PHONY: compose-scale
compose-scale:
	@test -n "$(SERVICE)" && test -n "$(SCALE)" || { \
		echo "Usage: make compose-scale SERVICE=worker SCALE=3"; exit 1; }
	$(COMPOSE) up -d --scale $(SERVICE)=$(SCALE)


# help: compose-cache-clear  - Clear nginx cache (requires running nginx container)
.PHONY: compose-cache-clear
compose-cache-clear:						## 🧹 Clear nginx cache
	@echo "🧹 Clearing nginx cache..."
	@if docker ps --format '{{.Names}}' | grep -q nginx; then \
		echo "   Clearing cache files..."; \
		$(COMPOSE) exec nginx sh -c "rm -rf /var/cache/nginx/*"; \
		echo "   Reloading nginx..."; \
		$(COMPOSE) exec nginx nginx -s reload; \
	else \
		echo "   ⚠️  Nginx is not running. Cache is ephemeral and will be fresh on next start."; \
		echo "   Start the stack with: make compose-up"; \
	fi
	@echo "✅ Done"

# Compose with validation and health check
.PHONY: compose-up-safe
compose-up-safe: compose-validate compose-up
	@echo "⏳ Waiting for services to be healthy..."
	@sleep 5
	@$(COMPOSE) ps
	@echo "✅ Stack started safely"

# ─────────────────────────────────────────────────────────────────────────────
# TLS Profile - Zero-config HTTPS via Nginx
# ─────────────────────────────────────────────────────────────────────────────
.PHONY: compose-tls compose-tls-https compose-tls-down compose-tls-logs compose-tls-ps

compose-tls: compose-validate
	@echo "🔐 Starting stack with TLS enabled..."
	@echo ""
	@echo "   Endpoints:"
	@echo "   ├─ HTTP:     http://localhost:8080"
	@echo "   ├─ HTTPS:    https://localhost:8443"
	@echo "   └─ Admin UI: https://localhost:8443/admin"
	@echo ""
	@echo "💡 Options:"
	@echo "   Custom certs:        mkdir -p certs && cp cert.pem certs/ && cp key.pem certs/"
	@echo "   Passphrase certs:    make certs-passphrase && echo KEY_FILE_PASSWORD=pass >> .env"
	@echo "   Force HTTPS:         make compose-tls-https  (redirects HTTP → HTTPS)"
	@echo "   Or set env:          NGINX_FORCE_HTTPS=true make compose-tls"
	@echo ""
	IMAGE_LOCAL=$(call get_image_name) $(COMPOSE_CMD) -f $(COMPOSE_FILE) --profile tls up -d --scale nginx=0
	@echo ""
	@echo "✅ TLS stack started! Both HTTP and HTTPS are available."

compose-tls-https: compose-validate
	@echo "🔒 Starting stack with HTTPS-only mode (HTTP redirects to HTTPS)..."
	@echo ""
	@echo "   Endpoints:"
	@echo "   ├─ HTTP:     http://localhost:8080 → redirects to HTTPS"
	@echo "   ├─ HTTPS:    https://localhost:8443"
	@echo "   └─ Admin UI: https://localhost:8443/admin"
	@echo ""
	NGINX_FORCE_HTTPS=true IMAGE_LOCAL=$(call get_image_name) $(COMPOSE_CMD) -f $(COMPOSE_FILE) --profile tls up -d --scale nginx=0
	@echo ""
	@echo "✅ TLS stack started! All HTTP requests redirect to HTTPS."

compose-tls-down:
	@echo "🛑 Stopping TLS stack..."
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) --profile tls down --remove-orphans
	@echo "✅ TLS stack stopped"

compose-tls-logs:
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) --profile tls logs -f

compose-tls-ps:
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) --profile tls ps

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
	@echo "☁️  Detecting OS and preparing IBM Cloud CLI install guidance..."
	@if grep -qi microsoft /proc/version 2>/dev/null; then \
		echo "🔧 Detected WSL2"; \
		echo "❌ Refusing to install IBM Cloud CLI via curl | sh."; \
		echo "💡 Install from IBM's official packaged distribution instead:"; \
		echo "   https://cloud.ibm.com/docs/cli?topic=cli-getting-started"; \
		exit 1; \
	elif [ "$$(uname)" = "Darwin" ]; then \
		echo "🍏 Detected macOS"; \
		echo "❌ Refusing to install IBM Cloud CLI via curl | sh."; \
		echo "💡 Install from IBM's official packaged distribution instead:"; \
		echo "   https://cloud.ibm.com/docs/cli?topic=cli-getting-started"; \
		exit 1; \
	elif [ "$$(uname)" = "Linux" ]; then \
		echo "🐧 Detected Linux"; \
		echo "❌ Refusing to install IBM Cloud CLI via curl | sh."; \
		echo "💡 Install from IBM's official packaged distribution instead:"; \
		echo "   https://cloud.ibm.com/docs/cli?topic=cli-getting-started"; \
		exit 1; \
	elif command -v powershell.exe >/dev/null; then \
		echo "🪟 Detected Windows"; \
		echo "❌ Refusing to install IBM Cloud CLI via remote PowerShell script."; \
		echo "💡 Install from IBM's official packaged distribution instead:"; \
		echo "   https://cloud.ibm.com/docs/cli?topic=cli-getting-started"; \
		exit 1; \
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

.PHONY: ibmcloud-list-containers
ibmcloud-list-containers:
	@echo "📦 Listing Code Engine images"
	ibmcloud cr images
	@echo "📦 Listing Code Engine applications..."
	@ibmcloud ce application list

.PHONY: ibmcloud-tag
ibmcloud-tag:
	@echo "🏷️  Tagging image $(IBMCLOUD_IMG_PROD) → $(IBMCLOUD_IMAGE_NAME)"
	podman tag $(IBMCLOUD_IMG_PROD) $(IBMCLOUD_IMAGE_NAME)
	podman images | head -3

.PHONY: ibmcloud-push
ibmcloud-push:
	@echo "📤 Logging into IBM Container Registry and pushing image..."
	@ibmcloud cr login
	podman push $(IBMCLOUD_IMAGE_NAME)

.PHONY: ibmcloud-deploy
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

.PHONY: ibmcloud-ce-logs
ibmcloud-ce-logs:
	@echo "📜 Streaming logs for '$(IBMCLOUD_CODE_ENGINE_APP)'..."
	@ibmcloud ce application logs --name $(IBMCLOUD_CODE_ENGINE_APP) --follow

.PHONY: ibmcloud-ce-status
ibmcloud-ce-status:
	@echo "📈 Application status for '$(IBMCLOUD_CODE_ENGINE_APP)'..."
	@ibmcloud ce application get --name $(IBMCLOUD_CODE_ENGINE_APP)

.PHONY: ibmcloud-ce-rm
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
#   remote registry (e.g. ghcr.io/ibm/mcp-context-forge:v0.9.0).
TAG              ?= latest         # override with TAG=<ver>
IMAGE            ?= $(IMAGE_LOCAL) # or IMAGE=ghcr.io/ibm/mcp-context-forge:$(TAG)

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
.PHONY: minikube-tunnel
minikube-tunnel:
	@echo "🌐 Starting minikube tunnel (Ctrl+C to quit) ..."
	minikube -p $(MINIKUBE_PROFILE) tunnel

.PHONY: minikube-port-forward
minikube-port-forward:
	@echo "🔌 Forwarding http://localhost:8080 → svc/mcp-stack-mcpgateway:80 in namespace mcp-private  (Ctrl+C to stop)..."
	kubectl port-forward -n mcp-private svc/mcp-stack-mcpgateway 8080:80

.PHONY: minikube-dashboard
minikube-dashboard:
	@echo "📊 Fetching dashboard URL ..."
	@minikube dashboard -p $(MINIKUBE_PROFILE) --url | { \
	  read url; \
	  echo "🔗 Dashboard: $$url"; \
	  ( command -v xdg-open >/dev/null && xdg-open $$url >/dev/null 2>&1 ) || \
	  ( command -v open     >/dev/null && open $$url     >/dev/null 2>&1 ) || true; \
	}

.PHONY: minikube-context
minikube-context:
	@echo "🎯 Switching kubectl context to Minikube ..."
	kubectl config use-context $(MINIKUBE_PROFILE)

.PHONY: minikube-ssh
minikube-ssh:
	@echo "🔧 Connecting to Minikube VM (exit with Ctrl+D) ..."
	minikube ssh -p $(MINIKUBE_PROFILE)

# -----------------------------------------------------------------------------
# 📦  IMAGE & MANIFEST HANDLING
# -----------------------------------------------------------------------------
.PHONY: minikube-image-load
minikube-image-load:
	@echo "📦 Loading $(IMAGE) into Minikube ..."
	@if ! docker image inspect $(IMAGE) >/dev/null 2>&1; then \
	  echo "❌ $(IMAGE) not found locally. Build or pull it first."; exit 1; \
	fi
	minikube image load $(IMAGE) -p $(MINIKUBE_PROFILE)

.PHONY: minikube-k8s-apply
minikube-k8s-apply:
	@echo "🧩 Applying k8s manifests in ./k8s ..."
	@kubectl apply -f deployment/k8s/ --recursive

# -----------------------------------------------------------------------------
# 🔍  Utility: print the current registry URL (host-port) - works after cluster
#             + registry addon are up.
# -----------------------------------------------------------------------------
.PHONY: minikube-registry-url
minikube-registry-url:
	@echo "📦 Internal registry URL:" && \
	minikube -p $(MINIKUBE_PROFILE) service registry -n kube-system --url || \
	echo "⚠️  Registry addon not ready - run make minikube-start first."

# -----------------------------------------------------------------------------
# 📊  INSPECTION & RESET
# -----------------------------------------------------------------------------
.PHONY: minikube-status
minikube-status:
	@echo "📊 Minikube cluster status:" && minikube status -p $(MINIKUBE_PROFILE)
	@echo "\n📦 Addon status:" && minikube addons list | grep -E "$(subst $(space),|,$(MINIKUBE_ADDONS))"
	@echo "\n🚦 Ingress controller:" && kubectl get pods -n ingress-nginx -o wide || true
	@echo "\n🔍 Dashboard:" && kubectl get pods -n kubernetes-dashboard -o wide || true
	@echo "\n🧩 Services:" && kubectl get svc || true
	@echo "\n🌐 Ingress:" && kubectl get ingress || true

.PHONY: minikube-reset
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
	  echo "❌ Refusing to install Helm via curl | bash."; \
	  echo "💡 Install Helm from a trusted package manager or pinned release:"; \
	  echo "   https://helm.sh/docs/intro/install/"; \
	  exit 1; \
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

.PHONY: argocd-login
argocd-login: argocd-cli-install
	@echo "🔐 Logging into Argo CD CLI..."
	@PASS=$$(kubectl -n $(ARGOCD_NS) get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d); \
	argocd login localhost:$(ARGOCD_PORT) --username admin --password $$PASS --insecure

.PHONY: argocd-app-bootstrap
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

.PHONY: argocd-app-sync
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
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install 'pypiserver>=2.3.0' passlib"
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

.PHONY: local-pypi-upload-auth
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

.PHONY: local-pypi-test
local-pypi-test:
	@echo "📥  Installing from local PyPI..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	$(UV_BIN) pip install --index-url $(LOCAL_PYPI_URL)/simple/ \
	            --extra-index-url https://pypi.org/simple/ \
	            --reinstall $(PROJECT_NAME)"
	@echo "✅  Installed from local PyPI"

.PHONY: local-pypi-clean
local-pypi-clean: clean dist local-pypi-start-auth local-pypi-upload-auth local-pypi-test
	@echo "🎉  Full local PyPI cycle complete!"
	@echo "📊  Package info:"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip show $(PROJECT_NAME)"

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
	$(UV_BIN) pip install devpi-server devpi-client devpi-web"
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

.PHONY: devpi-test
devpi-test:
	@echo "📥  Installing package mcp-contextforge-gateway from devpi..."
	@if ! curl -s $(DEVPI_URL) >/dev/null 2>&1; then \
		echo "❌  DevPi server not running. Run 'make devpi-start' first."; \
		exit 1; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	$(UV_BIN) pip install --index-url $(DEVPI_URL)/$(DEVPI_INDEX)/+simple/ \
	            --extra-index-url https://pypi.org/simple/ \
	            --reinstall mcp-contextforge-gateway"
	@echo "✅  Installed mcp-contextforge-gateway from devpi"

.PHONY: devpi-clean
devpi-clean: clean dist devpi-upload devpi-test
	@echo "🎉  Full devpi cycle complete!"
	@echo "📊  Package info:"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip show mcp-contextforge-gateway"

.PHONY: devpi-status
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

.PHONY: devpi-web
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
#      override on the CLI:  make VER=0.9.0 devpi-delete
# ─────────────────────────────────────────────────────────────────────────────
VER ?= $(shell python3 -c "import tomllib, pathlib; \
print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])" \
2>/dev/null || echo 0.0.0)

.PHONY: devpi-delete
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
	  /bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install -q bashate" ; \
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
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install -q alembic sqlalchemy"

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
# help: test-ui-headless-parallel - Run Playwright UI tests headless in parallel (pytest-xdist)
# help: test-ui-debug        - Run Playwright UI tests with Playwright Inspector
# help: test-ui-smoke        - Run Playwright UI smoke tests only (fast subset)
# help: test-ui-ci-smoke     - Run stable Playwright CI smoke subset (headless, serve-compatible)
# help: test-ui-parallel     - Run Playwright UI tests in parallel using pytest-xdist
# help: test-ui-report       - Run Playwright UI tests and generate HTML report
# help: test-ui-coverage     - Run Playwright UI tests with coverage for admin endpoints
# help: test-ui-screenshots  - Run Playwright UI tests with always-on screenshots (headless)
# help: test-ui-record       - Run Playwright UI tests and record videos + screenshots (headless)
# help: test-ui-update-snapshots - Update Playwright visual regression snapshots
# help: test-ui-clean        - Clean up Playwright test artifacts
# help: test-owasp           - Run OWASP access-control security tests (no ZAP required)
# help: test-zap             - Run ZAP DAST security scan (requires ZAP daemon; set ZAP_BASE_URL)

.PHONY: playwright-install playwright-install-all playwright-preflight test-ui test-ui-headless test-ui-headless-parallel test-ui-debug test-ui-smoke test-ui-ci-smoke test-ui-parallel test-ui-report test-ui-coverage test-ui-screenshots test-ui-record test-ui-update-snapshots test-ui-clean test-zap test-owasp

# Playwright test variables
PLAYWRIGHT_DIR := tests/playwright
PLAYWRIGHT_REPORTS := $(PLAYWRIGHT_DIR)/reports
PLAYWRIGHT_SCREENSHOTS := $(PLAYWRIGHT_DIR)/screenshots
PLAYWRIGHT_VIDEOS := $(PLAYWRIGHT_DIR)/videos
PLAYWRIGHT_SLOWMO ?= 750
TEST_BASE_URL ?= http://localhost:8080
ZAP_BASE_URL   ?= http://localhost:8090
ZAP_API_KEY    ?= changeme
# URL ZAP uses internally to spider the app. nginx exposes port 80 on mcpnet
# (host sees it as 8080 via port mapping), so ZAP inside Docker must use port 80.
# Works on both Linux and macOS/Windows Docker Desktop.
# Override only if your setup differs (e.g. a standalone ZAP outside mcpnet).
ZAP_TARGET_URL ?= http://nginx:80
ZAP_REPORTS   := tests/reports
# Optional install flags for Playwright browser installation (e.g. --with-deps in Linux CI)
PLAYWRIGHT_INSTALL_FLAGS ?=
PLAYWRIGHT_CI_SMOKE_TESTS := \
	tests/playwright/test_admin_ui.py::TestAdminUI::test_admin_panel_loads \
	tests/playwright/test_admin_ui.py::TestAdminUI::test_navigate_between_tabs \
	tests/playwright/test_version_page.py::TestVersionPage::test_version_panel_loads \
	tests/playwright/test_mcp_registry_page.py::TestMCPRegistryPage::test_registry_panel_loads

# default path when FILE is not provided
PLAYWRIGHT_TEST_TARGET ?= tests/playwright/

# If FILE is set, use that instead of the whole folder
ifdef FILE
  PLAYWRIGHT_TEST_TARGET := $(FILE)
endif


## --- Playwright Setup -------------------------------------------------------
# Playwright + pytest-playwright + python-owasp-zap-v2.4 live in the `dev`
# dependency group, so `uv run` syncs them automatically. These targets only
# install the browser binaries (a separate step from the Python package).
playwright-install: uv
	@echo "🎭 Installing Playwright browsers (chromium)..."
	@$(UV_BIN) run playwright install $(PLAYWRIGHT_INSTALL_FLAGS) chromium
	@echo "✅ Playwright chromium browser installed!"

playwright-install-all: uv
	@echo "🎭 Installing all Playwright browsers..."
	@$(UV_BIN) run playwright install $(PLAYWRIGHT_INSTALL_FLAGS)
	@echo "✅ All Playwright browsers installed!"

playwright-preflight:
	@echo "🌐 Playwright base URL: $(TEST_BASE_URL)"
	@echo "💡 Default target is docker-compose.yml nginx on http://localhost:8080"
	@echo "   Start it with: make testing-up"
	@if ! curl -s "$(TEST_BASE_URL)/health" >/dev/null 2>&1; then \
		echo "❌ Gateway not responding at $(TEST_BASE_URL)"; \
		echo "💡 Start it with: make testing-up"; \
		echo "💡 Or override with: TEST_BASE_URL=http://localhost:8000 make test-ui"; \
		exit 1; \
	fi

## --- Playwright test macro ---------------------------------------------------
# Run a Playwright test variant via `uv run pytest`.
# $(1) = label (e.g., "headed", "headless parallel")
# $(2) = directories to mkdir -p (space-separated, or empty for none)
# $(3) = env var exports before pytest (e.g., "PWDEBUG=1", or empty)
# $(4) = pytest arguments (variant-specific part)
# $(5) = fail behavior: "fail" or "continue" (|| true)
#
# pytest-xdist and pytest-html no longer require an inline `uv pip install`
# (both live in the `dev` dependency group); `uv run` syncs them on demand.
#
# Two plugins are suppressed globally via `addopts` in pyproject.toml and only
# opted back in by the targets that need them:
#   * pytest-playwright (`-p no:playwright`) — its session fixtures pollute the
#     asyncio event loop and break unrelated async tests. UI targets re-enable
#     it with `-p playwright` (run_playwright_test below).
#   * pytest-benchmark (`-p no:benchmark`) — its single-process timing model
#     conflicts with pytest-xdist (`-n auto`/`-n N`) used by `make test` and
#     friends. The benchmarking targets (e.g. `migration-test-performance`)
#     re-enable it with `-p benchmark` and run without `-n`.
define run_playwright_test
	@echo "🎭 Running Playwright UI tests ($(1))..."
	@$(MAKE) --no-print-directory playwright-preflight
	$(if $(strip $(2)),@mkdir -p $(2),)
	@$(if $(strip $(3)),$(3),) TEST_BASE_URL='$(TEST_BASE_URL)' \
	 $(UV_BIN) run pytest -p playwright $(4) \
		--browser chromium \
		$(if $(filter fail,$(5)),|| { echo '❌ UI tests failed!'; exit 1; },|| true)
endef

## --- UI Test Execution ------------------------------------------------------
test-ui: uv playwright-install
	$(call run_playwright_test,headed,$(PLAYWRIGHT_SCREENSHOTS) $(PLAYWRIGHT_REPORTS),,\
		$(PLAYWRIGHT_TEST_TARGET) -v --headed --screenshot=only-on-failure,fail)
	@echo "✅ UI tests completed!"

test-ui-headless: uv playwright-install
	$(call run_playwright_test,headless,$(PLAYWRIGHT_SCREENSHOTS) $(PLAYWRIGHT_REPORTS),,\
		$(PLAYWRIGHT_TEST_TARGET) -v --screenshot=only-on-failure,fail)
	@echo "✅ UI tests completed!"

test-ui-headless-parallel: uv playwright-install
	$(call run_playwright_test,headless parallel,$(PLAYWRIGHT_SCREENSHOTS) $(PLAYWRIGHT_REPORTS),,\
		$(PLAYWRIGHT_TEST_TARGET) -v -n auto --dist loadscope --screenshot=only-on-failure,fail)
	@echo "✅ UI parallel tests completed!"

test-ui-debug: uv playwright-install
	$(call run_playwright_test,debug,$(PLAYWRIGHT_SCREENSHOTS) $(PLAYWRIGHT_REPORTS),PWDEBUG=1,\
		$(PLAYWRIGHT_TEST_TARGET) -v -s --headed,fail)

test-ui-smoke: uv playwright-install
	$(call run_playwright_test,smoke,,,\
		$(PLAYWRIGHT_DIR)/ -v -m smoke --headed,fail)
	@echo "✅ UI smoke tests passed!"

test-ui-ci-smoke: uv playwright-install
	$(call run_playwright_test,CI smoke,$(PLAYWRIGHT_REPORTS),,\
		-v --screenshot=only-on-failure $(PLAYWRIGHT_CI_SMOKE_TESTS),fail)
	@echo "✅ UI CI smoke tests passed!"

test-ui-parallel: uv playwright-install
	$(call run_playwright_test,parallel,,,\
		$(PLAYWRIGHT_DIR)/ -v -n auto --dist loadscope,fail)
	@echo "✅ UI parallel tests completed!"

## --- UI Test Reporting ------------------------------------------------------
test-ui-report: uv playwright-install
	$(call run_playwright_test,report,$(PLAYWRIGHT_REPORTS),,\
		$(PLAYWRIGHT_DIR)/ -v --screenshot=only-on-failure --html=$(PLAYWRIGHT_REPORTS)/report.html --self-contained-html,continue)
	@echo "✅ UI test report generated: $(PLAYWRIGHT_REPORTS)/report.html"
	@echo "   Open with: open $(PLAYWRIGHT_REPORTS)/report.html"

test-ui-coverage: uv playwright-install
	$(call run_playwright_test,coverage,$(PLAYWRIGHT_REPORTS),,\
		$(PLAYWRIGHT_DIR)/ -v --cov=mcpgateway.admin --cov-report=html:$(PLAYWRIGHT_REPORTS)/coverage --cov-report=term,continue)
	@echo "✅ UI coverage report: $(PLAYWRIGHT_REPORTS)/coverage/index.html"

test-ui-screenshots: uv playwright-install
	$(call run_playwright_test,screenshots,$(PLAYWRIGHT_REPORTS),,\
		$(PLAYWRIGHT_DIR)/ -v --screenshot=on,fail)
	@echo "✅ Playwright screenshots captured"
	@echo "📁 Artifacts saved to: test-results/"

test-ui-record: uv playwright-install
	$(call run_playwright_test,record,$(PLAYWRIGHT_VIDEOS),,\
		$(PLAYWRIGHT_DIR)/ -v --video=on --screenshot=on --slowmo $(PLAYWRIGHT_SLOWMO),fail)
	@echo "✅ Playwright videos + screenshots saved"
	@echo "📁 Artifacts saved to: test-results/"

## --- UI Test Utilities ------------------------------------------------------
test-ui-update-snapshots: uv playwright-install
	$(call run_playwright_test,update-snapshots,,,\
		$(PLAYWRIGHT_DIR)/ -v --update-snapshots,fail)
	@echo "✅ Snapshots updated!"

test-ui-clean:
	@echo "🧹 Cleaning Playwright test artifacts..."
	@rm -rf $(PLAYWRIGHT_SCREENSHOTS)/*.png
	@rm -rf $(PLAYWRIGHT_VIDEOS)/*.webm
	@rm -rf $(PLAYWRIGHT_REPORTS)/*
	@rm -rf test-results/
	@rm -f playwright-report-*.html test-results-*.xml
	@echo "✅ Playwright artifacts cleaned!"

## --- OWASP / ZAP Security Testing ------------------------------------------
test-owasp: uv playwright-install  ## 🔒 Run OWASP access-control security tests (no ZAP required)
	@echo "🔒 Running OWASP access-control security tests..."
	@$(MAKE) --no-print-directory playwright-preflight
	@mkdir -p $(ZAP_REPORTS)
	@TEST_BASE_URL='$(TEST_BASE_URL)' \
	 $(UV_BIN) run pytest -p playwright tests/playwright/security/owasp/ \
		-v -m owasp_a01 --tb=short \
		|| { echo '❌ OWASP security tests failed!'; exit 1; }
	@echo "✅ OWASP security tests completed!"

test-zap: uv playwright-install  ## 🔒 Run ZAP DAST security scan (requires ZAP daemon; set ZAP_BASE_URL)
	@echo "🔒 Running ZAP DAST security scan against $(TEST_BASE_URL)..."
	@if [ -z "$(ZAP_BASE_URL)" ]; then \
		echo "❌ ZAP_BASE_URL is not set. Start the testing stack with: make testing-up"; \
		exit 1; \
	fi
	@$(MAKE) --no-print-directory playwright-preflight
	@mkdir -p $(ZAP_REPORTS)
	@TEST_BASE_URL='$(TEST_BASE_URL)' \
	 ZAP_BASE_URL='$(ZAP_BASE_URL)' \
	 ZAP_API_KEY='$(ZAP_API_KEY)' \
	 ZAP_TARGET_URL='$(ZAP_TARGET_URL)' \
	 $(UV_BIN) run pytest -p playwright tests/playwright/security/owasp/ \
		-v -m owasp_a01_zap --tb=short \
		|| { echo '❌ ZAP DAST scan failed!'; exit 1; }
	@echo "✅ ZAP DAST scan completed! Reports in $(ZAP_REPORTS)/"

## --- Combined Testing -------------------------------------------------------
test-all: test test-js test-ui-headless
	@echo "✅ All tests completed (Python + JavaScript + UI)!"

# Add UI tests to your existing test suite if needed
test-full: coverage test-js test-ui-report
	@echo "📊 Full test suite completed with coverage, JavaScript and UI tests!"


# =============================================================================
# 🔒 SECURITY TOOLS
# =============================================================================
# help: 🔒 SECURITY TOOLS
# help: security-all        - Run all security tools (semgrep, dodgy, detect-secrets-scan, etc.)
# help: security-report     - Generate comprehensive security report in docs/security/
# help: security-fix        - Auto-fix security issues where possible (pyupgrade, etc.)
# help: semgrep             - Static analysis for security patterns
# help: dodgy               - Check for suspicious code patterns (passwords, keys)

# help: pyupgrade           - Upgrade Python syntax to newer versions
# help: interrogate         - Check docstring coverage
# help: prospector          - Comprehensive Python code analysis
# help: pip-audit           - Audit Python dependencies for published CVEs
# help: detect-secrets-scan    - detect-secrets scan for secrets in repository using baseline file .secrets.baseline
# help: detect-secrets-audit   - detect-secrets audit for unverified secrets detected in baseline file .secrets.baseline
# help: devskim-install-dotnet - Install .NET SDK and DevSkim CLI (security patterns scanner)
# help: sri-generate        - Generate SRI hashes for CDN resources
# help: sri-verify          - Verify SRI hashes match current CDN content
# help: devskim             - Run DevSkim static analysis for security anti-patterns

# List of security tools to run with security-all
SECURITY_TOOLS := semgrep dodgy detect-secrets-scan interrogate prospector pip-audit devskim sri-verify

.PHONY: security-all security-report security-fix $(SECURITY_TOOLS) pyupgrade devskim-install-dotnet devskim sri-generate sri-verify

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
	@echo "✅  Security scan complete!"

## --------------------------------------------------------------------------- ##
##  Individual security tools
## --------------------------------------------------------------------------- ##
semgrep:                            ## 🔍 Security patterns & anti-patterns
	@echo "🔍  semgrep - scanning for security patterns..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	# Notice the use of uvx below -- semgrep is not in the project dependencies because it introduces a
	# resolution conflict with other packages.
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		uvx semgrep --config=auto $(TARGET) \
			--exclude-rule python.lang.compatibility.python37.python37-compatibility-importlib2 \
			|| true"

dodgy:                              ## 🔐 Suspicious code patterns
	@echo "🔐  dodgy - scanning for hardcoded secrets..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q dodgy && \
		$(VENV_DIR)/bin/dodgy $(TARGET) || true"


pyupgrade:                          ## ⬆️  Upgrade Python syntax
	@echo "⬆️  pyupgrade - checking for syntax upgrade opportunities..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q pyupgrade && \
		find $(TARGET) -name '*.py' -exec $(VENV_DIR)/bin/pyupgrade --py312-plus --diff {} + || true"
	@echo "💡  To apply changes, run: find $(TARGET) -name '*.py' -exec $(VENV_DIR)/bin/pyupgrade --py312-plus {} +"

interrogate: uv                     ## 📝 Docstring coverage
	@echo "📝  interrogate - checking docstring coverage..."
	@$(UV_BIN) tool run interrogate==$(INTERROGATE_VERSION) -vv mcpgateway || true

prospector:                         ## 🔬 Comprehensive code analysis
	@echo "🔬  prospector - running comprehensive analysis..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q prospector[with_everything] && \
		$(VENV_DIR)/bin/prospector mcpgateway || true"

pip-audit:                          ## 🔒 Audit Python dependencies for CVEs
	@echo "🔒  pip-audit vulnerability scan..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q pip-audit && \
		pip-audit --strict || true"



# =============================================================================
# 🔄 ASYNC CODE TESTING & PERFORMANCE PROFILING
# =============================================================================
# help: 🔄 ASYNC CODE TESTING & PERFORMANCE PROFILING
# help: async-test           - Run comprehensive async safety tests with debug mode
# help: async-lint           - Run async-aware linting (ruff, mypy with coroutine warnings)
# help: async-monitor        - Start aiomonitor for live async debugging (WebUI + console)
# help: async-debug          - Run async tests with PYTHONASYNCIODEBUG=1 and debug mode
# help: async-benchmark      - Run async performance benchmarks and generate reports
# help: async-validate       - Validate async code patterns and generate validation report
# help: async-clean          - Clean async testing artifacts and kill background processes
# help: profile              - Generate async performance profiles and start SnakeViz server
# help: profile-serve        - Start SnakeViz profile server on localhost:8080
# help: profile-compare      - Compare performance profiles between baseline and current

.PHONY: async-test async-lint profile async-monitor async-debug profile-serve

ASYNC_TEST_DIR := tests/async
PROFILE_DIR := $(ASYNC_TEST_DIR)/profiles
REPORTS_DIR := $(ASYNC_TEST_DIR)/reports
VENV_PYTHON := $(VENV_DIR)/bin/python

async-test: uv async-lint async-debug
	@echo "🔄 Running comprehensive async safety tests..."
	@mkdir -p $(REPORTS_DIR)
	@PYTHONASYNCIODEBUG=1 \
	 $(UV_BIN) run --extra plugins pytest \
		tests/ \
		--asyncio-mode=auto \
		--tb=short \
		--junitxml=$(REPORTS_DIR)/async-test-results.xml \
		-v

async-lint: uv
	@echo "🔍 Running async-aware linting..."
	@$(UV_BIN) tool run ruff==$(RUFF_VERSION) check mcpgateway/ tests/ \
		--select=F,E,B,ASYNC \
		--output-format=github
	@$(VENV_DIR)/bin/mypy mcpgateway/ \
		--warn-unused-coroutine \
		--strict

profile:
	@echo "📊 Generating async performance profiles..."
	@mkdir -p $(PROFILE_DIR)
	@$(VENV_PYTHON) $(ASYNC_TEST_DIR)/profiler.py \
		--scenarios websocket,database,mcp_calls \
		--output $(PROFILE_DIR) \
		--duration 60
	@echo "🌐 Starting SnakeViz server..."
	@$(VENV_DIR)/bin/snakeviz $(PROFILE_DIR)/combined_profile.prof \
		--server --port 8080

profile-serve:
	@echo "🌐 Starting SnakeViz profile server..."
	@$(VENV_DIR)/bin/snakeviz $(PROFILE_DIR) \
		--server --port 8080 --hostname 0.0.0.0

async-monitor:
	@echo "👁️  Starting aiomonitor for live async debugging..."
	@$(VENV_PYTHON) $(ASYNC_TEST_DIR)/monitor_runner.py \
		--webui_port 50101 \
		--console_port 50102 \
		--host localhost \
		--console-enabled

async-debug: uv
	@echo "🐛 Running async tests with debug mode..."
	@PYTHONASYNCIODEBUG=1 $(UV_BIN) run --extra plugins python -X dev \
		-m pytest tests/ \
		--asyncio-mode=auto \
		--capture=no \
		-v

.PHONY: async-benchmark
async-benchmark:
	@echo "⚡ Running async performance benchmarks..."
	@$(VENV_PYTHON) $(ASYNC_TEST_DIR)/benchmarks.py \
		--output $(REPORTS_DIR)/benchmark-results.json \
		--iterations 1000

.PHONY: profile-compare
profile-compare:
	@echo "📈 Comparing performance profiles..."
	@$(VENV_PYTHON) $(ASYNC_TEST_DIR)/profile_compare.py \
		--baseline $(PROFILE_DIR)/combined_profile.prof \
		--current $(PROFILE_DIR)/mcp_calls_profile.prof \
		--output $(REPORTS_DIR)/profile-comparison.json

.PHONY: async-validate
async-validate:
	@echo "✅ Validating async code patterns..."
	@$(VENV_PYTHON) $(ASYNC_TEST_DIR)/async_validator.py \
		--source mcpgateway/ \
		--report $(REPORTS_DIR)/async-validation.json

.PHONY: async-clean
async-clean:
	@echo "🧹 Cleaning async testing artifacts..."
	@rm -rf $(PROFILE_DIR)/* $(REPORTS_DIR)/*
	@pkill -f "aiomonitor" || true
	@pkill -f "snakeviz" || true

# Exclude pattern for detect-secrets to skip common directories and auto generated files.
# Uses Python verbose-regex mode (?x) so each alternative can be commented.
# Backslash line continuations collapse the value to one line with interleaved
# spaces — harmless under (?x).
DETECT_SECRETS_FILES_EXCLUDE := '(?x)( \
  package-lock\.json$$         \
  |Cargo\.lock$$               \
  |uv\.lock$$                  \
  |go\.sum$$                   \
  |mcpgateway/sri_hashes\.json$$ \
)'

.PHONY: detect-secrets-scan
detect-secrets-scan: uv                      ## 🔍  detect-secrets scan for secrets in repository
	@echo "🔍 Running detect-secrets scan..."
	@$(UV_BIN) tool run --from '$(DETECT_SECRETS_SPEC)' detect-secrets scan \
		--update .secrets.baseline \
		--use-all-plugins \
		--exclude-files $(DETECT_SECRETS_FILES_EXCLUDE)
	@echo "📊 detect-secrets findings report:"
	@$(UV_BIN) tool run --from '$(DETECT_SECRETS_SPEC)' detect-secrets audit --report .secrets.baseline

.PHONY: detect-secrets-audit
detect-secrets-audit: uv                     ## 🔎  detect-secrets audit for reviewing findings
	@echo "🔎 Running detect-secrets audit..."
	@$(UV_BIN) tool run --from '$(DETECT_SECRETS_SPEC)' detect-secrets audit .secrets.baseline

.PHONY: detect-secrets-hook
detect-secrets-hook: uv                      ## 🔎  detect-secrets pre-commit hook equivalent
	@echo "🔎 Running detect-secrets-hook pre-commit hook equivalent..."
	@$(UV_BIN) tool run --from '$(DETECT_SECRETS_SPEC)' detect-secrets-hook \
		--baseline .secrets.baseline \
		--use-all-plugins \
		--fail-on-unaudited

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
		export DOTNET_ROLL_FORWARD=Major && \
		if [ -z "$$DOTNET_ROOT" ] && [ -d /opt/homebrew/opt/dotnet/libexec ]; then \
			export DOTNET_ROOT=/opt/homebrew/opt/dotnet/libexec; \
		fi && \
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
##  SRI (Subresource Integrity) Management
## --------------------------------------------------------------------------- ##

.PHONY: sri-generate sri-verify

sri-generate:                       ## 🔐 Generate SRI hashes for CDN resources
	@echo "🔐 Generating SRI hashes for CDN resources..."
	@python3 scripts/generate-sri-hashes.py

sri-verify:                         ## ✅ Verify SRI hashes match current CDN content
	@python3 scripts/verify-sri-hashes.py

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
		$(UV_BIN) pip install -q semgrep && \
		$(VENV_DIR)/bin/semgrep --config=auto $(TARGET) --quiet || true" >> $(DOCS_DIR)/docs/security/report.md 2>&1
	@echo "" >> $(DOCS_DIR)/docs/security/report.md
	@echo "## Suspicious Code Patterns (dodgy)" >> $(DOCS_DIR)/docs/security/report.md
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip install -q dodgy && \
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
		$(UV_BIN) pip install -q pyupgrade && \
		find $(TARGET) -name '*.py' -exec $(VENV_DIR)/bin/pyupgrade --py312-plus {} +"
	@echo "➤ Updating dependencies to latest secure versions..."
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		$(UV_BIN) pip list --outdated"
	@echo "✅ Auto-fixes applied where possible"
	@echo "⚠️  Manual review still required for:"
	@echo "   - Dependency updates (run 'make update')"
	@echo "   - Secrets in code (review dodgy/detect-secrets output)"
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
	@if [ -f "Dockerfile" ] || [ -f "Containerfile" ] || [ -f "Containerfile.lite" ]; then \
		echo "📦 Testing Dockerfile/Containerfile..."; \
		snyk iac test $(CONTAINER_FILE) \
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

.PHONY: check-headers-debug
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

.PHONY: fix-all-headers-no-encoding
fix-all-headers-no-encoding:        ## 🔧 Fix headers without encoding line requirement
	@echo "🔧 Fixing headers without encoding line requirement..."
	@python3 .github/tools/fix_file_headers.py --fix-all --no-encoding

.PHONY: fix-all-headers-custom
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
.PHONY: pre-commit-check-headers
pre-commit-check-headers:           ## 🪝 Check headers for pre-commit hooks
	@echo "🪝 Checking headers for pre-commit..."
	@python3 .github/tools/fix_file_headers.py --check

.PHONY: pre-commit-fix-headers
pre-commit-fix-headers:             ## 🪝 Fix headers for pre-commit hooks
	@echo "🪝 Fixing headers for pre-commit..."
	@python3 .github/tools/fix_file_headers.py --fix-all

# ==============================================================================
# 🎯 FUZZ TESTING - Automated property-based and security testing
# ==============================================================================
# help: 🎯 FUZZ TESTING - Automated property-based and security testing
# help: fuzz-install       - Install fuzzing dependencies (hypothesis, schemathesis, etc.)
# help: fuzz-all           - Run complete fuzzing suite (hypothesis + atheris + api + security)
# help: fuzz-hypothesis    - Run Hypothesis property-based tests for core validation
# help: fuzz-atheris       - Run Atheris coverage-guided fuzzing (requires clang/libfuzzer)
# help: fuzz-api           - Run Schemathesis API fuzzing (requires running server)
# help: fuzz-restler       - Run RESTler API fuzzing instructions (stateful sequences)
# help: fuzz-restler-auto  - Run RESTler via Docker automatically (requires Docker + server)
# help: fuzz-security      - Run security-focused vulnerability tests (SQL injection, XSS, etc.)
# help: fuzz-quick         - Run quick fuzzing for CI/PR validation (50 examples)
# help: fuzz-extended      - Run extended fuzzing for nightly testing (1000+ examples)
# help: fuzz-report        - Generate comprehensive fuzzing reports (JSON + Markdown)
# help: fuzz-clean         - Clean fuzzing artifacts and generated reports

.PHONY: fuzz-install
fuzz-install: uv  ## 🔧 Sync project env (fuzz tooling now lives in the dev dependency group)
	@echo "🔧 Syncing project environment for fuzzing..."
	@$(UV_BIN) sync
	@echo "✅ Fuzzing tools available (hypothesis / pytest-benchmark / schemathesis from dev group; atheris layered ad-hoc by 'make fuzz-atheris')"

.PHONY: fuzz-hypothesis
fuzz-hypothesis: uv  ## 🧪 Run Hypothesis property-based tests
	@echo "🧪 Running Hypothesis property-based tests..."
	@$(UV_BIN) run pytest tests/fuzz/ -v \
		--hypothesis-show-statistics \
		--hypothesis-profile=dev \
		-k 'not (test_sql_injection or test_xss_prevention or test_integer_overflow or test_rate_limiting)' \
		|| true

ATHERIS_RUNS         ?= 10000
ATHERIS_TIME_BUDGET  ?= 300
ATHERIS_FUZZERS      := tests/fuzz/fuzzers/fuzz_jsonpath.py \
                         tests/fuzz/fuzzers/fuzz_jsonrpc.py \
                         tests/fuzz/fuzzers/fuzz_config_parser.py

.PHONY: fuzz-atheris
fuzz-atheris: uv  ## 🎭 Run Atheris coverage-guided fuzzing (Linux: prebuilt wheel; macOS arm64: needs `brew install llvm`)
	@echo "🎭 Running Atheris coverage-guided fuzzing..."
	@echo "   Runs: $(ATHERIS_RUNS), max wall time: $(ATHERIS_TIME_BUDGET)s per fuzzer"
	@mkdir -p corpus tests/fuzz/fuzzers/results reports
	@for script in $(ATHERIS_FUZZERS); do \
		echo "  → $$script"; \
		$(UV_BIN) run --with 'atheris>=3.0.0' python "$$script" \
			-runs=$(ATHERIS_RUNS) -max_total_time=$(ATHERIS_TIME_BUDGET) \
			|| echo "  ⚠️  $$script returned non-zero (continuing)"; \
	done
	@echo "✅ Atheris fuzzing complete"

.PHONY: fuzz-api
fuzz-api:                           ## 🌐 Run Schemathesis API fuzzing
	@echo "🌐 Running Schemathesis API fuzzing..."
	@echo "⚠️  API fuzzing requires running server - skipping automated server start"
	@echo "💡 To run manually:"
	@echo "   1. make dev (in separate terminal)"
	@echo "   2. source $(VENV_DIR)/bin/activate && schemathesis run http://localhost:4444/openapi.json --checks all --auth admin:changeme"
	@mkdir -p reports
	@echo "✅ API fuzzing setup completed"

.PHONY: fuzz-restler
fuzz-restler:                       ## 🧪 Run RESTler API fuzzing (instructions)
	@echo "🧪 Running RESTler API fuzzing (via Docker or local install)..."
	@echo "⚠️  RESTler is not installed by default; using instructions only"
	@mkdir -p reports/restler
	@echo "💡 To run with Docker (recommended):"
	@echo "   1) make dev   # in another terminal"
	@echo "   2) curl -sSf http://localhost:4444/openapi.json -o reports/restler/openapi.json"
	@echo "   3) docker run --rm -v $$PWD/reports/restler:/workspace ghcr.io/microsoft/restler restler compile --api_spec /workspace/openapi.json"
	@echo "   4) docker run --rm -v $$PWD/reports/restler:/workspace ghcr.io/microsoft/restler restler test --grammar_dir /workspace/Compile --no_ssl --time_budget 5"
	@echo "      # Artifacts will be under reports/restler"
	@echo "💡 To run with local install (RESTLER_HOME):"
	@echo "   export RESTLER_HOME=/path/to/restler && \\"
	@echo "   $$RESTLER_HOME/restler compile --api_spec reports/restler/openapi.json && \\"
	@echo "   $$RESTLER_HOME/restler test --grammar_dir Compile --no_ssl --time_budget 5"
	@echo "✅ RESTler instructions emitted"

.PHONY: fuzz-restler-auto
fuzz-restler-auto: uv  ## 🤖 Run RESTler via Docker automatically (server must be running)
	@echo "🤖 Running RESTler via Docker against a running server..."
	@if ! command -v docker >/dev/null 2>&1; then \
		echo "🐳 Docker not found; skipping RESTler fuzzing (fuzz-restler-auto)."; \
		echo "   Hint: Install Docker or use 'make fuzz-restler' for manual steps."; \
		exit 0; \
	fi
	@$(UV_BIN) run python tests/fuzz/scripts/run_restler_docker.py

.PHONY: fuzz-security
fuzz-security: uv  ## 🔐 Run security-focused fuzzing tests
	@echo "🔐 Running security-focused fuzzing tests..."
	@echo "⚠️  Security tests require running application with auth - they may fail in isolation"
	@HYPOTHESIS_PROFILE=dev \
	 $(UV_BIN) run pytest tests/fuzz/test_security_fuzz.py -v \
		|| true

.PHONY: fuzz-quick
fuzz-quick: uv  ## ⚡ Run quick fuzzing for CI
	@echo "⚡ Running quick fuzzing for CI..."
	@HYPOTHESIS_PROFILE=ci \
	 $(UV_BIN) run pytest tests/fuzz/ -v \
		-k 'not (test_very_large or test_sql_injection or test_xss_prevention or test_integer_overflow or test_rate_limiting)' \
		|| true

.PHONY: fuzz-extended
fuzz-extended: uv  ## 🕐 Run extended fuzzing for nightly runs
	@echo "🕐 Running extended fuzzing suite..."
	@HYPOTHESIS_PROFILE=thorough \
	 $(UV_BIN) run pytest tests/fuzz/ -v \
		--durations=20 || true

.PHONY: fuzz-report
fuzz-report: uv  ## 📊 Generate fuzzing report
	@echo "📊 Generating fuzzing report..."
	@mkdir -p reports
	@$(UV_BIN) run python tests/fuzz/scripts/generate_fuzz_report.py

.PHONY: fuzz-clean
fuzz-clean:                         ## 🧹 Clean fuzzing artifacts
	@echo "🧹 Cleaning fuzzing artifacts..."
	@rm -rf corpus/ tests/fuzz/fuzzers/results/ reports/schemathesis-report.json
	@rm -f reports/fuzz-report.json

.PHONY: fuzz-all
fuzz-all: fuzz-hypothesis fuzz-atheris fuzz-api fuzz-security fuzz-report  ## 🎯 Run complete fuzzing suite
	@echo "🎯 Complete fuzzing suite finished"

# =============================================================================
# 🔄 MIGRATION TESTING
# =============================================================================
# help: 🔄 MIGRATION TESTING
# help: migration-test-all       - Run comprehensive migration test suite (SQLite + PostgreSQL)
# help: migration-test-sqlite    - Run SQLite container migration tests only
# help: migration-test-postgres  - Run PostgreSQL compose migration tests only
# help: migration-test-performance - Run migration performance benchmarking
# help: migration-test-rollback  - Run only downgrade/reverse migration tests (pytest + roundtrip)
# help: migration-test-cross-db  - Run cross-database schema consistency test
# help: migration-setup          - Setup migration test environment
# help: migration-cleanup        - Clean up migration test containers and volumes
# help: migration-debug          - Debug migration test failures with diagnostic info
# help: migration-status         - Show current version configuration and supported versions
# help: upgrade-validate         - Validate fresh + upgrade + roundtrip DB paths (SQLite + PostgreSQL)

# Migration testing configuration
MIGRATION_TEST_DIR := tests/migration
MIGRATION_REPORTS_DIR := $(MIGRATION_TEST_DIR)/reports
UPGRADE_BASE_IMAGE ?= ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
UPGRADE_TARGET_IMAGE ?= mcpgateway/mcpgateway:latest

# Get supported versions from version config (n-2 policy)
MIGRATION_VERSIONS := $(shell cd $(MIGRATION_TEST_DIR) && python3 -c "from version_config import get_supported_versions; print(' '.join(get_supported_versions()))" 2>/dev/null || echo "0.5.0 0.8.0 0.9.0 latest")

.PHONY: migration-test-all migration-test-sqlite migration-test-postgres migration-test-performance \
        migration-test-rollback migration-test-cross-db migration-setup migration-cleanup migration-debug migration-status upgrade-validate

migration-test-all: uv migration-setup        ## Run comprehensive migration test suite (SQLite + PostgreSQL)
	@echo "🚀 Running comprehensive migration tests..."
	@echo "📋 Testing SQLite migrations..."
	@$(UV_BIN) run pytest $(MIGRATION_TEST_DIR)/test_docker_sqlite_migrations.py \
		-v --tb=short --maxfail=3 \
		--log-cli-level=INFO --log-cli-format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
	@echo ""
	@echo "📋 Testing PostgreSQL migrations..."
	@$(UV_BIN) run pytest $(MIGRATION_TEST_DIR)/test_compose_postgres_migrations.py \
		-v --tb=short --maxfail=3 \
		--log-cli-level=INFO --log-cli-format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
	@echo ""
	@echo "📊 Generating migration test report..."
	@$(UV_BIN) run python -c 'from tests.migration.utils.reporting import MigrationReportGenerator; \
		r = MigrationReportGenerator(); r.generate_summary_report()'
	@echo "✅ Migration tests complete! Reports in $(MIGRATION_REPORTS_DIR)/"

migration-test-sqlite: uv                     ## Run SQLite container migration tests only
	@echo "🐍 Running SQLite migration tests..."
	@$(UV_BIN) run pytest $(MIGRATION_TEST_DIR)/test_docker_sqlite_migrations.py \
		-v --tb=short --log-cli-level=INFO
	@echo "✅ SQLite migration tests complete!"

migration-test-postgres: uv                   ## Run PostgreSQL compose migration tests only
	@echo "🐘 Running PostgreSQL migration tests..."
	@$(UV_BIN) run pytest $(MIGRATION_TEST_DIR)/test_compose_postgres_migrations.py \
		-v --tb=short --log-cli-level=INFO
	@echo "✅ PostgreSQL migration tests complete!"

migration-test-performance: uv               ## Run migration performance benchmarking
	@echo "⚡ Running migration performance tests..."
	@# pytest-benchmark is suppressed globally (`-p no:benchmark` in pyproject.toml)
	@# because its measurement model conflicts with pytest-xdist's worker pool. This
	@# target is the canonical opt-in: `-p benchmark` re-enables the plugin and the
	@# absence of `-n` keeps execution single-process so timings stay meaningful.
	@$(UV_BIN) run pytest -p benchmark $(MIGRATION_TEST_DIR)/test_migration_performance.py \
		-v --tb=short --log-cli-level=INFO
	@echo "✅ Performance tests complete!"

migration-test-rollback: uv               ## Run only downgrade/reverse migration tests (pytest + roundtrip)
	@echo "⏪ Running reverse migration (downgrade) tests..."
	@$(UV_BIN) run pytest $(MIGRATION_TEST_DIR)/test_docker_sqlite_migrations.py \
	                     $(MIGRATION_TEST_DIR)/test_compose_postgres_migrations.py \
		-k 'reverse or rollback' \
		-v --tb=short --log-cli-level=INFO
	@echo "🔄 Running upgrade/downgrade roundtrip validation..."
	@BASE_IMAGE=$(UPGRADE_BASE_IMAGE) TARGET_IMAGE=$(UPGRADE_TARGET_IMAGE) bash scripts/ci/run_upgrade_validation.sh
	@echo "✅ Rollback tests complete!"

migration-test-cross-db: uv               ## Run cross-database schema consistency test
	@echo "🔀 Running cross-database schema consistency test..."
	@UPGRADE_TARGET_IMAGE=$(UPGRADE_TARGET_IMAGE) \
	 $(UV_BIN) run pytest $(MIGRATION_TEST_DIR)/test_cross_db_schema_consistency.py \
		-v --tb=short --log-cli-level=INFO
	@echo "✅ Cross-database schema consistency check complete!"

migration-setup:                          ## Setup migration test environment
	@echo "🔧 Setting up migration test environment..."
	@mkdir -p $(MIGRATION_REPORTS_DIR)
	@mkdir -p $(MIGRATION_TEST_DIR)/logs
	@echo "📦 Pulling required container images..."
	@if command -v docker >/dev/null 2>&1; then \
		for version in $(MIGRATION_VERSIONS); do \
			echo "  🔄 Pulling ghcr.io/ibm/mcp-context-forge:$$version..."; \
			docker pull ghcr.io/ibm/mcp-context-forge:$$version || true; \
		done; \
	else \
		echo "⚠️  Docker not available - tests may fail"; \
	fi
	@echo "✅ Migration test environment ready!"

.PHONY: migration-cleanup
migration-cleanup:                         ## Clean up migration test containers and volumes
	@echo "🧹 Cleaning up migration test environment..."
	@if command -v docker >/dev/null 2>&1; then \
		echo "🛑 Stopping migration test containers..."; \
		docker ps -a --filter "name=migration-test-" -q | xargs -r docker stop; \
		docker ps -a --filter "name=migration-test-" -q | xargs -r docker rm; \
		echo "🗑️  Removing migration test volumes..."; \
		docker volume ls --filter "name=migration-test-" -q | xargs -r docker volume rm; \
		echo "🧼 Pruning migration test networks..."; \
		docker network ls --filter "name=migration-test-" -q | xargs -r docker network rm; \
	fi
	@echo "🗂️  Cleaning up temporary files..."
	@rm -rf /tmp/migration_test_*
	@rm -rf $(MIGRATION_TEST_DIR)/logs/*.log
	@echo "✅ Migration test cleanup complete!"

.PHONY: migration-debug
migration-debug:                           ## Debug migration test failures with diagnostic info
	@echo "🔍 Migration test diagnostic information:"
	@echo ""
	@echo "📦 Container Runtime Info:"
	@if command -v docker >/dev/null 2>&1; then \
		echo "  Docker version: $$(docker --version)"; \
		echo "  Running containers:"; \
		docker ps --filter "name=migration-test-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"; \
		echo "  Available images:"; \
		docker images --filter "reference=ghcr.io/ibm/mcp-context-forge" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"; \
	else \
		echo "  ❌ Docker not available"; \
	fi
	@echo ""
	@echo "📁 Test Environment:"
	@echo "  Migration test dir: $(MIGRATION_TEST_DIR)"
	@echo "  Reports dir: $(MIGRATION_REPORTS_DIR)"
	@echo "  Virtual env: $(VENV_DIR)"
	@echo "  Logs: $$(find $(MIGRATION_TEST_DIR)/logs -name "*.log" 2>/dev/null | wc -l) log files"
	@echo ""
	@echo "🔧 Recent log entries:"
	@find $(MIGRATION_TEST_DIR)/logs -name "*.log" -type f -exec tail -n 5 {} + 2>/dev/null || echo "  No log files found"
	@echo "✅ Diagnostic complete!"

.PHONY: migration-status
migration-status:                          ## Show current version configuration and supported versions
	@echo "📊 Migration Test Version Configuration:"
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		cd $(MIGRATION_TEST_DIR) && python3 version_status.py"

.PHONY: upgrade-validate
upgrade-validate:                         ## Validate fresh + upgrade + roundtrip DB paths (SQLite + PostgreSQL)
	@echo "🔄 Running upgrade validation harness..."
	@echo "  Base image:   $(UPGRADE_BASE_IMAGE)"
	@echo "  Target image: $(UPGRADE_TARGET_IMAGE)"
	@BASE_IMAGE=$(UPGRADE_BASE_IMAGE) TARGET_IMAGE=$(UPGRADE_TARGET_IMAGE) bash scripts/ci/run_upgrade_validation.sh

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🦀 RUST
# =============================================================================
# 🦀 RUST (workspace: crates/*)
# =============================================================================
# help: 🦀 RUST
# help: -----------------------------------------------------------------------------
# help: Workspace-wide (all crates):
# help: rust-ensure-deps                      - Ensure Rust toolchain and maturin are available
# help: rust-build                            - Build Rust workspace (release)
# help: rust-build-check                      - Build workspace (debug) + verify maturin crates build
# help: rust-test                             - Run Rust workspace tests
# help: rust-format                           - Format Rust code (cargo fmt)
# help: rust-fmt-check                        - Check formatting (cargo fmt --check)
# help: rust-lint                             - Lint Rust code (cargo clippy)
# help: rust-check                            - Run all Rust checks (build, fmt, clippy, test)
# help: rust-doc                              - Build Rust documentation
# help: rust-vet                              - Run cargo vet (strict supply-chain auditing)
# help: rust-licenses                         - Run cargo-deny license check
# help: rust-coverage                         - Run coverage (terminal, HTML, Cobertura XML)
# help: rust-diff-cover                       - Run changed-line coverage for Rust
# help: rust-clean                            - Clean Rust build artifacts and uninstall maturin crates
# help: rust-bench-check                      - Verify benchmarks build (no run; for CI)
# help:
# help: Maturin (Python bindings, crates/* with pyproject.toml):
# help: rust-install                          - Install maturin crates into venv (release build)
# help: rust-dev                              - Install maturin crates in debug mode
# help: rust-stub-gen                         - Generate Python type stubs for maturin crates
# help: rust-verify-stubs                     - Verify stub files and pyproject.toml
# help: rust-verify                           - Verify maturin crate installation
# help: rust-clean-stubs                      - Remove generated stub files from maturin crates
# help: rust-uninstall-plugins                - Uninstall maturin crates from Python environment
# help: rust-build-wheels                     - Build Python wheels for maturin crates
# help:
# help: Runtime:
# help: rust-mcp-runtime-build                - Build the experimental Rust MCP runtime
# help: rust-mcp-runtime-test                 - Run tests for the experimental Rust MCP runtime
# help: rust-mcp-runtime-run                  - Run the experimental Rust MCP runtime against local gateway /rpc
# help: -----------------------------------------------------------------------------

.PHONY: rust-build rust-build-check rust-dev rust-test rust-format rust-fmt-check rust-lint rust-check rust-doc rust-clean rust-verify rust-verify-stubs rust-stub-gen rust-licenses rust-vet rust-deny rust-coverage rust-diff-cover rust-bench-check
.PHONY: rust-ensure-deps rust-install-deps rust-install-targets rust-install rust-build-wheels rust-uninstall-plugins rust-clean-stubs rust-verify-python-crates
.PHONY: rust-mcp-runtime-build rust-mcp-runtime-test rust-mcp-runtime-run

# Intentional broad scan under crates/: workspace-owned crates live here and CI
# should pick up new maturin crates automatically rather than curating a short list.
RUST_MATURIN_CRATES := $(shell find crates -type d 2>/dev/null | while read d; do [ -f "$$d/Cargo.toml" ] && [ -f "$$d/pyproject.toml" ] && echo "$$d"; done | sort)
# Keep rust server helpers discoverable without pulling mcp-servers/rust into the
# shared workspace commands.
RUST_MCP_DIRS := $(shell find mcp-servers/rust -maxdepth 2 -name Cargo.toml -exec dirname {} \; 2>/dev/null | sort -u)

rust-ensure-deps:                       ## Ensure Rust toolchain and maturin are available
	@if ! command -v rustup > /dev/null 2>&1; then \
		echo "🦀 Rust not found."; \
		echo "❌ Refusing to install Rust via remote shell bootstrapper."; \
		echo "💡 Install rustup from a trusted package manager or pinned release:"; \
		echo "   https://rustup.rs/"; \
		exit 1; \
	fi
	@if ! command -v cargo > /dev/null 2>&1; then \
		echo "⚠️  cargo not in PATH. Please run 'source \"$$HOME/.cargo/env\"' or restart your shell."; \
		exit 1; \
	fi
	@rustup component add rustfmt clippy 2>/dev/null || true
	@if ! command -v maturin > /dev/null 2>&1; then \
		if [ -f "$(VENV_DIR)/bin/activate" ]; then \
			echo "📦 Installing maturin into venv..."; \
			/bin/bash -c "source $(VENV_DIR)/bin/activate && $(UV_BIN) pip install maturin"; \
		elif command -v pip > /dev/null 2>&1; then \
			echo "📦 Installing maturin globally (venv not found)..."; \
			pip install maturin; \
		else \
			echo "⚠️  maturin not found and cannot be installed (no venv or pip available)"; \
			echo "   For building wheels, install maturin: pip install maturin"; \
		fi; \
	fi

rust-verify-python-crates:             ## Fail if a PyO3 crate is missing pyproject.toml packaging metadata
	@python3 -c 'import pathlib, sys; cargos=sorted(pathlib.Path("crates").rglob("Cargo.toml")); missing=[cargo.parent.as_posix() for cargo in cargos if "pyo3" in cargo.read_text(encoding="utf-8", errors="ignore").lower() and not cargo.with_name("pyproject.toml").exists()]; print("✅ PyO3 crate packaging metadata verified" if not missing else "❌ PyO3 crates missing pyproject.toml:"); [print(f"  - {crate}") for crate in missing]; sys.exit(1 if missing else 0)'

rust-install: rust-ensure-deps rust-verify-python-crates rust-stub-gen  ## Install maturin crates into venv
	@echo "🦀 Installing maturin crates into venv (from workspace root)..."
	@for crate in $(RUST_MATURIN_CRATES); do \
		echo "  Installing $$crate..."; \
		uv run maturin develop --release --manifest-path $$crate/Cargo.toml || exit 1; \
	done
	@echo "✅ All maturin crates installed"

rust-build: rust-ensure-deps            ## Build Rust workspace (release)
	@echo "🦀 Building Rust workspace (release)..."
	@cargo build --workspace --release
	@echo "✅ Rust workspace built"

rust-build-check: rust-ensure-deps rust-verify-python-crates  ## Build Rust workspace + verify all maturin crates build (debug, for CI)
	@echo "🦀 Building Rust workspace..."
	@cargo build --workspace
	@echo "🦀 Verifying all maturin crates build..."
	@for crate in $(RUST_MATURIN_CRATES); do \
		echo "  Building maturin crate: $$crate"; \
		uv run maturin build --manifest-path $$crate/Cargo.toml || exit 1; \
	done
	@echo "✅ Rust workspace and all maturin crates build OK"

rust-dev: rust-ensure-deps rust-verify-python-crates rust-stub-gen  ## Build and install maturin crates (debug mode)
	@echo "🦀 Installing maturin crates (development/debug mode)..."
	@for crate in $(RUST_MATURIN_CRATES); do \
		echo "  Installing $$crate (debug)..."; \
		uv run maturin develop --manifest-path $$crate/Cargo.toml || exit 1; \
	done
	@echo "✅ All maturin crates installed (dev mode)"

rust-test: rust-ensure-deps             ## Run Rust workspace tests
	@echo "🦀 Running Rust workspace tests..."
	@cargo test --workspace
	@echo "✅ Rust tests passed"

rust-format: rust-ensure-deps           ## Format Rust code (cargo fmt)
	@echo "🦀 Formatting Rust code..."
	@cargo fmt --all
	@echo "✅ Rust code formatted"

rust-fmt-check: rust-ensure-deps        ## Check formatting (cargo fmt --check)
	@echo "🦀 Checking Rust code format..."
	@cargo fmt --all -- --check
	@echo "✅ Rust format check passed"

rust-lint: rust-ensure-deps             ## Lint Rust code (cargo clippy)
	@echo "🦀 Linting Rust workspace..."
	@cargo clippy --workspace --all-targets -- -D warnings -A clippy::multiple_crate_versions
	@echo "✅ Rust lint passed"

rust-check: rust-build-check rust-fmt-check rust-lint rust-test  ## Run all Rust checks (build, fmt, clippy, test)
	@echo "✅ Rust check passed"

rust-doc: rust-ensure-deps              ## Build Rust documentation
	@echo "🦀 Building Rust documentation..."
	@cargo doc --workspace --no-deps --document-private-items
	@echo "✅ Rust doc built"

rust-build-wheels: rust-ensure-deps rust-verify-python-crates rust-stub-gen  ## Build Python wheels for maturin crates
	@echo "🦀 Building wheels for maturin crates (from workspace root)..."
	@for crate in $(RUST_MATURIN_CRATES); do \
		echo "  Building wheel: $$crate"; \
		uv run maturin build --release --manifest-path $$crate/Cargo.toml || exit 1; \
	done
	@echo "✅ All wheels built"

rust-vet: rust-ensure-deps              ## Run cargo-vet with strict supply-chain policy
	@echo "🦀 Running cargo-vet..."
	@command -v cargo-vet >/dev/null 2>&1 || { echo "Installing cargo-vet..."; cargo install --locked cargo-vet --version 0.10.2; }
	@cargo vet check
	@echo "✅ Rust supply-chain vetting passed"

rust-deny: rust-ensure-deps             ## Run cargo-deny policy checks on the Rust workspace
	@echo "🦀 Running cargo-deny policy checks (workspace)..."
	@command -v cargo-deny >/dev/null 2>&1 || { echo "Installing cargo-deny..."; cargo install --locked cargo-deny --version 0.19.0; }
	@cargo deny check advisories bans sources
	@echo "✅ Rust dependency policy check done"

rust-licenses: rust-ensure-deps         ## Run cargo-deny license check (workspace)
	@echo "🦀 Running cargo-deny license check (workspace)..."
	@command -v cargo-deny >/dev/null 2>&1 || { echo "Installing cargo-deny..."; cargo install --locked cargo-deny --version 0.19.0; }
	@cargo deny check licenses
	@echo "✅ Rust license check done"

rust-coverage: rust-ensure-deps         ## Run coverage for Rust workspace
	@echo "🦀 Running coverage (workspace)..."
	@command -v cargo-llvm-cov >/dev/null 2>&1 || { echo "Install cargo-llvm-cov: cargo install cargo-llvm-cov"; exit 1; }
	@mkdir -p coverage
	@cargo llvm-cov --workspace --html --output-dir coverage/rust
	@cargo llvm-cov report --cobertura --output-path coverage/cobertura.xml
	@cargo llvm-cov report
	@echo "✅ Coverage artefacts: HTML in coverage/rust/html/index.html & XML in coverage/cobertura.xml ✔"

rust-diff-cover:                       ## Run changed-line coverage for Rust
	@echo "📊  Running Rust diff-cover against main branch..."
	@test -d "$(VENV_DIR)" || $(MAKE) venv
	@if [ ! -f coverage/cobertura.xml ]; then \
		echo "ℹ️  No coverage/cobertura.xml found - running rust-coverage first..."; \
		$(MAKE) --no-print-directory rust-coverage; \
	fi
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
		diff-cover coverage/cobertura.xml --compare-branch=main --fail-under=90"

rust-bench-check: rust-ensure-deps      ## Verify benchmarks build (no run; for CI)
	@echo "🦀 Verifying Rust benchmarks build (no run)..."
	@cargo bench --workspace --no-run
	@echo "✅ Rust benchmarks build OK"

rust-uninstall-plugins: rust-ensure-deps ## Uninstall maturin crates from Python environment
	@echo "🦀 Uninstalling maturin crates from venv..."
	@for crate in $(RUST_MATURIN_CRATES); do \
		pkg=$$(grep '^name = ' $$crate/pyproject.toml 2>/dev/null | head -1 | sed 's/.*\"\(.*\)\".*/\1/'); \
		[ -n "$$pkg" ] && uv pip uninstall -y "$$pkg" 2>/dev/null || true; \
	done
	@echo "✅ Maturin crates uninstalled"

rust-clean: rust-ensure-deps            ## Clean Rust build artifacts and uninstall maturin crates
	@$(MAKE) --no-print-directory rust-uninstall-plugins
	@echo "🦀 Cleaning Rust build artifacts..."
	@cargo clean
	@rm -rf target
	@echo "✅ Rust clean done"

rust-verify: rust-ensure-deps rust-verify-python-crates  ## Verify maturin crate installation
	@echo "🦀 Verifying maturin crate installations..."
	@for crate in $(RUST_MATURIN_CRATES); do \
		pkg=$$(sed -n '/^\[lib\]/,/^\[/p' $$crate/Cargo.toml 2>/dev/null | grep '^name = ' | head -1 | sed 's/.*\"\([^\"]*\)\".*/\1/'); \
		[ -z "$$pkg" ] && { echo "  ❌ $$crate: no [lib] name in Cargo.toml"; exit 1; }; \
		uv run python -c "import $$pkg; print('  ✅ $$pkg')" || { echo "  ❌ $$pkg not installed"; exit 1; }; \
	done
	@echo "✅ All maturin crates verified"

rust-verify-stubs: rust-ensure-deps rust-verify-python-crates  ## Verify stub generation and pyproject.toml for maturin crates
	@echo "🦀 Verifying stub files and pyproject.toml..."
	@if [ -z "$(RUST_MATURIN_CRATES)" ]; then echo "ℹ️  No maturin crates found"; exit 0; fi
	@for crate in $(RUST_MATURIN_CRATES); do \
		if [ ! -f $$crate/pyproject.toml ]; then echo "❌ $$crate: pyproject.toml missing"; exit 1; fi; \
		pyi=$$(find $$crate/python -name "__init__.pyi" 2>/dev/null | head -1); \
		if [ -z "$$pyi" ]; then echo "❌ $$crate: no __init__.pyi (run make rust-stub-gen)"; exit 1; fi; \
		if [ ! -s "$$pyi" ]; then echo "❌ $$crate: stub file empty"; exit 1; fi; \
		echo "  ✅ $$crate"; \
	done
	@echo "✅ All stubs verified"

rust-clean-stubs: rust-ensure-deps rust-verify-python-crates  ## Remove generated stub files from maturin crates
	@echo "🦀 Removing generated stub files..."
	@if [ -z "$(RUST_MATURIN_CRATES)" ]; then echo "ℹ️  No maturin crates found"; exit 0; fi
	@for crate in $(RUST_MATURIN_CRATES); do \
		find $$crate/python -name "__init__.pyi" -type f -delete 2>/dev/null || true; \
	done
	@echo "✅ Rust clean-stubs done"

rust-stub-gen: rust-ensure-deps rust-verify-python-crates  ## Generate Python type stubs for maturin crates that have stub_gen
	@echo "🦀 Generating Python type stubs..."
	@if [ -z "$(RUST_MATURIN_CRATES)" ]; then echo "ℹ️  No maturin crates found"; exit 0; fi
	@for crate in $(RUST_MATURIN_CRATES); do \
		if [ -f $$crate/src/bin/stub_gen.rs ]; then \
			pkg=$$(grep '^name = ' $$crate/Cargo.toml 2>/dev/null | head -1 | sed 's/.*\"\(.*\)\".*/\1/'); \
			echo "  Stub-gen: $$pkg"; \
			cargo run -p $$pkg --bin "$${pkg}_stub_gen" || exit 1; \
		fi; \
	done
	@echo "✅ All stub files generated"

rust-install-deps: rust-ensure-deps     ## Install all Rust build dependencies
	@echo "✅ Rust build dependencies installed"

rust-install-targets: rust-ensure-deps  ## Install all Rust cross-compilation targets
	@echo "🎯 Installing Rust cross-compilation targets..."
	@rustup target add x86_64-unknown-linux-gnu
	@rustup target add aarch64-unknown-linux-gnu
	@rustup target add armv7-unknown-linux-gnueabihf
	@rustup target add s390x-unknown-linux-gnu
	@rustup target add powerpc64le-unknown-linux-gnu
	@rustup target add x86_64-apple-darwin
	@rustup target add aarch64-apple-darwin
	@rustup target add x86_64-pc-windows-msvc

rust-mcp-runtime-build:                 ## Build the experimental Rust MCP runtime
	@echo "🦀 Building experimental Rust MCP runtime..."
	@cd crates/mcp_runtime && cargo build --release

rust-mcp-runtime-test:                  ## Run tests for the experimental Rust MCP runtime
	@echo "🧪 Running Rust MCP runtime tests..."
	@cd crates/mcp_runtime && cargo test --release

rust-mcp-runtime-run:                   ## Run the experimental Rust MCP runtime against local gateway /rpc
	@echo "🚀 Starting Rust MCP runtime on http://127.0.0.1:8787 with backend http://127.0.0.1:4444/rpc"
	@cd crates/mcp_runtime && cargo run --release -- --backend-rpc-url http://127.0.0.1:4444/rpc --listen-http 127.0.0.1:8787

rust-a2a-runtime-build:                    ## Build the experimental Rust A2A runtime
	@echo "🦀 Building experimental Rust A2A runtime..."
	@cd crates/a2a_runtime && cargo build --release

rust-a2a-runtime-test:                     ## Run tests for the experimental Rust A2A runtime
	@echo "🧪 Running Rust A2A runtime tests..."
	@cd crates/a2a_runtime && cargo test --release

rust-a2a-runtime-run:                      ## Run the experimental Rust A2A runtime on http://127.0.0.1:8788
	@echo "🚀 Starting Rust A2A runtime on http://127.0.0.1:8788"
	@cd crates/a2a_runtime && cargo run --release -- --listen-http 127.0.0.1:8788

.PHONY: conc-02-gateways
conc-02-gateways:                    ## Run CONC-02 gateways read-during-write check (manual env/token setup required)
	@/bin/bash tests/manual/concurrency/run_conc_02_gateways.sh

# -----------------------------------------------------------------------------
# Temporary CI toggle for Conventional Commit message linting
# -----------------------------------------------------------------------------
# Default is disabled to avoid blocking in-flight PRs with legacy commit titles.
# Re-enable by setting COMMITLINT_ENFORCED=1 in CI or locally.
COMMITLINT_ENFORCED ?= 0
COMMITLINT_FROM ?= HEAD~1
COMMITLINT_TO ?= HEAD

.PHONY: linting-workflow-commitlint
linting-workflow-commitlint:         ## 📝  Conventional Commits linting (toggleable)
	@/bin/bash -c "set -euo pipefail; \
		if [ '$(COMMITLINT_ENFORCED)' != '1' ]; then \
			echo '⏭️ commitlint disabled (set COMMITLINT_ENFORCED=1 to enable)'; \
			exit 0; \
		fi; \
		echo '📝 commitlint $(COMMITLINT_FROM)..$(COMMITLINT_TO)...'; \
		command -v node >/dev/null 2>&1 || { echo '❌ node not found'; exit 1; }; \
		command -v npm >/dev/null 2>&1 || { echo '❌ npm not found'; exit 1; }; \
		mkdir -p '$(LINT_NODE_ROOT)/commitlint' '$(LINT_NODE_ROOT)/npm-cache'; \
		cd '$(LINT_NODE_ROOT)/commitlint'; \
		if [ ! -f package.json ]; then npm init -y >/dev/null 2>&1; fi; \
		npm_config_cache='$(LINT_NODE_ROOT)/npm-cache' npm install --silent @commitlint/cli @commitlint/config-conventional; \
		cd '$(CURDIR)'; \
		NODE_PATH='$(LINT_NODE_ROOT)/commitlint/node_modules' \
			node '$(LINT_NODE_ROOT)/commitlint/node_modules/@commitlint/cli/lib/cli.js' \
			--extends @commitlint/config-conventional \
			--from '$(COMMITLINT_FROM)' \
			--to '$(COMMITLINT_TO)'"

.PHONY: conc-01-gateways
conc-01-gateways:                    ## Run CONC-01 gateways manual matrix (manual env/token setup required)
	@/bin/bash tests/manual/concurrency/run_conc_01_gateways.sh
