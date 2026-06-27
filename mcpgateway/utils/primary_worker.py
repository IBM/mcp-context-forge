# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/primary_worker.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Primary-worker election for side-effecting plugin work.

When the gateway runs under multiple worker processes (e.g. gunicorn), every
worker loads the plugin manager and runs each plugin's ``initialize()``. For a
non-hook plugin that performs a side effect on startup or in a background task,
that work would run once per worker. ``is_primary_worker()`` lets such a plugin
gate its work so it runs on exactly one worker.

Election is done with a file lock: the first process to acquire it is the
primary and holds it for its lifetime; other processes get ``False``. The lock
is released by the OS when the holding process exits, so another caller becomes
primary on its next call.
"""

# Standard
import os
import tempfile

# Third-Party
from filelock import FileLock, Timeout

# First-Party
from mcpgateway.config import settings

# Environment variable to override the lock file path.
_LOCK_PATH_ENV = "MCPGW_PRIMARY_WORKER_LOCK"

# Module state: the lock object is kept here so the winning process keeps
# holding the lock for its lifetime, and so the primary decision is memoized.
_lock: "FileLock | None" = None
_is_primary: bool = False


def _lock_path() -> str:
    """Return the lock file path.

    Uses ``MCPGW_PRIMARY_WORKER_LOCK`` when set; otherwise a tempdir file scoped
    by the configured port so co-located gateway instances do not collide while
    workers of the same instance share one lock.

    Returns:
        Absolute path to the lock file.
    """
    override = os.environ.get(_LOCK_PATH_ENV)
    if override:
        return override
    return os.path.join(tempfile.gettempdir(), f"mcpgw_plugin_primary_{settings.port}.lock")


def is_primary_worker() -> bool:
    """Return ``True`` on exactly one worker process; ``False`` on the others.

    The first process to acquire the lock becomes the primary and keeps it. A
    non-primary process retries on each call, so if the current primary exits
    (e.g. gunicorn ``max_requests`` recycling) the next caller takes over.

    Intended for the startup / event-loop path; it mutates module state without
    a thread guard and is not meant to be called concurrently across threads.

    Example::

        from mcpgateway.utils.primary_worker import is_primary_worker

        async def initialize(self) -> None:
            if not is_primary_worker():
                return
            ...  # side effect that should run on one worker only

    Returns:
        Whether this process holds primary status.
    """
    global _lock, _is_primary  # pylint: disable=global-statement
    if _is_primary:
        return True
    if _lock is None:
        _lock = FileLock(_lock_path())
    try:
        _lock.acquire(timeout=0)
        _is_primary = True
    except Timeout:
        _is_primary = False
    return _is_primary
