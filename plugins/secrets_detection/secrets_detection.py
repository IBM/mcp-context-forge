# -*- coding: utf-8 -*-
"""Location: ./plugins/secrets_detection/secrets_detection.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Secrets Detection Plugin.

Detects likely credentials and secrets in inputs and outputs using regex and simple heuristics.

Hooks: prompt_pre_fetch, tool_post_invoke, resource_post_fetch
"""

# Future
from __future__ import annotations

# Standard
import logging
import re
from typing import Any, Dict, Tuple

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
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

# Initialize logging
logger = logging.getLogger(__name__)

# Try to import Rust-accelerated implementation
try:
    from secrets_detection_rust.secrets_detection_rust import py_scan_container as secrets_detection

    _RUST_AVAILABLE = True
    logger.info("🦀 Rust secrets detection available - using high-performance implementation (2-8x speedup)")
except ImportError as e:
    _RUST_AVAILABLE = False
    secrets_detection = None  # type: ignore
    logger.debug(f"Rust secrets detection not available (will use Python): {e}")
except Exception as e:
    _RUST_AVAILABLE = False
    secrets_detection = None  # type: ignore
    logger.warning(f"⚠️  Unexpected error loading Rust module: {e}", exc_info=True)

PATTERNS = {
    "aws_access_key_id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "aws_secret_access_key": re.compile(r"(?i)aws.{0,20}(?:secret|access).{0,20}=\s*([A-Za-z0-9/+=]{40})"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    "slack_token": re.compile(r"\bxox[abpqr]-[0-9A-Za-z\-]{10,48}\b"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----"),
    "jwt_like": re.compile(r"\beyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\b"),
    "hex_secret_32": re.compile(r"\b[a-f0-9]{32,}\b", re.IGNORECASE),
    "base64_24": re.compile(r"\b[A-Za-z0-9+/]{24,}={0,2}\b"),
}


class SecretsDetectionConfig(BaseModel):
    """Configuration for secrets detection.

    Attributes:
        enabled: Map of pattern names to whether they are enabled.
        redact: Whether to redact detected secrets.
        redaction_text: Text to replace secrets with when redacting.
        block_on_detection: Whether to block when secrets are detected.
        min_findings_to_block: Minimum number of findings required to block.
    """

    enabled: Dict[str, bool] = {k: True for k in PATTERNS.keys()}
    redact: bool = False
    redaction_text: str = "***REDACTED***"
    block_on_detection: bool = True
    min_findings_to_block: int = 1


def _detect(text: str, cfg: SecretsDetectionConfig) -> list[dict[str, Any]]:
    """Detect secrets in text using configured patterns.

    Args:
        text: Text to scan for secrets.
        cfg: Secrets detection configuration.

    Returns:
        List of findings with type and match preview.
    """
    findings: list[dict[str, Any]] = []
    for name, pat in PATTERNS.items():
        if not cfg.enabled.get(name, True):
            continue
        for m in pat.finditer(text):
            findings.append({"type": name, "match": m.group(0)[:8] + "…" if len(m.group(0)) > 8 else m.group(0)})
    return findings


def _scan_container(container: Any, cfg: SecretsDetectionConfig, use_rust: bool = True) -> Tuple[int, Any, list[dict[str, Any]]]:
    """Recursively scan container for secrets and optionally redact.

    Args:
        container: Container to scan (str, dict, list, or other).
        cfg: Secrets detection configuration.
        use_rust: Whether to use Rust implementation if available (default: True).

    Returns:
        Tuple of (count, redacted_container, all_findings).
    """
    # Use Rust implementation if available and requested
    if use_rust and _RUST_AVAILABLE and secrets_detection is not None:
        try:
            logger.debug("Using Rust implementation")
            # Pass Pydantic model directly - Rust extracts attributes
            return secrets_detection(container, cfg)
        except Exception as e:
            logger.warning(f"Rust scan failed, falling back to Python: {e}")
            # Fall through to Python implementation

    # Python implementation
    logger.debug(f"Using Python implementation (use_rust={use_rust}, _RUST_AVAILABLE={_RUST_AVAILABLE})")
    total = 0
    redacted = container
    all_findings: list[dict[str, Any]] = []
    if isinstance(container, str):
        f = _detect(container, cfg)
        total += len(f)
        all_findings.extend(f)
        if cfg.redact and f:
            # Replace matches with redaction text (best-effort)
            for name, pat in PATTERNS.items():
                if cfg.enabled.get(name, True):
                    redacted = pat.sub(cfg.redaction_text, redacted)
        return total, redacted, all_findings
    if isinstance(container, dict):
        new = {}
        for k, v in container.items():
            c, rv, f = _scan_container(v, cfg, use_rust=use_rust)
            total += c
            all_findings.extend(f)
            new[k] = rv
        return total, new, all_findings
    if isinstance(container, list):
        new_list = []
        for v in container:
            c, rv, f = _scan_container(v, cfg, use_rust=use_rust)
            total += c
            all_findings.extend(f)
            new_list.append(rv)
        return total, new_list, all_findings
    return total, container, all_findings


