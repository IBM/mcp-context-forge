# -*- coding: utf-8 -*-
"""Public-only multi-worker reproducer for trusted-internal dispatch.

The multi-worker (Docker stack) complement to the in-process integration test
``tests/integration/test_internal_mcp_dispatch_auth.py``: it proves that an
*unauthenticated* (public-only) MCP session, affinity-forwarded across gunicorn
workers, is **served** rather than RBAC-denied.

Prerequisites
-------------
* Testing stack up (multi-replica gunicorn + Redis), built from the branch under test.
* ``MCP_REQUIRE_AUTH=false`` on the gateway (so unauthenticated ``/mcp`` is allowed with
  public-only visibility). Without it, the unauthenticated ``initialize`` returns 401.
* The counter server running on the host (``:9400``), reachable from the gateway
  containers via ``host.docker.internal``.

Setup registers the counter gateway + a **public** virtual server with an admin token
(registration is an admin operation). The session itself is then driven with **no token**.

Env: ``JWT_SECRET_KEY`` (to mint the admin setup token), optional ``GW_BASE`` (default
``http://localhost:8080``) and ``VENV_PY`` (default ``.venv/bin/python``).
"""

# Standard
import os
import subprocess
import sys
import time
import uuid

# Third-Party
import httpx
import orjson

BASE = os.environ.get("GW_BASE", "http://localhost:8080")
JWT_SECRET = os.environ["JWT_SECRET_KEY"]
VENV_PY = os.environ.get("VENV_PY", ".venv/bin/python")


def _mint_admin_token():
    return subprocess.check_output(
        [VENV_PY, "-m", "mcpgateway.utils.create_jwt_token", "--username", "admin@example.com", "--admin", "--exp", "3600", "--secret", JWT_SECRET, "--algo", "HS256"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


_admin = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {_mint_admin_token()}", "Content-Type": "application/json"}, timeout=30)


def api_req(method, path, body=None):
    r = _admin.request(method, path, json=body)
    if r.status_code >= 400:
        print(f"  !! {method} {path} -> {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    return r.json() if r.content else {}


def parse_mcp(r):
    if "text/event-stream" in r.headers.get("content-type", ""):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                return orjson.loads(line[5:].strip())
        return None
    return r.json()


# --- setup (admin): register counter gateway + PUBLIC virtual server -------------------
print("=== setup: register repro-counter-public gateway + PUBLIC virtual server ===")
for gw in api_req("GET", "/gateways"):
    if gw.get("name") == "repro-counter-public":
        api_req("DELETE", f"/gateways/{gw['id']}")
gw_id = api_req("POST", "/gateways", {"name": "repro-counter-public", "url": "http://host.docker.internal:9400/mcp", "transport": "STREAMABLEHTTP", "visibility": "public"}).get("id")
tool_ids = []
for _ in range(30):
    time.sleep(1)
    tool_ids = [t["id"] for t in api_req("GET", "/tools") if t.get("gatewayId") == gw_id]
    if tool_ids:
        break
else:
    print("ERROR: tools never synced — is the counter reachable at host.docker.internal:9400?")
    sys.exit(1)
for sv in api_req("GET", "/servers"):
    if sv.get("name") == "repro-counter-public-vs":
        api_req("DELETE", f"/servers/{sv['id']}")
VS = uuid.uuid4().hex
api_req("POST", "/servers", {"server": {"id": VS, "name": "repro-counter-public-vs", "description": "public-only repro", "visibility": "public", "associated_tools": tool_ids, "associated_resources": [], "associated_prompts": []}})
print("public virtual server:", VS)


# --- drive a PUBLIC-ONLY session (NO Authorization header) ----------------------------
url = f"{BASE}/servers/{VS}/mcp"
public = httpx.Client(timeout=30, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})  # no token
r = public.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "public-only", "version": "1.0"}}})
if r.status_code == 401:
    print("ERROR: unauthenticated initialize -> 401. Set MCP_REQUIRE_AUTH=false on the gateway and retry.")
    sys.exit(1)
sid = r.headers.get("mcp-session-id")
public.headers["Mcp-Session-Id"] = sid
public.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
print("public-only session:", sid)

listed = parse_mcp(public.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
err = (listed or {}).get("error", {})
assert err.get("code") != -32003, f"public-only tools/list was RBAC-denied: {listed}"
names = [t["name"] for t in listed["result"]["tools"]]
print("public-only tools/list ->", names)
inc = next(n for n in names if "increment" in n)


def call(name, _id):
    d = parse_mcp(public.post(url, json={"jsonrpc": "2.0", "id": _id, "method": "tools/call", "params": {"name": name, "arguments": {}}}))
    res = d.get("result", {})
    if isinstance(res.get("structuredContent"), dict) and "result" in res["structuredContent"]:
        return res["structuredContent"]["result"]
    content = res.get("content", [])
    return int(content[0]["text"]) if content and content[0].get("type") == "text" else res


increments = [call(inc, 100 + i) for i in range(5)]
print("public-only increments:", increments)
ok = bool(names) and increments == [1, 2, 3, 4, 5]
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 2)
