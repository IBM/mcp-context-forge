#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Register compose-managed MCP servers and A2A agents with the ContextForge gateway.

Single entry point for the one-shot ``register`` service in ``docker-compose.yml``.
The service bind-mounts this file read-only and runs the ``stack`` subcommand,
which discovers which upstreams are running (compose-profile dependent) via
Docker's embedded DNS and registers each one::

    volumes:
      - ./scripts/register_mcp_servers.py:/app/scripts/register_mcp_servers.py:ro
    entrypoint: ["python3", "/app/scripts/register_mcp_servers.py"]
    command: ["stack"]

Individual subcommands remain for manual re-registration of a single target:

    fast-time, fast-test, fast-time-2026, slow-time, a2a-echo, benchmark

Registration pipeline (common to all MCP gateway targets):
    mint admin token -> wait authenticated-ready -> [per target] wait upstream
    health -> delete existing gateway + fixed virtual server -> POST /gateways
    -> force tools refresh -> wait for catalog sync -> collect catalog IDs ->
    create fixed-ID virtual server.

Deliberate per-target variations are data (see ``GATEWAY_TARGETS``): the A2A
echo agent registers via ``POST /a2a`` instead of ``/gateways``, and benchmark
registers a loop of N servers tolerating already-registered (409) entries.
Registrations uniformly use the admin token and delete+recreate idempotency;
the historical per-flow variations (non-admin mints, gateway reuse, divergent
retry sets) were incidental and have been collapsed.

