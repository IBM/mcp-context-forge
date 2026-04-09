# -*- coding: utf-8 -*-
"""Location: ./plugins/atr_threat_detection/atr_threat_detection.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

ATR Threat Detection Plugin.

Detects AI agent threats using regex-based ATR (Agent Threat Rules) community rules.
Scans prompts, tool invocations, tool results, and resources for known attack patterns
covering the OWASP Agentic Top 10: prompt injection, tool poisoning, context exfiltration,
privilege escalation, excessive autonomy, agent manipulation, skill compromise, and
data poisoning.

Hooks: prompt_pre_fetch, tool_pre_invoke, tool_post_invoke, resource_post_fetch
"""

# Future
from __future__ import annotations

# Standard
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

logger = logging.getLogger(__name__)

# Severity ordering for threshold comparison
SEVERITY_LEVELS: Dict[str, int] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

# Maximum text length to scan (guard against extremely large payloads)
MAX_SCAN_LENGTH = 500_000


class CompiledRule:
    """A single ATR rule with pre-compiled regex patterns.

    Attributes:
        rule_id: ATR rule identifier.
        title: Human-readable rule title.
        severity: Severity level string.
        severity_level: Numeric severity for threshold comparison.
        category: Threat category slug.
        threat_category: Human-readable threat category.
        patterns: List of compiled regex patterns.
    """

    __slots__ = ("rule_id", "title", "severity", "severity_level", "category", "threat_category", "patterns")

    def __init__(self, rule_id: str, title: str, severity: str, category: str, threat_category: str, patterns: List[re.Pattern[str]]) -> None:
        """Initialize a compiled ATR rule.

        Args:
            rule_id: ATR rule identifier.
            title: Human-readable rule title.
            severity: Severity level string.
            category: Threat category slug.
            threat_category: Human-readable threat category.
            patterns: List of compiled regex patterns.
        """
        self.rule_id = rule_id
        self.title = title
        self.severity = severity
        self.severity_level = SEVERITY_LEVELS.get(severity, 2)
        self.category = category
        self.threat_category = threat_category
        self.patterns = patterns


def _load_rules(rules_path: Path) -> List[CompiledRule]:
    """Load and compile ATR rules from a JSON file.

    Args:
        rules_path: Path to the rules JSON file.

    Returns:
        List of compiled ATR rules.

    Raises:
        FileNotFoundError: If the rules file does not exist.
        json.JSONDecodeError: If the rules file contains invalid JSON.
    """
    raw = json.loads(rules_path.read_text(encoding="utf-8"))
    compiled: List[CompiledRule] = []
    for entry in raw:
        patterns: List[re.Pattern[str]] = []
        for pat_str in entry.get("patterns", []):
            try:
                patterns.append(re.compile(pat_str))
            except re.error as exc:
                logger.warning("Skipping invalid regex in rule %s: %s", entry.get("id", "?"), exc)
        if patterns:
            compiled.append(
                CompiledRule(
                    rule_id=entry["id"],
                    title=entry.get("title", ""),
                    severity=entry.get("severity", "medium"),
                    category=entry.get("category", ""),
                    threat_category=entry.get("threat_category", ""),
                    patterns=patterns,
                )
            )
    return compiled


def _flatten_to_text(container: Any) -> str:
    """Recursively flatten a container (str, dict, list) into a single text string.

    Args:
        container: Value to flatten.

    Returns:
        Concatenated string representation of all text values.
    """
    if isinstance(container, str):
        return container
    if isinstance(container, dict):
        parts = []
        for value in container.values():
            parts.append(_flatten_to_text(value))
        return " ".join(parts)
    if isinstance(container, list):
        parts = []
        for item in container:
            parts.append(_flatten_to_text(item))
        return " ".join(parts)
    return str(container) if container is not None else ""


