# -*- coding: utf-8 -*-
"""version.py - diagnostics endpoint (HTML + JSON)

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

A FastAPI router that mounts at /version and returns either:
- JSON - machine-readable diagnostics payload
- HTML - a lightweight dashboard when the client requests text/html or ?format=html

Features:
- Cross-platform system metrics (Windows/macOS/Linux), with fallbacks where APIs are unavailable
- Optional dependencies: psutil (for richer metrics) and redis.asyncio (for Redis health); omitted gracefully if absent
- Authentication enforcement via `require_auth`; unauthenticated browsers see login form, API clients get JSON 401
- Redacted environment variables, sanitized DB/Redis URLs, Git commit detection
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
import json
import os
import platform
import socket
import subprocess
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import engine
from mcpgateway.utils.verify_credentials import require_auth

# Third-Party
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

# Optional runtime dependencies
try:
    # Third-Party
    import psutil  # optional for enhanced metrics
except ImportError:
    psutil = None  # type: ignore

try:
    # Third-Party
    import redis.asyncio as aioredis  # optional Redis health check

    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore
    REDIS_AVAILABLE = False

# Globals

START_TIME = time.time()
HOSTNAME = socket.gethostname()
LOGIN_PATH = "/login"
router = APIRouter(tags=["meta"])


def _is_secret(key: str) -> bool:
    """
    Identify if an environment variable key likely represents a secret.

    Parameters:
        key (str): The environment variable name.

    Returns:
        bool: True if the key contains secret-looking keywords, False otherwise.
    """
    return any(tok in key.upper() for tok in ("SECRET", "TOKEN", "PASS", "KEY"))


def _public_env() -> Dict[str, str]:
    """
    Collect environment variables excluding those that look secret.

    Returns:
        Dict[str, str]: A map of environment variable names to values.
    """
    return {k: v for k, v in os.environ.items() if not _is_secret(k)}


def _git_revision() -> Optional[str]:
    """
    Retrieve the current Git revision (short) if available.

    Returns:
        Optional[str]: The Git commit hash prefix or None if unavailable.
    """
    rev = os.getenv("GIT_COMMIT")
    if rev:
        return rev[:9]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return None


def _sanitize_url(url: Optional[str]) -> Optional[str]:
    """
    Redact credentials from a URL for safe display.

    Parameters:
        url (Optional[str]): The URL to sanitize.

    Returns:
        Optional[str]: The sanitized URL or None.
    """
    if not url:
        return None
    parts = urlsplit(url)
    if parts.password:
        netloc = f"{parts.username}@{parts.hostname}{':' + str(parts.port) if parts.port else ''}"
        parts = parts._replace(netloc=netloc)
    return urlunsplit(parts)


def _database_version() -> tuple[str, bool]:
    """
    Query the database server version.

    Returns:
        tuple[str, bool]: (version string or error message, reachable flag).
    """
    dialect = engine.dialect.name
    stmts = {
        "sqlite": "SELECT sqlite_version();",
        "postgresql": "SELECT current_setting('server_version');",
        "mysql": "SELECT version();",
    }
    stmt = stmts.get(dialect, "SELECT version();")
    try:
        with engine.connect() as conn:
            ver = conn.execute(text(stmt)).scalar()
            return str(ver), True
    except Exception as exc:
        return str(exc), False


def _system_metrics() -> Dict[str, Any]:
    """
    Gather system-wide and per-process metrics using psutil, falling back gracefully
    if psutil is not installed or certain APIs are unavailable.

    Returns:
        Dict[str, Any]: A dictionary containing:
            - boot_time (str): ISO-formatted system boot time.
            - cpu_percent (float): Total CPU utilization percentage.
            - cpu_count (int): Number of logical CPU cores.
            - cpu_freq_mhz (int | None): Current CPU frequency in MHz, or None if unavailable.
            - load_avg (tuple[float | None, float | None, float | None]):
                System load average over 1, 5, and 15 minutes, or (None, None, None)
                on platforms without getloadavg.
            - mem_total_mb (int): Total physical memory in megabytes.
            - mem_used_mb (int): Used physical memory in megabytes.
            - swap_total_mb (int): Total swap memory in megabytes.
            - swap_used_mb (int): Used swap memory in megabytes.
            - disk_total_gb (float): Total size of the root disk partition in gigabytes.
            - disk_used_gb (float): Used space of the root disk partition in gigabytes.
            - process (Dict[str, Any]): A nested dict with per-process metrics:
                * pid (int): Current process ID.
                * threads (int): Number of active threads.
                * rss_mb (float): Resident Set Size memory usage in megabytes.
                * vms_mb (float): Virtual Memory Size usage in megabytes.
                * open_fds (int | None): Number of open file descriptors, or None if unsupported.
                * proc_cpu_percent (float): CPU utilization percentage for this process.
        {}: Empty dict if psutil is not installed.
    """
    if not psutil:
        return {}

    # System memory and swap
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Load average (Unix); on Windows returns (None, None, None)
    try:
        load = tuple(round(x, 2) for x in os.getloadavg())
    except (AttributeError, OSError):
        load = (None, None, None)

    # CPU metrics
    freq = psutil.cpu_freq()
    cpu_pct = psutil.cpu_percent(interval=0.3)
    cpu_count = psutil.cpu_count(logical=True)

    # Process metrics
    proc = psutil.Process()
    try:
        open_fds = proc.num_fds()
    except Exception:
        open_fds = None
    proc_cpu_pct = proc.cpu_percent(interval=0.1)
    rss_mb = round(proc.memory_info().rss / 1_048_576, 2)
    vms_mb = round(proc.memory_info().vms / 1_048_576, 2)
    threads = proc.num_threads()
    pid = proc.pid

    # Disk usage for root partition (ensure str on Windows)
    root = os.getenv("SystemDrive", "C:\\") if os.name == "nt" else "/"
    disk = psutil.disk_usage(str(root))
    disk_total_gb = round(disk.total / 1_073_741_824, 2)
    disk_used_gb = round(disk.used / 1_073_741_824, 2)

    return {
        "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
        "cpu_percent": cpu_pct,
        "cpu_count": cpu_count,
        "cpu_freq_mhz": round(freq.current) if freq else None,
        "load_avg": load,
        "mem_total_mb": round(vm.total / 1_048_576),
        "mem_used_mb": round(vm.used / 1_048_576),
        "swap_total_mb": round(swap.total / 1_048_576),
        "swap_used_mb": round(swap.used / 1_048_576),
        "disk_total_gb": disk_total_gb,
        "disk_used_gb": disk_used_gb,
        "process": {
            "pid": pid,
            "threads": threads,
            "rss_mb": rss_mb,
            "vms_mb": vms_mb,
            "open_fds": open_fds,
            "proc_cpu_percent": proc_cpu_pct,
        },
    }


def _build_payload(
    redis_version: Optional[str],
    redis_ok: bool,
) -> Dict[str, Any]:
    """
    Build the complete diagnostics payload.

    Parameters:
        redis_version (Optional[str]): Version or error for Redis.
        redis_ok (bool): Whether Redis is reachable.

    Returns:
        Dict[str, Any]: Structured diagnostics data.
    """
    db_ver, db_ok = _database_version()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host": HOSTNAME,
        "uptime_seconds": int(time.time() - START_TIME),
        "app": {
            "name": settings.app_name,
            "mcp_protocol_version": settings.protocol_version,
            "git_revision": _git_revision(),
        },
        "platform": {
            "python": platform.python_version(),
            "fastapi": __import__("fastapi").__version__,
            "sqlalchemy": __import__("sqlalchemy").__version__,
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        },
        "database": {
            "dialect": engine.dialect.name,
            "url": _sanitize_url(settings.database_url),
            "reachable": db_ok,
            "server_version": db_ver,
        },
        "redis": {
            "available": REDIS_AVAILABLE,
            "url": _sanitize_url(settings.redis_url),
            "reachable": redis_ok,
            "server_version": redis_version,
        },
        "settings": {
            "cache_type": settings.cache_type,
            "mcpgateway_ui_enabled": getattr(settings, "mcpgateway_ui_enabled", None),
            "mcpgateway_admin_api_enabled": getattr(settings, "mcpgateway_admin_api_enabled", None),
        },
        "env": _public_env(),
        "system": _system_metrics(),
    }


def _html_table(obj: Dict[str, Any]) -> str:
    """
    Render a dict as an HTML table.

    Parameters:
        obj (Dict[str, Any]): The data to render.

    Returns:
        str: HTML table markup.
    """
    rows = "".join(f"<tr><th>{k}</th><td>{json.dumps(v, default=str) if not isinstance(v, str) else v}</td></tr>" for k, v in obj.items())
    return f"<table>{rows}</table>"


def _render_html(payload: Dict[str, Any]) -> str:
    """
    Render the full diagnostics payload as HTML.

    Parameters:
        payload (Dict[str, Any]): The diagnostics data.

    Returns:
        str: Complete HTML page.
    """
    style = (
        "<style>"
        "body{font-family:system-ui,sans-serif;margin:2rem;}"
        "table{border-collapse:collapse;width:100%;margin-bottom:1rem;}"
        "th,td{border:1px solid #ccc;padding:.5rem;text-align:left;}"
        "th{background:#f7f7f7;width:25%;}"
        "</style>"
    )
    header = f"<h1>MCP Gateway diagnostics</h1><p>Generated {payload['timestamp']} • Host {payload['host']} • Uptime {payload['uptime_seconds']}s</p>"
    sections = ""
    for title, key in (
        ("App", "app"),
        ("Platform", "platform"),
        ("Database", "database"),
        ("Redis", "redis"),
        ("Settings", "settings"),
        ("System", "system"),
    ):
        sections += f"<h2>{title}</h2>{_html_table(payload[key])}"
    env_section = f"<h2>Environment</h2>{_html_table(payload['env'])}"
    return f"<!doctype html><html><head><meta charset='utf-8'>{style}</head><body>{header}{sections}{env_section}</body></html>"


def _login_html(next_url: str) -> str:
    """
    Render the login form HTML for unauthenticated browsers.

    Parameters:
        next_url (str): The URL to return to after login.

    Returns:
        str: HTML of the login page.
    """
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Login - MCP Gateway</title>
<style>
body{{font-family:system-ui,sans-serif;margin:2rem;}}
form{{max-width:320px;margin:auto;}}
label{{display:block;margin:.5rem 0;}}
input{{width:100%;padding:.5rem;}}
button{{margin-top:1rem;padding:.5rem 1rem;}}
</style></head>
<body>
  <h2>Please log in</h2>
  <form action="{LOGIN_PATH}" method="post">
    <input type="hidden" name="next" value="{next_url}">
    <label>Username<input type="text" name="username" autocomplete="username"></label>
    <label>Password<input type="password" name="password" autocomplete="current-password"></label>
    <button type="submit">Login</button>
  </form>
</body></html>"""


