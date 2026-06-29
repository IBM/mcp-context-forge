# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/primary_worker.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Primary-worker election for side-effecting plugin work.

Under multiple worker processes every worker runs each plugin's
``initialize()``. ``is_primary_worker()`` lets a plugin gate side-effecting work
to one worker. Election uses a file lock: the first process to acquire it is
primary; the OS releases it on exit so another caller can take over.

The lock file is shared per host. Its path defaults to a port-scoped file in the
system temp dir and is overridable via the ``primary_worker_lock_path`` setting
(``PRIMARY_WORKER_LOCK_PATH``). Because that path is predictable and the temp dir
is world-writable, a local process can pre-acquire the lock and keep every worker
non-primary; point the setting at a gateway-owned directory in hostile
multi-tenant hosts.
"""

# Standard
import logging
import os
import tempfile
import threading

# Third-Party
from filelock import FileLock, Timeout

# First-Party
from mcpgateway.config import settings

__all__ = ["is_primary_worker"]

logger = logging.getLogger(__name__)

# Module state: the lock object is kept here so the winning process holds the
# lock for the lifetime of the process (it is never released explicitly; the OS
# releases it on process exit, which is what lets a follower take over), and so
# the primary decision is memoized. The guard protects the lazy ``_lock``
# init/acquire against concurrent threads (e.g. gunicorn ``--threads > 1``).
_lock: FileLock | None = None
_is_primary: bool = False
_guard = threading.Lock()


def _lock_path() -> str:
    """Return the lock file path.

    Uses ``primary_worker_lock_path`` if set, else a port-scoped tempdir file.

    Returns:
        Absolute path to the lock file.
    """
    override: str | None = settings.primary_worker_lock_path
    if override:
        return override
    return os.path.join(tempfile.gettempdir(), f"mcpgw_plugin_primary_{settings.port}.lock")


def is_primary_worker() -> bool:
    """Return ``True`` on exactly one worker process; ``False`` on the others.

    The first caller to acquire the lock holds it; others retry on later calls,
    so a new primary is elected if the current one exits. Safe to call from
    multiple threads.

    Returns:
        Whether this process holds primary status.
    """
    global _lock, _is_primary  # pylint: disable=global-statement
    if _is_primary:
        return True
    # The guard serializes the lazy init/acquire so concurrent threads can't
    # create two FileLock objects (TOCTOU). The in-guard re-check returns early
    # for threads that were waiting while another won (mypy can't see the
    # concurrent mutation, hence the unreachable ignore).
    with _guard:
        if _is_primary:
            return True  # type: ignore[unreachable]
        if _lock is None:
            _lock = FileLock(_lock_path())
        try:
            _lock.acquire(timeout=0)
            _is_primary = True
            logger.info("primary worker elected pid=%d lock=%s", os.getpid(), _lock_path())
        except Timeout:
            _is_primary = False
            logger.debug("non-primary worker pid=%d lock=%s", os.getpid(), _lock_path())
        except OSError as exc:
            # Permission error, missing parent dir, read-only temp dir, etc.
            # Fail closed (non-primary) rather than crashing initialize().
            _is_primary = False
            logger.warning("primary worker election failed pid=%d lock=%s err=%s", os.getpid(), _lock_path(), exc)
        return _is_primary
