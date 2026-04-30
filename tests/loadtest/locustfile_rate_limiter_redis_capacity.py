# -*- coding: utf-8 -*-
"""Location: ./tests/loadtest/locustfile_rate_limiter_redis_capacity.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Rate limiter Redis capacity test on the prompt pre-fetch path.
This benchmark is intentionally narrower than the existing tools/call scale test.
It exercises:
  client -> nginx -> 3 gateways -> auth -> prompt_pre_fetch -> Redis rate limiter -> prompt render
It avoids downstream MCP tool invocation so the measurement stays focused on the
Redis-backed rate limiter path. The benchmark is intended to answer:
  "How many concurrent users can the async Redis hot path sustain at a given pace
   while preserving correct shared-counter behavior?"
Usage:
    docker exec mcp-context-forge-redis-1 redis-cli FLUSHDB
    make benchmark-rate-limiter-redis-capacity
Environment Variables:
    RL_USERS:               Concurrent users (default: 100)
    RL_SPAWN_RATE:          User spawn rate (default: 10)
    RL_RUN_TIME:            Run duration (default: 120s)
    RL_REQS_PER_SECOND:     Per-user request pace (default: 0.25)
    RL_LIMIT_PER_MIN:       Configured limit for the output banner only (default: 30)
    RL_PROMPT_ID:           Optional prompt UUID to target (auto-detected if empty)
    JWT_SECRET_KEY:         JWT signing secret (default: my-test-key)
    JWT_ALGORITHM:          JWT algorithm (default: HS256)
    JWT_AUDIENCE:           JWT audience (default: mcpgateway-api)
    JWT_ISSUER:             JWT issuer (default: mcpgateway)
    DOCKER_GATEWAY_PATTERN: Gateway container pattern (default: mcp-context-forge-gateway)
    DOCKER_REDIS_CONTAINER: Redis container name (default: mcp-context-forge-redis-1)
"""

# Standard
from dataclasses import dataclass
from datetime import timedelta
import logging
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import uuid

# Third-Party
from locust import constant_throughput, events, tag, task
from locust.contrib.fasthttp import FastHttpUser
from locust.runners import WorkerRunner


