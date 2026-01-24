# -*- coding: utf-8 -*-
"""Location: ./plugins/safe_html_sanitizer/safe_html_sanitizer.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Safe HTML Sanitizer Plugin.

Sanitizes fetched HTML to neutralize common XSS vectors:
- Removes dangerous tags (script, iframe, object, embed, meta, link)
- Strips event handlers (on*) and inline style (optional)
- Blocks javascript:, vbscript:, and data: URLs (configurable data:image/*)
- Removes HTML comments (optional)
- Optionally converts sanitized HTML to plain text

Hook: resource_post_fetch
"""

# Future
from __future__ import annotations

# Standard
import html
from html.parser import HTMLParser
import re
from typing import Dict, List, Optional, Tuple

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
)

DEFAULT_ALLOWED_TAGS = [
    "a",
    "p",
    "div",
    "span",
    "strong",
    "em",
    "code",
    "pre",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "img",
    "br",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
]

DEFAULT_ALLOWED_ATTRS: Dict[str, List[str]] = {
    "*": ["id", "class", "title", "alt"],
    "a": ["href", "rel", "target"],
    "img": ["src", "width", "height", "alt", "title"],
    "table": ["border", "cellpadding", "cellspacing", "summary"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
}

DANGEROUS_TAGS = {"script", "iframe", "object", "embed", "meta", "link", "style"}
SAFE_TARGETS = {"_blank", "_self", "_parent", "_top"}

ON_ATTR = re.compile(r"^on[a-z]+", re.IGNORECASE)
BAD_SCHEMES = ("javascript:", "vbscript:")

DATA_URI_RE = re.compile(r"^data:([a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+)")
BIDI_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069]")

# Precompiled patterns for _to_text function
_BLOCK_BREAK_RE = re.compile(r"</(p|div|h[1-6]|li|tr|table|blockquote)>", re.IGNORECASE)
_NO_TAGS_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINES_RE = re.compile(r"\n{3,}")

# Precompiled patterns for fallback sanitization
_DANGEROUS_TAGS_RE = re.compile(r"<\s*(script|iframe|object|embed|style)[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_EVENT_HANDLERS_RE = re.compile(r"on[a-z]+\s*=\s*\"[^\"]*\"", re.IGNORECASE)


class SafeHTMLConfig(BaseModel):
    """Configuration for HTML sanitization.

    Attributes:
        allowed_tags: List of permitted HTML tags.
        allowed_attrs: Map of tag names to allowed attributes.
        remove_comments: Whether to remove HTML comments.
        drop_unknown_tags: Whether to remove unknown tags.
        strip_event_handlers: Whether to remove event handler attributes.
        sanitize_css: Whether to remove style attributes.
        allow_data_images: Whether to allow data: image URIs.
        remove_bidi_controls: Whether to remove bidirectional control characters.
        to_text: Whether to convert sanitized HTML to plain text.
    """

    allowed_tags: List[str] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_TAGS))
    allowed_attrs: Dict[str, List[str]] = Field(default_factory=lambda: dict(DEFAULT_ALLOWED_ATTRS))
    remove_comments: bool = True
    drop_unknown_tags: bool = True
    strip_event_handlers: bool = True
    sanitize_css: bool = True  # remove style attributes
    allow_data_images: bool = False
    remove_bidi_controls: bool = True
    to_text: bool = False


