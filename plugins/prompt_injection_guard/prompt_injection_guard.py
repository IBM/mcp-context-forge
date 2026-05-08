# -*- coding: utf-8 -*-
"""Location: ./plugins/prompt_injection_guard/prompt_injection_guard.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Prompt Injection Guard Plugin.

Screens prompts and tool arguments (and optionally tool outputs) for prompt injection
and jailbreak attempts using a two-tier detection approach:

  Tier 1 (always active): precompiled regex patterns covering canonical injection
    and jailbreak signatures — deterministic, sub-millisecond overhead.
  Tier 2 (optional):  LLM Guard (Protect AI, MIT) scored detection via a locally
    loaded DeBERTa classifier. Enabled only when ``use_llm_guard=True`` and the
    ``llm-guard`` package is installed.

Hooks: prompt_pre_fetch, tool_pre_invoke, tool_post_invoke (opt-in)

OWASP LLM Top 10 coverage: LLM01 (Prompt Injection), LLM07 (System Prompt Leakage)
"""

# Future
from __future__ import annotations

# Standard
import logging
import re
from typing import Any, Dict, Iterable, List, Literal, Optional, Pattern, Tuple

# Third-Party
from pydantic import BaseModel, ConfigDict, Field

# First-Party
from cpex.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier-1: precompiled regex pattern banks
# ---------------------------------------------------------------------------

# Prompt injection — attempts to override or ignore prior instructions
_INJECTION_PATTERNS: List[Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context|rules?|guidelines?)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context|rules?|guidelines?)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context|rules?|guidelines?)", re.IGNORECASE),
    re.compile(r"you\s+(are\s+now|must\s+now|will\s+now|should\s+now)\s+(act|behave|pretend|respond)", re.IGNORECASE),
    re.compile(r"new\s+(instructions?|prompt|task|role|persona)\s*:", re.IGNORECASE),
    re.compile(r"override\s+(the\s+)?(system|safety|content|moderation|previous)\s*(prompt|instructions?|rules?|filter|restriction)?", re.IGNORECASE),
    re.compile(r"bypass\s+(the\s+)?(safety|content|filter|restriction|moderation|guardrail)", re.IGNORECASE),
    re.compile(r"</?(system|user|assistant|instruction|prompt|context|human)\s*>", re.IGNORECASE),
    re.compile(r"\[\s*(system|instructions?|prompt|context|human)\s*\]", re.IGNORECASE),
    re.compile(r"print\s+(the\s+)?(above|previous|initial|original|your\s+system)\s*(prompt|instructions?|context|message)?", re.IGNORECASE),
    re.compile(r"what\s+(are|were|is)\s+(your\s+)?(system\s+)?instructions?", re.IGNORECASE),
    re.compile(r"repeat\s+(the\s+)?(above|previous|initial|system)\s*(prompt|instructions?|context|message)?", re.IGNORECASE),
    re.compile(r"translate\s+(the\s+)?(above|previous|initial|system)\s*(prompt|instructions?|context|message)?", re.IGNORECASE),
    re.compile(r"(from\s+now\s+on|henceforth|starting\s+now)\s*[,:]?\s*(you\s+are|act\s+as|pretend|respond)", re.IGNORECASE),
]

# Jailbreak — attempts to escape safety constraints or adopt an unconstrained persona
_JAILBREAK_PATTERNS: List[Pattern[str]] = [
    re.compile(r"\bDAN\b", re.IGNORECASE),  # "Do Anything Now" jailbreak
    re.compile(r"do\s+anything\s+now", re.IGNORECASE),
    re.compile(r"jailbreak(ed|ing|er)?", re.IGNORECASE),
    re.compile(r"(act|pretend|roleplay|play)\s+as\s+(an?\s+)?(evil|unfiltered|uncensored|unrestricted|unethical|rogue|malicious|dangerous)\s*(AI|assistant|model|chatbot|bot)?", re.IGNORECASE),
    re.compile(r"without\s+(any\s+)?(safety|ethical|moral|content)\s*(restrictions?|filters?|constraints?|guidelines?|rules?)", re.IGNORECASE),
    re.compile(r"(disable|remove|turn\s+off|deactivate)\s+(safety|content|ethical|moral)\s*(filter|mode|restriction|check|guardrail)", re.IGNORECASE),
    re.compile(r"(evil\s+mode|developer\s+mode|god\s+mode|unrestricted\s+mode|freedom\s+mode)", re.IGNORECASE),
    re.compile(r"you\s+have\s+no\s+(restrictions?|rules?|limits?|guidelines?|constraints?)", re.IGNORECASE),
    re.compile(r"(in\s+this\s+)?hypothetical\s+(scenario|world|universe|story|situation)\s*.{0,30}(illegal|harmful|dangerous|bomb|weapon|hack|exploit|kill)", re.IGNORECASE),
    re.compile(r"grandma\s+used\s+to\s+(tell|read|explain)", re.IGNORECASE),  # "grandma exploit"
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+(not\s+an?\s+AI|a\s+human|unrestricted|evil|uncensored)", re.IGNORECASE),
    re.compile(r"(as\s+a\s+|you\s+are\s+a?\s*)(language\s+model|AI|chatbot|assistant)\s+without\s+(any\s+)?(restrictions?|filters?|ethical|safety)", re.IGNORECASE),
    re.compile(r"token\s+smuggl", re.IGNORECASE),
    re.compile(r"prompt\s+inject", re.IGNORECASE),
    re.compile(r"always\s+respond\s+with\s+.{0,20}(no\s+matter\s+what|regardless|unconditionally)", re.IGNORECASE),
]

