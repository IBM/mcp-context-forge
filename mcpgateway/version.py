"""version.py - /version endpoint with rich diagnostic & HTML option **requiring authentication**.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module exposes a FastAPI router that returns a structured snapshot of the
running MCP Gateway instance, its dependencies (database, Redis, OS), and key
configuration flags.  If the request's *Accept* header includes *text/html* or
`?format=html` is passed, the endpoint will render a simple HTML dashboard; in
all other cases it returns JSON.

Access to this endpoint is protected by the same authentication dependency
(`require_auth`) used elsewhere in the gateway, so callers must supply a valid
Bearer token (or Basic credentials if enabled).
"""

from __future__ import annotations

import json
import os
import platform
import socket
import time
from datetime import datetime
from typing import Any, Dict

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text

try:
    import psutil  # optional - process & system metrics
except ImportError:  # pragma: no cover - psutil is optional
    psutil = None  # type: ignore

from mcpgateway.config import settings
from mcpgateway.db import engine
from mcpgateway.utils.verify_credentials import require_auth

# ──────────────────────────────────────────────────────────────────────────────
# Globals
# ──────────────────────────────────────────────────────────────────────────────

START_TIME = time.time()
HOSTNAME = socket.gethostname()
router = APIRouter(tags=["meta"])

# ──────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────────────────────────────────────


def _is_secret(key: str) -> bool:
    """Heuristic for redacting env‑vars that look secret."""
    keywords = ("SECRET", "PASSWORD", "TOKEN", "KEY")
    return any(k in key.upper() for k in keywords)


def _public_env() -> Dict[str, str]:
    """Return env‑vars with obvious secrets stripped out."""
    return {k: v for k, v in os.environ.items() if not _is_secret(k)}


def _database_version() -> tuple[str | None, bool]:
    """Attempt to fetch RDBMS version string; return (version, reachable)."""
    dialect = engine.dialect.name
    query_map = {
        "sqlite": "SELECT sqlite_version();",
        "postgresql": "SELECT current_setting('server_version');",
        "mysql": "SELECT version();",
    }
    query = query_map.get(dialect, "SELECT version();")
    try:
        with engine.connect() as conn:
            return conn.execute(text(query)).scalar() or "unknown", True
    except Exception as exc:  # noqa: BLE001 - we surface raw error
        return str(exc), False


def _system_metrics() -> Dict[str, Any]:
    """Return optional memory/CPU metrics if psutil available."""
    if not psutil:
        return {}
    vm = psutil.virtual_memory()
    load1, load5, load15 = os.getloadavg()
    return {
        "cpu_count": psutil.cpu_count(logical=True),
        "load_avg": [load1, load5, load15],
        "mem_total_mb": round(vm.total / 1048576),
        "mem_used_mb": round(vm.used / 1048576),
    }


def _build_payload(redis_version: str | None = None, redis_ok: bool = False) -> Dict[str, Any]:
    """Assemble structured diagnostic payload."""
    db_version, db_ok = _database_version()

    payload: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "host": HOSTNAME,
        "uptime_seconds": int(time.time() - START_TIME),
        "app": {
            "name": settings.app_name,
            "mcp_protocol_version": settings.protocol_version,
        },
        "platform": {
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "fastapi": __import__("fastapi").__version__,
            "sqlalchemy": __import__("sqlalchemy").__version__,
        },
        "database": {
            "dialect": engine.dialect.name,
            "url": settings.database_url,
            "reachable": db_ok,
            "server_version": db_version,
        },
        "redis": {
            "url": settings.redis_url,
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
    return payload


def _render_html(data: Dict[str, Any]) -> str:
    """Very small hand‑rolled HTML template. No Jinja needed."""

    def _table(obj: Dict[str, Any]) -> str:
        rows = "\n".join(f"<tr><th>{k}</th><td>{json.dumps(v, default=str) if not isinstance(v, str) else v}</td></tr>" for k, v in obj.items())
        return f"<table>{rows}</table>"

    sections = []
    for key in (
        "app",
        "platform",
        "database",
        "redis",
        "settings",
        "system",
    ):
        sections.append(f"<h2>{key.title()}</h2>{_table(data[key])}")
    env_rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in data["env"].items())
    env_table = f"<h2>Environment</h2><table>{env_rows}</table>"
    info_hdr = f"<h1>MCP Gateway diagnostics</h1><p>Generated: {data['timestamp']} — Host: {data['host']} — Uptime: {data['uptime_seconds']} s</p>"
    style = """
    <style>
    body{font-family:system-ui,sans-serif;margin:2rem;}
    table{border-collapse:collapse;width:100%;margin-bottom:1.5rem;}
    th,td{border:1px solid #ccc;padding:0.5rem;text-align:left;font-size:0.9rem;}
    th{background:#f7f7f7;width:22%;}
    h1{margin-top:0;}
    </style>"""
    return f"<!doctype html><html><head><meta charset='utf-8'>{style}</head><body>{info_hdr}{''.join(sections)}{env_table}</body></html>"


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────────────────


@router.get(
    "/version",
    summary="Gateway diagnostic & dependency versions (auth required)",
    response_class=JSONResponse,
)
async def get_version(
    request: Request,
    format: str | None = None,
    user: str = Depends(require_auth),  # 🛡️ enforce authentication
):
    """Return JSON or HTML diagnostic snapshot (authentication required).

    **JSON** is default; request HTML via:
    - `Accept: text/html` header
    - query param `?format=html`
    """
    redis_version: str | None = None
    redis_ok = False

    if settings.cache_type.lower() == "redis" and settings.redis_url:
        try:
            redis = aioredis.Redis.from_url(settings.redis_url)
            await redis.ping()
            info = await redis.info()
            redis_version = info.get("redis_version")
            redis_ok = True
        except Exception as exc:  # noqa: BLE001 - surface error
            redis_version = str(exc)

    data = _build_payload(redis_version, redis_ok)

    wants_html = format == "html" or "text/html" in request.headers.get("accept", "")
    if wants_html:
        return HTMLResponse(content=_render_html(data))
    return JSONResponse(content=data)
