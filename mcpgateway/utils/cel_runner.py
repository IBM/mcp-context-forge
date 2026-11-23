# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/cel_runner.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Sandboxed evaluation of CEL expressions.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timedelta
from functools import lru_cache
import logging
import os
import re
import sys
from typing import Any, Callable, Iterable, Mapping

# Third-Party
import cel

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.sandbox_pool import SandboxBusy, SandboxError, SandboxPool, SandboxTimeout

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_EXPRESSION_LENGTH",
    "CelBusy",
    "CelError",
    "CelEvaluationError",
    "CelSyntaxError",
    "CelTimeout",
    "check_expression",
    "evaluate_expression",
    "evaluate_value",
    "shutdown_cel_pool",
    "start_cel_pool",
    "subprocess_mode_available",
]

# Upper bound on expression source length. A literal list written into an expression is
# the only thing a comprehension can iterate over, so bounding the source bounds that.
MAX_EXPRESSION_LENGTH = 4096

# CEL's comprehension macros bind a loop variable as their first argument.
# Need to indentify and remove them before the unknown-variable check.
_STRING_LITERAL = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
_MACRO_CALL = re.compile(r"\.\s*(?:all|exists|exists_one|filter|map)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,")

_OUTCOME_OK = "ok"
_OUTCOME_SYNTAX = "syntax"
_OUTCOME_EVALUATION = "evaluation"


class CelError(Exception):
    """Raised when a CEL expression cannot be evaluated."""


class CelSyntaxError(CelError):
    """Raised when an expression does not parse or exceeds the length limit."""


class CelEvaluationError(CelError):
    """Raised when an expression parses but cannot produce a result."""


class CelTimeout(CelError):
    """Raised when an evaluation exceeds its wall-clock limit."""


class CelBusy(CelError):
    """Raised when every sandbox worker is already occupied. Safe to retry."""


_FALLBACK_WARNED = False


def subprocess_mode_available() -> bool:
    """Report whether the forked sandbox can be used on this platform.

    Returns:
        True when the sandbox should be used.
    """
    if settings.cel_execution != "subprocess":
        return False
    return sys.platform.startswith("linux")


def _worker_init() -> None:
    """Clear the inherited environment inside a CEL worker process."""
    os.environ.clear()


_POLICY_SANDBOX = SandboxPool(
    name="CEL policy",
    workers_fn=lambda: settings.cel_workers,
    timeout_fn=lambda: settings.cel_timeout_seconds,
    initializer=_worker_init,
)
# Response filters are written by tool registrants, policies by administrators. A
# separate pool keeps a runaway filter from killing the workers a policy check needs.
_FILTER_SANDBOX = SandboxPool(
    name="CEL filter",
    workers_fn=lambda: settings.cel_filter_workers,
    timeout_fn=lambda: settings.cel_filter_timeout_seconds,
    initializer=_worker_init,
)
_SANDBOXES = (_POLICY_SANDBOX, _FILTER_SANDBOX)


def start_cel_pool() -> None:
    """Create the CEL worker pools for this process: one for policies, one for response filters."""
    global _FALLBACK_WARNED  # pylint: disable=global-statement

    if not subprocess_mode_available():
        if not _FALLBACK_WARNED:
            logger.warning(
                "CEL sandbox is disabled (execution=%s, platform=%s). Policy expressions and response filters will run in-process with no environment scrub and no time limit. This is unsafe outside development.",
                settings.cel_execution,
                sys.platform,
            )
            _FALLBACK_WARNED = True
        return

    for sandbox in _SANDBOXES:
        sandbox.start()


def shutdown_cel_pool() -> None:
    """Tear down the CEL worker pools for this process."""
    for sandbox in _SANDBOXES:
        sandbox.shutdown()


@lru_cache(maxsize=256)
def _compile(expression: str) -> cel.Program:
    """Compile and cache a CEL program.

    Args:
        expression: The CEL source.

    Returns:
        The compiled program.

    Raises:
        ValueError: If the expression does not parse.
    """
    return cel.compile(expression)  # pylint: disable=no-member


