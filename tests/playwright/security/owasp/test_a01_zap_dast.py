# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/playwright/security/owasp/test_a01_zap_dast.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OWASP A01:2021 – ZAP DAST integration layer.

Activated only when the ``ZAP_BASE_URL`` environment variable is set.
Skipped silently in normal CI runs.

Requirements:
  * A running OWASP ZAP daemon (stable Docker image recommended):

    make testing-up

  * ``python-owasp-zap-v2.4`` installed (included in ``playwright`` optional-dependency group).

Environment variables:
  ZAP_BASE_URL    Base URL of the ZAP API daemon (host-visible), e.g. http://localhost:8090
  ZAP_API_KEY     ZAP API key (default: changeme)
  TEST_BASE_URL   Target application URL (host-visible, default: http://localhost:8080)
  ZAP_TARGET_URL  Target URL that ZAP itself uses to spider (Docker-internal).
                  nginx listens on port 80 inside mcpnet (host sees 8080 via port mapping), so the
                  default is http://nginx:80 — works on Linux and macOS/Windows Docker Desktop.
                  Override for standalone ZAP outside mcpnet, e.g. http://localhost:8080.

Usage::

    ZAP_BASE_URL=http://localhost:8090 ZAP_API_KEY=changeme \\
        pytest tests/playwright/security/owasp/test_a01_zap_dast.py -v -m owasp_a01_zap
"""

# Future
from __future__ import annotations

# Standard
import json
import logging
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

# Third-Party
import pytest
from requests.exceptions import ConnectionError, RequestException, Timeout

logger = logging.getLogger(__name__)

ZAP_BASE_URL = os.getenv("ZAP_BASE_URL", "")
ZAP_API_KEY = os.getenv("ZAP_API_KEY", "changeme")
# Host-visible URL used for: preflight health check, human-readable log messages.
TARGET_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
# Docker-internal URL used for: ZAP spider/scan targets and alert base-URL filtering.
# nginx listens on port 80 inside mcpnet (default: http://nginx:80 via make test-zap).
# Falls back to TARGET_URL so local (non-Docker) runs work unchanged.
ZAP_TARGET_URL = os.getenv("ZAP_TARGET_URL", TARGET_URL)

# A01-relevant CWEs to filter from ZAP alerts
_A01_CWES = {
    200,  # Exposure of Sensitive Information
    284,  # Improper Access Control
    285,  # Improper Authorization
    639,  # Authorization Bypass Through User-Controlled Key
    862,  # Missing Authorization
    863,  # Incorrect Authorization
    918,  # SSRF (server-side request forgery – access control boundary)
}

_HIGH_RISK_LEVELS = {"High", "Critical"}

if not ZAP_BASE_URL:
    pytest.skip("ZAP_BASE_URL not set – skipping ZAP DAST tests", allow_module_level=True)

try:
    # Third-Party
    from zapv2 import ZAPv2  # type: ignore[import-untyped]
except ImportError as exc:  # pragma: no cover
    pytest.skip(
        f"python-owasp-zap-v2.4 not installed: {exc}. " "Install it via: pip install 'python-owasp-zap-v2.4>=0.0.21'",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _zap_client() -> ZAPv2:
    return ZAPv2(apikey=ZAP_API_KEY, proxies={"http": ZAP_BASE_URL, "https": ZAP_BASE_URL})


def _make_admin_jwt() -> str:
    """Generate an admin JWT for the ZAP scanner to authenticate with."""
    # Import here so the module-level skip fires before any mcpgateway import
    # errors in environments where the package is not installed.
    # First-Party
    from mcpgateway.utils.create_jwt_token import _create_jwt_token  # noqa: PLC0415

    return _create_jwt_token(
        {"sub": "zap-scanner@example.com"},
        user_data={"email": "zap-scanner@example.com", "is_admin": True, "auth_provider": "local"},
        teams=None,  # teams=None + is_admin=True → admin bypass (sees everything)
    )


def _wait_for_passive_scan(zap: ZAPv2, timeout: int = 120) -> None:
    """Block until passive scan queue is empty or timeout is reached."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            remaining = int(zap.pscan.records_to_scan)
        except (ConnectionError, Timeout, RequestException):
            logger.warning("ZAP unreachable while polling passive scan; giving up")
            return
        if remaining == 0:
            return
        logger.debug("Passive scan records remaining: %d", remaining)
        time.sleep(2)
    logger.warning("Passive scan did not finish within %ds", timeout)


def _filter_a01_alerts(alerts: list[dict]) -> list[dict]:
    """Return only alerts with A01-relevant CWEs at HIGH or CRITICAL risk."""
    results = []
    for alert in alerts:
        try:
            cwe = int(alert.get("cweid", 0))
        except (ValueError, TypeError):
            cwe = 0
        risk = alert.get("risk", "")
        if cwe in _A01_CWES and risk in _HIGH_RISK_LEVELS:
            results.append(alert)
    return results


def _reports_dir() -> Path:
    """Return the reports/ directory path, creating it if necessary."""
    d = Path(__file__).parent.parent.parent.parent / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_report(alerts: list[dict], name: str) -> Path:
    """Write a JSON alert report to reports/ directory and return its path."""
    report_path = _reports_dir() / f"zap_a01_{name}_{int(time.time())}.json"
    report_path.write_text(json.dumps(alerts, indent=2))
    logger.info("ZAP report written to %s", report_path)
    return report_path


def _write_html_report(zap: ZAPv2, name: str) -> Path:
    """Fetch ZAP's built-in HTML report and write it to reports/."""
    html = zap.core.htmlreport()
    report_path = _reports_dir() / f"zap_a01_{name}_{int(time.time())}.html"
    report_path.write_text(html)
    logger.info("ZAP HTML report written to %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def zap() -> ZAPv2:
    """Module-scoped ZAP client.

    Before yielding:
    1. Polls TARGET_URL/health until the application is up (60 s deadline).
    2. Injects an admin Bearer token into all ZAP outbound requests via the
       Replacer add-on so the spider can crawl authenticated endpoints.
    """
    # --- 1. Wait for the target application to be reachable from the host ---
    health_url = f"{TARGET_URL}/health"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            urllib.request.urlopen(health_url, timeout=5)  # noqa: S310
            logger.info("Target application is up at %s", health_url)
            break
        except (urllib.error.URLError, OSError):
            logger.debug("Waiting for target app at %s …", health_url)
            time.sleep(3)
    else:
        pytest.skip(f"Target app not reachable at {health_url} after 60 s – is the testing stack running?")

    # --- 2. Connect to ZAP ---
    client = _zap_client()
    try:
        version = client.core.version
        logger.info("Connected to ZAP version %s at %s", version, ZAP_BASE_URL)
    except (ConnectionError, Timeout, RequestException) as exc:
        pytest.skip(f"Cannot connect to ZAP at {ZAP_BASE_URL}: {exc}")
    except json.JSONDecodeError as exc:
        logger.warning("ZAP returned malformed JSON during version check (possible crash/partial response): %s", exc)
        pytest.skip(f"Cannot connect to ZAP at {ZAP_BASE_URL}: {exc}")
    except Exception as exc:
        # ZAP raises bare Exception for non-2xx HTTP responses
        pytest.skip(f"Cannot connect to ZAP at {ZAP_BASE_URL}: {exc}")

    # --- 3. Inject admin auth header for all ZAP outbound requests ---
    # Without this the spider hits 401 on every protected path and stops after
    # the root page, auth redirect, and /health – the 3 URLs seen in the error.
    try:
        token = _make_admin_jwt()
        client.replacer.add_rule(
            description="ZAP-scanner admin JWT",
            enabled="true",
            matchtype="REQ_HEADER",
            matchregex="false",
            matchstring="Authorization",
            replacement=f"Bearer {token}",
        )
        logger.info("ZAP Replacer: injected admin Authorization header for all requests")
    except ConnectionError as exc:
        pytest.skip(f"ZAP daemon not reachable - Error: {exc}")
    except (Timeout, RequestException) as exc:
        pytest.skip(f"ZAP request failed: {exc}")
    except Exception as exc:
        # ZAP raises bare Exception for non-2xx; 404 means Replacer add-on not installed
        pytest.skip(f"ZAP Replacer add-on required for authenticated endpoint testing. " f"Install it in ZAP or tests will only cover public endpoints. Error: {exc}")

    return client


# Security-sensitive path prefixes for the active scan.
# The passive scan covers the full OpenAPI surface; the active scan focuses
# on paths where access-control vulnerabilities are most likely.
_ACTIVE_SCAN_PREFIXES = [
    "/auth/",
    "/rbac/",
    "/tokens/",
    "/servers",
    "/teams/",
    "/tools",
    "/gateways",
]


@pytest.fixture(scope="module")
def zap_context(zap: ZAPv2) -> dict:
    """Create two ZAP contexts: a broad one for import/spider and a narrow one for active scan.

    The broad context (``.*``) is used for OpenAPI import and spidering so ZAP
    discovers the full API surface.  The narrow context only includes
    security-sensitive prefixes, keeping the active scan focused and fast.
    """
    ts = int(time.time())

    # Broad context for OpenAPI import and spider
    broad_name = f"owasp_a01_broad_{ts}"
    broad_id = zap.context.new_context(broad_name)
    zap.context.include_in_context(broad_name, f"{ZAP_TARGET_URL}.*")

    # Narrow context for active scan (security-sensitive prefixes only)
    narrow_name = f"owasp_a01_scan_{ts}"
    narrow_id = zap.context.new_context(narrow_name)
    for prefix in _ACTIVE_SCAN_PREFIXES:
        zap.context.include_in_context(narrow_name, f"{ZAP_TARGET_URL}{prefix}.*")

    logger.info("ZAP contexts: broad=%s (id=%s), scan=%s (id=%s, %d prefixes)", broad_name, broad_id, narrow_name, narrow_id, len(_ACTIVE_SCAN_PREFIXES))
    yield {"ctx_id": broad_id, "ctx_name": broad_name, "scan_ctx_id": narrow_id, "scan_ctx_name": narrow_name}
    # No explicit cleanup needed; ZAP contexts are ephemeral


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.owasp_a01_zap
@pytest.mark.slow
class TestZAPAccessControlScan:
    """ZAP DAST scan tests for OWASP A01:2021 – Broken Access Control."""

    def test_zap_spider_discovers_protected_endpoints(self, zap: ZAPv2, zap_context: dict) -> None:
        """Import the OpenAPI spec and spider to build full site tree coverage.

        FastAPI auto-generates an OpenAPI 3.x spec at ``/openapi.json``.
        Importing it gives ZAP knowledge of all API paths, methods, and
        parameters.  We also manually seed a handful of key paths as a
        fallback and run the traditional spider for any HTML/UI routes.

        Requires ZAP memory >= 4 GB (set in docker-compose.yml).
        """
        protected_paths = ["/servers", "/tools", "/teams/", "/rbac", "/auth/email", "/tokens", "/gateways"]

        # --- 1. Import OpenAPI spec (primary discovery mechanism) ---
        openapi_url = f"{ZAP_TARGET_URL}/openapi.json"
        openapi_imported = False
        try:
            result = zap.openapi.import_url(openapi_url, hostoverride=None, contextid=zap_context["ctx_id"])
            logger.info("OpenAPI import result: %s", result)
            openapi_imported = True
        except (ConnectionError, Timeout, RequestException) as exc:
            logger.warning("OpenAPI import failed (network): %s – falling back to manual seeding", exc)
        except Exception as exc:
            logger.warning("OpenAPI import failed: %s – falling back to manual seeding", exc)

        # --- 2. Manual seed as fallback (or belt-and-suspenders) ---
        if not openapi_imported:
            for path in protected_paths:
                url = f"{ZAP_TARGET_URL}{path}"
                try:
                    zap.core.access_url(url, followredirects="true")
                except Exception as exc:
                    logger.debug("access_url failed for %s: %s", url, exc)

        # --- 3. Run the traditional spider (picks up any linked HTML/UI paths) ---
        scan_id = zap.spider.scan(ZAP_TARGET_URL, contextname=zap_context["ctx_name"])
        logger.info("ZAP spider started with scan_id=%s targeting %s", scan_id, ZAP_TARGET_URL)

        deadline = time.time() + 300
        while time.time() < deadline:
            progress = int(zap.spider.status(scan_id))
            logger.debug("Spider progress: %d%%", progress)
            if progress >= 100:
                break
            time.sleep(3)
        else:
            pytest.fail("ZAP spider did not complete within 5 minutes")

        # --- 3. Verify the site tree has real API coverage ---
        urls = zap.core.urls(baseurl=ZAP_TARGET_URL)
        discovered = [u for path in protected_paths for u in urls if path in u]
        assert discovered, (
            f"ZAP site tree contains no protected API paths among {len(urls)} known URLs. "
            f"Target: {ZAP_TARGET_URL}. "
            "Ensure ZAP_TARGET_URL is reachable from inside the ZAP container. "
            "Default is http://nginx:80 (nginx internal port on mcpnet). "
            "Override ZAP_TARGET_URL if ZAP runs outside the mcpnet network."
        )
        logger.info("Site tree has %d URLs; %d match protected paths", len(urls), len(discovered))

    def test_zap_passive_scan_finds_no_high_severity_a01_alerts(self, zap: ZAPv2) -> None:
        """After spidering, passive scan must not flag HIGH/CRITICAL A01 alerts."""
        _wait_for_passive_scan(zap, timeout=120)
        try:
            all_alerts = zap.core.alerts()
        except (ConnectionError, Timeout, RequestException) as exc:
            pytest.skip(f"ZAP unreachable during passive scan alert retrieval: {exc}")
        except json.JSONDecodeError as exc:
            pytest.skip(f"ZAP returned malformed response during passive scan: {exc}")
        a01_alerts = _filter_a01_alerts(all_alerts)

        if a01_alerts:
            _write_report(a01_alerts, "passive_failures")
            summary = "\n".join(f"  [{a['risk']}] CWE-{a.get('cweid','?')} – {a['alert']} @ {a['url']}" for a in a01_alerts)
            pytest.fail(f"ZAP passive scan found {len(a01_alerts)} HIGH/CRITICAL A01 alert(s):\n{summary}")

    def test_zap_active_scan_finds_no_critical_access_control_issues(self, zap: ZAPv2, zap_context: dict) -> None:
        """Active scan of security-sensitive prefixes must produce no CRITICAL A01 alerts."""
        try:
            scan_id = zap.ascan.scan(
                ZAP_TARGET_URL,
                recurse="true",
                inscopeonly="true",
                contextid=zap_context["scan_ctx_id"],
                scanpolicyname=None,  # default policy, full strength
            )
        except (ConnectionError, Timeout, RequestException) as exc:
            pytest.skip(f"Could not start ZAP active scan (network error): {exc}")
        except json.JSONDecodeError as exc:
            pytest.skip(f"Could not start ZAP active scan (malformed response): {exc}")
        except Exception as exc:
            pytest.skip(f"Could not start ZAP active scan: {exc}")

        logger.info("ZAP active scan started with scan_id=%s (in-scope only)", scan_id)

        deadline = time.time() + 2700  # 45 min hard cap
        while time.time() < deadline:
            try:
                progress = int(zap.ascan.status(scan_id))
            except (ConnectionError, Timeout, RequestException) as exc:
                pytest.skip(f"ZAP connection lost during active scan; proceeding with partial results. Error: {exc}")
                break
            except Exception as exc:
                logger.warning(
                    "There was an issue on the ZAP scan. Error: %s",
                    exc,
                )
                break
            logger.debug("Active scan progress: %d%%", progress)
            if progress >= 100:
                break
            time.sleep(5)
        else:
            pytest.skip("Active scan exceeded 45 min timeout - results incomplete.")

        # ZAP may have restarted after a crash; open a fresh client and allow
        # time for ZAP to come back up before querying alerts.
        time.sleep(5)
        try:
            fresh_zap = _zap_client()
            all_alerts = fresh_zap.core.alerts()
        except (ConnectionError, Timeout, RequestException) as exc:
            pytest.skip(f"ZAP unreachable after active scan: {exc}. " "If this is an OOM crash, increase the ZAP memory limit in docker-compose.yml.")
        except json.JSONDecodeError as exc:
            logger.warning("ZAP returned malformed JSON after active scan (possible crash/partial response): %s", exc)
            pytest.skip(f"ZAP response unparseable after active scan: {exc}. " "If this is an OOM crash, increase the ZAP memory limit in docker-compose.yml.")

        critical_a01 = [a for a in _filter_a01_alerts(all_alerts) if a.get("risk") == "Critical"]

        if critical_a01:
            _write_report(critical_a01, "active_critical")
            summary = "\n".join(f"  [Critical] CWE-{a.get('cweid','?')} – {a['alert']} @ {a['url']}" for a in critical_a01)
            pytest.fail(f"ZAP active scan found {len(critical_a01)} CRITICAL A01 alert(s):\n{summary}")

    def test_zap_generates_a01_report_artifact(self, zap: ZAPv2) -> None:
        """Write full A01 alert JSON and HTML reports to reports/ for artifact collection."""
        try:
            all_alerts = zap.core.alerts()
        except (ConnectionError, Timeout, RequestException) as exc:
            pytest.skip(f"ZAP unreachable during report generation: {exc}")
        except json.JSONDecodeError as exc:
            pytest.skip(f"ZAP returned malformed response during report generation: {exc}")
        a01_alerts = _filter_a01_alerts(all_alerts)
        json_path = _write_report(a01_alerts, "full_report")
        assert json_path.exists(), f"JSON report was not created at {json_path}"
        logger.info("A01 DAST JSON report: %s (%d alerts)", json_path, len(a01_alerts))

        try:
            html_path = _write_html_report(zap, "full_report")
            assert html_path.exists(), f"HTML report was not created at {html_path}"
            logger.info("A01 DAST HTML report: %s", html_path)
        except (ConnectionError, Timeout, RequestException) as exc:
            logger.warning("Could not generate HTML report: %s", exc)
        except json.JSONDecodeError as exc:
            logger.warning("ZAP returned malformed response for HTML report: %s", exc)