# System prompt leak — attempts to extract the confidential system prompt
_SYSTEM_PROMPT_LEAK_PATTERNS: List[Pattern[str]] = [
    re.compile(r"(reveal|show|display|output|print|tell\s+me|give\s+me|share)\s+(your\s+)?(system|initial|original|full|complete|entire)\s*(prompt|instructions?|context|configuration|setup|rules?)", re.IGNORECASE),
    re.compile(r"what\s+(is|are|was|were)\s+(your\s+)?(system\s+prompt|initial\s+instructions?|original\s+instructions?|prompt\s+template)", re.IGNORECASE),
    re.compile(r"(copy|dump|exfiltrate|leak|expose|extract)\s+(the\s+)?(system|initial|hidden|secret|full|complete)\s*(prompt|instructions?|context|message)", re.IGNORECASE),
    re.compile(r"repeat\s+(everything\s+)?(above|before|prior|your\s+instructions?|your\s+context)\s+(verbatim|word\s+for\s+word|exactly|literally)?", re.IGNORECASE),
    re.compile(r"output\s+(everything\s+)?before\s+(this|the\s+user|my)\s+(message|question|prompt|input)", re.IGNORECASE),
    re.compile(r"(you\s+are|your\s+name\s+is|your\s+role\s+is)\s+.{0,50}(confirm|what\s+is\s+your\s+name|tell\s+me\s+your\s+role)", re.IGNORECASE),
    re.compile(r"summarize\s+(your\s+)?(system|initial|full)\s*(prompt|instructions?|context)", re.IGNORECASE),
    re.compile(r"translate\s+(your\s+)?(system|initial|full)\s*(prompt|instructions?|context)\s+(into|to)", re.IGNORECASE),
    re.compile(r"<\|?\s*(system|instruction|context|human)\s*\|?>", re.IGNORECASE),  # special token injection
]

# Map category name -> (patterns, weight)
_CATEGORY_PATTERNS: Dict[str, Tuple[List[Pattern[str]], float]] = {
    "injection": (_INJECTION_PATTERNS, 1.0),
    "jailbreak": (_JAILBREAK_PATTERNS, 1.0),
    "system_prompt_leak": (_SYSTEM_PROMPT_LEAK_PATTERNS, 1.0),
}

# ---------------------------------------------------------------------------
# Tier-2: optional LLM Guard integration (lazy-loaded)
# ---------------------------------------------------------------------------
_llm_guard_loaded: bool = False
_llm_guard_scanner: Any = None


def _try_load_llm_guard() -> bool:
    """Attempt to lazy-load the LLM Guard PromptInjection scanner.

    Returns:
        True if the scanner was loaded successfully, False otherwise.
    """
    global _llm_guard_loaded, _llm_guard_scanner  # noqa: PLW0603
    if _llm_guard_loaded:
        return _llm_guard_scanner is not None
    _llm_guard_loaded = True
    try:
        from llm_guard.input_scanners import PromptInjection  # type: ignore[import]
        from llm_guard.input_scanners.prompt_injection import MatchType  # type: ignore[import]

        _llm_guard_scanner = PromptInjection(threshold=0.5, match_type=MatchType.FULL)
        logger.info("LLM Guard PromptInjection scanner loaded successfully")
        return True
    except ImportError:
        logger.debug("llm-guard package not installed; Tier-2 detection disabled (set use_llm_guard=false to suppress this message)")
        return False
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to initialise LLM Guard scanner: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Config schema
# ---------------------------------------------------------------------------


