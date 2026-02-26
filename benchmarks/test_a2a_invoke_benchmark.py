# -*- coding: utf-8 -*-
"""Benchmark POST /a2a/{agent_name}/invoke and compare to a stored main baseline.

Compares current branch speed to a fixed \"legacy main\" commit so that after
merge we still compare latest code vs that baseline.

Benchmark scenarios (15 total)
------------------------------
| #  | Scenario ID      | Total invokes | Client sends              | Gateway path                    | Stub delay  | Payload | Slow |
|----|------------------|---------------|---------------------------|----------------------------------|-------------|---------|------|
| 1  | single_light     | 1             | 1 POST single-invoke      | Queue → 1 invoke                 | 0.1s        | light   | no   |
| 2  | single_heavy     | 1             | 1 POST single-invoke      | Queue → 1 invoke                 | 0.1s        | heavy   | no   |
| 3  | single_slow      | 1             | 1 POST single-invoke      | Queue → 1 invoke                 | 3s          | light   | yes  |
| 4  | 10_single_light  | 10            | 10 sequential POSTs       | Queue, one at a time             | 0.1–1s each | light   | no   |
| 5  | 10_single_heavy  | 10            | 10 sequential POSTs       | Queue, one at a time             | 0.1–1s each | heavy   | no   |
| 6  | 10_batch_light   | 10            | 1 batch or 10 concurrent  | Batch (1 POST) or queue (10)     | 0.1–1s each | light   | no   |
| 7  | 10_batch_heavy   | 10            | 1 batch or 10 concurrent  | Batch (1 POST) or queue (10)     | 0.1–1s each | heavy   | no   |
| 8  | 10_single_slow   | 10            | 10 sequential POSTs       | Queue, one at a time             | 0.1–1s each | light   | no   |
| 9  | 10_batch_slow    | 10            | 1 batch or 10 concurrent  | Batch (1 POST) or queue (10)     | 0.1–1s each | light   | no   |
| 10 | 100_single_light | 100           | 10 waves × 10 sequential   | Queue, one at a time             | 0.1–1s each | light   | yes  |
| 11 | 100_single_heavy | 100           | 10 waves × 10 sequential   | Queue, one at a time             | 0.1–1s each | heavy   | yes  |
| 12 | 100_single_slow  | 100           | 10 waves × 10 sequential   | Queue, one at a time             | 0.1–1s each | light   | yes  |
| 13 | 100_batch_light  | 100           | waves × (batch or n conc.) | batch(n) or queue(n), n=5–20 seeded | 0.1–1s each | light   | yes  |
| 14 | 100_batch_heavy  | 100           | waves × (batch or n conc.) | batch(n) or queue(n), n=5–20 seeded | 0.1–1s each | heavy   | yes  |
| 15 | 100_batch_slow   | 100           | waves × (batch or n conc.) | batch(n) or queue(n), n=5–20 seeded | 0.1–1s each | light   | yes  |

Client behaviour:
  - Single: one POST to /a2a/{agent}/invoke.
  - N sequential: N POSTs in a row (_run_n_singles); gateway sees one request at a time.
  - Batch/concurrent: _run_one_batch_of_n(n) tries POST /a2a/invoke with {"invokes": [...]}; if that fails (e.g. 404), sends n concurrent POSTs to /a2a/{agent}/invoke. 100_batch_* use _batch_sizes_for_100(seed_offset) so batch sizes are 5–20 (last may be 1–4), deterministic per scenario; 100_batch_light adds 2s sleep between waves.

Stub: ThreadingHTTPServer so multiple concurrent requests from the gateway are handled in parallel (wall time ~max(delay) per wave when concurrent).

Delay consistency (main vs branch):
  Delays are deterministic: A2A_BENCH_SEED fixes the per-scenario delay sequences.
  Both the main run (baseline capture) and the branch run must use this same
  benchmark code: stub HTTP agent that sleeps then responds, and _delays_for_scenario
  with the same seed. Do not capture baseline with older mock-based code; use this
  file on main so agent response delays are identical for a fair comparison.

Usage:
  make bench BENCH=a2a_invoke
  make bench a2a_invoke

  # Save current run as baseline (e.g. from main to record legacy main timings)
  SAVE_A2A_INVOKE_BASELINE=1 make bench a2a_invoke

Baseline: one run on main (full suite, SAVE_A2A_INVOKE_BASELINE=1) stores all
scenario results in benchmarks/a2a_invoke_baseline_main.json; then back to branch
and keep that file for comparison.
"""

