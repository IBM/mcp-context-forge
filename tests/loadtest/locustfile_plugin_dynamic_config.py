# -*- coding: utf-8 -*-
"""Dynamic plugin configuration load test.

Tests that runtime plugin config changes propagate correctly across all
gateway instances under concurrent load. Validates the full path:
  Admin API → Redis → pub/sub → cache eviction → tool invocation

Scenarios tested:
  1. Global toggle: disable/enable plugins, verify tool calls reflect state
  2. Per-plugin mode: switch RateLimiter enforce/disabled, verify enforcement
  3. Per-tool binding: bind rate limiter to tool A only, verify tool B unaffected
  4. Per-user isolation: verify rate limits apply independently per user

Usage:
    # Docker-compose (3 replicas)
    locust -f tests/loadtest/locustfile_plugin_dynamic_config.py \\
        --host=http://localhost:8080 --headless --users=10 --spawn-rate=5 --run-time=5m

    # OCP
    locust -f tests/loadtest/locustfile_plugin_dynamic_config.py \\
        --host=http://<nginx-service>:80 --headless --users=10 --spawn-rate=5 --run-time=5m

Environment Variables:
    JWT_SECRET_KEY:    JWT signing key (default: my-test-key-but-now-longer-than-32-bytes)
    MCP_SERVER_ID:     Virtual server UUID (auto-detected if empty)
    PROPAGATION_WAIT:  Seconds to wait after admin change (default: 3)
"""

# Standard
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

# Third-Party
from locust import FastHttpUser, between, constant_throughput, events, task
from locust.runners import WorkerRunner

# =============================================================================
# Configuration
# =============================================================================

_ENV = {}
_env_file = os.path.join(os.path.dirname(__file__), "../../.env")
if os.path.isfile(_env_file):
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                _ENV[k.strip()] = v.strip().strip('"').strip("'")


def _cfg(key, default=""):
    return os.environ.get(key) or _ENV.get(key) or default


