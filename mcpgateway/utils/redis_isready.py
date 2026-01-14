#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/redis_isready.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Reeve Barreto, Mihai Criveti

redis_isready - Wait until Redis is ready and accepting connections
This helper blocks until the given **Redis** server (defined by a connection URL)
successfully responds to a `PING` command. It is intended to delay application startup until Redis is online.

It can be used both **synchronously** or **asynchronously**, and will retry
connections with a configurable interval and number of attempts.

Exit codes when executed as a script
-----------------------------------
* ``0`` - Redis ready.
* ``1`` - all attempts exhausted / timed-out.
* ``2`` - :pypi:`redis` is **not** installed.
* ``3`` - invalid parameter combination (``max_retries``/``retry_interval_ms``).

Features
--------
* Supports any valid Redis URL supported by :pypi:`redis`.
* **Exponential backoff with jitter** - prevents thundering herd on reconnect:
  - Retry delays: 2s → 4s → 8s → 16s → 30s (capped) → 30s...
  - Random jitter of ±25% prevents synchronized reconnection storms
  - Default: 30 retries ≈ 5 minutes total wait before giving up
* Retry settings are configurable via *environment variables*.
* Works both **synchronously** (blocking) and **asynchronously**.

Environment variables
---------------------
These environment variables can be used to configure retry behavior and Redis connection.

+-------------------------------+-----------------------------------------------+-----------------------------+
| Name                          | Description                                   | Default                     |
+===============================+===============================================+=============================+
| ``REDIS_URL``                 | Redis connection URL                          | ``redis://localhost:6379/0``|
| ``REDIS_MAX_RETRIES``         | Maximum retry attempts before failing         | ``30``                      |
| ``REDIS_RETRY_INTERVAL_MS``   | Base delay between retries *(milliseconds)*   | ``2000``                    |
| ``REDIS_MAX_BACKOFF_SECONDS`` | Max backoff cap *(seconds, jitter added)*     | ``30``                      |
| ``LOG_LEVEL``                 | Log verbosity when not set via ``--log-level``| ``INFO``                    |
+-------------------------------+-----------------------------------------------+-----------------------------+

Usage examples
--------------
Shell ::

    python3 redis_isready.py
    python3 redis_isready.py --redis-url "redis://localhost:6379/0"
                            --max-retries 5 --retry-interval-ms 500

Python ::

    from mcpgateway.utils.redis_isready import wait_for_redis_ready

    # Synchronous/blocking
    wait_for_redis_ready(sync=True)

    # Asynchronous
    import asyncio
    asyncio.run(wait_for_redis_ready())

Doctest examples
----------------
>>> from mcpgateway.utils.redis_isready import wait_for_redis_ready
>>> import logging
>>> class DummyLogger:
...     def __init__(self): self.infos = []
...     def info(self, msg): self.infos.append(msg)
...     def debug(self, msg): pass
...     def error(self, msg): pass
...     @property
...     def handlers(self): return [True]
>>> def dummy_probe(*args, **kwargs): return None
>>> import sys
>>> sys.modules['redis'] = type('redis', (), {'Redis': type('Redis', (), {'from_url': lambda url: type('R', (), {'ping': lambda self: True})()})})
>>> wait_for_redis_ready(redis_url='redis://localhost:6379/0', max_retries=1, retry_interval_ms=1, logger=DummyLogger(), sync=True)