class SecretsDetectionPlugin(Plugin):
    """Detect and optionally redact secrets in inputs/outputs."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the secrets detection plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = SecretsDetectionConfig(**(config.config or {}))

        # Set implementation type based on Rust availability
        if _RUST_AVAILABLE:
            self.implementation = "Rust"
            logger.info("🦀 SecretsDetectionPlugin initialized with Rust acceleration (2-7x speedup)")
        else:
            self.implementation = "Python"
            logger.info("🐍 SecretsDetectionPlugin initialized with Python implementation")

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Detect secrets in prompt arguments.

        Args:
            payload: Prompt payload.
            context: Plugin execution context.

        Returns:
            Result indicating secrets found or content redacted.
        """
        count, new_args, findings = _scan_container(payload.args or {}, self._cfg)
        if count >= self._cfg.min_findings_to_block and self._cfg.block_on_detection:
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Secrets detected",
                    description="Potential secrets detected in prompt arguments",
                    code="SECRETS_DETECTED",
                    details={"count": count, "examples": findings[:5]},
                ),
            )
        if self._cfg.redact and new_args != (payload.args or {}):
            return PromptPrehookResult(modified_payload=PromptPrehookPayload(prompt_id=payload.prompt_id, args=new_args), metadata={"secrets_redacted": True, "count": count})
        return PromptPrehookResult(metadata={"secrets_findings": findings, "count": count} if count else {})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Detect secrets in tool results.

        Args:
            payload: Tool result payload.
            context: Plugin execution context.

        Returns:
            Result indicating secrets found or content redacted.
        """
        count, new_result, findings = _scan_container(payload.result, self._cfg)
        if count >= self._cfg.min_findings_to_block and self._cfg.block_on_detection:
            return ToolPostInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Secrets detected",
                    description="Potential secrets detected in tool result",
                    code="SECRETS_DETECTED",
                    details={"count": count, "examples": findings[:5]},
                ),
            )
        if self._cfg.redact and new_result != payload.result:
            return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result), metadata={"secrets_redacted": True, "count": count})
        return ToolPostInvokeResult(metadata={"secrets_findings": findings, "count": count} if count else {})

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Detect secrets in fetched resource content.

        Args:
            payload: Resource post-fetch payload.
            context: Plugin execution context.

        Returns:
            Result indicating secrets found or content redacted.
        """
        content = payload.content
        # Only scan textual content
        if hasattr(content, "text") and isinstance(content.text, str):
            count, new_text, findings = _scan_container(content.text, self._cfg)
            if count >= self._cfg.min_findings_to_block and self._cfg.block_on_detection:
                return ResourcePostFetchResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Secrets detected",
                        description="Potential secrets detected in resource content",
                        code="SECRETS_DETECTED",
                        details={"count": count, "examples": findings[:5]},
                    ),
                )
            if self._cfg.redact and new_text != content.text:
                new_payload = ResourcePostFetchPayload(uri=payload.uri, content=type(content)(**{**content.model_dump(), "text": new_text}))
                return ResourcePostFetchResult(modified_payload=new_payload, metadata={"secrets_redacted": True, "count": count})
            return ResourcePostFetchResult(metadata={"secrets_findings": findings, "count": count} if count else {})
        return ResourcePostFetchResult(continue_processing=True)
