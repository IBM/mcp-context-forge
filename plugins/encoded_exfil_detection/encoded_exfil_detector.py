# -*- coding: utf-8 -*-
"""Location: ./plugins/encoded_exfil_detection/encoded_exfil_detector.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Encoded Exfiltration Detector Plugin.

Detects suspicious encoded payloads (base64, base64url, hex, percent-encoding,
hex escapes) in prompt args and tool outputs, then blocks or redacts.

Hooks: prompt_pre_fetch, tool_post_invoke, resource_post_fetch
"""

# Future
from __future__ import annotations

# Standard
import base64
import binascii
import json
import logging
import math
import re
from typing import Any, Dict, Iterable, Tuple
from urllib.parse import unquote_to_bytes

# Third-Party
from pydantic import BaseModel, Field, field_validator

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

logger = logging.getLogger(__name__)

# Try to import Rust-accelerated implementation
try:
    # Third-Party
    from encoded_exfil_detection_rust.encoded_exfil_detection_rust import ExfilDetectorEngine as _RustEngine  # pragma: no cover
    from encoded_exfil_detection_rust.encoded_exfil_detection_rust import py_scan_container as encoded_exfil_detection  # noqa: F401 — backward compat  # pragma: no cover

    _RUST_AVAILABLE = True  # pragma: no cover
    logger.info("🦀 Rust encoded exfil detector available - using high-performance implementation")  # pragma: no cover
except ImportError as e:
    _RUST_AVAILABLE = False
    _RustEngine = None  # type: ignore
    encoded_exfil_detection = None  # type: ignore
    logger.debug(f"Rust encoded exfil detector not available (will use Python): {e}")
except Exception as e:  # pragma: no cover - defensive import guard
    _RUST_AVAILABLE = False
    _RustEngine = None  # type: ignore
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
        allowlist_patterns: Regex patterns to skip known-good encoded strings.
        extra_sensitive_keywords: Additional sensitive keywords merged with built-in defaults.
        extra_egress_hints: Additional egress hints merged with built-in defaults.
        max_decode_depth: Maximum nested encoding layers to peel during detection.
        max_recursion_depth: Maximum container nesting depth for recursive scanning.
        log_detections: Whether to log detection events.
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

    allowlist_patterns: list[str] = Field(default_factory=list)
    extra_sensitive_keywords: list[str] = Field(default_factory=list)
    extra_egress_hints: list[str] = Field(default_factory=list)
    max_decode_depth: int = Field(default=2, ge=1, le=5)
    max_recursion_depth: int = Field(default=32, ge=1, le=1000)
    log_detections: bool = Field(default=True)
    per_encoding_score: Dict[str, int] = Field(default_factory=dict)
    parse_json_strings: bool = Field(default=True)

    # Pre-compiled allowlist patterns — populated by the validator below.
    _allowlist_compiled: list[re.Pattern[str]] = []
    # Pre-encoded extra keywords — populated by model_post_init.
    _extra_keywords_bytes: tuple[bytes, ...] = ()
    # Pre-lowercased extra egress hints — populated by model_post_init.
    _extra_hints_lower: tuple[str, ...] = ()

    model_config = {"ignored_types": (re.Pattern,)}

    @field_validator("allowlist_patterns")
    @classmethod
    def _validate_allowlist_patterns(cls, v: list[str]) -> list[str]:
        """Validate that allowlist patterns are valid regexes."""
        for idx, pattern in enumerate(v):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid allowlist regex pattern at index {idx} ('{pattern}'): {exc}") from exc
        return v

    def model_post_init(self, _context: Any) -> None:  # pylint: disable=arguments-differ
        """Pre-compile and cache derived values after validation."""
        setattr(self, "_allowlist_compiled", [re.compile(p) for p in self.allowlist_patterns])
        setattr(self, "_extra_keywords_bytes", tuple(kw.lower().encode() for kw in self.extra_sensitive_keywords))
        setattr(self, "_extra_hints_lower", tuple(h.lower() for h in self.extra_egress_hints))


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


def _contains_sensitive_keywords(decoded: bytes, extra_keywords: tuple[bytes, ...] = ()) -> bool:
    """Return True when decoded payload contains likely sensitive markers."""
    lowered = decoded.lower()
    keywords = _SENSITIVE_KEYWORDS + extra_keywords
    return any(keyword in lowered for keyword in keywords)


def _has_egress_context(text: str, start: int, end: int, radius: int = 80, extra_hints: tuple[str, ...] = ()) -> bool:
    """Inspect nearby text around candidate for egress/exfiltration hints."""
    lower_text = text.lower()
    left = max(0, start - radius)
    right = min(len(lower_text), end + radius)
    window = lower_text[left:right]
    hints = _EGRESS_HINTS + extra_hints
    return any(hint in window for hint in hints)


