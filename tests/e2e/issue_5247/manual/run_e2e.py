#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/issue_5247/manual/run_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

End-to-end verification for GitHub issue #5247 against a live mcpgateway instance.

Reproduces the reported bug against the real HTTP API (POST /gateways/{id}/tools/refresh)
on a fresh SQLite-backed gateway, and proves the fix by exercising:

  1. THE BUG: an unauthorized OAuth authorization_code gateway must no longer report
     success=true. It must report success=false with a message naming the
     /oauth/authorize/{id} endpoint.
  2. THE FIX WORKS END TO END: an authorized authorization_code gateway (a real
     OAuthToken row backing a real FastMCP server over SSE) must actually connect
     and populate tools -- proving the fix doesn't just report failure correctly,
     it makes the previously-permanent no-op work when authorized.
     c. The upstream server genuinely rejects a wrong/missing bearer token,
        proving the forwarded header is the real, live-resolved token --
        not a hardcoded stub.
  3. SURROUNDING BEHAVIOR IS UNCHANGED:
     a. A non-OAuth gateway with wrong credentials still reports success=false
        (this path already worked before the fix; must still work after).
     b. The background health-check path still returns success=true without
        connecting for an unauthorized auth_code gateway (must not start
        flapping gateways unreachable or spamming a real upstream with 401s).

All calls in sections 1-3a/2c go through real HTTP to the real FastAPI app,
a real SQLite database, and (for the authorized case) a real MCP server
speaking real SSE -- no gateway_service internals are mocked here.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

SCRATCH = Path(__file__).resolve().parent
REPO_ROOT = SCRATCH.parents[3]  # tests/e2e/issue_5247/manual/run_e2e.py -> repo root
DB_PATH = SCRATCH / "e2e.db"
GATEWAY_BASE = "http://127.0.0.1:48444"
UPSTREAM_PORT = 48001
UPSTREAM_TOKEN = "e2e-authorized-token-abc123"  # nosec B105 -- test-only fixture token, not a real credential

JWT_SECRET = "e2e-jwt-secret-DO-NOT-USE-IN-PRODUCTION-32plus-chars"  # pragma: allowlist secret
ENC_SECRET = "e2e-enc-secret-DO-NOT-USE-IN-PRODUCTION-32plus"  # pragma: allowlist secret

RESULTS = []


def record(name, passed, detail):
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}: {detail}")


def admin_token():
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcpgateway.utils.create_jwt_token",
            "--username",
            "admin@example.com",
            "--exp",
            "60",
            "--secret",
            JWT_SECRET,
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "JWT_SECRET_KEY": JWT_SECRET},
        check=True,
    )
    return out.stdout.strip().splitlines()[-1]


