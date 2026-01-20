# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/version.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

version.py - diagnostics endpoint (HTML + JSON)
A FastAPI router that mounts at /version and returns either:
- JSON - machine-readable diagnostics payload
- HTML - a lightweight dashboard when the client requests text/html or ?format=html

Features:
- Cross-platform system metrics (Windows/macOS/Linux), with fallbacks where APIs are unavailable
- Optional dependencies: psutil (for richer metrics) and redis.asyncio (for Redis health); omitted gracefully if absent
- Authentication enforcement via `require_auth`; unauthenticated browsers see login form, API clients get JSON 401
- Redacted environment variables, sanitized DB/Redis URLs

The module provides comprehensive system diagnostics including application info,
platform details, database and Redis connectivity, system metrics, and environment
variables (with secrets redacted).

Environment variables containing the following patterns are automatically redacted:
- Keywords: SECRET, TOKEN, PASS, KEY
- Specific vars: BASIC_AUTH_USER, DATABASE_URL, REDIS_URL

Examples:
    >>> from mcpgateway.version import _is_secret, _sanitize_url, START_TIME, HOSTNAME
    >>> _is_secret("DATABASE_PASSWORD")
    True
    >>> _is_secret("BASIC_AUTH_USER")
    True
    >>> _is_secret("HOSTNAME")
    False
    >>> _sanitize_url("redis://user:xxxxx@localhost:6379/0")
    'redis://user@localhost:6379/0'
    >>> _sanitize_url("postgresql://admin:xxxxx@db.example.com/mydb")
    'postgresql://admin@db.example.com/mydb'
    >>> _sanitize_url("https://example.com/path")
    'https://example.com/path'
    >>> isinstance(START_TIME, float)
    True
    >>> START_TIME > 0
    True
    >>> isinstance(HOSTNAME, str)
    True
    >>> len(HOSTNAME) > 0
    True
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from datetime import datetime, timezone
import importlib.util
import os
import platform
import socket
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

# Third-Party
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
import orjson
from sqlalchemy import text

# First-Party
from mcpgateway import __version__
from mcpgateway.config import settings
from mcpgateway.db import engine
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.redis_client import get_redis_client, is_redis_available
from mcpgateway.utils.verify_credentials import require_auth

# Optional runtime dependencies
try:
    # Third-Party
    import psutil  # optional for enhanced metrics
except ImportError:
    psutil = None  # type: ignore

try:
    REDIS_AVAILABLE = importlib.util.find_spec("redis.asyncio") is not None
except (ModuleNotFoundError, AttributeError) as e:
    # ModuleNotFoundError: redis package not installed
    # AttributeError: 'redis' exists but isn't a proper package (e.g., shadowed by a file)
    # Standard
    import logging

    logging.getLogger(__name__).warning(f"Redis module check failed ({type(e).__name__}: {e}), Redis support disabled")
    REDIS_AVAILABLE = False

# Globals

START_TIME = time.time()
HOSTNAME = socket.gethostname()
LOGIN_PATH = "/login"
router = APIRouter(tags=["meta"])


def _is_secret(key: str) -> bool:
    """Identify if an environment variable key likely represents a secret.

    Checks if the given environment variable name contains common secret-related
    keywords or matches specific patterns to prevent accidental exposure of
    sensitive information in diagnostics.

    Args:
        key (str): The environment variable name to check.

    Returns:
        bool: True if the key contains secret-looking keywords or matches
            known secret patterns, False otherwise.

    Examples:
        >>> _is_secret("DATABASE_PASSWORD")
        True
        >>> _is_secret("API_KEY")
        True
        >>> _is_secret("SECRET_TOKEN")
        True
        >>> _is_secret("PASS_PHRASE")
        True
        >>> # Specific MCP Gateway secrets
        >>> _is_secret("BASIC_AUTH_USER")
        True
        >>> _is_secret("BASIC_AUTH_PASSWORD")
        True
        >>> _is_secret("JWT_SECRET_KEY")
        True
        >>> _is_secret("AUTH_ENCRYPTION_SECRET")
        True
        >>> _is_secret("DATABASE_URL")
        True
        >>> _is_secret("REDIS_URL")
        True
        >>> # Non-secrets
        >>> _is_secret("HOSTNAME")
        False
        >>> _is_secret("PORT")
        False
        >>> _is_secret("DEBUG")
        False
        >>> _is_secret("APP_NAME")
        False
        >>> # Case insensitive check
        >>> _is_secret("database_password")
        True
        >>> _is_secret("MySecretKey")
        True
        >>> _is_secret("basic_auth_user")
        True
        >>> _is_secret("redis_url")
        True
    """
    key_upper = key.upper()

    # Check for common secret keywords
    if any(tok in key_upper for tok in ("SECRET", "TOKEN", "PASS", "KEY")):
        return True

    # Check for specific secret environment variables
    secret_vars = {"BASIC_AUTH_USER", "DATABASE_URL", "REDIS_URL"}

    return key_upper in secret_vars


