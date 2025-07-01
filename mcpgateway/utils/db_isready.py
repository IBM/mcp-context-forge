#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_isready.py
=============

Blocks until the configured database responds to a trivial round-trip
(`SELECT 1`) and then exits:

* **0**  - database ready
* **1**  - all attempts failed / timed out
* **2**  - SQLAlchemy missing
* **3**  - invalid parameters

The probe can be executed as a script or used as a helper from Python code.

---------------------------------------------------------------------------
Features
---------------------------------------------------------------------------

* Accepts **any** SQLAlchemy URL.
* Timing knobs (tries, interval, timeout) are tunable through environment
  variables or command-line flags.
* Works both **synchronously** and **asynchronously** (`await wait_for_db_ready()`).
* Credentials in log lines are automatically redacted.
* Relies on SQLAlchemy only (already required by the gateway).

---------------------------------------------------------------------------
Environment variables
---------------------------------------------------------------------------
This script uses mcpgateway.config.settings as a fallback for defaults,
but you can override them with environment variables or command-line flags.

+-------------------+--------------------------------------------+-----------+
| Name              | Description                                | Default   |
+===================+============================================+===========+
| DATABASE_URL      | SQLAlchemy connection URL                  | sqlite:///./mcp.db or ``settings.database_url`` |
| DB_WAIT_MAX_TRIES | Maximum attempts before giving up          | 30        |
| DB_WAIT_INTERVAL  | Delay between attempts (seconds)           | 2         |
| DB_CONNECT_TIMEOUT| Per-attempt connect timeout (seconds)      | 2         |
| LOG_LEVEL         | Log verbosity when not set via --log-level | INFO      |
+-------------------+--------------------------------------------+-----------+

---------------------------------------------------------------------------
Usage examples
---------------------------------------------------------------------------

Shell:

    python db_isready.py
    python db_isready.py --database-url "postgresql://user:pw@db:5432/mcp" \
                         --max-tries 20 --interval 1 --timeout 1

Python:

    from db_isready import wait_for_db_ready
    await wait_for_db_ready()          # async
    wait_for_db_ready(sync=True)       # sync

---------------------------------------------------------------------------
Implementation notes
---------------------------------------------------------------------------

