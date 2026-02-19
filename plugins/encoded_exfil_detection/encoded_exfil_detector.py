# -*- coding: utf-8 -*-
"""Location: ./plugins/encoded_exfil_detection/encoded_exfil_detector.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Encoded Exfiltration Detector Plugin.

Detects suspicious encoded payloads (base64, base64url, hex, percent-encoding,
hex escapes) in prompt args and tool outputs, then blocks or redacts.

Hooks: prompt_pre_fetch, tool_post_invoke
"""

# Future
from __future__ import annotations

# Standard
import base64
import binascii
import logging
import math
import re
from typing import Any, Dict, Iterable, Tuple
from urllib.parse import unquote_to_bytes

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

logger = logging.getLogger(__name__)

# Try to import Rust-accelerated implementation
try:
    from encoded_exfil_detection_rust.encoded_exfil_detection_rust import py_scan_container as encoded_exfil_detection

    _RUST_AVAILABLE = True
    logger.info("🦀 Rust encoded exfil detector available - using high-performance implementation")
except ImportError as e:
    _RUST_AVAILABLE = False
    encoded_exfil_detection = None  # type: ignore
    logger.debug(f"Rust encoded exfil detector not available (will use Python): {e}")
except Exception as e:  # pragma: no cover - defensive import guard
    _RUST_AVAILABLE = False
    encoded_exfil_detection = None  # type: ignore
    logger.warning(f"Unexpected error loading Rust encoded exfil module: {e}", exc_info=True)

# Precompiled detector patterns (minimum candidate length enforced in code)
_PATTERNS: Dict[str, re.Pattern[str]] = {
    "base64": re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=])"),
    "base64url": re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{16,}={0,2}(?![A-Za-z0-9_\-])"),
    "hex": re.compile(r"(?<![A-Fa-f0-9])[A-Fa-f0-9]{24,}(?![A-Fa-f0-9])"),
    "percent_encoding": re.compile(r"(?:%[0-9A-Fa-f]{2}){8,}"),
    "escaped_hex": re.compile(r"(?:\\x[0-9A-Fa-f]{2}){8,}"),
}

_SENSITIVE_KEYWORDS = (
    b"password",
    b"passwd",
    b"secret",
    b"token",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer",
    b"cookie",
    b"session",
    b"private key",
    b"ssh-rsa",
    b"refresh_token",
    b"client_secret",
)

_EGRESS_HINTS = (
    "curl",
    "wget",
    "http://",
    "https://",
    "upload",
    "webhook",
    "beacon",
    "dns",
    "exfil",
    "pastebin",
    "socket",
    "send",
)


class EncodedExfilDetectorConfig(BaseModel):
    """Configuration for encoded exfiltration detection.

    Attributes:
        enabled: Per-detector enable flags.
        min_encoded_length: Minimum encoded segment length to inspect.
        min_decoded_length: Minimum decoded byte length to treat as meaningful.
        min_entropy: Minimum Shannon entropy for suspicious payload scoring.
        min_printable_ratio: Minimum decoded printable ASCII ratio for scoring.
        min_suspicion_score: Score threshold to flag a candidate as suspicious.
        max_scan_string_length: Skip scanning strings above this size for latency safety.
        max_findings_per_value: Per-string finding limit.
        redact: Whether to redact detected segments.
        redaction_text: Replacement text when redaction is enabled.
        block_on_detection: Whether to block request on findings.
        min_findings_to_block: Number of findings required before blocking.
        include_detection_details: Include detailed findings in metadata.
    """

    enabled: Dict[str, bool] = Field(default_factory=lambda: {name: True for name in _PATTERNS.keys()})

    min_encoded_length: int = Field(default=24, ge=8, le=8192)
    min_decoded_length: int = Field(default=12, ge=4, le=32768)
    min_entropy: float = Field(default=3.3, ge=0.0, le=8.0)
    min_printable_ratio: float = Field(default=0.70, ge=0.0, le=1.0)
    min_suspicion_score: int = Field(default=3, ge=1, le=10)
    max_scan_string_length: int = Field(default=200_000, ge=1_000, le=5_000_000)
    max_findings_per_value: int = Field(default=50, ge=1, le=500)

    redact: bool = Field(default=False)
    redaction_text: str = Field(default="***ENCODED_REDACTED***")
    block_on_detection: bool = Field(default=True)
    min_findings_to_block: int = Field(default=1, ge=1, le=1000)
    include_detection_details: bool = Field(default=True)


def _shannon_entropy(data: bytes) -> float:
    """Calculate Shannon entropy for a byte sequence."""
    if not data:
        return 0.0
    total = len(data)
    counts: Dict[int, int] = {}
    for value in data:
        counts[value] = counts.get(value, 0) + 1
    entropy = 0.0
    for count in counts.values():
        probability = count / total
        entropy -= probability * math.log2(probability)
    return entropy


def _printable_ratio(data: bytes) -> float:
    """Return ratio of printable ASCII characters in byte payload."""
    if not data:
        return 0.0
    printable = sum(1 for b in data if 32 <= b <= 126 or b in (9, 10, 13))
    return printable / len(data)


