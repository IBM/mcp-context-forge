# -*- coding: utf-8 -*-
"""Argument Normalizer Plugin for MCP Gateway.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Normalizes string arguments for prompts and tools by applying:
- Unicode normalization (NFC/NFD/NFKC/NFKD)
- Whitespace cleanup (trim, collapse, newline normalization)
- Casing strategies (none/lower/upper/title)
- Date normalization to ISO 8601 (best-effort regex-based)
- Number normalization to canonical format (remove thousands, '.' decimal)

The plugin is non-blocking and returns modified payloads when changes occur.
"""

# Standard
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class CaseStrategy(str, Enum):
    NONE = "none"
    LOWER = "lower"
    UPPER = "upper"
    TITLE = "title"


class UnicodeForm(str, Enum):
    NFC = "NFC"
    NFD = "NFD"
    NFKC = "NFKC"
    NFKD = "NFKD"


class FieldOverride(BaseModel):
    """Per-field normalization overrides selected by regex matching the field path.

    Example field paths:
    - "name"
    - "user.name"
    - "items[0].title"
    """

    pattern: str
    enable_unicode: Optional[bool] = None
    unicode_form: Optional[UnicodeForm] = None
    remove_control_chars: Optional[bool] = None

    enable_whitespace: Optional[bool] = None
    trim: Optional[bool] = None
    collapse_internal: Optional[bool] = None
    normalize_newlines: Optional[bool] = None
    collapse_blank_lines: Optional[bool] = None

    enable_casing: Optional[bool] = None
    case_strategy: Optional[CaseStrategy] = None

    enable_dates: Optional[bool] = None
    day_first: Optional[bool] = None
    year_first: Optional[bool] = None

    enable_numbers: Optional[bool] = None
    decimal_detection: Optional[str] = None  # auto|comma|dot


class ArgumentNormalizerConfig(BaseModel):
    """Configuration for the Argument Normalizer plugin."""

    # Unicode
    enable_unicode: bool = Field(default=True, description="Enable Unicode normalization")
    unicode_form: UnicodeForm = Field(default=UnicodeForm.NFC, description="Unicode normalization form")
    remove_control_chars: bool = Field(default=True, description="Remove control characters")

    # Whitespace
    enable_whitespace: bool = Field(default=True, description="Enable whitespace normalization")
    trim: bool = Field(default=True, description="Trim leading/trailing whitespace")
    collapse_internal: bool = Field(default=True, description="Collapse internal runs of whitespace to a single space")
    normalize_newlines: bool = Field(default=True, description="Normalize CRLF/CR to LF")
    collapse_blank_lines: bool = Field(default=False, description="Collapse multiple blank lines to a single blank line")

    # Casing
    enable_casing: bool = Field(default=False, description="Enable casing strategy")
    case_strategy: CaseStrategy = Field(default=CaseStrategy.NONE, description="Casing strategy to apply")

    # Dates
    enable_dates: bool = Field(default=True, description="Enable date normalization")
    day_first: bool = Field(default=False, description="Assume day comes first in numeric dates (DD/MM/YYYY)")
    year_first: bool = Field(default=False, description="Assume year comes first when ambiguous (YYYY/MM/DD)")

    # Numbers
    enable_numbers: bool = Field(default=True, description="Enable number normalization")
    decimal_detection: str = Field(default="auto", description="How to detect decimal separator: auto|comma|dot")

    # Overrides
    field_overrides: List[FieldOverride] = Field(default_factory=list, description="Per-field overrides by regex")


@dataclass
class EffectiveCfg:
    enable_unicode: bool
    unicode_form: str
    remove_control_chars: bool
    enable_whitespace: bool
    trim: bool
    collapse_internal: bool
    normalize_newlines: bool
    collapse_blank_lines: bool
    enable_casing: bool
    case_strategy: str
    enable_dates: bool
    day_first: bool
    year_first: bool
    enable_numbers: bool
    decimal_detection: str


