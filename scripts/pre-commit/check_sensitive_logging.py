#!/usr/bin/env python3
"""Pre-commit hook: detect sensitive variable interpolation in logger calls.

Scans Python files for logger.{debug,info,warning,error,exception,critical}()
calls that interpolate variables whose names match known sensitive identifiers
(e.g. ``token``, ``password``, ``client_secret``).

Exit codes:
    0 - no violations found
    1 - violations detected (printed to stderr)

When invoked by pre-commit with ``pass_filenames: true``, only the staged files
are checked.  Can also be run standalone against explicit paths or a directory::

    python scripts/check_sensitive_logging.py mcpgateway/
    python scripts/check_sensitive_logging.py mcpgateway/auth.py mcpgateway/services/oauth.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SENSITIVE_IDENTIFIERS = {
    "access_token",
    "auth_token",
    "auth_value",
    "authorization",
    "client_secret",
    "id_token",
    "password",
    "refresh_token",
    "registration_access_token",
    "token",
}

SAFE_TOKEN_OBJECT_FIELDS = {"id", "jti", "name", "token_hash"}

LOGGER_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _is_safe_token_attribute(expression: ast.AST) -> bool:
    """Allow non-secret token metadata logs (e.g. token.id, token.name)."""
    return isinstance(expression, ast.Attribute) and isinstance(expression.value, ast.Name) and expression.value.id == "token" and expression.attr in SAFE_TOKEN_OBJECT_FIELDS


def _contains_sensitive_identifier(expression: ast.AST) -> bool:
    """Detect direct logging of sensitive variables or attributes."""
    if _is_safe_token_attribute(expression):
        return False

    for node in ast.walk(expression):
        if isinstance(node, ast.Name) and node.id in SENSITIVE_IDENTIFIERS:
            return True
        if isinstance(node, ast.Attribute) and node.attr in SENSITIVE_IDENTIFIERS:
            return True
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "credentials" and node.attr == "credentials":
            return True

    return False


def _check_file(file_path: Path) -> list[str]:
    """Return a list of ``file:line`` violation strings for *file_path*."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    if "logger." not in source:
        return []

    sensitive_needles = tuple(SENSITIVE_IDENTIFIERS) + ("credentials",)
    if not any(needle in source for needle in sensitive_needles):
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in LOGGER_METHODS:
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
            continue

        expressions_to_check: list[ast.AST] = []

        if node.args:
            message_expr = node.args[0]
            if isinstance(message_expr, ast.JoinedStr):
                for value in message_expr.values:
                    if isinstance(value, ast.FormattedValue):
                        expressions_to_check.append(value.value)
            # %-style / positional log args
            expressions_to_check.extend(node.args[1:])

        for expr in expressions_to_check:
            if _contains_sensitive_identifier(expr):
                violations.append(f"{file_path}:{node.lineno}")
                break

    return violations


def main() -> int:
    """Entry point."""
    paths = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else [Path("mcpgateway")]

    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(p.rglob("*.py"))
        elif p.suffix == ".py":
            files.append(p)

    violations: list[str] = []
    for f in files:
        violations.extend(_check_file(f))

    if violations:
        print("Sensitive variable interpolation in logger calls:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
