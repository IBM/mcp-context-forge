"""#4205 counter reproducers — Tests 2-5 (PR #5212), driven against the VM stack.

Reuses the host-side counter on :9400 (gateway 'repro-counter'); Test 4 also uses
a second counter on :9401 (gateway 'repro-counter-b'). Each test drives one or more
downstream sessions through nginx (round-robin across the 3 gateway replicas) and
asserts per-session upstream state survives the cross-worker affinity forwarding.
"""

import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
import uuid

import httpx

BASE = os.environ.get("GW_BASE", "http://localhost:8080")
TOKEN = os.environ["MCPGATEWAY_BEARER_TOKEN"]
JWT_SECRET = os.environ["JWT_SECRET_KEY"]
VENV_PY = "/root/mcp-context-forge/.venv/bin/python"

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
    raise RuntimeError(f"tools never synced for {name}")


def make_vs(name, tool_ids):
    for sv in api_req("GET", "/servers"):
        if sv.get("name") == name:
            try:
                api_req("DELETE", f"/servers/{sv['id']}")
            except Exception as e:
                print(f"  note: could not delete stale server {sv.get('id')}: {e}")
    vs_id = uuid.uuid4().hex
    api_req("POST", "/servers", {"server": {"id": vs_id, "name": name, "description": "#4205 repro",
            "associated_tools": tool_ids, "associated_resources": [], "associated_prompts": []}})
    return vs_id