def _merge_overrides(base: ArgumentNormalizerConfig, path: str) -> EffectiveCfg:
    """Compute an effective configuration for a given field path."""
    cfg = base
    # Start with base values
    eff = EffectiveCfg(
        enable_unicode=cfg.enable_unicode,
        unicode_form=cfg.unicode_form,
        remove_control_chars=cfg.remove_control_chars,
        enable_whitespace=cfg.enable_whitespace,
        trim=cfg.trim,
        collapse_internal=cfg.collapse_internal,
        normalize_newlines=cfg.normalize_newlines,
        collapse_blank_lines=cfg.collapse_blank_lines,
        enable_casing=cfg.enable_casing,
        case_strategy=cfg.case_strategy,
        enable_dates=cfg.enable_dates,
        day_first=cfg.day_first,
        year_first=cfg.year_first,
        enable_numbers=cfg.enable_numbers,
        decimal_detection=cfg.decimal_detection,
    )

    for override in cfg.field_overrides:
        try:
            if re.search(override.pattern, path or ""):
                if override.enable_unicode is not None:
                    eff.enable_unicode = override.enable_unicode
                if override.unicode_form is not None:
                    eff.unicode_form = override.unicode_form
                if override.remove_control_chars is not None:
                    eff.remove_control_chars = override.remove_control_chars

                if override.enable_whitespace is not None:
                    eff.enable_whitespace = override.enable_whitespace
                if override.trim is not None:
                    eff.trim = override.trim
                if override.collapse_internal is not None:
                    eff.collapse_internal = override.collapse_internal
                if override.normalize_newlines is not None:
                    eff.normalize_newlines = override.normalize_newlines
                if override.collapse_blank_lines is not None:
                    eff.collapse_blank_lines = override.collapse_blank_lines

                if override.enable_casing is not None:
                    eff.enable_casing = override.enable_casing
                if override.case_strategy is not None:
                    eff.case_strategy = override.case_strategy

                if override.enable_dates is not None:
                    eff.enable_dates = override.enable_dates
                if override.day_first is not None:
                    eff.day_first = override.day_first
                if override.year_first is not None:
                    eff.year_first = override.year_first

                if override.enable_numbers is not None:
                    eff.enable_numbers = override.enable_numbers
                if override.decimal_detection is not None:
                    eff.decimal_detection = override.decimal_detection
        except re.error:
            # Invalid override pattern: ignore safely
            logger.warning(f"ArgumentNormalizer: invalid override pattern for path '{path}'")
            continue

    return eff


_CTRL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_MULTI_SPACE_RE = re.compile(r"[\t\x0b\x0c ]+")
_MULTI_NEWLINES_RE = re.compile(r"\n{3,}")
_NUMERIC_TOKEN_RE = re.compile(r"(?<![\w.])-?\d{1,3}([ ,.']\d{3})*(?:[,.]\d+)?(?![\w.])")
_DATE_NUMERIC_RE = re.compile(r"\b(\d{1,4})[\-/.](\d{1,2})[\-/.](\d{1,4})\b")


def _normalize_unicode(text: str, eff: EffectiveCfg) -> str:
    if not eff.enable_unicode:
        return text
    try:
        text = unicodedata.normalize(eff.unicode_form, text)
    except Exception:  # pragma: no cover - defensive
        pass
    if eff.remove_control_chars:
        text = _CTRL_CHARS_RE.sub("", text)
    return text


def _normalize_whitespace(text: str, eff: EffectiveCfg) -> str:
    if not eff.enable_whitespace:
        return text
    if eff.normalize_newlines:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    if eff.trim:
        text = text.strip()
    if eff.collapse_internal:
        # Collapse horizontal whitespace runs into single spaces
        text = _MULTI_SPACE_RE.sub(" ", text)
    if eff.collapse_blank_lines:
        text = _MULTI_NEWLINES_RE.sub("\n\n", text)
    return text