class CategoryConfig(BaseModel):
    """Per-category detection configuration.

    Attributes:
        threshold: Score threshold above which a detection triggers the action (0.0–1.0).
        action: Action to take when the threshold is exceeded.
    """

    threshold: float = Field(default=0.75, ge=0.0, le=1.0, description="Score threshold for triggering an action")
    action: Literal["block", "redact", "flag-only"] = Field(default="block", description="Action to take when threshold exceeded")


class PromptInjectionGuardConfig(BaseModel):
    """Configuration for the Prompt Injection Guard plugin.

    Attributes:
        mode: Global default response mode when a category config does not override it.
        check_tool_output: Whether to scan tool outputs via the ``tool_post_invoke`` hook.
        use_llm_guard: Enable optional Tier-2 LLM Guard classifier scoring.
        redaction_placeholder: Replacement text used in ``redact`` mode.
        categories: Per-category threshold and action overrides.
    """

    mode: Literal["block", "redact", "flag-only"] = Field(default="block", description="Global default response mode")
    check_tool_output: bool = Field(default=False, description="Scan tool outputs via tool_post_invoke hook")
    use_llm_guard: bool = Field(default=False, description="Enable optional LLM Guard Tier-2 scorer (requires llm-guard package)")
    redaction_placeholder: str = Field(default="[INJECTION_REDACTED]", description="Replacement text used in redact mode")
    categories: Dict[str, CategoryConfig] = Field(
        default_factory=lambda: {
            "injection": CategoryConfig(threshold=0.75, action="block"),
            "jailbreak": CategoryConfig(threshold=0.80, action="block"),
            "system_prompt_leak": CategoryConfig(threshold=0.70, action="block"),
        }
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _iter_strings(value: Any) -> Iterable[Tuple[str, str]]:
    """Recursively yield all string leaf values from a nested data structure.

    Args:
        value: Arbitrary value to walk (dict, list, str, or other).

    Yields:
        Tuples of (path, string_value) for each string leaf found.
    """

    def _walk(obj: Any, path: str) -> Iterable[Tuple[str, str]]:
        """Inner recursive walker.

        Args:
            obj: Current object being walked.
            path: Dot-notation path accumulated so far.

        Yields:
            Tuples of (path, string_value).
        """
        if isinstance(obj, str):
            yield path, obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                yield from _walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from _walk(v, f"{path}[{i}]")

    yield from _walk(value, "")


def _scan_regex(text: str) -> List[Tuple[str, str, float]]:
    """Run Tier-1 regex scan on ``text``.

    Args:
        text: The text to scan.

    Returns:
        List of ``(category, matched_pattern, score)`` tuples for every match found.
        Score is always 1.0 for regex matches (binary hit/miss).
    """
    results: List[Tuple[str, str, float]] = []
    for category, (patterns, weight) in _CATEGORY_PATTERNS.items():
        for pat in patterns:
            m = pat.search(text)
            if m:
                results.append((category, pat.pattern, weight))
                break  # One match per category is sufficient
    return results


def _scan_llm_guard(text: str) -> Optional[Tuple[str, float]]:
    """Run Tier-2 LLM Guard scan on ``text``.

    Args:
        text: The text to scan.

    Returns:
        Tuple of (sanitized_text, score) when the scanner flags the input,
        or None when the scanner reports the text as safe.
    """
    if _llm_guard_scanner is None:
        return None
    try:
        sanitized, is_valid, risk_score = _llm_guard_scanner.scan("", text)
        if not is_valid:
            return sanitized, float(risk_score)
    except Exception as exc:
        logger.warning("LLM Guard scan error: %s", exc)
    return None


def _redact_text(text: str, placeholder: str) -> str:
    """Redact all Tier-1 pattern matches in ``text`` with ``placeholder``.

    Args:
        text: Input text to redact.
        placeholder: Replacement text.

    Returns:
        Redacted text with matched segments replaced by placeholder.
    """
    result = text
    for _category, (patterns, _weight) in _CATEGORY_PATTERNS.items():
        for pat in patterns:
            result = pat.sub(placeholder, result)
    return result


def _effective_action(category: str, cfg: PromptInjectionGuardConfig) -> Literal["block", "redact", "flag-only"]:
    """Resolve the effective action for a given category.

    Falls back to the global ``mode`` when the category has no explicit override.

    Args:
        category: Detection category name.
        cfg: Plugin configuration.

    Returns:
        The resolved action string.
    """
    cat_cfg = cfg.categories.get(category)
    if cat_cfg:
        return cat_cfg.action
    return cfg.mode


def _exceeds_threshold(category: str, score: float, cfg: PromptInjectionGuardConfig) -> bool:
    """Check whether ``score`` meets or exceeds the configured threshold for ``category``.

    Args:
        category: Detection category name.
        score: Detection score (0.0–1.0).
        cfg: Plugin configuration.

    Returns:
        True if score >= threshold, False otherwise.
    """
    cat_cfg = cfg.categories.get(category)
    threshold = cat_cfg.threshold if cat_cfg else 0.75
    return score >= threshold


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class PromptInjectionGuardPlugin(Plugin):
    """Screens prompts and tool arguments for prompt injection and jailbreak attempts.

    Uses a two-tier detection approach:
      - Tier 1: Precompiled regex patterns (always active, deterministic timing).
      - Tier 2: Optional LLM Guard PromptInjection scanner (requires ``llm-guard`` package).

    Supported hooks: ``prompt_pre_fetch``, ``tool_pre_invoke``, ``tool_post_invoke``.
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialise the plugin and load optional LLM Guard scanner.

        Args:
            config: Plugin configuration from the ContextForge plugin framework.
        """
        super().__init__(config)
        self._cfg = PromptInjectionGuardConfig(**(config.config or {}))
        if self._cfg.use_llm_guard:
            _try_load_llm_guard()

    # ------------------------------------------------------------------
    # Internal scan orchestration
    # ------------------------------------------------------------------

    def _scan_value(self, text: str) -> List[Tuple[str, str, float]]:
        """Run all enabled detection tiers against ``text``.

        Args:
            text: Text to scan.

        Returns:
            Deduplicated list of ``(category, matched_rule, score)`` tuples.
        """
        findings: List[Tuple[str, str, float]] = _scan_regex(text)

        # Tier 2: LLM Guard (only when enabled and loaded)
        if self._cfg.use_llm_guard and _llm_guard_scanner is not None:
            lg_result = _scan_llm_guard(text)
            if lg_result is not None:
                _sanitized, score = lg_result
                # LLM Guard does not distinguish sub-categories; map to "injection"
                existing_cats = {cat for cat, _, _ in findings}
                if "injection" not in existing_cats:
                    findings.append(("injection", "llm_guard:PromptInjection", score))
                else:
                    # Update score if LLM Guard gave a higher score
                    findings = [(cat, rule, max(s, score) if cat == "injection" else s) for cat, rule, s in findings]

        return findings

    def _build_result(self, findings: List[Tuple[str, str, float]], text: str) -> Optional[Dict[str, Any]]:
        """Determine the action to take based on scan findings.

        Args:
            findings: List of (category, matched_rule, score) from scanning.
            text: The original text that was scanned.

        Returns:
            A dict with keys ``action``, ``violation_details``, ``redacted_text`` when action
            is required, or None when all findings are below threshold or no action needed.
        """
        actionable: List[Tuple[str, str, float]] = [
            (cat, rule, score)
            for cat, rule, score in findings
            if _exceeds_threshold(cat, score, self._cfg)
        ]
        if not actionable:
            return None

        # Highest-priority category drives the top-level action
        # Priority: block > redact > flag-only
        action_priority = {"block": 0, "redact": 1, "flag-only": 2}
        effective_actions = [(_effective_action(cat, self._cfg), cat, rule, score) for cat, rule, score in actionable]
        effective_actions.sort(key=lambda x: action_priority.get(x[0], 99))

        top_action, top_cat, top_rule, top_score = effective_actions[0]

        violation_details: Dict[str, Any] = {
            "score": round(top_score, 4),
            "category": top_cat,
            "matched_rule": top_rule,
            "response_mode": top_action,
            "all_findings": [{"category": c, "matched_rule": r, "score": round(s, 4)} for c, r, s in actionable],
        }

        redacted: Optional[str] = None
        if top_action == "redact":
            redacted = _redact_text(text, self._cfg.redaction_placeholder)

        return {"action": top_action, "violation_details": violation_details, "redacted_text": redacted}

    def _scan_args(self, args: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Scan all string leaves in ``args`` and return the highest-priority actionable result.

        Scans every string leaf so that a ``block`` in a later argument is not
        silently downgraded by a ``redact`` or ``flag-only`` in an earlier one.

        Args:
            args: Tool or prompt arguments to scan.

        Returns:
            Highest-priority actionable result dict, or None when all inputs are clean.
        """
        if not args:
            return None
        action_priority = {"block": 0, "redact": 1, "flag-only": 2}
        best_result: Optional[Dict[str, Any]] = None
        best_priority = 99
        for _path, text in _iter_strings(args):
            if not text.strip():
                continue
            findings = self._scan_value(text)
            result = self._build_result(findings, text)
            if result is not None:
                priority = action_priority.get(result["action"], 99)
                if priority < best_priority:
                    best_priority = priority
                    best_result = result
                    if best_priority == 0:  # block is highest priority — short-circuit
                        break
        return best_result

    def _redact_args(self, obj: Any) -> Any:
        """Recursively walk ``obj`` and redact every flagged string leaf in-place.

        Args:
            obj: Arbitrary nested structure (dict, list, or str).

        Returns:
            A new structure with flagged string leaves replaced by the configured
            redaction placeholder.  Non-string, non-container values are returned
            unchanged.
        """
        if isinstance(obj, str):
            result = self._build_result(self._scan_value(obj), obj)
            if result and result.get("redacted_text"):
                return result["redacted_text"]
            return obj
        if isinstance(obj, dict):
            return {k: self._redact_args(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._redact_args(item) for item in obj]
        return obj

    # ------------------------------------------------------------------
    # Hook implementations
    # ------------------------------------------------------------------

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Screen prompt arguments before the prompt is fetched/rendered.

        Args:
            payload: The prompt pre-fetch payload containing arguments.
            context: Plugin execution context.

        Returns:
            PromptPrehookResult that blocks, redacts, or flags based on configuration.
        """
        scan_result = self._scan_args(payload.args or {})
        if scan_result is None:
            return PromptPrehookResult()

        action = scan_result["action"]
        details = scan_result["violation_details"]

        if action == "block":
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Prompt injection or jailbreak attempt detected",
                    description=f"Category: {details['category']}; Rule: {details['matched_rule']}",
                    code="PROMPT_INJECTION_DETECTED",
                    details=details,
                ),
            )

        if action == "redact":
            new_args = self._redact_args(dict(payload.args or {}))
            modified = PromptPrehookPayload(prompt_id=payload.prompt_id, args=new_args)
            return PromptPrehookResult(
                modified_payload=modified,
                metadata={"prompt_injection_guard": details},
            )

        # flag-only
        return PromptPrehookResult(metadata={"prompt_injection_guard": details})

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Screen tool arguments before the tool is invoked.

        Args:
            payload: The tool pre-invoke payload containing tool name and arguments.
            context: Plugin execution context.

        Returns:
            ToolPreInvokeResult that blocks, redacts, or flags based on configuration.
        """
        scan_result = self._scan_args(payload.args or {})
        if scan_result is None:
            return ToolPreInvokeResult()

        action = scan_result["action"]
        details = scan_result["violation_details"]

        if action == "block":
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Prompt injection or jailbreak attempt detected in tool arguments",
                    description=f"Category: {details['category']}; Rule: {details['matched_rule']}",
                    code="PROMPT_INJECTION_DETECTED",
                    details=details,
                ),
            )

        if action == "redact":
            new_args = self._redact_args(dict(payload.args or {}))
            modified = ToolPreInvokePayload(name=payload.name, args=new_args)
            return ToolPreInvokeResult(
                modified_payload=modified,
                metadata={"prompt_injection_guard": details},
            )

        # flag-only
        return ToolPreInvokeResult(metadata={"prompt_injection_guard": details})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Optionally screen tool outputs after invocation.

        Only active when ``check_tool_output=True`` in the plugin config.

        Args:
            payload: The tool post-invoke payload containing the result.
            context: Plugin execution context.

        Returns:
            ToolPostInvokeResult that blocks, redacts, or flags based on configuration.
        """
        if not self._cfg.check_tool_output:
            return ToolPostInvokeResult()

        result_text = payload.result
        if isinstance(result_text, (dict, list)):
            findings: List[Tuple[str, str, float]] = []
            for _path, text in _iter_strings(result_text):
                if text.strip():
                    findings.extend(self._scan_value(text))
        elif isinstance(result_text, str):
            findings = self._scan_value(result_text)
        else:
            return ToolPostInvokeResult()

        scan_result = self._build_result(findings, str(result_text))
        if scan_result is None:
            return ToolPostInvokeResult()

        action = scan_result["action"]
        details = scan_result["violation_details"]

        if action == "block":
            return ToolPostInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Prompt injection or jailbreak content detected in tool output",
                    description=f"Category: {details['category']}; Rule: {details['matched_rule']}",
                    code="PROMPT_INJECTION_IN_OUTPUT",
                    details=details,
                ),
            )

        # flag-only or redact on output — flag only (cannot safely redact arbitrary output)
        return ToolPostInvokeResult(metadata={"prompt_injection_guard": details})
