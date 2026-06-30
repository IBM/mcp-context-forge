"""Kill-switch (flag-off) e2e for session affinity.

Run against a testing stack started with ``MCPGATEWAY_SESSION_AFFINITY_ENABLED=false``.
Proves the feature flag is a real kill switch: with it off, the affinity machinery is
dormant (no heartbeat, no ownership registration, no cross-worker forwarding) while the
gateway still serves normally and reverts to the pre-affinity baseline (a stateful
session does not survive across workers).

Companion to ``run_reproducers.py``, which proves the flag-on path (the compose stack
defaults the flag on). Together they are the on/off A/B for the
``MCPGATEWAY_SESSION_AFFINITY_ENABLED`` gate.

Prerequisites
-------------
* Testing stack up, multi-replica, started with ``MCPGATEWAY_SESSION_AFFINITY_ENABLED=false``.
* The counter server running on the host (``:9400``), reachable from the gateway
  containers via ``host.docker.internal`` (needed by Test 3).
* ``JWT_SECRET_KEY`` exported (to mint the admin setup token).

Env: ``JWT_SECRET_KEY``; optional ``GW_BASE`` (default ``http://localhost:8080``),
``VENV_PY`` (default ``.venv/bin/python``), ``REDIS_CONTAINER``
(default ``mcp-context-forge-redis-1``).
"""

# Standard
import json
import os
import subprocess
import sys
import time
import uuid

# Third-Party
import httpx

BASE = os.environ.get("GW_BASE", "http://localhost:8080")
JWT_SECRET = os.environ["JWT_SECRET_KEY"]
VENV_PY = os.environ.get("VENV_PY", ".venv/bin/python")
REDIS_CONTAINER = os.environ.get("REDIS_CONTAINER", "mcp-context-forge-redis-1")


def mint_admin():
    return subprocess.check_output(
        [VENV_PY, "-m", "mcpgateway.utils.create_jwt_token", "--username", "admin@example.com", "--admin", "--exp", "3600", "--secret", JWT_SECRET, "--algo", "HS256"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


TOKEN = mint_admin()
api = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, timeout=30)
results = {}


def api_req(method, path, body=None):
    r = api.request(method, path, json=body)
    if r.status_code >= 400:
        print(f"  !! {method} {path} -> {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    return r.json() if r.content else {}


def parse_mcp(r):
    if "text/event-stream" in r.headers.get("content-type", ""):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return None
    return r.json()


def redis_keys(pattern):
    """Return the Redis keys matching ``pattern`` via the redis container's CLI."""
    out = subprocess.check_output(["docker", "exec", REDIS_CONTAINER, "redis-cli", "--scan", "--pattern", pattern], text=True).strip()
    return [line for line in out.splitlines() if line]


def ensure_gateway(name, port):
    """Register (idempotently) a counter gateway and return its synced tool ids."""
    for gw in api_req("GET", "/gateways"):
        if gw.get("name") == name:
            api_req("DELETE", f"/gateways/{gw['id']}")
    gw_id = api_req("POST", "/gateways", {"name": name, "url": f"http://host.docker.internal:{port}/mcp", "transport": "STREAMABLEHTTP"}).get("id")
    for _ in range(30):
        time.sleep(1)
        ids = [t["id"] for t in api_req("GET", "/tools") if t.get("gatewayId") == gw_id]
        if ids:
            return gw_id, ids
    raise RuntimeError(f"tools never synced for {name} (is the counter reachable at host.docker.internal:{port}?)")


def make_vs(name, tool_ids):
    for sv in api_req("GET", "/servers"):
        if sv.get("name") == name:
            api_req("DELETE", f"/servers/{sv['id']}")
    vs_id = uuid.uuid4().hex
    api_req("POST", "/servers", {"server": {"id": vs_id, "name": name, "description": "gating kill-switch repro", "associated_tools": tool_ids, "associated_resources": [], "associated_prompts": []}})
    return vs_id


def open_session(url, name="gating"):
    c = httpx.Client(timeout=40, headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    r = c.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": name, "version": "1.0"}}})
    sid = r.headers.get("mcp-session-id")
    c.headers["Mcp-Session-Id"] = sid
    c.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    return c, sid


# ===================== Test 1: gateway serves with the flag off =====================
print("=== Test 1 — gateway serves normally with affinity off ===")
try:
    health = httpx.get(f"{BASE}/health", timeout=10).status_code
    tools_ok = isinstance(api_req("GET", "/tools"), list)  # stateless, DB-backed admin call
    ok = health == 200 and tools_ok
    print(f"  /health={health} | admin /tools ok={tools_ok} | RESULT: {'PASS' if ok else 'FAIL'}")
    results["Test 1 (gateway serves)"] = ok
except Exception as e:  # noqa: BLE001
    print("  ERROR:", e)
    results["Test 1 (gateway serves)"] = False


# ===================== Test 2: affinity heartbeat dormant =====================
print("\n=== Test 2 — affinity heartbeat loop never started ===")
try:
    hb = redis_keys("mcpgw:worker_heartbeat:*")
    ok = len(hb) == 0
    print(f"  worker_heartbeat keys={len(hb)} (expect 0) | RESULT: {'PASS' if ok else 'FAIL'}")
    results["Test 2 (no heartbeat)"] = ok
except Exception as e:  # noqa: BLE001
    print("  ERROR:", e)
    results["Test 2 (no heartbeat)"] = False


# ===================== Test 3: no ownership + forwarding disabled =====================
print("\n=== Test 3 — no ownership registration, cross-worker session not forwarded ===")
try:
    _, ids = ensure_gateway("gating-counter", 9400)
    vs = make_vs("gating-counter-vs", ids)
    url = f"{BASE}/servers/{vs}/mcp"
    c, sid = open_session(url)
    # (a) ownership registration is gated off -> no pool_owner key for this session.
    owner_keys = redis_keys(f"mcpgw:pool_owner:{sid}")
    # (b) with no forwarding, requests that round-robin to a non-owner worker can't
    #     find the session -> "Session not found" (the pre-affinity baseline).
    seen_not_found = False
    for i in range(6):
        resp = c.post(url, json={"jsonrpc": "2.0", "id": 100 + i, "method": "tools/list", "params": {}})
        raw = resp.text.lower()
        if "session not found" in raw or '"code":-32002' in raw or '"code":-32600' in raw:
            seen_not_found = True
    no_owner = len(owner_keys) == 0
    ok = no_owner and seen_not_found
    print(f"  sid={sid[:12]}… | pool_owner keys={len(owner_keys)} (expect 0) | cross-worker session-not-found seen={seen_not_found} | RESULT: {'PASS' if ok else 'FAIL'}")
    results["Test 3 (no ownership / no forwarding)"] = ok
except Exception as e:  # noqa: BLE001
    print("  ERROR:", e)
    results["Test 3 (no ownership / no forwarding)"] = False


# ===================== summary =====================
print("\n================ SUMMARY ================")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
sys.exit(0 if all(results.values()) else 2)
