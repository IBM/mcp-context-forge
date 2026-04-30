# -*- coding: utf-8 -*-
"""Location: ./tests/loadtest/locustfile_rate_limiter_scale.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Rate limiter algorithm scale test — resource divergence across algorithms.
Why this test exists
--------------------
The algorithm comparison test (locustfile_rate_limiter_algorithms.py) uses a
single user, which creates one Redis key per algorithm.  At that scale the
memory difference between fixed_window (1 integer per key) and sliding_window
(30 timestamps per key) is invisible — a few hundred bytes vs a single integer.
This test uses many unique users so each one creates its own rate limit key.
Redis memory diverges visibly as user count grows:
  fixed_window    1 key  per user  =   N integers          (O(N))
  sliding_window  1 key  per user  =   N × W timestamps    (O(N × W))
  token_bucket    1 hash per user  =   tokens + last_refill (~0.2 KiB/key)
With 100 users and a 30/m limit (W=30 timestamps/window):
  fixed_window    ~100 Redis keys   → ~10 KB
  sliding_window  ~100 Redis keys   → ~30–90 KB  (sorted sets, ~30 entries each)
At 1,000 users the gap becomes ~1 MB vs ~30 MB — clearly measurable.
How it works
------------
  - N unique users (default 100), each with a distinct email identity
  - Each user's JWT sub is unique → separate rate limit key in Redis per user
  - All users send at 1 req/s (60 req/min) = 2× the 30/m per-user limit
  - docker stats streams gateway CPU/memory for the full test duration
  - A background thread polls Redis memory (DBSIZE + INFO memory) every 10s
    and builds a timeline showing how memory grows as users are added
  - Results show: rate accuracy, gateway resources, and Redis memory timeline
Run it the same way as the single-user test — just more users:
  docker exec mcp-context-forge-redis-1 redis-cli FLUSHDB
  RL_ALGORITHM=fixed_window make benchmark-rate-limiter-scale
  # restart gateways, flush Redis
  RL_ALGORITHM=sliding_window make benchmark-rate-limiter-scale
Environment Variables
---------------------
  RL_ALGORITHM:           Algorithm (default: fixed_window)
  RL_LIMIT_PER_MIN:       Configured limit (default: 30)
  RL_USERS:               Number of unique users (default: 500)
  RL_SPAWN_RATE:          Users spawned per second (default: 20)
  RL_RUN_TIME:            Test duration (default: 300s — 5 full 60s windows)
  RL_REQS_PER_SECOND:     Request pace per user (default: 1.0 = 60 req/min, 2× limit)
  MCP_SERVER_ID:          Virtual server UUID (auto-detected if empty)
  DOCKER_GATEWAY_PATTERN: Container name pattern (default: mcp-context-forge-gateway)
  DOCKER_REDIS_CONTAINER: Redis container name (default: mcp-context-forge-redis-1)
  JWT_SECRET_KEY:         JWT signing secret (default: my-test-key)
  JWT_ALGORITHM:          JWT algorithm (default: HS256)
  JWT_AUDIENCE:           JWT audience (default: mcpgateway-api)
  JWT_ISSUER:             JWT issuer (default: mcpgateway)
"""

# Standard
from collections import defaultdict
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from typing import Any
import uuid

# Third-Party
from locust import constant_throughput, events, tag, task
from locust.contrib.fasthttp import FastHttpUser
from locust.runners import WorkerRunner

# =============================================================================
# Configuration
# =============================================================================


def _load_env_file() -> dict[str, str]:
    env_vars: dict[str, str] = {}
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ]
    for path in search_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        env_vars[key.strip()] = value.strip().strip("\"'")
            break
    return env_vars


_ENV = _load_env_file()


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key) or _ENV.get(key) or default


