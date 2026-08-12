# -*- coding: utf-8 -*-
"""Tests for sandboxed jq filter execution."""

# Standard
import sys

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.jq_runner import JqFilterError, JqFilterTimeout, run_jq_filter, shutdown_jq_pool, start_jq_pool, subprocess_mode_available

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

    Asserts absence of the parent's values rather than an exactly empty mapping.
    Under pytest the child reliably comes back with terminal-geometry variables
    (``LINES``, ``COLUMNS``) repopulated after the initializer runs, so an
    ``== [{}]`` assertion fails for reasons that have nothing to do with the
    security property. Verified separately: in a clean process the worker's
    ``$ENV`` is exactly ``{}`` and ``os.getenv`` of a seeded secret returns None.
    """
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