Environment:
    JWT_SECRET_KEY         Secret used to mint the bearer token (required).
    GATEWAY_BASE_URL       Gateway base URL (default: http://gateway:4444).
    BENCHMARK_SERVER_COUNT benchmark: number of servers to register (default: 10).
    BENCHMARK_START_PORT   benchmark: first server port (default: 9000).

The script uses only the Python standard library so it runs unmodified inside
the gateway container image; the bearer token is minted via
``python3 -m mcpgateway.utils.create_jwt_token`` which ships in that image.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://gateway:4444")

# Populated by each subcommand before any api_request call.
TOKEN = ""


def generate_token() -> str:
    """Mint an admin gateway JWT using the utility bundled in the gateway image."""
    print("Generating JWT token...")
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        print("❌ JWT_SECRET_KEY is not set")
        sys.exit(1)
    cmd = [
        sys.executable,
        "-m",
        "mcpgateway.utils.create_jwt_token",
        "--username",
        "admin@example.com",
        "--exp",
        "10080",
        "--secret",
        secret,
        "--algo",
        "HS256",
        "--admin",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        print(f"❌ Failed to generate JWT token: {result.stderr.strip()}")
        sys.exit(1)
    return token


def decode_token(token: str) -> None:
    """Decode the token to verify claims (diagnostic only, never fatal)."""
    print("Decoding token to verify claims...")
    result = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--decode", token],
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        print("Failed to decode token")


def api_request(method: str, path: str, data: dict | None = None) -> Any:
    """Make an authenticated API request to the gateway."""
    url = f"{GATEWAY_BASE_URL}{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    if data:
        req.data = json.dumps(data).encode("utf-8")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def api_request_with_retry(
    method: str,
    path: str,
    data: dict | None = None,
    retries: int = 30,
    delay: int = 2,
    retry_statuses: tuple[int, ...] = (401, 403, 502, 503),
) -> Any:
    """Retry authenticated API requests while gateway workers settle."""
    for attempt in range(1, retries + 1):
        try:
            return api_request(method, path, data)
        except urllib.error.HTTPError as exc:
            if exc.code in retry_statuses and attempt < retries:
                print(f"Retrying {method} {path} after HTTP {exc.code} ({attempt}/{retries})")
                time.sleep(delay)
                continue
            raise
        except Exception:
            if attempt < retries:
                print(f"Retrying {method} {path} after transient error ({attempt}/{retries})")
                time.sleep(delay)
                continue
            raise
    return None  # unreachable, keeps type checkers happy


def wait_for_health(name: str, url: str, attempts: int = 60, delay: int = 2) -> None:
    """Poll an unauthenticated health endpoint until it returns HTTP 200."""
    for i in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    print(f"✅ {name} is healthy")
                    return
        except Exception:
            pass
        print(f"Waiting for {name}... ({i}/{attempts})")
        time.sleep(delay)
    print(f"❌ {name} failed to become healthy")
    sys.exit(1)


def wait_for_tcp(name: str, host: str, port: int, attempts: int = 30, delay: float = 1.0) -> None:
    """Wait until a TCP connection to host:port succeeds (no HTTP health endpoint)."""
    for i in range(1, attempts + 1):
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"✅ {name} is reachable")
                return
        except OSError:
            pass
        print(f"Waiting for {name}... ({i}/{attempts})")
        time.sleep(delay)
    print(f"❌ {name} failed to become reachable")
    sys.exit(1)


def host_resolvable(host: str) -> bool:
    """True when the compose service name resolves (i.e. a container exists).

    Profile-disabled services have no running container and fail Docker's
    embedded DNS; present-but-starting services already resolve.
    """
    try:
        socket.getaddrinfo(host, None)
        return True
    except socket.gaierror:
        return False


def wait_for_authenticated_readiness() -> None:
    """Wait until an authenticated GET /gateways succeeds.

    /health goes green before the admin/bootstrap path is fully ready for
    authenticated registration calls, so poll the real endpoint.
    """
    print("Waiting for authenticated gateway readiness...")
    for i in range(1, 61):
        try:
            gateways = api_request("GET", "/gateways")
            print(f"✅ Authenticated gateway readiness confirmed ({len(gateways)} gateways visible)")
            return
        except urllib.error.HTTPError as exc:
            print(f"Authenticated readiness not ready yet ({i}/60): HTTP {exc.code}")
        except Exception as exc:
            print(f"Authenticated readiness not ready yet ({i}/60): {exc}")
        time.sleep(2)
    print("❌ Gateway authenticated readiness check failed")
    sys.exit(1)


def delete_gateway_by_name(name: str) -> None:
    """Delete a registered gateway (peer MCP server) by name if it exists."""
    try:
        gateways = api_request_with_retry("GET", "/gateways")
        for gw in gateways:
            if gw.get("name") == name:
                print(f"Deleting existing gateway {gw['id']}...")
                api_request_with_retry("DELETE", f"/gateways/{gw['id']}")
    except Exception as e:
        print(f"Note: {e}")


def register_gateway(name: str, url: str) -> str:
    """Register a peer MCP server via Streamable HTTP and return its gateway ID."""
    result = api_request_with_retry(
        "POST",
        "/gateways",
        {
            "name": name,
            "url": url,
            "transport": "STREAMABLEHTTP",
        },
    )
    gateway_id = result.get("id", "")
    if not gateway_id:
        print("❌ Registration failed - no ID in response")
        sys.exit(1)
    print(f"✅ Successfully registered {name} (gateway_id: {gateway_id})")
    return gateway_id


def delete_virtual_server(virtual_server_id: str) -> None:
    """Delete a virtual server by fixed ID if it exists."""
    try:
        api_request_with_retry("DELETE", f"/servers/{virtual_server_id}")
        print(f"Deleted existing virtual server {virtual_server_id}")
    except Exception as e:
        print(f"Note: No existing virtual server to delete (or error: {e})")


def wait_for_tool_sync(gateway_id: str, gateway_name: str, attempts: int = 60, warn_only: bool = False) -> None:
    """Wait until tools synced from a peer gateway appear in the catalog.

    Note: API payloads may expose either gatewayId (camelCase) or gateway_id
    (snake_case) depending on the serializer path; the catalog uses camelCase.
    """
    print("Waiting for tools to sync...")
    for i in range(attempts):
        time.sleep(1)
        try:
            tools = api_request("GET", "/tools")
            synced = [t for t in tools if t.get("gatewayId") == gateway_id]
            if synced:
                print(f"Found {len(synced)} tools from {gateway_name} gateway")
                return
        except Exception:
            pass
        print(f"Waiting for sync... ({i + 1}/{attempts})")
    if warn_only:
        print("Warning: No tools synced, continuing anyway...")
    else:
        print(f"❌ Tools from {gateway_name} gateway did not sync in time")
        sys.exit(1)


def collect_gateway_items(gateway_id: str, include_resources_prompts: bool = False) -> tuple[list, list, list]:
    """Fetch tool/resource/prompt IDs belonging to a specific peer gateway."""
    tool_ids: list = []
    resource_ids: list = []
    prompt_ids: list = []

    try:
        tools = api_request("GET", "/tools")
        gw_tools = [t for t in tools if t.get("gatewayId") == gateway_id]
        tool_ids = [t["id"] for t in gw_tools]
        print(f"Found tools: {[t['name'] for t in gw_tools]}")
    except Exception as e:
        print(f"Failed to fetch tools: {e}")

    if include_resources_prompts:
        try:
            resources = api_request("GET", "/resources")
            gw_resources = [r for r in resources if r.get("gatewayId") == gateway_id or r.get("gateway_id") == gateway_id]
            resource_ids = [r["id"] for r in gw_resources]
            print(f"Found resources: {[r['name'] for r in gw_resources]}")
        except Exception as e:
            print(f"Failed to fetch resources: {e}")

        try:
            prompts = api_request("GET", "/prompts")
            gw_prompts = [p for p in prompts if p.get("gatewayId") == gateway_id or p.get("gateway_id") == gateway_id]
            prompt_ids = [p["id"] for p in gw_prompts]
            print(f"Found prompts: {[p['name'] for p in gw_prompts]}")
        except Exception as e:
            print(f"Failed to fetch prompts: {e}")

    return tool_ids, resource_ids, prompt_ids


def create_virtual_server(
    virtual_server_id: str,
    name: str,
    description: str,
    tool_ids: list,
    resource_ids: list,
    prompt_ids: list,
) -> None:
    """Create a virtual server bundling the given catalog entries."""
    print("Creating virtual server...")
    try:
        # API expects payload wrapped in a 'server' key; a fixed UUID keeps the
        # server ID consistent across restarts.
        server_payload = {
            "server": {
                "id": virtual_server_id,
                "name": name,
                "description": description,
                "associated_tools": tool_ids,
                "associated_resources": resource_ids,
                "associated_prompts": prompt_ids,
            }
        }
        result = api_request_with_retry("POST", "/servers", server_payload)
        print(f"Virtual server created: {result}")
        print(f"✅ Successfully created virtual server with {len(tool_ids)} tools, {len(resource_ids)} resources, {len(prompt_ids)} prompts")
    except Exception as e:
        print(f"❌ Failed to create virtual server: {e}")
        sys.exit(1)


@dataclass(frozen=True)
class GatewayTarget:
    """Declarative registration config for one MCP upstream."""

    name: str  # gateway registration name
    url: str  # upstream /mcp URL the gateway federates
    host: str  # compose service DNS name (used for stack discovery)
    health_url: str  # upstream /health probe URL
    virtual_server_id: str | None = None  # fixed VS UUID; None = no virtual server
    virtual_server_name: str = ""
    virtual_server_description: str = ""
    include_resources_prompts: bool = False  # collect resources+prompts into the VS
    require_tools: bool = False  # hard-fail when the sync yields no tools
    write_token_file: bool = False  # write /tmp/gateway-token.txt (load-test handoff)


GATEWAY_TARGETS = [
    GatewayTarget(
        name="fast_time",
        url="http://fast_time_server:9080/mcp",
        host="fast_time_server",
        health_url="http://fast_time_server:9080/health",
        virtual_server_id="9779b6698cbd4b4995ee04a4fab38737",  # pragma: allowlist secret
        virtual_server_name="Fast Time Server",
        virtual_server_description="Virtual server exposing Fast Time MCP tools, resources, and prompts",
        include_resources_prompts=True,
        require_tools=True,
        write_token_file=True,
    ),
    GatewayTarget(
        name="fast_test",
        url="http://fast_test_server:8880/mcp",
        host="fast_test_server",
        health_url="http://fast_test_server:8880/health",
        virtual_server_id="b8e3f1a2c4d5e6f7a1b2c3d4e5f6a7b8",  # pragma: allowlist secret
        virtual_server_name="Fast Test Server",
        virtual_server_description="Virtual server exposing Fast Test MCP tools (echo, time, stats)",
    ),
    GatewayTarget(
        name="fast_time_2026",
        url="http://fast_time_2026_server:9080/mcp",
        host="fast_time_2026_server",
        health_url="http://fast_time_2026_server:9080/health",
        virtual_server_id="f3a1c5e7b9d24f6081a3c5e7b9d24f60",  # pragma: allowlist secret
        virtual_server_name="Fast Time 2026 Server",
        virtual_server_description="Virtual server exposing Fast Time tools over strict MCP 2026-07-28",
    ),
    GatewayTarget(
        name="slow_time",
        url="http://slow_time_server:8081/mcp",
        host="slow_time_server",
        health_url="http://slow_time_server:8081/health",
    ),
]


def register_gateway_target(t: GatewayTarget) -> None:
    """Common registration pipeline for a single MCP upstream.

    Assumes TOKEN is set and the gateway is authenticated-ready. Idempotent by
    destruction: any existing gateway registration and fixed-ID virtual server
    are deleted first, so repeated runs always end in a freshly synced state.
    """
    wait_for_health(t.name, t.health_url, attempts=30)

    print(f"Registering {t.name} with gateway ({t.url}, Streamable HTTP)...")
    delete_gateway_by_name(t.name)

    if t.virtual_server_id:
        delete_virtual_server(t.virtual_server_id)

    try:
        gateway_id = register_gateway(t.name, t.url)
    except SystemExit:
        raise
    except Exception as e:
        print(f"❌ Registration failed: {e}")
        sys.exit(1)

    # Force immediate discovery before polling for synced catalog entries.
    try:
        refresh_result = api_request_with_retry(
            "POST",
            f"/gateways/{gateway_id}/tools/refresh?include_resources=true&include_prompts=true",
            retries=20,
            delay=2,
            retry_statuses=(401, 409, 502, 503),
        )
        print(f"Refresh response: {refresh_result}")
    except Exception as e:
        print(f"Note: manual refresh did not complete immediately: {e}")

    wait_for_tool_sync(gateway_id, t.name, attempts=60, warn_only=not t.require_tools)

    tool_ids, resource_ids, prompt_ids = collect_gateway_items(gateway_id, include_resources_prompts=t.include_resources_prompts)

    if t.require_tools and not tool_ids:
        print(f"❌ {t.name} gateway sync completed without any tools; aborting virtual server creation")
        sys.exit(1)

    if t.virtual_server_id:
        create_virtual_server(t.virtual_server_id, t.virtual_server_name, t.virtual_server_description, tool_ids, resource_ids, prompt_ids)

    if t.write_token_file:
        print("Writing bearer token to /tmp/gateway-token.txt...")
        with open("/tmp/gateway-token.txt", "w", encoding="utf-8") as fh:
            fh.write(TOKEN + "\n")
        print("Token written to /tmp/gateway-token.txt")

    print(f"✅ {t.name} registration complete!")


def register_a2a_echo() -> None:
    """Register the a2a-echo-agent A2A agent with the gateway."""
    print("Registering a2a_echo_agent with gateway...")

    # Delete existing agent if present
    try:
        agents = api_request("GET", "/a2a")
        items = agents if isinstance(agents, list) else agents.get("agents", agents.get("items", []))
        for a in items:
            if a.get("name") == "a2a-echo-agent":
                print(f"Deleting existing A2A agent {a.get('id')}...")
                api_request("DELETE", f"/a2a/{a.get('id')}")
    except Exception as e:
        print(f"Note: {e}")

    # Register agent (JSON-RPC endpoint at /)
    payload = {
        "agent": {
            "name": "a2a-echo-agent",
            "description": "Lightweight A2A echo agent for docker-compose testing",
            "endpoint_url": "http://a2a_echo_agent:9100/",
            "agent_type": "jsonrpc",
            "protocol_version": "1.0.0",
            "capabilities": {"echo": True, "transport": "JSONRPC", "supportsLegacyInterop": True},
            "tags": ["testing", "a2a", "echo"],
        },
        "visibility": "public",
    }

    result = api_request("POST", "/a2a", payload)
    print(f"✅ Registered a2a_echo_agent: {result.get('id', 'unknown')}")
    print("✅ Registration complete!")


def register_benchmark() -> None:
    """Register BENCHMARK_SERVER_COUNT benchmark MCP servers with the gateway.

    Additive rather than delete+recreate: already-registered servers (HTTP 409)
    count as success so re-runs against large server counts stay cheap.
    """
    print("Registering benchmark servers with gateway...")

    server_count = int(os.environ.get("BENCHMARK_SERVER_COUNT", "10"))
    start_port = int(os.environ.get("BENCHMARK_START_PORT", "9000"))

    print(f"Registering {server_count} benchmark servers (ports {start_port}-{start_port + server_count - 1})...")
    registered = 0
    for port in range(start_port, start_port + server_count):
        name = f"benchmark-{port}"
        try:
            result = api_request(
                "POST",
                "/gateways",
                {
                    "name": name,
                    "url": f"http://benchmark_server:{port}/mcp",
                    "transport": "STREAMABLEHTTP",
                },
            )
            print(f"✅ Registered {name}: {result.get('id', 'unknown')}")
            registered += 1
        except urllib.error.HTTPError as e:
            if e.code == 409:
                print(f"⏭️  {name} already registered")
                registered += 1
            else:
                print(f"❌ Failed to register {name}: HTTP {e.code}")
        except Exception as e:
            print(f"❌ Failed to register {name}: {e}")

    print(f"✅ Registration complete: {registered}/{server_count} benchmark servers")


def _standalone(t: GatewayTarget, decode: bool = False) -> None:
    """Standalone single-target registration: token + readiness + pipeline."""
    global TOKEN

    wait_for_health("gateway", f"{GATEWAY_BASE_URL}/health", attempts=60)

    TOKEN = generate_token()
    if decode:
        decode_token(TOKEN)

    wait_for_authenticated_readiness()

    register_gateway_target(t)


def _target(name: str) -> GatewayTarget:
    """Look up a gateway target by registration name."""
    return next(t for t in GATEWAY_TARGETS if t.name == name)


def cmd_fast_time() -> None:
    """Register fast_time_server and create its virtual server."""
    _standalone(_target("fast_time"), decode=True)
    print("✅ Setup complete!")


def cmd_fast_test() -> None:
    """Register fast_test_server and create its tools-only virtual server."""
    _standalone(_target("fast_test"))


def cmd_fast_time_2026() -> None:
    """Register the strict 2026-07-28 fast-time variant (tools-only VS)."""
    _standalone(_target("fast_time_2026"))


def cmd_slow_time() -> None:
    """Register slow_time_server with the gateway (no virtual server)."""
    _standalone(_target("slow_time"))


def cmd_a2a_echo() -> None:
    """Register the a2a-echo-agent A2A agent (standalone)."""
    global TOKEN
    TOKEN = generate_token()
    register_a2a_echo()


def cmd_benchmark() -> None:
    """Register the benchmark server loop (standalone)."""
    global TOKEN
    TOKEN = generate_token()
    # Wait for benchmark servers to start (standalone mode has no probe)
    print("Waiting for benchmark servers to start...")
    time.sleep(5)
    register_benchmark()


def cmd_stack() -> None:
    """Register every reachable compose upstream with the gateway in one pass.

    Which servers are present depends on the active compose profiles; each
    candidate is probed via Docker embedded DNS and skipped when its service
    has no running container. A failure on one target is reported but does not
    stop the remaining registrations; the exit code reflects any failures.
    """
    global TOKEN

    wait_for_health("gateway", f"{GATEWAY_BASE_URL}/health", attempts=60)

    TOKEN = generate_token()
    wait_for_authenticated_readiness()

    benchmark_start_port = int(os.environ.get("BENCHMARK_START_PORT", "9000"))

    # Non-gateway-entity flows: (label, compose host, readiness probe, register)
    special_targets = [
        (
            "a2a-echo-agent",
            "a2a_echo_agent",
            lambda: wait_for_tcp("a2a_echo_agent", "a2a_echo_agent", 9100),
            register_a2a_echo,
        ),
        (
            "benchmark",
            "benchmark_server",
            lambda: wait_for_health("benchmark_server", f"http://benchmark_server:{benchmark_start_port}/health", attempts=15),
            register_benchmark,
        ),
    ]

    print("Discovering reachable upstreams...")
    registered: list[str] = []
    failures: list[str] = []

    for t in GATEWAY_TARGETS:
        if not host_resolvable(t.host):
            print(f"⏭️  {t.name}: {t.host} not running (profile disabled); skipping")
            continue
        print(f"--- {t.name}: {t.host} found, registering ---")
        try:
            register_gateway_target(t)
            registered.append(t.name)
        except SystemExit:
            failures.append(t.name)
            print(f"❌ {t.name} registration failed; continuing with remaining targets")
        except Exception as exc:
            failures.append(t.name)
            print(f"❌ {t.name} registration failed: {exc}; continuing with remaining targets")

    for label, host, probe, register in special_targets:
        if not host_resolvable(host):
            print(f"⏭️  {label}: {host} not running (profile disabled); skipping")
            continue
        print(f"--- {label}: {host} found, registering ---")
        try:
            probe()
            register()
            registered.append(label)
        except SystemExit:
            failures.append(label)
            print(f"❌ {label} registration failed; continuing with remaining targets")
        except Exception as exc:
            failures.append(label)
            print(f"❌ {label} registration failed: {exc}; continuing with remaining targets")

    print(f"✅ Stack registration complete: {len(registered)} registered ({', '.join(registered) or 'none'})")
    if failures:
        print(f"❌ Failed registrations: {', '.join(failures)}")
        sys.exit(1)


def main() -> None:
    """Dispatch the requested registration subcommand."""
    parser = argparse.ArgumentParser(
        description="Register compose-managed MCP servers and A2A agents with the ContextForge gateway.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    subparsers.add_parser("stack", help="Register every reachable upstream (compose one-shot entrypoint)")
    subparsers.add_parser("fast-time", help="Register fast_time_server + virtual server")
    subparsers.add_parser("slow-time", help="Register slow_time_server (gateway only)")
    subparsers.add_parser("fast-test", help="Register fast_test_server + tools-only virtual server")
    subparsers.add_parser("fast-time-2026", help="Register the strict 2026-07-28 fast-time variant")
    subparsers.add_parser("a2a-echo", help="Register the a2a-echo-agent A2A agent")
    subparsers.add_parser("benchmark", help="Register BENCHMARK_SERVER_COUNT benchmark servers")
    args = parser.parse_args()

    handlers = {
        "stack": cmd_stack,
        "fast-time": cmd_fast_time,
        "slow-time": cmd_slow_time,
        "fast-test": cmd_fast_test,
        "fast-time-2026": cmd_fast_time_2026,
        "a2a-echo": cmd_a2a_echo,
        "benchmark": cmd_benchmark,
    }
    handlers[args.subcommand]()


if __name__ == "__main__":
    main()