def _load_env_file() -> dict[str, str]:
    """Load .env values from the repository root."""
    env_vars: dict[str, str] = {}
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ]
    for path in search_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
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
JWT_ALGORITHM = _cfg("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = _cfg("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = _cfg("JWT_ISSUER", "mcpgateway")

RL_USERS = int(_cfg("RL_USERS", "100"))
RL_SPAWN_RATE = int(_cfg("RL_SPAWN_RATE", "10"))
RL_RUN_TIME = _cfg("RL_RUN_TIME", "120s")
RL_REQS_PER_SECOND = float(_cfg("RL_REQS_PER_SECOND", "0.25"))
RL_LIMIT_PER_MIN = int(_cfg("RL_LIMIT_PER_MIN", "30"))
RL_PROMPT_ID = _cfg("RL_PROMPT_ID", "")
RL_FORCE_PYTHON = _cfg("RATE_LIMITER_FORCE_PYTHON", "").strip().lower() in ("1", "true", "yes")

DOCKER_GATEWAY_PATTERN = _cfg("DOCKER_GATEWAY_PATTERN", "mcp-context-forge-gateway")
DOCKER_REDIS_CONTAINER = _cfg("DOCKER_REDIS_CONTAINER", "mcp-context-forge-redis-1")

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromptTarget:
    """Benchmark prompt target with default argument values."""

    prompt_id: str
    name: str
    required_arguments: dict[str, str]


_prompt_target: PromptTarget | None = None
_detect_done = False
_user_counter = 0
_user_counter_lock = threading.Lock()
_user_tokens: list[str] = []
_registered_state: dict[str, object] = {}
_valid_users = 0
_created_prompt_id: str | None = None

_stats_file = None
_stats_proc = None
_stats_path = ""

_TEST_PASSWORD = "CapacityTest123!"  # pragma: allowlist secret
_USER_PREFIX = "rl-capacity"


def _default_prompt_argument_value(prompt_name: str, argument_name: str) -> str:
    """Return a deterministic low-cost argument value for benchmark prompts."""
    name = argument_name.lower()
    prompt = prompt_name.lower()

    if "timezones" in name:
        return "UTC,Europe/Dublin"
    if "secondary_timezone" in name or "timezone_b" in name:
        return "Europe/Dublin"
    if "primary_timezone" in name or "source_timezone" in name or "timezone_a" in name:
        return "UTC"
    if "timezone" in name:
        return "UTC"
    if "date" in name or "time" in name:
        return "2025-01-15T12:00:00Z"
    if "email" in name:
        return "capacity@example.com"
    if "location" in name or "city" in name:
        return "Dublin"
    if "include_" in name or name.startswith("with_") or name.endswith("_enabled"):
        return "true"
    if "name" in name or "title" in name or "subject" in name or "message" in name:
        return "capacity-test"
    if "compare" in prompt:
        return "UTC"
    return "capacity-test"


def _make_token(email: str) -> str:
    """Generate a rich admin token with explicit teams=null for admin bypass."""
    # First-Party
    from mcpgateway.utils.create_jwt_token import _create_jwt_token  # pylint: disable=import-outside-toplevel

    return _create_jwt_token(
        {"sub": email},
        expires_in_minutes=int(timedelta(hours=24).total_seconds() // 60),
        secret=JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
        user_data={
            "email": email,
            "full_name": "Rate Limiter Capacity Benchmark",
            "is_admin": True,
            "auth_provider": "local",
        },
        teams=None,
    )


def _admin_jwt() -> str:
    """Create a short-lived admin JWT for discovery and user bootstrap."""
    admin_email = _cfg("PLATFORM_ADMIN_EMAIL", "admin@example.com")
    return _make_token(admin_email)


def _admin_session(host: str):
    """Build a requests session pinned to the admin token."""
    # Third-Party
    import requests  # pylint: disable=import-outside-toplevel

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {_admin_jwt()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )
    session.base_url = host  # type: ignore[attr-defined]
    return session


def _extract_prompt_list(payload) -> list[dict]:
    """Normalize list responses across plain and paginated prompt payloads."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "prompts", "results"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _pick_prompt(prompts: list[dict]) -> PromptTarget | None:
    """Select the cheapest local prompt: local template, few args, short template."""
    candidates: list[tuple[tuple[int, int, str], PromptTarget]] = []
    for prompt in prompts:
        prompt_id = str(prompt.get("id") or "").strip()
        name = str(prompt.get("name") or prompt.get("custom_name") or "").strip()
        template = str(prompt.get("template") or "")
        enabled = prompt.get("enabled", True)
        if not prompt_id or not name or not enabled or not template:
            continue

        required_arguments: dict[str, str] = {}
        for argument in prompt.get("arguments", []) or []:
            if not isinstance(argument, dict):
                continue
            arg_name = str(argument.get("name") or "").strip()
            if argument.get("required") and arg_name:
                required_arguments[arg_name] = _default_prompt_argument_value(name, arg_name)

        target = PromptTarget(prompt_id=prompt_id, name=name, required_arguments=required_arguments)
        sort_key = (len(required_arguments), len(template), name)
        candidates.append((sort_key, target))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _create_benchmark_prompt(host: str):
    """Create a tiny temporary local prompt when none exists."""
    global _created_prompt_id  # pylint: disable=global-statement
    admin = _admin_session(host)
    name = f"rl-capacity-benchmark-{uuid.uuid4().hex[:8]}"
    response = admin.post(
        f"{host}/prompts",
        json={
            "prompt": {
                "name": name,
                "custom_name": name,
                "display_name": name,
                "description": "Temporary prompt for Redis capacity benchmarking",
                "template": "rate limiter capacity benchmark",
                "arguments": [],
                "tags": ["benchmark", "rate-limiter"],
            },
            "visibility": "public",
        },
        timeout=10,
    )
    response.raise_for_status()
    prompt = response.json()
    _created_prompt_id = str(prompt.get("id") or "")
    return PromptTarget(prompt_id=_created_prompt_id, name=str(prompt.get("name") or name), required_arguments={})


def _auto_detect(host: str) -> None:
    """Resolve the benchmark prompt once per process."""
    global _prompt_target, _detect_done  # pylint: disable=global-statement
    if _detect_done:
        return
    _detect_done = True

    admin = _admin_session(host)
    headers = dict(admin.headers)

    if RL_PROMPT_ID:
        response = admin.get(f"{host}/prompts/{RL_PROMPT_ID}", headers=headers, timeout=10)
        response.raise_for_status()
        prompt = response.json()
        required_arguments: dict[str, str] = {}
        name = str(prompt.get("name") or RL_PROMPT_ID)
        for argument in prompt.get("arguments", []) or []:
            if not isinstance(argument, dict):
                continue
            arg_name = str(argument.get("name") or "").strip()
            if argument.get("required") and arg_name:
                required_arguments[arg_name] = _default_prompt_argument_value(name, arg_name)
        _prompt_target = PromptTarget(prompt_id=str(prompt.get("id") or RL_PROMPT_ID), name=name, required_arguments=required_arguments)
        return

    response = admin.get(f"{host}/prompts", headers=headers, timeout=10)
    response.raise_for_status()
    prompt = _pick_prompt(_extract_prompt_list(response.json()))
    if prompt is None:
        prompt = _create_benchmark_prompt(host)
    _prompt_target = prompt


def _bootstrap_users(host: str) -> None:
    """Register benchmark users and pre-build one token per unique identity."""
    global _user_tokens, _registered_state, _valid_users  # pylint: disable=global-statement
    admin = _admin_session(host)

    registered: list[dict[str, str]] = []
    tokens: list[str] = []
    run_id = uuid.uuid4().hex[:6]

    for index in range(RL_USERS):
        email = f"{_USER_PREFIX}-{run_id}-{index:04d}@loadtest.internal"
        try:
            response = admin.post(
                f"{host}/auth/email/admin/users",
                json={
                    "email": email,
                    "password": _TEST_PASSWORD,
                    "full_name": f"Rate Limit Capacity User {index:04d}",
                    "is_admin": True,
                    "is_active": True,
                    "password_change_required": False,
                },
                timeout=10,
            )
            if response.status_code not in (200, 201):
                logger.warning("User registration failed for %s: %s %s", email, response.status_code, response.text[:200])
                tokens.append("")
                registered.append({"email": email})
                continue

            tokens.append(_make_token(email))
            registered.append({"email": email})
        except Exception as exc:
            logger.warning("User bootstrap failed for %s: %s", email, exc)
            tokens.append("")
            registered.append({"email": email})

    _user_tokens = tokens
    _registered_state = {"host": host, "users": registered}
    _valid_users = sum(1 for token in tokens if token)


def _cleanup_users() -> None:
    """Delete any benchmark users created during bootstrap."""
    if not _registered_state:
        return

    host = str(_registered_state.get("host") or "")
    users = _registered_state.get("users") or []
    if not host or not isinstance(users, list):
        return

    admin = _admin_session(host)
    for user in users:
        if not isinstance(user, dict):
            continue
        email = user.get("email")
        if not isinstance(email, str) or not email:
            continue
        try:
            admin.delete(f"{host}/auth/email/admin/users/{email}", timeout=10)
        except Exception as exc:
            logger.warning("Cleanup failed for %s: %s", email, exc)


def _cleanup_prompt(host: str) -> None:
    """Delete the temporary benchmark prompt when one was created."""
    if not _created_prompt_id:
        return
    admin = _admin_session(host)
    try:
        admin.delete(f"{host}/prompts/{_created_prompt_id}", timeout=10)
    except Exception as exc:
        logger.warning("Prompt cleanup failed for %s: %s", _created_prompt_id, exc)


def _mem_to_mib(raw: str) -> float:
    """Convert docker stats memory values to MiB."""
    raw = raw.strip()
    match = re.match(r"([\d.]+)\s*([KMGTkmgt]i?[Bb]?)", raw)
    if not match:
        return 0.0
    value, unit = float(match.group(1)), match.group(2).upper()
    if unit.startswith("K"):
        return value / 1024
    if unit.startswith("M"):
        return value
    if unit.startswith("G"):
        return value * 1024
    if unit.startswith("T"):
        return value * 1024 * 1024
    return value


def _parse_stats_file(path: str) -> dict[str, dict[str, float]]:
    """Parse docker stats output into avg/peak CPU and memory samples."""
    ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\[[?][0-9;]*[A-Za-z]")
    samples: dict[str, list[tuple[float, float]]] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = ansi.sub("", line).strip()
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                name = parts[0].strip()
                if not name:
                    continue
                mem = _mem_to_mib(parts[1].split("/")[0].strip())
                try:
                    cpu = float(parts[2].replace("%", "").strip())
                except ValueError:
                    continue
                if mem <= 0:
                    continue
                samples.setdefault(name, []).append((mem, cpu))
    except FileNotFoundError:
        return {}

    parsed: dict[str, dict[str, float]] = {}
    for name, points in samples.items():
        mems = [point[0] for point in points]
        cpus = [point[1] for point in points]
        parsed[name] = {
            "mem_avg": sum(mems) / len(mems),
            "mem_peak": max(mems),
            "cpu_avg": sum(cpus) / len(cpus),
            "cpu_peak": max(cpus),
            "samples": float(len(points)),
        }
    return parsed


def _start_stats_monitor() -> None:
    """Start a docker stats subprocess for gateway/Redis resource sampling."""
    global _stats_file, _stats_proc, _stats_path  # pylint: disable=global-statement
    try:
        fd, _stats_path = tempfile.mkstemp(prefix="rl_capacity_stats_", suffix=".tsv")
        _stats_file = os.fdopen(fd, "w")
        _stats_proc = subprocess.Popen(
            ["docker", "stats", "--format", "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}"],
            stdout=_stats_file,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # pragma: no cover - best effort benchmark instrumentation
        logger.error("docker stats monitor failed to start: %s", exc)


def _stop_stats_monitor() -> dict[str, dict[str, float]]:
    """Stop docker stats and return parsed samples."""
    global _stats_proc, _stats_file  # pylint: disable=global-statement
    if _stats_proc:
        try:
            _stats_proc.terminate()
            _stats_proc.wait(timeout=5)
        except Exception:  # pragma: no cover - best effort benchmark instrumentation
            pass
        _stats_proc = None
    if _stats_file:
        try:
            _stats_file.flush()
            _stats_file.close()
        except Exception:  # pragma: no cover - best effort benchmark instrumentation
            pass
        _stats_file = None
    return _parse_stats_file(_stats_path) if _stats_path else {}


@events.init_command_line_parser.add_listener
def set_defaults(parser):
    """Match Makefile defaults when invoked directly."""
    parser.set_defaults(users=RL_USERS, spawn_rate=RL_SPAWN_RATE, run_time=RL_RUN_TIME)


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Resolve prompt target and print a short benchmark banner."""
    del kwargs
    host = environment.host or "http://localhost:8080"
    _auto_detect(host)
    _bootstrap_users(host)
    _start_stats_monitor()
    if isinstance(environment.runner, WorkerRunner):
        return

    engine_label = "Python (RATE_LIMITER_FORCE_PYTHON=1)" if RL_FORCE_PYTHON else "Rust (default)"

    print("\n" + "=" * 90)
    print("RATE LIMITER REDIS CAPACITY TEST")
    print("=" * 90)
    print(f"  Host:              {host}")
    print("  Topology:          nginx -> 3 gateways -> shared Redis")
    print("  Path:              REST /prompts/{id}  (prompt_pre_fetch)")
    print(f"  Engine:            {engine_label}")
    print(f"  Prompt:            {(_prompt_target.name if _prompt_target else '(none)')} [{(_prompt_target.prompt_id if _prompt_target else '')}]")
    print(f"  Required args:     {len(_prompt_target.required_arguments) if _prompt_target else 0}")
    print(f"  Valid users:       {_valid_users}/{RL_USERS}")
    print(f"  Users:             {RL_USERS}")
    print(f"  Spawn rate:        {RL_SPAWN_RATE}/s")
    print(f"  Per-user pace:     {RL_REQS_PER_SECOND:.2f} req/s ({RL_REQS_PER_SECOND * 60:.0f} req/min)")
    print(f"  Banner limit:      {RL_LIMIT_PER_MIN}/min per user")
    print(f"  Duration:          {RL_RUN_TIME}")
    print("=" * 90)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print semantic request counts plus sampled gateway/Redis resource usage."""
    del kwargs
    host = environment.host or "http://localhost:8080"
    resource_data = _stop_stats_monitor()
    _cleanup_users()
    _cleanup_prompt(host)
    if isinstance(environment.runner, WorkerRunner):
        return

    stats = environment.stats
    total_http = stats.total.num_requests
    infra_fails = stats.total.num_failures

    allowed_entry = stats.entries.get(("Prompt execute [allowed]", "POST"))
    blocked_entry = stats.entries.get(("Prompt execute [rate-limited]", "POST"))
    allowed_count = allowed_entry.num_requests if allowed_entry else 0
    blocked_count = blocked_entry.num_requests if blocked_entry else 0
    semantic_total = allowed_count + blocked_count
    blocked_pct = (blocked_count / semantic_total * 100) if semantic_total else 0.0

    engine_label = "Python (RATE_LIMITER_FORCE_PYTHON=1)" if RL_FORCE_PYTHON else "Rust (default)"

    print("\n" + "=" * 90)
    print("RATE LIMITER REDIS CAPACITY RESULTS")
    print("=" * 90)
    print(f"  Engine:                    {engine_label}")
    print(f"  Prompt target:             {(_prompt_target.name if _prompt_target else '(none)')}")
    print(f"  HTTP requests observed:    {total_http:>10,}")
    print(f"  Semantic prompt calls:     {semantic_total:>10,}")
    print(f"  Allowed responses:         {allowed_count:>10,}")
    print(f"  Rate-limited responses:    {blocked_count:>10,}  ({blocked_pct:.1f}%)")
    print(f"  Infrastructure failures:   {infra_fails:>10,}")
    print(f"  Throughput (req/s):        {stats.total.total_rps:>10.2f}")
    if total_http > 0:
        print("\n  Response Times (ms):")
        print(f"    Average: {stats.total.avg_response_time:>10.1f}")
        print(f"    p50:     {stats.total.get_response_time_percentile(0.50):>10.1f}")
        print(f"    p95:     {stats.total.get_response_time_percentile(0.95):>10.1f}")
        print(f"    p99:     {stats.total.get_response_time_percentile(0.99):>10.1f}")

    if resource_data:
        gateways = sorted([(name, data) for name, data in resource_data.items() if DOCKER_GATEWAY_PATTERN in name], key=lambda item: item[0])
        redis_rows = [(name, data) for name, data in resource_data.items() if name == DOCKER_REDIS_CONTAINER or name.endswith("/redis-1") or "redis" in name.lower()]
        if gateways or redis_rows:
            print(f"\n  {'CONTAINER RESOURCE USAGE':^86}")
            print("  " + "-" * 86)
            print(f"  {'Container':<36} {'Mem avg':>9} {'Mem peak':>9} {'CPU avg':>8} {'CPU peak':>9} {'Samples':>7}")
            print("  " + "-" * 86)
            total_mem_avg = 0.0
            total_mem_peak = 0.0
            for name, data in gateways + redis_rows:
                short = name.replace("mcp-context-forge-", "")
                print(f"  {short:<36} {data['mem_avg']:>7.1f}M {data['mem_peak']:>7.1f}M " f"{data['cpu_avg']:>7.1f}% {data['cpu_peak']:>8.1f}% {int(data['samples']):>7}")
                if DOCKER_GATEWAY_PATTERN in name:
                    total_mem_avg += data["mem_avg"]
                    total_mem_peak += data["mem_peak"]
            if len(gateways) > 1:
                print("  " + "-" * 86)
                print(f"  {'All gateways combined':<36} {total_mem_avg:>7.1f}M {total_mem_peak:>7.1f}M")

    print("\n" + "=" * 90 + "\n")


class CapacityPromptUser(FastHttpUser):
    """Concurrent prompt caller with a unique JWT identity per Locust user."""

    wait_time = constant_throughput(RL_REQS_PER_SECOND)
    connection_timeout = 30.0
    network_timeout = 30.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        global _user_counter  # pylint: disable=global-statement
        with _user_counter_lock:
            user_id = _user_counter
            _user_counter += 1
        self._token = _user_tokens[user_id % len(_user_tokens)] if _user_tokens else ""

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

    @task
    @tag("rate-limit", "redis", "capacity", "prompts")
    def execute_prompt(self) -> None:
        """Execute the chosen prompt and classify the response semantically."""
        if _prompt_target is None:
            return

        try:
            with self.client.post(
                f"/prompts/{_prompt_target.prompt_id}",
                json=_prompt_target.required_arguments,
                headers=self._headers(),
                name="Prompt execute",
                catch_response=True,
            ) as response:
                if response.status_code == 200:
                    response.request_meta["name"] = "Prompt execute [allowed]"
                    response.success()
                    return

                body_text = ""
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        body_text = str(payload.get("message") or payload.get("details") or payload)
                    else:
                        body_text = str(payload)
                except Exception:
                    body_text = response.text or ""

                if response.status_code == 429:
                    response.request_meta["name"] = "Prompt execute [rate-limited]"
                    response.success()
                    return
                body_lower = body_text.lower()
                if response.status_code in (422, 403) and ("rate" in body_lower or "rate_limit" in body_lower):
                    response.request_meta["name"] = "Prompt execute [rate-limited]"
                    response.success()
                    return

                response.request_meta["name"] = "Prompt execute [infra-error]"
                response.failure(f"HTTP {response.status_code}: {body_text[:160]}")
        except Exception as exc:
            logger.warning("Prompt execute request failed: %s", exc)
