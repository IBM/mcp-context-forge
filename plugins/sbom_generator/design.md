# SBOM Generator Plugin — Design Document

## 1. Overview

The SBOM Generator is a native gateway plugin that hooks into the `assessment_post_scan`
phase of the MCP server lifecycle. Its job is to produce a **Software Bill of Materials
(SBOM)** — a structured inventory of every dependency in an MCP server — and persist it
for later querying, licence auditing, and CVE correlation.

---

## 2. Goals

| Goal | Notes |
|---|---|
| Generate CycloneDX 1.5 or SPDX 2.3 SBOMs | Format is configurable per deployment |
| Support container images and source directories | Both are common MCP server delivery mechanisms |
| Enforce licence policy at registration time | Block servers with GPL-3.0 / AGPL-3.0 before they are admitted |
| Enable rapid CVE response | Given a package + version range, return all affected servers in one query |
| Zero blocking of the gateway event loop | All Syft invocations are async subprocesses |

---

## 3. Non-Goals

- **Does not perform vulnerability scanning** — that is the responsibility of the
  Container Vulnerability Scanner plugin (#2216) and the Source Code Scanner (#2217).
- **Does not call any external CVE database** — CVE correlation is a pure in-database
  query against already-stored SBOMs.
- **Does not support SBOM merging or diffing** — out of scope for v0.1.0.

---

## 4. Data Flow

```
MCP Server Assessment
        │
        ▼
assessment_post_scan(context, payload)
        │
        ├─1─▶ Extract dependencies
        │         ContainerExtractor  →  syft <image> -o cyclonedx-json
        │         SourceExtractor     →  syft dir:<path> -o cyclonedx-json
        │         (async subprocess, timeout enforced)
        │         returns: ExtractionResult[SBOMComponent]
        │
        ├─2─▶ Generate SBOM document
        │         CycloneDXGenerator  →  SBOMDocument (format=cyclonedx)
        │         SPDXGenerator       →  SBOMDocument (format=spdx)
        │         returns: SBOMDocument
        │
        ├─3─▶ Validate licences
        │         LicensePolicy.validate_licenses(licences)
        │         blocked → PluginViolation (if fail_on_blocked_licenses=true)
        │         flagged → logged as warning
        │
        ├─4─▶ Store SBOM
        │         SBOMRepository.create_sbom(server_id, sbom_doc)
        │         SBOMDocumentDB  +  SBOMComponentDB rows committed
        │
        └─5─▶ Return result metadata
                  {sbom_id, component_count, format, licenses: {blocked, flagged}}
```

---

## 5. Module Responsibilities

### `sbom_generator.py`
The plugin entry point. Owns the `assessment_post_scan` hook and orchestrates the
four steps above. Translates internal errors into `PluginViolation` where appropriate.
Does **not** contain extraction, generation, or storage logic directly.

### `extraction/`
Responsible for obtaining raw dependency data from a target.

- **`base.py`** — `BaseExtractor` ABC with `extract(target)` and `supports(target)`.
- **`syft_wrapper.py`** — thin async wrapper around the Syft CLI. All subprocess
  management (launch, timeout, stdout capture, JSON parse) lives here so extractors
  stay focused on routing and result mapping.
- **`container_extractor.py`** — routes container image references to Syft, maps
  Syft CycloneDX JSON output to `SBOMComponent` dataclasses.
- **`source_extractor.py`** — same as above but for `dir:<path>` targets. Validates
  directory existence before invoking Syft.

**Why Syft?** Syft has first-class support for Python, npm, Go, Rust, and system
packages from a single binary, produces both CycloneDX and SPDX JSON natively, and
is actively maintained by Anchore. Wrapping it as a subprocess avoids importing
large native libraries into the gateway process.

### `generation/`
Responsible for transforming an `ExtractionResult` into a standard SBOM document.

- **`base.py`** — `BaseGenerator` ABC with `generate()` and `serialise()`.
- **`cyclonedx.py`** — produces a CycloneDX 1.5 JSON structure. The `metadata.component`
  field is populated with the MCP server name/version so the SBOM is self-describing.
- **`spdx.py`** — produces an SPDX 2.3 JSON structure. Each component becomes an SPDX
  Package with a `purl` external reference and `DESCRIBES` relationship from the document.

The generator layer is intentionally decoupled from extraction: it takes an
`ExtractionResult` and knows nothing about whether the source was a container or a
directory. This makes both generators independently testable with synthetic data.

### `storage/`
Responsible for persisting SBOMs and exposing query primitives.

- **`models.py`** — SQLAlchemy ORM models. `SBOMDocumentDB` owns the full JSON blob
  and top-level metadata. `SBOMComponentDB` stores individual packages as indexed rows
  to enable efficient `WHERE name = ? AND ecosystem = ?` queries without JSON parsing.
  `SBOMVulnerabilityDB` is reserved for a future CVE feed ingestion feature.
- **`repository.py`** — all database I/O. The `find_affected_servers` method performs
  a coarse SQL filter (name + optional ecosystem); precise version range logic is applied
  in Python by `version_parser.is_vulnerable` to avoid relying on SQL string ordering.

### `query/`
High-level query objects that compose the repository with domain logic.

- **`component_search.py`** — `ComponentSearch` wraps repository search with result
  mapping to `ComponentSearchResult` dataclasses suitable for JSON API responses.
- **`cve_correlation.py`** — `CVECorrelation.find_affected()` is the implementation of
  US-2 (`GET /sbom/affected?package=requests&version_lt=2.31.0`). It requires at least
  one version constraint and deduplicates results by `(server_id, component_version)`.
- **`license_analyzer.py`** — `LicenseAnalyzer` produces both a global summary across
  all stored SBOMs and a per-server compliance report, using the same `LicensePolicy`
  instance that the plugin uses at assessment time.

### `utils/`
Stateless helpers with no external dependencies.

- **`purl_generator.py`** — constructs, validates, and parses Package URLs (PURLs) per
  the [purl-spec](https://github.com/package-url/purl-spec). Used by extractors when
  Syft does not emit a PURL for a component.
- **`version_parser.py`** — PEP-440 aware version comparison via `packaging.version`.
  Strips `v`/`V` prefixes so Go and Rust version strings compare correctly. Falls back
  to lexicographic ordering if `packaging` is unavailable.

---

## 6. Key Design Decisions

### 6.1 Syft as a subprocess, not a library
Syft is written in Go. Calling it as a subprocess isolates its memory footprint, avoids
CGo complexity, and means the gateway never crashes due to Syft bugs. The tradeoff is
process-launch overhead (~200–500 ms for small images), which is acceptable for an
assessment hook that runs once per server registration.

### 6.2 Component rows alongside full SBOM JSON
`SBOMComponentDB` duplicates data already present in `document_json`. This is intentional:
the component table enables indexed SQL queries for CVE correlation and licence analysis
without deserialising potentially large JSON blobs on every request.

### 6.3 Python-side version comparison
SQL string comparison of version numbers is unreliable (`"2.9" > "2.10"` in ASCII order).
The repository performs a broad SQL filter (package name match), then `is_vulnerable()`
applies PEP-440 semantics in Python. The extra rows fetched are negligible for typical
deployment sizes.

### 6.4 Format-agnostic domain model
`SBOMDocument` and `SBOMComponent` are plain Python dataclasses that carry no
format-specific fields. Both `CycloneDXGenerator` and `SPDXGenerator` read from the
same model and emit format-specific JSON. This means switching a deployment from
CycloneDX to SPDX requires only a config change, not a code change.

### 6.5 Licence enforcement at assessment time
Blocked licences raise a `PluginViolation` before the server is stored, not after.
This is the correct place to enforce policy — consistent with how the existing
`SecretsDetectionPlugin` and `PIIFilterPlugin` operate.

---

## 7. Error Handling Strategy

| Error type | Source | Behaviour |
|---|---|---|
| `ExtractionError` | Syft not found, timeout, non-zero exit | `PluginViolation` if `fail_on_missing_sbom=true`, else logged and skipped |
| `GenerationError` | Malformed extraction result | Same as above |
| `StorageError` | DB unavailable | Always raises `PluginViolation` — SBOM must be persisted |
| `LicenseBlockedError` (via `PluginViolation`) | Blocked licence found | Always raises if `fail_on_blocked_licenses=true` |
| Unexpected `Exception` | Anything else | Always raises `PluginViolation` |

---

## 8. Testing Strategy

All 140 unit tests run without Syft installed. The Syft CLI is mocked via
`unittest.mock.AsyncMock` in extraction tests so the suite is fully hermetic and
suitable for CI environments without Docker or Go tooling.

| Test file | What it covers |
|---|---|
| `test_purl_generator.py` | PURL construction, validation, parsing, roundtrip |
| `test_version_parser.py` | Normalisation, comparison operators, CVE range checks |
| `test_generation.py` | CycloneDX and SPDX output structure, edge cases |
| `test_extraction.py` | ABC enforcement, `supports()` routing, Syft output parsing, async extract |
| `test_query.py` | CVE correlation, component search, licence analysis with mock repository |

---

## 9. Future Work

- **SBOM export endpoint** — `GET /sbom/{id}/export?format=cyclonedx` to download the
  full SBOM JSON for compliance audits.
- **Admin UI** — table view of stored SBOMs with per-server drill-down.
- **CVE feed ingestion** — populate `SBOMVulnerabilityDB` from NVD/OSV feeds and
  surface affected servers automatically on new CVE publication.
- **SBOM diff** — compare two SBOMs for a server to highlight dependency changes between
  assessments.
- **Compression** — the `is_compressed` flag in `SBOMDocumentDB` is reserved for gzip
  compression of `document_json`; not yet implemented.