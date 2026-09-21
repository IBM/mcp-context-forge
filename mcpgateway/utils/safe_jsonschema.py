# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/safe_jsonschema.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Bounded JSON Schema validation.

Tool and prompt schemas are attacker-influenced, and Python's ``re`` holds the GIL while it
backtracks. A schema that carries a regex keyword therefore has its whole validation run in
a killable worker under a wall-clock limit.

The routing question is "does this schema contain a regex keyword", never "is this pattern
safe". Classifying patterns was tried and failed: a classifier that wrongly admits one
pattern sends it to the inline path, where nothing bounds it. Whole-validation routing also
covers the paths that reach ``re`` inside jsonschema itself, such as
``jsonschema/_utils.py:82``, which ``additionalProperties`` uses and which no keyword
override intercepts.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import Mapping
import logging
import multiprocessing
from typing import Any, List, Optional

# Third-Party
import jsonschema
import orjson
import referencing

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.sandbox_pool import SandboxError, SandboxPool, SandboxUnavailable

logger = logging.getLogger(__name__)

__all__ = [
    "sandbox_unavailable",
    "schema_uses_regex",
    "shutdown_validation_pool",
    "start_validation_pool",
    "validate_safely",
    "warn_unprovable_patterns",
]

# Keywords whose values are regular expressions. ``pattern`` holds one, and each key of
# ``patternProperties`` is one.
_REGEX_KEYWORDS = ("pattern", "patternProperties")

# Draft classes are told to the worker by name, because a class reference does not survive
# every start method.
_DRAFTS = {
    "Draft4": jsonschema.Draft4Validator,
    "Draft6": jsonschema.Draft6Validator,
    "Draft7": jsonschema.Draft7Validator,
    "Draft201909": jsonschema.Draft201909Validator,
    "Draft202012": jsonschema.Draft202012Validator,
}
_DRAFT_NAMES = {cls: name for name, cls in _DRAFTS.items()}

_SANDBOX_DOWN = False

# The Task 1 gate establishes which start methods work here.
_START_METHOD = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"

_SANDBOX = SandboxPool(
    name="schema validation",
    workers_fn=lambda: settings.regex_workers,
    timeout_fn=lambda: settings.regex_timeout_seconds,
    start_method=_START_METHOD,
)


def schema_uses_regex(schema: Any) -> bool:
    """Report whether a schema carries a regex keyword at any depth.

    This is the whole routing decision. It inspects keyword presence, never pattern
    content, so it cannot be wrong about a pattern's behavior.

    Args:
        schema: A JSON Schema, or any sub-node of one.

    Returns:
        True when ``pattern`` or ``patternProperties`` appears anywhere.

    Examples:
        >>> schema_uses_regex({"type": "string"})
        False
        >>> schema_uses_regex({"properties": {"x": {"pattern": "^a$"}}})
        True
    """
    stack: List[Any] = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, Mapping):
            for keyword in _REGEX_KEYWORDS:
                if keyword in node:
                    return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _validate_in_worker(draft_name: str, schema_json: bytes, instance_json: bytes) -> Optional[str]:
    """Validate an instance inside a worker process.

    Runs in a separate process, so a non-terminating match is killable.

    Args:
        draft_name: Key into the draft table.
        schema_json: Serialized schema.
        instance_json: Serialized instance.

    Returns:
        The best-matching error message, or None when the instance is valid.
    """
    schema = orjson.loads(schema_json)
    instance = orjson.loads(instance_json)
    validator = _DRAFTS[draft_name](schema, registry=referencing.Registry())
    error = jsonschema.exceptions.best_match(validator.iter_errors(instance))
    return None if error is None else str(error)


def sandbox_unavailable() -> bool:
    """Report whether this process runs without a validation sandbox.

    Returns:
        True when a regex-bearing schema must be refused rather than validated.
    """
    return _SANDBOX_DOWN


def start_validation_pool() -> None:
    """Create the validation worker pool for this process.

    Call from application startup, after any fork the server performs. A platform without a
    usable start method refuses regex-bearing schemas instead of failing to boot.
    """
    global _SANDBOX_DOWN  # pylint: disable=global-statement
    try:
        _SANDBOX.start()
        _SANDBOX_DOWN = False
        return
    except SandboxUnavailable:
        pass
    except Exception:  # pylint: disable=broad-except
        logger.warning("Validation sandbox failed to start", exc_info=True)
    _SANDBOX_DOWN = True
    logger.warning(
        "Schema validation sandbox unavailable on this platform. A schema carrying a regex keyword will be refused rather than validated. Tools and prompts using such a schema will fail validation here.",
    )


def shutdown_validation_pool() -> None:
    """Tear down the validation worker pool for this process."""
    _SANDBOX.shutdown()


def validate_safely(instance: Any, schema: dict, validator_cls: type) -> None:
    """Validate an instance against a schema without risking the event loop.

    Args:
        instance: The data to validate.
        schema: The JSON Schema to validate against.
        validator_cls: The stock jsonschema validator class chosen for this schema.

    Raises:
        jsonschema.exceptions.ValidationError: If the instance is invalid, or if validation
            cannot be completed safely. A truncated validation is a failure, never a pass.
    """
    if not schema_uses_regex(schema):
        error = jsonschema.exceptions.best_match(validator_cls(schema, registry=referencing.Registry()).iter_errors(instance))
        if error is not None:
            raise error
        return

    if sandbox_unavailable():
        raise jsonschema.exceptions.ValidationError("schema carries a regex keyword and no validation sandbox is available on this platform")

    try:
        instance_json = orjson.dumps(instance)
        schema_json = orjson.dumps(schema)
    except (TypeError, orjson.JSONEncodeError) as exc:
        raise jsonschema.exceptions.ValidationError(f"instance or schema could not be serialized for safe validation: {exc}") from exc

    if len(instance_json) > settings.regex_max_subject_bytes:
        raise jsonschema.exceptions.ValidationError(f"instance of {len(instance_json)} bytes exceeds the {settings.regex_max_subject_bytes} byte limit for pattern validation")

    try:
        message = _SANDBOX.submit(_validate_in_worker, _DRAFT_NAMES.get(validator_cls, "Draft202012"), schema_json, instance_json)
    except SandboxError as exc:
        logger.warning(
            "Schema validation failed closed",
            extra={"reason": type(exc).__name__, "instance_bytes": len(instance_json), "schema_bytes": len(schema_json)},
        )
        raise jsonschema.exceptions.ValidationError(f"schema validation could not be completed safely: {exc}") from exc

    if message is not None:
        raise jsonschema.exceptions.ValidationError(message)


def warn_unprovable_patterns(schema: Any, *, source: str) -> None:
    """Log one warning when a registered schema carries a regex keyword.

    Storing such a schema is safe, because the sandbox bounds every match. This gives an
    operator an inventory without blocking registration.

    Args:
        schema: A JSON Schema, or any sub-node of one.
        source: A short identifier for the log line, such as ``tool:weather``.
    """
    if schema_uses_regex(schema):
        logger.warning(
            "Schema carries a regex keyword; its validations run in the sandbox",
            extra={"source": source},
        )
