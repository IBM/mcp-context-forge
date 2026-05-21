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
from typing import Any, Optional, Pattern

# Third-Party
from pydantic import BaseModel, ConfigDict, field_validator

# First-Party
from cpex.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


_DEFAULT_BLOCKED = [
    r"\bDROP\b",
    r"\bTRUNCATE\b",
    r"\bALTER\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
]

# Precompiled regex patterns for better performance
_LINE_COMMENT_RE = re.compile(r"--.*?$", flags=re.MULTILINE)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", flags=re.DOTALL)
_DELETE_FROM_RE = re.compile(r"\bDELETE\b\s+\bFROM\b", flags=re.IGNORECASE)
_UPDATE_RE = re.compile(r"\bUPDATE\b\s+\w+", flags=re.IGNORECASE)
_WHERE_RE = re.compile(r"\bWHERE\b", flags=re.IGNORECASE)


class SQLSanitizerConfig(BaseModel):
    """Configuration for SQL sanitization.

    Attributes:
        fields: Argument fields to scan for SQL (None = all strings).
        blocked_statements: List of compiled regex patterns for blocked SQL statements.
        block_delete_without_where: Whether to block DELETE without WHERE.
        block_update_without_where: Whether to block UPDATE without WHERE.
        strip_comments: Whether to remove SQL comments.
        require_parameterization: Whether to require parameterized queries.
        block_on_violation: Whether to block on violations.
    """

    fields: Optional[list[str]] = None  # which arg keys to scan; None = all strings
    blocked_statements: list[Pattern[str]] = [re.compile(pat, re.IGNORECASE) for pat in _DEFAULT_BLOCKED]
    block_delete_without_where: bool = True
    block_update_without_where: bool = True
    strip_comments: bool = True
    require_parameterization: bool = False
    block_on_violation: bool = True

    @field_validator("blocked_statements", mode="before")
    @classmethod
    def compile_patterns(cls, v: Any) -> list[Pattern[str]]:
        """Compile string patterns to regex Pattern objects.

        Args:
            v: List of regex pattern strings or Pattern objects.

        Returns:
            List of compiled Pattern objects.
        """
        if not isinstance(v, list):
            return v
        compiled = []
        for item in v:
            if isinstance(item, str):
                compiled.append(re.compile(item, re.IGNORECASE))
            elif isinstance(item, Pattern):
                compiled.append(item)
            else:
                compiled.append(item)
        return compiled

    model_config = ConfigDict(arbitrary_types_allowed=True)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments from query text.

    Args:
        sql: SQL query string.

    Returns:
        SQL string with comments removed.
    """
    # Remove -- line comments and /* */ block comments
    sql = _LINE_COMMENT_RE.sub("", sql)
    sql = _BLOCK_COMMENT_RE.sub("", sql)
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
    # Dangerous statements - patterns are already compiled
    for pat in cfg.blocked_statements:
        if pat.search(sql):
            issues.append(f"Blocked statement matched: {pat.pattern}")
    # DELETE without WHERE
    if cfg.block_delete_without_where and _DELETE_FROM_RE.search(sql):
        if not _WHERE_RE.search(sql):
            issues.append("DELETE without WHERE clause")
    # UPDATE without WHERE
    if cfg.block_update_without_where and _UPDATE_RE.search(sql):
        if not _WHERE_RE.search(sql):
            issues.append("UPDATE without WHERE clause")
    # Parameterization / interpolation checks
    if cfg.require_parameterization and _has_interpolation(original):
        issues.append("Possible non-parameterized interpolation detected")
    return issues


def _scan_value(key: str, value: Any, cfg: SQLSanitizerConfig, issues: list[str], scanned: dict[str, Any]) -> None:
    """Recursively scan a value for SQL issues, respecting cfg.fields for key filtering.

    Only string values whose key is in cfg.fields (or all string values when
    cfg.fields is None) are passed to _find_issues.  Nested dicts and lists are
    walked regardless of the key so that deeply-nested field names are still
    checked against cfg.fields.

    Args:
        key: The field name associated with this value.
        value: The value to inspect.
        cfg: Sanitization configuration.
        issues: Accumulator for issue strings (mutated in place).
        scanned: Accumulator for sanitized replacements (mutated in place).
    """
    if isinstance(value, str):
        # Apply field-name filter only at the leaf string level
        if cfg.fields is None or key in cfg.fields:
            found = _find_issues(value, cfg)
            if found:
                issues.extend([f"{key}: {m}" for m in found])
            if cfg.strip_comments:
                clean = _strip_sql_comments(value)
                if clean != value:
                    scanned[key] = clean
    elif isinstance(value, dict):
        for k, v in value.items():
            _scan_value(k, v, cfg, issues, scanned)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                for k, v in item.items():
                    _scan_value(k, v, cfg, issues, scanned)
            elif isinstance(item, str):
                # List items that are plain strings inherit the parent key
                if cfg.fields is None or key in cfg.fields:
                    found = _find_issues(item, cfg)
                    if found:
                        issues.extend([f"{key}[]: {m}" for m in found])


def _scan_args(args: dict[str, Any] | None, cfg: SQLSanitizerConfig) -> tuple[list[str], dict[str, Any]]:
    """Scan tool arguments for SQL issues, including deeply nested structures.

    Walks all top-level keys and recurses into nested dicts and lists.
    String values are only checked when their key matches cfg.fields
    (or unconditionally when cfg.fields is None).

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
        _scan_value(k, v, cfg, issues, scanned)
    return issues, scanned


class SQLSanitizerPlugin(Plugin):
    """Block or sanitize risky SQL statements in inputs."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the SQL sanitizer plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        logger.debug(f"SQL-SANITIZER config: {config}")
        self._cfg = SQLSanitizerConfig(**(config.config or {}))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Scan prompt arguments for risky SQL.

        Args:
            payload: Prompt payload.
            context: Plugin execution context.

        Returns:
            Result indicating SQL issues found or sanitized.
        """
        logger.debug(f"SQL-SANITIZER payload: {payload.args} config: {self._cfg}")
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
            return PromptPrehookResult(modified_payload=PromptPrehookPayload(prompt_id=payload.prompt_id, args=new_args), metadata={"sql_sanitized": True})
        return PromptPrehookResult(metadata={"sql_issues": issues} if issues else {})

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Scan tool arguments for risky SQL.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result indicating SQL issues found or sanitized.
        """
        logger.debug(f"SQL-SANITIZER payload: {payload.args} config: {self._cfg}")
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
