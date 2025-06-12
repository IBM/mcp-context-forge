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

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import shlex
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from collections import deque
from types import SimpleNamespace
from typing import Callable, List, Tuple

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
    "uvenv run mcp_server_time -- --local-timezone=Europe/Dublin",
    "--port",
    str(PORT_TIME_SERVER),
]


# ─────────────────────── Helper: pretty sections ────────────────────────
def log_section(title: str, emoji: str = "⚙️"):
    logging.info("\n%s  %s\n%s", emoji, title, "─" * (len(title) + 4))


# ───────────────────────── Tail‑N streaming runner ───────────────────────
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
    logging.info("%s – %s", status, desc)
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


def wait_http_ok(url: str, timeout: int = 30) -> bool:
    import requests

    end = time.time() + timeout
    while time.time() < end:
        try:
            if requests.get(url, timeout=2, verify=False).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


# ───────────────────────────── Requests wrapper ──────────────────────────
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def generate_jwt() -> str:
    return (
        subprocess.check_output(
            ["docker", "exec", DOCKER_CONTAINER, "python3", "-m", "mcpgateway.utils.create_jwt_token", "--username", "admin", "--exp", "300", "--secret", "my-test-key"],
            text=True,
        )
        .strip()
        .strip('"')
    )


def request(method: str, path: str, *, json_data=None, **kw):
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


def cleanup():
    log_section("Cleanup", "🧹")
    global _supergw_proc
    if _supergw_proc and _supergw_proc.poll() is None:
        _supergw_proc.terminate()
        try:
            _supergw_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _supergw_proc.kill()
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
    # wait until gateway exposes the basic endpoints
    for ep in ("/health", "/ready", "/version"):
        full = f"https://localhost:{PORT_GATEWAY}{ep}"
        if not wait_http_ok(full, 45):
            raise RuntimeError(f"Gateway endpoint {ep} not ready")
    logging.info("✅ Gateway /health /ready /version all OK")


def step_5_start_time_server(restart=False):
    global _supergw_proc
    if port_open(PORT_TIME_SERVER):
        if restart:
            logging.info("🔄 Restarting process on port %d", PORT_TIME_SERVER)
            try:
                pid = int(subprocess.check_output(["lsof", "-ti", f"TCP:{PORT_TIME_SERVER}"], text=True).strip())
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
            except Exception as e:
                logging.warning("Could not stop existing server: %s", e)
        else:
            logging.info("ℹ️  Re‑using MCP‑Time‑Server on port %d", PORT_TIME_SERVER)
    if not port_open(PORT_TIME_SERVER):
        log_section("Launching MCP‑Time‑Server", "⏰")
        _supergw_proc = subprocess.Popen(SUPERGW_CMD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            if port_open(PORT_TIME_SERVER):
                break
            if _supergw_proc.poll() is not None:
                raise RuntimeError("Time‑Server exited")
            time.sleep(1)


def step_6_register_gateway() -> int:
    log_section("Registering gateway", "🛂")
    payload = {"name": "smoketest_time_server", "url": f"http://localhost:{PORT_TIME_SERVER}/sse"}
    r = request("POST", "/gateways", json_data=payload)
    if r.status_code in (200, 201):
        gid = r.json()["id"]
        logging.info("✅ Gateway ID %s registered", gid)
        return gid
    # 409 conflict → find existing
    if r.status_code == 409:
        gw = next(g for g in request("GET", "/gateways").json() if g["name"] == payload["name"])
        logging.info("ℹ️  Gateway already present – using ID %s", gw["id"])
        return gw["id"]
    # other error
    msg = r.text
    try:
        msg = json.loads(msg)
    except Exception:
        pass
    raise RuntimeError(f"Gateway registration failed {r.status_code}: {msg}")


def step_7_verify_tools():
    names = [t["name"] for t in request("GET", "/tools").json()]
    assert "get_current_time" in names, "get_current_time absent"
    logging.info("✅ Tool visible in /tools")


def step_8_invoke_tool():
    body = {"jsonrpc": "2.0", "id": 1, "method": "get_current_time", "params": {"timezone": "Europe/Dublin"}}
    j = request("POST", "/rpc", json_data=body).json()

    if "error" in j:
        raise RuntimeError(j["error"])

    result = j.get("result", j)
    if "content" not in result:
        raise RuntimeError("Missing 'content' in tool response")

    text = result["content"][0]["text"]
    assert "datetime" in text, "datetime missing"
    logging.info("✅ Tool invocation returned time")



def step_9_version_health():
    health = request("GET", "/health").json()["status"].lower()
    assert health in ("ok", "healthy"), f"Unexpected health status: {health}"
    ver = request("GET", "/version").json()["app"]["name"]
    logging.info("✅ Health OK – app %s", ver)



def step_10_cleanup_gateway(gid: int):
    request("DELETE", f"/gateways/{gid}")
    assert all(g["id"] != gid for g in request("GET", "/gateways").json())
    logging.info("✅ Gateway deleted")


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
    ap = argparse.ArgumentParser(description="MCP Gateway smoke‑test")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--tail", type=int, default=10, help="Tail window (default 10)")
    ap.add_argument("--start-step", type=int, default=1)
    ap.add_argument("--end-step", type=int)
    ap.add_argument("--only-steps", help="Comma separated indices (1‑based)")
    ap.add_argument("--cleanup-only", action="store_true")
    ap.add_argument("--restart-time-server", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
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
        for no, (name, fn) in enumerate(sel, 1):
            logging.info("\n🔸 Step %s/%s — %s", no, len(sel), name)
            if name == "start_time_server":
                fn(args.restart_time_server)  # type: ignore[arg-type]
            elif name == "register_gateway":
                gid = fn()  # type: ignore[func-returns-value]
            elif name == "cleanup_gateway" and gid is not None:
                fn(gid)  # type: ignore[arg-type]
            else:
                fn()
        logging.info("\n✅✅  ALL STEPS PASSED")
    except Exception as e:
        failed = True
        logging.error("❌  Failure: %s", e, exc_info=args.verbose)

    if not failed:
        cleanup()



if __name__ == "__main__":
    main()
