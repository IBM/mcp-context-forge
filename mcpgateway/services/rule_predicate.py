# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/rule_predicate.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

CPEX APL predicate subset for the RBAC rule catalog.

The accepted grammar follows the CPEX Agent Policy Language predicate
forms (https://contextforge-org.github.io/cpex/docs/apl/):

- Truthiness: ``role.team_admin``, ``authenticated``
- Comparison: ``delegation.depth > 2``, ``client.trust_level == 'trusted'``
  with the operators ``==``, ``!=``, ``>``, ``>=``, ``<``, ``<=``
- Set membership: ``subject.id in allowed_users``, ``subject.id not in banned``
- Existence: ``exists(delegation.origin_subject_id)``
- Grouping with parentheses and the join operators ``&`` (and) and ``|`` (or)
- ``require(a, b)`` denies when any argument is false; ``require(a | b)``
  denies only when every argument is false

Attribute paths resolve against a mapping the caller builds from the
user context and the tool invocation. Identity families: ``role.*``,
``perm.*``, ``team.*``, ``subject.id``, ``authenticated``,
``token.is_admin``. Tool arguments: ``args.<name>`` — the gateway
populates these from ``Mcp-Param-<name>`` headers that conforming
MCP 2026-07-28 clients mirror per SEP-2243 (``x-mcp-header``).
Paths deeper than 2 segments are rejected. Missing attributes evaluate
to false; an existence check is the only form that can distinguish a
missing attribute from a false one. A predicate referencing ``args.*``
that arrives without the corresponding header denies fail-closed.
"""

# Standard
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Union

_MAX_ATTR_DEPTH = 2
_MISSING = object()

_VALID_OPERATORS = ("==", "!=", ">=", "<=", ">", "<")


class PredicateSyntaxError(ValueError):
    """Raised when a predicate string falls outside the accepted grammar."""


@dataclass(frozen=True)
class Truthiness:
    """A bare attribute that is true when present and truthy."""

    attr: str


@dataclass(frozen=True)
class Compare:
    """An attribute compared with a literal."""

    attr: str
    op: str
    literal: Union[bool, float, int, str]


@dataclass(frozen=True)
class Membership:
    """An attribute checked against a collection attribute."""

    attr: str
    collection_attr: str
    negate: bool


@dataclass(frozen=True)
class Exists:
    """True when the attribute is present."""

    attr: str


@dataclass(frozen=True)
class All:
    """True when every child holds."""

    children: Sequence[Any]


@dataclass(frozen=True)
class AnyOf:
    """True when at least one child holds."""

    children: Sequence[Any]


Node = Union[All, AnyOf, Compare, Exists, Membership, Truthiness]


def _resolve(attributes: Mapping[str, Any], attr: str) -> Any:
    """Resolve a dotted attribute path against a nested mapping.

    Args:
        attributes: Nested attribute mapping.
        attr: Dotted path of at most 2 segments.

    Returns:
        The value, or the ``_MISSING`` sentinel when any segment is absent.
    """
    current: Any = attributes
    for segment in attr.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _is_number(value: Any) -> bool:
    """Say whether the value is numeric (never bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate(node: Node, attributes: Mapping[str, Any]) -> bool:
    """Evaluate a parsed predicate node against the attributes.

    Args:
        node: Node produced by :func:`parse_predicate`.
        attributes: Nested attribute mapping from the caller context.

    Returns:
        bool: The node's truth value. Missing attributes are false.
    """
    if isinstance(node, Truthiness):
        value = _resolve(attributes, node.attr)
        return value is not _MISSING and bool(value)
    if isinstance(node, Exists):
        return _resolve(attributes, node.attr) is not _MISSING
    if isinstance(node, Compare):
        value = _resolve(attributes, node.attr)
        if value is _MISSING:
            return False
        if node.op == "==":
            return value == node.literal
        if node.op == "!=":
            return value != node.literal
        if not _is_number(value) or not _is_number(node.literal):
            return False
        if node.op == ">":
            return value > node.literal
        if node.op == ">=":
            return value >= node.literal
        if node.op == "<":
            return value < node.literal
        return value <= node.literal
    if isinstance(node, Membership):
        member = _resolve(attributes, node.attr)
        collection = _resolve(attributes, node.collection_attr)
        if member is _MISSING or not isinstance(collection, (list, set, tuple, frozenset)):
            result = False
        else:
            result = member in collection
        return not result if node.negate else result
    if isinstance(node, All):
        return all(evaluate(child, attributes) for child in node.children)
    if isinstance(node, AnyOf):
        return any(evaluate(child, attributes) for child in node.children)
    raise PredicateSyntaxError(f"Unknown predicate node: {type(node).__name__}")


class _Tokenizer:
    """Tokenizer for the CPEX APL predicate subset."""

    _SYMBOLS = ("==", "!=", ">=", "<=", ">", "<", "&", "|", "(", ")", ",")

    def __init__(self, text: str) -> None:
        """Tokenize the predicate text.

        Args:
            text: Predicate string.

        Raises:
            PredicateSyntaxError: On any character outside the grammar.
        """
        self.tokens: list[str] = []
        index = 0
        while index < len(text):
            char = text[index]
            if char.isspace():
                index += 1
                continue
            matched = False
            for symbol in self._SYMBOLS:
                if text.startswith(symbol, index):
                    self.tokens.append(symbol)
                    index += len(symbol)
                    matched = True
                    break
            if matched:
                continue
            if char == "'":
                end = text.find("'", index + 1)
                if end == -1:
                    raise PredicateSyntaxError(f"Unterminated string literal at {index}")
                self.tokens.append(text[index : end + 1])
                index = end + 1
                continue
            if char.isdigit() or (char == "-" and index + 1 < len(text) and text[index + 1].isdigit()):
                start = index
                index += 1
                while index < len(text) and (text[index].isdigit() or text[index] == "."):
                    index += 1
                self.tokens.append(text[start:index])
                continue
            if char.isalpha() or char == "_":
                start = index
                index += 1
                while index < len(text) and (text[index].isalnum() or text[index] in "_."):
                    index += 1
                self.tokens.append(text[start:index])
                continue
            raise PredicateSyntaxError(f"Unexpected character {char!r} at {index}")
        if not self.tokens:
            raise PredicateSyntaxError("Empty predicate")


class _Parser:
    """Recursive-descent parser for the CPEX APL predicate subset."""

    def __init__(self, tokens: Sequence[str]) -> None:
        """Prepare the parser.

        Args:
            tokens: Tokens from :class:`_Tokenizer`.
        """
        self._tokens = list(tokens)
        self._index = 0

    def parse(self) -> Node:
        """Parse the token stream into a predicate node.

        Returns:
            The root node.

        Raises:
            PredicateSyntaxError: On malformed input or trailing tokens.
        """
        node = self._parse_or()
        if self._index != len(self._tokens):
            raise PredicateSyntaxError(f"Unexpected token {self._peek()!r}")
        return node

    def _peek(self) -> Optional[str]:
        """Return the next token without consuming it."""
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _next(self) -> str:
        """Consume and return the next token."""
        token = self._peek()
        if token is None:
            raise PredicateSyntaxError("Unexpected end of predicate")
        self._index += 1
        return token

    def _parse_or(self) -> Node:
        """Parse ``a | b`` alternation."""
        children = [self._parse_and()]
        while self._peek() == "|":
            self._next()
            children.append(self._parse_and())
        return children[0] if len(children) == 1 else AnyOf(tuple(children))

    def _parse_and(self) -> Node:
        """Parse ``a & b`` conjunction."""
        children = [self._parse_unary()]
        while self._peek() == "&":
            self._next()
            children.append(self._parse_unary())
        return children[0] if len(children) == 1 else All(tuple(children))

    def _parse_unary(self) -> Node:
        """Parse one atom, a parenthesized group, or a require call."""
        token = self._peek()
        if token == "(":
            self._next()
            node = self._parse_or()
            if self._next() != ")":
                raise PredicateSyntaxError("Expected )")
            return node
        if token == "require":
            self._next()
            if self._next() != "(":
                raise PredicateSyntaxError("require needs (")
            children = [self._parse_or()]
            while self._peek() == ",":
                self._next()
                children.append(self._parse_or())
            if self._next() != ")":
                raise PredicateSyntaxError("Expected ) after require arguments")
            return All(tuple(children))
        return self._parse_atom()

    def _parse_atom(self) -> Node:
        """Parse truthiness, existence, comparison, or membership."""
        head = self._next()
        if head == "exists":
            if self._next() != "(":
                raise PredicateSyntaxError("exists needs (")
            attr = self._next()
            if self._next() != ")":
                raise PredicateSyntaxError("Expected ) after exists argument")
            self._validate_attr(attr)
            return Exists(attr)
        self._validate_attr(head)
        token = self._peek()
        if token in _VALID_OPERATORS:
            self._next()
            return Compare(head, token, self._literal())
        if token == "not":
            self._next()
            if self._next() != "in":
                raise PredicateSyntaxError("Expected 'in' after 'not'")
            return self._membership(head, negate=True)
        if token == "in":
            self._next()
            return self._membership(head, negate=False)
        return Truthiness(head)

    def _membership(self, attr: str, negate: bool) -> Membership:
        """Parse the collection attribute of a membership check."""
        collection = self._next()
        self._validate_attr(collection)
        return Membership(attr, collection, negate)

    def _literal(self) -> Union[bool, float, int, str]:
        """Parse a comparison literal."""
        token = self._next()
        if token in ("True", "False"):
            return token == "True"
        if token.startswith("'") and token.endswith("'") and len(token) >= 2:
            return token[1:-1]
        try:
            return int(token)
        except ValueError:
            pass
        try:
            return float(token)
        except ValueError as exc:
            raise PredicateSyntaxError(f"Invalid literal {token!r}") from exc

    @staticmethod
    def _validate_attr(attr: str) -> None:
        """Validate one attribute path token.

        Args:
            attr: Dotted attribute path.

        Raises:
            PredicateSyntaxError: When the path is malformed or too deep.
        """
        segments = attr.split(".")
        if len(segments) > _MAX_ATTR_DEPTH:
            raise PredicateSyntaxError(f"Attribute path too deep: {attr}")
        for segment in segments:
            if not segment or not (segment[0].isalpha() or segment[0] == "_"):
                raise PredicateSyntaxError(f"Invalid attribute path: {attr}")


def parse_predicate(predicate: str) -> Node:
    """Parse a predicate string into its node tree.

    Args:
        predicate: Predicate in the CPEX APL subset.

    Returns:
        The root node.

    Raises:
        PredicateSyntaxError: On any input outside the grammar.
    """
    return _Parser(_Tokenizer(predicate).tokens).parse()


def evaluate_predicate(predicate: str, attributes: Mapping[str, Any]) -> bool:
    """Parse and evaluate a predicate against the caller attributes.

    Args:
        predicate: Predicate in the CPEX APL subset.
        attributes: Nested attribute mapping built from the user context.

    Returns:
        bool: The predicate truth value. Missing attributes are false.

    Raises:
        PredicateSyntaxError: On any input outside the grammar.
    """
    return evaluate(parse_predicate(predicate), attributes)