# Standard
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

# Third-Party
import pytest

# Hardcoded main commit to compare against. Update when refreshing baseline from main.
A2A_INVOKE_MAIN_BASELINE_COMMIT = "b4d87709421ca2b0aab648ad145ecc50bd316433"

BASELINE_FILE = Path(__file__).resolve().parent / "a2a_invoke_baseline_main.json"

# Collected for summary table (scenario_id, mean_ms, base_mean, x_mean)
_BASELINE_COMPARISONS: list[tuple[str, float, float, str]] = []

INVOKE_AGENT_NAME = "bench-agent"
# Fixed seed so delay sequences are identical on main and branch (required for fair comparison)
A2A_BENCH_SEED = 42
# Keep under gateway max_param_length (default 10_000) so validation accepts the payload
HEAVY_PARAM_SIZE = 9_000

# Payloads
LIGHT_PAYLOAD = {"parameters": {"query": "bench"}, "interaction_type": "query"}
HEAVY_PAYLOAD = {
    "parameters": {"query": "x" * HEAVY_PARAM_SIZE, "bench": True},
    "interaction_type": "query",
}

# Small mocked response (same for light/heavy; heavy is request size only)
MOCK_RESPONSE_SMALL = {"response": "ok", "status": "success"}


def _get_current_commit():
    """Return current git commit SHA or empty string."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=Path(__file__).resolve().parent.parent,
        )
        return (out.stdout or "").strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _use_rust_path():
    import mcpgateway.main as main_mod

    return getattr(main_mod, "rust_a2a", None) is not None


def _delays_for_scenario(delay_spec, count):
    """Return list of delay seconds for each internal request (count), deterministic.
    Uses A2A_BENCH_SEED so main and branch see the same delay sequence for the same scenario.
    """
    random.seed(A2A_BENCH_SEED)
    if delay_spec == "0.1":
        return [0.1] * count
    if delay_spec == "3":
        return [3.0] * count
    if delay_spec == "0.1-1":
        return [random.uniform(0.1, 1.0) for _ in range(count)]
    return [0.1] * count


def _batch_sizes_for_100(seed_offset: int = 0) -> list[int]:
    """Return list of batch sizes in [5, 20] that sum to 100, deterministic.
    Uses A2A_BENCH_SEED + seed_offset so the same scenario always gets the same sequence.
    Last batch may be 1–4 if remainder is smaller than 5.
    """
    random.seed(A2A_BENCH_SEED + seed_offset)
    sizes = []
    remaining = 100
    while remaining > 0:
        chunk = min(remaining, random.randint(5, 20)) if remaining > 20 else remaining
        sizes.append(chunk)
        remaining -= chunk
    return sizes


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTPServer that handles each request in a separate thread so concurrent POSTs can run in parallel."""

    daemon_threads = True


def _start_stub_agent_server(delays):
    """Start a real HTTP server that simulates agent response delay. Returns (base_url, stop_fn).
    Each POST receives the next delay from the list, sleeps that many seconds, then returns 200 + JSON.
    Uses ThreadingHTTPServer: when the gateway (e.g. Rust invoker) sends N requests at once, N handler
    threads run in parallel—each sleeps its delay then responds—so all N responses are sent back
    after ~max(delay), not after sum(delay). The HTTP request is always real; only the response timing
    is simulated per request.
    """
    delays_lock = threading.Lock()
    delays_list = list(delays)

    class StubHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            # Read request body so the gateway can complete sending (required for large payloads)
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length:
                self.rfile.read(content_length)
            with delays_lock:
                d = delays_list.pop(0) if delays_list else 0.1
            time.sleep(d)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(MOCK_RESPONSE_SMALL).encode())

        def log_message(self, format, *args):
            pass

    server = _ThreadedHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    def stop():
        server.shutdown()
    return base_url, stop