def _public_env() -> Dict[str, str]:
    """Collect environment variables excluding those that look secret.

    Filters out environment variables containing sensitive keywords or matching
    known secret patterns to create a safe subset for display in diagnostics.

    Returns:
        Dict[str, str]: A map of environment variable names to values,
            excluding any variables identified as secrets.

    Examples:
        >>> import os
        >>> # Mock environment
        >>> original_env = dict(os.environ)
        >>> os.environ.clear()
        >>> os.environ.update({
        ...     "HOME": "/home/user",
        ...     "PATH": "/usr/bin:/bin",
        ...     "DATABASE_PASSWORD": "xxxxx",
        ...     "API_KEY": "xxxxx",
        ...     "DEBUG": "true",
        ...     "BASIC_AUTH_USER": "admin",
        ...     "BASIC_AUTH_PASSWORD": "xxxxx",
        ...     "JWT_SECRET_KEY": "xxxxx",
        ...     "AUTH_ENCRYPTION_SECRET": "xxxxx",
        ...     "DATABASE_URL": "postgresql://user:xxxxx@localhost/db",
        ...     "REDIS_URL": "redis://user:xxxxx@localhost:6379",
        ...     "APP_NAME": "MyApp",
        ...     "PORT": "8080"
        ... })
        >>>
        >>> result = _public_env()
        >>> # Public vars should be included
        >>> "HOME" in result
        True
        >>> "PATH" in result
        True
        >>> "DEBUG" in result
        True
        >>> "APP_NAME" in result
        True
        >>> "PORT" in result
        True
        >>> # Secrets should be excluded
        >>> "DATABASE_PASSWORD" in result
        False
        >>> "API_KEY" in result
        False
        >>> "BASIC_AUTH_USER" in result
        False
        >>> "BASIC_AUTH_PASSWORD" in result
        False
        >>> "JWT_SECRET_KEY" in result
        False
        >>> "AUTH_ENCRYPTION_SECRET" in result
        False
        >>> "DATABASE_URL" in result
        False
        >>> "REDIS_URL" in result
        False
        >>>
        >>> # Restore original environment
        >>> os.environ.clear()
        >>> os.environ.update(original_env)
    """
    return {k: v for k, v in os.environ.items() if not _is_secret(k)}


def _sanitize_url(url: Optional[str]) -> Optional[str]:
    """Redact credentials from a URL for safe display.

    Removes password component from URLs while preserving username and other
    components. Useful for displaying connection strings in logs or diagnostics
    without exposing sensitive credentials.

    Args:
        url (Optional[str]): The URL to sanitize, may be None.

    Returns:
        Optional[str]: The sanitized URL with password removed, or None if input was None.

    Examples:
        >>> _sanitize_url(None)

        >>> _sanitize_url("")

        >>> # Basic URL without credentials
        >>> _sanitize_url("http://localhost:8080/path")
        'http://localhost:8080/path'

        >>> # URL with username and password
        >>> _sanitize_url("postgresql://user:xxxxx@localhost:5432/db")
        'postgresql://user@localhost:5432/db'

        >>> # Redis URL with auth
        >>> _sanitize_url("redis://admin:xxxxx@redis.example.com:6379/0")
        'redis://admin@redis.example.com:6379/0'

        >>> # URL with only password (no username)
        >>> _sanitize_url("redis://:xxxxx@localhost:6379")
        'redis://localhost:6379'

        >>> # Complex URL with query params
        >>> _sanitize_url("mysql://root:xxxxx@db.local:3306/mydb?charset=utf8")
        'mysql://root@db.local:3306/mydb?charset=utf8'
    """
    if not url:
        return None
    parts = urlsplit(url)
    if parts.password:
        # Only include username@ if username exists
        if parts.username:
            netloc = f"{parts.username}@{parts.hostname}{':' + str(parts.port) if parts.port else ''}"
        else:
            netloc = f"{parts.hostname}{':' + str(parts.port) if parts.port else ''}"
        parts = parts._replace(netloc=netloc)
    result = urlunsplit(parts)
    return result if isinstance(result, str) else str(result)


