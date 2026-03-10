# Makefile for Rust Plugins
# Automatically discovers and installs all plugins (subdirectories with Cargo.toml)

.PHONY: install clean list help build test fmt clippy doc test-python test-verbose clean-all fmt-check doc-open bench bench-compare compare check verify verify-stubs clean-stubs test-integration test-all uninstall

# Discover all plugin directories containing Cargo.toml
PLUGIN_DIRS := $(shell find . -mindepth 1 -maxdepth 1 -type d -exec test -f {}/Cargo.toml \; -print | sed 's|^\./||' | sort)

# Pattern rule for calling plugin-specific targets (common to all plugins)
# Usage: make <plugin>-<target>
# Examples:
#   make pii_filter-install
#   make secrets_detection-test
#   make encoded_exfil_detection-build
%-build %-clean %-clean-all %-clippy %-doc %-doc-open %-fmt %-fmt-check %-help %-install %-uninstall %-test %-test-python %-test-verbose:
	@plugin=$$(echo $@ | sed 's/-[^-]*$$//'); \
	target=$$(echo $@ | sed 's/^[^-]*-//'); \
	echo "Running 'make $$target' in $$plugin..."; \
	cd $$plugin && $(MAKE) $$target

install:
	@echo "Installing all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo ""; \
		echo "Installing plugin: $$plugin"; \
		(cd $$plugin && $(MAKE) install) || exit 1; \
	done
	@echo ""
	@echo "✓ All plugins installed successfully"

uninstall:
	@echo "Uninstalling all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Uninstalling: $$plugin"; \
		(cd $$plugin && $(MAKE) uninstall) || exit 1; \
	done
	@echo "✓ All plugins uninstalled"

clean:
	@echo "Cleaning all plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Cleaning: $$plugin"; \
		(cd $$plugin && $(MAKE) clean) || exit 1; \
	done
	@rm -rf target/

build:
	@echo "Building all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Building: $$plugin"; \
		(cd $$plugin && $(MAKE) build) || exit 1; \
	done

build-target-%:
	@echo "Building all Rust plugins for target: $*..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Building $$plugin for $*..."; \
		(cd $$plugin && $(MAKE) build-target TARGET=$*) || exit 1; \
	done

test:
	@echo "Testing all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Testing: $$plugin"; \
		(cd $$plugin && $(MAKE) test) || exit 1; \
	done

test-verbose:
	@echo "Testing all Rust plugins (verbose)..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Testing: $$plugin"; \
		(cd $$plugin && $(MAKE) test-verbose) || exit 1; \
	done

test-python:
	@echo "Running Python tests for all plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Testing Python: $$plugin"; \
		(cd $$plugin && $(MAKE) test-python) || exit 1; \
	done

fmt:
	@echo "Formatting all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Formatting: $$plugin"; \
		(cd $$plugin && $(MAKE) fmt) || exit 1; \
	done

fmt-check:
	@echo "Checking format for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Checking format: $$plugin"; \
		(cd $$plugin && $(MAKE) fmt-check) || exit 1; \
	done

clippy:
	@echo "Running clippy on all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Clippy: $$plugin"; \
		(cd $$plugin && $(MAKE) clippy) || exit 1; \
	done

doc:
	@echo "Building documentation for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Building docs: $$plugin"; \
		(cd $$plugin && $(MAKE) doc) || exit 1; \
	done

doc-open:
	@echo "Building and opening documentation for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Building docs: $$plugin"; \
		(cd $$plugin && $(MAKE) doc-open) || exit 1; \
	done

clean-all:
	@echo "Deep cleaning all plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Deep cleaning: $$plugin"; \
		(cd $$plugin && $(MAKE) clean-all); \
	done
	@rm -rf target/

bench:
	@echo "Running benchmarks for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Benchmarking: $$plugin"; \
		(cd $$plugin && $(MAKE) bench) || exit 1; \
	done

bench-compare:
	@echo "Running performance comparisons for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Comparing: $$plugin"; \
		(cd $$plugin && $(MAKE) bench-compare) || exit 1; \
	done

compare:
	@echo "Running compare_performance.py for all Rust plugins (skip benchmarks)..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Comparing: $$plugin"; \
		(cd $$plugin && $(MAKE) compare) || exit 1; \
	done

build-wheels:
	@echo "Building wheels for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Building wheels for: $$plugin"; \
		echo "Cleaning python directory..."; \
		find $$plugin/python -name "*.so" -delete 2>/dev/null || true; \
		find $$plugin/python -name "*.pyd" -delete 2>/dev/null || true; \
		(cd $$plugin && uv run maturin build --release --out dist) || exit 1; \
	done
	@echo "✓ All wheels built successfully"

audit:
	@echo "Running security audit for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Auditing: $$plugin"; \
		(cd $$plugin && cargo audit) || exit 1; \
	done
	@echo "✓ All plugins audited successfully"

coverage:
	@echo "Running coverage for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Running coverage for: $$plugin"; \
		cd $$plugin; \
		$(MAKE) install || exit 1; \
		if [ -f Makefile ] && grep -q "coverage:" Makefile; then \
			uv run make coverage || exit 1; \
		else \
			mkdir -p coverage; \
			cargo llvm-cov --cobertura --output-path coverage/cobertura.xml || exit 1; \
		fi; \
		cd ..; \
	done
	@echo "✓ Coverage completed for all plugins"

release:
	@echo "Building and publishing release for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Building release for: $$plugin"; \
		cd $$plugin; \
		uv run maturin build --release --out dist || exit 1; \
		cd ..; \
	done
	@echo "✓ Release build completed"