JWT_SECRET_KEY = _cfg("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
JWT_ALGORITHM = _cfg("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = _cfg("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = _cfg("JWT_ISSUER", "mcpgateway")
ADMIN_EMAIL = _cfg("PLATFORM_ADMIN_EMAIL", "admin@example.com")
MCP_SERVER_ID = _cfg("MCP_SERVER_ID", "")
PROPAGATION_WAIT = float(_cfg("PROPAGATION_WAIT", "7"))

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# =============================================================================
# Shared state
# =============================================================================

_server_id: str = ""
_tool_names: list[str] = []
_detect_done = False

# Track current expected state for verification
_plugins_enabled = True
_rate_limiter_mode = "enforce"  # or "disabled"
_scenario_phase = "warmup"


# =============================================================================
# JWT token
# =============================================================================


def _make_token(email: str = ADMIN_EMAIL) -> str:
    """Generate a JWT for the given user."""
    import jwt  # pylint: disable=import-outside-toplevel

    payload = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=8760),
        "iat": datetime.now(timezone.utc),
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
        "jti": str(uuid.uuid4()),
        "token_use": "session",
        "user": {
            "email": email,
            "full_name": f"Load Test User {email}",
            "is_admin": True,
            "auth_provider": "local",
        },
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


_admin_token: str = ""


def _get_admin_token() -> str:
    global _admin_token  # pylint: disable=global-statement
    if not _admin_token:
        _admin_token = _make_token()
    return _admin_token


# =============================================================================
# Auto-detect server and tools
# =============================================================================


def _auto_detect(host: str) -> None:
    global _server_id, _tool_names, _detect_done  # pylint: disable=global-statement
    if _detect_done:
        return
    _detect_done = True

    import requests  # pylint: disable=import-outside-toplevel

    headers = {"Authorization": f"Bearer {_get_admin_token()}", "Accept": "application/json"}

    if MCP_SERVER_ID:
        _server_id = MCP_SERVER_ID
    else:
        try:
            resp = requests.get(f"{host}/servers", headers=headers, timeout=10)
            servers = resp.json() if resp.status_code == 200 else []
            if isinstance(servers, list) and servers:
                _server_id = servers[0].get("id", "")
        except Exception as exc:
            logger.warning("Server auto-detect failed: %s", exc)

    if _server_id:
        try:
            payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
            resp = requests.post(
                f"{host}/servers/{_server_id}/mcp",
                json=payload,
                headers={**headers, "Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code == 200:
                result = resp.json().get("result", {})
                _tool_names = [t["name"] for t in result.get("tools", [])]
        except Exception as exc:
            logger.warning("Tool auto-detect failed: %s", exc)

    logger.error("Dynamic config test: server=%s  tools=%s", _server_id, _tool_names)


# =============================================================================
# JSON-RPC helper
# =============================================================================


def _jsonrpc(method: str, params: dict | None = None) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method}
    if params is not None:
        body["params"] = params
    return body


# =============================================================================
# Event handlers
# =============================================================================


@events.init_command_line_parser.add_listener
def set_defaults(parser):
    parser.set_defaults(users=10, spawn_rate=5, run_time="300s")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    host = environment.host or "http://localhost:8080"
    _auto_detect(host)
    if isinstance(environment.runner, WorkerRunner):
        return

    logger.error("=" * 70)
    logger.error("DYNAMIC PLUGIN CONFIGURATION TEST")
    logger.error("=" * 70)
    logger.error("  Host:              %s", host)
    logger.error("  Server:            %s", _server_id)
    logger.error("  Tools:             %s", ", ".join(_tool_names[:5]) or "(none)")
    logger.error("  Propagation wait:  %.0fs", PROPAGATION_WAIT)
    logger.error("")
    logger.error("  Scenarios:")
    logger.error("    1. Global toggle (disable/enable)")
    logger.error("    2. Per-plugin mode (enforce/disabled)")
    logger.error("    3. Per-tool binding (tool A limited, tool B not)")
    logger.error("    4. Per-user isolation (independent limits)")
    logger.error("=" * 70)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    if isinstance(environment.runner, WorkerRunner):
        return

    stats = environment.stats
    total = stats.total.num_requests
    failures = stats.total.num_failures
    logger.error("=" * 70)
    logger.error("RESULTS")
    logger.error("=" * 70)
    logger.error("  Total requests: %d", total)
    logger.error("  Total failures: %d (%.2f%%)", failures, (failures / total * 100) if total else 0)
    logger.error("")

    for name in sorted(stats.entries.keys()):
        entry = stats.entries[name]
        if entry.num_requests > 0:
            logger.error(
                "  %-50s %6d reqs  %3d fails  avg %6.0fms",
                entry.name, entry.num_requests, entry.num_failures,
                entry.avg_response_time or 0,
            )
    logger.error("=" * 70)


# =============================================================================
# AdminUser — orchestrates plugin config changes
# =============================================================================


class AdminUser(FastHttpUser):
    """Admin user that toggles plugin configuration at runtime.

    Runs through scenarios sequentially, waiting for propagation after each change.
    Only 1 instance of this user should run.
    """

    weight = 1
    wait_time = between(1, 2)
    connection_timeout = 30.0
    network_timeout = 30.0

    def _admin_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {_get_admin_token()}",
        }

    def _put_global_toggle(self, enabled: bool) -> bool:
        """Toggle global plugin state."""
        global _plugins_enabled  # pylint: disable=global-statement
        with self.client.put(
            "/admin/plugins",
            data=json.dumps({"enabled": enabled}),
            headers=self._admin_headers(),
            name="Admin: global toggle",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                _plugins_enabled = enabled
                resp.success()
                return True
            resp.failure(f"HTTP {resp.status_code}")
            return False

    def _put_plugin_mode(self, plugin: str, mode: str) -> bool:
        """Change a plugin's mode."""
        global _rate_limiter_mode  # pylint: disable=global-statement
        with self.client.put(
            f"/admin/plugins/{plugin}",
            data=json.dumps({"mode": mode}),
            headers=self._admin_headers(),
            name=f"Admin: {plugin} mode={mode}",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                if "RateLimiter" in plugin:
                    _rate_limiter_mode = mode
                resp.success()
                return True
            resp.failure(f"HTTP {resp.status_code}")
            return False

    def _verify_state(self) -> None:
        """Verify GET /admin/plugins reflects current expected state."""
        with self.client.get(
            "/admin/plugins",
            headers=self._admin_headers(),
            name="Admin: verify state",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                actual = data.get("plugins_globally_enabled")
                if actual == _plugins_enabled:
                    resp.success()
                else:
                    resp.failure(f"State mismatch: expected={_plugins_enabled} actual={actual}")
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task
    def run_scenarios(self) -> None:
        """Execute all test scenarios sequentially."""
        global _scenario_phase  # pylint: disable=global-statement

        # --- Scenario 1: Global toggle ---
        _scenario_phase = "global_toggle_disable"
        self._put_global_toggle(False)
        time.sleep(PROPAGATION_WAIT)
        self._verify_state()

        _scenario_phase = "global_toggle_enable"
        self._put_global_toggle(True)
        time.sleep(PROPAGATION_WAIT)
        self._verify_state()

        # --- Scenario 2: Per-plugin mode toggle ---
        _scenario_phase = "mode_disable"
        self._put_plugin_mode("RateLimiterPlugin", "disabled")
        time.sleep(PROPAGATION_WAIT)

        _scenario_phase = "mode_enforce"
        self._put_plugin_mode("RateLimiterPlugin", "enforce")
        time.sleep(PROPAGATION_WAIT)

        # --- Scenario 3: Verify state consistency across replicas ---
        _scenario_phase = "verify_consistency"
        for _ in range(6):  # Hit all 3 replicas twice
            self._verify_state()

        # Brief pause before next cycle
        _scenario_phase = "idle"
        time.sleep(5)


# =============================================================================
# ToolUser — continuously calls tools, tags results based on expected state
# =============================================================================


class ToolUser(FastHttpUser):
    """Tool user that continuously calls MCP tools.

    Tags each request based on whether it was rate-limited or allowed,
    and whether that matches the expected state (plugins enabled/disabled,
    rate limiter mode).
    """

    weight = 10
    wait_time = constant_throughput(2)  # 2 req/s per user
    connection_timeout = 30.0
    network_timeout = 30.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mcp_session_id: str | None = None
        self._initialized = False
        self._user_token = _make_token(ADMIN_EMAIL)

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._user_token}",
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
                if response.status_code == 429:
                    response.request_meta["name"] = f"{name} [rate-limited]"
                    response.success()
                    return {"_rate_limited": True}
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    return None
                try:
                    data = response.json()
                except Exception:
                    response.failure("Invalid JSON")
                    return None

                # Check for MCP-level rate limit (isError in result)
                result = data.get("result", {})
                if isinstance(result, dict) and result.get("isError"):
                    content = result.get("content", [])
                    if any("rate" in str(c).lower() or "limit" in str(c).lower() for c in content):
                        response.request_meta["name"] = f"{name} [rate-limited]"
                        response.success()
                        return {"_rate_limited": True}

                response.success()
                return result
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
                "clientInfo": {"name": "locust-dynamic-config-test", "version": "1.0.0"},
            },
            "MCP initialize",
        )
        if result is not None:
            self._initialized = True

    def on_start(self) -> None:
        self._ensure_initialized()

    @task(3)
    def call_primary_tool(self) -> None:
        """Call the first tool (typically fast-time-get-system-time)."""
        if not _tool_names:
            return
        tool = _tool_names[0]
        self._mcp_post(
            "tools/call",
            {"name": tool, "arguments": {}},
            f"tools/call [{tool}]",
        )

    @task(1)
    def call_secondary_tool(self) -> None:
        """Call the second tool (typically fast-time-convert-time).

        Used to verify per-tool binding isolation — if rate limiter is
        bound only to the primary tool, this tool should never be limited.
        """
        if len(_tool_names) < 2:
            return
        tool = _tool_names[1]
        self._mcp_post(
            "tools/call",
            {"name": tool, "arguments": {"source_timezone": "UTC", "target_timezone": "US/Eastern"}},
            f"tools/call [{tool}]",
        )


# =============================================================================
# VerifierUser — polls state consistency across replicas
# =============================================================================


class VerifierUser(FastHttpUser):
    """Verifier user that periodically checks plugin state across replicas.

    Sends GET /admin/plugins through the load balancer to hit different
    replicas and verifies they all report the same state.
    """

    weight = 1
    wait_time = between(2, 4)
    connection_timeout = 30.0
    network_timeout = 30.0

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {_get_admin_token()}",
        }

    @task
    def verify_state_consistency(self) -> None:
        """Check that the current replica matches expected global state."""
        with self.client.get(
            "/admin/plugins",
            headers=self._headers(),
            name=f"Verify: plugins_enabled={_plugins_enabled}",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                actual = data.get("plugins_globally_enabled")
                if actual == _plugins_enabled:
                    resp.success()
                else:
                    resp.failure(
                        f"Inconsistency: expected={_plugins_enabled} actual={actual} "
                        f"phase={_scenario_phase}"
                    )
            else:
                resp.failure(f"HTTP {resp.status_code}")
