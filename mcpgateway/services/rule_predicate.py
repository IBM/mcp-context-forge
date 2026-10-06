# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/rule_predicate.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

CEL predicates for the RBAC rule catalog.

Predicates are Google Common Expression Language expressions over
the attribute families the gateway binds at evaluation time. The
expression syntax matches OpenFGA condition expressions, so a
predicate can move between the gateway rule catalog and an OpenFGA
authorization model without rewriting
(https://openfga.dev/docs/modeling/conditions).

Variable families:

- ``subject.id`` — principal identity
- ``authenticated`` — true on every evaluated request
- ``token.is_admin`` — admin flag from the token
- ``role.<name>`` — true for each role the principal holds
- ``team.<id>`` — true for each team the principal belongs to
- ``args.<name>`` — tool arguments, merged from SEP-2243 mirrored
  ``Mcp-Param-<name>`` headers and the JSON-RPC body arguments

Example predicates:

- ``subject.id == 'becky@demo.example.com' && args.timezone != ''``
- ``role.team_admin || subject.id in ['alice@demo.example.com']``
- ``args.timezone.startsWith('America/')``
- ``token.is_admin && args.depth > 2``

Semantics: a missing attribute makes the enclosing select false, and
an evaluation error means the predicate does not match. Both cases
fail closed: an ``allow`` rule without a match grants nothing, and a
``deny`` rule without a match must be paired with an engine grant
that already excludes the caller.

Expression notes:

- ``startsWith``, ``endsWith``, ``matches`` (RE2 regex), and ``size``
  work on strings. ``contains`` is rejected: the celpy interpreter
  mis-evaluates it, and ``matches('.*x.*')`` covers the same need.
- Mirrored header values are strings. Compare a numeric header with
  ``int(args.depth) > 2``; body arguments keep their native types.
- OpenFGA conditions declare typed parameters. A predicate that must
  move into an OpenFGA authorization model should compare against
  values of the declared parameter type.

Expressions are validated at parse time against a canary activation
that binds every family empty. The canary rejects unknown top-level
identifiers and malformed calls before the rule is stored.
"""

# Standard
import re
from typing import Any, Mapping

# Third-Party
from celpy import Environment, celtypes
from celpy.celparser import CELParseError
from celpy.evaluation import CELEvalError

_MAX_PREDICATE_LENGTH = 4096
_MAX_COMPILE_CACHE = 512

_ANNOTATIONS: dict[str, Any] = {
    "subject": celtypes.MapType,
    "args": celtypes.MapType,
    "role": celtypes.MapType,
    "team": celtypes.MapType,
    "token": celtypes.MapType,
    "authenticated": celtypes.BoolType,
}

_CANARY_ACTIVATION = {
    "subject": celtypes.MapType({}),
    "args": celtypes.MapType({}),
    "role": celtypes.MapType({}),
    "team": celtypes.MapType({}),
    "token": celtypes.MapType({}),
    "authenticated": celtypes.BoolType(False),
}

_ENVIRONMENT = Environment(annotations=_ANNOTATIONS)

_COMPILE_CACHE: dict[str, Any] = {}

_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'")
_ARGS_MEMBER = re.compile(r"\bargs\.([A-Za-z_][A-Za-z0-9_]*)\b")
_ARGS_INDEX = re.compile(r"\bargs\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]")


class PredicateSyntaxError(ValueError):
    """Raised when a predicate falls outside the accepted CEL subset."""


class CelPredicate:
    """A compiled CEL predicate ready for repeated evaluation."""

    def __init__(self, source: str, runner: Any) -> None:
        """Hold the source text and its compiled runner.

        Args:
            source: The predicate expression text.
            runner: Compiled celpy program runner.
        """
        self.source = source
        self._runner = runner

    def evaluate(self, attributes: Mapping[str, Any]) -> bool:
        """Evaluate against bound attribute families.

        Args:
            attributes: Nested attribute mapping.

        Returns:
            bool: The expression truth value. Evaluation errors are
            false; a predicate that cannot run does not match.
        """
        try:
            activation = _adapt(attributes)
            return bool(self._runner.evaluate(activation))
        except (CELEvalError, CELParseError, KeyError, TypeError, ValueError):
            return False


def _adapt(value: Any) -> Any:
    """Convert plain Python containers to celtypes recursively.

    Args:
        value: A dict, list, or scalar from the attribute mapping.

    Returns:
        The value expressed with celtypes containers.
    """
    if isinstance(value, Mapping):
        return celtypes.MapType({str(k): _adapt(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return celtypes.ListType([_adapt(v) for v in value])
    return value


def _canary(runner: Any) -> None:
    """Reject expressions that cannot run against empty families.

    Args:
        runner: Compiled celpy program runner.

    Raises:
        PredicateSyntaxError: When the canary reports an undeclared
        reference, which means the expression names a variable the
        gateway never binds.
    """
    try:
        runner.evaluate(dict(_CANARY_ACTIVATION))
    except (CELEvalError, CELParseError, KeyError, TypeError, ValueError) as exc:
        message = str(exc)
        if "undeclared reference to" in message:
            raise PredicateSyntaxError(f"Predicate fails validation: {message.splitlines()[0]}") from exc


def parse_predicate(predicate: str) -> CelPredicate:
    """Compile a CEL predicate for the catalog attribute families.

    Args:
        predicate: CEL expression over the bound families.

    Returns:
        CelPredicate: The compiled predicate.

    Raises:
        PredicateSyntaxError: On empty, oversized, unparsable, or
        canary-failing input.
    """
    if not predicate or not predicate.strip():
        raise PredicateSyntaxError("Empty predicate")
    if len(predicate) > _MAX_PREDICATE_LENGTH:
        raise PredicateSyntaxError(f"Predicate longer than {_MAX_PREDICATE_LENGTH} characters")
    if ".contains(" in predicate:
        raise PredicateSyntaxError("contains is unsupported: use matches('.*<text>.*') instead")
    cached = _COMPILE_CACHE.get(predicate)
    if cached is not None:
        return cached
    try:
        program = _ENVIRONMENT.compile(predicate)
        runner = _ENVIRONMENT.program(program)
    except (CELParseError, SyntaxError, ValueError, TypeError) as exc:
        raise PredicateSyntaxError(f"Predicate does not parse as CEL: {str(exc).splitlines()[0]}") from exc
    _canary(runner)
    compiled = CelPredicate(predicate, runner)
    if len(_COMPILE_CACHE) >= _MAX_COMPILE_CACHE:
        _COMPILE_CACHE.clear()
    _COMPILE_CACHE[predicate] = compiled
    return compiled


def evaluate_predicate(predicate: str, attributes: Mapping[str, Any]) -> bool:
    """Compile and evaluate a predicate against the attributes.

    Args:
        predicate: CEL expression over the bound families.
        attributes: Nested attribute mapping built from the user context.

    Returns:
        bool: The truth value. Missing attributes and evaluation
        errors are false.

    Raises:
        PredicateSyntaxError: On any input outside the subset.
    """
    return parse_predicate(predicate).evaluate(attributes)


def collect_args_references(predicate: str) -> set[str]:
    """Collect the ``args.<name>`` references in a predicate.

    The header annotator uses this to learn which tool parameters a
    rule's predicate reads. String literals are stripped first so a
    quoted ``'args.x'`` never counts as a reference.

    Args:
        predicate: CEL expression over the bound families.

    Returns:
        The referenced parameter names.
    """
    try:
        parse_predicate(predicate)
    except PredicateSyntaxError:
        return set()
    names = set(_ARGS_INDEX.findall(predicate))
    stripped = _STRING_LITERAL.sub("''", predicate)
    names |= set(_ARGS_MEMBER.findall(stripped))
    return names
