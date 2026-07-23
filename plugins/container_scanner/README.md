# Container Scanner Plugin

Scans container images for CVEs before gateway registration and runtime deployment using [Trivy](https://github.com/aquasecurity/trivy) or [Grype](https://github.com/anchore/grype).

## Overview

The plugin intercepts two gateway lifecycle hooks:

- **`server_pre_register`** — blocks registration of a new MCP server if its image fails policy
- **`runtime_pre_deploy`** — blocks deployment at runtime if the image fails policy

Both hooks run the same pipeline: cache check → auth resolution → scanner execution → policy evaluation → result persistence.

## Pipeline

```
Hook trigger
  └── CacheManager.lookup(image_digest)       # skip scan if result is fresh
        └── AuthResolver.resolve(image_ref)   # inject registry credentials
              └── TrivyRunner / GrypeRunner   # run scanner CLI, parse JSON
                    └── PolicyEvaluator       # filter by threshold, CVE ignore list
                          └── ScanResultRepository.save()   # persist result
                                └── return allow / block decision
```

Scan errors (CLI crash, timeout, image not found) are handled separately from policy violations — see `scan_error` vs `reason` in the result.

## Directory Structure

```
plugins/container_scanner/
├── container_scanner.py        # Plugin entry point, hook handlers
├── config.py                   # ScannerConfig and RegistryConfig models
├── types.py                    # Vulnerability, Summary, ScanResult schemas
├── auth/
│   └── auth_resolver.py        # Resolves registry credentials from env vars
├── cache/
│   └── cache_manager.py        # Digest-keyed TTL cache
├── policy/
│   └── policy_evaluator.py     # Severity filtering and block/audit decision
├── scanners/
│   ├── base.py                 # ScannerRunner interface
│   ├── trivy_runner.py
│   └── grype_runner.py
└── storage/
    └── repository.py           # In-memory result store + shared singleton
```

## Configuration

Add to `plugins/config.yaml`:

```yaml
- name: "ContainerScannerPlugin"
  kind: "plugins.container_scanner.container_scanner.ContainerScannerPlugin"
  hooks: ["server_pre_register", "runtime_pre_deploy"]
  mode: "enforce"       # enforce | audit | disabled
  priority: 5
  config:
    scanner: "trivy"              # trivy | grype
    severity_threshold: "HIGH"   # CRITICAL | HIGH | MEDIUM | LOW
    fail_on_unfixed: false        # if false, vulns with no fix are ignored
    ignore_cves: []               # list of CVE IDs to suppress
    timeout_seconds: 300
    mode: "enforce"
    cache_enabled: true
    cache_ttl_hours: 24
    on_scan_error: "fail_closed"  # fail_closed | fail_open
    registries: []                # per-registry auth (see below)
```

### Registry Authentication

```yaml
registries:
  - url: "ghcr.io"
    auth_type: "token"
    token_env: "GHCR_TOKEN"          # env var name, not the token value

  - url: "registry.example.com"
    auth_type: "basic"
    username_env: "REG_USER"
    password_env: "REG_PASS"
```

Credentials are read from environment variables at scan time — never stored in config.

### Mode Reference

| Mode | Effect |
|------|--------|
| `enforce` | Blocks deployment when policy is violated |
| `audit` | Allows deployment but records the violation |
| `disabled` | Skips scanning entirely |

### `on_scan_error` Reference

| Value | Effect |
|-------|--------|
| `fail_closed` | Block deployment if the scanner CLI fails (safe default) |
| `fail_open` | Allow deployment but record the error in `scan_error` |

## REST API

Scan results are accessible via the admin API (requires authentication):

| Endpoint | Description |
|----------|-------------|
| `GET /container-scanner/health` | Liveness check and result count |
| `GET /container-scanner/scans` | All results, most recent first |
| `GET /container-scanner/scans/{image_ref}` | Result for a specific image ref or digest |
| `POST /scan` | Manually trigger a scan; body: `{"image_ref": "...", "image_digest": null}` |

Each result includes a `vulnerabilities` array with full CVE detail:

```json
{
  "image_ref": "ghcr.io/org/app:v1",
  "blocked": true,
  "vulnerability_count": 2,
  "vulnerabilities": [
    {
      "cve_id": "CVE-2023-0001",
      "severity": "CRITICAL",
      "package_name": "libssl",
      "installed_version": "1.1.1t-r0",
      "fixed_version": "1.1.1u-r0",
      "description": "OpenSSL vulnerability..."
    }
  ]
}
```

Example:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/container-scanner/scans/ghcr.io/org/app:v1
```

## Admin UI

The container scanner ships its own self-contained dashboard, served by the plugin's MCP server on a dedicated port.

### Starting the server

```bash
# Default port (8000)
python -m plugins.container_scanner.server

# Custom port
PLUGINS_SERVER_PORT=8100 python -m plugins.container_scanner.server
```

Then open **`http://localhost:8000/`** (or the port you set) in a browser.

### Summary table

The table shows one row per scanned image, most recent first. Click the `▸` arrow on any row to expand it.

| Column | Description |
|--------|-------------|
| Scan Time | UTC timestamp of when the scan ran |
| Image | `image_ref` (digest shown on a second line if available) |
| Scanner | `trivy` or `grype` |
| Status | **Allowed** (green), **Blocked** (red), or **Error** (yellow) with the policy reason truncated below |
| Critical / High / Medium / Low | CVE counts by severity, coloured red → orange → yellow → grey |
| Duration | Scanner subprocess wall time in ms |

### Vulnerability detail (expandable)

Clicking a row expands an inline panel showing every individual CVE finding:

| Column | Description |
|--------|-------------|
| CVE | CVE identifier (e.g. `CVE-2023-0001`) |
| Severity | Colour-coded: **CRITICAL** (red), **HIGH** (orange), **MEDIUM** (yellow), **LOW** (grey) |
| Package | Vulnerable package name |
| Installed | Currently installed version |
| Fixed Version | Remediation target in green, or *"no fix available"* if none exists |
| Description | Full CVE description (truncated; hover for full text) |

If the scanner encountered an error, the expanded panel shows the raw error message instead of a CVE table.

If no results are present, the UI shows a prompt to register a server with a container image reference to trigger the first scan.

> Results are held in memory and reset when the gateway restarts. Use the REST API to export them before restarting if persistence is needed.

## Policy Evaluation

Vulnerabilities are filtered in order:

1. **Severity threshold** — drop vulns below `severity_threshold`
2. **CVE ignore list** — drop CVE IDs in `ignore_cves`
3. **Unfixed filter** — if `fail_on_unfixed: false`, drop vulns with no `fixed_version`
4. **Mode decision** — `enforce` blocks if any violations remain; `audit` records but allows

## Caching

The cache is keyed by `image_digest` (not by tag). Tag-based caching is not supported — if no digest is available, the cache is skipped entirely. Cached vulnerability lists are re-evaluated against the current policy on every hit, so changing `severity_threshold` takes effect without re-scanning.

## Prerequisites

At least one scanner must be installed and on `PATH`:

```bash
# Trivy (recommended)
brew install aquasecurity/trivy/trivy   # macOS
# or: https://github.com/aquasecurity/trivy/releases

# Grype (alternative)
brew install anchore/grype/grype
# or: https://github.com/anchore/grype/releases
```

## Running Tests

```bash
# Unit tests
pytest tests/unit/plugins/test_container_scanner/ -v

# Integration tests (hook → API end-to-end)
pytest tests/integration/test_container_scanner/ -v
```
