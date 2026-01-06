#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/db_isready.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

db_isready - Wait until the configured database is ready
==========================================================
This helper blocks until the given database (defined by an **SQLAlchemy** URL)
successfully answers a trivial round-trip - ``SELECT 1`` - and then returns.
It is useful as a container **readiness/health probe** or imported from Python
code to delay start-up of services that depend on the DB.

Exit codes when executed as a script
-----------------------------------
* ``0`` - database ready.
* ``1`` - all attempts exhausted / timed-out.
* ``2`` - :pypi:`SQLAlchemy` is **not** installed.
* ``3`` - invalid parameter combination (``max_tries``/``interval``/``timeout``).

Features
--------
* Accepts **any** SQLAlchemy URL supported by the installed version.
* Timing knobs (tries, interval, connect-timeout) configurable through
  *environment variables* **or** *CLI flags* - see below.
* Works **synchronously** (blocking) or **asynchronously** - simply
  ``await wait_for_db_ready()``.
* Credentials appearing in log lines are automatically **redacted**.
* Depends only on ``sqlalchemy`` (already required by *mcpgateway*).

Environment variables
---------------------
The script falls back to :pydata:`mcpgateway.config.settings`, but the values
below can be overridden via environment variables *or* the corresponding
command-line options.

+------------------------+----------------------------------------------+-----------+
| Name                   | Description                                  | Default   |
+========================+==============================================+===========+
| ``DATABASE_URL``       | SQLAlchemy connection URL                    | ``sqlite:///./mcp.db`` |
| ``DB_WAIT_MAX_TRIES``  | Maximum attempts before giving up            | ``30``    |
| ``DB_WAIT_INTERVAL``   | Delay between attempts *(seconds)*           | ``2``     |
| ``DB_CONNECT_TIMEOUT`` | Per-attempt connect timeout *(seconds)*      | ``2``     |
| ``LOG_LEVEL``          | Log verbosity when not set via ``--log-level`` | ``INFO`` |
+------------------------+----------------------------------------------+-----------+

Usage examples
--------------
Shell ::

    python3 db_isready.py
    python3 db_isready.py --database-url "sqlite:///./mcp.db" --max-tries 2 --interval 1 --timeout 1

Python ::

    from mcpgateway.utils.db_isready import wait_for_db_ready

    # Synchronous/blocking
    wait_for_db_ready(sync=True)

    # Asynchronous
    import asyncio
    asyncio.run(wait_for_db_ready())

