#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""db_isready.py - Blocks until the MCP Gateway database is ready.

This standalone readiness probe exits *0* once the configured database answers a
trivial SQL round-trip (``SELECT 1``) and *1* after all retries fail. It is
meant for container orchestrators (Kubernetes, Docker Healthcheck, etc.) and CI
pipelines that need a dependable way to wait for the DB service.

Features
--------
* Works with **any SQLAlchemy URL** supplied via the ``DATABASE_URL`` environment
  variable or the ``--database-url`` command-line flag.
* All timing knobs (tries, interval, timeout) are tunable through env-vars or
  CLI flags.
* **Verbose, timestamped logging** including backend type, target host, current
  attempt, total attempts, interval and timeout for easy troubleshooting.
* Prints clear, context-rich diagnostics and degrades gracefully if dependencies
  are missing.
* Requires only **SQLAlchemy >= 1.4** - a dependency already present in the MCP
  Gateway.

Environment Variables
---------------------
DATABASE_URL
    SQLAlchemy connection URL. If unset, defaults to ``sqlite:///./mcp.db``.
DB_WAIT_MAX_TRIES
    Maximum connection attempts before giving up (default : 30).
DB_WAIT_INTERVAL
    Delay between attempts in seconds (default : 2).
DB_CONNECT_TIMEOUT
    Per-attempt network timeout in seconds (default : 2).

Example
~~~~~~~
>>> # Use environment defaults
>>> python db_isready.py

>>> # Explicit Postgres URL and faster retries (CI)
>>> python db_isready.py --database-url "postgresql://user:pw@db:5432/mcp" \
...                      --max-tries 20 --interval 1 --timeout 1

Exit Codes
~~~~~~~~~~
0   Database is ready.
1   All attempts failed.
2   *sqlalchemy* is missing.
3   Invalid parameters or ``DATABASE_URL``.
"""
# Future
from __future__ import annotations

# Standard
import argparse
import logging
import os
import sys
import time
from typing import Any, Dict

try:
    # Third-Party
    from sqlalchemy import create_engine, text  # type: ignore
    from sqlalchemy.engine.url import make_url  # type: ignore
    from sqlalchemy.exc import OperationalError  # type: ignore
except ImportError:  # pragma: no cover - explicit probe error path
    sys.stderr.write("❌ SQLAlchemy not installed — aborting (pip install sqlalchemy)\n")
    sys.exit(2)

# ---------------------------------------------------------------------------
# Defaults — overridable via ENV *or* CLI
# ---------------------------------------------------------------------------
ENV_DB_URL = "DATABASE_URL"
ENV_MAX_TRIES = "DB_WAIT_MAX_TRIES"
ENV_INTERVAL = "DB_WAIT_INTERVAL"
ENV_TIMEOUT = "DB_CONNECT_TIMEOUT"

DEFAULT_MAX_TRIES = 30
DEFAULT_INTERVAL = 2.0  # seconds
DEFAULT_TIMEOUT = 2  # seconds per attempt

# SQLite file embedded in repo root (see README)
DEFAULT_SQLITE_PATH = "sqlite:///./mcp.db"

# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def parse_cli() -> argparse.Namespace:  # noqa: D401 - imperative mood
    """Return parsed command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Block until the MCP Gateway database is ready (SQLAlchemy URL)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--database-url",
        dest="database_url",
        help="SQLAlchemy connection URL (falls back to env)",
    )
    parser.add_argument("--max-tries", type=int, help="Maximum connection attempts")
    parser.add_argument("--interval", type=float, help="Delay between attempts in seconds")
    parser.add_argument("--timeout", type=int, help="Per-attempt connect() timeout in seconds")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _format_target(url_obj) -> str:
    """Return a human-readable target string from a SQLAlchemy URL object."""
    backend = url_obj.get_backend_name()
    if backend == "sqlite":
        return url_obj.database or "<memory>"
    host = url_obj.host or "localhost"
    port = f":{url_obj.port}" if url_obj.port else ""
    db = f"/{url_obj.database}" if url_obj.database else ""
    return f"{host}{port}{db}"


# ---------------------------------------------------------------------------
# Main probe logic
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover - script entry-point
    # Configure simple timestamped logger (stdout so k8s captures it)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    log = logging.getLogger("db_isready")

    args = parse_cli()

    # Resolve effective configuration (precedence: CLI > ENV > default)
    database_url = args.database_url or os.getenv(ENV_DB_URL) or DEFAULT_SQLITE_PATH

    max_tries = args.max_tries or int(os.getenv(ENV_MAX_TRIES, DEFAULT_MAX_TRIES))
    interval = args.interval or float(os.getenv(ENV_INTERVAL, DEFAULT_INTERVAL))
    timeout = args.timeout or int(os.getenv(ENV_TIMEOUT, DEFAULT_TIMEOUT))

    if max_tries < 1 or interval <= 0 or timeout <= 0:
        log.error("Invalid parameters — check --max-tries / --interval / --timeout")
        sys.exit(3)

    # Validate and parse URL
    try:
        url_obj = make_url(database_url)
    except Exception as exc:  # noqa: BLE001 - any parse failure is fatal here
        log.error("Invalid DATABASE_URL: %s", exc)
        sys.exit(3)

    backend = url_obj.get_backend_name()
    target = _format_target(url_obj)

    log.info(
        "Probing %s database @ %s (timeout=%ss, interval=%ss, max_tries=%d)",
        backend,
        target,
        timeout,
        interval,
        max_tries,
    )

    # Build SQLAlchemy Engine (no pooling; short-lived probe)
    connect_args: Dict[str, Any] = {}
    if backend.startswith(("postgresql", "mysql")):
        # Most network DBAPIs honour 'connect_timeout' keyword (secs)
        connect_args["connect_timeout"] = timeout

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        connect_args=connect_args,
    )

    start_time = time.perf_counter()

    for attempt in range(1, max_tries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))  # lightweight round-trip
            elapsed = time.perf_counter() - start_time
            log.info("Database is ready after %.2fs (attempt %d)", elapsed, attempt)
            sys.exit(0)
        except OperationalError as exc:  # noqa: BLE001 - broad ok in probe
            log.warning(
                "Attempt %d/%d failed (%s: %s) — retrying in %.1fs (timeout=%ss)",
                attempt,
                max_tries,
                exc.__class__.__name__,
                exc,
                interval,
                timeout,
            )
        except Exception as exc:
            # Unexpected errors (driver import race, etc.) still retry but highlighted
            log.error("Unexpected error while probing DB on attempt %d/%d: %s", attempt, max_tries, exc)
        time.sleep(interval)

    total_elapsed = time.perf_counter() - start_time
    log.error(
        "Database not ready after %.0fs and %d attempts — giving up",
        total_elapsed,
        max_tries,
    )
    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover - CLI entry-point
    main()
