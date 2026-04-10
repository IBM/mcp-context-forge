# Plugin Migration Plan: In-tree to PyPI Packages

## Overview

This document outlines the migration strategy for converting 5 in-tree ContextForge plugins to standalone PyPI packages, following the pattern established with `cpex-rate-limiter`.

## Plugins to Migrate

1. **encoded_exfil_detection** - Encoded exfiltration detection
2. **pii_filter** - PII detection and masking
3. **retry_with_backoff** - Retry logic with exponential backoff
4. **secrets_detection** - Secret scanning
5. **url_reputation** - URL reputation checking

## Current State Analysis

### Directory Structure
```
plugins/
├── encoded_exfil_detection/    # Python implementation
├── pii_filter/                 # Python implementation
├── retry_with_backoff/         # Python implementation
├── secrets_detection/          # Python implementation
└── url_reputation/             # Python implementation

plugins_rust/
├── encoded_exfil_detection/    # Rust implementation (PyO3)
├── pii_filter/                 # Rust implementation (PyO3)
├── retry_with_backoff/         # Rust implementation (PyO3)
├── secrets_detection/          # Rust implementation (PyO3)
└── url_reputation/             # Rust implementation (PyO3)
```

### References Found
- **Config files**: 5 YAML files reference these plugins
  - `plugins/config.yaml`
  - `plugins/config-pii-guardian-policy.yaml`
  - `plugins/webhook_notification/test_config.yaml`
  - `tests/performance/plugins/config.yaml`
  - `tests/unit/mcpgateway/plugins/fixtures/configs/init_hooks_plugins_test.yaml`

### Build Infrastructure
- `plugins_rust/Makefile` - Orchestrates all Rust plugin builds
- Individual plugin Makefiles in each `plugins_rust/*/` directory
- `Containerfile.lite` - Includes Rust plugin build steps
- Root `Makefile` - Has `rust-*` targets for plugin operations

## Migration Strategy

### Phase 1: Package Creation & Publishing

For each plugin, create a standalone PyPI package:

#### Package Naming Convention
- `cpex-encoded-exfil-detection`
- `cpex-pii-filter`
- `cpex-retry-with-backoff`
- `cpex-secrets-detection`
- `cpex-url-reputation`

#### Package Structure (per plugin)
```
cpex-<plugin-name>/
├── Cargo.toml              # Rust package metadata
├── pyproject.toml          # Python package metadata (maturin)
├── README.md               # Package documentation
├── LICENSE                 # Apache 2.0
├── src/
│   └── lib.rs             # Rust implementation
├── python/
│   └── <package_name>/
│       └── __init__.py    # Python interface
└── tests/
    ├── test_*.rs          # Rust tests
    └── test_*.py          # Python tests
```

#### Publishing Steps (per plugin)
1. Create standalone repository or monorepo structure
2. Configure maturin for PyO3 builds
3. Build wheels for multiple platforms (Linux, macOS, Windows)
4. Publish to PyPI with version `0.0.1` or `0.1.0`
5. Verify installation: `pip install cpex-<plugin-name>`

### Phase 2: Repository Updates

#### 2.1 Update pyproject.toml
Add new packages to `[project.optional-dependencies]` under `plugins` group:

```toml
plugins = [
    "cpex-rate-limiter>=0.0.2",
    "cpex-encoded-exfil-detection>=0.1.0",
    "cpex-pii-filter>=0.1.0",
    "cpex-retry-with-backoff>=0.1.0",
    "cpex-secrets-detection>=0.1.0",
    "cpex-url-reputation>=0.1.0",
]
```

#### 2.2 Update Configuration Files
Replace plugin `kind` references in all YAML files:

**Before:**
```yaml
kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
```

**After:**
```yaml
kind: "cpex_pii_filter.PIIFilterPlugin"
```

Files to update:
- `plugins/config.yaml`
- `plugins/config-pii-guardian-policy.yaml`
- `plugins/webhook_notification/test_config.yaml`
- `tests/performance/plugins/config.yaml`
- `tests/unit/mcpgateway/plugins/fixtures/configs/init_hooks_plugins_test.yaml`

