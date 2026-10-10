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
import sys
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
    "warn_unprovable_pattern_source",
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

# An empty registry refuses remote $ref retrieval.
_NO_RETRIEVE_REGISTRY: referencing.Registry = referencing.Registry()

_SANDBOX_DOWN = False

# Names the real cause, because "unavailable on this platform" sends an operator to the
# platform when the fault is usually configuration. The cause fills the placeholder.
_SANDBOX_DOWN_MESSAGE = (
    "Schema validation sandbox could not start (%s). A schema carrying a regex keyword will be refused rather than validated. Tools and prompts using such a schema will fail validation here."
)


def _start_method_for(platform: str) -> str:
    """Choose the multiprocessing start method for a platform.

    ``fork`` is unsafe on Darwin; mirrors ``jq_runner.subprocess_mode_available()``.

    Args:
        platform: A ``sys.platform`` value.

    Returns:
        ``"fork"`` on Linux, ``"spawn"`` elsewhere.

    Examples:
        >>> _start_method_for("linux")
        'fork'
        >>> _start_method_for("darwin")
        'spawn'
        >>> _start_method_for("win32")
        'spawn'
    """
    return "fork" if platform.startswith("linux") else "spawn"


_START_METHOD = _start_method_for(sys.platform)

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
    validator = _DRAFTS[draft_name](schema, registry=_NO_RETRIEVE_REGISTRY)
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

    Call from application startup, after any fork the server performs. A start failure refuses
    regex-bearing schemas instead of failing to boot, and names its cause in the log.
    """
    global _SANDBOX_DOWN  # pylint: disable=global-statement
    try:
        _SANDBOX.start()
        _SANDBOX_DOWN = False
        return
    except SandboxUnavailable as exc:
        _SANDBOX_DOWN = True
        logger.warning(_SANDBOX_DOWN_MESSAGE, f"no sandbox on this platform: {exc}", exc_info=True)
    except Exception as exc:  # pylint: disable=broad-except
        _SANDBOX_DOWN = True
        logger.warning(_SANDBOX_DOWN_MESSAGE, f"{type(exc).__name__}: {exc}", exc_info=True)


def shutdown_validation_pool() -> None:
    """Tear down the validation worker pool for this process."""
    _SANDBOX.shutdown()


def validate_safely(instance: Any, schema: dict, validator_cls: type) -> None:
    """Validate an instance against a schema without risking the event loop.

    Args:
        instance: The data to validate.
        schema: The JSON Schema to validate against.
        validator_cls: The stock jsonschema validator class chosen for this schema. A
            regex-bearing schema accepts only a class in the draft table, because the worker
            must reproduce the same semantics.

    Raises:
        jsonschema.exceptions.ValidationError: If the instance is invalid, or if validation
            cannot be completed safely. A truncated validation is a failure, never a pass.
    """
    if not schema_uses_regex(schema):
        error = jsonschema.exceptions.best_match(validator_cls(schema, registry=_NO_RETRIEVE_REGISTRY).iter_errors(instance))
        if error is not None:
            raise error
        return

    if sandbox_unavailable():
        raise jsonschema.exceptions.ValidationError("schema carries a regex keyword and no validation sandbox is available on this platform")

    draft_name = _DRAFT_NAMES.get(validator_cls)
    if draft_name is None:
        # Substituting a draft would give the sandbox different semantics from the inline
        # path for the same class, which weakens the boundary silently. Refuse instead, so
        # the call site that passed an extended validator is the thing that surfaces.
        raise jsonschema.exceptions.ValidationError(f"validator class {validator_cls.__name__} is not a stock jsonschema draft, so the validation sandbox cannot reproduce its semantics")

    try:
        instance_json = orjson.dumps(instance)
        schema_json = orjson.dumps(schema)
    except (TypeError, orjson.JSONEncodeError) as exc:
        raise jsonschema.exceptions.ValidationError(f"instance or schema could not be serialized for safe validation: {exc}") from exc

    if len(instance_json) > settings.regex_max_subject_bytes:
        raise jsonschema.exceptions.ValidationError(f"instance of {len(instance_json)} bytes exceeds the {settings.regex_max_subject_bytes} byte limit for pattern validation")

    try:
        message = _SANDBOX.submit(_validate_in_worker, draft_name, schema_json, instance_json)
    except SandboxError as exc:
        logger.warning(
            "Schema validation failed closed",
            extra={"reason": type(exc).__name__, "instance_bytes": len(instance_json), "schema_bytes": len(schema_json)},
        )
        raise jsonschema.exceptions.ValidationError(f"schema validation could not be completed safely: {exc}") from exc

    if message is not None:
        raise jsonschema.exceptions.ValidationError(message)


def _report_diagnostic_failure(message: str, source: str) -> None:
    """Log that a never-raises diagnostic failed, and swallow a failure to log that.

    The callers below promise never to raise, and they run inside a SQLAlchemy
    ``before_insert`` listener, a federation sync loop, and a plugin load path. An unguarded
    fallback log would break that promise whenever logging itself is the thing that failed,
    which is the case their own ``except`` handler exists to report. Nothing remains to do
    once logging is unusable, so the second failure is dropped.

    Args:
        message: A printf-style message with one ``%s`` placeholder for the source.
        source: A short identifier for the log line, such as ``tool:weather``.
    """
    try:
        logger.warning(message, source, exc_info=True)
    except Exception:  # pylint: disable=broad-except
        pass


def warn_unprovable_patterns(schema: Any, *, source: str) -> None:
    """Log one warning when a registered schema carries a regex keyword.

    Storing such a schema is safe, because the sandbox bounds every match. This gives an
    operator an inventory without blocking registration.

    This function never raises. It sits ahead of, or beside, data-mutating operations at
    every call site (a SQLAlchemy ``before_insert``/``before_update`` listener, a federation
    sync loop, an OpenAPI import response) that must not fail because a diagnostic failed.
    That guarantee is structural: every exception raised anywhere in this function's body,
    including from ``schema_uses_regex`` or from logging itself, is caught here and swallowed
    after being logged. Do not add a call-site ``try/except`` to recreate this guarantee;
    fix it here instead, so every caller, present and future, inherits it for free.

    Args:
        schema: A JSON Schema, or any sub-node of one.
        source: A short identifier for the log line, such as ``tool:weather``.
    """
    try:
        if schema_uses_regex(schema):
            logger.warning(
                "Schema carries a regex keyword; its validations run in the sandbox",
                extra={"source": source},
            )
    except Exception:
        _report_diagnostic_failure("Schema regex inventory check failed for source=%s; continuing without a warning", source)


def warn_unprovable_pattern_source(pattern: str, *, source: str) -> None:
    """Log one warning when an operator-supplied regex pattern is compiled without a time bound.

    This covers plugin configuration sites, not schema storage. Plugin regex patterns come
    from deploy-time operator configuration, not from an attacker, so a pathological pattern
    here is administrator self-denial-of-service, not an attack surface reached by a request.
    Routing these compiles through the validation sandbox would put IPC in a hot filter path
    for no security gain, so this only gives an operator an inventory; it does not bound the
    compile or any later match.

    This function never raises. It sits immediately before a plugin's ``re.compile`` call,
    which must not fail to load because a diagnostic failed. That guarantee is structural:
    every exception raised anywhere in this function's body, including from logging itself,
    is caught here and swallowed after being logged. Do not add a call-site ``try/except`` to
    recreate this guarantee; fix it here instead, so every caller, present and future,
    inherits it for free.

    Args:
        pattern: The operator-supplied regex source about to be compiled.
        source: A short identifier for the log line, such as ``plugin:regex_filter``.
    """
    try:
        logger.warning(
            "Operator-supplied regex compiled without a time bound",
            extra={"source": source, "pattern_length": len(pattern)},
        )
    except Exception:
        _report_diagnostic_failure("Regex pattern compile warning failed for source=%s; continuing without a warning", source)