release-publish:
	@echo "Publishing release wheels to PyPI..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Publishing: $$plugin"; \
		cd $$plugin; \
		if [ -n "$$MATURIN_PYPI_TOKEN" ]; then \
			uv run maturin publish --username __token__ --password "$$MATURIN_PYPI_TOKEN" || exit 1; \
		else \
			echo "⚠️  MATURIN_PYPI_TOKEN not set, skipping publish"; \
		fi; \
		cd ..; \
	done
	@echo "✓ Release published"

check:
	@echo "Running all checks for all Rust plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Checking: $$plugin"; \
		(cd $$plugin && $(MAKE) check-all) || exit 1; \
	done

verify:
	@echo "Verifying Rust plugin installations..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Verifying: $$plugin"; \
		(cd $$plugin && $(MAKE) verify) || exit 1; \
	done

clean-stubs:
	@echo "Cleaning stub files for all plugins..."
	@for plugin in $(PLUGIN_DIRS); do \
		echo "Cleaning stubs: $$plugin"; \
		find $$plugin/python -name "__init__.pyi" -type f -delete 2>/dev/null || true; \
	done
	@echo "✓ All stub files cleaned"

verify-stubs:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Running: make rust-verify-stubs"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Verifying stub files and pyproject.toml for all plugins..."
	@echo ""
	@for plugin in $(PLUGIN_DIRS); do \
		echo ""; \
		echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
		echo "Checking plugin: $$plugin"; \
		echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
		if [ ! -f "$$plugin/pyproject.toml" ]; then \
			echo "❌ ERROR: pyproject.toml not found in $$plugin"; \
			exit 1; \
		fi; \
		echo "✅ pyproject.toml exists"; \
		pyi_file=$$(find $$plugin/python -name "__init__.pyi" 2>/dev/null | head -1); \
		if [ -z "$$pyi_file" ]; then \
			echo "❌ ERROR: No __init__.pyi file found in $$plugin/python"; \
			echo "   Run 'make rust-install' to generate stub files"; \
			exit 1; \
		fi; \
		if [ ! -s "$$pyi_file" ]; then \
			echo "❌ ERROR: Stub file is empty: $$pyi_file"; \
			exit 1; \
		fi; \
		echo "✅ Stub file exists: $$pyi_file"; \
		if ! grep -q "def \|class " "$$pyi_file"; then \
			echo "⚠️  WARNING: Stub file may be incomplete (no functions or classes found)"; \
		fi; \
		echo "✅ $$plugin verification complete"; \
	done
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "✅ All plugins verified successfully!"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

test-all: test test-python
	@echo "✓ All tests completed successfully"

list:
	@echo "Discovered plugins:"
	@for plugin in $(PLUGIN_DIRS); do \
		echo "  - $$plugin"; \
	done

help:
	@echo "Available targets (run on ALL plugins):"
	@echo "  make install          - Install all Rust plugins"
	@echo "  make uninstall        - Uninstall all Rust plugins"
	@echo "  make build            - Build all Rust plugins"
	@echo "  make test             - Test all Rust plugins"
	@echo "  make test-verbose     - Test all plugins (verbose)"
	@echo "  make test-python      - Run Python tests for all plugins"
	@echo "  make test-integration - Run integration tests for all plugins"
	@echo "  make test-all         - Run all tests (Rust + Python)"
	@echo "  make clean            - Clean all build artifacts"
	@echo "  make clean-all        - Deep clean all plugins"
	@echo "  make fmt              - Format all plugin code"
	@echo "  make fmt-check        - Check formatting for all plugins"
	@echo "  make clippy           - Run clippy on all plugins"
	@echo "  make check            - Run all checks (fmt, clippy, test)"
	@echo "  make bench            - Run benchmarks for all plugins"
	@echo "  make bench-compare    - Run performance comparisons (with benchmarks)"
	@echo "  make compare          - Run compare_performance.py only (skip benchmarks)"
	@echo "  make verify           - Verify all plugin installations"
	@echo "  make verify-stubs     - Verify stub generation and pyproject.toml"
	@echo "  make clean-stubs      - Remove all generated stub files"
	@echo "  make doc              - Build documentation for all plugins"
	@echo "  make doc-open         - Build and open docs for all plugins"
	@echo "  make list             - List discovered plugins"
	@echo ""
	@echo "Plugin-specific targets (use <plugin>-<target>):"
	@echo "  make <plugin>-build        - Build specific plugin"
	@echo "  make <plugin>-clean        - Clean specific plugin"
	@echo "  make <plugin>-clean-all    - Clean all plugin artifacts"
	@echo "  make <plugin>-clippy       - Run clippy on plugin"
	@echo "  make <plugin>-doc          - Build plugin documentation"
	@echo "  make <plugin>-doc-open     - Build and open plugin docs"
	@echo "  make <plugin>-fmt          - Format plugin code"
	@echo "  make <plugin>-fmt-check    - Check plugin code formatting"
	@echo "  make <plugin>-help         - Show plugin-specific help"
	@echo "  make <plugin>-install      - Install specific plugin"
	@echo "  make <plugin>-uninstall    - Uninstall specific plugin"
	@echo "  make <plugin>-test         - Test specific plugin"
	@echo "  make <plugin>-test-python  - Run Python tests for plugin"
	@echo "  make <plugin>-test-verbose - Run verbose tests for plugin"
	@echo ""
	@echo "Examples:"
	@echo "  make install                        # Install all plugins"
	@echo "  make test                           # Test all plugins"
	@echo "  make pii_filter-install             # Install only pii_filter"
	@echo "  make secrets_detection-test         # Test only secrets_detection"
	@echo "  make encoded_exfil_detection-build  # Build only encoded_exfil_detection"

.DEFAULT_GOAL := install
