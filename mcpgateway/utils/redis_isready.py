#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redis_isready - Wait until Redis is ready and accepting connections
======================================================================
This helper blocks until the given **Redis** server (defined by a connection URL)
successfully responds to a `PING` command. It is intended to delay application startup until Redis is online.

It can be used both **synchronously** or **asynchronously**, and will retry
connections with a configurable interval and number of attempts.

Features
--------
* Supports any valid Redis URL supported by :pypi:`redis`.
* Retry settings are configurable via *environment variables*.
* Works both **synchronously** (blocking) and **asynchronously**.

Environment variables
---------------------
These environment variables can be used to configure retry behavior and Redis connection.

+-----------------------------+-----------------------------------------------+-----------------------------+
| Name                        | Description                                   | Default                     |
+=============================+===============================================+=============================+
| ``REDIS_URL``               | Redis connection URL                          | ``redis://localhost:6379/0``|
| ``REDIS_MAX_RETRIES``       | Maximum retry attempts before failing         | ``3``                       |
| ``REDIS_RETRY_INTERVAL_MS`` | Delay between retries *(milliseconds)*        | ``2000``                    |
| ``LOG_LEVEL``               | Log verbosity when not set via ``--log-level``| ``INFO``                    |
+-----------------------------+-----------------------------------------------+-----------------------------+

Usage examples
--------------
Shell ::

    python redis_isready.py
    python redis_isready.py --redis-url "redis://localhost:6379/0" \
                            --max-retries 5 --retry-interval-ms 500

Python ::

    from redis_isready import wait_for_redis_ready

    await wait_for_redis_ready()           # asynchronous
    wait_for_redis_ready(sync=True)        # synchronous / blocking
"""


# Standard
import asyncio
import logging
import os
import time
from typing import Optional

try:
    # Third-Party
    from redis import Redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Environment variables
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_MAX_RETRIES = int(os.getenv("REDIS_MAX_RETRIES", "3"))
REDIS_RETRY_INTERVAL_MS = int(os.getenv("REDIS_RETRY_INTERVAL_MS", "2000"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def wait_for_redis_ready(
    *,
    redis_url: str = REDIS_URL,
    max_retries: int = REDIS_MAX_RETRIES,
    retry_interval_ms: int = REDIS_RETRY_INTERVAL_MS,
    logger: Optional[logging.Logger] = None,
    sync: bool = False,
) -> None:
    """
    Wait until a Redis server is ready to accept connections.

    This function attempts to connect to Redis and issue a `PING` command,
    retrying if the connection fails. It can run synchronously (blocking)
    or asynchronously using an executor. Intended for use during service
    startup to ensure Redis is reachable before proceeding.

    Args:
        redis_url : str
            Redis connection URL. Defaults to the value of the `REDIS_URL` environment variable.
        max_retries : int
            Maximum number of connection attempts before failing.
        retry_interval_ms : int
            Delay between retry attempts, in milliseconds.
        logger : logging.Logger, optional
            Logger instance to use. If not provided, a default logger is configured.
        sync : bool
            If True, runs the probe synchronously. If False (default), runs it asynchronously.

    Raises:
        RuntimeError: If Redis does not respond successfully after all retry attempts.
    """

    log = logger or logging.getLogger("redis_isready")
    if not log.handlers:  # basicConfig **once** - respects *log.setLevel* later
        logging.basicConfig(
            level=getattr(logging, LOG_LEVEL, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    if max_retries < 1 or retry_interval_ms <= 0:
        raise RuntimeError("Invalid max_retries or retry_interval_ms values")

    def _probe() -> None:
        """
        Inner synchronous probe running in either the current or a thread.

        Returns:
            None - the function exits successfully once the DB answers.

        Raises:
            RuntimeError: Forwarded after exhausting ``max_tries`` attempts.
        """

        redis = Redis.from_url(redis_url)
        for attempt in range(1, max_retries + 1):
            try:
                redis.ping()
                log.info(f"Redis ready (attempt {attempt})")
                return
            except ConnectionError:
                log.warning(f"Redis connection failed (attempt {attempt}/{max_retries}) - retrying in {retry_interval_ms} ms")
                time.sleep(retry_interval_ms / 1000.0)
        raise RuntimeError(f"Redis not ready after {max_retries} attempts")

    if sync:
        _probe()
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(loop.run_in_executor(None, _probe))
