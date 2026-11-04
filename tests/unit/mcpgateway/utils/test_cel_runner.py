# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_cel_runner.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for sandboxed CEL expression evaluation.
"""

# Standard
import multiprocessing
import os
import sys

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils import cel_runner
from mcpgateway.utils.cel_runner import (
    CelBusy,
    CelError,
    CelEvaluationError,
    CelSyntaxError,
    CelTimeout,
    evaluate_expression,
    MAX_EXPRESSION_LENGTH,
    shutdown_cel_pool,
    start_cel_pool,
    subprocess_mode_available,
)
from mcpgateway.utils.sandbox_pool import SandboxBusy, SandboxError, SandboxTimeout

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork-based sandbox is Linux-only")

VARIABLES = {"description": "Lists files. Example: ls | grep txt", "tool_name": "list_files"}
GLOBAL_POLICY = '!(description.contains("&&") || description.contains("||") || description.contains("$("))'
PER_TOOL_POLICY = 'tool_name == "run_query" || !description.contains("|")'


def test_cel_settings_defaults():
    """The sandbox is on by default with a short wall-clock limit."""
    assert settings.cel_execution == "subprocess"
    assert settings.cel_timeout_seconds == 1.0
    assert settings.cel_workers == 2


@pytest.fixture
def inprocess(monkeypatch):
    """Run every evaluation in the test process."""
    monkeypatch.setattr(settings, "cel_execution", "inprocess")


@pytest.fixture
def cel_pool():
    """Start a fresh sandbox for one test and tear it down afterwards."""
    shutdown_cel_pool()
    start_cel_pool()
    yield
    shutdown_cel_pool()


# --- in-process evaluation -------------------------------------------------


def test_inprocess_true_and_false(inprocess):
    """A policy allows a clean description and rejects a matching one."""
    assert evaluate_expression(GLOBAL_POLICY, VARIABLES) is True
    assert evaluate_expression(GLOBAL_POLICY, {**VARIABLES, "description": "make && make test"}) is False


def test_inprocess_branches_on_tool_name(inprocess):
    """One expression gives different answers for different tools."""
    assert evaluate_expression(PER_TOOL_POLICY, {"description": "SELECT a | b", "tool_name": "run_query"}) is True
    assert evaluate_expression(PER_TOOL_POLICY, {"description": "SELECT a | b", "tool_name": "delete_rows"}) is False


def test_inprocess_syntax_error(inprocess):
    """An unparseable expression raises CelSyntaxError."""
    with pytest.raises(CelSyntaxError):
        evaluate_expression('description.contains("&&"', VARIABLES)


def test_inprocess_unknown_variable_names_the_available_ones(inprocess):
    """A reference to an unsupplied variable is rejected before execution."""
    with pytest.raises(CelEvaluationError, match=r"unknown variable\(s\) \['gateway_id'\]; available: \['description', 'tool_name'\]"):
        evaluate_expression('gateway_id == "g1"', VARIABLES)


def test_name_check_catches_a_short_circuited_typo(inprocess):
    """CEL never evaluates the right side of ``true || ...``, so only the name check sees the typo."""
    with pytest.raises(CelEvaluationError, match=r"unknown variable\(s\) \['gatewy_id'\]"):
        evaluate_expression('true || gatewy_id == "g1"', VARIABLES)


def test_comprehension_loop_variables_are_rejected(inprocess):
    """Loop variables count as referenced names, so comprehension macros are refused."""
    with pytest.raises(CelEvaluationError, match=r"unknown variable\(s\) \['cmd'\]"):
        evaluate_expression('["ls", "cat"].exists(cmd, description.contains(cmd))', VARIABLES)


def test_inprocess_unknown_function(inprocess):
    """A runtime failure inside the library is reported as an evaluation error."""
    with pytest.raises(CelEvaluationError, match="split"):
        evaluate_expression('description.split(" ").size() > 0', VARIABLES)


def test_inprocess_non_boolean_result(inprocess):
    """An expression that evaluates to something other than a boolean is rejected."""
    with pytest.raises(CelEvaluationError, match="returned str, expected bool"):
        evaluate_expression("description", VARIABLES)


def test_expression_length_cap_runs_before_compilation(inprocess, monkeypatch):
    """An over-long expression is refused without being parsed."""
    monkeypatch.setattr(cel_runner, "_compile", lambda _expression: pytest.fail("compile must not run"))
    expression = "true || " * (MAX_EXPRESSION_LENGTH // 8) + "true"
    assert len(expression) > MAX_EXPRESSION_LENGTH
    with pytest.raises(CelSyntaxError, match=f"limit is {MAX_EXPRESSION_LENGTH}"):
        evaluate_expression(expression, VARIABLES)


def test_compiled_programs_are_cached(inprocess):
    """Compilation is cached so repeated evaluations stay cheap."""
    cel_runner._compile.cache_clear()  # pylint: disable=protected-access
    evaluate_expression(GLOBAL_POLICY, VARIABLES)
    evaluate_expression(GLOBAL_POLICY, VARIABLES)
    info = cel_runner._compile.cache_info()  # pylint: disable=protected-access
    assert info.misses == 1
    assert info.hits == 1


def test_unknown_worker_outcome_is_an_error():
    """A status the caller does not recognise cannot pass as a result."""
    with pytest.raises(CelError, match="unexpected CEL worker outcome"):
        cel_runner._raise_for_outcome(("mystery", None))  # pylint: disable=protected-access


# --- execution mode selection ----------------------------------------------


def test_subprocess_mode_unavailable_off_linux(monkeypatch):
    """The forked sandbox is only offered on Linux."""
    monkeypatch.setattr(sys, "platform", "darwin")
    assert subprocess_mode_available() is False


def test_subprocess_mode_off_when_configured_inprocess(inprocess):
    """The inprocess setting disables the sandbox regardless of platform."""
    assert subprocess_mode_available() is False


def test_start_cel_pool_warns_once_when_sandbox_unavailable(monkeypatch):
    """The in-process fallback is logged exactly once per process."""
    monkeypatch.setattr(cel_runner, "subprocess_mode_available", lambda: False)
    monkeypatch.setattr(cel_runner, "_FALLBACK_WARNED", False)
    calls = []
    monkeypatch.setattr(cel_runner.logger, "warning", lambda *args, **kwargs: calls.append(args))
    start_cel_pool()
    start_cel_pool()
    assert len(calls) == 1
    assert "CEL sandbox is disabled" in calls[0][0]


def test_shutdown_without_start_is_harmless():
    """Shutting down a pool that was never started does nothing."""
    shutdown_cel_pool()
    assert cel_runner._SANDBOX._current_executor() is None  # pylint: disable=protected-access


# --- forked sandbox ----------------------------------------------------------


@linux_only
def test_ordinary_expression_runs_in_worker(cel_pool):
    """A policy evaluates correctly through the sandbox."""
    assert evaluate_expression(GLOBAL_POLICY, VARIABLES) is True
    assert evaluate_expression(GLOBAL_POLICY, {**VARIABLES, "description": "$(whoami)"}) is False


@linux_only
@pytest.mark.parametrize(
    "expression,error,fragment",
    [
        ('description.contains("&&"', CelSyntaxError, "parse"),
        ('gateway_id == "g1"', CelEvaluationError, "unknown variable"),
        ("description", CelEvaluationError, "expected bool"),
    ],
)
def test_error_classes_survive_the_process_boundary(cel_pool, expression, error, fragment):
    """Each failure keeps its specific class and message when raised in a worker."""
    with pytest.raises(error, match=fragment):
        evaluate_expression(expression, VARIABLES)


@linux_only
def test_worker_environment_is_scrubbed():
    """The worker initializer leaves nothing of the parent's environment."""
    os.environ["CEL_RUNNER_CANARY"] = "present"
    try:
        parent_end, child_end = multiprocessing.get_context("fork").Pipe(duplex=False)
        process = multiprocessing.get_context("fork").Process(target=_report_environment_size, args=(child_end,))
        process.start()
        process.join(timeout=10)
        assert parent_end.recv() == 0
    finally:
        os.environ.pop("CEL_RUNNER_CANARY", None)


