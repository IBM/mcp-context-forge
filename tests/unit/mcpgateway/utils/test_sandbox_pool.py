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
from mcpgateway.utils import sandbox_pool
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


def _slow_init() -> None:
    """Stand in for a worker start-up that takes longer than a tight per-call budget."""
    time.sleep(0.3)


def test_rebuild_after_a_kill_warms_workers_outside_the_call_budget():
    """The first call on a pool rebuilt after a kill must not pay for process start-up under its own timeout."""
    instance = SandboxPool(name="test", workers_fn=lambda: 1, timeout_fn=lambda: 0.1, initializer=_slow_init)
    instance.start()
    try:
        with pytest.raises(SandboxTimeout):
            instance.submit(_runaway, r"^(a+)+$", "a" * 40 + "b")
        assert instance._current_executor() is None
        assert instance.submit(_echo, "warm") == "warm"
    finally:
        instance.shutdown()


class _NeverReadyFuture:
    """A warm-up future that never completes."""

    def result(self, timeout=None):  # pylint: disable=unused-argument
        """Fail the way a stuck worker start-up does.

        Args:
            timeout: Ignored.

        Raises:
            TimeoutError: Always.
        """
        raise TimeoutError("warm-up never completed")


class _NeverReadyPool:
    """Stand in for an executor whose workers never come up."""

    def __init__(self):
        self.shutdown_calls = []

    def submit(self, _fn, *_args):
        """Hand back a future that will time out.

        Args:
            _fn: Ignored.
            *_args: Ignored.

        Returns:
            A future whose result never arrives.
        """
        return _NeverReadyFuture()

    def shutdown(self, **kwargs):
        """Record how the pool was torn down.

        Args:
            **kwargs: The shutdown options used.
        """
        self.shutdown_calls.append(kwargs)


def _kill_pool(instance: SandboxPool) -> None:
    """Drive a started pool through a timeout so its workers are killed and discarded.

    Args:
        instance: A started SandboxPool with a short timeout.
    """
    with pytest.raises(SandboxTimeout):
        instance.submit(_runaway, r"^(a+)+$", "a" * 40 + "b")
    assert instance._current_executor() is None  # pylint: disable=protected-access


def test_rebuild_warmup_failure_raises_sandbox_error_and_leaves_pool_empty(monkeypatch):
    """A rebuild whose workers never come up fails the call and tears the half-built pool down."""
    instance = SandboxPool(name="test", workers_fn=lambda: 1, timeout_fn=lambda: 0.1)
    instance.start()
    try:
        _kill_pool(instance)
        failing_pool = _NeverReadyPool()
        monkeypatch.setattr(instance, "_build", lambda _workers: failing_pool)
        with pytest.raises(SandboxError, match="warm-up never completed"):
            instance.submit(_echo, "x")
        assert failing_pool.shutdown_calls == [{"wait": False, "cancel_futures": True}]
        assert instance._current_executor() is None  # pylint: disable=protected-access
    finally:
        instance.shutdown()


def test_pool_retries_build_after_failed_rebuild(monkeypatch):
    """One failed rebuild does not wedge the pool: the next call builds again and succeeds."""
    instance = SandboxPool(name="test", workers_fn=lambda: 1, timeout_fn=lambda: 0.1)
    instance.start()
    try:
        _kill_pool(instance)
        real_build = instance._build  # pylint: disable=protected-access
        attempts = []

        def flaky_build(workers):
            attempts.append(workers)
            if len(attempts) == 1:
                return _NeverReadyPool()
            return real_build(workers)

        monkeypatch.setattr(instance, "_build", flaky_build)
        with pytest.raises(SandboxError):
            instance.submit(_echo, "x")
        assert instance.submit(_echo, "recovered") == "recovered"
        assert attempts == [1, 1]
    finally:
        instance.shutdown()


def test_raising_timeout_function_during_rebuild_is_wrapped():
    """A settings read that blows up inside the warm-up surfaces as SandboxError, not a bare exception."""
    budgets = iter([0.1, 0.1])

    def timeout_fn():
        try:
            return next(budgets)
        except StopIteration:
            raise RuntimeError("settings unavailable")  # pylint: disable=raise-missing-from

    instance = SandboxPool(name="test", workers_fn=lambda: 1, timeout_fn=timeout_fn)
    instance.start()  # first budget: start-up warm-up
    try:
        _kill_pool(instance)  # second budget: the call that times out
        with pytest.raises(SandboxError, match="settings unavailable"):
            instance.submit(_echo, "x")  # third read raises inside _build_warm
        assert instance._current_executor() is None  # pylint: disable=protected-access
    finally:
        instance.shutdown()


