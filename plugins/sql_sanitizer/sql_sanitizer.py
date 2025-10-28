# -*- coding: utf-8 -*-
"""Location: ./plugins/sql_sanitizer/sql_sanitizer.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

SQL Sanitizer Plugin.

Detects risky SQL patterns and optionally sanitizes or blocks.
Target fields are scanned for SQL text; comments can be stripped,
dangerous statements flagged, and simple heuristic checks for
non-parameterized interpolation are applied.

Hooks: prompt_pre_fetch, tool_pre_invoke
"""

# Future
from __future__ import annotations

# Standard
import re
from typing import Any, Optional

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

_DEFAULT_BLOCKED = [
    r"\bDROP\b",
    r"\bTRUNCATE\b",
    r"\bALTER\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
]


class SQLSanitizerConfig(BaseModel):
    """Configuration for SQL sanitization.

    Attributes:
        fields: Argument fields to scan for SQL (None = all strings).
        blocked_statements: List of regex patterns for blocked SQL statements.
        block_delete_without_where: Whether to block DELETE without WHERE.
        block_update_without_where: Whether to block UPDATE without WHERE.
        strip_comments: Whether to remove SQL comments.
        require_parameterization: Whether to require parameterized queries.
        block_on_violation: Whether to block on violations.
    """

    fields: Optional[list[str]] = None  # which arg keys to scan; None = all strings
    blocked_statements: list[str] = _DEFAULT_BLOCKED
    block_delete_without_where: bool = True
    block_update_without_where: bool = True
    strip_comments: bool = True
    require_parameterization: bool = False
    block_on_violation: bool = True


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments from query text.

    Args:
        sql: SQL query string.

    Returns:
        SQL string with comments removed.
    """
    # Remove -- line comments and /* */ block comments
    sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql


def _has_interpolation(sql: str) -> bool:
    """Check for naive string interpolation heuristics.

    Args:
        sql: SQL query string.

    Returns:
        True if interpolation patterns detected.
    """
    # Heuristics for naive string concatenation or f-strings
    if "+" in sql or "%." in sql or "{" in sql and "}" in sql:
        return True
    return False


def _find_issues(sql: str, cfg: SQLSanitizerConfig) -> list[str]:
    """Find SQL security issues in query text.

    Args:
        sql: SQL query string.
        cfg: Sanitization configuration.

    Returns:
        List of issue descriptions.
    """
    original = sql
    if cfg.strip_comments:
        sql = _strip_sql_comments(sql)
    issues: list[str] = []
    # Dangerous statements
    for pat in cfg.blocked_statements:
        if re.search(pat, sql, flags=re.IGNORECASE):
            issues.append(f"Blocked statement matched: {pat}")
    # DELETE without WHERE
    if cfg.block_delete_without_where and re.search(r"\bDELETE\b\s+\bFROM\b", sql, flags=re.IGNORECASE):
        if not re.search(r"\bWHERE\b", sql, flags=re.IGNORECASE):
            issues.append("DELETE without WHERE clause")
    # UPDATE without WHERE
    if cfg.block_update_without_where and re.search(r"\bUPDATE\b\s+\w+", sql, flags=re.IGNORECASE):
        if not re.search(r"\bWHERE\b", sql, flags=re.IGNORECASE):
            issues.append("UPDATE without WHERE clause")
    # Parameterization / interpolation checks
    if cfg.require_parameterization and _has_interpolation(original):
        issues.append("Possible non-parameterized interpolation detected")
    return issues


def _scan_args(args: dict[str, Any] | None, cfg: SQLSanitizerConfig) -> tuple[list[str], dict[str, Any]]:
    """Scan tool arguments for SQL issues.

    Args:
        args: Tool arguments dictionary.
        cfg: Sanitization configuration.

    Returns:
        Tuple of (issues list, sanitized args dict).
    """
    issues: list[str] = []
    if not args:
        return issues, {}
    scanned: dict[str, Any] = {}
    for k, v in args.items():
        if cfg.fields and k not in cfg.fields:
            continue
        if isinstance(v, str):
            found = _find_issues(v, cfg)
            if found:
                issues.extend([f"{k}: {m}" for m in found])
            if cfg.strip_comments:
                clean = _strip_sql_comments(v)
                if clean != v:
                    scanned[k] = clean
    return issues, scanned


class SQLSanitizerPlugin(Plugin):
    """Block or sanitize risky SQL statements in inputs."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the SQL sanitizer plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = SQLSanitizerConfig(**(config.config or {}))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Scan prompt arguments for risky SQL.

        Args:
            payload: Prompt payload.
            context: Plugin execution context.

        Returns:
            Result indicating SQL issues found or sanitized.
        """
        issues, scanned = _scan_args(payload.args or {}, self._cfg)
        if issues and self._cfg.block_on_violation:
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Risky SQL detected",
                    description="Potentially dangerous SQL detected in prompt args",
                    code="SQL_SANITIZER",
                    details={"issues": issues},
                ),
            )
        if scanned:
            new_args = {**(payload.args or {}), **scanned}
            return PromptPrehookResult(modified_payload=PromptPrehookPayload(name=payload.name, args=new_args), metadata={"sql_sanitized": True})
        return PromptPrehookResult(metadata={"sql_issues": issues} if issues else {})

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Scan tool arguments for risky SQL.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result indicating SQL issues found or sanitized.
        """
        issues, scanned = _scan_args(payload.args or {}, self._cfg)
        if issues and self._cfg.block_on_violation:
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Risky SQL detected",
                    description="Potentially dangerous SQL detected in tool args",
                    code="SQL_SANITIZER",
                    details={"issues": issues},
                ),
            )
        if scanned:
            new_args = {**(payload.args or {}), **scanned}
            return ToolPreInvokeResult(modified_payload=ToolPreInvokePayload(name=payload.name, args=new_args), metadata={"sql_sanitized": True})
        return ToolPreInvokeResult(metadata={"sql_issues": issues} if issues else {})