def session_tools(c, url):
    listed = parse_mcp(c.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
    return [t["name"] for t in listed["result"]["tools"]]


def call(c, url, name, _id):
    d = parse_mcp(c.post(url, json={"jsonrpc": "2.0", "id": _id, "method": "tools/call", "params": {"name": name, "arguments": {}}}))
    res = d.get("result", {})
    if isinstance(res.get("structuredContent"), dict) and "result" in res["structuredContent"]:
        return res["structuredContent"]["result"]
    content = res.get("content", [])
    if content and content[0].get("type") == "text":
        return int(content[0]["text"])
    return res


def open_session(token, url, name="s"):
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    c = httpx.Client(timeout=40, headers=H)
    r = c.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": name, "version": "1.0"}}})
    c.headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
    c.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    return c, r.headers["mcp-session-id"]


def run_session(name, token, n, vs_id):
    url = f"{BASE}/servers/{vs_id}/mcp"
    c, sid = open_session(token, url, name)
    names = session_tools(c, url)
    inc = next(x for x in names if "increment" in x)
    get = next(x for x in names if "value" in x)
    incs = [call(c, url, inc, 100 + i) for i in range(n)]
    return sid, incs, call(c, url, get, 999)


def mint_token(exp):
    return subprocess.check_output([VENV_PY, "-m", "mcpgateway.utils.create_jwt_token",
        "--username", "admin@example.com", "--admin", "--exp", str(exp), "--secret", JWT_SECRET, "--algo", "HS256"],
        text=True, stderr=subprocess.DEVNULL).strip()


def redis(*args):
    return subprocess.check_output(["docker", "exec", "mcp-context-forge-redis-1", "redis-cli", *args], text=True).strip()


# ===================== shared setup =====================
print("=== setup: gateway A (:9400) + virtual server VS_A ===")
_, a_ids = ensure_gateway("repro-counter", 9400)
VS_A = make_vs("repro-counter-vs", a_ids)
print("VS_A:", VS_A, "tools:", len(a_ids))


# ===================== Test 1 =====================
print("\n=== Test 1 — single session, increment x25 ===")
try:
    sid, incs, gv = run_session("T1", TOKEN, 25, VS_A)
    print(f"  sid={sid[:12]}… increments={incs} get_value={gv}")
    ok = incs == list(range(1, 26)) and gv == 25
    print("  RESULT:", "PASS" if ok else "FAIL")
    results["Test 1"] = ok
except Exception as e:  # noqa: BLE001
    print("  ERROR:", e)
    results["Test 1"] = False


# ===================== Test 2 =====================
print("\n=== Test 2 — 3 concurrent sessions, one token, increment x10 ===")
try:
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        out = list(ex.map(lambda i: run_session(f"S{i}", TOKEN, 10, VS_A), range(3)))
    sids = [o[0] for o in out]
    for i, (sid, incs, gv) in enumerate(out):
        print(f"  S{i} sid={sid[:12]}… increments={incs} get_value={gv}")
    ok = all(o[1] == list(range(1, 11)) and o[2] == 10 for o in out) and len(set(sids)) == 3
    print("  distinct sids:", len(set(sids)), "| RESULT:", "PASS" if ok else "FAIL")
    results["Test 2"] = ok
except Exception as e:
    print("  ERROR:", e); results["Test 2"] = False


# ===================== Test 3 =====================
print("\n=== Test 3 — two distinct tokens (same admin), parallel sessions, x10 ===")
try:
    tok_a, tok_b = mint_token(900), mint_token(600)
    assert tok_a != tok_b, "tokens identical"
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(run_session, "UserA", tok_a, 10, VS_A)
        fb = ex.submit(run_session, "UserB", tok_b, 10, VS_A)
        ra, rb = fa.result(), fb.result()
    print(f"  UserA sid={ra[0][:12]}… increments={ra[1]} get_value={ra[2]}")
    print(f"  UserB sid={rb[0][:12]}… increments={rb[1]} get_value={rb[2]}")
    ok = ra[1] == list(range(1, 11)) and rb[1] == list(range(1, 11)) and ra[2] == 10 and rb[2] == 10 and ra[0] != rb[0]
    print("  RESULT:", "PASS" if ok else "FAIL")
    results["Test 3"] = ok
except Exception as e:
    print("  ERROR:", e); results["Test 3"] = False


# ===================== Test 4 =====================
print("\n=== Test 4 — one session across TWO counters (A x5, B x3, A x2) ===")
try:
    _, b_ids = ensure_gateway("repro-counter-b", 9401)
    VS_AB = make_vs("repro-counter-multi", a_ids + b_ids)
    url = f"{BASE}/servers/{VS_AB}/mcp"
    c, sid = open_session(TOKEN, url, "multi")
    names = session_tools(c, url)
    a_inc = next(x for x in names if "increment" in x and "counter-b" not in x)
    b_inc = next(x for x in names if "increment" in x and "counter-b" in x)
    a_get = next(x for x in names if "value" in x and "counter-b" not in x)
    b_get = next(x for x in names if "value" in x and "counter-b" in x)
    a1 = [call(c, url, a_inc, 10 + i) for i in range(5)]
    b1 = [call(c, url, b_inc, 20 + i) for i in range(3)]
    a2 = [call(c, url, a_inc, 30 + i) for i in range(2)]
    av, bv = call(c, url, a_get, 40), call(c, url, b_get, 41)
    print(f"  session {sid[:12]}…")
    print(f"  A increments: {a1} then {a2}  -> get_value={av}")
    print(f"  B increments: {b1}            -> get_value={bv}")
    ok = a1 == [1, 2, 3, 4, 5] and a2 == [6, 7] and b1 == [1, 2, 3] and av == 7 and bv == 3
    print("  RESULT:", "PASS" if ok else "FAIL")
    results["Test 4"] = ok
except Exception as e:
    print("  ERROR:", e); results["Test 4"] = False


# ===================== Test 5 =====================
print("\n=== Test 5 — owner-worker kill / failover recovery contract ===")
try:
    url = f"{BASE}/servers/{VS_A}/mcp"
    c, sid = open_session(TOKEN, url, "kill")
    names = session_tools(c, url)
    inc = next(x for x in names if "increment" in x)
    bound = [call(c, url, inc, 50 + i) for i in range(5)]
    owner = redis("get", f"mcpgw:pool_owner:{sid}")            # host:pid
    host, pid = owner.split(":")
    print(f"  [1] bound sid={sid[:12]}… increments={bound}")
    print(f"  [2] pool_owner -> {owner}")
    # map container hostname (short id) -> container name
    ps = subprocess.check_output(["docker", "ps", "--format", "{{.ID}} {{.Names}}"], text=True).splitlines()
    cname = next(n for line in ps for cid, n in [line.split()] if host.startswith(cid))
    print(f"  [3] owner worker pid {pid} in {cname}")
    subprocess.run(["docker", "exec", cname, "python3", "-c", f"import os,signal; os.kill({int(pid)}, signal.SIGKILL)"], check=True)
    print(f"  [4] kill -9 {pid} -> worker dead (gunicorn respawns)")
    t0 = time.time()
    try:
        r = c.post(url, json={"jsonrpc": "2.0", "id": 60, "method": "tools/call", "params": {"name": inc, "arguments": {}}})
        body = r.text[:160]
        code = r.status_code
    except Exception as ex2:
        code, body = "EXC", str(ex2)[:160]
    dt = time.time() - t0
    print(f"  [5] stale-sid request -> HTTP {code} in {dt:.1f}s | {body}")
    stale_ok = (code == 404) or ("-32600" in str(body)) or ("Session not found" in str(body))
    c2, sid2 = open_session(TOKEN, url, "fresh")
    fresh = [call(c2, url, inc, 70 + i) for i in range(3)]
    print(f"  [6] fresh initialize {sid2[:12]}… increments={fresh}")
    ok = bound == [1, 2, 3, 4, 5] and stale_ok and fresh == [1, 2, 3]
    print("  RESULT:", "PASS" if ok else "FAIL")
    results["Test 5"] = ok
except Exception as e:
    print("  ERROR:", e); results["Test 5"] = False


# ===================== summary =====================
print("\n================ SUMMARY ================")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
sys.exit(0 if all(results.values()) else 2)
