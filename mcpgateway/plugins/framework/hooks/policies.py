# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/hooks/policies.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Hook payload policy types and utilities.

The framework provides the types and utilities for controlled payload
modification; the gateway defines the actual concrete policies.

Examples:
    >>> from mcpgateway.plugins.framework.hooks.policies import HookPayloadPolicy, apply_policy
    >>> policy = HookPayloadPolicy(writable_fields=frozenset({"name", "args"}))
    >>> sorted(policy.writable_fields)
    ['args', 'name']
"""

# Standard
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

# Third-Party
from pydantic import BaseModel


class DefaultHookPolicy(str, Enum):
    """Controls behavior for hooks without an explicit policy.

    Attributes:
        ALLOW: Accept all modifications (backwards compatible).
        DENY: Reject all modifications (strict mode).

    Examples:
        >>> DefaultHookPolicy.ALLOW
        <DefaultHookPolicy.ALLOW: 'allow'>
        >>> DefaultHookPolicy.DENY.value
        'deny'
        >>> DefaultHookPolicy('allow')
        <DefaultHookPolicy.ALLOW: 'allow'>
    """

    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class HookPayloadPolicy:
    """Defines which payload fields plugins are allowed to modify.

    Attributes:
        writable_fields: The set of field names that plugins may change.

    Examples:
        >>> policy = HookPayloadPolicy(writable_fields=frozenset({"name", "args"}))
        >>> "name" in policy.writable_fields
        True
        >>> "secret" in policy.writable_fields
        False
    """

    writable_fields: frozenset[str]


_SENTINEL = object()


def apply_policy(
    original: BaseModel,
    modified: BaseModel,
    policy: HookPayloadPolicy,
) -> Optional[BaseModel]:
    """Apply policy-based controlled merge.

    Only fields listed in ``policy.writable_fields`` are accepted from
    *modified*; all other changes are silently discarded.

    Args:
        original: The original (or current) payload.
        modified: The payload returned by the plugin.
        policy: The policy defining which fields are writable.

    Returns:
        An updated payload with only the allowed changes applied, or
        ``None`` if the plugin made no effective (allowed) changes.

    Examples:
        >>> from pydantic import BaseModel, ConfigDict
        >>> class P(BaseModel):
        ...     model_config = ConfigDict(frozen=True)
        ...     name: str
        ...     secret: str
        >>> orig = P(name="old", secret="s")
        >>> mod = P(name="new", secret="hacked")
        >>> policy = HookPayloadPolicy(writable_fields=frozenset({"name"}))
        >>> result = apply_policy(orig, mod, policy)
        >>> result.name
        'new'
        >>> result.secret
        's'
    """
    updates: dict[str, Any] = {}
    for field in policy.writable_fields:
        old_val = getattr(original, field, _SENTINEL)
        new_val = getattr(modified, field, _SENTINEL)
        if new_val is not _SENTINEL and new_val != old_val:
            updates[field] = new_val
    return original.model_copy(update=updates) if updates else None