#### 2.3 Update Container Builds

**Containerfile.lite** changes:
```dockerfile
# BEFORE: Build Rust plugins in-tree
RUN cd plugins_rust && make install

# AFTER: Install from PyPI
RUN uv pip install --system mcp-contextforge-gateway[plugins]
```

Remove Rust build dependencies if no longer needed:
- `cargo`
- `rustc`
- Build tools for Rust compilation

#### 2.4 Update Makefile

Remove or update Rust plugin targets:
```makefile
# Remove these targets (or mark as deprecated)
rust-install:
rust-build:
rust-test:
rust-clean:
rust-verify-stubs:
```

Add deprecation notices:
```makefile
rust-install:
    @echo "⚠️  DEPRECATED: Rust plugins are now PyPI packages"
    @echo "Install with: uv pip install mcp-contextforge-gateway[plugins]"
    @exit 1
```

#### 2.5 Remove In-tree Code

**Python plugins** (after verification):
```bash
rm -rf plugins/encoded_exfil_detection/
rm -rf plugins/pii_filter/
rm -rf plugins/retry_with_backoff/
rm -rf plugins/secrets_detection/
rm -rf plugins/url_reputation/
```

**Rust plugins** (after verification):
```bash
rm -rf plugins_rust/encoded_exfil_detection/
rm -rf plugins_rust/pii_filter/
rm -rf plugins_rust/retry_with_backoff/
rm -rf plugins_rust/secrets_detection/
rm -rf plugins_rust/url_reputation/
```

**Note**: Keep `plugins_rust/rate_limiter/` temporarily as reference, then remove.

#### 2.6 Remove Plugin-specific Tests

Remove tests that import plugin internals:
```bash
# Find and remove tests importing from plugins.*
find tests/ -name "test_*.py" -exec grep -l "from plugins\.(pii_filter|secrets_detection|url_reputation|retry_with_backoff|encoded_exfil_detection)" {} \;
```

Keep integration tests that use plugins via the plugin framework (no internal imports).

### Phase 3: Documentation Updates

#### 3.1 Update Plugin Documentation
- `docs/docs/using/plugins/plugins.md` - Update plugin table entries
- `docs/docs/using/plugins/rust-plugins.md` - Update or deprecate
- `plugins/AGENTS.md` - Update plugin development guidance
- `README.md` - Update installation instructions

**Plugin table updates:**
```markdown
| Plugin | Type | Description |
|--------|------|-------------|
| [PII Filter](https://pypi.org/project/cpex-pii-filter/) | Package | Detects and masks PII |
| [Secrets Detection](https://pypi.org/project/cpex-secrets-detection/) | Package | Detects credentials/secrets |
| [URL Reputation](https://pypi.org/project/cpex-url-reputation/) | Package | URL reputation checks |
| [Retry with Backoff](https://pypi.org/project/cpex-retry-with-backoff/) | Package | Exponential backoff retry |
| [Encoded Exfil Detection](https://pypi.org/project/cpex-encoded-exfil-detection/) | Package | Encoded exfiltration detection |
```

#### 3.2 Update Installation Docs
```markdown
## Installing Plugins

```bash
# Install all plugins
pip install mcp-contextforge-gateway[plugins]

# Or install specific plugins
pip install cpex-pii-filter cpex-secrets-detection
```
```

### Phase 4: Verification & Testing

#### 4.1 Installation Verification
```bash
# Clean environment test
python -m venv test_env
source test_env/bin/activate
pip install mcp-contextforge-gateway[plugins]

# Verify imports
python -c "from cpex_pii_filter import PIIFilterPlugin; print('✓ PII Filter')"
python -c "from cpex_secrets_detection import SecretsDetectionPlugin; print('✓ Secrets Detection')"
python -c "from cpex_url_reputation import URLReputationPlugin; print('✓ URL Reputation')"
python -c "from cpex_retry_with_backoff import RetryWithBackoffPlugin; print('✓ Retry with Backoff')"
python -c "from cpex_encoded_exfil_detection import EncodedExfilDetectorPlugin; print('✓ Encoded Exfil Detection')"
```

