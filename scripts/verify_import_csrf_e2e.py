#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E2E verification for issue #5964: /admin/import/* CSRF headers.

Starts a real gateway server (uvicorn, SQLite, CSRF enforcement on) and
drives it over plain HTTP with a real cookie-jar session -- the same
mechanics a browser uses -- to reproduce the request shape the Admin UI's
JS now sends for the three call sites named in the issue:

    - POST /admin/import/preview        (fileTransfer.js previewImport)
    - POST /admin/import/configuration  (fileTransfer.js handleImport)
    - POST /admin/import/configuration  (selectiveImport.js handleSelectiveImport)

selectiveImport.js and fileTransfer.js's handleImport hit the identical
URL+method, so one endpoint covers both call sites; the request shape
(headers, cookie-only auth) is what distinguishes them, not the URL.

For each site this script sends the CSRF header the fixed JS attaches
(X-CSRF-Token from the mcpgateway_csrf_token cookie) and omits Authorization
entirely (the httponly session-cookie login case that produced a malformed
"Bearer " header before the fix), and asserts the request is NOT rejected
with 403 CSRF errors.

Negative controls prove the fix did not weaken CSRF enforcement generally:
    - the same three calls WITHOUT X-CSRF-Token must still 403
    - a sibling read (/admin/llm/providers/html) and a sibling write
      (/admin/llm/providers/{id}/fetch-models) -- the #5780 fix's own area,
      and the code path Task 3's llmRequestHeaders delegation touches --
      must remain reachable, proving no collateral damage

Usage:
    .venv/bin/python scripts/verify_import_csrf_e2e.py