class ATRThreatDetectionPlugin(Plugin):
    """Detect AI agent threats using ATR community rules.

    Performs regex-based scanning of prompts, tool invocations, tool results,
    and resource content against a bundled set of ATR rules. Pure regex with
    no external API calls -- typical scan latency is <5ms.
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the ATR threat detection plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        cfg = config.config or {}
        self._block_on_detection: bool = cfg.get("block_on_detection", True)
        self._min_severity: str = cfg.get("min_severity", "medium")
        self._min_severity_level: int = SEVERITY_LEVELS.get(self._min_severity, 2)

        rules_path = Path(__file__).parent / "rules.json"
        self._rules = _load_rules(rules_path)
        logger.info(
            "ATRThreatDetectionPlugin initialized: %d rules loaded, min_severity=%s, block=%s",
            len(self._rules),
            self._min_severity,
            self._block_on_detection,
        )

    def _scan_text(self, text: str) -> List[Dict[str, Any]]:
        """Run all compiled ATR patterns against text and return findings.

        Only rules meeting or exceeding the configured minimum severity threshold
        are evaluated.

        Args:
            text: Text to scan for threats.

        Returns:
            List of finding dicts with rule_id, title, severity, category, and match_preview.
        """
        if not text:
            return []
        # Guard against extremely large payloads
        scan_text = text[:MAX_SCAN_LENGTH] if len(text) > MAX_SCAN_LENGTH else text
        findings: List[Dict[str, Any]] = []
        for rule in self._rules:
            if rule.severity_level < self._min_severity_level:
                continue
            for pattern in rule.patterns:
                match = pattern.search(scan_text)
                if match:
                    matched_str = match.group(0)
                    preview = (matched_str[:40] + "...") if len(matched_str) > 40 else matched_str
                    findings.append(
                        {
                            "rule_id": rule.rule_id,
                            "title": rule.title,
                            "severity": rule.severity,
                            "category": rule.category,
                            "match_preview": preview,
                        }
                    )
                    break  # One match per rule is sufficient
        return findings

    def _make_violation(self, findings: List[Dict[str, Any]], scan_target: str) -> PluginViolation:
        """Create a PluginViolation from findings.

        Args:
            findings: List of finding dicts.
            scan_target: Description of what was scanned.

        Returns:
            PluginViolation instance.
        """
        matched_rules = [f"{f['rule_id']} ({f['title']})" for f in findings]
        max_severity = max(SEVERITY_LEVELS.get(f["severity"], 2) for f in findings)
        severity_name = {v: k for k, v in SEVERITY_LEVELS.items()}.get(max_severity, "medium")
        return PluginViolation(
            reason="Agent threat detected",
            description=f"ATR rules matched in {scan_target}: {', '.join(matched_rules[:5])}",
            code="ATR_THREAT_DETECTED",
            details={
                "count": len(findings),
                "max_severity": severity_name,
                "rules": findings[:10],
            },
        )

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Scan prompt arguments for agent threats.

        Args:
            payload: Prompt payload.
            context: Plugin execution context.

        Returns:
            Result indicating threats found or clean.
        """
        text = _flatten_to_text(payload.args or {})
        findings = self._scan_text(text)
        if findings and self._block_on_detection:
            return PromptPrehookResult(
                continue_processing=False,
                violation=self._make_violation(findings, "prompt arguments"),
            )
        return PromptPrehookResult(metadata={"atr_findings": findings, "count": len(findings)})

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Scan tool name and arguments for agent threats before invocation.

        Args:
            payload: Tool pre-invoke payload.
            context: Plugin execution context.

        Returns:
            Result indicating threats found or clean.
        """
        parts = [payload.name or ""]
        args = getattr(payload, "args", None) or getattr(payload, "arguments", None) or {}
        parts.append(_flatten_to_text(args))
        text = " ".join(parts)
        findings = self._scan_text(text)
        if findings and self._block_on_detection:
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=self._make_violation(findings, "tool invocation"),
            )
        return ToolPreInvokeResult(metadata={"atr_findings": findings, "count": len(findings)})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Scan tool results for agent threats (credential leaks, exfiltration, injection).

        Args:
            payload: Tool post-invoke payload.
            context: Plugin execution context.

        Returns:
            Result indicating threats found or clean.
        """
        text = _flatten_to_text(payload.result)
        findings = self._scan_text(text)
        if findings and self._block_on_detection:
            return ToolPostInvokeResult(
                continue_processing=False,
                violation=self._make_violation(findings, "tool result"),
            )
        return ToolPostInvokeResult(metadata={"atr_findings": findings, "count": len(findings)})

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Scan fetched resource content for agent threats.

        Args:
            payload: Resource post-fetch payload.
            context: Plugin execution context.

        Returns:
            Result indicating threats found or clean.
        """
        content = payload.content
        text = ""
        if hasattr(content, "text") and isinstance(content.text, str):
            text = content.text
        elif isinstance(content, str):
            text = content
        else:
            text = _flatten_to_text(content)
        findings = self._scan_text(text)
        if findings and self._block_on_detection:
            return ResourcePostFetchResult(
                continue_processing=False,
                violation=self._make_violation(findings, "resource content"),
            )
        return ResourcePostFetchResult(metadata={"atr_findings": findings, "count": len(findings)})