def _report_environment_size(conn) -> None:
    """Run the worker initializer in a forked child and report the remaining environment size.

    Args:
        conn: Pipe end to send the size through.
    """
    cel_runner._worker_init()  # pylint: disable=protected-access
    conn.send(len(os.environ))
    conn.close()


@linux_only
def test_pool_is_reused_within_a_process(cel_pool):
    """Starting an already-started pool keeps the same executor."""
    first = cel_runner._SANDBOX._current_executor()  # pylint: disable=protected-access
    start_cel_pool()
    assert cel_runner._SANDBOX._current_executor() is first  # pylint: disable=protected-access


@linux_only
def test_pool_is_rebuilt_after_pid_change(cel_pool, monkeypatch):
    """A pool inherited across a fork is replaced rather than reused."""
    monkeypatch.setattr(cel_runner._SANDBOX, "_pool_pid", -1)  # pylint: disable=protected-access
    assert evaluate_expression(GLOBAL_POLICY, VARIABLES) is True
    assert cel_runner._SANDBOX._pool_pid == os.getpid()  # pylint: disable=protected-access


def test_start_cel_pool_cleans_up_on_warmup_failure(monkeypatch):
    """A pool whose workers never answer is torn down and the failure propagates."""
    shutdown_cel_pool()
    monkeypatch.setattr(cel_runner, "subprocess_mode_available", lambda: True)

    class _NeverReadyFuture:
        def result(self, timeout=None):
            raise TimeoutError("warm-up never completed")

    class _NeverReadyPool:
        def __init__(self):
            self.shutdown_calls = []

        def submit(self, _fn, *_args):
            return _NeverReadyFuture()

        def shutdown(self, **kwargs):
            self.shutdown_calls.append(kwargs)

    failing_pool = _NeverReadyPool()
    monkeypatch.setattr(cel_runner._SANDBOX, "_build", lambda _workers: failing_pool)  # pylint: disable=protected-access
    with pytest.raises(TimeoutError):
        start_cel_pool()
    assert failing_pool.shutdown_calls == [{"wait": False, "cancel_futures": True}]
    assert cel_runner._SANDBOX._current_executor() is None  # pylint: disable=protected-access


