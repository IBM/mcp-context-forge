# -*- coding: utf-8 -*-
"""MCP Streamable HTTP protocol load test — pure MCP protocol RPS measurement.

This locustfile tests ONLY the MCP Streamable HTTP transport path through the
gateway virtual server endpoint: /servers/{server_id}/mcp

It exists to isolate MCP protocol overhead from REST API / admin UI / other
endpoints so we can get a clean RPS number for just the MCP path.

Test scenarios (selectable via --class-picker):
  MCPAgentUser        (weight 10) - Realistic agent: init once, then call 6 tools
  MCPToolCallerUser   (weight  5) - Heavy tool caller: tools/call in a tight loop
  MCPDiscoveryUser    (weight  3) - Discovery heavy: tools/list, resources/list, prompts/list
  MCPSessionChurnUser (weight  2) - Session churn: new session per request cycle
  MCPStressUser       (weight  1) - Max-throughput: constant_throughput, minimal overhead

Usage:
    # Quick headless (150 users, 2 min)
    make load-test-mcp-protocol

    # Web UI with class picker
    make load-test-mcp-protocol-ui

    # High-load (500 users, 5 min)
    make load-test-mcp-protocol-heavy

    # Direct invocation
    locust -f tests/loadtest/locustfile_mcp_protocol.py \
        --host=http://localhost:4444 --users=150 --spawn-rate=30 --run-time=120s --headless

Environment Variables:
    LOADTEST_HOST:             Gateway URL           (default: http://localhost:4444)
    MCP_SERVER_ID:             Virtual server UUID   (auto-detected from /servers if empty)
    MCP_TOOL_NAMES:            Comma-sep tool names  (auto-detected from tools/list if empty)
    JWT_SECRET_KEY:            JWT signing secret     (default: my-test-key)
    JWT_ALGORITHM:             JWT algorithm          (default: HS256)
    JWT_AUDIENCE:              JWT audience           (default: mcpgateway-api)
    JWT_ISSUER:                JWT issuer             (default: mcpgateway)
    PLATFORM_ADMIN_EMAIL:      Admin email            (default: admin@example.com)
    MCPGATEWAY_BEARER_TOKEN:   Pre-generated token    (optional, overrides JWT generation)

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import random
from typing import Any
import uuid
import warnings

# Third-Party
from locust import between, constant_throughput, events, tag, task
from locust.contrib.fasthttp import FastHttpUser
from locust.runners import MasterRunner, WorkerRunner

# =============================================================================
# Configuration
# =============================================================================


def _load_env_file() -> dict[str, str]:
    """Load .env file from project root."""
    env_vars: dict[str, str] = {}
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ]
    for path in search_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
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


# JWT / Auth
JWT_SECRET_KEY = _cfg("JWT_SECRET_KEY", "my-test-key")
JWT_ALGORITHM = _cfg("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = _cfg("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = _cfg("JWT_ISSUER", "mcpgateway")
JWT_USERNAME = _cfg("PLATFORM_ADMIN_EMAIL", "admin@example.com")
BEARER_TOKEN = _cfg("MCPGATEWAY_BEARER_TOKEN", "")

# MCP target
MCP_SERVER_ID = _cfg("MCP_SERVER_ID", "")
MCP_SERVER_IDS_STR = _cfg("MCP_SERVER_IDS", "")
MCP_TOOL_NAMES_STR = _cfg("MCP_TOOL_NAMES", "")
LOCUST_LOG_LEVEL = os.environ.get("LOCUST_LOG_LEVEL", _ENV.get("LOCUST_LOG_LEVEL", "INFO")).upper()

logging.basicConfig(level=getattr(logging, LOCUST_LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, LOCUST_LOG_LEVEL, logging.INFO))


def _configure_log_levels() -> None:
    """Reduce benchmark log noise across Locust and common client libraries."""
    level = getattr(logging, LOCUST_LOG_LEVEL, logging.INFO)
    logger.setLevel(level)
    for logger_name in (
        "locust",
        "locust.main",
        "locust.runners",
        "locust.stats_logger",
        "urllib3",
        "requests",
        "gevent",
    ):
        logging.getLogger(logger_name).setLevel(level)
    if level >= logging.ERROR:
        warnings.filterwarnings(
            "ignore",
            message=r"The HMAC key is .* below the minimum recommended length of 32 bytes for SHA256\.",
        )


@dataclass(frozen=True)
class ServerTarget:
    server_id: str
    server_name: str
    tool_names: list[str]
    resource_uris: list[str]
    prompt_targets: list["PromptTarget"]


@dataclass(frozen=True)
class PromptTarget:
    name: str
    required_arguments: dict[str, str]

# Shared state (populated on test_start)
_server_id: str = ""
_tool_names: list[str] = []
_resource_uris: list[str] = []
_prompt_targets: list[PromptTarget] = []
_server_targets: list[ServerTarget] = []
_jwt_token: str | None = None
_server_target_index = 0

# Timezones for realistic args
TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Paris",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Australia/Sydney",
    "America/Chicago",
    "Europe/Dublin",
    "Europe/Berlin",
    "Asia/Singapore",
]


def _default_prompt_argument_value(prompt_name: str, argument_name: str) -> str:
    """Return a deterministic benchmark-friendly value for a required prompt arg."""
    name = argument_name.lower()
    prompt = prompt_name.lower()

    if "timezones" in name:
        return "America/New_York,Europe/Dublin"
    if "timezone_b" in name or "secondary_timezone" in name:
        return "America/New_York"
    if "timezone_a" in name or "primary_timezone" in name or "from_timezone" in name or "source_timezone" in name:
        return "UTC"
    if "target_timezone" in name or (name == "timezone" and "compare" not in prompt):
        return "Europe/Dublin"
    if "timezone" in name:
        return "UTC"
    if "include_" in name or name.startswith("with_") or name.endswith("_enabled") or name.endswith("_flag"):
        return "true"
    if "duration" in name:
        return "30"
    if "time" in name or "date" in name:
        return "2025-01-15T12:00:00Z"
    if "location" in name or "city" in name:
        return "Dublin"
    if "email" in name:
        return "loadtest@example.com"
    if "name" in name or "title" in name or "subject" in name:
        return "load-test"
    return "load-test"


# =============================================================================
# JWT Token Generation
# =============================================================================


def _generate_jwt_token() -> str:
    """Generate a JWT token matching gateway expectations."""
    try:
        # Third-Party
        import jwt  # pylint: disable=import-outside-toplevel

        jti = str(uuid.uuid4())
        payload = {
            "sub": JWT_USERNAME,
            "exp": datetime.now(timezone.utc) + timedelta(hours=8760),
            "iat": datetime.now(timezone.utc),
            "aud": JWT_AUDIENCE,
            "iss": JWT_ISSUER,
            "jti": jti,
            "token_use": "session",
            "user": {
                "email": JWT_USERNAME,
                "full_name": "MCP Protocol Load Test",
                "is_admin": True,
                "auth_provider": "local",
            },
        }
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        logger.info("Generated JWT for %s (jti=%s...)", JWT_USERNAME, jti[:8])
        return token
    except Exception as e:
        logger.warning("JWT generation failed: %s", e)
        return ""


def _get_token() -> str:
    global _jwt_token  # pylint: disable=global-statement
    if BEARER_TOKEN:
        return BEARER_TOKEN
    if _jwt_token is None:
        _jwt_token = _generate_jwt_token()
    return _jwt_token


# =============================================================================
# Auto-Detection: Server ID, Tool Names
# =============================================================================


def _auto_detect(host: str) -> None:
    """Discover MCP server targets and per-target inventories from the gateway REST API."""
    global _server_id, _tool_names, _resource_uris, _prompt_targets, _server_targets  # pylint: disable=global-statement

    # Third-Party
    import requests  # pylint: disable=import-outside-toplevel

    token = _get_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    requested_server_ids = [server_id.strip() for server_id in MCP_SERVER_IDS_STR.split(",") if server_id.strip()]

    # --- Server ID selection (prefer explicit multi-server list, then single server, else best auto-detect) ---
    if MCP_SERVER_ID:
        requested_server_ids = [MCP_SERVER_ID]

    if not requested_server_ids:
        try:
            resp = requests.get(f"{host}/servers", headers=headers, timeout=10)
            resp.raise_for_status()
            servers = resp.json()
            if isinstance(servers, dict):
                servers = servers.get("items", servers.get("servers", []))
            if isinstance(servers, list) and servers:
                # Pick enabled server with the most tools
                enabled = [s for s in servers if s.get("enabled", True)]
                if enabled:
                    best = max(enabled, key=lambda s: len(s.get("associatedTools", [])))
                    requested_server_ids = [best.get("id", "")]
                else:
                    requested_server_ids = [servers[0].get("id", "")]
        except Exception as e:
            logger.warning("Failed to auto-detect server_id: %s", e)

    requested_server_ids = [server_id for server_id in requested_server_ids if server_id]
    if not requested_server_ids:
        logger.error("No MCP_SERVER_ID/MCP_SERVER_IDS set and auto-detection failed.")
        return

    discovered_targets: list[ServerTarget] = []

    for server_id in requested_server_ids:
        mcp_url = f"{host}/servers/{server_id}/mcp"
        mcp_headers = {**headers, "Content-Type": "application/json"}
        session_id = None
        server_name = server_id

        def _mcp_call(method: str, params: dict | None = None) -> dict | None:
            nonlocal session_id
            payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method}
            if params:
                payload["params"] = params
            hdrs = dict(mcp_headers)
            if session_id:
                hdrs["Mcp-Session-Id"] = session_id
            try:
                resp = requests.post(mcp_url, json=payload, headers=hdrs, timeout=15)
                if "Mcp-Session-Id" in resp.headers:
                    session_id = resp.headers["Mcp-Session-Id"]
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    logger.warning("MCP error for server %s method %s: %s", server_id, method, data["error"])
                    return None
                return data.get("result")
            except Exception as e:
                logger.warning("MCP %s failed for server %s: %s", method, server_id, e)
                return None

        init_result = _mcp_call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "locust-mcp-discovery", "version": "1.0"},
            },
        )
        if init_result:
            server_name = init_result.get("serverInfo", {}).get("name") or server_name

        if MCP_TOOL_NAMES_STR:
            tool_names = [t.strip() for t in MCP_TOOL_NAMES_STR.split(",") if t.strip()]
        else:
            result = _mcp_call("tools/list")
            tool_names = [t["name"] for t in result.get("tools", []) if "name" in t] if result else []

        result = _mcp_call("resources/list")
        resource_uris = [r["uri"] for r in result.get("resources", []) if "uri" in r] if result else []

        result = _mcp_call("prompts/list")
        prompt_targets = []
        if result:
            for prompt in result.get("prompts", []):
                prompt_name = prompt.get("name")
                if not isinstance(prompt_name, str) or not prompt_name:
                    continue
                required_arguments = {}
                for argument in prompt.get("arguments", []) or []:
                    arg_name = argument.get("name")
                    if argument.get("required") and isinstance(arg_name, str) and arg_name:
                        required_arguments[arg_name] = _default_prompt_argument_value(prompt_name, arg_name)
                prompt_targets.append(PromptTarget(name=prompt_name, required_arguments=required_arguments))

        discovered_targets.append(
            ServerTarget(
                server_id=server_id,
                server_name=server_name,
                tool_names=tool_names,
                resource_uris=resource_uris,
                prompt_targets=prompt_targets,
            )
        )

    _server_targets = discovered_targets
    if not _server_targets:
        logger.error("No MCP server targets could be initialized.")
        return

    primary = _server_targets[0]
    _server_id = primary.server_id
    _tool_names = primary.tool_names
    _resource_uris = primary.resource_uris
    _prompt_targets = primary.prompt_targets

    logger.info("Using %d MCP server target(s)", len(_server_targets))
    for target in _server_targets:
        logger.info(
            "  server=%s name=%r tools=%d resources=%d prompts=%d",
            target.server_id,
            target.server_name,
            len(target.tool_names),
            len(target.resource_uris),
            len(target.prompt_targets),
        )


# =============================================================================
# Event Handlers
# =============================================================================


_detect_lock_done = False


def _ensure_detected(host: str) -> None:
    """Run auto-detection once per process (safe for --processes mode)."""
    global _detect_lock_done  # pylint: disable=global-statement
    if _detect_lock_done:
        return
    _detect_lock_done = True
    _auto_detect(host)


@events.init_command_line_parser.add_listener
def set_defaults(parser):
    parser.set_defaults(users=150, spawn_rate=30, run_time="120s")


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    del environment, kwargs
    _configure_log_levels()


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    host = environment.host or "http://localhost:4444"
    # Run auto-detect in every process (master, workers, standalone)
    # This ensures _server_id / _tool_names are populated in each worker
    _ensure_detected(host)
    # Only log banner from master / standalone
    if not isinstance(environment.runner, WorkerRunner):
        logger.info("=" * 70)
        logger.info("MCP STREAMABLE HTTP PROTOCOL LOAD TEST")
        logger.info("=" * 70)
        logger.info("  Host: %s", host)
        if _server_targets:
            for target in _server_targets[:5]:
                logger.info(
                    "  MCP endpoint: %s/servers/%s/mcp (%s, tools=%d)",
                    host,
                    target.server_id,
                    target.server_name,
                    len(target.tool_names),
                )
        elif _server_id:
            logger.info("  MCP endpoint: %s/servers/%s/mcp", host, _server_id)
            logger.info("  Tools: %s", ", ".join(_tool_names[:10]) if _tool_names else "(none)")
        logger.info("=" * 70)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    if isinstance(environment.runner, WorkerRunner):
        return
    stats = environment.stats
    total = stats.total.num_requests
    fails = stats.total.num_failures
    fail_pct = (fails / total * 100) if total > 0 else 0

    print("\n" + "=" * 90)
    print("MCP STREAMABLE HTTP PROTOCOL — RESULTS")
    print("=" * 90)
    print(f"\n  {'OVERALL':^86}")
    print("  " + "-" * 86)
    print(f"  Total Requests:     {total:>12,}")
    print(f"  Total Failures:     {fails:>12,} ({fail_pct:.2f}%)")
    print(f"  Requests/sec (RPS): {stats.total.total_rps:>12.2f}")
    if total > 0:
        print("\n  Response Times (ms):")
        print(f"    Average:  {stats.total.avg_response_time:>10.2f}")
        print(f"    Min:      {stats.total.min_response_time:>10.2f}")
        print(f"    Max:      {stats.total.max_response_time:>10.2f}")
        print(f"    p50:      {stats.total.get_response_time_percentile(0.50):>10.2f}")
        print(f"    p90:      {stats.total.get_response_time_percentile(0.90):>10.2f}")
        print(f"    p95:      {stats.total.get_response_time_percentile(0.95):>10.2f}")
        print(f"    p99:      {stats.total.get_response_time_percentile(0.99):>10.2f}")

    # Per-endpoint breakdown
    entries = sorted(stats.entries.values(), key=lambda e: e.num_requests, reverse=True)
    if entries:
        print(f"\n  {'ENDPOINT BREAKDOWN':^86}")
        print("  " + "-" * 86)
        print(f"  {'Name':<45} {'Reqs':>8} {'Fails':>8} {'RPS':>8} {'Avg(ms)':>8} {'p99(ms)':>8}")
        print("  " + "-" * 86)
        for entry in entries[:20]:
            p99 = entry.get_response_time_percentile(0.99) if entry.num_requests > 0 else 0
            print(f"  {entry.name:<45} {entry.num_requests:>8,} {entry.num_failures:>8,} " f"{entry.total_rps:>8.1f} {entry.avg_response_time:>8.1f} {p99:>8.1f}")

    print("\n" + "=" * 90 + "\n")


# =============================================================================
# Helper: JSON-RPC
# =============================================================================


def _jsonrpc(method: str, params: dict | None = None) -> dict:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method}
    if params is not None:
        payload["params"] = params
    return payload


# =============================================================================
# Base MCP User — handles session init, auth, and request mechanics
# =============================================================================


class BaseMCPUser(FastHttpUser):
    """Base for all MCP Streamable HTTP user classes.

    Uses FastHttpUser for gevent-based high concurrency.
    Each user maintains its own MCP session via Mcp-Session-Id header.
    """

    abstract = True
    connection_timeout = 30.0
    network_timeout = 30.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mcp_session_id: str | None = None
        self._initialized = False
        self._token = _get_token()
        self._server_id = ""
        self._server_name = ""
        self._tool_names: list[str] = []
        self._resource_uris: list[str] = []
        self._prompt_targets: list[PromptTarget] = []

    def _mcp_path(self) -> str:
        return f"/servers/{self._server_id}/mcp"

    def _mcp_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        return headers

    def _mcp_request(self, method: str, params: dict | None, name: str) -> dict | None:
        """Send MCP JSON-RPC request and validate the response.

        Returns the 'result' field on success, None on error.
        """
        payload = _jsonrpc(method, params)
        try:
            with self.client.post(
                self._mcp_path(),
                data=json.dumps(payload),
                headers=self._mcp_headers(),
                name=name,
                catch_response=True,
            ) as response:
                if response is None:
                    return None

                # Capture session ID
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
                except Exception as e:
                    response.failure(f"Invalid JSON: {e}")
                    return None

                if data is None:
                    response.failure("Null JSON response")
                    return None

                if "error" in data:
                    err = data["error"]
                    response.failure(f"JSON-RPC error {err.get('code', '?')}: {err.get('message', '?')}")
                    return None

                response.success()
                return data.get("result")
        except Exception as e:  # pragma: no cover - network client can fail before a response exists
            logger.warning("MCP request failed before response for %s: %s", name, e)
            return None

    def _assign_target(self):
        global _server_target_index  # pylint: disable=global-statement
        if not _server_targets:
            return
        target = _server_targets[_server_target_index % len(_server_targets)]
        _server_target_index += 1
        self._server_id = target.server_id
        self._server_name = target.server_name
        self._tool_names = list(target.tool_names)
        self._resource_uris = list(target.resource_uris)
        self._prompt_targets = list(target.prompt_targets)

    def _ensure_initialized(self):
        """Initialize the MCP session (once per user lifecycle)."""
        if self._initialized:
            return
        if not self._server_id:
            return
        result = self._mcp_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "locust-mcp-protocol", "version": "1.0.0"},
            },
            "MCP initialize",
        )
        if result is not None:
            self._initialized = True

    def on_start(self):
        self._assign_target()
        self._ensure_initialized()


# =============================================================================
# User 1: MCPAgentUser — Realistic agent with 6 tools (customer scenario)
# =============================================================================


class MCPAgentUser(BaseMCPUser):
    """Simulates a realistic AI agent that uses 6 MCP tools.

    Matches the customer scenario: an agent with 6 tools at 150 RPS target.
    Each "turn" the agent:
      1. Calls tools/list (periodic discovery)
      2. Calls 1-3 tools per turn (random selection from available tools)
      3. Occasionally lists resources/prompts

    Weight: 10 (dominant — this is the primary scenario to measure)
    """

    weight = 10
    wait_time = between(0.05, 0.3)

    def _pick_tools(self, n: int = 1) -> list[str]:
        """Pick n random tools from the discovered set (cap at 6 like the customer)."""
        pool = self._tool_names[:6] if len(self._tool_names) > 6 else self._tool_names
        if not pool:
            return []
        return random.sample(pool, min(n, len(pool)))

    def _build_tool_args(self, tool_name: str) -> dict:
        """Build plausible arguments for a tool based on its name."""
        name_lower = tool_name.lower()
        if "time" in name_lower or "timezone" in name_lower:
            return {"timezone": random.choice(TIMEZONES)}
        if "echo" in name_lower:
            return {"message": f"load-test-{random.randint(1, 10000)}"}
        if "convert" in name_lower:
            src = random.choice(TIMEZONES)
            dst = random.choice([t for t in TIMEZONES if t != src])
            return {"time": "2025-06-15T14:30:00Z", "source_timezone": src, "target_timezone": dst}
        # Generic: many tools accept empty args or have defaults
        return {}

    @task(15)
    @tag("agent", "tools", "call")
    def agent_call_tool(self):
        """Agent calls a tool — the core workload."""
        tools = self._pick_tools(1)
        if not tools:
            return
        tool = tools[0]
        args = self._build_tool_args(tool)
        self._mcp_request("tools/call", {"name": tool, "arguments": args}, f"MCP tools/call [{tool}]")

    @task(8)
    @tag("agent", "tools", "call")
    def agent_multi_tool_turn(self):
        """Agent calls 2-3 tools in sequence (multi-step reasoning)."""
        tools = self._pick_tools(random.randint(2, 3))
        for tool in tools:
            args = self._build_tool_args(tool)
            self._mcp_request("tools/call", {"name": tool, "arguments": args}, f"MCP tools/call [{tool}]")

    @task(5)
    @tag("agent", "tools", "list")
    def agent_list_tools(self):
        """Agent discovers available tools."""
        self._mcp_request("tools/list", {}, "MCP tools/list")

    @task(2)
    @tag("agent", "resources")
    def agent_list_resources(self):
        """Agent lists resources."""
        self._mcp_request("resources/list", {}, "MCP resources/list")

    @task(2)
    @tag("agent", "prompts")
    def agent_list_prompts(self):
        """Agent lists prompts."""
        self._mcp_request("prompts/list", {}, "MCP prompts/list")

    @task(1)
    @tag("agent", "resources")
    def agent_read_resource(self):
        """Agent reads a resource."""
        if self._resource_uris:
            uri = random.choice(self._resource_uris)
            self._mcp_request("resources/read", {"uri": uri}, "MCP resources/read")

    @task(1)
    @tag("agent", "prompts")
    def agent_get_prompt(self):
        """Agent gets a prompt."""
        if self._prompt_targets:
            prompt = random.choice(self._prompt_targets)
            self._mcp_request("prompts/get", {"name": prompt.name, "arguments": dict(prompt.required_arguments)}, "MCP prompts/get")

    @task(1)
    @tag("agent", "ping")
    def agent_ping(self):
        """Agent sends ping (keepalive)."""
        self._mcp_request("ping", None, "MCP ping")


# =============================================================================
# User 2: MCPToolCallerUser — Heavy tool/call in tight loop
# =============================================================================


class MCPToolCallerUser(BaseMCPUser):
    """Hammers tools/call as fast as possible to find the ceiling.

    Weight: 5
    """

    weight = 5
    wait_time = between(0.02, 0.1)

    @task(20)
    @tag("toolcall", "call")
    def call_tool(self):
        """Call a random tool rapidly."""
        if not self._tool_names:
            return
        tool = random.choice(self._tool_names[:6] if len(self._tool_names) > 6 else self._tool_names)
        name_lower = tool.lower()
        if "time" in name_lower:
            args = {"timezone": random.choice(TIMEZONES)}
        elif "echo" in name_lower:
            args = {"message": "perf-test"}
        elif "convert" in name_lower:
            args = {"time": "2025-01-01T00:00:00Z", "source_timezone": "UTC", "target_timezone": "Europe/London"}
        else:
            args = {}
        self._mcp_request("tools/call", {"name": tool, "arguments": args}, "MCP tools/call [rapid]")

    @task(1)
    @tag("toolcall", "list")
    def list_tools(self):
        """Occasional tools/list."""
        self._mcp_request("tools/list", {}, "MCP tools/list [rapid]")


# =============================================================================
# User 3: MCPDiscoveryUser — Discovery-heavy (tools/list, resources, prompts)
# =============================================================================


class MCPDiscoveryUser(BaseMCPUser):
    """Exercises discovery endpoints heavily.

    Weight: 3
    """

    weight = 3
    wait_time = between(0.05, 0.2)

    @task(10)
    @tag("discovery", "tools")
    def list_tools(self):
        self._mcp_request("tools/list", {}, "MCP tools/list")

    @task(8)
    @tag("discovery", "resources")
    def list_resources(self):
        self._mcp_request("resources/list", {}, "MCP resources/list")

    @task(8)
    @tag("discovery", "prompts")
    def list_prompts(self):
        self._mcp_request("prompts/list", {}, "MCP prompts/list")

    @task(5)
    @tag("discovery", "resources")
    def list_resource_templates(self):
        self._mcp_request("resources/templates/list", {}, "MCP resources/templates/list")

    @task(3)
    @tag("discovery", "resources")
    def read_resource(self):
        if self._resource_uris:
            uri = random.choice(self._resource_uris)
            self._mcp_request("resources/read", {"uri": uri}, "MCP resources/read")

    @task(3)
    @tag("discovery", "prompts")
    def get_prompt(self):
        if self._prompt_targets:
            prompt = random.choice(self._prompt_targets)
            self._mcp_request("prompts/get", {"name": prompt.name, "arguments": dict(prompt.required_arguments)}, "MCP prompts/get")


# =============================================================================
# User 4: MCPSessionChurnUser — New session per cycle (worst case)
# =============================================================================


class MCPSessionChurnUser(BaseMCPUser):
    """Creates a new MCP session for every request cycle.

    This simulates the worst case where clients don't reuse sessions
    (e.g. serverless functions, short-lived containers).

    Weight: 2
    """

    weight = 2
    wait_time = between(0.1, 0.3)

    def on_start(self):
        # Do NOT call _ensure_initialized — each task cycle initializes fresh
        pass

    @task(10)
    @tag("churn", "lifecycle")
    def full_lifecycle(self):
        """Full init -> tools/list -> tools/call -> end."""
        # Reset session
        self._mcp_session_id = None
        self._initialized = False

        # Initialize
        self._mcp_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "locust-churn", "version": "1.0.0"},
            },
            "MCP initialize [churn]",
        )

        # List tools
        self._mcp_request("tools/list", {}, "MCP tools/list [churn]")

        # Call a tool
        if self._tool_names:
            tool = random.choice(self._tool_names[:6] if len(self._tool_names) > 6 else self._tool_names)
            name_lower = tool.lower()
            if "time" in name_lower:
                args = {"timezone": random.choice(TIMEZONES)}
            elif "echo" in name_lower:
                args = {"message": "churn-test"}
            else:
                args = {}
            self._mcp_request("tools/call", {"name": tool, "arguments": args}, "MCP tools/call [churn]")


# =============================================================================
# User 5: MCPStressUser — Maximum throughput with constant_throughput
# =============================================================================


class MCPStressUser(BaseMCPUser):
    """Constant-throughput stress test: 5 req/s per user.

    With 100 users = 500 RPS target.

    Weight: 1 (opt-in via class picker for stress runs)
    """

    weight = 1
    wait_time = constant_throughput(5)

    @task(10)
    @tag("stress", "call")
    def stress_call_tool(self):
        if not self._tool_names:
            return
        tool = random.choice(self._tool_names[:6] if len(self._tool_names) > 6 else self._tool_names)
        name_lower = tool.lower()
        if "time" in name_lower:
            args = {"timezone": "UTC"}
        elif "echo" in name_lower:
            args = {"message": "stress"}
        else:
            args = {}
        self._mcp_request("tools/call", {"name": tool, "arguments": args}, "MCP tools/call [stress]")

    @task(3)
    @tag("stress", "list")
    def stress_list_tools(self):
        self._mcp_request("tools/list", {}, "MCP tools/list [stress]")

    @task(1)
    @tag("stress", "ping")
    def stress_ping(self):
        self._mcp_request("ping", None, "MCP ping [stress]")


# =============================================================================
# User 6: RESTBaselineUser — /rpc + REST API comparison baseline
# =============================================================================


class RESTBaselineUser(FastHttpUser):
    """REST API baseline for direct comparison with MCP streamable HTTP.

    Runs the same logical operations (tools/list, tools/call) via the /rpc
    endpoint and REST API, so we can measure the overhead that the MCP
    streamable HTTP transport adds.

    Weight: 0 (opt-in via class picker — not included in default runs)
    """

    weight = 0
    wait_time = between(0.05, 0.2)
    connection_timeout = 30.0
    network_timeout = 30.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._token = _get_token()
        self._auth_headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @task(10)
    @tag("baseline", "rpc", "list")
    def rpc_list_tools(self):
        """tools/list via /rpc (REST JSON-RPC)."""
        payload = _jsonrpc("tools/list", {})
        with self.client.post(
            "/rpc",
            data=json.dumps(payload),
            headers=self._auth_headers,
            name="REST /rpc tools/list",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(10)
    @tag("baseline", "rpc", "call")
    def rpc_call_tool(self):
        """tools/call via /rpc (REST JSON-RPC)."""
        if not _tool_names:
            return
        tool = random.choice(_tool_names[:6] if len(_tool_names) > 6 else _tool_names)
        name_lower = tool.lower()
        if "echo" in name_lower:
            args = {"message": "baseline"}
        elif "time" in name_lower:
            args = {"timezone": "UTC"}
        else:
            args = {}
        payload = _jsonrpc("tools/call", {"name": tool, "arguments": args})
        with self.client.post(
            "/rpc",
            data=json.dumps(payload),
            headers=self._auth_headers,
            name="REST /rpc tools/call",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(5)
    @tag("baseline", "rest", "list")
    def rest_list_tools(self):
        """/tools via REST API."""
        with self.client.get(
            "/tools",
            headers=self._auth_headers,
            name="REST /tools",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(3)
    @tag("baseline", "health")
    def health_check(self):
        """/health (no auth, minimal middleware)."""
        with self.client.get("/health", name="REST /health", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")
