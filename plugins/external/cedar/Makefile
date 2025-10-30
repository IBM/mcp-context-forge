
REQUIRED_BUILD_BINS := uv

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

# Project variables
PACKAGE_NAME = cedarpolicyplugin
PROJECT_NAME = cedarpolicyplugin
TARGET ?= cedarpolicyplugin

# Virtual-environment variables
VENVS_DIR ?= $(HOME)/.venv
VENV_DIR  ?= $(VENVS_DIR)/$(PROJECT_NAME)

# =============================================================================
# Linters
# =============================================================================

black:
	@echo "🎨  black $(TARGET)..." && $(VENV_DIR)/bin/black -l 200 $(TARGET)

black-check:
	@echo "🎨  black --check $(TARGET)..." && $(VENV_DIR)/bin/black -l 200 --check --diff $(TARGET)

ruff:
	@echo "⚡ ruff $(TARGET)..." && $(VENV_DIR)/bin/ruff check $(TARGET) && $(VENV_DIR)/bin/ruff format $(TARGET)

ruff-check:
	@echo "⚡ ruff check $(TARGET)..." && $(VENV_DIR)/bin/ruff check $(TARGET)

ruff-fix:
	@echo "⚡ ruff check --fix $(TARGET)..." && $(VENV_DIR)/bin/ruff check --fix $(TARGET)

ruff-format:
	@echo "⚡ ruff format $(TARGET)..." && $(VENV_DIR)/bin/ruff format $(TARGET)

# =============================================================================
# Container runtime configuration and operations
# =============================================================================

# Container resource limits
CONTAINER_MEMORY = 2048m
CONTAINER_CPUS   = 2

# Auto-detect container runtime if not specified - DEFAULT TO DOCKER
CONTAINER_RUNTIME ?= $(shell command -v docker >/dev/null 2>&1 && echo docker || echo podman)

# Alternative: Always default to docker unless explicitly overridden
# CONTAINER_RUNTIME ?= docker

# Container port
CONTAINER_PORT ?= 8000
CONTAINER_INTERNAL_PORT ?= 8000

print-runtime:
	@echo Using container runtime: $(CONTAINER_RUNTIME)

# Base image name (without any prefix)
IMAGE_BASE ?= mcpgateway/$(PROJECT_NAME)
IMAGE_TAG ?= latest

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



# Function to get the actual image name as it appears in image list
define get_image_name
$(shell $(CONTAINER_RUNTIME) images --format "{{.Repository}}:{{.Tag}}" | grep -E "(localhost/)?$(IMAGE_BASE):$(IMAGE_TAG)" | head -1)
endef

# Function to normalize image name for operations
define normalize_image
$(if $(findstring localhost/,$(1)),$(1),$(if $(filter podman,$(CONTAINER_RUNTIME)),localhost/$(1),$(1)))
endef

# Containerfile to use (can be overridden)
#CONTAINER_FILE ?= Containerfile
CONTAINER_FILE ?= $(shell [ -f "Containerfile" ] && echo "Containerfile" || echo "Dockerfile")

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
		-p $(CONTAINER_PORT):$(CONTAINER_INTERNAL_PORT) \
		--restart=always \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl --fail http://localhost:$(CONTAINER_INTERNAL_PORT)/health || exit 1" \
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
		-p $(CONTAINER_PORT):$(CONTAINER_INTERNAL_PORT) \
		--restart=always \
		--memory=$(CONTAINER_MEMORY) --cpus=$(CONTAINER_CPUS) \
		--health-cmd="curl --fail http://localhost:$(CONTAINER_INTERNAL_PORT)/health || exit 1" \
		--health-interval=1m --health-retries=3 \
		--health-start-period=30s --health-timeout=10s \
		-d $(call get_image_name)
	@sleep 2
	@echo "✅ Container started"
	@echo "🔍 Health check status:"
	@$(CONTAINER_RUNTIME) inspect $(PROJECT_NAME) --format='{{.State.Health.Status}}' 2>/dev/null || echo "No health check configured"

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
# Targets
# =============================================================================

.PHONY: venv
venv:
	@rm -Rf "$(VENV_DIR)"
	@test -d "$(VENVS_DIR)" || mkdir -p "$(VENVS_DIR)"
	@python3 -m venv "$(VENV_DIR)"
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m pip install --upgrade pip setuptools pdm uv"
	@echo -e "✅  Virtual env created.\n💡  Enter it with:\n    . $(VENV_DIR)/bin/activate\n"