def _normalize_padding(candidate: str) -> str:
    """Normalize base64 padding to 4-byte alignment."""
    remainder = len(candidate) % 4
    if remainder == 0:
        return candidate
    return candidate + ("=" * (4 - remainder))


def _decode_candidate(encoding: str, candidate: str) -> bytes | None:
    """Decode a candidate encoded string, returning bytes if successful."""
    try:
        if encoding == "base64":
            return base64.b64decode(_normalize_padding(candidate), validate=True)

        if encoding == "base64url":
            # validate URL-safe charset before decode for better precision
            if not re.fullmatch(r"[A-Za-z0-9_\-=]+", candidate):
                return None
            return base64.urlsafe_b64decode(_normalize_padding(candidate))

        if encoding == "hex":
            if len(candidate) % 2 != 0:
                return None
            return bytes.fromhex(candidate)

        if encoding == "percent_encoding":
            return unquote_to_bytes(candidate)

        if encoding == "escaped_hex":
            chunks = re.findall(r"\\x([0-9A-Fa-f]{2})", candidate)
            if not chunks:
                return None
            return bytes(int(chunk, 16) for chunk in chunks)

    except (binascii.Error, ValueError):
        return None

    return None


def _contains_sensitive_keywords(decoded: bytes) -> bool:
    """Return True when decoded payload contains likely sensitive markers."""
    lowered = decoded.lower()
    return any(keyword in lowered for keyword in _SENSITIVE_KEYWORDS)


def _has_egress_context(text: str, start: int, end: int, radius: int = 80) -> bool:
    """Inspect nearby text around candidate for egress/exfiltration hints."""
    lower_text = text.lower()
    left = max(0, start - radius)
    right = min(len(lower_text), end + radius)
    window = lower_text[left:right]
    return any(hint in window for hint in _EGRESS_HINTS)


def _apply_redactions(text: str, findings: Iterable[dict[str, Any]], replacement: str) -> str:
    """Apply non-overlapping redactions from end to start to preserve offsets."""
    redacted = text
    spans = sorted({(f["start"], f["end"]) for f in findings}, key=lambda item: (item[0], item[1]))
    for start, end in reversed(spans):
        redacted = f"{redacted[:start]}{replacement}{redacted[end:]}"
    return redacted


def _evaluate_candidate(text: str, path: str, encoding: str, candidate: str, start: int, end: int, cfg: EncodedExfilDetectorConfig) -> dict[str, Any] | None:
    """Score and classify a candidate encoded segment."""
    if len(candidate) < cfg.min_encoded_length:
        return None

    decoded = _decode_candidate(encoding, candidate)
    if decoded is None or len(decoded) < cfg.min_decoded_length:
        return None

    entropy = _shannon_entropy(decoded)
    printable = _printable_ratio(decoded)
    sensitive_hit = _contains_sensitive_keywords(decoded)
    egress_hit = _has_egress_context(text, start, end)

    score = 1  # baseline for successfully decoded segment
    reasons: list[str] = ["decodable"]

    if entropy >= cfg.min_entropy:
        score += 1
        reasons.append("high_entropy")

    if printable >= cfg.min_printable_ratio:
        score += 1
        reasons.append("printable_payload")

    if sensitive_hit:
        score += 2
        reasons.append("sensitive_keywords")

    if egress_hit:
        score += 1
        reasons.append("egress_context")

    if len(candidate) >= cfg.min_encoded_length * 2:
        score += 1
        reasons.append("long_segment")

    if score < cfg.min_suspicion_score:
        return None

    preview = candidate[:24] + "…" if len(candidate) > 24 else candidate
    return {
        "type": "encoded_exfiltration",
        "encoding": encoding,
        "path": path or "$",
        "start": start,
        "end": end,
        "score": score,
        "entropy": round(entropy, 3),
        "decoded_len": len(decoded),
        "printable_ratio": round(printable, 3),
        "reason": reasons,
        "match": preview,
    }


def _scan_text(text: str, cfg: EncodedExfilDetectorConfig, path: str = "") -> tuple[str, list[dict[str, Any]]]:
    """Scan a single text value and optionally redact suspicious segments."""
    if not text or len(text) > cfg.max_scan_string_length:
        return text, []

    findings_by_span: Dict[Tuple[int, int], dict[str, Any]] = {}

    for encoding, pattern in _PATTERNS.items():
        if not cfg.enabled.get(encoding, True):
            continue

        for match in pattern.finditer(text):
            finding = _evaluate_candidate(text=text, path=path, encoding=encoding, candidate=match.group(0), start=match.start(), end=match.end(), cfg=cfg)
            if finding is None:
                continue

            key = (finding["start"], finding["end"])
            existing = findings_by_span.get(key)
            if existing is None or finding["score"] > existing["score"]:
                findings_by_span[key] = finding

            if len(findings_by_span) >= cfg.max_findings_per_value:
                break

    findings = sorted(findings_by_span.values(), key=lambda item: (item["start"], item["end"]))
    if not findings or not cfg.redact:
        return text, findings

    return _apply_redactions(text, findings, cfg.redaction_text), findings


