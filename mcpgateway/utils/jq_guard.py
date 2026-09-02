# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/jq_guard.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Static safety gate for user-supplied jq filters.

Tool ``jsonpath_filter`` values are compiled and executed by the gateway. jq
exposes built-ins that read the host process environment (``env``, ``$ENV``),
read host state (``input_filename``, ``$__loc__``), write to the gateway's
stderr (``debug``, ``stderr``), and load code from disk (``include``,
``import``, ``modulemeta``). None of those belong in a response filter.

This module rejects them before compilation. It is deliberately free of
``mcpgateway`` imports so that ``schemas.py`` can use it at validation time
without creating an import cycle through ``tool_service``.

The scanner is not a full jq parser. It tracks just enough structure to avoid
two classes of mistake a plain regex makes: it does not match denied names
inside string literals or comments, and it does descend into ``\\(...)``
interpolation, which is executable code. An identifier directly preceded by
``.`` is field access rather than a built-in, and jq rejects whitespace between
the dot and the name, so that suppression cannot be bypassed.
"""

# Future
from __future__ import annotations

# Standard
import re
from typing import Set

__all__ = ["DENIED_JQ_TOKENS", "assert_safe_jq_filter", "scan_jq_tokens"]

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

DENIED_JQ_TOKENS = frozenset(
    {
        # Process environment.
        "env",
        "$ENV",
        # Input-stream reads.
        "input",
        "inputs",
        # Host state.
        "input_filename",
        "input_line_number",
        "$__loc__",
        # Writes to the gateway's own stderr.
        "debug",
        "stderr",
        # Filesystem module loading.
        "include",
        "import",
        "modulemeta",
    }
)


def scan_jq_tokens(text: str) -> Set[str]:
    """Collect identifier and ``$name`` tokens that jq would treat as code.

    String literals and ``#`` comments are skipped. ``\\(...)`` interpolation is
    entered, including when nested inside a further string. Identifiers directly
    preceded by ``.`` are omitted because they are field names.

    Args:
        text: The jq filter source.

    Returns:
        The set of code-position tokens found.

    Examples:
        >>> sorted(scan_jq_tokens(".a|env"))
        ['env']
        >>> sorted(scan_jq_tokens(".env"))
        []
        >>> sorted(scan_jq_tokens('"env"'))
        []
        >>> sorted(scan_jq_tokens('"\\\\(env)"'))
        ['env']
    """
    tokens: Set[str] = set()
    modes = ["code"]  # innermost last: "code" or "string"
    depths = [0]  # paren depth for each code frame
    prev = ""  # previous significant character in the current code frame
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if modes[-1] == "string":
            if char == "\\":
                if index + 1 < length and text[index + 1] == "(":
                    modes.append("code")
                    depths.append(0)
                    prev = ""
                    index += 2
                    continue
                index += 2
                continue
            if char == '"':
                modes.pop()
                index += 1
                continue
            index += 1
            continue

        if char == "#":
            while index < length and text[index] != "\n":
                index += 1
            continue

        if char == '"':
            modes.append("string")
            prev = '"'
            index += 1
            continue

        if char == "(":
            depths[-1] += 1
            prev = "("
            index += 1
            continue

        if char == ")":
            if depths[-1] == 0 and len(modes) > 1:
                modes.pop()
                depths.pop()
                prev = ""
                index += 1
                continue
            if depths[-1] > 0:
                depths[-1] -= 1
            prev = ")"
            index += 1
            continue

        if char == "$":
            match = _IDENT.match(text, index + 1)
            if match:
                tokens.add("$" + match.group(0))
                prev = "w"
                index = match.end()
                continue
            prev = "$"
            index += 1
            continue

        match = _IDENT.match(text, index)
        if match:
            if prev != ".":
                tokens.add(match.group(0))
            prev = "w"
            index = match.end()
            continue

        if not char.isspace():
            prev = char
        index += 1

    return tokens


def assert_safe_jq_filter(jq_filter: str) -> None:
    """Reject a jq filter that uses a restricted built-in.

    Args:
        jq_filter: The jq filter source to check.

    Raises:
        ValueError: If the filter references a denied built-in.

    Examples:
        >>> assert_safe_jq_filter(".a.b") is None
        True
        >>> assert_safe_jq_filter("$ENV")
        Traceback (most recent call last):
            ...
        ValueError: jq filter uses a restricted built-in: $ENV
    """
    if not jq_filter:
        return None

    denied = sorted(scan_jq_tokens(jq_filter) & DENIED_JQ_TOKENS)
    if denied:
        raise ValueError(f"jq filter uses a restricted built-in: {', '.join(denied)}")
    return None