def _ensure_bench_agent_in_db(endpoint_url, encrypted_auth=False):
    """Create or update the bench A2A agent in the DB so the gateway can invoke it (real HTTP).

    If encrypted_auth is True, sets auth_type='bearer' and auth_value to encode_auth(...)
    so the encrypted-auth path (Rust decrypt) is exercised when AUTH_ENCRYPTION_SECRET is set.
    """
    from sqlalchemy import select

    from mcpgateway.db import A2AAgent as DbA2AAgent
    from mcpgateway.db import SessionLocal
    from mcpgateway.utils.create_slug import slugify

    db = SessionLocal()
    try:
        existing = db.execute(
            select(DbA2AAgent).where(DbA2AAgent.name == INVOKE_AGENT_NAME)
        ).scalars().first()
        slug = slugify(INVOKE_AGENT_NAME)
        if existing:
            existing.endpoint_url = endpoint_url
            existing.enabled = True
            if encrypted_auth:
                from mcpgateway.utils.services_auth import encode_auth

                existing.auth_type = "bearer"
                existing.auth_value = encode_auth({"Authorization": "Bearer bench-token"})
            else:
                existing.auth_type = None
                existing.auth_value = None
            db.commit()
            return
        agent = DbA2AAgent(
            name=INVOKE_AGENT_NAME,
            slug=slug,
            endpoint_url=endpoint_url,
            agent_type="generic",
            protocol_version="1.0",
            visibility="public",
            enabled=True,
        )
        if encrypted_auth:
            from mcpgateway.utils.services_auth import encode_auth

            agent.auth_type = "bearer"
            agent.auth_value = encode_auth({"Authorization": "Bearer bench-token"})
        db.add(agent)
        db.commit()
    finally:
        db.close()


def _run_single(client, headers, agent_name, payload):
    r = client.post(
        f"/a2a/{agent_name}/invoke",
        json=payload,
        headers=headers,
    )
    assert r.status_code == 200, r.text


def _run_n_singles(client, headers, agent_name, payload, n):
    """Run n sequential POST /a2a/{agent}/invoke."""
    for _ in range(n):
        _run_single(client, headers, agent_name, payload)


def _try_batch_of_n(client, headers, agent_name, payload, n):
    """Try one POST to /a2a/invoke with n invokes. Return True if 200 and all results ok, else False."""
    invokes = [
        {
            "agent_name": agent_name,
            "parameters": payload.get("parameters", payload),
            "interaction_type": payload.get("interaction_type", "query"),
        }
        for _ in range(n)
    ]
    r = client.post("/a2a/invoke", json={"invokes": invokes}, headers=headers)
    if r.status_code != 200:
        return False
    try:
        data = r.json()
    except Exception:
        return False
    if not (isinstance(data, list) and len(data) == n):
        return False
    for item in data:
        if isinstance(item, dict) and item.get("status_code") not in (None, 200):
            return False
    return True


def _run_n_concurrent(client, headers, agent_name, payload, n):
    """Run n POSTs to /a2a/{agent_name}/invoke concurrently (ThreadPoolExecutor)."""
    with ThreadPoolExecutor(max_workers=n) as executor:
        futures = [
            executor.submit(
                client.post,
                f"/a2a/{agent_name}/invoke",
                json=payload,
                headers=headers,
            )
            for _ in range(n)
        ]
        for fut in as_completed(futures):
            r = fut.result()
            assert r.status_code == 200, r.text


def _run_one_batch_of_n(client, headers, agent_name, payload, n):
    """Run n invokes: use POST /a2a/invoke with invokes list if available, else n concurrent POSTs to single-invoke."""
    if _try_batch_of_n(client, headers, agent_name, payload, n):
        return
    _run_n_concurrent(client, headers, agent_name, payload, n)


def _run_100_in_waves_of_10(client, headers, agent_name, payload):
    """Run 100 invokes in 10 waves of 10 (no pause between waves)."""
    for _ in range(10):
        _run_n_singles(client, headers, agent_name, payload, 10)


# ---------------------------------------------------------------------------
# Baseline: scenarios dict, merge on save, compare per scenario
# ---------------------------------------------------------------------------


