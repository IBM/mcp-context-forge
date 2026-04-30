# -*- coding: utf-8 -*-
"""Location: ./tests/protocol_compliance/helpers/drift.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Cross-target payload normalization for drift detection.

The harness compares responses from ``reference``, ``gateway_proxy``, and
``gateway_virtual`` and asserts that — after accounting for legitimate
gateway decoration — they're structurally equal. Divergence that survives
normalization is drift.

Normalization responsibilities:
  * Strip the gateway's slug prefix from tool names (``compliance-reference-echo``
    → ``echo``) so the name sets compare apples-to-apples.
  * Drop gateway-added metadata fields (``annotations``, ``meta``, ``_meta``)
    that describe decoration, not behavior.
  * Sort list payloads so ordering differences don't surface as drift.
  * For tool-call results, compare only ``isError`` and the textual content
    of the response — not the wire-level envelope's decoration.

Anything NOT stripped here is a behavioral assertion. If the gateway adds
a new legitimate decoration field in the future, extend the strip list
*once* with a clear comment — don't paper over it inside individual tests.
"""

from __future__ import annotations

from typing import Any, Iterable

from .compliance import GATEWAY_UPSTREAM_SLUG

_SLUG_PREFIX = f"{GATEWAY_UPSTREAM_SLUG}-"


def _strip_slug_prefix(name: str) -> str:
    """Translate ``compliance-reference-log-at-level`` → ``log_at_level``."""
    if name.startswith(_SLUG_PREFIX):
        bare = name[len(_SLUG_PREFIX) :]
        return bare.replace("-", "_")
    return name


def normalize_tool_names(tools: Iterable[Any]) -> list[str]:
    """Return the sorted set of *bare* tool names from our reference upstream.

    When the gateway has multiple registered upstreams (e.g. the bundled
    ``fast-test-*`` / ``fast-time-*`` test stack), gateway targets advertise
    tools from *all* of them. That's not drift — it's the ambient test
    environment. Normalization filters to just the ``compliance-reference-*``
    slug so cross-target comparison is apples-to-apples.

    On the reference target, names are bare (no slug prefix), so we return
    them as-is.
    """
    names = [t.name for t in tools]
    has_slug_prefix = any(n.startswith(_SLUG_PREFIX) for n in names)
    if has_slug_prefix:
        return sorted({_strip_slug_prefix(n) for n in names if n.startswith(_SLUG_PREFIX)})
    return sorted(set(names))


def normalize_resource_uris(resources: Iterable[Any]) -> list[str]:
    """Return the sorted set of resource URIs. Gateway doesn't re-namespace URIs."""
    return sorted({str(r.uri) for r in resources})


def normalize_prompt_names(prompts: Iterable[Any]) -> list[str]:
    """Return the sorted set of *bare* prompt names. Same slug-strip as tools."""
    return sorted({_strip_slug_prefix(p.name) for p in prompts})


def normalize_tool_result(result: Any) -> dict[str, Any]:
    """Reduce a ``CallToolResult`` to the fields that encode behavior.

    Strips ``meta`` / ``_meta`` on the envelope and each content block.
    Keeps ``isError`` and the concatenated text of each text content item.
    """
    content_texts: list[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            content_texts.append(text)
    return {
        "isError": bool(result.isError),
        "text": "\n".join(content_texts),
    }


def assert_drift_free(results_by_target: dict[str, Any], *, probe: str) -> None:
    """Pairwise-compare normalized results, skipping unavailable targets.

    Raises AssertionError with a readable diff if any two available targets
    disagree. Silently returns if fewer than two targets are available —
    drift can't be assessed from one data point.
    """
    available = {k: v for k, v in results_by_target.items() if v is not None}
    if len(available) < 2:
        return

    items = list(available.items())
    first_name, first_value = items[0]
    for other_name, other_value in items[1:]:
        assert first_value == other_value, f"drift on probe {probe!r} between {first_name} and {other_name}:\n" f"  {first_name}: {first_value!r}\n" f"  {other_name}: {other_value!r}"