Doctest examples
----------------
>>> from mcpgateway.utils.db_isready import wait_for_db_ready
>>> import logging
>>> class DummyLogger:
...     def __init__(self): self.infos = []
...     def info(self, msg): self.infos.append(msg)
...     def debug(self, msg): pass
...     def error(self, msg): pass
...     @property
...     def handlers(self): return [True]
>>> import sys
>>> sys.modules['sqlalchemy'] = type('sqlalchemy', (), {
...     'create_engine': lambda *a, **k: type('E', (), {'connect': lambda self: type('C', (), {'execute': lambda self, q: 1, '__enter__': lambda self: self, '__exit__': lambda self, exc_type, exc_val, exc_tb: None})()})(),
...     'text': lambda q: q,
...     'engine': type('engine', (), {'Engine': object, 'URL': object, 'url': type('url', (), {'make_url': lambda u: type('U', (), {'get_backend_name': lambda self: "sqlite"})()}),}),
...     'exc': type('exc', (), {'OperationalError': Exception})
... })
>>> wait_for_db_ready(database_url='sqlite:///./mcp.db', max_tries=1, interval=1, timeout=1, logger=DummyLogger(), sync=True)
>>> try:
...     wait_for_db_ready(database_url='sqlite:///./mcp.db', max_tries=0, interval=1, timeout=1, logger=DummyLogger(), sync=True)
... except RuntimeError as e:
...     print('error')
error
"""

# Future
from __future__ import annotations

# Standard
# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import argparse
import asyncio
import logging
import os
import re
import sys
import time
from typing import Any, Dict, Final, Optional

# ---------------------------------------------------------------------------
# Third-party imports - abort early if SQLAlchemy is missing
# ---------------------------------------------------------------------------
try:
    # Third-Party
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine, URL
    from sqlalchemy.engine.url import make_url
    from sqlalchemy.exc import OperationalError
except ImportError:  # pragma: no cover - handled at runtime for the CLI
    sys.stderr.write("SQLAlchemy not installed - aborting (pip install sqlalchemy)\n")
    sys.exit(2)

# ---------------------------------------------------------------------------
# Optional project settings (silently ignored if mcpgateway package is absent)
# ---------------------------------------------------------------------------
try:
    # First-Party
    from mcpgateway.config import settings
except Exception:  # pragma: no cover - fallback minimal settings

    class _Settings:
        """Fallback dummy settings when *mcpgateway* is not import-able."""

        database_url: str = "sqlite:///./mcp.db"
        log_level: str = "INFO"

    settings = _Settings()  # type: ignore

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------
ENV_DB_URL: Final[str] = "DATABASE_URL"
ENV_MAX_TRIES: Final[str] = "DB_WAIT_MAX_TRIES"
ENV_INTERVAL: Final[str] = "DB_WAIT_INTERVAL"
ENV_TIMEOUT: Final[str] = "DB_CONNECT_TIMEOUT"

# ---------------------------------------------------------------------------
# Defaults - overridable via env-vars or CLI flags
# ---------------------------------------------------------------------------
DEFAULT_DB_URL: Final[str] = os.getenv(ENV_DB_URL, settings.database_url)
DEFAULT_MAX_TRIES: Final[int] = int(os.getenv(ENV_MAX_TRIES, "30"))
DEFAULT_INTERVAL: Final[float] = float(os.getenv(ENV_INTERVAL, "2"))
DEFAULT_TIMEOUT: Final[int] = int(os.getenv(ENV_TIMEOUT, "2"))
DEFAULT_LOG_LEVEL: Final[str] = os.getenv("LOG_LEVEL", settings.log_level).upper()

# ---------------------------------------------------------------------------
# Helpers - sanitising / formatting util functions
# ---------------------------------------------------------------------------
_CRED_RE: Final[re.Pattern[str]] = re.compile(r"://([^:/?#]+):([^@]+)@")
_PWD_RE: Final[re.Pattern[str]] = re.compile(r"(?i)(password|pwd)=([^\s]+)")


def _sanitize(txt: str) -> str:
    """Hide credentials contained in connection strings or driver errors.

    Args:
        txt: Arbitrary text that may contain a DB DSN or ``password=...``
            parameter.

    Returns:
        Same *txt* but with credentials replaced by ``***``.
    """

    redacted = _CRED_RE.sub(r"://\\1:***@", txt)
    return _PWD_RE.sub(r"\\1=***", redacted)


def _format_target(url: URL) -> str:
    """Return a concise *host[:port]/db* representation for logging.

    Args:
        url: A parsed :class:`sqlalchemy.engine.url.URL` instance.

    Returns:
        Human-readable connection target string suitable for log messages.
    """

    if url.get_backend_name() == "sqlite":
        return url.database or "<memory>"

    host: str = url.host or "localhost"
    port: str = f":{url.port}" if url.port else ""
    db: str = f"/{url.database}" if url.database else ""
    return f"{host}{port}{db}"


# ---------------------------------------------------------------------------
# Public API - *wait_for_db_ready*
# ---------------------------------------------------------------------------


def wait_for_db_ready(
    *,
    database_url: str = DEFAULT_DB_URL,
    max_tries: int = DEFAULT_MAX_TRIES,
    interval: float = DEFAULT_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
    logger: Optional[logging.Logger] = None,
    sync: bool = False,
) -> None:
    """
    Block until the database replies to ``SELECT 1``.

    The helper can be awaited **asynchronously** *or* called in *blocking*
    mode by passing ``sync=True``.

    Args:
        database_url: SQLAlchemy URL to probe. Falls back to ``$DATABASE_URL``
            or the project default (usually an on-disk SQLite file).
        max_tries: Total number of connection attempts before giving up.
        interval: Delay *in seconds* between attempts.
        timeout: Per-attempt connection timeout in seconds (passed to the DB
            driver when supported).
        logger: Optional custom :class:`logging.Logger`. If omitted, a default
            one named ``"db_isready"`` is lazily configured.
        sync: When *True*, run in the **current** thread instead of scheduling
            the probe inside an executor. Setting this flag from inside a
            running event-loop will block that loop!

    Raises:
        RuntimeError: If *invalid* parameters are supplied or the database is
            still unavailable after the configured number of attempts.

    Doctest:
    >>> from mcpgateway.utils.db_isready import wait_for_db_ready
    >>> import logging
    >>> class DummyLogger:
    ...     def __init__(self): self.infos = []
    ...     def info(self, msg): self.infos.append(msg)
    ...     def debug(self, msg): pass
    ...     def error(self, msg): pass
    ...     @property
    ...     def handlers(self): return [True]
    >>> import sys
    >>> sys.modules['sqlalchemy'] = type('sqlalchemy', (), {
    ...     'create_engine': lambda *a, **k: type('E', (), {'connect': lambda self: type('C', (), {'execute': lambda self, q: 1, '__enter__': lambda self: self, '__exit__': lambda self, exc_type, exc_val, exc_tb: None})()})(),
    ...     'text': lambda q: q,
    ...     'engine': type('engine', (), {'Engine': object, 'URL': object, 'url': type('url', (), {'make_url': lambda u: type('U', (), {'get_backend_name': lambda self: "sqlite"})()}),}),
    ...     'exc': type('exc', (), {'OperationalError': Exception})
    ... })
    >>> wait_for_db_ready(database_url='sqlite:///./mcp.db', max_tries=1, interval=1, timeout=1, logger=DummyLogger(), sync=True)
    >>> try:
    ...     wait_for_db_ready(database_url='sqlite:///./mcp.db', max_tries=0, interval=1, timeout=1, logger=DummyLogger(), sync=True)
    ... except RuntimeError as e:
    ...     print('error')
    error
    """

    log = logger or logging.getLogger("db_isready")
    if not log.handlers:  # basicConfig **once** - respects *log.setLevel* later
        logging.basicConfig(
            level=getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    if max_tries < 1 or interval <= 0 or timeout <= 0:
        raise RuntimeError("Invalid max_tries / interval / timeout values")

    url_obj: URL = make_url(database_url)
    backend: str = url_obj.get_backend_name()
    target: str = _format_target(url_obj)

    log.info(f"Probing {backend} at {target} (timeout={timeout}s, interval={interval}s, max_tries={max_tries})")

    connect_args: Dict[str, Any] = {}
    if backend.startswith(("postgresql", "mysql")):
        # Most drivers honour this parameter - harmless for others.
        connect_args["connect_timeout"] = timeout

    if backend == "sqlite":
        # SQLite doesn't support pool overflow/timeout parameters
        engine: Engine = create_engine(
            database_url,
            connect_args=connect_args,
        )
    else:
        # Other databases support full pooling configuration
        engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
            connect_args=connect_args,
        )

    def _probe() -> None:  # noqa: D401 - internal helper
        """Inner synchronous probe running in either the current or a thread.

        Returns:
            None - the function exits successfully once the DB answers.

        Raises:
            RuntimeError: Forwarded after exhausting ``max_tries`` attempts.
        """

        start = time.perf_counter()
        for attempt in range(1, max_tries + 1):
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                elapsed = time.perf_counter() - start
                log.info(f"Database ready after {elapsed:.2f}s (attempt {attempt})")
                return
            except OperationalError as exc:
                log.debug(f"Attempt {attempt}/{max_tries} failed ({_sanitize(str(exc))}) - retrying in {interval:.1f}s")
            time.sleep(interval)
        raise RuntimeError(f"Database not ready after {max_tries} attempts")

    if sync:
        _probe()
    else:
        loop = asyncio.get_event_loop()
        # Off-load to default executor to avoid blocking the event-loop.
        loop.run_until_complete(loop.run_in_executor(None, _probe))


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _parse_cli() -> argparse.Namespace:
    """Parse command-line arguments for the *db_isready* CLI wrapper.

    Returns:
        Parsed :class:`argparse.Namespace` holding all CLI options.

    Examples:
        >>> import sys
        >>> # Save original argv
        >>> original_argv = sys.argv
        >>>
        >>> # Test default values
        >>> sys.argv = ['db_isready.py']
        >>> args = _parse_cli()
        >>> args.database_url == DEFAULT_DB_URL
        True
        >>> args.max_tries == DEFAULT_MAX_TRIES
        True
        >>> args.interval == DEFAULT_INTERVAL
        True
        >>> args.timeout == DEFAULT_TIMEOUT
        True
        >>> args.log_level == DEFAULT_LOG_LEVEL
        True

        >>> # Test custom values
        >>> sys.argv = ['db_isready.py', '--database-url', 'postgresql://localhost/test',
        ...             '--max-tries', '5', '--interval', '1.5', '--timeout', '10',
        ...             '--log-level', 'DEBUG']
        >>> args = _parse_cli()
        >>> args.database_url
        'postgresql://localhost/test'
        >>> args.max_tries
        5
        >>> args.interval
        1.5
        >>> args.timeout
        10
        >>> args.log_level
        'DEBUG'

        >>> # Restore original argv
        >>> sys.argv = original_argv
    """

    parser = argparse.ArgumentParser(
        description="Wait until the configured database is ready.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DB_URL,
        help="SQLAlchemy URL (env DATABASE_URL)",
    )
    parser.add_argument("--max-tries", type=int, default=DEFAULT_MAX_TRIES, help="Maximum connection attempts")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="Delay between attempts in seconds")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-attempt connect timeout in seconds")
    parser.add_argument("--log-level", default=DEFAULT_LOG_LEVEL, help="Logging level (DEBUG, INFO, ...)")
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    """CLI entry-point.

    * Parses command-line options.
    * Applies ``--log-level`` to the *db_isready* logger **before** the first
      message is emitted.
    * Delegates the actual probing to :func:`wait_for_db_ready`.
    * Exits with:

        * ``0`` - database became ready.
        * ``1`` - connection attempts exhausted.
        * ``2`` - SQLAlchemy missing (handled on import).
        * ``3`` - invalid parameter combination.
    """
    cli_args = _parse_cli()

    log = logging.getLogger("db_isready")
    log.setLevel(cli_args.log_level.upper())

    try:
        wait_for_db_ready(
            database_url=cli_args.database_url,
            max_tries=cli_args.max_tries,
            interval=cli_args.interval,
            timeout=cli_args.timeout,
            sync=True,
            logger=log,
        )
    except RuntimeError as exc:
        log.error(f"Database unavailable: {exc}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