def _scan_container(container: Any, cfg: EncodedExfilDetectorConfig, path: str = "", use_rust: bool = True) -> tuple[int, Any, list[dict[str, Any]]]:
    """Recursively scan container for encoded exfiltration patterns."""
    if use_rust and _RUST_AVAILABLE and encoded_exfil_detection is not None:
        try:
            count, redacted, findings = encoded_exfil_detection.py_scan_container(container, cfg)
            normalized_findings = []
            for finding in findings:
                if isinstance(finding, dict):
                    if "path" not in finding:
                        finding["path"] = path or "$"
                    normalized_findings.append(finding)
            return int(count), redacted, normalized_findings
        except Exception as e:  # pragma: no cover - fallback path safety
            logger.warning(f"Rust encoded exfil scan failed, falling back to Python: {e}")

    if isinstance(container, str):
        redacted, findings = _scan_text(container, cfg, path=path)
        return len(findings), redacted, findings

    if isinstance(container, dict):
        total = 0
        findings: list[dict[str, Any]] = []
        updated: dict[str, Any] = {}
        for key, value in container.items():
            child_path = f"{path}.{key}" if path else str(key)
            count, new_value, child_findings = _scan_container(value, cfg, path=child_path, use_rust=False)
            total += count
            findings.extend(child_findings)
            updated[key] = new_value
        return total, updated, findings

    if isinstance(container, list):
        total = 0
        findings = []
        updated_list: list[Any] = []
        for index, value in enumerate(container):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            count, new_value, child_findings = _scan_container(value, cfg, path=child_path, use_rust=False)
            total += count
            findings.extend(child_findings)
            updated_list.append(new_value)
        return total, updated_list, findings

    return 0, container, []


class EncodedExfilDetectorPlugin(Plugin):
    """Detect and mitigate suspicious encoded exfiltration payloads."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize encoded exfiltration detector plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = EncodedExfilDetectorConfig(**(config.config or {}))
        self.implementation = "Rust" if _RUST_AVAILABLE else "Python"

    def _findings_for_metadata(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return sanitized findings details for metadata emission."""
        if self._cfg.include_detection_details:
            return findings[:10]
        return [{"encoding": f.get("encoding"), "path": f.get("path"), "score": f.get("score")} for f in findings[:10]]

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Scan prompt arguments for encoded exfiltration attempts."""
        count, new_args, findings = _scan_container(payload.args or {}, self._cfg, path="args")

        if count >= self._cfg.min_findings_to_block and self._cfg.block_on_detection:
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Encoded exfiltration pattern detected",
                    description="Suspicious encoded payload detected in prompt arguments",
                    code="ENCODED_EXFIL_DETECTED",
                    details={
                        "count": count,
                        "examples": self._findings_for_metadata(findings),
                        "implementation": self.implementation,
                        "request_id": context.global_context.request_id if context and context.global_context else None,
                    },
                ),
            )

        metadata = {"encoded_exfil_count": count, "encoded_exfil_findings": self._findings_for_metadata(findings), "implementation": self.implementation} if count else {}

        if self._cfg.redact and new_args != (payload.args or {}):
            modified_payload = PromptPrehookPayload(prompt_id=payload.prompt_id, args=new_args)
            metadata = {**metadata, "encoded_exfil_redacted": True}
            return PromptPrehookResult(modified_payload=modified_payload, metadata=metadata)

        return PromptPrehookResult(metadata=metadata)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Scan tool outputs for suspicious encoded exfiltration payloads."""
        count, new_result, findings = _scan_container(payload.result, self._cfg, path="result")

        if count >= self._cfg.min_findings_to_block and self._cfg.block_on_detection:
            return ToolPostInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Encoded exfiltration pattern detected",
                    description=f"Suspicious encoded payload detected in tool output '{payload.name}'",
                    code="ENCODED_EXFIL_DETECTED",
                    details={
                        "tool": payload.name,
                        "count": count,
                        "examples": self._findings_for_metadata(findings),
                        "implementation": self.implementation,
                        "request_id": context.global_context.request_id if context and context.global_context else None,
                    },
                ),
            )

        metadata = {"encoded_exfil_count": count, "encoded_exfil_findings": self._findings_for_metadata(findings), "implementation": self.implementation} if count else {}

        if self._cfg.redact and new_result != payload.result:
            modified_payload = ToolPostInvokePayload(name=payload.name, result=new_result)
            metadata = {**metadata, "encoded_exfil_redacted": True}
            return ToolPostInvokeResult(modified_payload=modified_payload, metadata=metadata)

        return ToolPostInvokeResult(metadata=metadata)


__all__ = [
    "EncodedExfilDetectorConfig",
    "EncodedExfilDetectorPlugin",
    "_scan_container",
    "_scan_text",
]