# Endpoint
@router.get("/version", summary="Diagnostics (auth required)")
async def version_endpoint(
    request: Request,
    fmt: Optional[str] = None,
    partial: Optional[bool] = False,
    _user=Depends(require_auth),
) -> Response:
    """
    Serve diagnostics as JSON, full HTML, or partial HTML (if requested).

    Parameters:
        request (Request): The incoming HTTP request.
        fmt (Optional[str]): Query param 'html' for full HTML output.
        partial (Optional[bool]): Query param to request partial HTML fragment.

    Returns:
        Response: JSONResponse or HTMLResponse with diagnostics data.
    """
    # Redis health check
    redis_ok = False
    redis_version: Optional[str] = None
    if REDIS_AVAILABLE and settings.cache_type.lower() == "redis" and settings.redis_url:
        try:
            client = aioredis.Redis.from_url(settings.redis_url)
            await client.ping()
            info = await client.info()
            redis_version = info.get("redis_version")
            redis_ok = True
        except Exception as exc:
            redis_version = str(exc)

    payload = _build_payload(redis_version, redis_ok)
    if partial:
        # Return partial HTML fragment for HTMX embedding
        templates = Jinja2Templates(directory=str(settings.templates_dir))
        return templates.TemplateResponse(request, "version_info_partial.html", {"request": request, "payload": payload})
    wants_html = fmt == "html" or "text/html" in request.headers.get("accept", "")
    if wants_html:
        return HTMLResponse(_render_html(payload))
    return JSONResponse(payload)
