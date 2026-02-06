# -*- coding: utf-8 -*-
"""Location: ./plugins/examples/cdm_content_scanner/cdm_content_scanner.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

CDM Content Scanner Plugin - Example demonstrating content scanning using CDM MessageView.

This plugin shows how to use the Common Data Model's MessageView to scan
message content for sensitive patterns like PII, secrets, or prohibited content.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    MessageHookType,
    MessagePayload,
    MessageResult,
)
from mcpgateway.plugins.framework.cdm.view import ViewKind
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ScanPattern(BaseModel):
    """A pattern to scan for in content."""

    name: str = Field(description="Pattern name for reporting")
    pattern: str = Field(description="Regex pattern to match")
    severity: str = Field(default="medium", description="Severity: low, medium, high, critical")
    block: bool = Field(default=False, description="Block message if pattern found")
    scan_pre: bool = Field(default=True, description="Scan input messages (pre)")
    scan_post: bool = Field(default=True, description="Scan output messages (post)")
    view_kinds: List[str] = Field(
        default_factory=lambda: ["text", "tool_call", "tool_result"],
        description="ViewKinds to scan",
    )


class CDMContentScannerConfig(BaseModel):
    """Configuration for the CDM Content Scanner plugin."""

    patterns: List[ScanPattern] = Field(
        default_factory=list,
        description="Patterns to scan for",
    )
    log_matches: bool = Field(
        default=True,
        description="Log pattern matches",
    )
    include_match_in_metadata: bool = Field(
        default=False,
        description="Include matched text in metadata (caution: may log sensitive data)",
    )


# Default patterns for common sensitive data
DEFAULT_PATTERNS = [
    ScanPattern(
        name="ssn",
        pattern=r"\b\d{3}-\d{2}-\d{4}\b",
        severity="critical",
        block=True,
    ),
    ScanPattern(
        name="credit_card",
        pattern=r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
        severity="critical",
        block=True,
    ),
    ScanPattern(
        name="email",
        pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        severity="medium",
        block=False,
    ),
    ScanPattern(
        name="api_key",
        pattern=r'\b(?:api[_-]?key|apikey|api_token)[:\s]+[\'"]?[A-Za-z0-9\-_]{20,}[\'"]?\b',
        severity="high",
        block=True,
    ),
    ScanPattern(
        name="aws_key",
        pattern=r"\bAKIA[0-9A-Z]{16}\b",
        severity="critical",
        block=True,
    ),
]


class CDMContentScannerPlugin(Plugin):
    """Content scanning using CDM MessageView.

    This plugin demonstrates how to:
    1. Use MessageView.content to access text for scanning
    2. Use is_pre/is_post to differentiate input vs output
    3. Filter by ViewKind (text, tool_call, tool_result, etc.)
    4. Report findings with severity levels
    """

    def __init__(self, config: PluginConfig):
        """Initialize the plugin."""
        super().__init__(config)
        self.scanner_config = CDMContentScannerConfig.model_validate(self._config.config)

        # Use default patterns if none configured
        if not self.scanner_config.patterns:
            self.scanner_config.patterns = DEFAULT_PATTERNS

        # Compile regex patterns
        self.compiled_patterns: List[tuple[ScanPattern, re.Pattern]] = []
        for pattern in self.scanner_config.patterns:
            try:
                compiled = re.compile(pattern.pattern, re.IGNORECASE)
                self.compiled_patterns.append((pattern, compiled))
            except re.error as e:
                logger.error(f"Invalid regex pattern '{pattern.name}': {e}")

        logger.info(
            f"CDMContentScannerPlugin initialized with {len(self.compiled_patterns)} patterns"
        )

    def _should_scan_view(self, view: Any, pattern: ScanPattern) -> bool:
        """Check if we should scan this view with this pattern.

        Args:
            view: The MessageView to check.
            pattern: The pattern configuration.

        Returns:
            True if this view should be scanned with this pattern.
        """
        # Check pre/post filtering
        if view.is_pre and not pattern.scan_pre:
            return False
        if view.is_post and not pattern.scan_post:
            return False

        # Check view kind filtering
        if pattern.view_kinds:
            view_kind_str = view.kind.value
            if view_kind_str not in pattern.view_kinds:
                return False

        return True

    async def message_evaluate(
        self, payload: MessagePayload, context: PluginContext
    ) -> MessageResult:
        """Evaluate a message by scanning content for sensitive patterns.

        This method demonstrates how to use MessageView to:
        - Access content from any view type
        - Check is_pre/is_post for directional filtering
        - Filter by ViewKind
        - Report findings with context

        Args:
            payload: The CDM Message to evaluate.
            context: Plugin execution context.

        Returns:
            MessageResult with potential violation if blocking pattern found.
        """
        findings: List[Dict[str, Any]] = []
        blocking_finding: Optional[Dict[str, Any]] = None

        # Get views from the message
        views = payload.view(context)

        for view in views:
            # Get content to scan
            content = view.content
            if not content:
                continue

            # Check each pattern
            for pattern, compiled in self.compiled_patterns:
                # Check if we should scan this view with this pattern
                if not self._should_scan_view(view, pattern):
                    continue

                # Scan for matches
                matches = compiled.findall(content)
                if matches:
                    finding = {
                        "pattern_name": pattern.name,
                        "severity": pattern.severity,
                        "view_kind": view.kind.value,
                        "is_pre": view.is_pre,
                        "match_count": len(matches),
                    }

                    if self.scanner_config.include_match_in_metadata:
                        finding["matches"] = matches[:5]  # Limit to first 5

                    findings.append(finding)

                    if self.scanner_config.log_matches:
                        phase = "input" if view.is_pre else "output"
                        logger.warning(
                            f"Pattern '{pattern.name}' ({pattern.severity}) found in {phase} "
                            f"{view.kind.value}: {len(matches)} match(es)"
                        )

                    # Check if this should block
                    if pattern.block and blocking_finding is None:
                        blocking_finding = finding

        # Store findings in metadata
        if findings:
            context.metadata["content_scan_findings"] = findings
            context.metadata["content_scan_blocked"] = blocking_finding is not None

        # If we have a blocking finding, return violation
        if blocking_finding:
            violation = PluginViolation(
                reason=f"Sensitive content detected: {blocking_finding['pattern_name']}",
                description=f"Found {blocking_finding['severity']} severity pattern "
                            f"'{blocking_finding['pattern_name']}' in message content",
                code="SENSITIVE_CONTENT_DETECTED",
                details={
                    "pattern": blocking_finding["pattern_name"],
                    "severity": blocking_finding["severity"],
                    "view_kind": blocking_finding["view_kind"],
                    "match_count": blocking_finding["match_count"],
                },
            )
            return MessageResult(continue_processing=False, violation=violation)

        return MessageResult()

    async def shutdown(self) -> None:
        """Cleanup when plugin shuts down."""
        logger.info("CDMContentScannerPlugin shutting down")
