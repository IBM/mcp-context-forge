# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/cel_runner.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Sandboxed evaluation of CEL expressions.
"""

# Future
from __future__ import annotations

# Standard
from functools import lru_cache
import logging
import os
import sys
from typing import Any, Mapping

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
    "evaluate_expression",
    "shutdown_cel_pool",
    "start_cel_pool",
    "subprocess_mode_available",
]

# Upper bound on expression source length. A literal list written into an expression is
# the only thing a comprehension can iterate over, so bounding the source bounds that.
MAX_EXPRESSION_LENGTH = 4096

_OUTCOME_OK = "ok"
_OUTCOME_SYNTAX = "syntax"
_OUTCOME_EVALUATION = "evaluation"


class CelError(Exception):
    """Raised when a CEL expression cannot be evaluated."""


class CelSyntaxError(CelError):
    """Raised when an expression does not parse or exceeds the length limit."""


class CelEvaluationError(CelError):
    """Raised when an expression parses but cannot produce a boolean."""


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


_SANDBOX = SandboxPool(
    name="CEL",
    workers_fn=lambda: settings.cel_workers,
    timeout_fn=lambda: settings.cel_timeout_seconds,
    initializer=_worker_init,
)


def start_cel_pool() -> None:
    """Create the CEL worker pool for this process."""
    global _FALLBACK_WARNED  # pylint: disable=global-statement

    if not subprocess_mode_available():
        if not _FALLBACK_WARNED:
            logger.warning(
                "CEL sandbox is disabled (execution=%s, platform=%s). Policy expressions will run in-process with no environment scrub and no time limit. This is unsafe outside development.",
                settings.cel_execution,
                sys.platform,
            )
            _FALLBACK_WARNED = True
        return

    _SANDBOX.start()


def shutdown_cel_pool() -> None:
    """Tear down the CEL worker pool for this process."""
    _SANDBOX.shutdown()


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


def _evaluate_in_worker(expression: str, variables: Mapping[str, Any]) -> tuple[str, Any]:
    """Compile, check, and execute an expression. This is the worker entry point.

    Args:
        expression: The CEL source.
        variables: variables the expression may reference
    Returns:
        ``("ok", result)`` with a boolean result, or ``("syntax", message)`` /
        ``("evaluation", message)`` describing why no boolean was produced.
    """
    try:
        program = _compile(expression)
    except ValueError as exc:
        return (_OUTCOME_SYNTAX, str(exc))

    missing = sorted(set(program.variables()) - set(variables))
    if missing:
        return (_OUTCOME_EVALUATION, f"unknown variable(s) {missing}; available: {sorted(variables)}")

    try:
        result = program.execute(cel.Context(variables=dict(variables)))  # pylint: disable=no-member
    except Exception as exc:  # pylint: disable=broad-except
        return (_OUTCOME_EVALUATION, f"{type(exc).__name__}: {exc}")

    if not isinstance(result, bool):
        return (_OUTCOME_EVALUATION, f"expression returned {type(result).__name__}, expected bool")
    return (_OUTCOME_OK, result)


def _raise_for_outcome(outcome: tuple[str, Any]) -> bool:
    """Turn a worker outcome into a boolean or the matching exception.

    Args:
        outcome: The pair returned by :func:`_evaluate_in_worker`.

    Returns:
        The boolean result.

    Raises:
        CelSyntaxError: If the expression did not parse.
        CelEvaluationError: If the expression could not produce a boolean.
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


def evaluate_expression(expression: str, variables: Mapping[str, Any]) -> bool:
    """Evaluate a CEL expression to a boolean under the configured execution mode.

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
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CelSyntaxError(f"expression is {len(expression)} characters; the limit is {MAX_EXPRESSION_LENGTH}")

    if not subprocess_mode_available():
        return _raise_for_outcome(_evaluate_in_worker(expression, variables))

    try:
        outcome = _SANDBOX.submit(_evaluate_in_worker, expression, variables)
    except SandboxTimeout as exc:
        raise CelTimeout("CEL expression exceeded the execution time limit") from exc
    except SandboxBusy as exc:
        raise CelBusy("CEL sandbox has no free worker") from exc
    except SandboxError as exc:
        raise CelError(str(exc)) from exc
    return _raise_for_outcome(outcome)