Exits 0 and prints a PASS summary if every check holds; exits 1 and prints
the first failing check otherwise. Safe to run repeatedly -- uses a fresh
temporary SQLite DB and a random free port each run, and never runs against
a persistent CSRF_ENABLED=true # pragma: allowlist secret
or production database.
"""

# Standard
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time

# Third-Party
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "changeme"  # pragma: allowlist secret -- default PLATFORM_ADMIN_PASSWORD, isolated ephemeral DB only

CHECKS = []  # (description, passed: bool, detail: str)


def record(description, passed, detail=""):
    CHECKS.append((description, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {description}" + (f" -- {detail}" if detail else ""))


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(base_url, timeout=180):
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            r = requests.get(f"{base_url}/health", timeout=2)
            if r.status_code == 200:
                return
        except requests.exceptions.RequestException as e:
            last_err = e
        time.sleep(0.5)
    raise RuntimeError(f"server did not become healthy at {base_url}/health within {timeout}s: {last_err}")


def main():
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory(prefix="mcpgw-e2e-") as tmpdir:
        db_path = os.path.join(tmpdir, "e2e.db")

        env = os.environ.copy()
        env.update(
            {
                "DATABASE_URL": f"sqlite:///{db_path}",
                "HOST": "127.0.0.1",
                "PORT": str(port),
                "JWT_SECRET_KEY": secrets.token_urlsafe(32),
                "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(32),
                "AUTH_REQUIRED": "true",
                "MCPGATEWAY_UI_ENABLED": "true",
                "MCPGATEWAY_ADMIN_API_ENABLED": "true",
                "PLATFORM_ADMIN_EMAIL": ADMIN_EMAIL,
                "PLATFORM_ADMIN_PASSWORD": ADMIN_PASSWORD,
                # Bootstrap normally force-flags the default admin account for a
                # mandatory password change; PasswordChangeEnforcementMiddleware
                # then serves /admin/change-password-required (still HTTP 200)
                # for every other request. Disabled here so the script can drive
                # the actual endpoints under test -- not a CSRF-relevant setting.
                "ADMIN_REQUIRE_PASSWORD_CHANGE_ON_BOOTSTRAP": "false",
                # CSRF must be genuinely on -- this whole script exists to prove
                # the Admin UI's writes survive it, not to route around it.
                "CSRF_ENABLED": "true",
                "CSRF_COOKIE_NAME": "mcpgateway_csrf_token",
                "CSRF_TOKEN_NAME": "X-CSRF-Token",
                # Plain HTTP on localhost: Secure-flagged cookies are silently
                # dropped by cookie jars on non-TLS requests (this exact
                # footgun broke PR #5780's own e2e regression test the first
                # time -- see commit 0d6aef010's third commit message).
                "SECURE_COOKIES": "false",
                "CSRF_COOKIE_SECURE": "false",
                "LOG_LEVEL": "WARNING",
                "PLUGINS_ENABLED": "false",
                "OBSERVABILITY_ENABLED": "false",
            }
        )

        proc = subprocess.Popen(
            [
                os.path.join(REPO_ROOT, ".venv", "bin", "uvicorn"),
                "mcpgateway.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            wait_for_server(base_url)

            session = requests.Session()
            # This environment has no brotli decoder installed, and the server
            # compresses responses with br by default; ask for uncompressed
            # bodies so response.json()/.text work without an extra dependency.
            session.headers["Accept-Encoding"] = "identity"
            # Real browsers auto-attach these for fetch() calls made from the
            # rendered /admin page -- Referer feeds is_browser_request's
            # same-origin check (rbac.py) and _request_origin_matches's CSRF
            # origin check (admin.py); plain python-requests sends neither.
            # Without them every request here would be misclassified as a
            # non-browser API call and/or fail CSRF origin validation for
            # reasons that have nothing to do with the fix under test.
            session.headers["Origin"] = base_url
            session.headers["Referer"] = f"{base_url}/admin"

            # Real login, exactly as a browser does it: form POST, cookie jar
            # picks up jwt_token + mcpgateway_csrf_token from Set-Cookie.
            login_resp = session.post(
                f"{base_url}/admin/login",
                data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                allow_redirects=False,
            )
            record(
                "admin login succeeds (redirect, session+CSRF cookies set)",
                login_resp.status_code in (302, 303) and "jwt_token" in session.cookies and "mcpgateway_csrf_token" in session.cookies,
                f"status={login_resp.status_code} cookies={sorted(session.cookies.keys())}",
            )

            csrf_token = session.cookies.get("mcpgateway_csrf_token")

            # This is the exact header shape getAuthHeaders() now produces for
            # a session-cookie login: Content-Type + X-CSRF-Token, NO
            # Authorization (there is no JS-readable bearer token to send).
            fixed_headers = {
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf_token,
            }

            # Real export blob as import payload -- avoids hand-guessing the
            # import schema, exercises the real preview/import services.
            export_resp = session.get(
                f"{base_url}/admin/export/configuration",
                params={"types": "tools", "include_dependencies": "false"},
                headers={"X-CSRF-Token": csrf_token},
            )
            record(
                "seed export for import payload succeeds",
                export_resp.status_code == 200,
                f"status={export_resp.status_code}",
            )
            export_blob = export_resp.json()

            # --- Site 1: fileTransfer.js previewImport -> POST /admin/import/preview
            preview_resp = session.post(
                f"{base_url}/admin/import/preview",
                headers=fixed_headers,
                data=json.dumps({"data": export_blob}),
            )
            record(
                "previewImport-shaped request is not CSRF-rejected",
                preview_resp.status_code != 403,
                f"status={preview_resp.status_code} body={preview_resp.text[:200]}",
            )

            # --- Site 2/3: fileTransfer.js handleImport AND selectiveImport.js
            # handleSelectiveImport both hit this identical URL+method; the
            # request shape below is what both now send. dry_run=true so
            # this never actually mutates the seeded DB.
            import_resp = session.post(
                f"{base_url}/admin/import/configuration",
                headers=fixed_headers,
                data=json.dumps({"import_data": export_blob, "conflict_strategy": "update", "dry_run": True}),
            )
            record(
                "handleImport/handleSelectiveImport-shaped request is not CSRF-rejected",
                import_resp.status_code != 403,
                f"status={import_resp.status_code} body={import_resp.text[:200]}",
            )

            # --- Negative controls: CSRF must still be enforced, not disabled.
            no_csrf_headers = {"Content-Type": "application/json"}

            neg_preview = session.post(
                f"{base_url}/admin/import/preview",
                headers=no_csrf_headers,
                data=json.dumps({"data": export_blob}),
            )
            record(
                "previewImport WITHOUT X-CSRF-Token is still rejected (403)",
                neg_preview.status_code == 403,
                f"status={neg_preview.status_code}",
            )

            neg_import = session.post(
                f"{base_url}/admin/import/configuration",
                headers=no_csrf_headers,
                data=json.dumps({"import_data": export_blob, "conflict_strategy": "update", "dry_run": True}),
            )
            record(
                "handleImport WITHOUT X-CSRF-Token is still rejected (403)",
                neg_import.status_code == 403,
                f"status={neg_import.status_code}",
            )

            # --- Surrounding-area regression check: llm_admin_router is
            # mounted at /admin/llm (mcpgateway/api/v1/__init__.py:258) with
            # the SAME enforce_admin_csrf dependency as /admin/import/*, and
            # its provider/model writes are exactly what Task 3 (the
            # llmRequestHeaders -> getAuthHeaders delegation) and the earlier
            # #5780 fix cover. Confirm that area still works under the same
            # session/CSRF mechanics this change reuses.
            llm_resp = session.get(
                f"{base_url}/admin/llm/providers/html",
                headers={"X-CSRF-Token": csrf_token},
            )
            record(
                "sibling /admin/llm/providers/html read still reachable (no collateral damage)",
                llm_resp.status_code == 200,
                f"status={llm_resp.status_code}",
            )

            # A real state-changing /admin/llm/* write, run through the exact
            # code path Task 3 refactored (llmRequestHeaders -> getAuthHeaders
            # delegation). fetch-models on a nonexistent provider id 404s at
            # the service layer, which is the correct signal to look for: it
            # got PAST CSRF/auth and reached real application logic instead
            # of being rejected at the CSRF gate.
            llm_write_resp = session.post(
                f"{base_url}/admin/llm/providers/nonexistent-provider-id/fetch-models",
                headers=fixed_headers,
            )
            record(
                "sibling /admin/llm/* write is not CSRF-rejected (reaches app logic, not 403)",
                llm_write_resp.status_code != 403,
                f"status={llm_write_resp.status_code}",
            )

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            if proc.stdout:
                server_output = proc.stdout.read()
                if any(not passed for _, passed, _ in CHECKS):
                    print("\n--- server output (tail) ---")
                    print("\n".join(server_output.splitlines()[-80:]))

    failed = [c for c in CHECKS if not c[1]]
    print("\n" + "=" * 72)
    print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    if failed:
        print("FAILED:")
        for desc, _, detail in failed:
            print(f"  - {desc}: {detail}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