def test_pool_failure_fails_closed(monkeypatch):
    """When the sandbox cannot be built, evaluation raises instead of running unprotected."""
    shutdown_cel_pool()
    monkeypatch.setattr(cel_runner, "subprocess_mode_available", lambda: True)
    monkeypatch.setattr(cel_runner._SANDBOX, "_build", lambda: (_ for _ in ()).throw(OSError("no fork for you")))  # pylint: disable=protected-access
    with pytest.raises(CelError, match="no fork for you"):
        evaluate_expression(GLOBAL_POLICY, VARIABLES)


@pytest.mark.parametrize(
    "sandbox_error,cel_error",
    [
        (SandboxTimeout("overran"), CelTimeout),
        (SandboxBusy("full"), CelBusy),
        (SandboxError("broken"), CelError),
    ],
)
def test_sandbox_errors_are_translated_without_losing_the_cause(monkeypatch, sandbox_error, cel_error):
    """Pool-level failures map onto the matching CEL error and keep their cause."""
    monkeypatch.setattr(cel_runner, "subprocess_mode_available", lambda: True)

    def _raise(*_args):
        raise sandbox_error

    monkeypatch.setattr(cel_runner._SANDBOX, "submit", _raise)  # pylint: disable=protected-access
    with pytest.raises(cel_error) as excinfo:
        evaluate_expression(GLOBAL_POLICY, VARIABLES)
    assert excinfo.value.__cause__ is sandbox_error