def _database_version() -> tuple[str, bool]:
    """Query the database server version.

    Attempts to connect to the configured database and retrieve its version string.
    Uses dialect-specific queries for accurate version information.

    Returns:
        tuple[str, bool]: A tuple containing:
            - str: Version string on success, or error message on failure
            - bool: True if database is reachable, False otherwise

    Examples:
        >>> from unittest.mock import Mock, patch, MagicMock
        >>>
        >>> # Test successful SQLite connection
        >>> mock_engine = Mock()
        >>> mock_engine.dialect.name = "sqlite"
        >>> mock_conn = Mock()
        >>> mock_result = Mock()
        >>> mock_result.scalar.return_value = "3.39.2"
        >>> mock_conn.execute.return_value = mock_result
        >>> mock_conn.__enter__ = Mock(return_value=mock_conn)
        >>> mock_conn.__exit__ = Mock(return_value=None)
        >>> mock_engine.connect.return_value = mock_conn
        >>>
        >>> with patch('mcpgateway.version.engine', mock_engine):
        ...     version, reachable = _database_version()
        >>> version
        '3.39.2'
        >>> reachable
        True

        >>> # Test PostgreSQL
        >>> mock_engine.dialect.name = "postgresql"
        >>> mock_result.scalar.return_value = "14.5"
        >>> with patch('mcpgateway.version.engine', mock_engine):
        ...     version, reachable = _database_version()
        >>> version
        '14.5'
        >>> reachable
        True

        >>> # Test connection failure
        >>> mock_engine.connect.side_effect = Exception("Connection refused")
        >>> with patch('mcpgateway.version.engine', mock_engine):
        ...     version, reachable = _database_version()
        >>> version
        'Connection refused'
        >>> reachable
        False
    """
    dialect = engine.dialect.name
    stmts = {
        "sqlite": "SELECT sqlite_version();",
        "postgresql": "SELECT current_setting('server_version');",
        "mysql": "SELECT version();",
    }
    stmt = stmts.get(dialect, "XXSELECT version();XX")
    try:
        with engine.connect() as conn:
            ver = conn.execute(text(stmt)).scalar()
            return str(ver), True
    except Exception as exc:
        return str(exc), False