>>> try:
...     wait_for_redis_ready(redis_url='redis://localhost:6379/0', max_retries=0, retry_interval_ms=1, logger=DummyLogger(), sync=True)
... except RuntimeError as e:
...     print('error')
error
"""

# Standard
import argparse
import asyncio
import logging
import os
import random
import sys
import time
from typing import Any, Optional

# First-Party
# First Party imports
from mcpgateway.config import settings

# Environment variables
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_MAX_RETRIES = int(os.getenv("REDIS_MAX_RETRIES", "30"))
REDIS_RETRY_INTERVAL_MS = int(os.getenv("REDIS_RETRY_INTERVAL_MS", "2000"))
REDIS_MAX_BACKOFF_SECONDS = float(os.getenv("REDIS_MAX_BACKOFF_SECONDS", "30"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def wait_for_redis_ready(
    *,
    redis_url: str = REDIS_URL,
    max_retries: int = REDIS_MAX_RETRIES,
    retry_interval_ms: int = REDIS_RETRY_INTERVAL_MS,
    max_backoff: float = REDIS_MAX_BACKOFF_SECONDS,
    logger: Optional[logging.Logger] = None,
    sync: bool = False,
) -> None:
    """
    Wait until a Redis server is ready to accept connections.

    This function attempts to connect to Redis and issue a `PING` command,
    retrying if the connection fails. It can run synchronously (blocking)
    or asynchronously using an executor. Intended for use during service
    startup to ensure Redis is reachable before proceeding.

    Uses **exponential backoff with jitter** to prevent thundering herd when
    multiple workers attempt to reconnect simultaneously. The delay between
    attempts doubles each time (capped at max_backoff), with ±25% random jitter.

    Example retry progression with retry_interval_ms=2000, max_backoff=30s:
        Attempt 1: 2s, Attempt 2: 4s, Attempt 3: 8s, Attempt 4: 16s,
        Attempt 5+: 30s (capped), each ±25% jitter

    Args:
        redis_url : str
            Redis connection URL. Defaults to the value of the `REDIS_URL` environment variable.
        max_retries : int
            Maximum number of connection attempts before failing.
        retry_interval_ms : int
            Base delay between retry attempts, in milliseconds. Actual delay uses
            exponential backoff: ``min(interval * 2^(attempt-1), max_backoff)``, then ±25% jitter.
        max_backoff : float
            Maximum backoff delay in seconds (default 30). Jitter is applied after this cap,
            so actual sleep can be ±25% of this value.
        logger : logging.Logger, optional
            Logger instance to use. If not provided, a default logger is configured.
        sync : bool
            If True, runs the probe synchronously. If False (default), runs it asynchronously.

    Raises:
        RuntimeError: If Redis does not respond successfully after all retry attempts.

    Examples:
        >>> from mcpgateway.utils.redis_isready import wait_for_redis_ready
        >>> import logging
        >>> class DummyLogger:
        ...     def __init__(self): self.infos = []
        ...     def info(self, msg): self.infos.append(msg)
        ...     def debug(self, msg): pass
        ...     def error(self, msg): pass
        ...     @property
        ...     def handlers(self): return [True]
        >>> import sys
        >>> sys.modules['redis'] = type('redis', (), {'Redis': type('Redis', (), {'from_url': lambda url: type('R', (), {'ping': lambda self: True})()})})
        >>> wait_for_redis_ready(redis_url='redis://localhost:6379/0', max_retries=1, retry_interval_ms=1, logger=DummyLogger(), sync=True)
        >>> try:
        ...     wait_for_redis_ready(redis_url='redis://localhost:6379/0', max_retries=0, retry_interval_ms=1, logger=DummyLogger(), sync=True)
        ... except RuntimeError as e:
        ...     print('error')
        error
    """
    log = logger or logging.getLogger("redis_isready")
    if not log.handlers:  # basicConfig **once** - respects *log.setLevel* later
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL, logging.INFO),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    if max_retries < 1 or retry_interval_ms <= 0:
        raise RuntimeError("Invalid max_retries or retry_interval_ms values")

    log.info(f"Probing Redis at {redis_url} (interval={retry_interval_ms}ms, max_retries={max_retries}, max_backoff={max_backoff}s)")

    def _probe(*_: Any) -> None:
        """
        Inner synchronous probe running in either the current or a thread.

        Args:
            *_: Ignored arguments (for compatibility with run_in_executor).

        Returns:
            None - the function exits successfully once Redis answers.

        Raises:
            RuntimeError: Forwarded after exhausting ``max_retries`` attempts.
        """
        try:
            # Import redis here to avoid dependency issues if not used
            # Third-Party
            from redis import Redis
        except ImportError:  # pragma: no cover - handled at runtime for the CLI
            sys.stderr.write("redis library not installed - aborting (pip install redis)\n")
            sys.exit(2)

        redis_client = Redis.from_url(redis_url)
        interval_s = retry_interval_ms / 1000.0  # Convert to seconds
        for attempt in range(1, max_retries + 1):
            try:
                redis_client.ping()
                log.info(f"Redis ready (attempt {attempt})")
                return
            except Exception as exc:
                if attempt < max_retries:  # Don't sleep on the last attempt
                    # Exponential backoff: interval * 2^(attempt-1), capped at max_backoff
                    backoff = min(interval_s * (2 ** (attempt - 1)), max_backoff)
                    # Add jitter (±25%) to prevent thundering herd
                    jitter = backoff * random.uniform(-0.25, 0.25)  # noqa: DUO102  # nosec B311 - timing jitter, not security
                    sleep_time = max(0.1, backoff + jitter)  # Ensure minimum 0.1s
                    log.debug(f"Attempt {attempt}/{max_retries} failed ({exc}) - retrying in {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                else:
                    log.debug(f"Attempt {attempt}/{max_retries} failed ({exc})")
        raise RuntimeError(f"Redis not ready after {max_retries} attempts")

    if sync:
        _probe()
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(loop.run_in_executor(None, _probe))


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _parse_cli() -> argparse.Namespace:
    """Parse command-line arguments for the *redis_isready* CLI wrapper.

    Returns:
        Parsed :class:`argparse.Namespace` holding all CLI options.

    Examples:
        >>> import sys
        >>> # Save original argv
        >>> original_argv = sys.argv
        >>>
        >>> # Test with default values
        >>> sys.argv = ['redis_isready.py']
        >>> args = _parse_cli()
        >>> args.redis_url == REDIS_URL
        True
        >>> args.max_retries == REDIS_MAX_RETRIES
        True
        >>> args.retry_interval_ms == REDIS_RETRY_INTERVAL_MS
        True
        >>> args.log_level == LOG_LEVEL
        True
        >>>
        >>> # Test with custom values
        >>> sys.argv = ['redis_isready.py', '--redis-url', 'redis://custom:6380/1',
        ...             '--max-retries', '5', '--retry-interval-ms', '500',
        ...             '--log-level', 'DEBUG']
        >>> args = _parse_cli()
        >>> args.redis_url
        'redis://custom:6380/1'
        >>> args.max_retries
        5
        >>> args.retry_interval_ms
        500
        >>> args.log_level
        'DEBUG'
        >>>
        >>> # Restore original argv
        >>> sys.argv = original_argv
    """

    parser = argparse.ArgumentParser(
        description="Wait until Redis is ready and accepting connections.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--redis-url",
        default=REDIS_URL,
        help="Redis connection URL (env REDIS_URL)",
    )
    parser.add_argument("--max-retries", type=int, default=REDIS_MAX_RETRIES, help="Maximum connection attempts")
    parser.add_argument("--retry-interval-ms", type=int, default=REDIS_RETRY_INTERVAL_MS, help="Delay between attempts in milliseconds")
    parser.add_argument("--max-backoff", type=float, default=REDIS_MAX_BACKOFF_SECONDS, help="Maximum backoff delay in seconds (jitter applied after)")
    parser.add_argument("--log-level", default=LOG_LEVEL, help="Logging level (DEBUG, INFO, ...)")
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    """CLI entry-point.

    * Parses command-line options.
    * Applies ``--log-level`` to the *redis_isready* logger **before** the first
      message is emitted.
    * Delegates the actual probing to :func:`wait_for_redis_ready`.
    * Exits with:

        * ``0`` - Redis became ready.
        * ``1`` - connection attempts exhausted.
        * ``2`` - redis library missing.
        * ``3`` - invalid parameter combination.
    """
    cli_args = _parse_cli()

    log = logging.getLogger("redis_isready")
    log.setLevel(cli_args.log_level.upper())

    try:
        wait_for_redis_ready(
            redis_url=cli_args.redis_url,
            max_retries=cli_args.max_retries,
            retry_interval_ms=cli_args.retry_interval_ms,
            max_backoff=cli_args.max_backoff,
            sync=True,
            logger=log,
        )
    except RuntimeError as exc:
        log.error(f"Redis unavailable: {exc}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    if settings.cache_type == "redis":
        # Ensure Redis is ready before proceeding
        main()
    else:
        # If not using Redis, just exit with success
        sys.exit(0)
