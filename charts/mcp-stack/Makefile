#!/usr/bin/env -S make -f
# ==============================================================================
# MCP Stack Helm Chart Makefile
# ==============================================================================

# Chart configuration
CHART_NAME := mcp-stack
CHART_VERSION := $(shell grep '^version:' Chart.yaml | cut -d' ' -f2)
APP_VERSION := $(shell grep '^appVersion:' Chart.yaml | cut -d' ' -f2 | tr -d '"')

# Registry configuration
REGISTRY := ghcr.io
REPO := ibm/mcp-context-forge
CHART_REGISTRY := oci://$(REGISTRY)/$(REPO)

# Directories
DIST_DIR := dist
DOCS_DIR := docs
TEMP_DIR := tmp
TEST_DIR := tests

# Kubernetes configuration
KUBECONFIG ?= ~/.kube/config
NAMESPACE ?= mcp-test
RELEASE_NAME ?= mcp-stack-test

# Colors for output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[0;33m
BLUE := \033[0;34m
PURPLE := \033[0;35m
CYAN := \033[0;36m
WHITE := \033[0;37m
NC := \033[0m # No Color

# Default target
.DEFAULT_GOAL := help

# ==============================================================================
# HELP & INFORMATION
# ==============================================================================

.PHONY: help
help: ## 🎯 Show this help message
	@echo "$(CYAN)MCP Stack Helm Chart$(NC) - Available targets:"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make $(CYAN)<target>$(NC)\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*?##/ { \
			printf "  $(CYAN)%-20s$(NC) %s\n", $$1, $$2 \
		} \
		/^##@/ { \
			printf "\n$(YELLOW)%s$(NC)\n", substr($$0, 5) \
		}' $(MAKEFILE_LIST)
	@echo ""

.PHONY: info
info: ## 📋 Show chart information
	@echo "$(CYAN)Chart Information:$(NC)"
	@echo "  Name:        $(CHART_NAME)"
	@echo "  Version:     $(CHART_VERSION)"
	@echo "  App Version: $(APP_VERSION)"
	@echo "  Registry:    $(CHART_REGISTRY)"
	@echo "  Namespace:   $(NAMESPACE)"
	@echo "  Release:     $(RELEASE_NAME)"
	@echo ""

.PHONY: version
version: ## 🏷️ Show chart version
	@echo "$(CHART_VERSION)"

##@ 🔍 Validation & Linting

.PHONY: lint
lint: ## 🔧 Run Helm lint on the chart
	@echo "$(BLUE)Running Helm lint...$(NC)"
	@helm lint . --strict
	@echo "$(GREEN)✓ Lint completed successfully$(NC)"

.PHONY: lint-values
lint-values: ## 📝 Validate values.yaml against schema
	@echo "$(BLUE)Validating values.yaml against schema...$(NC)"
	@if [ -f values.schema.json ]; then \
		helm lint . --strict > /dev/null && \
		echo "$(GREEN)✓ Values validation passed$(NC)"; \
	else \
		echo "$(YELLOW)⚠ No values.schema.json found$(NC)"; \
	fi

.PHONY: lint-yaml
lint-yaml: ## 🔍 Lint YAML files with yamllint
	@echo "$(BLUE)Running yamllint...$(NC)"
	@if command -v yamllint >/dev/null 2>&1; then \
		yamllint . -c .yamllint.yml || yamllint .; \
		echo "$(GREEN)✓ YAML lint completed$(NC)"; \
	else \
		echo "$(YELLOW)⚠ yamllint not found, skipping$(NC)"; \
	fi

.PHONY: validate-all
validate-all: lint lint-values lint-yaml ## ✅ Run all validation checks

##@ 🧪 Testing

.PHONY: test-template
test-template: ## 📄 Test template rendering with default values
	@echo "$(BLUE)Testing template rendering...$(NC)"
	@helm template $(CHART_NAME) . --debug --dry-run > $(TEMP_DIR)/rendered.yaml
	@echo "$(GREEN)✓ Template rendering successful$(NC)"

.PHONY: test-template-values
test-template-values: ## 📄 Test template rendering with custom values
	@echo "$(BLUE)Testing template rendering with custom values...$(NC)"
	@if [ -f my-values.yaml ]; then \
		helm template $(CHART_NAME) . -f my-values.yaml --debug --dry-run > $(TEMP_DIR)/rendered-custom.yaml; \
		echo "$(GREEN)✓ Template rendering with custom values successful$(NC)"; \
	else \
		echo "$(YELLOW)⚠ my-values.yaml not found, using default values$(NC)"; \
		$(MAKE) test-template; \
	fi

.PHONY: test-dry-run
test-dry-run: ## 🎭 Test installation with dry-run
	@echo "$(BLUE)Testing installation (dry-run)...$(NC)"
	@helm install $(RELEASE_NAME) . --namespace $(NAMESPACE) --create-namespace --dry-run --debug
	@echo "$(GREEN)✓ Dry-run installation successful$(NC)"

.PHONY: test-upgrade-dry-run
test-upgrade-dry-run: ## 🔄 Test upgrade with dry-run
	@echo "$(BLUE)Testing upgrade (dry-run)...$(NC)"
	@helm upgrade $(RELEASE_NAME) . --namespace $(NAMESPACE) --dry-run --debug
	@echo "$(GREEN)✓ Dry-run upgrade successful$(NC)"

.PHONY: test-kubeval
test-kubeval: ## 🔍 Validate Kubernetes manifests with kubeval
	@echo "$(BLUE)Validating Kubernetes manifests...$(NC)"
	@if command -v kubeval >/dev/null 2>&1; then \
		helm template $(CHART_NAME) . | kubeval --strict --ignore-missing-schemas; \
		echo "$(GREEN)✓ Kubeval validation passed$(NC)"; \
	else \
		echo "$(YELLOW)⚠ kubeval not found, skipping$(NC)"; \
	fi

.PHONY: test-all
test-all: test-template test-dry-run test-kubeval ## 🧪 Run all tests

##@ 📦 Packaging & Publishing

.PHONY: clean
clean: ## 🧹 Clean build artifacts
	@echo "$(BLUE)Cleaning build artifacts...$(NC)"
	@rm -rf $(DIST_DIR) $(TEMP_DIR) *.tgz values.schema.generated.json
	@echo "$(GREEN)✓ Clean completed$(NC)"

.PHONY: package
package: clean validate-all ## 📦 Package the Helm chart
	@echo "$(BLUE)Packaging Helm chart...$(NC)"
	@mkdir -p $(DIST_DIR)
	@helm package . --destination $(DIST_DIR) --dependency-update
	@echo "$(GREEN)✓ Chart packaged: $(DIST_DIR)/$(CHART_NAME)-$(CHART_VERSION).tgz$(NC)"

.PHONY: package-dev
package-dev: clean ## 📦 Package chart for development (skip validation)
	@echo "$(BLUE)Packaging Helm chart (development)...$(NC)"
	@mkdir -p $(DIST_DIR)
	@helm package . --destination $(DIST_DIR)
	@echo "$(GREEN)✓ Chart packaged: $(DIST_DIR)/$(CHART_NAME)-$(CHART_VERSION).tgz$(NC)"

.PHONY: push
push: package ## 🚀 Push chart to OCI registry
	@echo "$(BLUE)Pushing chart to registry...$(NC)"
	@helm push $(DIST_DIR)/$(CHART_NAME)-$(CHART_VERSION).tgz $(CHART_REGISTRY)
	@echo "$(GREEN)✓ Chart pushed to $(CHART_REGISTRY)$(NC)"

.PHONY: sign
sign: package ## 🔐 Sign the chart package
	@echo "$(BLUE)Signing chart package...$(NC)"
	@if command -v cosign >/dev/null 2>&1; then \
		cosign sign-blob --yes $(DIST_DIR)/$(CHART_NAME)-$(CHART_VERSION).tgz \
			--output-signature $(DIST_DIR)/$(CHART_NAME)-$(CHART_VERSION).tgz.sig \
			--output-certificate $(DIST_DIR)/$(CHART_NAME)-$(CHART_VERSION).tgz.pem; \
		echo "$(GREEN)✓ Chart signed$(NC)"; \
	else \
		echo "$(YELLOW)⚠ cosign not found, skipping signing$(NC)"; \
	fi

##@ 🚀 Deployment & Management

.PHONY: install
install: ## 🚀 Install the chart
	@echo "$(BLUE)Installing chart...$(NC)"
	@helm install $(RELEASE_NAME) . --namespace $(NAMESPACE) --create-namespace --wait --timeout 10m
	@echo "$(GREEN)✓ Chart installed successfully$(NC)"

.PHONY: install-dev
install-dev: ## 🚀 Install chart with development values
	@echo "$(BLUE)Installing chart (development)...$(NC)"
	@if [ -f my-values.yaml ]; then \
		helm install $(RELEASE_NAME) . --namespace $(NAMESPACE) --create-namespace -f my-values.yaml --wait --timeout 10m; \
	else \
		echo "$(YELLOW)⚠ my-values.yaml not found, using default values$(NC)"; \
		$(MAKE) install; \
	fi
	@echo "$(GREEN)✓ Chart installed successfully$(NC)"

.PHONY: upgrade
upgrade: ## 🔄 Upgrade the chart
	@echo "$(BLUE)Upgrading chart...$(NC)"
	@helm upgrade $(RELEASE_NAME) . --namespace $(NAMESPACE) --wait --timeout 10m
	@echo "$(GREEN)✓ Chart upgraded successfully$(NC)"

.PHONY: upgrade-dev
upgrade-dev: ## 🔄 Upgrade chart with development values
	@echo "$(BLUE)Upgrading chart (development)...$(NC)"
	@if [ -f my-values.yaml ]; then \
		helm upgrade $(RELEASE_NAME) . --namespace $(NAMESPACE) -f my-values.yaml --wait --timeout 10m; \
	else \
		echo "$(YELLOW)⚠ my-values.yaml not found, using default values$(NC)"; \
		$(MAKE) upgrade; \
	fi
	@echo "$(GREEN)✓ Chart upgraded successfully$(NC)"

.PHONY: uninstall
uninstall: ## 🗑️ Uninstall the chart
	@echo "$(BLUE)Uninstalling chart...$(NC)"
	@helm uninstall $(RELEASE_NAME) --namespace $(NAMESPACE) --wait --timeout 5m
	@echo "$(GREEN)✓ Chart uninstalled successfully$(NC)"

.PHONY: status
status: ## 📊 Show chart status
	@echo "$(BLUE)Chart status:$(NC)"
	@helm status $(RELEASE_NAME) --namespace $(NAMESPACE)

.PHONY: history
history: ## 📜 Show chart history
	@echo "$(BLUE)Chart history:$(NC)"
	@helm history $(RELEASE_NAME) --namespace $(NAMESPACE)

.PHONY: rollback
rollback: ## ⏪ Rollback to previous version
	@echo "$(BLUE)Rolling back chart...$(NC)"
	@helm rollback $(RELEASE_NAME) --namespace $(NAMESPACE) --wait --timeout 5m
	@echo "$(GREEN)✓ Chart rolled back successfully$(NC)"

##@ 🔍 Debugging & Inspection

.PHONY: debug
debug: ## 🐛 Show debug information
	@echo "$(BLUE)Debug information:$(NC)"
	@echo "Kubernetes context: $$(kubectl config current-context)"
	@echo "Namespace: $(NAMESPACE)"
	@echo "Release name: $(RELEASE_NAME)"
	@echo ""
	@echo "$(BLUE)Helm releases:$(NC)"
	@helm list --namespace $(NAMESPACE) || echo "No releases found"
	@echo ""
	@echo "$(BLUE)Kubernetes resources:$(NC)"
	@kubectl get all --namespace $(NAMESPACE) || echo "No resources found"

.PHONY: describe
describe: ## 📋 Describe all chart resources
	@echo "$(BLUE)Describing chart resources...$(NC)"
	@kubectl describe all --namespace $(NAMESPACE) -l app.kubernetes.io/instance=$(RELEASE_NAME)

.PHONY: logs
logs: ## 📜 Show logs for all pods
	@echo "$(BLUE)Showing logs for all pods...$(NC)"
	@kubectl logs --namespace $(NAMESPACE) -l app.kubernetes.io/instance=$(RELEASE_NAME) --all-containers=true --tail=100

.PHONY: logs-follow
logs-follow: ## 📜 Follow logs for all pods
	@echo "$(BLUE)Following logs for all pods...$(NC)"
	@kubectl logs --namespace $(NAMESPACE) -l app.kubernetes.io/instance=$(RELEASE_NAME) --all-containers=true --follow

.PHONY: port-forward
port-forward: ## 🌐 Port-forward to gateway service
	@echo "$(BLUE)Port-forwarding to gateway service...$(NC)"
	@kubectl port-forward --namespace $(NAMESPACE) service/$(RELEASE_NAME)-mcpgateway 4444:80

.PHONY: shell
shell: ## 🐚 Open shell in gateway pod
	@echo "$(BLUE)Opening shell in gateway pod...$(NC)"
	@kubectl exec --namespace $(NAMESPACE) -it deployment/$(RELEASE_NAME)-mcpgateway -- /bin/bash

##@ 📚 Documentation

.PHONY: docs
docs: ## 📚 Generate chart documentation
	@echo "$(BLUE)Generating chart documentation...$(NC)"
	@if command -v helm-docs >/dev/null 2>&1; then \
		helm-docs --chart-search-root=. --template-files=README.md.gotmpl --output-file=README.md; \
		echo "$(GREEN)✓ Documentation generated$(NC)"; \
	else \
		echo "$(YELLOW)⚠ helm-docs not found, skipping documentation generation$(NC)"; \
	fi

.PHONY: schema
schema: ## 📋 Generate values schema (preserves existing schema)
	@echo "$(BLUE)Generating values schema...$(NC)"
	@if command -v helm schema >/dev/null 2>&1; then \
		helm schema --input values.yaml --output values.schema.generated.json; \
		echo "$(GREEN)✓ Values schema generated: values.schema.generated.json$(NC)"; \
		echo "$(YELLOW)⚠ Review and manually merge with values.schema.json if needed$(NC)"; \
		if [ -f values.schema.json ]; then \
			echo "$(BLUE)💡 Compare schemas with: make schema-diff$(NC)"; \
		fi; \
	else \
		echo "$(YELLOW)⚠ helm schema plugin not found$(NC)"; \
		echo "Install with: make install-deps or helm plugin install https://github.com/karuppiah7890/helm-schema-gen"; \
	fi

.PHONY: schema-diff
schema-diff: ## 🔍 Compare existing and generated schemas
	@echo "$(BLUE)Comparing schemas...$(NC)"
	@if [ -f values.schema.json ] && [ -f values.schema.generated.json ]; then \
		if command -v diff >/dev/null 2>&1; then \
			diff -u values.schema.json values.schema.generated.json || echo "$(YELLOW)⚠ Schemas differ$(NC)"; \
		elif command -v jq >/dev/null 2>&1; then \
			echo "$(BLUE)Existing schema keys:$(NC)"; \
			jq -r 'paths(scalars) as $p | $p | join(".")' values.schema.json | sort; \
			echo "$(BLUE)Generated schema keys:$(NC)"; \
			jq -r 'paths(scalars) as $p | $p | join(".")' values.schema.generated.json | sort; \
		else \
			echo "$(YELLOW)⚠ diff or jq not found for comparison$(NC)"; \
		fi; \
	else \
		echo "$(YELLOW)⚠ Both schemas must exist for comparison$(NC)"; \
		echo "Run 'make schema' to generate values.schema.generated.json"; \
	fi

.PHONY: schema-validate
schema-validate: ## ✅ Validate values.yaml against existing schema
	@echo "$(BLUE)Validating values.yaml against schema...$(NC)"
	@if [ -f values.schema.json ]; then \
		if command -v ajv >/dev/null 2>&1; then \
			ajv validate -s values.schema.json -d values.yaml && echo "$(GREEN)✓ Values validation passed$(NC)" || \
			(echo "$(YELLOW)⚠ ajv failed, trying without meta-schema validation$(NC)" && \
			 ajv validate -s values.schema.json -d values.yaml && echo "$(GREEN)✓ Values validation passed$(NC)"); \
		elif command -v ajv-cli >/dev/null 2>&1; then \
			ajv-cli validate -s values.schema.json -d values.yaml && echo "$(GREEN)✓ Values validation passed$(NC)" || \
			(echo "$(YELLOW)⚠ ajv-cli failed, trying helm lint validation$(NC)" && \
			 helm lint . --strict > /dev/null && echo "$(GREEN)✓ Helm lint validation passed$(NC)"); \
		elif command -v python3 >/dev/null 2>&1; then \
			echo "$(YELLOW)⚠ ajv not found, trying Python jsonschema validation$(NC)"; \
			python3 -c "import jsonschema, yaml, json; jsonschema.validate(yaml.safe_load(open('values.yaml')), json.load(open('values.schema.json')))" 2>/dev/null && \
			echo "$(GREEN)✓ Python jsonschema validation passed$(NC)" || \
			(echo "$(YELLOW)⚠ Python validation failed, using helm lint$(NC)" && \
			 helm lint . --strict > /dev/null && echo "$(GREEN)✓ Helm lint validation passed$(NC)"); \
		else \
			echo "$(YELLOW)⚠ No schema validators found, using helm lint for basic validation$(NC)"; \
			echo "$(YELLOW)💡 For proper schema validation, install ajv: npm install -g ajv-cli$(NC)"; \
			helm lint . --strict > /dev/null && echo "$(GREEN)✓ Helm lint validation passed$(NC)"; \
		fi; \
	else \
		echo "$(YELLOW)⚠ values.schema.json not found$(NC)"; \
	fi

.PHONY: schema-validate-simple
schema-validate-simple: ## ✅ Simple schema validation using Python
	@echo "$(BLUE)Validating values.yaml against schema (Python method)...$(NC)"
	@if [ -f values.schema.json ]; then \
		if command -v python3 >/dev/null 2>&1; then \
			python3 -c "import jsonschema, yaml, json; jsonschema.validate(yaml.safe_load(open('values.yaml')), json.load(open('values.schema.json'))); print('✓ Schema validation passed')" || \
			echo "$(YELLOW)⚠ Install required Python packages: pip install jsonschema pyyaml$(NC)"; \
		else \
			echo "$(YELLOW)⚠ Python3 not found$(NC)"; \
		fi; \
	else \
		echo "$(YELLOW)⚠ values.schema.json not found$(NC)"; \
	fi

.PHONY: readme
readme: ## 📖 Update README with chart values
	@echo "$(BLUE)Updating README with chart values...$(NC)"
	@if command -v helm-docs >/dev/null 2>&1; then \
		helm-docs --sort-values-order=file; \
		echo "$(GREEN)✓ README updated$(NC)"; \
	else \
		echo "$(YELLOW)⚠ helm-docs not found$(NC)"; \
	fi

##@ 🔄 Dependencies

.PHONY: deps-update
deps-update: ## 📥 Update chart dependencies
	@echo "$(BLUE)Updating chart dependencies...$(NC)"
	@helm dependency update
	@echo "$(GREEN)✓ Dependencies updated$(NC)"

.PHONY: deps-build
deps-build: ## 🔨 Build chart dependencies
	@echo "$(BLUE)Building chart dependencies...$(NC)"
	@helm dependency build
	@echo "$(GREEN)✓ Dependencies built$(NC)"

.PHONY: deps-clean
deps-clean: ## 🧹 Clean chart dependencies
	@echo "$(BLUE)Cleaning chart dependencies...$(NC)"
	@rm -rf charts/ Chart.lock
	@echo "$(GREEN)✓ Dependencies cleaned$(NC)"

##@ 🛠️ Development Tools

.PHONY: install-deps
install-deps: ## 📥 Install missing development dependencies
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	@echo "$(BLUE)Detecting package manager...$(NC)"
	@if command -v brew >/dev/null 2>&1; then \
		echo "$(GREEN)✓ Using Homebrew$(NC)"; \
		$(MAKE) install-deps-brew; \
	elif command -v apt-get >/dev/null 2>&1; then \
		echo "$(GREEN)✓ Using APT$(NC)"; \
		$(MAKE) install-deps-apt; \
	elif command -v yum >/dev/null 2>&1; then \
		echo "$(GREEN)✓ Using YUM$(NC)"; \
		$(MAKE) install-deps-yum; \
	elif command -v npm >/dev/null 2>&1; then \
		echo "$(GREEN)✓ Using NPM for Node.js tools$(NC)"; \
		$(MAKE) install-deps-npm; \
	else \
		echo "$(YELLOW)⚠ No supported package manager found$(NC)"; \
		echo "Please install tools manually:"; \
		echo "  - yamllint: pip install yamllint"; \
		echo "  - kubeval: https://github.com/instrumenta/kubeval/releases"; \
		echo "  - helm-docs: https://github.com/norwoodj/helm-docs/releases"; \
		echo "  - cosign: https://github.com/sigstore/cosign/releases"; \
		echo "  - prettier: npm install -g prettier"; \
		echo "  - ajv-cli: npm install -g ajv-cli (for JSON schema validation)"; \
		echo "  - fswatch: https://github.com/emcrisostomo/fswatch/releases"; \
	fi
	@$(MAKE) install-helm-plugins

.PHONY: install-deps-brew
install-deps-brew: ## 📥 Install dependencies using Homebrew
	@echo "$(BLUE)Installing dependencies with Homebrew...$(NC)"
	@tools="yamllint kubeval helm-docs cosign prettier fswatch"; \
	for tool in $tools; do \
		if ! command -v $tool >/dev/null 2>&1; then \
			echo "$(BLUE)Installing $tool...$(NC)"; \
			brew install $tool || echo "$(YELLOW)⚠ Failed to install $tool$(NC)"; \
		else \
			echo "$(GREEN)✓ $tool already installed$(NC)"; \
		fi; \
	done

.PHONY: install-deps-apt
install-deps-apt: ## 📥 Install dependencies using APT
	@echo "$(BLUE)Installing dependencies with APT...$(NC)"
	@sudo apt-get update
	@if ! command -v yamllint >/dev/null 2>&1; then \
		echo "$(BLUE)Installing yamllint...$(NC)"; \
		sudo apt-get install -y yamllint || pip3 install yamllint; \
	fi
	@if ! command -v kubeval >/dev/null 2>&1; then \
		echo "$(BLUE)Installing kubeval...$(NC)"; \
		wget -O /tmp/kubeval.tar.gz https://github.com/instrumenta/kubeval/releases/latest/download/kubeval-linux-amd64.tar.gz; \
		tar -xzf /tmp/kubeval.tar.gz -C /tmp/; \
		sudo mv /tmp/kubeval /usr/local/bin/; \
	fi
	@if ! command -v helm-docs >/dev/null 2>&1; then \
		echo "$(BLUE)Installing helm-docs...$(NC)"; \
		wget -O /tmp/helm-docs.tar.gz https://github.com/norwoodj/helm-docs/releases/latest/download/helm-docs_$(shell uname -s)_$(shell uname -m).tar.gz; \
		tar -xzf /tmp/helm-docs.tar.gz -C /tmp/; \
		sudo mv /tmp/helm-docs /usr/local/bin/; \
	fi
	@if ! command -v prettier >/dev/null 2>&1; then \
		echo "$(BLUE)Installing prettier via npm...$(NC)"; \
		sudo npm install -g prettier || echo "$(YELLOW)⚠ npm not found, skipping prettier$(NC)"; \
	fi
	@if ! command -v ajv-cli >/dev/null 2>&1; then \
		echo "$(BLUE)Installing ajv-cli for JSON schema validation...$(NC)"; \
		sudo npm install -g ajv-cli || echo "$(YELLOW)⚠ npm not found, skipping ajv-cli$(NC)"; \
	fi

.PHONY: install-deps-yum
install-deps-yum: ## 📥 Install dependencies using YUM
	@echo "$(BLUE)Installing dependencies with YUM...$(NC)"
	@if ! command -v yamllint >/dev/null 2>&1; then \
		echo "$(BLUE)Installing yamllint...$(NC)"; \
		sudo yum install -y yamllint || pip3 install yamllint; \
	fi
	@echo "$(YELLOW)⚠ Please install remaining tools manually:$(NC)"
	@echo "  - kubeval: https://github.com/instrumenta/kubeval/releases"
	@echo "  - helm-docs: https://github.com/norwoodj/helm-docs/releases"
	@echo "  - cosign: https://github.com/sigstore/cosign/releases"

.PHONY: install-deps-npm
install-deps-npm: ## 📥 Install Node.js dependencies using NPM
	@echo "$(BLUE)Installing Node.js dependencies with NPM...$(NC)"
	@if ! command -v prettier >/dev/null 2>&1; then \
		echo "$(BLUE)Installing prettier...$(NC)"; \
		npm install -g prettier; \
	fi
	@if ! command -v ajv-cli >/dev/null 2>&1; then \
		echo "$(BLUE)Installing ajv-cli for JSON schema validation...$(NC)"; \
		npm install -g ajv-cli; \
	fi

.PHONY: install-helm-plugins
install-helm-plugins: ## 📥 Install required Helm plugins
	@echo "$(BLUE)Installing Helm plugins...$(NC)"
	@if ! helm plugin list | grep -q "schema"; then \
		echo "$(BLUE)Installing helm-schema plugin...$(NC)"; \
		helm plugin install https://github.com/karuppiah7890/helm-schema-gen || echo "$(YELLOW)⚠ Failed to install helm-schema$(NC)"; \
	else \
		echo "$(GREEN)✓ helm-schema plugin already installed$(NC)"; \
	fi
	@if ! helm plugin list | grep -q "diff"; then \
		echo "$(BLUE)Installing helm-diff plugin...$(NC)"; \
		helm plugin install https://github.com/databus23/helm-diff || echo "$(YELLOW)⚠ Failed to install helm-diff$(NC)"; \
	else \
		echo "$(GREEN)✓ helm-diff plugin already installed$(NC)"; \
	fi

.PHONY: setup-dev
setup-dev: ## 🔧 Set up development environment
	@echo "$(BLUE)Setting up development environment...$(NC)"
	@mkdir -p $(TEMP_DIR) $(DIST_DIR)
	@if [ ! -f my-values.yaml ]; then \
		cp values.yaml my-values.yaml; \
		echo "$(GREEN)✓ Created my-values.yaml$(NC)"; \
	fi
	@echo "$(GREEN)✓ Development environment ready$(NC)"
	@echo "$(YELLOW)💡 Run 'make install-deps' to install optional development tools$(NC)"

.PHONY: watch
watch: ## 👀 Watch for changes and re-lint
	@echo "$(BLUE)Watching for changes...$(NC)"
	@if command -v fswatch >/dev/null 2>&1; then \
		fswatch -o . -e "$(DIST_DIR)" -e "$(TEMP_DIR)" -e "*.tgz" | xargs -n1 -I{} make lint; \
	else \
		echo "$(YELLOW)⚠ fswatch not found, install with: brew install fswatch$(NC)"; \
	fi

.PHONY: format
format: ## 🎨 Format YAML files
	@echo "$(BLUE)Formatting YAML files...$(NC)"
	@if command -v prettier >/dev/null 2>&1; then \
		prettier --write "**/*.{yaml,yml}" --ignore-path .helmignore; \
		echo "$(GREEN)✓ YAML files formatted$(NC)"; \
	else \
		echo "$(YELLOW)⚠ prettier not found, skipping formatting$(NC)"; \
	fi

.PHONY: check-tools
check-tools: ## 🔍 Check for required tools
	@echo "$(BLUE)Checking for required tools...$(NC)"
	@tools="helm kubectl"; \
	missing_required=""; \
	for tool in $tools; do \
		if command -v $tool >/dev/null 2>&1; then \
			echo "$(GREEN)✓ $tool$(NC)"; \
		else \
			echo "$(RED)✗ $tool (required)$(NC)"; \
			missing_required="$missing_required $tool"; \
		fi; \
	done
	@if [ -n "$missing_required" ]; then \
		echo "$(RED)Missing required tools:$missing_required$(NC)"; \
		echo "Please install them manually."; \
		exit 1; \
	fi
	@echo ""
	@echo "$(BLUE)Checking for optional tools...$(NC)"
	@tools="yamllint kubeval helm-docs cosign prettier fswatch"; \
	missing_optional=""; \
	for tool in $tools; do \
		if command -v $tool >/dev/null 2>&1; then \
			echo "$(GREEN)✓ $tool$(NC)"; \
		else \
			echo "$(YELLOW)- $tool (optional)$(NC)"; \
			missing_optional="$missing_optional $tool"; \
		fi; \
	done
	@echo ""
	@echo "$(BLUE)Checking for Helm plugins...$(NC)"
	@plugins="schema diff"; \
	for plugin in $plugins; do \
		if helm plugin list | grep -q "$plugin"; then \
			echo "$(GREEN)✓ helm-$plugin$(NC)"; \
		else \
			echo "$(YELLOW)- helm-$plugin (optional)$(NC)"; \
		fi; \
	done
	@if [ -n "$missing_optional" ]; then \
		echo ""; \
		echo "$(YELLOW)💡 Install missing tools with: make install-deps$(NC)"; \
	fi

##@ 🧪 Integration Testing

.PHONY: test-integration
test-integration: install ## 🧪 Run integration tests
	@echo "$(BLUE)Running integration tests...$(NC)"
	@echo "Waiting for pods to be ready..."
	@kubectl wait --for=condition=ready pod --namespace $(NAMESPACE) -l app.kubernetes.io/instance=$(RELEASE_NAME) --timeout=300s
	@echo "$(GREEN)✓ Integration tests passed$(NC)"

.PHONY: test-e2e
test-e2e: install ## 🔄 Run end-to-end tests
	@echo "$(BLUE)Running end-to-end tests...$(NC)"
	@kubectl wait --for=condition=ready pod --namespace $(NAMESPACE) -l app.kubernetes.io/instance=$(RELEASE_NAME) --timeout=300s
	@kubectl port-forward --namespace $(NAMESPACE) service/$(RELEASE_NAME)-mcpgateway 4444:80 &
	@sleep 5
	@curl -f http://localhost:4444/health || (echo "$(RED)✗ Health check failed$(NC)" && exit 1)
	@pkill -f "kubectl port-forward" || true
	@echo "$(GREEN)✓ End-to-end tests passed$(NC)"

.PHONY: test-cleanup
test-cleanup: ## 🧹 Clean up test resources
	@echo "$(BLUE)Cleaning up test resources...$(NC)"
	@helm uninstall $(RELEASE_NAME) --namespace $(NAMESPACE) --ignore-not-found --wait --timeout 5m
	@kubectl delete namespace $(NAMESPACE) --ignore-not-found --wait --timeout 5m
	@echo "$(GREEN)✓ Test cleanup completed$(NC)"

##@ 🎯 CI/CD Targets

.PHONY: ci-setup
ci-setup: check-tools ## 🔄 CI: Set up CI environment
	@echo "$(BLUE)Setting up CI environment...$(NC)"
	@$(MAKE) setup-dirs
	@echo "$(GREEN)✓ CI setup completed$(NC)"

.PHONY: ci-lint
ci-lint: validate-all ## 🔄 CI: Run linting and validation
	@echo "$(GREEN)✓ CI linting completed$(NC)"

.PHONY: ci-test
ci-test: test-all ## 🔄 CI: Run all tests
	@echo "$(GREEN)✓ CI testing completed$(NC)"

.PHONY: ci-package
ci-package: package ## 🔄 CI: Package chart
	@echo "$(GREEN)✓ CI packaging completed$(NC)"

.PHONY: ci-publish
ci-publish: push ## 🔄 CI: Publish chart
	@echo "$(GREEN)✓ CI publishing completed$(NC)"

.PHONY: ci-all
ci-all: ci-setup ci-lint ci-test ci-package ## 🔄 CI: Run all CI tasks

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

# Ensure temp directory exists
$(TEMP_DIR):
	@mkdir -p $(TEMP_DIR)

# Ensure dist directory exists
$(DIST_DIR):
	@mkdir -p $(DIST_DIR)

# Set up directories
.PHONY: setup-dirs
setup-dirs: $(TEMP_DIR) $(DIST_DIR)

# Include setup-dirs as a dependency for targets that need it
test-template: setup-dirs
package: setup-dirs
package-dev: setup-dirs

# ==============================================================================
# PHONY TARGETS
# ==============================================================================

.PHONY: all
all: validate-all test-all package ## 🎯 Run full build pipeline

# Mark all targets as phony
.PHONY: $(MAKECMDGOALS)