def _to_json(value: Any) -> Any:
    """Convert a CEL result into plain JSON data

    Args:
        value: The value the program produced.

    Returns:
        The same value built only from dict, list, str, int, float, bool and None.
    """
    if isinstance(value, dict):
        return {str(k): _to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _free_variables(program: cel.Program) -> set[str]:
    """Return the variables a program needs from its context.

    Args:
        program: A compiled program.

    Returns:
        The referenced names minus those bound by a comprehension macro.
    """
    return set(program.variables()) - _macro_bound_names(program.source)


def _macro_bound_names(source: str) -> set[str]:
    """Return the loop names a program binds and uses only inside their own macro.

    The engine reports loop names as free variables. A name counts as bound only
    when every mention of it sits inside a macro call that declares it; a mention
    outside is a real unknown variable that would fail at run time. String literals
    are blanked first so their text cannot declare or mention a name.

    Args:
        source: The CEL source.

    Returns:
        The names that need no value from the caller.
    """
    text = _STRING_LITERAL.sub(lambda match: " " * len(match.group(0)), source)
    scopes: dict[str, list[tuple[int, int]]] = {}
    for call in _MACRO_CALL.finditer(text):
        depth, end = 1, call.end()
        while end < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[end], 0)
            end += 1
        scopes.setdefault(call.group(1), []).append((call.start(), end))
    bound = set()
    for name, spans in scopes.items():
        mentions = re.finditer(rf"(?<![A-Za-z0-9_.]){re.escape(name)}(?![A-Za-z0-9_])", text)
        if all(any(start <= mention.start() < end for start, end in spans) for mention in mentions):
            bound.add(name)
    return bound


def _run_in_worker(expression: str, variables: Mapping[str, Any]) -> tuple[str, Any]:
    """Compile, check, and execute an expression. This is the worker entry point.

    Args:
        expression: The CEL source.
        variables: variables the expression may reference
    Returns:
        ``("ok", result)`` with the result as plain JSON data, or ``("syntax", message)`` /
        ``("evaluation", message)`` describing why no result was produced.
    """
    try:
        program = _compile(expression)
    except ValueError as exc:
        return (_OUTCOME_SYNTAX, str(exc))

    missing = sorted(_free_variables(program) - set(variables))
    if missing:
        return (_OUTCOME_EVALUATION, f"unknown variable(s) {missing}; available: {sorted(variables)}")

    try:
        result = program.execute(cel.Context(variables=dict(variables)))  # pylint: disable=no-member
    except Exception as exc:  # pylint: disable=broad-except
        return (_OUTCOME_EVALUATION, f"{type(exc).__name__}: {exc}")

    return (_OUTCOME_OK, _to_json(result))


def _evaluate_in_worker(expression: str, variables: Mapping[str, Any]) -> tuple[str, Any]:
    """Run an expression that must produce a boolean.

    Args:
        expression: The CEL source.
        variables: variables the expression may reference
    Returns:
        ``("ok", result)`` with a boolean result, or ``("syntax", message)`` /
        ``("evaluation", message)`` describing why no boolean was produced.
    """
    outcome = _run_in_worker(expression, variables)
    status, payload = outcome
    if status == _OUTCOME_OK and not isinstance(payload, bool):
        return (_OUTCOME_EVALUATION, f"expression returned {type(payload).__name__}, expected bool")
    return outcome


def _check_expression(expression: str, allowed_variables: frozenset[str]) -> tuple[str, Any]:
    """Compile an expression and confirm it references only allowed variables.

    Args:
        expression: The CEL source.
        allowed_variables: Names the expression may reference.
    Returns:
        ``("ok", None)``, or ``("syntax", message)`` / ``("evaluation", message)``
        describing why the expression can never run.
    """
    try:
        program = _compile(expression)
    except ValueError as exc:
        return (_OUTCOME_SYNTAX, str(exc))

    unknown = sorted(_free_variables(program) - allowed_variables)
    if unknown:
        return (_OUTCOME_EVALUATION, f"unknown variable(s) {unknown}; available: {sorted(allowed_variables)}")
    return (_OUTCOME_OK, None)