class _Sanitizer(HTMLParser):
    """HTML parser that sanitizes content by removing dangerous elements.

    Attributes:
        cfg: Sanitization configuration.
        out: List of output HTML fragments.
        skip_stack: Stack tracking nested dangerous tags to skip.
    """

    def __init__(self, cfg: SafeHTMLConfig) -> None:
        """Initialize the sanitizer.

        Args:
            cfg: Sanitization configuration.
        """
        super().__init__(convert_charrefs=True)
        self.cfg = cfg
        self.out: List[str] = []
        self.skip_stack: List[str] = []  # dangerous tag depth stack

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        """Handle HTML start tags with sanitization.

        Args:
            tag: Tag name.
            attrs: List of attribute name-value pairs.
        """
        if tag.lower() in DANGEROUS_TAGS:
            self.skip_stack.append(tag.lower())
            return
        if self.skip_stack:
            return
        tag_l = tag.lower()
        if tag_l not in self.cfg.allowed_tags:
            # Drop unknown tags but keep their inner content
            return
        # sanitize attributes
        allowed_for_tag = set(self.cfg.allowed_attrs.get(tag_l, []) + self.cfg.allowed_attrs.get("*", []))
        safe_attrs: List[Tuple[str, str]] = []
        rel_values: List[str] = []
        for name, value in attrs:
            if not name:
                continue
            n = name.lower()
            if self.cfg.strip_event_handlers and ON_ATTR.match(n):
                continue
            if n == "style" and self.cfg.sanitize_css:
                continue
            if n not in allowed_for_tag:
                continue
            val = value or ""
            # Remove bidi/zero-width from attributes too
            if self.cfg.remove_bidi_controls:
                val = BIDI_ZERO_WIDTH.sub("", val)
            # URL scheme checks
            if tag_l in {"a", "img"} and n in {"href", "src"}:
                vlow = val.strip().lower()
                if vlow.startswith(BAD_SCHEMES):
                    continue
                if vlow.startswith("data:"):
                    if not self.cfg.allow_data_images:
                        continue
                    m = DATA_URI_RE.match(vlow)
                    if not m or not m.group(1).startswith("image/"):
                        continue
            if tag_l == "a" and n == "target":
                if val not in SAFE_TARGETS:
                    val = "_blank"
            if tag_l == "a" and n == "rel":
                rel_values = [p.strip() for p in val.split()] if val else []
                continue  # we'll re-emit after target check
            safe_attrs.append((n, val))
        # Enforce rel="noopener noreferrer" for target=_blank
        if tag_l == "a":
            targets = {k: v for k, v in safe_attrs if k == "target"}
            if "target" in targets and targets["target"] == "_blank":
                rel_set = set(rel_values)
                rel_set.update({"noopener", "noreferrer"})
                safe_attrs = [(k, v) for (k, v) in safe_attrs if k != "rel"] + [("rel", " ".join(sorted(rel_set)))]
            elif rel_values:
                safe_attrs.append(("rel", " ".join(sorted(set(rel_values)))))
        # emit
        attr_str = "".join(f' {html.escape(k)}="{html.escape(v, quote=True)}"' for k, v in safe_attrs)
        self.out.append(f"<{tag_l}{attr_str}>")

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        """Handle self-closing HTML tags.

        Args:
            tag: Tag name.
            attrs: List of attribute name-value pairs.
        """
        # Treat as start + end for void tags
        self.handle_starttag(tag, attrs)
        # If we emitted, last char is '>' and tag is allowed; we can self-close by replacing last '>' with '/>'
        if self.out and self.out[-1].startswith(f"<{tag.lower()}") and self.out[-1].endswith(">"):
            self.out[-1] = self.out[-1][:-1] + " />"

    def handle_endtag(self, tag: str) -> None:
        """Handle HTML end tags.

        Args:
            tag: Tag name.
        """
        t = tag.lower()
        if t in DANGEROUS_TAGS:
            if self.skip_stack and self.skip_stack[-1] == t:
                self.skip_stack.pop()
            return
        if self.skip_stack:
            return
        if t not in self.cfg.allowed_tags:
            return
        self.out.append(f"</{t}>")

    def handle_data(self, data: str) -> None:
        """Handle text data between HTML tags.

        Args:
            data: Text content.
        """
        if self.skip_stack:
            return
        text = data
        if self.cfg.remove_bidi_controls:
            text = BIDI_ZERO_WIDTH.sub("", text)
        self.out.append(html.escape(text))

    def handle_comment(self, data: str) -> None:
        """Handle HTML comments.

        Args:
            data: Comment content.
        """
        if self.cfg.remove_comments:
            return
        self.out.append(f"<!--{data}-->")

    def get_html(self) -> str:
        """Get the sanitized HTML output.

        Returns:
            Sanitized HTML string.
        """
        return "".join(self.out)


def _to_text(html_str: str) -> str:
    """Convert HTML to plain text.

    Args:
        html_str: HTML string to convert.

    Returns:
        Plain text with basic formatting preserved.
    """
    # Very simple, retain line breaks around common block tags
    block_break = _BLOCK_BREAK_RE.sub("\n", html_str)
    # Strip the remaining tags
    no_tags = _NO_TAGS_RE.sub("", block_break)
    # Collapse multiple newlines
    return _MULTI_NEWLINES_RE.sub("\n\n", no_tags).strip()


class SafeHTMLSanitizerPlugin(Plugin):
    """Sanitizes HTML content to remove XSS vectors and dangerous elements."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the safe HTML sanitizer plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = SafeHTMLConfig(**(config.config or {}))

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Sanitize HTML content after resource fetch.

        Args:
            payload: Resource post-fetch payload.
            context: Plugin execution context.

        Returns:
            Result with sanitized HTML content.
        """
        content = payload.content
        if not hasattr(content, "text") or not isinstance(content.text, str) or not content.text:
            return ResourcePostFetchResult(continue_processing=True)

        parser = _Sanitizer(self._cfg)
        try:
            parser.feed(content.text)
            sanitized = parser.get_html()
        except Exception:
            # On parser errors, fall back to a minimal strip of dangerous tags
            sanitized = _DANGEROUS_TAGS_RE.sub("", content.text)
            sanitized = _EVENT_HANDLERS_RE.sub("", sanitized)

        if self._cfg.to_text:
            new_text = _to_text(sanitized)
        else:
            new_text = sanitized

        if new_text != content.text:
            new_payload = ResourcePostFetchPayload(uri=payload.uri, content=type(content)(**{**content.model_dump(), "text": new_text}))
            return ResourcePostFetchResult(modified_payload=new_payload, metadata={"html_sanitized": True})
        return ResourcePostFetchResult(metadata={"html_sanitized": False})
