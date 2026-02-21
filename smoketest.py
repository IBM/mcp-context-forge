#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
# Author : Mihai Criveti
# Description: 🛠️ ContextForge Smoke-Test Utility

This script verifies a full install + runtime setup of the ContextForge:
- Creates a virtual environment and installs dependencies.
- Builds and runs the Docker HTTPS container.
- Starts the MCP Time Server via mcpgateway.translate.
- Verifies /health, /ready, /version before registering the gateway.
- Federates the time server as a gateway, verifies its tool list.
- Invokes the remote tool via /rpc and checks the result.
- Tests resource management, prompts, virtual servers, and error handling.
- Cleans up all created entities (gateway, process, container).
- Streams logs live with --tail and prints step timings.

Usage:
  ./smoketest.py                  Run full test
  ./smoketest.py --start-step 6   Resume from step 6
  ./smoketest.py --cleanup-only   Just run cleanup
  ./smoketest.py -v               Verbose (shows full logs)
"""

# Future
from __future__ import annotations

# Standard
import argparse
from collections import deque
import itertools
import json
import logging
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from typing import Callable, Dict, List, Tuple
import uuid
from urllib.parse import urlencode

# First-Party
from mcpgateway.config import settings

# ───────────────────────── Ports / constants ────────────────────────────
PORT_GATEWAY = 4444  # HTTPS container
PORT_TIME_SERVER = 8002  # mcpgateway.translate
DOCKER_CONTAINER = "mcpgateway"

MAKE_VENV_CMD = ["make", "venv", "install", "install-dev"]
MAKE_DOCKER_BUILD = ["make", "docker"]
MAKE_DOCKER_RUN = ["make", "docker-run-ssl-host"]
MAKE_DOCKER_STOP = ["make", "docker-stop"]

TRANSLATE_CMD = [
    "python3",
    "-m",
    "mcpgateway.translate",
    "--stdio",
    "uvx mcp-server-time --local-timezone=Europe/Dublin",
    "--port",
    str(PORT_TIME_SERVER),
]


# ───────────────────────── Test State Tracking ─────────────────────────
class TestContext:
    """Track all created entities for proper cleanup"""

    def __init__(self):
        self.gateways: List[int] = []
        self.resources: List[str] = []
        self.prompts: List[str] = []
        self.tools: List[str] = []
        self.virtual_servers: List[str] = []
        self.test_results: Dict[str, bool] = {}
        self.error_messages: Dict[str, str] = {}

    def add_gateway(self, gid: int):
        self.gateways.append(gid)

    def add_resource(self, uri: str):
        self.resources.append(uri)

    def add_prompt(self, name: str):
        self.prompts.append(name)

    def add_tool(self, tool_id: str):
        self.tools.append(tool_id)

    def add_virtual_server(self, server_id: str):
        self.virtual_servers.append(server_id)

    def record_test(self, name: str, success: bool, error: str = ""):
        self.test_results[name] = success
        if error:
            self.error_messages[name] = error

    def summary(self) -> str:
        total = len(self.test_results)
        passed = sum(1 for v in self.test_results.values() if v)
        failed = total - passed
        return f"Tests: {total} | Passed: {passed} | Failed: {failed}"


# Global test context
test_ctx = TestContext()


# ─────────────────────── Helper: pretty sections ────────────────────────
def log_section(title: str, emoji: str = "⚙️"):
    logging.info("\n%s  %s\n%s", emoji, title, "─" * (len(title) + 4))


# ───────────────────────── Tail-N streaming runner ───────────────────────
_spinner_cycle = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")


def run_shell(
    cmd: List[str] | str,
    desc: str,
    *,
    tail: int,
    verbose: bool,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run *cmd*; show rolling tail N lines refreshed in place."""
    log_section(desc, "🚀")
    logging.debug("CMD: %s", cmd if isinstance(cmd, str) else " ".join(shlex.quote(c) for c in cmd))

    proc = subprocess.Popen(
        cmd,
        shell=isinstance(cmd, str),
        text=True,
        bufsize=1,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    full_buf: list[str] = []
    tail_buf: deque[str] = deque(maxlen=tail)
    done = threading.Event()

    def pump():
        assert proc.stdout
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            full_buf.append(line)
            tail_buf.append(line)
            if verbose:
                print(line)
        done.set()

    threading.Thread(target=pump, daemon=True).start()

    start = time.time()
    try:
        while not done.is_set():
            time.sleep(0.2)
            if verbose:
                continue
            spinner = next(_spinner_cycle)
            header = f"{spinner} {desc} (elapsed {time.time() - start:4.0f}s)"
            pane_lines = list(tail_buf)
            pane_height = len(pane_lines) + 2
            sys.stdout.write(f"\x1b[{pane_height}F\x1b[J")  # rewind & clear
            print(header)
            for l in pane_lines:
                print(l[:120])
            print()
            sys.stdout.flush()
    except KeyboardInterrupt:
        proc.terminate()
        raise
    finally:
        proc.wait()

    if not verbose:  # clear final pane
        sys.stdout.write(f"\x1b[{min(len(tail_buf) + 2, tail + 2)}F\x1b[J")
        sys.stdout.flush()

    globals()["_PREV_CMD_OUTPUT"] = "\n".join(full_buf)  # for show_last()
    status = "✅ PASS" if proc.returncode == 0 else "❌ FAIL"
    logging.info("%s - %s", status, desc)
    if proc.returncode and check:
        logging.error("↳ Last %d lines:\n%s", tail, "\n".join(tail_buf))
        raise subprocess.CalledProcessError(proc.returncode, cmd, output="\n".join(full_buf))
    return subprocess.CompletedProcess(cmd, proc.returncode, "\n".join(full_buf), "")


def show_last(lines: int = 30):
    txt = globals().get("_PREV_CMD_OUTPUT", "")
    print("\n".join(txt.splitlines()[-lines:]))


# ───────────────────────────── Networking utils ──────────────────────────
def port_open(port: int, host="127.0.0.1", timeout=1.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def wait_http_ok(url: str, timeout: int = 30, *, headers: dict | None = None) -> bool:
    # Third-Party
    import requests

    end = time.time() + timeout
    while time.time() < end:
        try:
            if requests.get(url, timeout=2, verify=False, headers=headers).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


# Third-Party
# ───────────────────────────── Requests wrapper ──────────────────────────
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def generate_jwt() -> str:
    """
    Create a short-lived admin JWT that matches the gateway's settings.
    Resolution order → environment-variable override, then package defaults.
    """
    # Use email format for new authentication system
    user = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
    secret = os.getenv("JWT_SECRET_KEY", "my-test-key")
    expiry = os.getenv("TOKEN_EXPIRY", "300")  # seconds

    cmd = [
        "docker",
        "exec",
        DOCKER_CONTAINER,
        "python3",
        "-m",
        "mcpgateway.utils.create_jwt_token",
        "--username",
        user,
        "--exp",
        expiry,
        "--secret",
        secret,
    ]
    return subprocess.check_output(cmd, text=True).strip().strip('"')


def request(method: str, path: str, *, json_data=None, form_data=None, **kw):
    # Third-Party
    import requests

    token = generate_jwt()
    kw.setdefault("headers", {})["Authorization"] = f"Bearer {token}"
    kw["verify"] = False
    url = f"https://localhost:{PORT_GATEWAY}{path}"
    t0 = time.time()
    content_type = os.getenv("FORGE_CONTENT_TYPE", "application/json")
    kw["headers"]["Content-Type"] = content_type
    if content_type == "application/x-www-form-urlencoded" and form_data is not None:
        resp = requests.request(method, url, data=urlencode(form_data), **kw)
    else:
        resp = requests.request(method, url, json=json_data, **kw)
    ms = (time.time() - t0) * 1000
    logging.info("→ %s %s %s %.0f ms", method.upper(), path, resp.status_code, ms)
    logging.debug("  ↳ response: %s", resp.text[:400])
    return resp


# ───────────────────────────── Cleanup logic ─────────────────────────────
_translate_proc: subprocess.Popen | None = None
_translate_log_file = None


def cleanup():
    log_section("Cleanup", "🧹")
    global _translate_proc, _translate_log_file

    # Clean up all created entities
    cleanup_errors = []

    # Delete virtual servers
    for server_id in test_ctx.virtual_servers:
        try:
            logging.info("🗑️  Deleting virtual server: %s", server_id)
            request("DELETE", f"/servers/{server_id}")
        except Exception as e:
            cleanup_errors.append(f"Failed to delete server {server_id}: {e}")

    # Delete tools
    for tool_id in test_ctx.tools:
        try:
            logging.info("🗑️  Deleting tool: %s", tool_id)
            request("DELETE", f"/tools/{tool_id}")
        except Exception as e:
            cleanup_errors.append(f"Failed to delete tool {tool_id}: {e}")

    # Delete prompts
    for prompt_name in test_ctx.prompts:
        try:
            logging.info("🗑️  Deleting prompt: %s", prompt_name)
            request("DELETE", f"/prompts/{prompt_name}")
        except Exception as e:
            cleanup_errors.append(f"Failed to delete prompt {prompt_name}: {e}")

    # Delete resources
    for resource_uri in test_ctx.resources:
        try:
            logging.info("🗑️  Deleting resource: %s", resource_uri)
            request("DELETE", f"/resources/{resource_uri}")
        except Exception as e:
            cleanup_errors.append(f"Failed to delete resource {resource_uri}: {e}")

    # Delete gateways
    for gid in test_ctx.gateways:
        try:
            logging.info("🗑️  Deleting gateway ID: %s", gid)
            request("DELETE", f"/gateways/{gid}")
        except Exception as e:
            cleanup_errors.append(f"Failed to delete gateway {gid}: {e}")

    # Clean up the translate process
    if _translate_proc and _translate_proc.poll() is None:
        logging.info("🔄 Terminating mcpgateway.translate process (PID: %d)", _translate_proc.pid)
        _translate_proc.terminate()
        try:
            _translate_proc.wait(timeout=5)
            logging.info("✅ mcpgateway.translate process terminated cleanly")
        except subprocess.TimeoutExpired:
            logging.warning("⚠️  mcpgateway.translate didn't terminate in time, killing it")
            _translate_proc.kill()
            _translate_proc.wait()

    # Close log file if open
    if _translate_log_file:
        _translate_log_file.close()
        _translate_log_file = None

    # Stop docker container
    logging.info("🐋 Stopping Docker container")
    subprocess.run(MAKE_DOCKER_STOP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if cleanup_errors:
        logging.warning("⚠️  Cleanup completed with errors:")
        for err in cleanup_errors:
            logging.warning("  - %s", err)
    else:
        logging.info("✅ Cleanup complete")


# ───────────────────────────── Test steps ────────────────────────────────
cfg = SimpleNamespace(tail=10, verbose=False)  # populated in main()


def sh(cmd, desc):  # shorthand
    return run_shell(cmd, desc, tail=cfg.tail, verbose=cfg.verbose)


def step_1_setup_venv():
    sh(MAKE_VENV_CMD, "1️⃣  Create venv + install deps")


def step_2_pip_install():
    sh(["pip", "install", "."], "2️⃣  pip install .")


def step_3_docker_build():
    sh(MAKE_DOCKER_BUILD, "3️⃣  Build Docker image")


def step_4_docker_run():
    sh(MAKE_DOCKER_RUN, "4️⃣  Run Docker container (HTTPS)")

    # Build one token and reuse it for the health probes below.
    token = generate_jwt()
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Probe endpoints until they respond with 200.
    for ep in ("/health", "/ready", "/version"):
        full = f"https://localhost:{PORT_GATEWAY}{ep}"
        need_auth = os.getenv("AUTH_REQUIRED", "true").lower() == "true"
        headers = auth_headers if (ep == "/version" or need_auth) else None
        logging.info("🔍 Waiting for endpoint %s (auth: %s)", ep, bool(headers))
        if not wait_http_ok(full, 45, headers=headers):
            raise RuntimeError(f"Gateway endpoint {ep} not ready")
        logging.info("✅ Endpoint %s is ready", ep)

    logging.info("✅ Gateway /health /ready /version all OK")


def step_5_start_time_server(restart=False):
    global _translate_proc, _translate_log_file

    # Check if uvx is available
    try:
        uvx_check = subprocess.run(["uvx", "--version"], capture_output=True, text=True)
        if uvx_check.returncode == 0:
            logging.info("🔍 Found uvx version: %s", uvx_check.stdout.strip())
        else:
            logging.warning("⚠️  uvx not found or not working. This may cause issues.")
    except FileNotFoundError:
        logging.warning("⚠️  uvx not found. Please install uv (pip install uv) if the time server fails.")

    if port_open(PORT_TIME_SERVER):
        if restart:
            logging.info("🔄 Restarting process on port %d", PORT_TIME_SERVER)
            try:
                pid = int(subprocess.check_output(["lsof", "-ti", f"TCP:{PORT_TIME_SERVER}"], text=True).strip())
                logging.info("🔍 Found existing process PID: %d", pid)
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
            except Exception as e:
                logging.warning("Could not stop existing server: %s", e)
        else:
            logging.info("ℹ️  Re-using MCP-Time-Server on port %d", PORT_TIME_SERVER)
            return

    if not port_open(PORT_TIME_SERVER):
        log_section("Launching MCP-Time-Server", "⏰")
        logging.info("🚀 Command: %s", " ".join(shlex.quote(c) for c in TRANSLATE_CMD))

        # Create a log file for the time server output
        log_filename = f"translate_{int(time.time())}.log"
        _translate_log_file = open(log_filename, "w")
        logging.info("📝 Logging mcpgateway.translate output to: %s", log_filename)

        # Start the process directly
        _translate_proc = subprocess.Popen(TRANSLATE_CMD, stdout=_translate_log_file, stderr=subprocess.STDOUT, text=True, bufsize=1)

        logging.info("🔍 Started mcpgateway.translate process with PID: %d", _translate_proc.pid)

        # Wait for the server to start
        start_time = time.time()
        timeout = 30
        check_interval = 0.5

        while time.time() - start_time < timeout:
            # Check if process is still running
            exit_code = _translate_proc.poll()
            if exit_code is not None:
                # Process exited, read the log file
                _translate_log_file.close()
                with open(log_filename, "r") as f:
                    output = f.read()
                logging.error("❌ Time-Server process exited with code %d", exit_code)
                logging.error("📋 Process output:\n%s", output)
                raise RuntimeError(f"Time-Server exited with code {exit_code}. Check the logs above.")

            # Check if port is open
            if port_open(PORT_TIME_SERVER):
                elapsed = time.time() - start_time
                logging.info("✅ Time-Server is listening on port %d (took %.1fs)", PORT_TIME_SERVER, elapsed)

                # Give it a moment to fully initialize
                time.sleep(1)

                # Double-check it's still running
                if _translate_proc.poll() is None:
                    return
                else:
                    raise RuntimeError("Time-Server started but then immediately exited")

            # Log progress
            if int(time.time() - start_time) % 5 == 0:
                logging.info("⏳ Still waiting for Time-Server to start... (%.0fs elapsed)", time.time() - start_time)

            time.sleep(check_interval)

        # Timeout reached
        if _translate_proc.poll() is None:
            _translate_proc.terminate()
            _translate_proc.wait()

        _translate_log_file.close()
        with open(log_filename, "r") as f:
            output = f.read()
        logging.error("📋 Process output:\n%s", output)
        raise RuntimeError(f"Time-Server failed to start within {timeout}s")


def step_6_register_gateway() -> int:
    log_section("Registering gateway", "🛂")
    payload = {"name": "smoketest_time_server", "url": f"http://localhost:{PORT_TIME_SERVER}/sse"}
    logging.info("📤 Registering gateway with payload: %s", json.dumps(payload, indent=2))

    r = request("POST", "/gateways", json_data=payload)
    if r.status_code in (200, 201):
        gid = r.json()["id"]
        logging.info("✅ Gateway ID %s registered", gid)
        test_ctx.add_gateway(gid)
        return gid
    # 409 conflict → find existing
    if r.status_code == 409:
        logging.info("⚠️  Gateway already exists, fetching existing one")
        gateways = request("GET", "/gateways").json()
        gw = next((g for g in gateways if g["name"] == payload["name"]), None)
        if gw:
            logging.info("ℹ️  Gateway already present - using ID %s", gw["id"])
            test_ctx.add_gateway(gw["id"])
            return gw["id"]
        else:
            raise RuntimeError("Gateway conflict but not found in list")
    # other error
    msg = r.text
    try:
        msg = json.loads(msg)
    except Exception:
        pass
    raise RuntimeError(f"Gateway registration failed {r.status_code}: {msg}")


def step_7_verify_tools():
    logging.info("🔍 Fetching tool list")
    tools = request("GET", "/tools").json()
    tool_names = [t["name"] for t in tools]

    expected_tool = f"smoketest-time-server{settings.gateway_tool_name_separator}get-current-time"
    logging.info("📋 Found %d tools total", len(tool_names))
    logging.debug("📋 All tools: %s", json.dumps(tool_names, indent=2))

    if expected_tool not in tool_names:
        # Log similar tools to help debug
        similar = [t for t in tool_names if "time" in t.lower() or "smoketest" in t.lower()]
        if similar:
            logging.error("❌ Expected tool not found. Similar tools: %s", similar)
        raise AssertionError(f"{expected_tool} not found in tools list")

    logging.info("✅ Tool '%s' visible in /tools", expected_tool)


def step_8_invoke_tool():
    log_section("Invoking remote tool", "🔧")
    body = {"jsonrpc": "2.0", "id": 1, "method": f"smoketest-time-server{settings.gateway_tool_name_separator}get-current-time", "params": {"timezone": "Europe/Dublin"}}
    logging.info("📤 RPC request: %s", json.dumps(body, indent=2))

    j = request("POST", "/rpc", json_data=body).json()
    logging.info("📥 RPC response: %s", json.dumps(j, indent=2))

    if "error" in j:
        raise RuntimeError(f"RPC error: {j['error']}")

    result = j.get("result", j)
    if "content" not in result:
        raise RuntimeError(f"Missing 'content' in tool response. Got: {result}")

    content = result["content"]
    if not content or not isinstance(content, list):
        raise RuntimeError(f"Invalid content format. Expected list, got: {type(content)}")

    text = content[0].get("text", "")
    if not text:
        raise RuntimeError(f"No text in content. Content: {content}")

    if "datetime" not in text:
        raise RuntimeError(f"Expected 'datetime' in response, got: {text}")

    logging.info("✅ Tool invocation returned time: %s", text[:100])


def step_9_version_health():
    log_section("Final health check", "🏥")

    health_resp = request("GET", "/health").json()
    logging.info("📥 Health response: %s", json.dumps(health_resp, indent=2))
    health = health_resp.get("status", "").lower()
    assert health in ("ok", "healthy"), f"Unexpected health status: {health}"

    ver_resp = request("GET", "/version").json()
    logging.info("📥 Version response: %s", json.dumps(ver_resp, indent=2))
    ver = ver_resp.get("app", {}).get("name", "Unknown")
    logging.info("✅ Health OK - app %s", ver)


def step_10_cleanup_gateway(gid: int | None = None):
    log_section("Cleanup gateway registration", "🧹")

    if gid is None:
        logging.warning("🧹  No gateway ID; nothing to delete")
        return

    logging.info("🗑️  Deleting gateway ID: %s", gid)
    request("DELETE", f"/gateways/{gid}")

    # Verify it's gone
    gateways = request("GET", "/gateways").json()
    if any(g["id"] == gid for g in gateways):
        raise RuntimeError(f"Gateway {gid} still exists after deletion")

    logging.info("✅ Gateway deleted successfully")


# ===== NEW PHASE 1 TEST STEPS =====


def step_11_enhanced_tool_testing():
    """Enhanced tool testing with multiple scenarios"""
    log_section("Enhanced Tool Testing", "🔧")

    # Test 1: Multiple tool invocations in sequence
    logging.info("📋 Test: Multiple tool invocations in sequence")
    for tz in ["Europe/London", "America/New_York", "Asia/Tokyo"]:
        body = {"jsonrpc": "2.0", "id": f"seq-{tz}", "method": f"smoketest-time-server{settings.gateway_tool_name_separator}get-current-time", "params": {"timezone": tz}}
        r = request("POST", "/rpc", json_data=body)
        assert r.status_code == 200, f"Failed to get time for {tz}"
        test_ctx.record_test(f"tool_invoke_{tz}", True)

    # Test 2: Tool with invalid parameters
    logging.info("📋 Test: Tool with invalid parameters")
    body = {"jsonrpc": "2.0", "id": "invalid-params", "method": f"smoketest-time-server{settings.gateway_tool_name_separator}get-current-time", "params": {"invalid_param": "test"}}
    r = request("POST", "/rpc", json_data=body)
    if r.status_code != 200:
        test_ctx.record_test("tool_invalid_params", True)
    else:
        # Check if response contains error
        resp = r.json()
        test_ctx.record_test("tool_invalid_params", "error" in resp)

    # Test 3: Tool discovery filtering
    logging.info("📋 Test: Tool discovery with filtering")
    tools = request("GET", "/tools").json()
    time_tools = [t for t in tools if "time" in t["name"].lower()]
    test_ctx.record_test("tool_discovery_filter", len(time_tools) > 0)

    # Test 4: Get specific tool details
    logging.info("📋 Test: Get specific tool details")
    if tools:
        tool_id = tools[0]["id"]
        r = request("GET", f"/tools/{tool_id}")
        test_ctx.record_test("tool_details", r.status_code == 200)
        if r.status_code == 200:
            details = r.json()
            # Verify tool has required fields
            required_fields = ["id", "name", "description"]
            has_fields = all(field in details for field in required_fields)
            test_ctx.record_test("tool_schema_validation", has_fields)

    logging.info("✅ Enhanced tool testing completed")


def step_12_resource_management():
    """Test resource creation, retrieval, update, and deletion"""
    log_section("Resource Management Testing", "📚")

    # Test 1: Create Markdown resource
    logging.info("📋 Test: Create Markdown resource")
    md_resource = {
        "uri": f"test/readme_{uuid.uuid4().hex[:8]}",
        "name": "Test README",
        "description": "Test markdown resource",
        "mimeType": "text/markdown",
        "content": "# Test Resource\n\nThis is a test markdown resource.\n\n## Features\n- Test item 1\n- Test item 2",
    }
    r = request("POST", "/resources", json_data=md_resource)
    if r.status_code in (200, 201):
        test_ctx.add_resource(md_resource["uri"])
        test_ctx.record_test("resource_create_markdown", True)
    else:
        test_ctx.record_test("resource_create_markdown", False, r.text)

    # Test 2: Create JSON resource
    logging.info("📋 Test: Create JSON resource")
    json_resource = {
        "uri": f"config/test_{uuid.uuid4().hex[:8]}",
        "name": "Test Config",
        "description": "Test JSON configuration",
        "mimeType": "application/json",
        "content": json.dumps({"version": "1.0.0", "debug": True, "features": ["test1", "test2"]}),
    }
    r = request("POST", "/resources", json_data=json_resource)
    if r.status_code in (200, 201):
        test_ctx.add_resource(json_resource["uri"])
        test_ctx.record_test("resource_create_json", True)
    else:
        test_ctx.record_test("resource_create_json", False, r.text)

    # Test 3: Create plain text resource
    logging.info("📋 Test: Create plain text resource")
    text_resource = {"uri": f"docs/notes_{uuid.uuid4().hex[:8]}", "name": "Test Notes", "description": "Plain text notes", "mimeType": "text/plain", "content": "These are test notes.\nLine 2\nLine 3"}
    r = request("POST", "/resources", json_data=text_resource)
    if r.status_code in (200, 201):
        test_ctx.add_resource(text_resource["uri"])
        test_ctx.record_test("resource_create_text", True)
    else:
        test_ctx.record_test("resource_create_text", False, r.text)

    # Test 4: List resources
    logging.info("📋 Test: List resources")
    r = request("GET", "/resources")
    if r.status_code == 200:
        resources = r.json()
        test_ctx.record_test("resource_list", len(resources) >= 3)
    else:
        test_ctx.record_test("resource_list", False, r.text)

    # Test 5: Get resource by URI (content)
    if test_ctx.resources:
        logging.info("📋 Test: Get resource content")
        # Note: The endpoint might be /resources/{uri}/content or similar
        # Adjust based on actual API
        test_uri = test_ctx.resources[0]
        r = request("GET", f"/resources/{test_uri}")
        test_ctx.record_test("resource_get_content", r.status_code == 200)

    # Test 6: Update resource
    if test_ctx.resources:
        logging.info("📋 Test: Update resource")
        update_data = {"content": "# Updated Content\n\nThis content has been updated."}
        r = request("PUT", f"/resources/{test_ctx.resources[0]}", json_data=update_data)
        test_ctx.record_test("resource_update", r.status_code in (200, 204))

    # Test 7: Delete resource
    if len(test_ctx.resources) > 1:
        logging.info("📋 Test: Delete resource")
        delete_uri = test_ctx.resources.pop()  # Remove from tracking
        r = request("DELETE", f"/resources/{delete_uri}")
        test_ctx.record_test("resource_delete", r.status_code in (200, 204))

    logging.info("✅ Resource management testing completed")


def step_13_prompt_management():
    """Test prompt creation with and without arguments"""
    log_section("Prompt Management Testing", "💬")

    # Test 1: Create simple prompt without arguments
    logging.info("📋 Test: Create simple prompt")
    simple_prompt = {"name": f"greeting_{uuid.uuid4().hex[:8]}", "description": "Simple greeting prompt", "template": "Hello! Welcome to the ContextForge. How can I help you today?", "arguments": []}
    r = request("POST", "/prompts", json_data=simple_prompt)
    if r.status_code in (200, 201):
        test_ctx.add_prompt(simple_prompt["name"])
        test_ctx.record_test("prompt_create_simple", True)
    else:
        test_ctx.record_test("prompt_create_simple", False, r.text)

    # Test 2: Create prompt with arguments
    logging.info("📋 Test: Create prompt with arguments")
    template_prompt = {
        "name": f"code_review_{uuid.uuid4().hex[:8]}",
        "description": "Code review prompt with parameters",
        "template": "Please review the following {{ language }} code:\n\n```{{ language }}\n{{ code }}\n```\n\nFocus areas: {{ focus_areas }}",
        "arguments": [
            {"name": "language", "description": "Programming language", "required": True},
            {"name": "code", "description": "Code to review", "required": True},
            {"name": "focus_areas", "description": "Areas to focus on", "required": False},
        ],
    }
    r = request("POST", "/prompts", json_data=template_prompt)
    if r.status_code in (200, 201):
        test_ctx.add_prompt(template_prompt["name"])
        test_ctx.record_test("prompt_create_template", True)
    else:
        test_ctx.record_test("prompt_create_template", False, r.text)

    # Test 3: List prompts
    logging.info("📋 Test: List prompts")
    r = request("GET", "/prompts")
    if r.status_code == 200:
        prompts = r.json()
        test_ctx.record_test("prompt_list", len(prompts) >= 2)
    else:
        test_ctx.record_test("prompt_list", False, r.text)

    # Test 4: Execute prompt with parameters
    if len(test_ctx.prompts) > 1:
        logging.info("📋 Test: Execute prompt with parameters")
        prompt_name = test_ctx.prompts[1]  # Use template prompt
        params = {"language": "python", "code": "def hello():\n    print('Hello, World!')", "focus_areas": "code style and best practices"}
        r = request("POST", f"/prompts/{prompt_name}", json_data=params)
        if r.status_code == 200:
            result = r.json()
            # Check if messages array exists
            test_ctx.record_test("prompt_execute", "messages" in result)
        else:
            test_ctx.record_test("prompt_execute", False, r.text)

    # Test 5: Execute prompt without parameters
    if test_ctx.prompts:
        logging.info("📋 Test: Execute simple prompt")
        r = request("POST", f"/prompts/{test_ctx.prompts[0]}", json_data={})
        test_ctx.record_test("prompt_execute_simple", r.status_code == 200)

    # Test 6: Delete prompt
    if len(test_ctx.prompts) > 1:
        logging.info("📋 Test: Delete prompt")
        delete_name = test_ctx.prompts.pop()
        r = request("DELETE", f"/prompts/{delete_name}")
        test_ctx.record_test("prompt_delete", r.status_code in (200, 204))

    logging.info("✅ Prompt management testing completed")


def step_14_error_handling_validation():
    """Test error handling and input validation"""
    log_section("Error Handling & Validation Testing", "🛡️")

    # Test 1: XSS in tool name
    logging.info("📋 Test: XSS prevention in tool names")
    xss_tool = {"name": "<script>alert('xss')</script>", "url": "https://example.com/api", "description": "Test XSS", "integrationType": "REST", "requestType": "GET"}
    r = request("POST", "/tools", json_data=xss_tool)
    test_ctx.record_test("validation_xss_tool_name", r.status_code in (400, 422))

    # Test 2: SQL injection pattern
    logging.info("📋 Test: SQL injection prevention")
    sql_inject = {"name": "tool'; DROP TABLE tools; --", "url": "https://example.com", "description": "Test SQL injection", "integrationType": "REST", "requestType": "GET"}
    r = request("POST", "/tools", json_data=sql_inject)
    test_ctx.record_test("validation_sql_injection", r.status_code in (400, 422))

    # Test 3: Invalid URL scheme
    logging.info("📋 Test: Invalid URL scheme")
    invalid_url = {"name": f"test_tool_{uuid.uuid4().hex[:8]}", "url": "javascript:alert(1)", "description": "Test invalid URL", "integrationType": "REST", "requestType": "GET"}
    r = request("POST", "/tools", json_data=invalid_url)
    test_ctx.record_test("validation_invalid_url", r.status_code in (400, 422))

    # Test 4: Directory traversal in resource URI
    logging.info("📋 Test: Directory traversal prevention")
    traversal_resource = {"uri": "../../etc/passwd", "name": "Test traversal", "content": "test"}
    r = request("POST", "/resources", json_data=traversal_resource)
    test_ctx.record_test("validation_directory_traversal", r.status_code in (400, 422, 500))

    # Test 5: Name too long (255+ chars)
    logging.info("📋 Test: Name length validation")
    long_name = {"name": "a" * 300, "url": "https://example.com", "description": "Test long name", "integrationType": "REST", "requestType": "GET"}
    r = request("POST", "/tools", json_data=long_name)
    test_ctx.record_test("validation_name_too_long", r.status_code in (400, 422))

    # Test 6: Empty required fields
    logging.info("📋 Test: Empty required fields")
    empty_fields = {"name": "", "url": "https://example.com"}
    r = request("POST", "/tools", json_data=empty_fields)
    test_ctx.record_test("validation_empty_required", r.status_code in (400, 422))

    # Test 7: Whitespace only in name
    logging.info("📋 Test: Whitespace-only validation")
    whitespace_only = {"name": "   ", "url": "https://example.com", "description": "Test whitespace"}
    r = request("POST", "/tools", json_data=whitespace_only)
    test_ctx.record_test("validation_whitespace_only", r.status_code in (400, 422))

    # Test 8: Invalid JSON-RPC request
    logging.info("📋 Test: Malformed JSON-RPC request")
    malformed_rpc = {"jsonrpc": "1.0", "method": "test", "id": "test"}  # Wrong version
    r = request("POST", "/rpc", json_data=malformed_rpc)
    test_ctx.record_test("validation_invalid_jsonrpc", r.status_code != 200 or "error" in r.json())

    # Test 9: Tool not found
    logging.info("📋 Test: Tool not found error")
    r = request("GET", f"/tools/{uuid.uuid4()}")
    test_ctx.record_test("error_tool_not_found", r.status_code == 404)

    # Test 10: Gateway not found
    logging.info("📋 Test: Gateway not found error")
    r = request("GET", "/gateways/99999")
    test_ctx.record_test("error_gateway_not_found", r.status_code == 404)

    logging.info("✅ Error handling & validation testing completed")


def step_15_virtual_server_management():
    """Test virtual server creation and management"""
    log_section("Virtual Server Management", "🖥️")

    # Get available tools first
    tools = request("GET", "/tools").json()
    if not tools:
        logging.warning("⚠️  No tools available for virtual server testing")
        test_ctx.record_test("virtual_server_skipped", False, "No tools available")
        return

    # Select time-related tools
    time_tools = [t for t in tools if "time" in t["name"].lower()]
    if not time_tools:
        time_tools = tools[:2]  # Just take first 2 tools

    tool_ids = [t["id"] for t in time_tools[:3]]  # Max 3 tools

    # Test 1: Create virtual server
    logging.info("📋 Test: Create virtual server")
    virtual_server = {"name": f"time_utils_{uuid.uuid4().hex[:8]}", "description": "Time utilities virtual server", "associatedTools": tool_ids}
    r = request("POST", "/servers", json_data=virtual_server)
    if r.status_code in (200, 201):
        server_data = r.json()
        server_id = server_data["id"]
        test_ctx.add_virtual_server(server_id)
        test_ctx.record_test("virtual_server_create", True)

        # Test 2: List virtual servers
        logging.info("📋 Test: List virtual servers")
        r = request("GET", "/servers")
        if r.status_code == 200:
            servers = r.json()
            test_ctx.record_test("virtual_server_list", len(servers) >= 1)
        else:
            test_ctx.record_test("virtual_server_list", False, r.text)

        # Test 3: Get specific virtual server
        logging.info("📋 Test: Get virtual server details")
        r = request("GET", f"/servers/{server_id}")
        test_ctx.record_test("virtual_server_get", r.status_code == 200)

        # Test 4: Test SSE endpoint (brief connection test)
        logging.info("📋 Test: Virtual server SSE endpoint")
        try:
            # Just test that the endpoint exists and responds
            # Third-Party
            import requests

            token = generate_jwt()
            url = f"https://localhost:{PORT_GATEWAY}/servers/{server_id}/sse"
            # Use stream=True to test SSE connection
            with requests.get(url, headers={"Authorization": f"Bearer {token}"}, verify=False, stream=True, timeout=2) as r:
                test_ctx.record_test("virtual_server_sse", r.status_code == 200)
        except requests.Timeout:
            # Timeout is OK for SSE - it means connection was established
            test_ctx.record_test("virtual_server_sse", True)
        except Exception as e:
            test_ctx.record_test("virtual_server_sse", False, str(e))

        # Test 5: Update virtual server
        logging.info("📋 Test: Update virtual server")
        update_data = {"description": "Updated time utilities server"}
        r = request("PUT", f"/servers/{server_id}", json_data=update_data)
        test_ctx.record_test("virtual_server_update", r.status_code in (200, 204))

    else:
        test_ctx.record_test("virtual_server_create", False, r.text)

    logging.info("✅ Virtual server management testing completed")


def step_16_test_summary():
    """Print test summary"""
    log_section("Test Summary", "📊")

    summary = test_ctx.summary()
    logging.info(summary)

    # Show failed tests
    failed_tests = [name for name, passed in test_ctx.test_results.items() if not passed]
    if failed_tests:
        logging.warning("\n❌ Failed tests:")
        for test_name in failed_tests:
            error = test_ctx.error_messages.get(test_name, "No error message")
            logging.warning("  - %s: %s", test_name, error)
    else:
        logging.info("\n✅ All additional tests passed!")

    # Show entity counts
    logging.info("\n📦 Created entities:")
    logging.info("  - Gateways: %d", len(test_ctx.gateways))
    logging.info("  - Resources: %d", len(test_ctx.resources))
    logging.info("  - Prompts: %d", len(test_ctx.prompts))
    logging.info("  - Tools: %d", len(test_ctx.tools))
    logging.info("  - Virtual Servers: %d", len(test_ctx.virtual_servers))


# ───────────────────────────── Step registry ─────────────────────────────
StepFunc = Callable[..., None]
STEPS: List[Tuple[str, StepFunc]] = [
    ("setup_venv", step_1_setup_venv),
    ("pip_install", step_2_pip_install),
    ("docker_build", step_3_docker_build),
    ("docker_run", step_4_docker_run),
    ("start_time_server", step_5_start_time_server),
    ("register_gateway", step_6_register_gateway),
    ("verify_tools", step_7_verify_tools),
    ("invoke_tool", step_8_invoke_tool),
    ("version_health", step_9_version_health),
    # New Phase 1 tests
    ("enhanced_tool_testing", step_11_enhanced_tool_testing),
    ("resource_management", step_12_resource_management),
    ("prompt_management", step_13_prompt_management),
    ("error_handling_validation", step_14_error_handling_validation),
    ("virtual_server_management", step_15_virtual_server_management),
    ("test_summary", step_16_test_summary),
    ("cleanup_gateway", step_10_cleanup_gateway),
]


# ──────────────────────────────── Main ───────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="ContextForge smoke-test")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--tail", type=int, default=10, help="Tail window (default 10)")
    ap.add_argument("--start-step", type=int, default=1)
    ap.add_argument("--end-step", type=int)
    ap.add_argument("--only-steps", help="Comma separated indices (1-based)")
    ap.add_argument("--cleanup-only", action="store_true")
    ap.add_argument("--restart-time-server", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg.tail = args.tail
    cfg.verbose = args.verbose  # make available in helpers

    if args.cleanup_only:
        cleanup()
        return

    # Select steps
    sel: List[Tuple[str, StepFunc]]
    if args.only_steps:
        idx = [int(i) for i in args.only_steps.split(",")]
        sel = [STEPS[i - 1] for i in idx]
    else:
        sel = STEPS[args.start_step - 1 : (args.end_step or len(STEPS))]

    gid = None
    failed = False

    try:
        logging.info("🚀 Starting ContextForge smoke test")
        logging.info("📋 Environment:")
        logging.info("  - Gateway port: %d", PORT_GATEWAY)
        logging.info("  - Time server port: %d", PORT_TIME_SERVER)
        logging.info("  - Docker container: %s", DOCKER_CONTAINER)
        logging.info("  - Selected steps: %s", [s[0] for s in sel])

        for no, (name, fn) in enumerate(sel, 1):
            logging.info("\n🔸 Step %s/%s - %s", no, len(sel), name)
            if name == "start_time_server":
                fn(args.restart_time_server)  # type: ignore[arg-type]
            elif name == "register_gateway":
                gid = fn()  # type: ignore[func-returns-value]
            elif name == "cleanup_gateway":
                if gid is None:
                    logging.warning("🧹  Skipping gateway-deletion: no gateway was ever registered")
                else:
                    fn(gid)  # type: ignore[arg-type]
            else:
                fn()
        logging.info("\n✅✅  ALL STEPS PASSED")
    except Exception as e:
        failed = True
        logging.error("❌  Failure: %s", e, exc_info=args.verbose)
        logging.error("\n💡 Troubleshooting tips:")
        logging.error("  - Check if uvx is installed: uvx --version")
        logging.error("  - Check if port %d is already in use: lsof -i :%d", PORT_TIME_SERVER, PORT_TIME_SERVER)
        logging.error("  - Look for translate_*.log files for detailed output")
        logging.error("  - Try running with -v for verbose output")

    if not failed:
        cleanup()
    else:
        logging.warning("⚠️  Skipping cleanup due to failure. Run with --cleanup-only to clean up manually.")
        # Still show test summary even on failure
        if any(name == "test_summary" for name, _ in sel):
            step_16_test_summary()


if __name__ == "__main__":
    main()
