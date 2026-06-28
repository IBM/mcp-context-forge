# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/primary_worker.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Primary-worker election for side-effecting plugin work.

Under multiple worker processes every worker runs each plugin's
``initialize()``. ``is_primary_worker()`` lets a plugin gate side-effecting work
to one worker. Election uses a file lock: the first process to acquire it is
primary; the OS releases it on exit so another caller can take over.
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

    Uses ``MCPGW_PRIMARY_WORKER_LOCK`` if set, else a port-scoped tempdir file.

    Returns:
        Absolute path to the lock file.
    """
    override = os.environ.get(_LOCK_PATH_ENV)
    if override:
        return override
    return os.path.join(tempfile.gettempdir(), f"mcpgw_plugin_primary_{settings.port}.lock")


def is_primary_worker() -> bool:
    """Return ``True`` on exactly one worker process; ``False`` on the others.

    The first caller to acquire the lock holds it; others retry on later calls,
    so a new primary is elected if the current one exits. Call from the startup /
    event-loop path (mutates module state without a thread guard).

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
