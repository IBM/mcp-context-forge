# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_jq_runner.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for sandboxed jq filter execution.
"""

# Standard
import os
import signal
import sys
import threading
import time

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.jq_runner import JqFilterBusy, JqFilterError, JqFilterTimeout, run_jq_filter, shutdown_jq_pool, start_jq_pool, subprocess_mode_available

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork-based sandbox is Linux-only")


def test_jq_filter_settings_defaults():
    """The sandbox is on by default with a short wall-clock limit."""
    assert settings.jq_filter_execution == "subprocess"
    assert settings.jq_filter_timeout_seconds == 2.0
    assert settings.jq_filter_workers == 2


def test_inprocess_mode_applies_filter(monkeypatch):
    """In-process mode still evaluates ordinary filters correctly."""
    monkeypatch.setattr(settings, "jq_filter_execution", "inprocess")
    assert run_jq_filter(".a", {"a": 42}) == [42]


def test_inprocess_mode_reports_compile_errors(monkeypatch):
    """A malformed filter surfaces as JqFilterError, not a raw jq exception."""
    monkeypatch.setattr(settings, "jq_filter_execution", "inprocess")
    with pytest.raises(JqFilterError):
        run_jq_filter("this is not jq |||", {"a": 1})


def test_compiled_programs_are_cached():
    """Compilation is cached so repeated invocations stay cheap."""
    # First-Party
    from mcpgateway.utils.jq_runner import _compile_jq_filter

    _compile_jq_filter.cache_clear()
    _compile_jq_filter(".a")
    _compile_jq_filter(".a")
    assert _compile_jq_filter.cache_info().hits == 1


@pytest.fixture
def jq_pool():
    """Provide a started pool and tear it down afterwards."""
    start_jq_pool()
    yield
    shutdown_jq_pool()


@linux_only
def test_worker_environment_is_scrubbed(monkeypatch):
    """A worker cannot see the gateway's secrets even without the static gate.

    Deliberately does not use the ``jq_pool`` fixture: ``start_jq_pool`` now warms
    the pool by forking a worker before returning, so the fork must happen *after*
    the canary variables are set, not before. Otherwise a worker forked by the
    fixture (before this test's ``monkeypatch.setenv`` calls) would never see the
    canaries in the first place, and the assertions below would pass even with
    ``_worker_init``'s ``os.environ.clear()`` removed entirely.

    ``shutdown_jq_pool`` runs first, before the canaries are set, because
    ``start_jq_pool`` returns early and reuses any pool already built under this
    PID. Earlier tests in this file — and ``tool_service`` tests that reach
    ``extract_using_jq`` in the default subprocess mode — can leave a live pool
    behind, and without the explicit teardown this test would silently assert
    against a worker forked before the canaries existed, passing even with
    ``_worker_init``'s ``os.environ.clear()`` removed entirely.

    ``run_jq_filter`` now re-asserts the static gate itself, which would refuse
    ``$ENV`` outright. The gate is stubbed out here on purpose: the point of
    this test is that the worker-side scrub holds *without* the gate, since the
    scrub is the backstop for anything the gate misses.

    Asserts absence of the parent's values rather than an exactly empty mapping.
    Under pytest the child reliably comes back with terminal-geometry variables
    (``LINES``, ``COLUMNS``) repopulated after the initializer runs, so an
    ``== [{}]`` assertion fails for reasons that have nothing to do with the
    security property. Verified separately: in a clean process the worker's
    ``$ENV`` is exactly ``{}`` and ``os.getenv`` of a seeded secret returns None.
    """
    # First-Party
    from mcpgateway.utils import jq_runner

    shutdown_jq_pool()
    monkeypatch.setattr(jq_runner, "assert_safe_jq_filter", lambda _filter: None)
    monkeypatch.setenv("JQ_RUNNER_CANARY", "LEAKED")
    monkeypatch.setenv("JWT_SECRET_KEY", "sentinel-value-must-not-appear")

    start_jq_pool()
    try:
        worker_env = run_jq_filter("$ENV", {"a": 1})[0]

        assert "JQ_RUNNER_CANARY" not in worker_env
        assert "JWT_SECRET_KEY" not in worker_env
        assert "sentinel-value-must-not-appear" not in str(worker_env)
    finally:
        shutdown_jq_pool()


@linux_only
def test_ordinary_filter_runs_in_worker(jq_pool):
    """Normal filters produce the same results through the sandbox."""
    assert run_jq_filter(".a", {"a": 42}) == [42]


@linux_only
def test_runaway_filter_times_out_and_pool_recovers(jq_pool, monkeypatch):
    """A non-terminating filter is killed, and the next call still works."""
    monkeypatch.setattr(settings, "jq_filter_timeout_seconds", 1.0)
    with pytest.raises(JqFilterTimeout):
        run_jq_filter("reduce range(100000000000) as $i (0; .+1)", {"a": 1})
    assert run_jq_filter(".a", {"a": 7}) == [7]


@linux_only
def test_private_processes_attribute_still_exists(jq_pool):
    """The kill path depends on a private CPython attribute; fail loudly if it moves.

    ``ProcessPoolExecutor`` starts workers lazily, so ``_processes`` would be an
    empty dict until the first submit — ``start_jq_pool``'s warm-up submit already
    populates it by the time the ``jq_pool`` fixture returns, but this still runs
    a filter of its own before asserting so the check does not depend on that
    warm-up behavior.
    """
    # First-Party
    from mcpgateway.utils import jq_runner

    assert run_jq_filter(".a", {"a": 1}) == [1]
    assert getattr(jq_runner._POOL, "_processes", None), "ProcessPoolExecutor._processes is gone; the timeout kill path needs rewriting"  # pylint: disable=protected-access


def test_subprocess_mode_unavailable_off_linux(monkeypatch):
    """Non-Linux platforms fall back to in-process execution."""
    monkeypatch.setattr(sys, "platform", "darwin")
    assert subprocess_mode_available() is False


def test_pool_failure_fails_closed(monkeypatch):
    """If the pool cannot be built, filters error rather than silently running in-process."""
    # First-Party
    from mcpgateway.utils import jq_runner

    shutdown_jq_pool()
    monkeypatch.setattr(jq_runner, "subprocess_mode_available", lambda: True)
    monkeypatch.setattr(jq_runner, "_build_pool", lambda: (_ for _ in ()).throw(OSError("no fork for you")))
    with pytest.raises(JqFilterError):
        run_jq_filter(".a", {"a": 1})


@linux_only
def test_pool_is_reused_within_a_process(jq_pool):
    """Repeated startup calls do not churn the pool."""
    # First-Party
    from mcpgateway.utils import jq_runner

    first = jq_runner._POOL  # pylint: disable=protected-access
    start_jq_pool()
    assert jq_runner._POOL is first  # pylint: disable=protected-access


@linux_only
def test_pool_is_rebuilt_after_pid_change(jq_pool, monkeypatch):
    """A pool inherited across a fork is discarded rather than reused."""
    # First-Party
    from mcpgateway.utils import jq_runner

    monkeypatch.setattr(jq_runner, "_POOL_PID", -1)
    assert run_jq_filter(".a", {"a": 5}) == [5]
    assert jq_runner._POOL_PID == os.getpid()  # pylint: disable=protected-access


def test_run_jq_filter_reasserts_the_static_gate(monkeypatch):
    """The runner refuses a restricted built-in even if a caller skips the gate."""
    monkeypatch.setattr(settings, "jq_filter_execution", "inprocess")
    with pytest.raises(ValueError, match="restricted built-in"):
        run_jq_filter("$ENV", {"a": 1})


def test_start_jq_pool_warns_once_when_sandbox_unavailable(monkeypatch):
    """A disabled sandbox logs a warning on first call and stays silent after."""
    # First-Party
    from mcpgateway.utils import jq_runner

    monkeypatch.setattr(jq_runner, "subprocess_mode_available", lambda: False)
    monkeypatch.setattr(jq_runner, "_FALLBACK_WARNED", False)
    calls = []
    monkeypatch.setattr(jq_runner.logger, "warning", lambda *a, **k: calls.append(a))

    start_jq_pool()
    start_jq_pool()

    assert len(calls) == 1
    assert jq_runner._FALLBACK_WARNED is True  # pylint: disable=protected-access


def test_start_jq_pool_cleans_up_on_warmup_failure(monkeypatch):
    """A pool that fails its warm-up submit is shut down, and the failure propagates."""
    # First-Party
    from mcpgateway.utils import jq_runner

    shutdown_jq_pool()
    monkeypatch.setattr(jq_runner, "subprocess_mode_available", lambda: True)

    class _FailingFuture:
        def result(self, timeout=None):  # pylint: disable=unused-argument
            raise TimeoutError("warm-up never completed")

    class _FailingPool:
        def __init__(self):
            self.shutdown_calls = []

        def submit(self, *_args, **_kwargs):
            return _FailingFuture()

        def shutdown(self, wait=False, cancel_futures=False):  # pylint: disable=unused-argument
            self.shutdown_calls.append((wait, cancel_futures))

    failing_pool = _FailingPool()
    monkeypatch.setattr(jq_runner, "_build_pool", lambda: failing_pool)

    with pytest.raises(TimeoutError):
        start_jq_pool()

    assert failing_pool.shutdown_calls == [(False, True)]
    assert jq_runner._POOL is None  # pylint: disable=protected-access


def test_kill_workers_logs_when_process_kill_raises(monkeypatch):
    """A process that refuses to die is logged, not left to crash the caller."""
    # First-Party
    from mcpgateway.utils import jq_runner

    class _StubbornProcess:
        def kill(self):
            raise OSError("no such process")

    class _StubPool:
        def __init__(self):
            self._processes = {1: _StubbornProcess()}
            self.shutdown_calls = []

        def shutdown(self, wait=False, cancel_futures=False):  # pylint: disable=unused-argument
            self.shutdown_calls.append((wait, cancel_futures))

    warnings = []
    monkeypatch.setattr(jq_runner.logger, "warning", lambda *a, **k: warnings.append(a))

    pool = _StubPool()
    jq_runner._kill_workers(pool)  # pylint: disable=protected-access

    assert len(warnings) == 1
    assert pool.shutdown_calls == [(False, True)]


def test_run_jq_filter_wraps_a_generic_submit_failure(monkeypatch):
    """An exception from submit/result that isn't a timeout or a broken pool is still wrapped."""
    # First-Party
    from mcpgateway.utils import jq_runner

    class _BrokenSubmitPool:
        def __init__(self):
            setattr(self, jq_runner._GATE_ATTR, threading.Semaphore(1))  # pylint: disable=protected-access

        def submit(self, *_args, **_kwargs):
            raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr(jq_runner, "subprocess_mode_available", lambda: True)
    monkeypatch.setattr(jq_runner, "_ensure_pool", lambda: _BrokenSubmitPool())

    with pytest.raises(JqFilterError):
        run_jq_filter(".a", {"a": 1})


def test_run_jq_filter_does_not_double_wrap_a_jq_filter_error(monkeypatch):
    """A JqFilterError raised directly from the pool is re-raised, not re-wrapped."""
    # First-Party
    from mcpgateway.utils import jq_runner

    original = JqFilterError("already the right shape")

    class _DirectlyFailingPool:
        def __init__(self):
            setattr(self, jq_runner._GATE_ATTR, threading.Semaphore(1))  # pylint: disable=protected-access

        def submit(self, *_args, **_kwargs):
            raise original

    monkeypatch.setattr(jq_runner, "subprocess_mode_available", lambda: True)
    monkeypatch.setattr(jq_runner, "_ensure_pool", lambda: _DirectlyFailingPool())

    with pytest.raises(JqFilterError) as excinfo:
        run_jq_filter(".a", {"a": 1})

    assert excinfo.value is original


def _worker_processes():
    """Return the live ``Process`` objects of the current pool.

    Returns:
        A list of ``multiprocessing.Process`` objects owned by the pool.
    """
    # First-Party
    from mcpgateway.utils import jq_runner

    return list(getattr(jq_runner._POOL, "_processes", {}).values())  # pylint: disable=protected-access


def _wait_until(predicate, timeout=15.0):
    """Poll a predicate until it holds or the deadline passes.

    Args:
        predicate: Zero-argument callable returning a truthy value when done.
        timeout: Seconds to keep polling.

    Returns:
        The last value the predicate returned.
    """
    deadline = time.monotonic() + timeout
    result = predicate()
    while not result and time.monotonic() < deadline:
        time.sleep(0.05)
        result = predicate()
    return result


@linux_only
def test_pool_recovers_after_a_worker_dies_abnormally(monkeypatch):
    """An OOM-style worker death must not brick filtering for the whole process.

    ``ProcessPoolExecutor`` marks itself permanently broken when a worker dies
    outside its control, so every later ``submit`` raises ``BrokenProcessPool``.
    Only the timeout path used to drop the pool, which left an attacker able to
    disable filtering for the lifetime of the gateway worker with a single
    unbounded-allocation filter. SIGKILL stands in for the OOM killer here.
    """
    # First-Party
    from mcpgateway.utils import jq_runner

    shutdown_jq_pool()
    monkeypatch.setattr(settings, "jq_filter_workers", 1)
    start_jq_pool()
    try:
        broken = jq_runner._POOL  # pylint: disable=protected-access
        processes = _worker_processes()
        assert processes, "warm-up should have forked a worker"
        for process in processes:
            os.kill(process.pid, signal.SIGKILL)

        assert _wait_until(lambda: bool(getattr(broken, "_broken", False))), "ProcessPoolExecutor never reported the dead worker; the recovery path needs rechecking"

        with pytest.raises(JqFilterError):
            run_jq_filter(".a", {"a": 1})

        # The broken executor must have been discarded, not handed out again.
        assert jq_runner._POOL is not broken  # pylint: disable=protected-access
        assert run_jq_filter(".a", {"a": 1}) == [1]
        assert run_jq_filter(".a", {"a": 2}) == [2]
    finally:
        shutdown_jq_pool()


@linux_only
def test_kill_targets_the_given_pool_even_after_pool_is_replaced(monkeypatch):
    """A timeout kills the pool its filter ran in, not whichever pool is current.

    The previous identity check bailed out whenever ``_POOL`` had moved on,
    which orphaned the runaway worker of the pool that actually overran.
    """
    # First-Party
    from mcpgateway.utils import jq_runner

    shutdown_jq_pool()
    monkeypatch.setattr(settings, "jq_filter_workers", 1)
    start_jq_pool()
    stale = jq_runner._POOL  # pylint: disable=protected-access
    stale_processes = _worker_processes()
    assert stale_processes

    # Simulate another thread having replaced the global pool meanwhile.
    replacement = jq_runner._build_pool()  # pylint: disable=protected-access
    jq_runner._POOL = replacement  # pylint: disable=protected-access
    jq_runner._POOL_PID = os.getpid()  # pylint: disable=protected-access
    try:
        jq_runner._kill_pool_workers(stale)  # pylint: disable=protected-access

        assert _wait_until(lambda: all(not p.is_alive() for p in stale_processes)), "the stale pool's workers survived the kill"
        # The newer pool is untouched and still usable.
        assert jq_runner._POOL is replacement  # pylint: disable=protected-access
        assert run_jq_filter(".a", {"a": 3}) == [3]
    finally:
        shutdown_jq_pool()


@linux_only
def test_shutdown_kills_a_worker_running_a_runaway_filter(monkeypatch):
    """Shutdown must not leave a non-terminating filter running.

    ``shutdown(wait=False, cancel_futures=True)`` cancels queued work but cannot
    stop a worker mid-filter, and ``ProcessPoolExecutor``'s own ``atexit`` hook
    then blocks interpreter exit joining it. Reproduces the composed race: a
    hostile filter is running, shutdown clears the global pool, and the caller's
    own timeout fires only afterwards.
    """
    shutdown_jq_pool()
    monkeypatch.setattr(settings, "jq_filter_workers", 1)
    monkeypatch.setattr(settings, "jq_filter_timeout_seconds", 30.0)
    start_jq_pool()
    processes = _worker_processes()
    assert processes

    errors = []

    def _runaway():
        try:
            run_jq_filter("reduce range(100000000000) as $i (0; .+1)", {"a": 1})
        except Exception as exc:  # pylint: disable=broad-except
            errors.append(exc)

    thread = threading.Thread(target=_runaway, daemon=True)
    thread.start()
    try:
        # Let the worker actually pick the job up before shutting down.
        assert _wait_until(lambda: all(p.is_alive() for p in processes), timeout=5.0)
        time.sleep(0.5)

        shutdown_jq_pool()

        assert _wait_until(lambda: all(not p.is_alive() for p in processes)), "the runaway worker outlived shutdown_jq_pool"
        thread.join(timeout=15.0)
        assert not thread.is_alive(), "the caller stayed blocked on a worker that shutdown was supposed to kill"
        assert errors and isinstance(errors[0], JqFilterError)
    finally:
        shutdown_jq_pool()


@linux_only
def test_a_full_pool_fails_fast_instead_of_queueing(monkeypatch):
    """A submission with no free worker is refused immediately, not queued.

    Reproduces the reported race precisely: with every worker already running
    a filter, a further call must not sit in ProcessPoolExecutor's internal
    queue consuming the same wall-clock budget meant for runaway detection --
    it must fail fast with JqFilterBusy, and it must not touch the pool.
    """
    shutdown_jq_pool()
    monkeypatch.setattr(settings, "jq_filter_workers", 1)
    monkeypatch.setattr(settings, "jq_filter_timeout_seconds", 5.0)
    start_jq_pool()
    processes_before = _worker_processes()

    busy_thread_result = []

    def _occupy_the_only_worker():
        try:
            run_jq_filter("reduce range(100000000000) as $i (0; .+1)", {"a": 1})
        except Exception as exc:  # pylint: disable=broad-except
            busy_thread_result.append(exc)

    occupier = threading.Thread(target=_occupy_the_only_worker, daemon=True)
    occupier.start()
    try:
        assert _wait_until(lambda: all(p.is_alive() for p in processes_before), timeout=5.0)
        time.sleep(0.3)  # let the occupier's filter actually start running

        start = time.monotonic()
        with pytest.raises(JqFilterBusy):
            run_jq_filter(".a", {"a": 1})
        elapsed = time.monotonic() - start

        # Fails fast: nowhere near the 5s per-filter timeout budget.
        assert elapsed < 1.0, f"a full pool should fail immediately, took {elapsed}s"

        # The occupier's worker was never touched by the second call.
        assert all(p.is_alive() for p in processes_before)
    finally:
        occupier.join(timeout=10.0)
        shutdown_jq_pool()

    assert busy_thread_result and isinstance(busy_thread_result[0], JqFilterTimeout)


@linux_only
def test_gate_is_released_after_a_normal_call(jq_pool):
    """A completed call frees its slot for the next one, even with one worker."""
    # First-Party
    from mcpgateway.utils import jq_runner

    gate = getattr(jq_runner._POOL, jq_runner._GATE_ATTR)  # pylint: disable=protected-access
    for _ in range(3):
        assert run_jq_filter(".a", {"a": 1}) == [1]
    # Every acquire in the loop above was matched by a release.
    assert gate.acquire(blocking=False)
    gate.release()


def test_jq_filter_busy_is_a_jq_filter_error():
    """JqFilterBusy is catchable alongside every other jq failure mode."""
    assert issubclass(JqFilterBusy, JqFilterError)
    assert not issubclass(JqFilterBusy, JqFilterTimeout)