`SELECT 1` is compiled by SQLAlchemy's dialect layer; on databases that
require a dummy table (e.g., Oracle) it becomes `SELECT 1 FROM DUAL`,
so the probe is portable across all supported back-ends.
"""
# Future
from __future__ import annotations

# Standard
import argparse
import asyncio
import logging
import os
import re
import sys
import time
from typing import Any, Dict, Final, Optional

# --------------------------------------------------------------------------- #
# Dependency check                                                            #
# --------------------------------------------------------------------------- #
try:
    # Third-Party
    from sqlalchemy import create_engine, text  # type: ignore
    from sqlalchemy.engine.url import make_url  # type: ignore
    from sqlalchemy.exc import OperationalError  # type: ignore
except ImportError:  # pragma: no cover
    sys.stderr.write("SQLAlchemy not installed - aborting (pip install sqlalchemy)\n")
    sys.exit(2)

# --------------------------------------------------------------------------- #
# Optional project settings (silently ignored if package is absent)           #
# --------------------------------------------------------------------------- #
try:
    # First-Party
    from mcpgateway.config import settings  # type: ignore
except Exception:  # pragma: no cover

    class _Settings:  # minimal fallback
        database_url: str = "sqlite:///./mcp.db"
        log_level: str = "INFO"

    settings = _Settings()  # type: ignore

# --------------------------------------------------------------------------- #
# Defaults (overridable by env or CLI)                                        #
# --------------------------------------------------------------------------- #
ENV_DB_URL = "DATABASE_URL"
ENV_MAX_TRIES = "DB_WAIT_MAX_TRIES"
ENV_INTERVAL = "DB_WAIT_INTERVAL"
ENV_TIMEOUT = "DB_CONNECT_TIMEOUT"

DEFAULT_DB_URL: Final[str] = os.getenv(ENV_DB_URL, settings.database_url)
DEFAULT_MAX_TRIES: Final[int] = int(os.getenv(ENV_MAX_TRIES, 30))
DEFAULT_INTERVAL: Final[float] = float(os.getenv(ENV_INTERVAL, 2))
DEFAULT_TIMEOUT: Final[int] = int(os.getenv(ENV_TIMEOUT, 2))
DEFAULT_LOG_LEVEL: Final[str] = os.getenv("LOG_LEVEL", settings.log_level).upper()

# --------------------------------------------------------------------------- #
# Helper utilities                                                            #
# --------------------------------------------------------------------------- #
_CRED_RE = re.compile(r"://([^:/?#]+):([^@]+)@")
_PWD_RE = re.compile(r"(?i)(password|pwd)=([^\s]+)")


def _sanitize(txt: str) -> str:
    """Redact credentials in URLs and DSNs."""
    txt = _CRED_RE.sub(r"://\\1:***@", txt)
    return _PWD_RE.sub(r"\\1=***", txt)


def _format_target(url) -> str:
    """Return host:port/db (or sqlite path) without secrets."""
    if url.get_backend_name() == "sqlite":
        return url.database or "<memory>"
    host = url.host or "localhost"
    port = f":{url.port}" if url.port else ""
    db = f"/{url.database}" if url.database else ""
    return f"{host}{port}{db}"


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
def wait_for_db_ready(
    *,
    database_url: str = DEFAULT_DB_URL,
    max_tries: int = DEFAULT_MAX_TRIES,
    interval: float = DEFAULT_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
    logger: Optional[logging.Logger] = None,
    sync: bool = False,
) -> None:
    """Block until the database responds, otherwise raise RuntimeError."""
    log = logger or logging.getLogger("db_isready")
    if not log.handlers:
        logging.basicConfig(
            level=getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    if max_tries < 1 or interval <= 0 or timeout <= 0:
        raise RuntimeError("Invalid max_tries / interval / timeout values")

    url_obj = make_url(database_url)
    backend = url_obj.get_backend_name()
    target = _format_target(url_obj)

    log.info(
        "Probing %s at %s (timeout=%ss, interval=%ss, max_tries=%d)",
        backend,
        target,
        timeout,
        interval,
        max_tries,
    )

    connect_args: Dict[str, Any] = {}
    if backend.startswith(("postgresql", "mysql")):
        connect_args["connect_timeout"] = timeout

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        connect_args=connect_args,
    )

    def _probe() -> None:
        start = time.perf_counter()
        for attempt in range(1, max_tries + 1):
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                log.info(
                    "Database ready after %.2fs (attempt %d)",
                    time.perf_counter() - start,
                    attempt,
                )
                return
            except OperationalError as exc:
                log.debug(
                    "Attempt %d/%d failed (%s) - retrying in %.1fs",
                    attempt,
                    max_tries,
                    _sanitize(str(exc)),
                    interval,
                )
            time.sleep(interval)
        raise RuntimeError(f"Database not ready after {max_tries} attempts")

    if sync:
        _probe()
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(loop.run_in_executor(None, _probe))


# --------------------------------------------------------------------------- #
# CLI interface                                                               #
# --------------------------------------------------------------------------- #
def _parse_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Wait until the configured database is ready.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--database-url", default=DEFAULT_DB_URL, help="SQLAlchemy URL (env DATABASE_URL)")
    p.add_argument("--max-tries", type=int, default=DEFAULT_MAX_TRIES, help="Maximum connection attempts")
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="Delay between attempts in seconds")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-attempt connect timeout in seconds")
    p.add_argument("--log-level", default=DEFAULT_LOG_LEVEL, help="Logging level (DEBUG, INFO, ...)")
    return p.parse_args()


def main() -> None:  # pragma: no cover
    args = _parse_cli()
    logging.getLogger("db_isready").setLevel(args.log_level.upper())
    try:
        wait_for_db_ready(
            database_url=args.database_url,
            max_tries=args.max_tries,
            interval=args.interval,
            timeout=args.timeout,
            sync=True,
        )
    except RuntimeError as exc:
        logging.error("Database unavailable: %s", exc)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
