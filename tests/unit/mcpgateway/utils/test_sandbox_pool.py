# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sandbox_pool.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the killable worker pool shared by jq and schema validation.
"""

# Standard
import os
import re
import threading
import time

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.sandbox_pool import SandboxBusy, SandboxError, SandboxPool, SandboxTimeout


def _echo(value: str) -> str:
    """Return the value unchanged, from inside a worker.

    Args:
        value: Any picklable string.

    Returns:
        The same string.
    """
    return value


def _runaway(pattern: str, text: str) -> bool:
    """Run a match that may never terminate.

    Args:
        pattern: Regex source.
        text: Subject to search.

    Returns:
        True when the pattern matches.
    """
    return re.compile(pattern).search(text) is not None


@pytest.fixture(name="pool")
def _pool():
    """Provide a started one-worker pool and tear it down afterwards.

    Yields:
        A running SandboxPool.
    """
    instance = SandboxPool(name="test", workers_fn=lambda: 1, timeout_fn=lambda: 1.0)
    instance.start()
    yield instance
    instance.shutdown()


def test_submit_returns_worker_result(pool):
    """A normal call round-trips through the worker.

    Args:
        pool: A started one-worker sandbox pool.
    """
    assert pool.submit(_echo, "hello") == "hello"


def test_overrun_raises_timeout_and_kills_the_worker(pool):
    """A runaway match must not outlive its budget.

    Args:
        pool: A started one-worker sandbox pool.
    """
    start = time.perf_counter()
    with pytest.raises(SandboxTimeout):
        pool.submit(_runaway, r"^(a+)+$", "a" * 40 + "b")
    assert time.perf_counter() - start < 10.0


def test_pool_serves_the_next_call_after_a_kill(pool):
    """Killing a worker must not brick the pool.

    Args:
        pool: A started one-worker sandbox pool.
    """
    with pytest.raises(SandboxTimeout):
        pool.submit(_runaway, r"^(a+)+$", "a" * 40 + "b")
    assert pool.submit(_echo, "still here") == "still here"


def test_busy_pool_raises_busy_not_timeout():
    """No free worker is a retryable condition, not a runaway."""
    instance = SandboxPool(name="test-busy", workers_fn=lambda: 1, timeout_fn=lambda: 5.0)
    instance.start()
    try:
        started = threading.Event()

        def hold():
            """Occupy the single worker."""
            started.set()
            try:
                instance.submit(_runaway, r"^(a+)+$", "a" * 40 + "b")
            except Exception:  # pylint: disable=broad-except
                pass

        thread = threading.Thread(target=hold, daemon=True)
        thread.start()
        started.wait(timeout=5)
        time.sleep(0.3)
        with pytest.raises(SandboxBusy):
            instance.submit(_echo, "nope")
    finally:
        instance.shutdown()


def test_settings_are_read_at_call_time_not_construction():
    """A runtime change to the timeout must take effect.

    jq tests monkeypatch settings after import. A pool that froze them in its constructor
    would turn those tests into silent no-ops.
    """
    budget = {"value": 30.0}
    instance = SandboxPool(name="test-fresh", workers_fn=lambda: 1, timeout_fn=lambda: budget["value"])
    instance.start()
    try:
        budget["value"] = 0.5
        start = time.perf_counter()
        with pytest.raises(SandboxTimeout):
            instance.submit(_runaway, r"^(a+)+$", "a" * 40 + "b")
        assert time.perf_counter() - start < 5.0, "the pool used the construction-time timeout"
    finally:
        instance.shutdown()


def test_a_raising_timeout_function_does_not_leak_a_permit():
    """A failing budget read must not consume a worker slot forever.

    Reading the budget after taking a permit leaves a window with no release path. One
    failure there would strand the permit and make every later call return SandboxBusy.
    """
    state = {"raising": False}

    def timeout_fn():
        """Return the budget, or fail once the test arms the failure.

        Returns:
            The wall-clock limit in seconds.

        Raises:
            RuntimeError: When the test has armed the failure.
        """
        if state["raising"]:
            raise RuntimeError("settings unavailable")
        return 5.0

    instance = SandboxPool(name="test-leak", workers_fn=lambda: 1, timeout_fn=timeout_fn)
    instance.start()
    try:
        state["raising"] = True
        with pytest.raises(RuntimeError):
            instance.submit(_echo, "boom")

        state["raising"] = False
        assert instance.submit(_echo, "still here") == "still here"
    finally:
        instance.shutdown()


def test_gate_is_stamped_on_the_executor(pool):
    """The admission gate must travel with the executor it admits to.

    Args:
        pool: A started one-worker sandbox pool.
    """
    executor = pool._current_executor()  # pylint: disable=protected-access
    assert getattr(executor, "_mcpgateway_submit_gate", None) is not None


def test_submit_does_not_double_wrap_a_sandbox_error():
    """A SandboxError raised from the executor is re-raised, not re-wrapped."""
    original = SandboxError("already the right shape")

    class _DirectlyFailingPool:
        """An executor stand-in that fails with an already-shaped error."""

        def __init__(self):
            """Stamp the admission gate the pool expects."""
            setattr(self, "_mcpgateway_submit_gate", threading.Semaphore(1))

        def submit(self, *_args, **_kwargs):
            """Fail with the pre-built error.

            Args:
                *_args: Ignored.
                **_kwargs: Ignored.

            Raises:
                SandboxError: Always.
            """
            raise original

    instance = SandboxPool(name="test-wrap", workers_fn=lambda: 1, timeout_fn=lambda: 5.0)
    instance._pool = _DirectlyFailingPool()  # pylint: disable=protected-access
    instance._pool_pid = os.getpid()  # pylint: disable=protected-access

    with pytest.raises(SandboxError) as excinfo:
        instance.submit(_echo, "x")

    assert excinfo.value is original