def _handle_baseline(benchmark, scenario_id):
    """Save this scenario if SAVE_A2A_INVOKE_BASELINE=1; else load and print vs baseline."""
    meta = benchmark.stats
    stats = getattr(meta, "stats", meta)
    mean_ms = getattr(stats, "mean", 0) * 1000
    median_ms = getattr(stats, "median", 0) * 1000

    save_baseline = os.getenv("SAVE_A2A_INVOKE_BASELINE", "").strip().lower() in ("1", "true", "yes")

    if save_baseline:
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if BASELINE_FILE.exists():
            with open(BASELINE_FILE) as f:
                data = json.load(f)
        if "scenarios" not in data:
            data["scenarios"] = {}
        data["commit"] = _get_current_commit()
        data["delay_seed"] = A2A_BENCH_SEED
        data["scenarios"][scenario_id] = {
            "mean_ms": mean_ms,
            "median_ms": median_ms,
            "rounds": getattr(stats, "rounds", 0),
            "iterations": getattr(meta, "iterations", 0),
        }
        with open(BASELINE_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n[bench] Saved scenario {scenario_id!r} to {BASELINE_FILE}")
        return

    if not BASELINE_FILE.exists():
        print(f"\n[bench] No baseline at {BASELINE_FILE}. Run from main with SAVE_A2A_INVOKE_BASELINE=1.")
        return

    with open(BASELINE_FILE) as f:
        baseline = json.load(f)

    baseline_commit = baseline.get("commit", "")
    if baseline_commit != A2A_INVOKE_MAIN_BASELINE_COMMIT:
        print(
            f"\n[bench] Baseline commit {baseline_commit!r} != main {A2A_INVOKE_MAIN_BASELINE_COMMIT!r}; skip."
        )
        return

    baseline_seed = baseline.get("delay_seed")
    if baseline_seed is not None and baseline_seed != A2A_BENCH_SEED:
        print(
            f"\n[bench] Baseline delay_seed={baseline_seed!r} != current A2A_BENCH_SEED={A2A_BENCH_SEED!r}; "
            "delays may differ, comparison may be unfair."
        )

    scenarios = baseline.get("scenarios", {})
    if scenario_id not in scenarios:
        print(f"\n[bench] No baseline for scenario {scenario_id!r}")
        return

    base = scenarios[scenario_id]
    base_mean = base.get("mean_ms", 0)
    base_median = base.get("median_ms", 0)
    diff_mean = mean_ms - base_mean
    diff_median = median_ms - base_median
    pct_mean = (100.0 * diff_mean / base_mean) if base_mean else 0
    pct_median = (100.0 * diff_median / base_median) if base_median else 0

    def _x_str(current: float, base_val: float) -> str:
        if not base_val:
            return "1.00x"
        r = current / base_val
        if r < 1:
            return f"{1 / r:.2f}x faster"
        if r > 1:
            return f"{r:.2f}x slower"
        return "1.00x"

    x_mean = _x_str(mean_ms, base_mean)
    x_median = _x_str(median_ms, base_median)

    _BASELINE_COMPARISONS.append((scenario_id, mean_ms, base_mean, x_mean))

    print(f"\n[bench] {scenario_id} vs main ({A2A_INVOKE_MAIN_BASELINE_COMMIT[:8]}):")
    print(f"        current  mean={mean_ms:.3f}ms  median={median_ms:.3f}ms")
    print(f"        baseline mean={base_mean:.3f}ms  median={base_median:.3f}ms")
    print(f"        diff     mean={diff_mean:+.3f}ms ({pct_mean:+.1f}%)  median={diff_median:+.3f}ms ({pct_median:+.1f}%)")
    print(f"        vs base  mean={x_mean}  median={x_median}")


# ---------------------------------------------------------------------------
# Scenario tests 1–15
# ---------------------------------------------------------------------------


def test_a2a_invoke_single_light(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 1: single invoke, light payload, 0.1s delay. Real gateway→agent HTTP."""
    delays = _delays_for_scenario("0.1", 1)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_single(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "single_light")


def test_a2a_invoke_single_light_encrypted_auth(benchmark, a2a_bench_client, a2a_bench_auth_headers, monkeypatch):
    """Single invoke with encrypted agent auth (Rust decrypt path). Same as single_light but agent has encrypted auth_value.

    Requires AUTH_ENCRYPTION_SECRET to be set in the environment before the gateway starts so the queue
    is inited with the secret; otherwise the request may get 503 (queue full / not inited for decrypt).
    """
    from pydantic import SecretStr

    from mcpgateway.config import get_settings

    monkeypatch.setattr(get_settings(), "auth_encryption_secret", SecretStr("bench-secret-32-bytes-long!!!!!!!!"))
    delays = _delays_for_scenario("0.1", 1)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url, encrypted_auth=True)

        def run():
            r = a2a_bench_client.post(
                f"/a2a/{INVOKE_AGENT_NAME}/invoke",
                json=LIGHT_PAYLOAD,
                headers=a2a_bench_auth_headers,
            )
            if r.status_code == 503 and "queue full" in (r.json().get("detail") or ""):
                pytest.skip("A2A queue full or not inited with secret; set AUTH_ENCRYPTION_SECRET at process start")
            assert r.status_code == 200, r.text

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "single_light_encrypted_auth")


def test_a2a_invoke_single_heavy(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 2: single invoke, heavy payload, 0.1s delay. Real gateway→agent HTTP."""
    delays = _delays_for_scenario("0.1", 1)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_single(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, HEAVY_PAYLOAD)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "single_heavy")


def test_a2a_invoke_single_slow(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 3: single invoke, light, 3s delay. Real gateway→agent HTTP."""
    delays = _delays_for_scenario("3", 1)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_single(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "single_slow")


def test_a2a_invoke_10_single_light(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 4: 10 single invokes, light, 0.1–1s delay (seeded). Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 10)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_n_singles(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD, 10)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "10_single_light")


def test_a2a_invoke_10_single_heavy(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 5: 10 single invokes, heavy, 0.1–1s delay (seeded). Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 10)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_n_singles(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, HEAVY_PAYLOAD, 10)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "10_single_heavy")


def test_a2a_invoke_10_batch_light(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 6: 10 invokes as batch (10 POSTs). Real HTTP; Rust can run concurrent."""
    delays = _delays_for_scenario("0.1-1", 10)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_one_batch_of_n(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD, 10)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "10_batch_light")


def test_a2a_invoke_10_batch_heavy(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 7: 10 invokes as batch, heavy. Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 10)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_one_batch_of_n(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, HEAVY_PAYLOAD, 10)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "10_batch_heavy")


