# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sandbox_start_method.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Establish by test which multiprocessing start methods can run a validation worker.
The answer decides whether non-Linux platforms get a real sandbox.
"""

# Standard
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import re

# Third-Party
import pytest

METHODS = [m for m in ("fork", "spawn", "forkserver") if m in multiprocessing.get_all_start_methods()]


def _worker(pattern: str, text: str) -> bool:
    """Run one match inside a worker process.

    Args:
        pattern: Regex source.
        text: Subject to search.

    Returns:
        True when the pattern matches the subject.
    """
    return re.compile(pattern).search(text) is not None


@pytest.mark.parametrize("method", METHODS)
def test_start_method_runs_a_worker(method):
    """Each available start method must run a module-level worker function.

    Args:
        method: Multiprocessing start method under test.
    """
    ctx = multiprocessing.get_context(method)
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as pool:
        assert pool.submit(_worker, r"^a+$", "aaa").result(timeout=60) is True


@pytest.mark.parametrize("method", METHODS)
def test_start_method_worker_is_killable(method):
    """A worker stuck in catastrophic backtracking must die when killed.

    Args:
        method: Multiprocessing start method under test.
    """
    ctx = multiprocessing.get_context(method)
    pool = ProcessPoolExecutor(max_workers=1, mp_context=ctx)
    try:
        pool.submit(_worker, r"^a+$", "a").result(timeout=60)
        future = pool.submit(_worker, r"^(a+)+$", "a" * 40 + "b")
        with pytest.raises(Exception):
            future.result(timeout=1.0)
        processes = list((getattr(pool, "_processes", None) or {}).values())
        assert processes, "pool exposes no _processes mapping; the kill route is gone"
        for process in processes:
            process.kill()
        for process in processes:
            process.join(timeout=30)
            assert not process.is_alive()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