def test_concurrent_calls_after_a_kill_build_one_pool(monkeypatch):
    """Two callers arriving during a rebuild share one new pool instead of forking twice."""
    instance = SandboxPool(name="test", workers_fn=lambda: 2, timeout_fn=lambda: 0.5, initializer=_slow_init)
    instance.start()
    try:
        _kill_pool(instance)
        real_build = instance._build  # pylint: disable=protected-access
        builds = []

        def counting_build(workers):
            builds.append(workers)
            return real_build(workers)

        monkeypatch.setattr(instance, "_build", counting_build)
        results = {}

        def call(label):
            results[label] = instance.submit(_echo, label)

        threads = [threading.Thread(target=call, args=(label,)) for label in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results == {"a": "a", "b": "b"}
        assert builds == [2]
    finally:
        instance.shutdown()


def test_private_idle_permit_attribute_still_exists(pool):
    """The kill path hands the executor one idle permit per killed worker; pin the private name it uses."""
    permits = getattr(pool._current_executor(), "_idle_worker_semaphore", None)  # pylint: disable=protected-access
    assert isinstance(permits, type(threading.Semaphore())), "ProcessPoolExecutor._idle_worker_semaphore is gone; the kill path's replacement guard needs rewriting"


class _KillableProcess:
    """A worker process stand-in that records whether it was killed."""

    def __init__(self):
        self.killed = False

    def kill(self):
        """Record the kill."""
        self.killed = True


class _FakeExecutor:
    """Just enough of ProcessPoolExecutor for the discard path."""

    def __init__(self, worker_count: int):
        self._processes = {pid: _KillableProcess() for pid in range(worker_count)}
        self._idle_worker_semaphore = threading.Semaphore(0)
        self.shutdown_calls = []

    def shutdown(self, **kwargs):
        """Record how the pool was torn down.

        Args:
            **kwargs: The shutdown options used.
        """
        self.shutdown_calls.append(kwargs)


def test_discard_hands_the_executor_one_idle_permit_per_killed_worker():
    """Killing N workers leaves N idle permits so the manager thread never forks a replacement."""
    instance = SandboxPool(name="test", workers_fn=lambda: 3, timeout_fn=lambda: 1.0)
    fake = _FakeExecutor(worker_count=3)
    setattr(fake, sandbox_pool._OWNER_PID_ATTR, os.getpid())  # pylint: disable=protected-access
    instance._pool = fake  # pylint: disable=protected-access
    instance._pool_pid = os.getpid()  # pylint: disable=protected-access

    instance.shutdown()

    assert all(process.killed for process in fake._processes.values())  # pylint: disable=protected-access
    assert fake.shutdown_calls == [{"wait": False, "cancel_futures": True}]
    assert [fake._idle_worker_semaphore.acquire(blocking=False) for _ in range(4)] == [True, True, True, False]  # pylint: disable=protected-access
    assert instance._current_executor() is None  # pylint: disable=protected-access


def test_shutdown_kills_a_worker_running_a_runaway_call():
    """Shutdown must not leave a running call behind, nor its caller blocked.

    ``ProcessPoolExecutor.shutdown`` cannot stop a running task, and its own
    ``atexit`` hook then blocks interpreter exit joining the worker. Reproduces
    the race: a runaway call is running, shutdown clears the pool, and the
    caller's own timeout would fire only afterwards.
    """
    instance = SandboxPool(name="test-shutdown", workers_fn=lambda: 1, timeout_fn=lambda: 30.0)
    instance.start()
    processes = list(instance._current_executor()._processes.values())  # pylint: disable=protected-access
    assert processes
    started = threading.Event()
    errors = []

    def runaway():
        """Occupy the single worker with a call that never returns on its own."""
        started.set()
        try:
            instance.submit(_runaway, r"^(a+)+$", "a" * 40 + "b")
        except Exception as exc:  # pylint: disable=broad-except
            errors.append(exc)

    thread = threading.Thread(target=runaway, daemon=True)
    thread.start()
    started.wait(timeout=5)
    time.sleep(0.5)
    try:
        instance.shutdown()
        deadline = time.monotonic() + 15.0
        while any(p.is_alive() for p in processes) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not any(p.is_alive() for p in processes), "the runaway worker outlived shutdown"
        thread.join(timeout=15.0)
        assert not thread.is_alive(), "the caller stayed blocked on a worker that shutdown killed"
        assert errors and isinstance(errors[0], SandboxError)
    finally:
        instance.shutdown()


def test_start_reads_worker_count_once():
    """Starting a pool must not evaluate its worker-count callable twice."""
    calls = 0

    def workers_fn():
        """Count worker setting reads.

        Returns:
            One worker.
        """
        nonlocal calls
        calls += 1
        return 1

    instance = SandboxPool(name="test-worker-count", workers_fn=workers_fn, timeout_fn=lambda: 5.0)
    try:
        instance.start()
        assert calls == 1
    finally:
        instance.shutdown()


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