def test_a2a_invoke_10_single_slow(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 8: 10 single invokes, light, 0.1–1s delay (seeded). Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 10)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_n_singles(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD, 10)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "10_single_slow")


def test_a2a_invoke_10_batch_slow(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 9: 10 batch invokes, light, 0.1–1s delay (seeded). Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 10)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_one_batch_of_n(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD, 10)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "10_batch_slow")


@pytest.mark.slow
@pytest.mark.benchmark(min_rounds=1)
def test_a2a_invoke_100_single_light(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 10: 100 single invokes in waves of 10, light, 0.1–1s delay. Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 100)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_100_in_waves_of_10(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "100_single_light")


@pytest.mark.slow
@pytest.mark.benchmark(min_rounds=1)
def test_a2a_invoke_100_single_heavy(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 11: 100 single invokes in waves of 10, heavy. Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 100)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_100_in_waves_of_10(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, HEAVY_PAYLOAD)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "100_single_heavy")


@pytest.mark.slow
@pytest.mark.benchmark(min_rounds=1)
def test_a2a_invoke_100_single_slow(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 12: 100 single invokes in waves of 10, light, 0.1–1s delay. Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 100)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)

        def run():
            _run_100_in_waves_of_10(a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "100_single_slow")


@pytest.mark.slow
@pytest.mark.benchmark(min_rounds=1)
def test_a2a_invoke_100_batch_light(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 13: 100 invokes in batches of 5–20 (seeded), light. Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 100)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)
        batch_sizes = _batch_sizes_for_100(seed_offset=0)

        def run():
            for n in batch_sizes:
                _run_one_batch_of_n(
                    a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD, n
                )
                time.sleep(2.0)

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "100_batch_light")


@pytest.mark.slow
@pytest.mark.benchmark(min_rounds=1)
def test_a2a_invoke_100_batch_heavy(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 14: 100 invokes in batches of 5–20 (seeded), heavy. Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 100)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)
        batch_sizes = _batch_sizes_for_100(seed_offset=1)

        def run():
            for n in batch_sizes:
                _run_one_batch_of_n(
                    a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, HEAVY_PAYLOAD, n
                )

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "100_batch_heavy")


@pytest.mark.slow
@pytest.mark.benchmark(min_rounds=1)
def test_a2a_invoke_100_batch_slow(benchmark, a2a_bench_client, a2a_bench_auth_headers):
    """Scenario 15: 100 invokes in batches of 5–20 (seeded), light, 0.1–1s delay. Real HTTP."""
    delays = _delays_for_scenario("0.1-1", 100)
    base_url, stop = _start_stub_agent_server(delays)
    try:
        _ensure_bench_agent_in_db(base_url)
        batch_sizes = _batch_sizes_for_100(seed_offset=2)

        def run():
            for n in batch_sizes:
                _run_one_batch_of_n(
                    a2a_bench_client, a2a_bench_auth_headers, INVOKE_AGENT_NAME, LIGHT_PAYLOAD, n
                )

        benchmark(run)
    finally:
        stop()
    _handle_baseline(benchmark, "100_batch_slow")