def _raise_for_outcome(outcome: tuple[str, Any]) -> Any:
    """Turn a worker outcome into its result or the matching exception.

    Args:
        outcome: The pair returned by a worker entry point.

    Returns:
        The result carried by an ``"ok"`` outcome.

    Raises:
        CelSyntaxError: If the expression did not parse.
        CelEvaluationError: If the expression could not produce a result.
        CelError: If the worker returned an outcome this module does not know.
    """
    status, payload = outcome
    if status == _OUTCOME_OK:
        return payload
    if status == _OUTCOME_SYNTAX:
        raise CelSyntaxError(payload)
    if status == _OUTCOME_EVALUATION:
        raise CelEvaluationError(payload)
    raise CelError(f"unexpected CEL worker outcome {status!r}")


def _run(worker: Callable[..., tuple[str, Any]], sandbox: SandboxPool, expression: str, *args: Any) -> Any:
    """Run a worker entry point under the configured execution mode.

    Args:
        worker: The entry point to run.
        sandbox: The pool to run it in.
        expression: The CEL source, checked against the length cap first.
        *args: Remaining arguments for the entry point.

    Returns:
        The result carried by the worker's outcome.

    Raises:
        CelSyntaxError: If the expression is too long or does not parse.
        CelEvaluationError: If the expression cannot produce a result.
        CelTimeout: If the evaluation exceeds its wall-clock limit.
        CelBusy: If every sandbox worker is already running another evaluation.
        CelError: If the sandbox cannot run the evaluation.
    """
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CelSyntaxError(f"expression is {len(expression)} characters; the limit is {MAX_EXPRESSION_LENGTH}")

    if not subprocess_mode_available():
        return _raise_for_outcome(worker(expression, *args))

    try:
        outcome = sandbox.submit(worker, expression, *args)
    except SandboxTimeout as exc:
        raise CelTimeout("CEL expression exceeded the execution time limit") from exc
    except SandboxBusy as exc:
        raise CelBusy("CEL sandbox has no free worker") from exc
    except SandboxError as exc:
        raise CelError(str(exc)) from exc
    return _raise_for_outcome(outcome)


def evaluate_expression(expression: str, variables: Mapping[str, Any]) -> bool:
    """Evaluate a CEL expression to a boolean, in the policy pool under ``CEL_TIMEOUT_SECONDS``.

    Args:
        expression: The CEL source.
        variables: variables the expression may reference

    Returns:
        The boolean the expression evaluated to.

    Raises:
        CelSyntaxError: If the expression is too long or does not parse.
        CelEvaluationError: If the expression references an unsupplied variable, fails
            at runtime, or returns something other than a boolean.
        CelTimeout: If the evaluation exceeds its wall-clock limit.
        CelBusy: If every sandbox worker is already running another evaluation.
        CelError: If the sandbox cannot run the evaluation.
    """
    return _run(_evaluate_in_worker, _POLICY_SANDBOX, expression, variables)


def evaluate_value(expression: str, variables: Mapping[str, Any]) -> Any:
    """Evaluate a CEL expression to plain JSON data, in the filter pool under ``CEL_FILTER_TIMEOUT_SECONDS``.

    Args:
        expression: The CEL source.
        variables: variables the expression may reference

    Returns:
        The result, built only from dict, list, str, int, float, bool and None.

    Raises:
        CelSyntaxError: If the expression is too long or does not parse.
        CelEvaluationError: If the expression references an unsupplied variable or
            fails at runtime.
        CelTimeout: If the evaluation exceeds its wall-clock limit.
        CelBusy: If every sandbox worker is already running another evaluation.
        CelError: If the sandbox cannot run the evaluation.
    """
    return _run(_run_in_worker, _FILTER_SANDBOX, expression, variables)


def check_expression(expression: str, allowed_variables: Iterable[str]) -> None:
    """Confirm an expression compiles and references only the given variables.

    This is the registration-time check for expressions whose real input is not
    known yet, such as a response filter. It parses the expression and runs
    nothing, so it needs no sandbox and cannot time out or find the pool busy.

    Args:
        expression: The CEL source.
        allowed_variables: Names the expression may reference.

    Raises:
        CelSyntaxError: If the expression is too long or does not parse.
        CelEvaluationError: If the expression references a variable not in
            ``allowed_variables``.
    """
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CelSyntaxError(f"expression is {len(expression)} characters; the limit is {MAX_EXPRESSION_LENGTH}")
    _raise_for_outcome(_check_expression(expression, frozenset(allowed_variables)))
