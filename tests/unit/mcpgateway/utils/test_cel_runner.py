# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_cel_runner.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for sandboxed CEL expression evaluation.
"""

# Standard
from datetime import datetime, timedelta, timezone
import os
import sys
import time

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
    check_expression,
    evaluate_expression,
    evaluate_value,
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
    assert settings.cel_filter_timeout_seconds == 2.0
    assert settings.cel_filter_workers == 2


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


def test_comprehension_loop_variables_are_not_unknown(inprocess):
    """A name bound by a comprehension macro is not a variable the caller must supply."""
    assert evaluate_expression('["rm", "cat"].exists(cmd, description.contains(cmd))', VARIABLES) is False
    assert evaluate_expression('["rm", "grep"].exists(cmd, description.contains(cmd))', VARIABLES) is True


def test_loop_variable_used_outside_its_macro_is_still_caught(inprocess):
    """A loop name mentioned outside the macro that binds it is a real unknown variable."""
    with pytest.raises(CelEvaluationError, match="unknown variable"):
        evaluate_expression('["ls"].exists(cmd, true) && cmd == "x"', VARIABLES)
    with pytest.raises(CelEvaluationError, match="unknown variable"):
        check_expression("response.items.map(i, i.n) + [i]", {"response"})


def test_macro_text_inside_a_string_literal_binds_nothing(inprocess):
    """A string literal that spells a macro call does not make its name a bound loop variable."""
    with pytest.raises(CelEvaluationError, match="unknown variable"):
        check_expression('response.user.name + ".map(secret," + secret', {"response"})


def test_string_literal_cannot_unbind_a_loop_variable(inprocess):
    """Text inside a string literal is not a mention of the loop name outside its macro."""
    check_expression('response.items.map(i, i.name + ") + [i]")', {"response"})
    assert evaluate_value('response.items.map(i, i.name + ") + [i]")', {"response": {"items": [{"name": "a"}]}}) == ["a) + [i]"]


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
    assert cel_runner._POLICY_SANDBOX._current_executor() is None  # pylint: disable=protected-access


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
    shutdown_cel_pool()
    os.environ["CEL_RUNNER_CANARY"] = "present"
    try:
        start_cel_pool()
        assert cel_runner._POLICY_SANDBOX.submit(_environment_size) == 0  # pylint: disable=protected-access
    finally:
        os.environ.pop("CEL_RUNNER_CANARY", None)
        shutdown_cel_pool()


def _environment_size() -> int:
    """Count the environment variables visible inside a worker process.

    Returns:
        The number of environment variables the worker can see.
    """
    return len(os.environ)


@linux_only
def test_pool_is_reused_within_a_process(cel_pool):
    """Starting an already-started pool keeps the same executor."""
    first = cel_runner._POLICY_SANDBOX._current_executor()  # pylint: disable=protected-access
    start_cel_pool()
    assert cel_runner._POLICY_SANDBOX._current_executor() is first  # pylint: disable=protected-access


@linux_only
def test_pool_is_rebuilt_after_pid_change(cel_pool, monkeypatch):
    """A pool inherited across a fork is replaced rather than reused."""
    abandoned = cel_runner._POLICY_SANDBOX._current_executor()  # pylint: disable=protected-access
    monkeypatch.setattr(cel_runner._POLICY_SANDBOX, "_pool_pid", -1)  # pylint: disable=protected-access
    try:
        assert evaluate_expression(GLOBAL_POLICY, VARIABLES) is True
        assert cel_runner._POLICY_SANDBOX._pool_pid == os.getpid()  # pylint: disable=protected-access
    finally:
        cel_runner._POLICY_SANDBOX._discard(abandoned)  # pylint: disable=protected-access


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
    monkeypatch.setattr(cel_runner._POLICY_SANDBOX, "_build", lambda _workers: failing_pool)  # pylint: disable=protected-access
    with pytest.raises(TimeoutError):
        start_cel_pool()
    assert failing_pool.shutdown_calls == [{"wait": False, "cancel_futures": True}]
    assert cel_runner._POLICY_SANDBOX._current_executor() is None  # pylint: disable=protected-access


def test_pool_failure_fails_closed(monkeypatch):
    """When the sandbox cannot be built, evaluation raises instead of running unprotected."""
    shutdown_cel_pool()
    monkeypatch.setattr(cel_runner, "subprocess_mode_available", lambda: True)
    monkeypatch.setattr(cel_runner._POLICY_SANDBOX, "_build", lambda: (_ for _ in ()).throw(OSError("no fork for you")))  # pylint: disable=protected-access
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

    monkeypatch.setattr(cel_runner._POLICY_SANDBOX, "submit", _raise)  # pylint: disable=protected-access
    with pytest.raises(cel_error) as excinfo:
        evaluate_expression(GLOBAL_POLICY, VARIABLES)
    assert excinfo.value.__cause__ is sandbox_error


# --- value-returning evaluation -----------------------------------------------

RESPONSE = {"items": [{"name": "a", "size": 1}, {"name": "b", "size": 2}], "total": 2}


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("response.total", 2),
        ("response.items.map(i, i.name)", ["a", "b"]),
        ("response.items.filter(i, i.size > 1)", [{"name": "b", "size": 2}]),
        ("response.items[0]", {"name": "a", "size": 1}),
        ("response", RESPONSE),
        ('{"count": response.total, "names": response.items.map(i, i.name)}', {"count": 2, "names": ["a", "b"]}),
    ],
)
def test_evaluate_value_returns_plain_json(inprocess, expression, expected):
    """A filter returns whatever shape the expression builds, as plain JSON data."""
    assert evaluate_value(expression, {"response": RESPONSE}) == expected


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("timestamp('2020-01-01T00:00:00Z')", "2020-01-01T00:00:00+00:00"),
        ("duration('90s')", 90.0),
        ("b'abc'", "abc"),
        ("{1: 'one'}", {"1": "one"}),
        ("[duration('1s')]", [1.0]),
    ],
)
def test_evaluate_value_converts_cel_only_types(inprocess, expression, expected):
    """Timestamps, durations, bytes and non-string keys come back as JSON values."""
    assert evaluate_value(expression, {}) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (b"\xff\xfeok", "\ufffd\ufffdok"),
        ({"when": datetime(2020, 1, 1, tzinfo=timezone.utc), "inner": {"d": timedelta(minutes=1)}}, {"when": "2020-01-01T00:00:00+00:00", "inner": {"d": 60.0}}),
        ({1: "a", "1": "b"}, {"1": "b"}),
        ((1, (2, 3)), [1, [2, 3]]),
    ],
)
def test_to_json_edge_cases(value, expected):
    """Undecodable bytes are replaced, nested CEL types are converted, and colliding keys keep the last value."""
    assert cel_runner._to_json(value) == expected


@pytest.mark.parametrize(
    "expression,error,fragment",
    [
        ("response.items[", CelSyntaxError, "parse"),
        ("payload.total", CelEvaluationError, "unknown variable"),
        ("response.missing", CelEvaluationError, "KeyError"),
    ],
)
def test_evaluate_value_errors(inprocess, expression, error, fragment):
    """A value evaluation fails with the same error classes as a policy."""
    with pytest.raises(error, match=fragment):
        evaluate_value(expression, {"response": RESPONSE})


def test_evaluate_value_does_not_require_a_boolean(inprocess):
    """The boolean requirement belongs to policies only."""
    assert evaluate_value("response.total", {"response": RESPONSE}) == 2
    with pytest.raises(CelEvaluationError, match="expected bool"):
        evaluate_expression("response.total", {"response": RESPONSE})


# --- registration-time check ---------------------------------------------------


def test_check_expression_accepts_a_valid_filter(inprocess):
    """A filter that compiles and uses only the allowed variable passes without data."""
    assert check_expression("response.items[0].name", {"response"}) is None


@pytest.mark.parametrize(
    "expression,error,fragment",
    [
        ("response.items[", CelSyntaxError, "parse"),
        ("payload.total", CelEvaluationError, r"unknown variable\(s\) \['payload'\]; available: \['response'\]"),
    ],
)
def test_check_expression_rejects_what_can_never_run(inprocess, expression, error, fragment):
    """Syntax errors and unknown variables are caught at registration."""
    with pytest.raises(error, match=fragment):
        check_expression(expression, {"response"})


def test_check_expression_applies_the_length_cap(inprocess):
    """The source length limit applies before compilation, as for policies."""
    with pytest.raises(CelSyntaxError, match="characters"):
        check_expression("response." + "a" * MAX_EXPRESSION_LENGTH, {"response"})


@linux_only
def test_value_runs_in_worker(cel_pool):
    """A value evaluation goes through the sandbox and keeps its error classes."""
    assert evaluate_value("response.items.map(i, i.size)", {"response": RESPONSE}) == [1, 2]
    with pytest.raises(CelSyntaxError, match="parse"):
        evaluate_value("response[", {"response": RESPONSE})


@linux_only
def test_runaway_filter_times_out_and_the_pool_recovers(cel_pool, monkeypatch):
    """A filter that overruns the configured budget is killed, and the next call still runs."""
    monkeypatch.setattr(settings, "cel_filter_timeout_seconds", 0.5)
    response = list(range(5000))
    start = time.perf_counter()
    with pytest.raises(CelTimeout):
        evaluate_value("response.all(a, response.all(b, a + b >= 0))", {"response": response})
    assert time.perf_counter() - start < 10.0
    assert evaluate_value("response.size()", {"response": response}) == 5000


@linux_only
def test_runaway_filter_leaves_the_policy_pool_untouched(cel_pool, monkeypatch):
    """A filter timeout kills only filter workers; a policy evaluates on the same policy pool afterwards."""
    monkeypatch.setattr(settings, "cel_filter_timeout_seconds", 0.5)
    policy_pool = cel_runner._POLICY_SANDBOX._current_executor()  # pylint: disable=protected-access
    with pytest.raises(CelTimeout):
        evaluate_value("response.all(a, response.all(b, a + b >= 0))", {"response": list(range(5000))})
    assert evaluate_expression(GLOBAL_POLICY, VARIABLES) is True
    assert cel_runner._POLICY_SANDBOX._current_executor() is policy_pool  # pylint: disable=protected-access


def test_check_expression_never_touches_the_sandbox(monkeypatch):
    """The write-time check parses only, so a busy or dead pool cannot turn a valid filter into a rejection."""

    def refuse(*_args):
        raise AssertionError("check_expression submitted to the sandbox")

    monkeypatch.setattr(settings, "cel_execution", "subprocess")
    monkeypatch.setattr(cel_runner._POLICY_SANDBOX, "submit", refuse)
    monkeypatch.setattr(cel_runner._FILTER_SANDBOX, "submit", refuse)
    assert check_expression("response.items.map(i, i.name)", {"response"}) is None
    with pytest.raises(CelEvaluationError, match="unknown variable"):
        check_expression("payload", {"response"})
