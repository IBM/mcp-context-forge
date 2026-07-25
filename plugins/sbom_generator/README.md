# SBOM Generator Plugin

Generates **Software Bill of Materials (SBOM)** for MCP servers in **CycloneDX** or **SPDX** format.  
Enables dependency tracking, license compliance enforcement, and rapid CVE correlation.

## Why

| Problem | This plugin solves it |
|---|---|
| New CVE published | Instantly find every server running the affected package |
| License audit (SOC2, FedRAMP, HIPAA) | Export full SBOM per server on demand |
| Deep dependency trees | Syft enumerates all transitive deps from container images or source |
| Blocked licenses (GPL-3.0, AGPL-3.0) | Fail assessment in `enforce` mode before the server is registered |


## Configuration (`plugins/config.yaml`)

```yaml
plugins:
  - name: "SBOMGeneratorPlugin"
    kind: "plugins.sbom_generator.sbom_generator.SBOMGeneratorPlugin"
    hooks:
      - assessment_post_scan
    mode: "enforce"
    priority: 20

    config:
      syft:
        format: "cyclonedx"        # cyclonedx | spdx
        spec_version: "1.5"
        include_dev_deps: false
        timeout_seconds: 300

      license:
        detect_licenses: true
        blocked_licenses:
          - "GPL-3.0"
          - "AGPL-3.0"
          - "GPL-3.0-only"
          - "GPL-3.0-or-later"
        warn_licenses:
          - "GPL-2.0"
          - "LGPL-3.0"

      storage:
        store_full_sbom: true
        retention_days: 365
        enable_compression: true

      fail_on_blocked_licenses: true
      fail_on_missing_sbom: false
```

## Prerequisites

Install [Syft](https://github.com/anchore/syft):

```bash
# macOS / Linux
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin

# Verify
syft version
```

## Supported Sources

| Source type | Example target | Extractor |
|---|---|---|
| Container image | `nginx:latest` | `ContainerExtractor` |
| Source directory | `dir:/app` or `/app` | `SourceExtractor` |

## Supported Formats

| Format | Spec | Generator class |
|---|---|---|
| CycloneDX JSON | 1.5 | `CycloneDXGenerator` |
| SPDX JSON | 2.3 | `SPDXGenerator` |

## Query APIs

### Find servers affected by a CVE

```python
from plugins.sbom_generator.query import CVECorrelation
from plugins.sbom_generator.storage import SBOMRepository

repo = SBOMRepository(db_session)
cve_correlation = CVECorrelation(repo)

# Find servers affected by a specific package
affected = cve_correlation.find_affected_by_component(
    name="requests",
    version="2.28.0",
    ecosystem="python",
)
# [AffectedServer(server_id="...", component_version="2.28.0", ...), ...]

# Or search by version range
affected_range = cve_correlation.find_affected_by_version_range(
    name="requests",
    min_version="2.0.0",
    max_version="2.31.0",
)
```

### Search components

```python
from plugins.sbom_generator.query import ComponentSearch

results = ComponentSearch(repo).search(name="requests", ecosystem="python")
```

### License compliance report

```python
from plugins.sbom_generator.query import LicenseAnalyzer
from plugins.sbom_generator.models import LicensePolicy

policy = LicensePolicy(blocked=["GPL-3.0", "AGPL-3.0"], flagged=["GPL-2.0"])
analyzer = LicenseAnalyzer(repo, policy)

summary = analyzer.global_summary()       # across all SBOMs
report  = analyzer.server_report("srv-1") # single server
```

## Package Structure

```
plugins/sbom_generator/
├── sbom_generator.py          # SBOMGeneratorPlugin — gateway hook entry point
├── config.py                  # Pydantic config (SBOMGeneratorConfig)
├── errors.py                  # Custom exception hierarchy
├── models.py                  # Domain dataclasses (SBOMComponent, SBOMDocument, …)
├── extraction/
│   ├── base.py                # BaseExtractor ABC
│   ├── syft_wrapper.py        # Async Syft CLI subprocess wrapper
│   ├── container_extractor.py # Extracts from container images
│   └── source_extractor.py    # Extracts from source directories
├── generation/
│   ├── base.py                # BaseGenerator ABC
│   ├── cyclonedx.py           # CycloneDX 1.5 JSON generator
│   └── spdx.py                # SPDX 2.3 JSON generator
├── query/
│   ├── component_search.py    # Search components across stored SBOMs
│   ├── cve_correlation.py     # Find servers affected by a CVE
│   └── license_analyzer.py   # License compliance reports
├── storage/
│   ├── models.py              # SQLAlchemy ORM models
│   └── repository.py          # CRUD + query operations
└── utils/
    ├── purl_generator.py      # PURL construction and parsing
    └── version_parser.py      # Version comparison and CVE range checks
```

## Running Tests

Unit tests (query, storage, models):
```bash
pytest tests/unit/plugins/sbom_generator/query/ -v        # 52 tests
pytest tests/unit/plugins/sbom_generator/ -v              # All unit tests
```

Integration tests (API endpoints, end-to-end workflows):
```bash
pytest tests/integration/test_sbom_e2e.py -v              # 15 tests
pytest tests/integration/test_sbom_api.py -v              # 30 tests
```

All tests run without Syft installed — the CLI is mocked in extraction tests.

Coverage report:
```bash
pytest tests/unit/plugins/sbom_generator/query/ tests/integration/test_sbom_e2e.py \
       --cov=plugins.sbom_generator --cov-report=term-missing
```

## Related Issues

- [#2215](https://github.com/IBM/mcp-context-forge/issues/2215) — Epic: MCP Server Security Posture Assessment
- [#2216](https://github.com/IBM/mcp-context-forge/issues/2216) — Container Vulnerability Scanner (Trivy/Grype)
- [#2217](https://github.com/IBM/mcp-context-forge/issues/2217) — Source Code Scanner (Semgrep/Bandit)

## References

- [CycloneDX Specification](https://cyclonedx.org/specification/overview/)
- [SPDX Specification](https://spdx.github.io/spdx-spec/)
- [Syft Documentation](https://github.com/anchore/syft)
- [NTIA SBOM Minimum Elements](https://www.ntia.gov/page/software-bill-materials)
- [PURL Specification](https://github.com/package-url/purl-spec)