def _system_metrics() -> Dict[str, Any]:
    """Gather system-wide and per-process metrics using psutil.

    Collects comprehensive system and process metrics with graceful fallbacks
    when psutil is not installed or certain APIs are unavailable (e.g., on Windows).

    Returns:
        Dict[str, Any]: A dictionary containing system and process metrics including:
            - boot_time (str): ISO-formatted system boot time.
            - cpu_percent (float): Total CPU utilization percentage.
            - cpu_count (int): Number of logical CPU cores.
            - cpu_freq_mhz (float | None): Current CPU frequency in MHz (if available).
            - load_avg (Tuple[float | None, float | None, float | None]): System load average over 1, 5, and 15 minutes,
            or (None, None, None) if unsupported.
            - mem_total_mb (float): Total physical memory in MB.
            - mem_used_mb (float): Used physical memory in MB.
            - swap_total_mb (float): Total swap memory in MB.
            - swap_used_mb (float): Used swap memory in MB.
            - disk_total_gb (float): Total size of the root partition in GB.
            - disk_used_gb (float): Used space on the root partition in GB.
            - process (Dict[str, Any]): Dictionary containing metrics for the current process:
                - pid (int): Current process ID.
                - threads (int): Number of active threads.
                - rss_mb (float): Resident Set Size memory usage in MB.
                - vms_mb (float): Virtual Memory Size usage in MB.
                - open_fds (int | None): Number of open file descriptors, or None if unsupported.
                - proc_cpu_percent (float): CPU utilization percentage for the current process.

        Returns empty dict if psutil is not installed.

    Examples:
        >>> from unittest.mock import Mock, patch
        >>>
        >>> # Test without psutil
        >>> with patch('mcpgateway.version.psutil', None):
        ...     metrics = _system_metrics()
        >>> metrics
        {}

        >>> # Test with mocked psutil
        >>> mock_psutil = Mock()
        >>> mock_vm = Mock(total=8589934592, used=4294967296)  # 8GB total, 4GB used
        >>> mock_swap = Mock(total=2147483648, used=1073741824)  # 2GB total, 1GB used
        >>> mock_freq = Mock(current=2400.0)
        >>> mock_disk = Mock(total=107374182400, used=53687091200)  # 100GB total, 50GB used
        >>> mock_mem_info = Mock(rss=104857600, vms=209715200)  # 100MB RSS, 200MB VMS
        >>> mock_process = Mock()
        >>> mock_process.memory_info.return_value = mock_mem_info
        >>> mock_process.num_fds.return_value = 42
        >>> mock_process.cpu_percent.return_value = 25.5
        >>> mock_process.num_threads.return_value = 4
        >>> mock_process.pid = 1234
        >>>
        >>> mock_psutil.virtual_memory.return_value = mock_vm
        >>> mock_psutil.swap_memory.return_value = mock_swap
        >>> mock_psutil.cpu_freq.return_value = mock_freq
        >>> mock_psutil.cpu_percent.return_value = 45.2
        >>> mock_psutil.cpu_count.return_value = 8
        >>> mock_psutil.Process.return_value = mock_process
        >>> mock_psutil.disk_usage.return_value = mock_disk
        >>> mock_psutil.boot_time.return_value = 1640995200.0  # 2022-01-01 00:00:00 UTC
        >>>
        >>> with patch('mcpgateway.version.psutil', mock_psutil):
        ...     with patch('os.getloadavg', return_value=(1.5, 2.0, 1.75)):
        ...         with patch('os.name', 'posix'):
        ...             metrics = _system_metrics()
        >>>
        >>> metrics['cpu_percent']
        45.2
        >>> metrics['cpu_count']
        8
        >>> metrics['cpu_freq_mhz']
        2400
        >>> metrics['load_avg']
        (1.5, 2.0, 1.75)
        >>> metrics['mem_total_mb']
        8192
        >>> metrics['mem_used_mb']
        4096
        >>> metrics['process']['pid']
        1234
        >>> metrics['process']['threads']
        4
        >>> metrics['process']['rss_mb']
        100.0
        >>> metrics['process']['open_fds']
        42
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
    proc: "psutil.Process" = psutil.Process()
    try:
        open_fds = proc.num_fds()
    except Exception:
        open_fds = None
    proc_cpu_pct = proc.cpu_percent(interval=0.1)
    memory_info = getattr(proc, "memory_info")()
    rss_mb = round(memory_info.rss / 1_048_576, 2)
    vms_mb = round(memory_info.vms / 1_048_576, 2)
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
    """Build the complete diagnostics payload.

    Assembles all diagnostic information into a structured dictionary suitable
    for JSON serialization or HTML rendering.

    Args:
        redis_version (Optional[str]): Redis version string or error message.
        redis_ok (bool): Whether Redis is reachable and operational.

    Returns:
        Dict[str, Any]: Complete diagnostics payload containing timestamp, host info,
            application details, platform info, database and Redis status, settings,
            environment variables, and system metrics.
    """
    db_ver, db_ok = _database_version()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host": HOSTNAME,
        "uptime_seconds": int(time.time() - START_TIME),
        "app": {
            "name": settings.app_name,
            "version": __version__,
            "mcp_protocol_version": settings.protocol_version,
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
            "metrics_retention_days": getattr(settings, "metrics_retention_days", 30),
            "metrics_rollup_retention_days": getattr(settings, "metrics_rollup_retention_days", 365),
            "metrics_cleanup_enabled": getattr(settings, "metrics_cleanup_enabled", True),
            "metrics_rollup_enabled": getattr(settings, "metrics_rollup_enabled", True),
        },
        "env": _public_env(),
        "system": _system_metrics(),
    }


def _html_table(obj: Dict[str, Any]) -> str:
    """Render a dict as an HTML table.

    Converts a dictionary into an HTML table with keys as headers and values
    as cells. Non-string values are JSON-serialized for display.

    Args:
        obj (Dict[str, Any]): The dictionary to render as a table.

    Returns:
        str: HTML table markup string.

    Examples:
        >>> # Simple string values
        >>> html = _html_table({"name": "test", "version": "1.0"})
        >>> '<table>' in html
        True
        >>> '<tr><th>name</th><td>test</td></tr>' in html
        True
        >>> '<tr><th>version</th><td>1.0</td></tr>' in html
        True

        >>> # Complex values get JSON serialized
        >>> html = _html_table({"count": 42, "active": True, "items": ["a", "b"]})
        >>> '<th>count</th><td>42</td>' in html
        True
        >>> '<th>active</th><td>true</td>' in html
        True
        >>> '<th>items</th><td>["a","b"]</td>' in html
        True

        >>> # Empty dict
        >>> _html_table({})
        '<table></table>'
    """
    rows = "".join(f"<tr><th>{k}</th><td>{orjson.dumps(v, default=str).decode() if not isinstance(v, str) else v}</td></tr>" for k, v in obj.items())
    return f"<table>{rows}</table>"


def _render_html(payload: Dict[str, Any]) -> str:
    """Render the full diagnostics payload as HTML.

    Creates a complete HTML page with styled tables displaying all diagnostic
    information in a user-friendly format.

    Args:
        payload (Dict[str, Any]): The complete diagnostics data structure.

    Returns:
        str: Complete HTML page as a string.

    Examples:
        >>> payload = {
        ...     "timestamp": "2024-01-01T00:00:00Z",
        ...     "host": "test-server",
        ...     "uptime_seconds": 3600,
        ...     "app": {"name": "TestApp", "version": "1.0"},
        ...     "platform": {"python": "3.9.0"},
        ...     "database": {"dialect": "sqlite", "reachable": True},
        ...     "redis": {"available": False},
        ...     "settings": {"cache_type": "memory"},
        ...     "system": {"cpu_count": 4},
        ...     "env": {"PATH": "/usr/bin"}
        ... }
        >>>
        >>> html = _render_html(payload)
        >>> '<!doctype html>' in html
        True
        >>> '<h1>MCP Gateway diagnostics</h1>' in html
        True
        >>> 'test-server' in html
        True
        >>> '3600s' in html
        True
        >>> '<h2>App</h2>' in html
        True
        >>> '<h2>Database</h2>' in html
        True
        >>> '<style>' in html
        True
        >>> 'border-collapse:collapse' in html
        True
    """
    style = (
        "<style>"
        "body{font-family:system-ui,sans-serif;margin:2rem;}"
        "table{border-collapse:collapse;width:100%;margin-bottom:1rem;}"
        "th,td{border:1px solid #ccc;padding:.5rem;text-align:left;}"
        "th{background:#f7f7f7;width:25%;}"
        "</style>"
    )
    header = f"<h1>MCP Gateway diagnostics</h1><p>Generated {payload['timestamp']} - Host {payload['host']} - Uptime {payload['uptime_seconds']}s</p>"
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
    """Render the login form HTML for unauthenticated browsers.

    Creates a simple login form that posts credentials and redirects back
    to the requested URL after successful authentication.

    Args:
        next_url (str): The URL to redirect to after successful login.

    Returns:
        str: HTML string containing the complete login page.

    Examples:
        >>> html = _login_html("/version?format=html")
        >>> '<!doctype html>' in html
        True
        >>> '<h2>Please log in</h2>' in html
        True
        >>> 'action="/login"' in html
        True
        >>> 'name="next" value="/version?format=html"' in html
        True
        >>> 'type="text" name="username"' in html
        True
        >>> 'type="password" name="password"' in html
        True
        >>> 'autocomplete="username"' in html
        True
        >>> 'autocomplete="current-password"' in html
        True
        >>> '<button type="submit">Login</button>' in html
        True
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
    """Serve diagnostics as JSON, full HTML, or partial HTML.

    Main endpoint that gathers all diagnostic information and returns it in the
    requested format. Requires authentication via HTTP Basic Auth or session.

    The endpoint supports three output formats:
    - JSON (default): Machine-readable diagnostic data
    - Full HTML: Complete HTML page with styled tables
    - Partial HTML: HTML fragment for embedding (when partial=True)

    Args:
        request (Request): The incoming FastAPI request object.
        fmt (Optional[str]): Query parameter to force format ('html' for HTML output).
        partial (Optional[bool]): Query parameter to request partial HTML fragment.
        _user: Injected authenticated user from require_auth dependency.

    Returns:
        Response: JSONResponse with diagnostic data, or HTMLResponse with formatted page.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import Mock, AsyncMock, patch
        >>> from fastapi import Request
        >>> from fastapi.responses import JSONResponse, HTMLResponse
        >>>
        >>> # Create mock request
        >>> mock_request = Mock(spec=Request)
        >>> mock_request.headers = {"accept": "application/json"}
        >>>
        >>> # Test JSON response (default)
        >>> async def test_json():
        ...     with patch('mcpgateway.version.REDIS_AVAILABLE', False):
        ...         with patch('mcpgateway.version._build_payload') as mock_build:
        ...             mock_build.return_value = {"test": "data"}
        ...             response = await version_endpoint(mock_request, fmt=None, partial=False, _user="testuser")
        ...             return response
        >>>
        >>> response = asyncio.run(test_json())
        >>> isinstance(response, JSONResponse)
        True

        >>> # Test HTML response with fmt parameter
        >>> async def test_html_fmt():
        ...     with patch('mcpgateway.version.REDIS_AVAILABLE', False):
        ...         with patch('mcpgateway.version._build_payload') as mock_build:
        ...             with patch('mcpgateway.version._render_html') as mock_render:
        ...                 mock_build.return_value = {"test": "data"}
        ...                 mock_render.return_value = "<html>test</html>"
        ...                 response = await version_endpoint(mock_request, fmt="html", partial=False, _user="testuser")
        ...                 return response
        >>>
        >>> response = asyncio.run(test_html_fmt())
        >>> isinstance(response, HTMLResponse)
        True

        >>> # Test with Redis available (using is_redis_available and get_redis_client)
        >>> async def test_with_redis():
        ...     from mcpgateway.utils.redis_client import _reset_client
        ...     _reset_client()  # Reset shared client state for clean test
        ...     mock_redis = AsyncMock()
        ...     mock_redis.info = AsyncMock(return_value={"redis_version": "7.0.5"})
        ...
        ...     async def mock_get_redis_client():
        ...         return mock_redis
        ...
        ...     async def mock_is_redis_available():
        ...         return True
        ...
        ...     with patch('mcpgateway.version.REDIS_AVAILABLE', True):
        ...         with patch('mcpgateway.version.settings') as mock_settings:
        ...             mock_settings.cache_type = "redis"
        ...             mock_settings.redis_url = "redis://localhost:6379"
        ...             with patch('mcpgateway.version.is_redis_available', mock_is_redis_available):
        ...                 with patch('mcpgateway.version.get_redis_client', mock_get_redis_client):
        ...                     with patch('mcpgateway.version._build_payload') as mock_build:
        ...                         mock_build.return_value = {"redis": {"version": "7.0.5"}}
        ...                         response = await version_endpoint(mock_request, _user="testuser")
        ...                         # Verify Redis info was retrieved
        ...                         mock_redis.info.assert_called_once()
        ...                         # Verify payload was built with Redis info
        ...                         mock_build.assert_called_once_with("7.0.5", True)
        ...                         _reset_client()  # Clean up after test
        ...                         return response
        >>>
        >>> response = asyncio.run(test_with_redis())
        >>> isinstance(response, JSONResponse)
        True
    """
    # Redis health check - use shared client from factory
    redis_ok = False
    redis_version: Optional[str] = None
    if REDIS_AVAILABLE and settings.cache_type.lower() == "redis" and settings.redis_url:
        try:
            # Use centralized availability check
            redis_ok = await is_redis_available()
            if redis_ok:
                client = await get_redis_client()
                if client:
                    info = await asyncio.wait_for(client.info(), timeout=3.0)
                    redis_version = info.get("redis_version", "unknown")
                else:
                    redis_version = "Client not available"
            else:
                redis_version = "Not reachable"
        except Exception as exc:
            redis_ok = False
            redis_version = str(exc)

    payload = _build_payload(redis_version, redis_ok)
    if partial:
        # Return partial HTML fragment for HTMX embedding
        templates = Jinja2Templates(directory=str(settings.templates_dir), auto_reload=settings.templates_auto_reload)
        return templates.TemplateResponse(request, "version_info_partial.html", {"request": request, "payload": payload})
    wants_html = fmt == "html" or "text/html" in request.headers.get("accept", "")
    if wants_html:
        return HTMLResponse(_render_html(payload))
    return ORJSONResponse(payload)