def _normalize_casing(text: str, eff: EffectiveCfg) -> str:
    if not eff.enable_casing or eff.case_strategy == CaseStrategy.NONE:
        return text
    if eff.case_strategy == CaseStrategy.LOWER:
        return text.lower()
    if eff.case_strategy == CaseStrategy.UPPER:
        return text.upper()
    if eff.case_strategy == CaseStrategy.TITLE:
        return text.title()
    return text


def _normalize_dates(text: str, eff: EffectiveCfg) -> str:
    if not eff.enable_dates:
        return text

    def convert(m: re.Match[str]) -> str:
        a, b, c = m.group(1), m.group(2), m.group(3)
        # Identify positions based on year_first/day_first
        try:
            ia, ib, ic = int(a), int(b), int(c)
        except Exception:
            return m.group(0)

        year = month = day = None

        # If one of the parts looks like year (>= 1000), prefer that
        if ia >= 1000 and not eff.day_first:
            year, month, day = ia, ib, ic
        elif ic >= 1000:
            # First two are day/month or month/day; choose plausible month/day,
            # prefer day_first only when ambiguous (both <= 12)
            if ia <= 31 and ib <= 31:
                if ia <= 12 and ib > 12:
                    # M/DD
                    month, day, year = ia, ib, ic
                elif ia > 12 and ib <= 12:
                    # DD/M
                    day, month, year = ia, ib, ic
                elif ia <= 12 and ib <= 12:
                    # ambiguous
                    if eff.day_first:
                        day, month, year = ia, ib, ic
                    else:
                        month, day, year = ia, ib, ic
                else:
                    return m.group(0)
            else:
                return m.group(0)
        elif eff.year_first and ia <= 99 and ic <= 99:
            # Ambiguous YY-M-D; leave untouched
            return m.group(0)
        else:
            # Fallback: treat last as year if plausible, else leave
            if 1 <= ib <= 12 and 1 <= ia <= 31 and 0 <= ic <= 99:
                if eff.day_first:
                    day, month, year = ia, ib, (2000 + ic if ic < 100 else ic)
                else:
                    month, day, year = ia, ib, (2000 + ic if ic < 100 else ic)
            elif ia >= 100 and ib <= 12 and ic <= 31:
                year, month, day = ia, ib, ic
            else:
                return m.group(0)

        if not (year and month and day):
            return m.group(0)
        if not (1 <= month <= 12 and 1 <= day <= 31 and 1000 <= year <= 9999):
            return m.group(0)
        return f"{year:04d}-{month:02d}-{day:02d}"

    try:
        return _DATE_NUMERIC_RE.sub(convert, text)
    except Exception:  # pragma: no cover - defensive
        return text


def _normalize_numbers(text: str, eff: EffectiveCfg) -> str:
    if not eff.enable_numbers:
        return text

    def fix_numeric(token: str) -> str:
        # Infer decimal separator
        dec = eff.decimal_detection
        if dec == "auto":
            # Last occurrence of comma/dot decides decimal separator
            last_comma = token.rfind(",")
            last_dot = token.rfind(".")
            if last_comma > last_dot:
                dec = "comma"
            else:
                dec = "dot"

        # Remove thousands separators
        if dec == "dot":
            # '.' is decimal; remove ',' and spaces; keep last '.'
            parts = token.split(".")
            if len(parts) > 1:
                decimals = parts[-1]
                int_part = "".join(parts[:-1])
                int_part = int_part.replace(",", "").replace(" ", "").replace("'", "")
                return f"{int_part}.{decimals}"
            else:
                return token.replace(",", "").replace(" ", "").replace("'", "")
        else:
            # comma decimal; swap comma→dot for decimal, strip other separators
            parts = token.split(",")
            if len(parts) > 1:
                decimals = parts[-1]
                int_part = "".join(parts[:-1])
                int_part = int_part.replace(".", "").replace(" ", "").replace("'", "")
                return f"{int_part}.{decimals}"
            else:
                return token.replace(".", "").replace(" ", "").replace("'", "")

    def repl(m: re.Match[str]) -> str:
        token = m.group(0)
        try:
            return fix_numeric(token)
        except Exception:  # pragma: no cover - defensive
            return token

    try:
        return _NUMERIC_TOKEN_RE.sub(repl, text)
    except Exception:  # pragma: no cover - defensive
        return text