.PHONY: install
install: venv
	$(foreach bin,$(REQUIRED_BUILD_BINS), $(if $(shell command -v $(bin) 2> /dev/null),,$(error Couldn't find `$(bin)`)))
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install ."

.PHONY: install-dev
install-dev: venv
	$(foreach bin,$(REQUIRED_BUILD_BINS), $(if $(shell command -v $(bin) 2> /dev/null),,$(error Couldn't find `$(bin)`)))
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install -e .[dev]"

.PHONY: install-editable
install-editable: venv
	$(foreach bin,$(REQUIRED_BUILD_BINS), $(if $(shell command -v $(bin) 2> /dev/null),,$(error Couldn't find `$(bin)`)))
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && python3 -m uv pip install -e .[dev]"

.PHONY: uninstall
uninstall:
	pip uninstall $(PACKAGE_NAME)

.PHONY: dist
dist: clean                  ## Build wheel + sdist into ./dist
	@test -d "$(VENV_DIR)" || $(MAKE) --no-print-directory venv
	@/bin/bash -eu -c "\
	    source $(VENV_DIR)/bin/activate && \
	    python3 -m pip install --quiet --upgrade pip build && \
	    python3 -m build"
	@echo '🛠  Wheel & sdist written to ./dist'

.PHONY: wheel
wheel:                       ## Build wheel only
	@test -d "$(VENV_DIR)" || $(MAKE) --no-print-directory venv
	@/bin/bash -eu -c "\
	    source $(VENV_DIR)/bin/activate && \
	    python3 -m pip install --quiet --upgrade pip build && \
	    python3 -m build -w"
	@echo '🛠  Wheel written to ./dist'

.PHONY: sdist
sdist:                       ## Build source distribution only
	@test -d "$(VENV_DIR)" || $(MAKE) --no-print-directory venv
	@/bin/bash -eu -c "\
	    source $(VENV_DIR)/bin/activate && \
	    python3 -m pip install --quiet --upgrade pip build && \
	    python3 -m build -s"
	@echo '🛠  Source distribution written to ./dist'

.PHONY: verify
verify: dist               ## Build, run metadata & manifest checks
	@/bin/bash -c "source $(VENV_DIR)/bin/activate && \
	twine check dist/* && \
	check-manifest && \
	pyroma -d ."
	@echo "✅  Package verified - ready to publish."

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
	$(MAKE) --no-print-directory ruff-fix TARGET="$$actual_target"

.PHONY: lint-check
lint-check:
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
	$(MAKE) --no-print-directory black-check TARGET="$$actual_target"; \
	$(MAKE) --no-print-directory ruff-check TARGET="$$actual_target"

.PHONY: lock
lock:
	$(foreach bin,$(REQUIRED_BUILD_BINS), $(if $(shell command -v $(bin) 2> /dev/null),,$(error Couldn't find `$(bin)`. Please run `make init`)))
	uv lock

.PHONY: test
test:
	pytest tests

.PHONY: serve
serve:
	@echo "Implement me."

.PHONY: build
build:
	@$(MAKE) container-build

.PHONY: start
start:
	@$(MAKE) container-run

.PHONY: stop
stop:
	@$(MAKE) container-stop

.PHONY: clean
clean:
	find . -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -delete
	rm -rf *.egg-info .pytest_cache tests/.pytest_cache build dist .ruff_cache .coverage

.PHONY: help
help:
	@echo "This Makefile is offered for convenience."
	@echo ""
	@echo "The following are the valid targets for this Makefile:"
	@echo "...install           Install package from sources"
	@echo "...install-dev       Install package from sources with dev packages"
	@echo "...install-editable  Install package from sources in editabled mode"
	@echo "...uninstall         Uninstall package"
	@echo "...dist              Clean-build wheel *and* sdist into ./dist"
	@echo "...wheel             Build wheel only"
	@echo "...sdist             Build source distribution only"
	@echo "...verify            Build + twine + check-manifest + pyroma (no upload)"
	@echo "...serve             Start API server locally"
	@echo "...build             Build API server container image"
	@echo "...start             Start the API server container"
	@echo "...start             Stop the API server container"
	@echo "...lock              Lock dependencies"
	@echo "...lint-fix          Check and fix lint errors"
	@echo "...lint-check        Check for lint errors"
	@echo "...test              Run all tests"
	@echo "...clean             Remove all artifacts and builds"