JWT_SECRET_KEY = _cfg("JWT_SECRET_KEY", "my-test-key")
JWT_ALGORITHM_CFG = _cfg("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = _cfg("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = _cfg("JWT_ISSUER", "mcpgateway")
MCP_SERVER_ID = _cfg("MCP_SERVER_ID", "")

RL_ALGORITHM = _cfg("RL_ALGORITHM", "fixed_window")
RL_LIMIT_PER_MIN = int(_cfg("RL_LIMIT_PER_MIN", "30"))
RL_USERS = int(_cfg("RL_USERS", "100"))
RL_SPAWN_RATE = int(_cfg("RL_SPAWN_RATE", "10"))
RL_RUN_TIME = _cfg("RL_RUN_TIME", "300s")

DOCKER_GATEWAY_PATTERN = _cfg("DOCKER_GATEWAY_PATTERN", "mcp-context-forge-gateway")
DOCKER_REDIS_CONTAINER = _cfg("DOCKER_REDIS_CONTAINER", "mcp-context-forge-redis-1")

_REQS_PER_SECOND = float(_cfg("RL_REQS_PER_SECOND", "1.0"))

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# =============================================================================
# Shared state
# =============================================================================

_server_id: str = ""
_tool_names: list[str] = []
_detect_done = False
_test_start_time: float = 0.0

# Per-user identity counter — assigns each locust user a slot in _user_tokens
_user_counter = 0
_user_counter_lock = threading.Lock()

# Populated by _bootstrap_users() before locust users start:
#   index N → gateway-issued access_token for scale-user-N
_user_tokens: list[str] = []

# Tracks what was registered so _cleanup_users() can delete it all
_registered_state: dict[str, Any] = {}  # {"host": ..., "users": [{"email": ...}]}

_stats_lock = threading.Lock()

# 30-second window buckets — {bucket_index: {"allowed": int, "blocked": int}}
_bucket_stats: dict[int, dict[str, int]] = defaultdict(lambda: {"allowed": 0, "blocked": 0})

# Pre-bootstrap Redis snapshot (t=0, before any RL keys exist)
_redis_baseline: dict[str, Any] | None = None
# Algorithm detected from Redis key types after steady state
_detected_algorithm: str = ""
# Number of bootstrapped users with valid JWT tokens
_valid_users: int = 0

_TEST_PASSWORD = "ScaleTest123!"  # pragma: allowlist secret
_USER_PREFIX = "rl-scale"

# =============================================================================
# docker stats monitor (streaming subprocess)
# =============================================================================

_stats_file: Any = None
_stats_proc: Any = None
_stats_path: str = ""


def _mem_to_mib(raw: str) -> float:
    raw = raw.strip()
    m = re.match(r"([\d.]+)\s*([KMGTkmgt]i?[Bb]?)", raw)
    if not m:
        return 0.0
    val, unit = float(m.group(1)), m.group(2).upper()
    if unit.startswith("K"):
        return val / 1024
    if unit.startswith("M"):
        return val
    if unit.startswith("G"):
        return val * 1024
    if unit.startswith("T"):
        return val * 1024 * 1024
    return val


def _parse_stats_file(path: str) -> dict[str, dict[str, float]]:
    _ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\[[?][0-9;]*[A-Za-z]")
    samples: dict[str, list[tuple[float, float]]] = defaultdict(list)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = _ansi.sub("", line).strip()
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                name = parts[0].strip()
                if not name:
                    continue
                used_mem = parts[1].split("/")[0].strip()
                mem_mib = _mem_to_mib(used_mem)
                cpu_str = parts[2].replace("%", "").strip()
                try:
                    cpu = float(cpu_str)
                except ValueError:
                    continue
                if mem_mib > 0:
                    samples[name].append((mem_mib, cpu))
    except FileNotFoundError:
        pass
    result: dict[str, dict[str, float]] = {}
    for name, pts in samples.items():
        if not pts:
            continue
        mems = [p[0] for p in pts]
        cpus = [p[1] for p in pts]
        result[name] = {
            "mem_avg": sum(mems) / len(mems),
            "mem_peak": max(mems),
            "cpu_avg": sum(cpus) / len(cpus),
            "cpu_peak": max(cpus),
            "samples": len(pts),
        }
    return result


def _start_stats_monitor() -> None:
    global _stats_file, _stats_proc, _stats_path  # pylint: disable=global-statement
    try:
        fd, _stats_path = tempfile.mkstemp(prefix="rl_scale_stats_", suffix=".tsv")
        _stats_file = os.fdopen(fd, "w")
        _stats_proc = subprocess.Popen(
            ["docker", "stats", "--format", "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}"],
            stdout=_stats_file,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.error("docker stats monitor failed to start: %s", exc)


def _stop_stats_monitor() -> dict[str, dict[str, float]]:
    global _stats_proc, _stats_file  # pylint: disable=global-statement
    if _stats_proc:
        try:
            _stats_proc.terminate()
            _stats_proc.wait(timeout=5)
        except Exception:
            pass
        _stats_proc = None
    if _stats_file:
        try:
            _stats_file.flush()
            _stats_file.close()
        except Exception:
            pass
        _stats_file = None
    return _parse_stats_file(_stats_path) if _stats_path else {}


# =============================================================================
# Redis memory timeline (background polling thread)
# =============================================================================

# Timeline entries: list of {"elapsed": float, "keys": int, "mem_mib": float, "users": int}
_redis_timeline: list[dict[str, Any]] = []
_redis_poll_running = False
_redis_poll_thread: threading.Thread | None = None
_active_users = 0  # updated by user on_start/on_stop


def _scan_redis_pattern(pattern: str, timeout: int = 20) -> int:
    """Count Redis keys matching a pattern using non-blocking SCAN iteration."""
    try:
        r = subprocess.run(
            ["docker", "exec", DOCKER_REDIS_CONTAINER, "redis-cli", "--scan", "--pattern", pattern],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode != 0:
            return 0
        return sum(1 for line in r.stdout.splitlines() if line.strip())
    except Exception:
        return 0


def _scan_rl_dimension(dimension: str, timeout: int = 20) -> int:
    """Count rate-limiter keys for a given dimension, regardless of tenant prefix.

    After the tenant-scoping change in the gateway's tool-service (G1/G2 from
    issue #4343), keys for team-owned tools land at
    ``rl:{tenant_id}:{dimension}:{id}:{window}`` instead of
    ``rl:{dimension}:{id}:{window}``. Single-tenant deployments keep the
    unprefixed layout. Scan both so this test works before and after the
    change, and against mixed deployments.
    """
    return _scan_redis_pattern(f"rl:{dimension}:*", timeout=timeout) + _scan_redis_pattern(f"rl:*:{dimension}:*", timeout=timeout)


def _scan_rl_sample_keys(dimension: str, timeout: int = 15) -> list[str]:
    """Return sample rate-limiter keys for a dimension, scanning both layouts.

    Used by algorithm-detection to read a representative key's Redis data
    type. Returns the union of unprefixed and tenant-prefixed keys.
    """
    keys: list[str] = []
    for pattern in (f"rl:{dimension}:*", f"rl:*:{dimension}:*"):
        try:
            r = subprocess.run(
                ["docker", "exec", DOCKER_REDIS_CONTAINER, "redis-cli", "--scan", "--pattern", pattern],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if r.returncode == 0:
                keys.extend(line.strip() for line in r.stdout.splitlines() if line.strip())
        except Exception:
            continue
    return keys


def _poll_redis_once() -> dict[str, Any] | None:
    """Query Redis for key count and memory usage via docker exec.

    Returns both total_keys (DBSIZE) and rl_keys (user:* + tenant:* only)
    so the summary can report RL-specific memory per key without noise from
    unrelated keys (session store, user DB cache, etc.).
    """
    try:
        # DBSIZE — total key count (for reference / sanity check)
        r_dbsize = subprocess.run(
            ["docker", "exec", DOCKER_REDIS_CONTAINER, "redis-cli", "DBSIZE"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        total_keys = int(r_dbsize.stdout.strip()) if r_dbsize.returncode == 0 else 0

        # RL-specific keys only (per-user and per-team buckets). Scan both
        # the unprefixed layout (rl:{dim}:*) and the tenant-prefixed layout
        # (rl:{tenant}:{dim}:*) introduced by the G1/G2 fix in #4343.
        rl_keys = _scan_rl_dimension("user") + _scan_rl_dimension("tenant")

        # INFO memory — used_memory in bytes
        r_mem = subprocess.run(
            ["docker", "exec", DOCKER_REDIS_CONTAINER, "redis-cli", "INFO", "memory"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        mem_bytes = 0
        for line in r_mem.stdout.splitlines():
            if line.startswith("used_memory:"):
                mem_bytes = int(line.split(":")[1].strip())
                break

        return {
            "elapsed": time.time() - _test_start_time,
            "total_keys": total_keys,
            "rl_keys": rl_keys,
            "keys": rl_keys,  # alias used by display code
            "mem_mib": mem_bytes / (1024 * 1024),
            "users": _active_users,
        }
    except Exception as exc:
        logger.warning("Redis poll failed: %s", exc)
        return None


def _detect_algorithm_from_redis() -> str:
    """Detect the active rate-limiting algorithm by inspecting Redis key types.

    After steady state there should be user:* keys in Redis.  Their data type
    reveals which algorithm is running:
      string  → fixed_window   (single integer counter)
      zset    → sliding_window (sorted set of request timestamps)
      hash    → token_bucket   (tokens + last_refill timestamp)
    """
    try:
        sample_keys = _scan_rl_sample_keys("user")
        if not sample_keys:
            return f"unknown — no rl:user:* or rl:*:user:* keys in Redis " f"(expected for {RL_ALGORITHM}?)"

        r_type = subprocess.run(
            ["docker", "exec", DOCKER_REDIS_CONTAINER, "redis-cli", "TYPE", sample_keys[0]],
            capture_output=True,
            text=True,
            timeout=5,
        )
        key_type = r_type.stdout.strip().lower()

        mapping = {
            "string": "fixed_window",
            "zset": "sliding_window",
            "hash": "token_bucket",
        }
        detected = mapping.get(key_type, f"unknown ({key_type})")
        match = "✅ matches config" if detected == RL_ALGORITHM else f"⚠️  MISMATCH — config says {RL_ALGORITHM}"
        return f"{detected}  [Redis key type: {key_type}]  {match}"
    except Exception as exc:
        return f"detection failed: {exc}"


def _redis_poll_loop() -> None:
    while _redis_poll_running:
        entry = _poll_redis_once()
        if entry:
            _redis_timeline.append(entry)
        time.sleep(5)


def _start_redis_monitor() -> None:
    global _redis_poll_running, _redis_poll_thread  # pylint: disable=global-statement
    _redis_poll_running = True
    _redis_poll_thread = threading.Thread(target=_redis_poll_loop, daemon=True)
    _redis_poll_thread.start()


def _stop_redis_monitor() -> None:
    global _redis_poll_running  # pylint: disable=global-statement
    _redis_poll_running = False
    if _redis_poll_thread:
        _redis_poll_thread.join(timeout=6)


# =============================================================================
# Admin JWT — used only for setup/teardown API calls
# =============================================================================


def _admin_jwt() -> str:
    """Create a short-lived JWT for the platform admin (setup/teardown only)."""
    # First-Party
    from mcpgateway.utils.create_jwt_token import _create_jwt_token  # pylint: disable=import-outside-toplevel

    admin_email = _cfg("PLATFORM_ADMIN_EMAIL", "admin@example.com")
    return _create_jwt_token(
        {"sub": admin_email},
        user_data={"email": admin_email, "is_admin": True, "auth_provider": "local"},
        teams=None,
        secret=JWT_SECRET_KEY,
    )


def _admin_session(host: str) -> Any:
    # Third-Party
    import requests  # pylint: disable=import-outside-toplevel

    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {_admin_jwt()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )
    s.base_url = host  # type: ignore[attr-defined]
    return s


# =============================================================================
# User bootstrap and cleanup — follows isolation test pattern
# =============================================================================


def _bootstrap_users(host: str) -> None:
    """Register N test users via the admin API and build per-user JWTs.

    Strategy:
      1. Discover a virtual server with tools (admin credentials)
      2. Register N users in the gateway DB with is_admin=True so they can
         access public servers without needing team-scoped RBAC assignment
      3. Build a short-lived admin JWT for each user (unique sub → unique
         rate-limit key in Redis)

    Tokens are stored in _user_tokens[i] for ScaleComparisonUser to pick up.
    """
    global _user_tokens, _registered_state, _server_id, _tool_names  # pylint: disable=global-statement

    # Third-Party
    import requests  # pylint: disable=import-outside-toplevel

    # First-Party
    from mcpgateway.utils.create_jwt_token import _create_jwt_token  # pylint: disable=import-outside-toplevel

    admin = _admin_session(host)

    # ------------------------------------------------------------------
    # 1. Discover server and tools (using admin credentials)
    # ------------------------------------------------------------------
    server_ids_to_try: list[str] = [MCP_SERVER_ID] if MCP_SERVER_ID else []
    if not server_ids_to_try:
        resp = admin.get(f"{host}/servers", timeout=10)
        all_servers = resp.json() if resp.status_code == 200 else []
        server_ids_to_try = [s.get("id", "") for s in (all_servers if isinstance(all_servers, list) else []) if s.get("id")]

    for sid in server_ids_to_try:
        try:
            resp = admin.post(
                f"{host}/servers/{sid}/mcp",
                json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}},
                headers={**dict(admin.headers), "Accept": "application/json, text/event-stream"},
                timeout=10,
            )
            if resp.status_code == 200:
                tools = [t["name"] for t in resp.json().get("result", {}).get("tools", [])]
                if tools:
                    _server_id = sid
                    _tool_names = tools
                    break
        except Exception as exc:
            logger.warning("Tool detect failed for %s: %s", sid, exc)

    # ------------------------------------------------------------------
    # 2. Register N users in the DB (is_admin=True so they can use public servers)
    #    Build a JWT per user — each unique sub → unique rate-limit key in Redis
    # ------------------------------------------------------------------
    registered: list[dict[str, str]] = []
    tokens: list[str] = []
    run_id = uuid.uuid4().hex[:6]

    for i in range(RL_USERS):
        email = f"{_USER_PREFIX}-{run_id}-{i:04d}@loadtest.internal"
        try:
            r = admin.post(
                f"{host}/auth/email/admin/users",
                json={
                    "email": email,
                    "password": _TEST_PASSWORD,
                    "full_name": f"Scale Test User {i:04d}",
                    "is_admin": True,
                    "is_active": True,
                    "password_change_required": False,
                },
                timeout=10,
            )
            if r.status_code not in (200, 201):
                logger.warning("User registration failed for %s: %s %s", email, r.status_code, r.text[:200])
                tokens.append("")
                registered.append({"email": email})
                continue

            user_jwt = _create_jwt_token(
                {"sub": email},
                user_data={"email": email, "is_admin": True, "auth_provider": "local"},
                teams=None,
                secret=JWT_SECRET_KEY,
            )
            tokens.append(user_jwt)
            registered.append({"email": email})

        except Exception as exc:
            logger.warning("Bootstrap failed for user %d (%s): %s", i, email, exc)
            tokens.append("")
            registered.append({"email": email})

    _user_tokens = tokens
    _registered_state = {"host": host, "users": registered}

    valid = sum(1 for t in tokens if t)
    global _valid_users  # pylint: disable=global-statement
    _valid_users = valid
    logger.error("Bootstrap complete: %d/%d users registered with valid tokens", valid, RL_USERS)


def _cleanup_users() -> None:
    """Delete all test users registered during bootstrap."""
    if not _registered_state:
        return

    host = _registered_state.get("host", "")
    if not host:
        return

    admin = _admin_session(host)

    for user in _registered_state.get("users", []):
        email = user.get("email", "")
        if email:
            try:
                admin.delete(f"{host}/auth/email/admin/users/{email}", timeout=10)
            except Exception:
                pass

    logger.error("Cleanup complete: deleted %d users", len(_registered_state.get("users", [])))


# =============================================================================
# Event handlers
# =============================================================================


@events.init_command_line_parser.add_listener
def set_defaults(parser):
    parser.set_defaults(users=RL_USERS, spawn_rate=RL_SPAWN_RATE, run_time=RL_RUN_TIME)


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global _test_start_time, _redis_baseline  # pylint: disable=global-statement
    _test_start_time = time.time()

    host = environment.host or "http://localhost:8080"

    # Capture Redis state BEFORE bootstrap so we have a true noise-free baseline.
    # Bootstrap registers ~N users via the admin API and may create session/auth
    # keys of its own — the baseline must be taken first.
    _redis_baseline = _poll_redis_once()
    if _redis_baseline:
        _redis_baseline["elapsed"] = 0.0  # normalise to t=0

    _bootstrap_users(host)
    _start_stats_monitor()
    _start_redis_monitor()

    if isinstance(environment.runner, WorkerRunner):
        return

    logger.error("=" * 70)
    logger.error("RATE LIMITER SCALE TEST — RESOURCE DIVERGENCE")
    logger.error("=" * 70)
    logger.error("  Host:       %s", host)
    logger.error("  Algorithm:  %s  (set in plugins/config.yaml)", RL_ALGORITHM)
    logger.error("  Users:      %d unique identities  (each gets own Redis key)", RL_USERS)
    logger.error("  Spawn rate: %d users/s  (ramp-up over %ds)", RL_SPAWN_RATE, RL_USERS // RL_SPAWN_RATE)
    logger.error("  Limit:      %d req/min per user", RL_LIMIT_PER_MIN)
    logger.error("  Pace:       %d req/s per user  (2× the limit)", int(_REQS_PER_SECOND))
    logger.error("  Duration:   %s", RL_RUN_TIME)
    logger.error("")
    logger.error("  Redis memory grows proportionally to unique users:")
    logger.error("    fixed_window   1 integer per user        (~0.1-0.3 KiB/key)")
    logger.error("    sliding_window %d timestamps per user  (~1-3 KiB/key, %dx more)", RL_LIMIT_PER_MIN, RL_LIMIT_PER_MIN)
    logger.error("    token_bucket   1 hash per user           (tokens + last_refill, ~0.2 KiB/key)")
    logger.error("=" * 70)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    global _detected_algorithm  # pylint: disable=global-statement

    # Take a final Redis snapshot before stopping monitors
    final = _poll_redis_once()
    if final:
        _redis_timeline.append(final)

    # Detect the actual algorithm from Redis key types while keys still exist
    _detected_algorithm = _detect_algorithm_from_redis()

    resource_data = _stop_stats_monitor()
    _stop_redis_monitor()
    _cleanup_users()

    if isinstance(environment.runner, WorkerRunner):
        return

    stats = environment.stats
    total_http = stats.total.num_requests
    infra_fails = stats.total.num_failures

    rl_entry = stats.entries.get(("MCP tools/call [rate-limited]", "POST"), None)
    rl_count = rl_entry.num_requests if rl_entry else 0
    allowed_entry = stats.entries.get(("MCP tools/call [allowed]", "POST"), None)
    allowed_count = allowed_entry.num_requests if allowed_entry else 0
    # Each request is classified in-place: allowed_count and rl_count are already
    # mutually exclusive — no subtraction needed.
    semantic_allowed = allowed_count
    tool_calls = allowed_count + rl_count  # excludes infra errors
    rl_pct = (rl_count / tool_calls * 100) if tool_calls > 0 else 0

    print("\n" + "=" * 90)
    print(f"RATE LIMITER SCALE TEST — {RL_ALGORITHM.upper()}")
    print("=" * 90)
    print(f"\n  Algorithm (config): {RL_ALGORITHM}")
    print(f"  Algorithm (live):   {_detected_algorithm}")
    print(f"  Unique users:       {_valid_users}/{RL_USERS} with valid tokens")
    print(f"  Configured limit:   {RL_LIMIT_PER_MIN} req/min per user")
    print(f"  Test pace:          {int(_REQS_PER_SECOND * 60)} req/min per user  (2× the limit)")

    # Rate accuracy
    print(f"\n  {'RATE LIMITING ACCURACY':^86}")
    print("  " + "-" * 86)
    print(f"  Tool call attempts:        {tool_calls:>8,}")
    print(f"  Allowed through:           {semantic_allowed:>8,}")
    print(f"  Rate-limited (blocked):    {rl_count:>8,}  ({rl_pct:.1f}%)")
    print(f"  Infrastructure failures:   {infra_fails:>8,}")

    # 30-second window breakdown
    if _bucket_stats:
        print(f"\n  {'30s WINDOW BREAKDOWN  (aggregate across all users)':^86}")
        print("  " + "-" * 86)
        print(f"  {'Window':<14} {'Start':>7} {'Allowed':>10} {'Blocked':>10} {'Block%':>8}  Note")
        print("  " + "-" * 86)
        spawn_end = RL_USERS / RL_SPAWN_RATE
        for idx in sorted(_bucket_stats):
            b = _bucket_stats[idx]
            start_s = idx * 30
            total_b = b["allowed"] + b["blocked"]
            pct = (b["blocked"] / total_b * 100) if total_b > 0 else 0.0
            note = ""
            if start_s < spawn_end:
                note = "ramp-up"
            elif (start_s % 60) == 0 and start_s > 0:
                note = "<-- window boundary"
            print(f"  t={start_s:>4}-{start_s+30:<4}s  {start_s:>6}s {b['allowed']:>10,} {b['blocked']:>10,} {pct:>7.1f}%  {note}")

    # Gateway resource table
    gateways = sorted(
        [(n, d) for n, d in resource_data.items() if DOCKER_GATEWAY_PATTERN in n],
        key=lambda x: x[0],
    )
    redis_entries = [(n, d) for n, d in resource_data.items() if DOCKER_REDIS_CONTAINER.replace("mcp-context-forge-", "") in n or "redis" in n.lower()]

    if gateways or redis_entries:
        print(f"\n  {'GATEWAY RESOURCE USAGE  (docker stats, sampled every ~1s)':^86}")
        print("  " + "-" * 86)
        print(f"  {'Container':<38} {'Mem avg':>9} {'Mem peak':>9} {'CPU avg':>8} {'CPU peak':>9} {'Samples':>7}")
        print("  " + "-" * 86)
        total_mem_avg = total_mem_peak = 0.0
        for name, d in gateways + redis_entries:
            short = name.replace("mcp-context-forge-", "")
            print(f"  {short:<38} {d['mem_avg']:>7.1f}M {d['mem_peak']:>7.1f}M {d['cpu_avg']:>7.1f}% {d['cpu_peak']:>8.1f}% {int(d['samples']):>7}")
            if DOCKER_GATEWAY_PATTERN in name:
                total_mem_avg += d["mem_avg"]
                total_mem_peak += d["mem_peak"]
        if len(gateways) > 1:
            print("  " + "-" * 86)
            print(f"  {'All gateways combined':<38} {total_mem_avg:>7.1f}M {total_mem_peak:>7.1f}M")

    # Redis memory timeline — the key comparison metric
    all_timeline = ([_redis_baseline] if _redis_baseline else []) + _redis_timeline
    if all_timeline:
        print(f"\n  {'REDIS MEMORY TIMELINE  (polled every 5s)':^86}")
        print("  " + "-" * 86)
        print(f"  {'Elapsed':>8} {'Active users':>14} {'RL keys':>10} {'Total keys':>11} {'Redis mem':>12}  Note")
        print("  " + "-" * 86)

        spawn_duration = RL_USERS / RL_SPAWN_RATE
        for entry in all_timeline:
            elapsed = entry["elapsed"]
            users = entry["users"]
            rl_keys = entry.get("rl_keys", entry.get("keys", 0))
            total_keys = entry.get("total_keys", rl_keys)
            mem = entry["mem_mib"]
            note = ""
            if elapsed < 5:
                note = "← baseline (before users spawn)"
            elif elapsed <= spawn_duration + 5:
                note = f"ramping up ({users}/{RL_USERS} users active)"
            elif elapsed > spawn_duration + 5:
                note = "all users active — steady state"
            print(f"  {elapsed:>7.0f}s {users:>14} {rl_keys:>10,} {total_keys:>11,} {mem:>10.2f} MiB  {note}")

        # Show the key insight: memory per RL key
        # Use pre-bootstrap baseline for noise-floor, steady-state sample for peak.
        # Math: delta_mem / delta_rl_keys from the SAME sample pair (not mixing max(mem) with max(keys)).
        if len(all_timeline) >= 2:
            baseline_entry = _redis_baseline if _redis_baseline else all_timeline[0]
            baseline_mem = baseline_entry["mem_mib"]
            baseline_rl_keys = baseline_entry.get("rl_keys", 0)

            spawn_end = RL_USERS / RL_SPAWN_RATE
            steady = [e for e in _redis_timeline if e["elapsed"] > spawn_end + 10]
            if not steady:
                steady = _redis_timeline[-min(3, len(_redis_timeline)) :]

            if steady:
                # Pick the steady-state sample with the most RL keys (most representative)
                best = max(steady, key=lambda e: e.get("rl_keys", 0))
                delta_mem = best["mem_mib"] - baseline_mem
                delta_rl_keys = best.get("rl_keys", 0) - baseline_rl_keys
                per_key = (delta_mem * 1024 / delta_rl_keys) if delta_rl_keys > 0 else 0

                print("  " + "-" * 86)
                print(f"  Baseline Redis mem:  {baseline_mem:.2f} MiB  (pre-bootstrap, {baseline_rl_keys:,} RL keys)")
                print(f"  Steady-state mem:    {best['mem_mib']:.2f} MiB  (+{delta_mem:.2f} MiB delta, {best.get('rl_keys', 0):,} RL keys)")
                print(f"  RL key delta:        {delta_rl_keys:,}  (baseline-subtracted)")
                if delta_rl_keys > 0:
                    print(f"  Mem per RL key:      {per_key:.2f} KiB  (delta_mem / delta_keys — same sample)")
                    print(f"\n  Expected per-key cost by algorithm:")
                    print(f"    fixed_window:    ~0.1–0.3 KiB  (single integer + TTL)")
                    print(f"    sliding_window:  ~1–3 KiB      (sorted set, {RL_LIMIT_PER_MIN} float entries)")
                    print(f"    token_bucket:    ~0.2 KiB      (hash: tokens + last_refill)")
                    if per_key < 0.5:
                        verdict = "✅ consistent with fixed_window"
                    elif per_key <= 5.0:
                        verdict = "✅ consistent with sliding_window or token_bucket"
                    else:
                        verdict = "⚠️  higher than expected — investigate"
                    print(f"\n  Observed: {per_key:.2f} KiB/key  →  {verdict}")

    # Latency
    if total_http > 0:
        print(f"\n  Response Times (ms):")
        print(f"    Average: {stats.total.avg_response_time:>8.1f}")
        print(f"    p50:     {stats.total.get_response_time_percentile(0.50):>8.1f}")
        print(f"    p90:     {stats.total.get_response_time_percentile(0.90):>8.1f}")
        print(f"    p99:     {stats.total.get_response_time_percentile(0.99):>8.1f}")

    print("\n  To compare algorithms:")
    print("    1. docker exec mcp-context-forge-redis-1 redis-cli FLUSHDB")
    print("    2. Change algorithm: in plugins/config.yaml, restart gateways")
    print("    3. RL_ALGORITHM=<algo> make benchmark-rate-limiter-scale")

    print("\n" + "=" * 90 + "\n")


# =============================================================================
# Helpers
# =============================================================================


def _jsonrpc(method: str, params: dict | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method}
    if params is not None:
        body["params"] = params
    return body


# =============================================================================
# ScaleComparisonUser — each instance has a unique identity
# =============================================================================


class ScaleComparisonUser(FastHttpUser):
    """Each locust user has a unique email identity → unique Redis key per user.

    This is what makes Redis memory diverge across algorithms:
      fixed_window   → 1 integer key per user
      sliding_window → 1 sorted-set key per user (W entries each)
      token_bucket   → no Redis key (memory-only fallback)
    """

    wait_time = constant_throughput(_REQS_PER_SECOND)
    connection_timeout = 30.0
    network_timeout = 30.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        global _user_counter  # pylint: disable=global-statement
        with _user_counter_lock:
            uid = _user_counter
            _user_counter += 1
        self._email = f"scale-user-{uid:04d}@loadtest.internal"
        self._token = _user_tokens[uid % len(_user_tokens)] if _user_tokens else ""
        self._mcp_session_id: str | None = None
        self._initialized = False

    def on_start(self) -> None:
        global _active_users  # pylint: disable=global-statement
        with _stats_lock:
            _active_users += 1
        self._ensure_initialized()

    def on_stop(self) -> None:
        global _active_users  # pylint: disable=global-statement
        with _stats_lock:
            _active_users -= 1

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._token}",
        }
        if self._mcp_session_id:
            h["Mcp-Session-Id"] = self._mcp_session_id
        return h

    def _mcp_post(self, method: str, params: dict | None, name: str) -> dict | None:
        if not _server_id:
            return None
        try:
            with self.client.post(
                f"/servers/{_server_id}/mcp",
                data=json.dumps(_jsonrpc(method, params)),
                headers=self._headers(),
                name=name,
                catch_response=True,
            ) as response:
                sid = response.headers.get("Mcp-Session-Id") if response.headers else None
                if sid:
                    self._mcp_session_id = sid
                if response.status_code in (502, 503, 504):
                    response.failure(f"Infrastructure error: {response.status_code}")
                    return None
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    return None
                try:
                    data = response.json()
                except Exception:
                    response.failure("Invalid JSON")
                    return None
                if data is None:
                    response.failure("Null response")
                    return None
                if "error" in data:
                    err = data["error"]
                    response.failure(f"JSON-RPC error {err.get('code', '?')}: {err.get('message', '?')}")
                    return None
                response.success()
                return data.get("result")
        except Exception as exc:
            logger.warning("Request failed (%s): %s", name, exc)
            return None

    def _ensure_initialized(self) -> None:
        if self._initialized or not _server_id:
            return
        result = self._mcp_post(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": f"scale-test-{self._email}", "version": "1.0.0"},
            },
            "MCP initialize",
        )
        if result is not None:
            self._initialized = True

    @task
    @tag("rate-limit", "scale", "tools")
    def call_tool(self) -> None:
        """Call a tool; classify the response in-place as allowed, rate-limited, or infra-error.

        A single tools/call request is sent. The Locust stat name is set based on
        the semantic outcome — no second request is fired:
          - 'MCP tools/call [allowed]'      — gateway processed the call normally
          - 'MCP tools/call [rate-limited]' — HTTP 429 or MCP result.isError (plugin rate-limit block)
          - 'MCP tools/call [infra-error]'  — HTTP error or malformed response
        """
        if not _tool_names or not _server_id:
            return

        tool = _tool_names[0]
        name_lower = tool.lower()
        if "time" in name_lower or "timezone" in name_lower:
            args: dict[str, Any] = {"timezone": "UTC"}
        elif "convert" in name_lower:
            args = {"time": "2025-01-01T00:00:00Z", "source_timezone": "UTC", "target_timezone": "Europe/London"}
        elif "echo" in name_lower:
            args = {"message": "scale-test"}
        else:
            args = {}

        try:
            with self.client.post(
                f"/servers/{_server_id}/mcp",
                data=json.dumps(_jsonrpc("tools/call", {"name": tool, "arguments": args})),
                headers=self._headers(),
                name="MCP tools/call",
                catch_response=True,
            ) as response:
                sid = response.headers.get("Mcp-Session-Id") if response.headers else None
                if sid:
                    self._mcp_session_id = sid

                if response.status_code == 429:
                    response.request_meta["name"] = "MCP tools/call [rate-limited]"
                    response.success()
                    return
                if response.status_code in (502, 503, 504):
                    response.request_meta["name"] = "MCP tools/call [infra-error]"
                    response.failure(f"Infrastructure error: {response.status_code}")
                    return
                if response.status_code != 200:
                    response.request_meta["name"] = "MCP tools/call [infra-error]"
                    response.failure(f"HTTP {response.status_code}")
                    return
                try:
                    data = response.json()
                except Exception:
                    response.request_meta["name"] = "MCP tools/call [infra-error]"
                    response.failure("Invalid JSON")
                    return
                if data is None:
                    response.request_meta["name"] = "MCP tools/call [infra-error]"
                    response.failure("Null response")
                    return
                if "error" in data:
                    err = data["error"]
                    err_msg = str(err.get("message", "")).lower()
                    err_data_str = str(err.get("data", "")).lower()
                    # Rate-limit violations may arrive as JSON-RPC errors when the
                    # PluginViolationError is caught by FastAPI's global handler.
                    if "rate" in err_msg or "rate_limit" in err_data_str or err.get("code") == 429:
                        response.request_meta["name"] = "MCP tools/call [rate-limited]"
                        response.success()
                        bucket = int((time.time() - _test_start_time) / 30)
                        with _stats_lock:
                            _bucket_stats[bucket]["blocked"] += 1
                        return
                    response.request_meta["name"] = "MCP tools/call [infra-error]"
                    response.failure(f"JSON-RPC error {err.get('code', '?')}: {err.get('message', '?')}")
                    return

                result = data.get("result")
                bucket = int((time.time() - _test_start_time) / 30)
                if isinstance(result, dict) and result.get("isError"):
                    response.request_meta["name"] = "MCP tools/call [rate-limited]"
                    response.success()
                    with _stats_lock:
                        _bucket_stats[bucket]["blocked"] += 1
                else:
                    response.request_meta["name"] = "MCP tools/call [allowed]"
                    response.success()
                    with _stats_lock:
                        _bucket_stats[bucket]["allowed"] += 1
        except Exception as exc:
            logger.warning("Request failed (tools/call): %s", exc)
