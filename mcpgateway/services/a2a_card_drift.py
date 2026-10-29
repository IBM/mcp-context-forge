# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/a2a_card_drift.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Compare two A2A Agent Cards and classify the changes.

A change is behaviour-affecting when it alters how the gateway calls the agent:
the supported interfaces (URL, binding, protocol version), the security schemes
and requirements, and ``capabilities.streaming``. Every other change is descriptive.
"""

# Standard
from typing import Any, Dict, List

# First-Party
from mcpgateway.services.a2a_card_import import normalize_card, suggest_agent_fields

BEHAVIOUR_AFFECTING_PATHS = frozenset({"supportedInterfaces", "securitySchemes", "securityRequirements", "capabilities.streaming"})
_MISSING = object()


def _flatten(card: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a card one level so ``capabilities`` fields compare individually.

    Args:
        card: Card in the 1.0 shape.

    Returns:
        Mapping of path to value, for example ``capabilities.streaming``.
    """
    flat: Dict[str, Any] = {}
    for key, value in card.items():
        if key == "capabilities" and isinstance(value, dict):
            flat.update({f"capabilities.{name}": item for name, item in value.items()})
        else:
            flat[key] = value
    return flat


def diff_cards(old: Dict[str, Any], new: Dict[str, Any], endpoint_url: str) -> Dict[str, Any]:
    """Report how ``new`` differs from ``old``.

    Both cards are normalized to the 1.0 shape first, so a card that moves from the
    0.3 to the 1.0 format does not report format-only differences.

    Args:
        old: The currently applied card.
        new: The freshly fetched card.
        endpoint_url: The agent's stored ``endpoint_url``.

    Returns:
        A report with ``changes``, ``behaviourAffecting``, and ``unapplied``. ``unapplied`` names
        deployment settings that applying the card never rewrites: ``endpoint_url`` and ``auth``.

    Examples:
        >>> old = {"name": "a", "supportedInterfaces": [{"url": "https://x/rpc"}], "capabilities": {"streaming": False}}
        >>> report = diff_cards(old, {**old, "description": "new"}, "https://x/rpc")
        >>> report["behaviourAffecting"], [c["path"] for c in report["changes"]]
        (False, ['description'])
        >>> diff_cards(old, {**old, "capabilities": {"streaming": True}}, "https://x/rpc")["behaviourAffecting"]
        True
    """
    old_flat = _flatten(normalize_card(old)[0])
    new_flat = _flatten(normalize_card(new)[0])

    changes: List[Dict[str, Any]] = []
    for path in sorted(set(old_flat) | set(new_flat)):
        before = old_flat.get(path, _MISSING)
        after = new_flat.get(path, _MISSING)
        if before == after:
            continue
        change: Dict[str, Any] = {
            "path": path,
            "change": "added" if before is _MISSING else "removed" if after is _MISSING else "modified",
            "behaviourAffecting": path in BEHAVIOUR_AFFECTING_PATHS,
        }
        if before is not _MISSING:
            change["before"] = before
        if after is not _MISSING:
            change["after"] = after
        changes.append(change)

    unapplied: List[str] = []
    if any(change["path"] in ("securitySchemes", "securityRequirements") for change in changes):
        unapplied.append("auth")
    if new_flat.get("supportedInterfaces") and suggest_agent_fields(normalize_card(new)[0])[0]["endpoint_url"] != endpoint_url:
        unapplied.append("endpoint_url")

    return {"changes": changes, "behaviourAffecting": any(change["behaviourAffecting"] for change in changes), "unapplied": unapplied}