def _apply_redactions(text: str, findings: Iterable[dict[str, Any]], replacement: str) -> str:
    """Apply non-overlapping redactions from end to start to preserve offsets."""
    redacted = text
    spans = sorted({(f["start"], f["end"]) for f in findings}, key=lambda item: (item[0], item[1]))
    for start, end in reversed(spans):
        redacted = f"{redacted[:start]}{replacement}{redacted[end:]}"
    return redacted


def _evaluate_candidate(
    text: str,
    path: str,
    encoding: str,
    candidate: str,
    start: int,
    end: int,
    cfg: EncodedExfilDetectorConfig,
    extra_keywords: tuple[bytes, ...] = (),
    extra_hints: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    """Score and classify a candidate encoded segment."""
    if len(candidate) < cfg.min_encoded_length:
        return None

    decoded = _decode_candidate(encoding, candidate)
    if decoded is None or len(decoded) < cfg.min_decoded_length:
        return None

    entropy = _shannon_entropy(decoded)
    printable = _printable_ratio(decoded)
    sensitive_hit = _contains_sensitive_keywords(decoded, extra_keywords=extra_keywords)
    egress_hit = _has_egress_context(text, start, end, extra_hints=extra_hints)

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

    threshold = cfg.per_encoding_score.get(encoding, cfg.min_suspicion_score)
    if score < threshold:
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


def _scan_text(
    text: str,
    cfg: EncodedExfilDetectorConfig,
    path: str = "",
    decode_depth: int = 0,
) -> tuple[str, list[dict[str, Any]]]:
    """Scan a single text value and optionally redact suspicious segments."""
    if not text or len(text) > cfg.max_scan_string_length:
        return text, []

    findings_by_span: Dict[Tuple[int, int], dict[str, Any]] = {}

    for encoding, pattern in _PATTERNS.items():
        if not cfg.enabled.get(encoding, True):
            continue

        for match in pattern.finditer(text):
            candidate = match.group(0)

            # Check allowlist — skip candidates matching any allowlist pattern
            if cfg._allowlist_compiled:
                if any(ap.search(candidate) for ap in cfg._allowlist_compiled):
                    continue

            finding = _evaluate_candidate(
                text=text,
                path=path,
                encoding=encoding,
                candidate=candidate,
                start=match.start(),
                end=match.end(),
                cfg=cfg,
                extra_keywords=cfg._extra_keywords_bytes,
                extra_hints=cfg._extra_hints_lower,
            )

            # Try nested decoding — peel encoding layers to find deeper secrets
            if decode_depth < cfg.max_decode_depth - 1:
                decoded = _decode_candidate(encoding, candidate)
                if decoded is not None and len(decoded) >= cfg.min_decoded_length:
                    decoded_text = decoded.decode("utf-8", errors="replace")
                    _, nested_findings = _scan_text(
                        decoded_text,
                        cfg,
                        path=path,
                        decode_depth=decode_depth + 1,
                    )
                    for nf in nested_findings:
                        # Use nested finding if it has a higher score than the outer one
                        if finding is None or nf["score"] > finding["score"]:
                            finding = {**nf, "start": match.start(), "end": match.end()}

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


def _scan_container(
    container: Any,
    cfg: EncodedExfilDetectorConfig,
    path: str = "",
    use_rust: bool = True,
    _depth: int = 0,
) -> tuple[int, Any, list[dict[str, Any]]]:
    """Recursively scan container for encoded exfiltration patterns."""
    if _depth > cfg.max_recursion_depth:
        return 0, container, []

    if use_rust and _RUST_AVAILABLE and encoded_exfil_detection is not None:  # pragma: no cover - Rust path
        try:
            count, redacted, findings = encoded_exfil_detection(container, cfg)
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
        # Scan as raw text first — always returns the original type (string)
        redacted, findings = _scan_text(container, cfg, path=path)
        # Try parsing string as JSON for additional findings (metadata only, no type mutation)
        # Heuristic: only attempt JSON parse if string starts with { or [ and is within size limit
        if cfg.parse_json_strings and _depth < cfg.max_recursion_depth and len(container) <= cfg.max_scan_string_length and len(container) >= 2 and container[0] in ("{", "["):
            try:
                parsed = json.loads(container)
                if isinstance(parsed, (dict, list)):
                    json_path = f"{path}(json)" if path else "(json)"
                    _, _, json_findings = _scan_container(parsed, cfg, path=json_path, use_rust=False, _depth=_depth + 1)
                    # Deduplicate: only add JSON findings whose encoded match isn't already found in raw scan
                    raw_matches = {f.get("match") for f in findings}
                    for jf in json_findings:
                        if jf.get("match") not in raw_matches:
                            findings.append(jf)
            except (json.JSONDecodeError, ValueError):
                pass
        return len(findings), redacted, findings

    if isinstance(container, dict):
        total = 0
        findings: list[dict[str, Any]] = []
        updated: dict[str, Any] = {}
        for key, value in container.items():
            child_path = f"{path}.{key}" if path else str(key)
            # Scan keys that are long enough to contain encoded content
            if isinstance(key, str) and len(key) >= cfg.min_encoded_length:
                key_path = f"{child_path}(key)"
                _, key_findings = _scan_text(key, cfg, path=key_path)
                findings.extend(key_findings)
                total += len(key_findings)
            count, new_value, child_findings = _scan_container(value, cfg, path=child_path, use_rust=False, _depth=_depth + 1)
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
            count, new_value, child_findings = _scan_container(value, cfg, path=child_path, use_rust=False, _depth=_depth + 1)
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

        # Try to create persistent Rust engine (parses config once, reuses across scans)
        self._rust_engine = None
        if _RUST_AVAILABLE and _RustEngine is not None:  # pragma: no cover - Rust path
            try:
                self._rust_engine = _RustEngine(self._cfg)
            except Exception as e:  # pragma: no cover - defensive init guard
                logger.warning(f"Failed to initialize Rust exfil engine, using Python fallback: {e}")
        self.implementation = "Rust" if self._rust_engine is not None else "Python"

    def _findings_for_metadata(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return sanitized findings details for metadata emission."""
        if self._cfg.include_detection_details:
            return findings[:10]
        return [{"encoding": f.get("encoding"), "path": f.get("path"), "score": f.get("score")} for f in findings[:10]]

    def _scan(self, container: Any, path: str = "") -> tuple[int, Any, list[dict[str, Any]]]:
        """Run the scanner with plugin-level configuration."""
        if self._rust_engine is not None:  # pragma: no cover - Rust path
            try:
                count, redacted, findings = self._rust_engine.scan(container)
                normalized = []
                for f in findings:
                    if isinstance(f, dict):
                        if "path" not in f:
                            f["path"] = path or "$"
                        normalized.append(f)
                return int(count), redacted, normalized
            except Exception as e:  # pragma: no cover - fallback path safety
                logger.warning(f"Rust engine scan failed, falling back to Python: {e}")
        return _scan_container(container, self._cfg, path=path, use_rust=False)

    def _log_detection(self, hook: str, count: int, findings: list[dict[str, Any]], context: PluginContext) -> None:
        """Log detection events without exposing sensitive content."""
        if not self._cfg.log_detections or count == 0:
            return
        encoding_types = sorted({f.get("encoding", "unknown") for f in findings})
        request_id = context.global_context.request_id if context and context.global_context else "unknown"
        logger.warning("Encoded exfiltration detected [hook=%s, count=%d, encodings=%s, request_id=%s]", hook, count, encoding_types, request_id)

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Scan prompt arguments for encoded exfiltration attempts."""
        count, new_args, findings = self._scan(payload.args or {}, path="args")
        self._log_detection("prompt_pre_fetch", count, findings, context)

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
        count, new_result, findings = self._scan(payload.result, path="result")
        self._log_detection("tool_post_invoke", count, findings, context)

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

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Scan fetched resource content for suspicious encoded exfiltration payloads."""
        count, new_content, findings = self._scan(payload.content, path="content")
        self._log_detection("resource_post_fetch", count, findings, context)

        if count >= self._cfg.min_findings_to_block and self._cfg.block_on_detection:
            return ResourcePostFetchResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Encoded exfiltration pattern detected",
                    description="Suspicious encoded payload detected in resource content",
                    code="ENCODED_EXFIL_DETECTED",
                    details={
                        "uri": payload.uri,
                        "count": count,
                        "examples": self._findings_for_metadata(findings),
                        "implementation": self.implementation,
                        "request_id": context.global_context.request_id if context and context.global_context else None,
                    },
                ),
            )

        metadata = {"encoded_exfil_count": count, "encoded_exfil_findings": self._findings_for_metadata(findings), "implementation": self.implementation} if count else {}

        if self._cfg.redact and new_content != payload.content:
            modified_payload = ResourcePostFetchPayload(uri=payload.uri, content=new_content)
            metadata = {**metadata, "encoded_exfil_redacted": True}
            return ResourcePostFetchResult(modified_payload=modified_payload, metadata=metadata)

        return ResourcePostFetchResult(metadata=metadata)


__all__ = [
    "EncodedExfilDetectorConfig",
    "EncodedExfilDetectorPlugin",
    "_scan_container",
    "_scan_text",
]
