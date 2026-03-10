# Security Testing (OWASP & DAST)

ContextForge includes a two-layer security test suite focused on
**OWASP A01:2021 – Broken Access Control**.  The layers are independent:
Layer 1 runs in every CI environment with no extra infrastructure; Layer 2
requires a running OWASP ZAP daemon.

---

## Testing Pyramid Placement

| Layer | Tool | Marker | Requires |
|-------|------|--------|----------|
| Layer 1 – direct access control | Playwright / pytest | `owasp_a01` | Gateway only |
| Layer 2 – ZAP DAST | OWASP ZAP + pytest | `owasp_a01_zap` | `make testing-up` |

---

## Layer 1 — Direct Access Control Tests

**Location:** `tests/playwright/security/owasp/test_a01_broken_access_control.py`

These tests call the gateway's REST API directly via Playwright's
`APIRequestContext`.  No browser, no proxy, no ZAP.

| Attack pattern | CWE | What is checked |
|----------------|-----|-----------------|
| Force browsing | CWE-284, CWE-862 | 7 protected endpoints return 401 for anonymous requests |
| IDOR / cross-user | CWE-639 | User A token cannot read User B's private resources |
| Cross-tenant | CWE-639, CWE-285 | Team-A-scoped token cannot see Team-B resources |
| Vertical privilege escalation | CWE-269, CWE-285 | Non-admin tokens are rejected by admin-only APIs |
| JWT tampering | CWE-345, CWE-287 | Unsigned, payload-modified, expired, `alg=none`, wrong `iss`/`aud` |
| HTTP method access control | CWE-284 | Non-admin cannot mutate publicly readable resources |
| CORS enforcement | CWE-942 | No wildcard or reflected `Access-Control-Allow-Origin` for arbitrary origins |

### Running Layer 1

```bash
# Requires the gateway to be running (make dev or make testing-up)
make test-owasp
```

The target defaults to `http://localhost:8080`.  Override with:

```bash
TEST_BASE_URL=http://localhost:4444 make test-owasp
```

---

## Layer 2 — ZAP DAST Integration

**Location:** `tests/playwright/security/owasp/test_a01_zap_dast.py`

ZAP acts as an active scanner.  The test suite:

1. Seeds ZAP's site tree by directly accessing each protected path
   (`zap.core.access_url`) — necessary because ZAP's traditional spider
   follows HTML hyperlinks and cannot discover REST API endpoints on its own.
2. Runs ZAP's traditional spider to catch any additional HTML/UI paths.
3. Waits for the **passive scan** queue to drain, then asserts no
   HIGH/CRITICAL A01 alerts.
4. Runs the **active scan** (attack payloads) and asserts no CRITICAL A01
   alerts.
5. Writes a JSON report to `tests/reports/`.

### Prerequisites

Start the testing stack and the ZAP DAST daemon:

```bash
make testing-up        # gateway + nginx + Locust + test servers
make testing-zap-up    # OWASP ZAP daemon (separate profile)
```

ZAP runs in its own `dast` Docker Compose profile to avoid pulling the
heavyweight image and reserving memory during normal test runs.
Wait for it to become healthy — ZAP's JVM takes 30–45 seconds to start.

### Running Layer 2

```bash
make test-zap
```

This sets the required environment variables automatically and runs only the
`owasp_a01_zap` marker.  To run manually:

```bash
ZAP_BASE_URL=http://localhost:8090 \
ZAP_API_KEY=changeme \
ZAP_TARGET_URL=http://host.docker.internal:8080 \
pytest tests/playwright/security/owasp/ -v -m owasp_a01_zap
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ZAP_BASE_URL` | *(unset — skips ZAP tests)* | ZAP API daemon URL, host-visible (e.g. `http://localhost:8090`) |
| `ZAP_API_KEY` | `changeme` | ZAP API key configured in docker-compose |
| `TEST_BASE_URL` | `http://localhost:8080` | Gateway URL, host-visible (used for preflight health check) |
| `ZAP_TARGET_URL` | `http://host.docker.internal:8080` | Gateway URL as seen from inside the ZAP container |

!!! note "Why two URL variables?"
    `TEST_BASE_URL` is the host-visible address used by the Python test process
    for health checks and result verification.  `ZAP_TARGET_URL` is the address
    ZAP itself uses when spidering and scanning — inside Docker, `localhost`
    resolves to the ZAP container, not the host.
    `host.docker.internal:8080` is the correct Docker-to-host address on macOS
    and Windows.  On Linux, use the host's Docker bridge IP (typically
    `172.17.0.1`).

### Authentication

ZAP authenticates automatically.  At startup the `zap` fixture:

1. Generates an admin JWT using the application's own `create_jwt_token`
   utility (`teams=None` + `is_admin=True` → admin bypass scope).
2. Installs it as a permanent `Authorization: Bearer <token>` header on all
   ZAP outbound requests via ZAP's **Replacer** add-on.

No manual login or session configuration is required.

### Scan Resilience

The test suite imports the full OpenAPI spec (300+ paths) into ZAP.  The
default Docker memory limit is 16 GB.  The **passive scan** completes
reliably at this limit and covers the full API surface.  The **active scan**
(attack payloads against every endpoint) may time out or OOM on very large
APIs and is skipped gracefully when this happens:

- If ZAP disconnects mid-scan, the polling loop breaks and proceeds with
  partial results.
- After the scan, the test reconnects via a fresh ZAP client (ZAP restarts
  automatically via `restart: unless-stopped`).
- If ZAP is still unreachable after reconnecting, the test is **skipped**
  with a message indicating the memory limit.

### Reports

JSON alert reports are written to `tests/reports/` after each scan phase:

| File pattern | Contents |
|---|---|
| `zap_a01_passive_failures_<ts>.json` | HIGH/CRITICAL A01 alerts from passive scan |
| `zap_a01_active_critical_<ts>.json` | CRITICAL A01 alerts from active scan |
| `zap_a01_full_report_<ts>.json` | All A01 alerts regardless of severity |

---

## Skipping ZAP Tests in CI

ZAP tests are skipped automatically when `ZAP_BASE_URL` is not set.
Standard CI runs (`make test`) do not set this variable, so only Layer 1
runs.  Enable Layer 2 in CI by adding a ZAP daemon service to your pipeline
and setting `ZAP_BASE_URL` before running `make test-zap`.

---

## See Also

- [OWASP Top 10 A01:2021](https://owasp.org/Top10/A01_2021-Broken_Access_Control/)
- [RBAC guide](../manage/rbac.md)
- [Security features](../architecture/security-features.md)
- [Performance / load testing](performance.md)