def register_gateway(client, token, *, name, url, transport="SSE", auth_type=None, oauth_config=None):
    payload = {"name": name, "url": url, "transport": transport}
    if auth_type:
        payload["auth_type"] = auth_type
    if oauth_config:
        payload["oauth_config"] = oauth_config
    resp = client.post(f"{GATEWAY_BASE}/gateways/", json=payload, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 300:
        raise RuntimeError(f"gateway registration failed: {resp.status_code} {resp.text}")
    return resp.json()


def refresh(client, token, gateway_id):
    resp = client.post(f"{GATEWAY_BASE}/gateways/{gateway_id}/tools/refresh", headers={"Authorization": f"Bearer {token}"})
    return resp.status_code, resp.json()


def register_local_gateway(name, url, auth_type, auth_json):
    """Register a gateway pointed at a local mock server, via the real service layer.

    See register_local_gateway.py's module docstring: the public HTTP registration
    endpoint correctly rejects localhost/private URLs via SSRF protection (verified
    directly against SecurityValidator.validate_url), so this bypasses only that
    client-input schema check -- not any gateway_service business logic -- to give
    the local mock upstream a routable id. The refresh call under test in every
    scenario still goes through the real, unmodified public endpoint.
    """
    out = subprocess.run(
        [sys.executable, str(SCRATCH / "register_local_gateway.py"), name, url, auth_type, json.dumps(auth_json)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DATABASE_URL": f"sqlite:///{DB_PATH}",
            "JWT_SECRET_KEY": JWT_SECRET,
            "AUTH_ENCRYPTION_SECRET": ENC_SECRET,
            "BASIC_AUTH_PASSWORD": "e2e-admin-password-32chars-min!!",  # pragma: allowlist secret
        },
        timeout=30,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"local gateway registration failed: {out.stdout}\n{out.stderr}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def insert_valid_oauth_token(gateway_id, user_email, access_token):
    """Insert an OAuthToken row -- simulating a completed OAuth authorization flow.

    The access_token column uses the db.py EncryptedText type, whose process_result_value
    decrypts on ORM read but passes plaintext through unchanged when the stored value isn't
    recognized as encrypted (EncryptionService.is_encrypted() -> False). TokenStorageService's
    own decrypt_secret_async() is documented idempotent for the same reason. So a raw plaintext
    insert here round-trips correctly through the real ORM read path with no encryption step
    needed on this side.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        INSERT INTO oauth_tokens
            (id, gateway_id, user_id, app_user_email, access_token, token_type, expires_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now', '+1 hour'), datetime('now'), datetime('now'))
        """,
        (uuid.uuid4().hex, gateway_id, user_email, user_email, access_token, "Bearer"),
    )
    conn.commit()
    conn.close()


def run_health_check_path_directly(gateway_id):
    """Exercise the created_via="health_check" branch against the live DB, no HTTP mocking.

    There is no public HTTP endpoint for the background health-check refresh path, so this
    calls the real service method directly against the same SQLite file the live app is
    using, proving the health-check branch still short-circuits (no helper call, no
    connection attempt) for an unauthorized auth_code gateway.
    """
    script = f"""
import asyncio, os, sys
sys.path.insert(0, {str(REPO_ROOT)!r})
os.environ["DATABASE_URL"] = "sqlite:///{DB_PATH}"
os.environ["JWT_SECRET_KEY"] = "{JWT_SECRET}"
os.environ["AUTH_ENCRYPTION_SECRET"] = "{ENC_SECRET}"
os.environ["BASIC_AUTH_PASSWORD"] = "e2e-admin-password-32chars-min!!"  # pragma: allowlist secret
from mcpgateway.services.gateway_service import GatewayService

async def main():
    svc = GatewayService()
    result = await svc._refresh_gateway_tools_resources_prompts(
        "{gateway_id}", user_email="admin@example.com", created_via="health_check"
    )
    print("HEALTHCHECK_RESULT", result["success"], result["error"])

asyncio.run(main())
"""
    out = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return out.stdout, out.stderr


def main():
    token = admin_token()
    client = httpx.Client(timeout=15.0)

    # Gateways are deduplicated by URL (not just name) in "Public" scope, so every URL used
    # below carries this run's unique tag as a query string -- makes the script safely
    # re-runnable against the same long-lived DB without colliding on a prior run's rows.
    run_tag = uuid.uuid4().hex[:8]

    # === Scenario 1: THE BUG -- unauthorized auth_code gateway must fail, not silently succeed ===
    # Uses a real, DNS-resolvable domain (example.com, RFC 2606) that is not running an MCP
    # server -- mirrors the issue's own repro (a real host, https://mcp.monday.com/sse, simply
    # not authorized). The point of this scenario is that NO connection is ever attempted
    # (no token stored), so the target's reachability is irrelevant to what's being proven.
    gw_unauthorized = register_gateway(
        client,
        token,
        name=f"e2e-unauthorized-{run_tag}",
        url=f"https://example.com/sse?run={run_tag}",
        oauth_config={
            "grant_type": "authorization_code",
            "client_id": "e2e-client-id",
            "client_secret": "e2e-client-secret",  # pragma: allowlist secret
            "authorization_url": "https://example.com/authorize",
            "token_url": "https://example.com/token",
            "redirect_uri": "https://example.com/oauth/callback",
            "scopes": ["read"],
        },
        auth_type="oauth",
    )
    gw1_id = gw_unauthorized["id"]
    status, body = refresh(client, token, gw1_id)
    record(
        "1. Unauthorized auth_code gateway reports failure (the bug)",
        status == 200 and body.get("success") is False and f"/oauth/authorize/{gw1_id}" in (body.get("error") or ""),
        f"HTTP {status}, success={body.get('success')}, error={body.get('error')!r}, toolsAdded={body.get('toolsAdded')}",
    )

    # === Scenario 2: THE FIX -- authorized auth_code gateway actually connects and fetches tools ===
    mock_proc = subprocess.Popen(
        [sys.executable, str(SCRATCH / "mock_upstream_mcp.py")],
        env={**os.environ, "E2E_EXPECTED_TOKEN": UPSTREAM_TOKEN, "E2E_UPSTREAM_PORT": str(UPSTREAM_PORT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        for _ in range(30):
            try:
                httpx.get(f"http://127.0.0.1:{UPSTREAM_PORT}/sse", timeout=1.0)
                break
            except httpx.TransportError:
                time.sleep(0.5)
        else:
            raise RuntimeError("mock upstream MCP server never came up")

        gw_authorized = register_local_gateway(
            f"e2e-authorized-{run_tag}",
            f"http://127.0.0.1:{UPSTREAM_PORT}/sse?run={run_tag}",
            "oauth",
            {
                "grant_type": "authorization_code",
                "client_id": "e2e-client-id",
                "client_secret": "e2e-client-secret",  # pragma: allowlist secret
                "authorization_url": f"http://127.0.0.1:{UPSTREAM_PORT}/authorize",
                "token_url": f"http://127.0.0.1:{UPSTREAM_PORT}/token",
                "redirect_uri": "https://example.com/oauth/callback",
                "scopes": ["read"],
            },
        )
        gw2_id = gw_authorized["id"]
        insert_valid_oauth_token(gw2_id, "admin@example.com", UPSTREAM_TOKEN)

        status, body = refresh(client, token, gw2_id)
        record(
            "2. Authorized auth_code gateway connects and fetches tools (the fix)",
            status == 200 and body.get("success") is True and body.get("toolsAdded", 0) >= 1,
            f"HTTP {status}, success={body.get('success')}, toolsAdded={body.get('toolsAdded')}, error={body.get('error')!r}",
        )

        # 2c: prove the upstream genuinely enforces the bearer -- insert a WRONG token
        # for a second unauthorized-looking id and confirm it is rejected as a real
        # connection failure, not silently accepted.
        gw_wrong_token = register_local_gateway(
            f"e2e-wrong-token-{run_tag}",
            f"http://127.0.0.1:{UPSTREAM_PORT}/sse?run={run_tag}-wrong",
            "oauth",
            {
                "grant_type": "authorization_code",
                "client_id": "e2e-client-id",
                "client_secret": "e2e-client-secret",  # pragma: allowlist secret
                "authorization_url": f"http://127.0.0.1:{UPSTREAM_PORT}/authorize",
                "token_url": f"http://127.0.0.1:{UPSTREAM_PORT}/token",
                "redirect_uri": "https://example.com/oauth/callback",
                "scopes": ["read"],
            },
        )
        gw3_id = gw_wrong_token["id"]
        insert_valid_oauth_token(gw3_id, "admin@example.com", "this-is-not-the-right-token")
        status, body = refresh(client, token, gw3_id)
        record(
            "2c. Upstream genuinely enforces the bearer token (not a stub)",
            status == 200 and body.get("success") is False,
            f"HTTP {status}, success={body.get('success')}, error={body.get('error')!r}",
        )

        # === Scenario 3a: non-OAuth gateway with wrong credentials still reports failure ===
        # Registration for non-OAuth auth types performs a real connection probe immediately
        # (only authorization_code has the "skip probe, needs user consent" carve-out this PR
        # touches) -- so wrong Basic credentials against a real target are rejected right here,
        # at registration, never producing a falsely-successful gateway. This is the
        # pre-existing, unaffected-by-this-PR behavior the design spec's root-cause analysis
        # (issue's second sub-case, "wrong credentials") already predicted; this proves it
        # against a live server that genuinely requires (different) credentials.
        try:
            register_local_gateway(
                f"e2e-basic-wrongcreds-{run_tag}",
                f"http://127.0.0.1:{UPSTREAM_PORT}/sse?run={run_tag}-basic",
                "basic",
                {"username": "wronguser", "password": "wrongpass"},  # pragma: allowlist secret
            )
            record("3a. Non-OAuth gateway with wrong credentials reports failure (no regression)", False, "registration unexpectedly succeeded")
        except RuntimeError as exc:
            record(
                "3a. Non-OAuth gateway with wrong credentials reports failure (no regression)",
                "401 Unauthorized" in str(exc) or "GatewayConnectionError" in str(exc),
                f"registration correctly rejected: {str(exc)[:250]!r}",
            )
    finally:
        mock_proc.terminate()
        try:
            mock_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock_proc.kill()

    # === Scenario 3b: health-check path for an unauthorized auth_code gateway is unchanged ===
    stdout, stderr = run_health_check_path_directly(gw1_id)
    hc_ok = "HEALTHCHECK_RESULT True None" in stdout
    record(
        "3b. Health-check path unchanged (still success=true, no connection attempt)",
        hc_ok,
        f"stdout={stdout.strip()!r} stderr_tail={stderr.strip()[-300:]!r}",
    )

    print("\n=== SUMMARY ===")
    for r in RESULTS:
        print(f"{'PASS' if r['passed'] else 'FAIL'}: {r['name']}")
    all_passed = all(r["passed"] for r in RESULTS)
    print(f"\nOVERALL: {'ALL PASSED' if all_passed else 'FAILURES PRESENT'} ({sum(r['passed'] for r in RESULTS)}/{len(RESULTS)})")

    with open(SCRATCH / "e2e_results.json", "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