def _normalize_text(text: str, eff: EffectiveCfg) -> str:
    """Normalize a text value using an effective configuration.

    Examples:
        Normalize unicode and whitespace:

        >>> cfg = ArgumentNormalizerConfig()
        >>> eff = _merge_overrides(cfg, "field")
        >>> _normalize_text("  Café  ", eff)
        'Café'

        Normalize numbers with auto decimal detection:

        >>> cfg2 = ArgumentNormalizerConfig(enable_numbers=True)
        >>> eff2 = _merge_overrides(cfg2, "price")
        >>> _normalize_text("1.234,56", eff2)
        '1234.56'

        Normalize dates with day-first style:

        >>> cfg3 = ArgumentNormalizerConfig(enable_dates=True, day_first=True)
        >>> eff3 = _merge_overrides(cfg3, "date")
        >>> _normalize_text("Due 31/12/2023", eff3)
        'Due 2023-12-31'

        Apply lower-casing:

        >>> cfg4 = ArgumentNormalizerConfig(enable_casing=True, case_strategy="lower")
        >>> eff4 = _merge_overrides(cfg4, "name")
        >>> _normalize_text("  JOHN DOE  ", eff4)
        'john doe'
    """
    original = text
    text = _normalize_unicode(text, eff)
    text = _normalize_whitespace(text, eff)
    text = _normalize_dates(text, eff)
    text = _normalize_numbers(text, eff)
    text = _normalize_casing(text, eff)
    return text if text != original else original


def _normalize_value(value: Any, base_cfg: ArgumentNormalizerConfig, path: str, modified_flag: Dict[str, bool]) -> Any:
    eff = _merge_overrides(base_cfg, path)
    if isinstance(value, str):
        new_val = _normalize_text(value, eff)
        if new_val != value:
            modified_flag["modified"] = True
        return new_val
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            child_path = f"{path}.{k}" if path else str(k)
            out[k] = _normalize_value(v, base_cfg, child_path, modified_flag)
        return out
    if isinstance(value, list):
        out_list: List[Any] = []
        for idx, item in enumerate(value):
            child_path = f"{path}[{idx}]"
            out_list.append(_normalize_value(item, base_cfg, child_path, modified_flag))
        return out_list
    return value


class ArgumentNormalizerPlugin(Plugin):
    """Argument Normalizer plugin for prompts and tools."""

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.cfg = ArgumentNormalizerConfig.model_validate(self._config.config)

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        if not payload.args:
            return PromptPrehookResult()

        modified = {"modified": False}
        normalized_args: Dict[str, Any] = {}
        for key, value in payload.args.items():
            normalized_args[key] = _normalize_value(value, self.cfg, key, modified)

        if modified["modified"]:
            logger.debug("ArgumentNormalizer: normalized prompt args for %s", payload.name)
            return PromptPrehookResult(
                modified_payload=PromptPrehookPayload(name=payload.name, args=normalized_args),
                metadata={"argument_normalizer": {"modified": True}},
            )

        return PromptPrehookResult()

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        if payload.args is None:
            return ToolPreInvokeResult()

        modified = {"modified": False}
        normalized_args = _normalize_value(payload.args, self.cfg, payload.name or "tool", modified)

        if modified["modified"]:
            logger.debug("ArgumentNormalizer: normalized tool args for %s", payload.name)
            return ToolPreInvokeResult(
                modified_payload=ToolPreInvokePayload(name=payload.name, args=normalized_args),
                metadata={"argument_normalizer": {"modified": True}},
            )

        return ToolPreInvokeResult()

    async def shutdown(self) -> None:
        logger.info("ArgumentNormalizer plugin shutting down")