#### 4.2 Functional Testing
```bash
# Start gateway with plugins enabled
PLUGINS_ENABLED=true make dev

# Run plugin tests
pytest tests/unit/mcpgateway/plugins/ -v
pytest tests/integration/ -k plugin -v

# Run performance tests
pytest tests/performance/plugins/ -v
```

#### 4.3 Container Testing
```bash
# Build container
docker build -f Containerfile.lite -t contextforge:test .

# Verify plugins available
docker run contextforge:test python -c "from cpex_pii_filter import PIIFilterPlugin; print('OK')"
```

## Migration Checklist

### Pre-Migration
- [ ] Audit current plugin usage in production
- [ ] Document plugin configurations
- [ ] Create backup branch: `git checkout -b pre-plugin-migration`
- [ ] Review plugin dependencies and compatibility

### Per-Plugin Migration
For each plugin (encoded_exfil_detection, pii_filter, retry_with_backoff, secrets_detection, url_reputation):

- [ ] Create PyPI package structure
- [ ] Copy Rust implementation from `plugins_rust/<plugin>/`
- [ ] Copy Python wrapper from `plugins/<plugin>/`
- [ ] Add maturin build configuration
- [ ] Write package README and documentation
- [ ] Add comprehensive tests
- [ ] Build wheels for Linux, macOS, Windows
- [ ] Publish to PyPI (test.pypi.org first)
- [ ] Verify installation from PyPI
- [ ] Update version in pyproject.toml

### Repository Updates
- [ ] Update `pyproject.toml` with all 5 new packages
- [ ] Update all 5 config YAML files
- [ ] Update `Containerfile.lite`
- [ ] Update root `Makefile`
- [ ] Remove in-tree Python plugin code (5 directories)
- [ ] Remove in-tree Rust plugin code (5 directories)
- [ ] Remove plugin-specific tests that import internals
- [ ] Update documentation (4+ files)

### Verification
- [ ] Clean install test in fresh venv
- [ ] Import verification for all 5 plugins
- [ ] Gateway startup with plugins enabled
- [ ] Run full test suite
- [ ] Container build and test
- [ ] Performance benchmarks (compare before/after)

### Post-Migration
- [ ] Update CHANGELOG.md
- [ ] Create migration guide for users
- [ ] Announce deprecation of in-tree plugins
- [ ] Monitor for issues in first release
- [ ] Remove deprecated `plugins_rust/rate_limiter/` reference

## Rollback Plan

If issues arise:

1. **Immediate**: Revert to pre-migration branch
2. **Config-only**: Restore old `kind` references in YAML files
3. **Partial**: Keep PyPI packages, restore in-tree code temporarily
4. **Full**: Unpublish packages (if critical security issue)

## Timeline Estimate

- **Phase 1** (Package Creation): 2-3 days per plugin = 10-15 days
- **Phase 2** (Repository Updates): 2-3 days
- **Phase 3** (Documentation): 1-2 days
- **Phase 4** (Verification): 2-3 days

**Total**: 15-23 days for complete migration

## Success Criteria

1. All 5 plugins available on PyPI
2. Gateway installs and runs with `[plugins]` extra
3. All tests pass (unit, integration, performance)
4. Container builds successfully
5. Documentation updated and accurate
6. No in-tree plugin code remains
7. Build time reduced (no Rust compilation in container)

## Notes

- Follow semantic versioning for packages
- Maintain backward compatibility in plugin APIs
- Consider deprecation period for in-tree plugins
- Monitor PyPI download statistics
- Plan for future plugin additions to PyPI

## References

- Rate Limiter Migration: Commit `dafc9b1fd`
- PyO3 Documentation: https://pyo3.rs/
- Maturin Guide: https://www.maturin.rs/
- PyPI Publishing: https://packaging.python.org/
