#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
# Author : Mihai Criveti
# Description: 🛠️ MCP Gateway Smoke-Test Utility

This script verifies a full install + runtime setup of the MCP Gateway:
- Creates a virtual environment and installs dependencies.
- Builds and runs the Docker HTTPS container.
- Starts the MCP Time Server via npx supergateway.
- Verifies /health, /ready, /version before registering the gateway.
- Federates the time server as a gateway, verifies its tool list.
- Invokes the remote tool via /rpc and checks the result.
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
from typing import Callable, List, Tuple

# First-Party
from mcpgateway.config import settings

# ───────────────────────── Ports / constants ────────────────────────────
PORT_GATEWAY = 4444  # HTTPS container
PORT_TIME_SERVER = 8002  # supergateway
DOCKER_CONTAINER = "mcpgateway"

MAKE_VENV_CMD = ["make", "venv", "install", "install-dev"]
MAKE_DOCKER_BUILD = ["make", "docker"]
MAKE_DOCKER_RUN = ["make", "docker-run-ssl-host"]
MAKE_DOCKER_STOP = ["make", "docker-stop"]

SUPERGW_CMD = [
    "npx",
    "-y",
    "supergateway",
    "--stdio",
    "uvx mcp-server-time --local-timezone=Europe/Dublin",
    "--port",
    str(PORT_TIME_SERVER),
]


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
            header = f"{spinner} {desc} (elapsed {time.time()-start:4.0f}s)"
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
        sys.stdout.write(f"\x1b[{min(len(tail_buf)+2, tail+2)}F\x1b[J")
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
    user = os.getenv("BASIC_AUTH_USER", "admin")
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


def request(method: str, path: str, *, json_data=None, **kw):
    # Third-Party
    import requests

    token = generate_jwt()
    kw.setdefault("headers", {})["Authorization"] = f"Bearer {token}"
    kw["verify"] = False
    url = f"https://localhost:{PORT_GATEWAY}{path}"
    t0 = time.time()
    resp = requests.request(method, url, json=json_data, **kw)
    ms = (time.time() - t0) * 1000
    logging.info("→ %s %s %s %.0f ms", method.upper(), path, resp.status_code, ms)
    logging.debug("  ↳ response: %s", resp.text[:400])
    return resp


# ───────────────────────────── Cleanup logic ─────────────────────────────
_supergw_proc: subprocess.Popen | None = None
_supergw_log_file = None


def cleanup():
    log_section("Cleanup", "🧹")
    global _supergw_proc, _supergw_log_file

    # Clean up the supergateway process
    if _supergw_proc and _supergw_proc.poll() is None:
        logging.info("🔄 Terminating supergateway process (PID: %d)", _supergw_proc.pid)
        _supergw_proc.terminate()
        try:
            _supergw_proc.wait(timeout=5)
            logging.info("✅ Supergateway process terminated cleanly")
        except subprocess.TimeoutExpired:
            logging.warning("⚠️  Supergateway didn't terminate in time, killing it")
            _supergw_proc.kill()
            _supergw_proc.wait()

    # Close log file if open
    if _supergw_log_file:
        _supergw_log_file.close()
        _supergw_log_file = None

    # Stop docker container
    logging.info("🐋 Stopping Docker container")
    subprocess.run(MAKE_DOCKER_STOP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    global _supergw_proc, _supergw_log_file

    # Check if npx is available
    try:
        npx_version = subprocess.check_output(["npx", "--version"], text=True, stderr=subprocess.DEVNULL).strip()
        logging.info("🔍 Found npx version: %s", npx_version)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("npx not found. Please install Node.js and npm.")

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
        logging.info("🚀 Command: %s", " ".join(shlex.quote(c) for c in SUPERGW_CMD))

        # Create a log file for the time server output
        log_filename = f"supergateway_{int(time.time())}.log"
        _supergw_log_file = open(log_filename, "w")
        logging.info("📝 Logging supergateway output to: %s", log_filename)

        # Start the process with output capture
        _supergw_proc = subprocess.Popen(
            SUPERGW_CMD,
            stdout=_supergw_log_file,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        logging.info("🔍 Started supergateway process with PID: %d", _supergw_proc.pid)

        # Wait for the server to start
        start_time = time.time()
        timeout = 30
        check_interval = 0.5

        while time.time() - start_time < timeout:
            # Check if process is still running
            exit_code = _supergw_proc.poll()
            if exit_code is not None:
                # Process exited, read the log file
                _supergw_log_file.close()
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
                if _supergw_proc.poll() is None:
                    return
                else:
                    raise RuntimeError("Time-Server started but then immediately exited")

            # Log progress
            if int(time.time() - start_time) % 5 == 0:
                logging.info("⏳ Still waiting for Time-Server to start... (%.0fs elapsed)", time.time() - start_time)

            time.sleep(check_interval)

        # Timeout reached
        if _supergw_proc.poll() is None:
            _supergw_proc.terminate()
            _supergw_proc.wait()

        _supergw_log_file.close()
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
        return gid
    # 409 conflict → find existing
    if r.status_code == 409:
        logging.info("⚠️  Gateway already exists, fetching existing one")
        gateways = request("GET", "/gateways").json()
        gw = next((g for g in gateways if g["name"] == payload["name"]), None)
        if gw:
            logging.info("ℹ️  Gateway already present - using ID %s", gw["id"])
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
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": f"smoketest-time-server{settings.gateway_tool_name_separator}get-current-time",
        "params": {"timezone": "Europe/Dublin"}
    }
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
    ("cleanup_gateway", step_10_cleanup_gateway),
]


# ──────────────────────────────── Main ───────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="MCP Gateway smoke-test")
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
        logging.info("🚀 Starting MCP Gateway smoke test")
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
        logging.error("  - Check if npx is installed: npx --version")
        logging.error("  - Check if uvx is installed: uvx --version")
        logging.error("  - Check if port %d is already in use: lsof -i :%d", PORT_TIME_SERVER, PORT_TIME_SERVER)
        logging.error("  - Look for supergateway_*.log files for detailed output")
        logging.error("  - Try running with -v for verbose output")

    if not failed:
        cleanup()
    else:
        logging.warning("⚠️  Skipping cleanup due to failure. Run with --cleanup-only to clean up manually.")


if __name__ == "__main__":
    main()
