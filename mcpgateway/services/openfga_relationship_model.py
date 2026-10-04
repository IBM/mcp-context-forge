# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/openfga_relationship_model.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Relationship-based OpenFGA model for ContextForge.

This model encodes team boundaries as graph topology rather than
application-layer checks. A ContextForge team is modeled as a
``domain`` — a deliberately abstract tenant concept that works
identically whether membership comes from the database
(``email_team_members``), from Entra group claims, or from KeyCloak
role claims in a JWT.

The model hierarchy::

    domain:eng
      ├── member: [user:anne, user:bob]
      ├── admin: [user:anne]
      │
      └── server:api-gw
          └── parent: [domain:eng]

    check(user:anne, can_update, server:api-gw)
      → server:api-gw → parent → domain:eng → admin → user:anne ✓

Every capability type gains ``parent: [domain]`` and per-permission
relations that traverse the domain hierarchy. The type-wide marker
objects (``<type>:all``) remain for global/platform-admin checks.
"""

# Standard
import logging
from typing import Any

# First-Party
from mcpgateway.db import Permissions
from mcpgateway.services.rule_catalog_service import capability_for_permission
from mcpgateway.services.openfga_sync import relation_for

logger = logging.getLogger(__name__)

ENTITY_TYPES = ("tool", "resource", "prompt", "server", "gateway", "a2a_agent", "route")


def build_relationship_type_definitions() -> list[dict[str, Any]]:
    """Build the relationship-based authorization model.

    The key difference from the flat model: every capability type has a
    ``parent: [domain]`` relation, and permission relations traverse the
    domain hierarchy instead of relying on type-wide role grants.

    Returns:
        Type definitions in the OpenFGA JSON form (schema 1.1).
    """
    permissions = Permissions.get_all_permissions()
    by_type: dict[str, list[str]] = {entity: [] for entity in ENTITY_TYPES}
    for permission in permissions:
        by_type[capability_for_permission(permission)].append(permission)

    type_definitions: list[dict[str, Any]] = [
        {"type": "user"},
        {
            "type": "domain",
            "relations": {
                "member": {"this": {}},
                "admin": {"this": {}},
            },
            "metadata": {
                "relations": {
                    "member": {"directly_related_user_types": [{"type": "user"}]},
                    "admin": {"directly_related_user_types": [{"type": "user"}]},
                }
            },
        },
    ]

    for entity in ENTITY_TYPES:
        relations: dict[str, Any] = {
            "parent": {"this": {}},
            "blocked": {"this": {}},
        }
        metadata: dict[str, Any] = {
            "relations": {
                "parent": {"directly_related_user_types": [{"type": "domain"}]},
                "blocked": {"directly_related_user_types": [{"type": "user"}, {"type": "domain", "relation": "admin"}, {"type": "domain", "relation": "member"}]},
            }
        }
        for permission in by_type[entity]:
            rel = relation_for(permission)
            # Domain members get read access; domain admins get everything
            if ".read" in permission or ".preview" in permission or permission.startswith("a2a.read"):
                relations[rel] = {
                    "union": {
                        "child": [
                            {"this": {}},
                            {"computedUserset": {"object": "", "relation": ""}},  # placeholder replaced below
                        ]
                    }
                }
                # Simpler: use tupleToUserset for member traversal
                relations[rel] = {
                    "union": {
                        "child": [
                            {"this": {}},
                            {"tupleToUserset": {"tupleset": {"relation": "parent"}, "computedUserset": {"relation": "member"}}},
                        ]
                    }
                }
                metadata["relations"][rel] = {
                    "directly_related_user_types": [
                        {"type": "user"},
                        {"type": "domain", "relation": "admin"},
                        {"type": "domain", "relation": "member"},
                    ]
                }
            else:
                # Write operations: admin from parent, plus direct grants
                relations[rel] = {
                    "union": {
                        "child": [
                            {"this": {}},
                            {"tupleToUserset": {"tupleset": {"relation": "parent"}, "computedUserset": {"relation": "admin"}}},
                        ]
                    }
                }
                metadata["relations"][rel] = {
                    "directly_related_user_types": [
                        {"type": "user"},
                        {"type": "domain", "relation": "admin"},
                    ]
                }

        type_definitions.append({"type": entity, "relations": relations, "metadata": metadata})

    return type_definitions


def build_relationship_conditions() -> dict[str, Any]:
    """Build the condition definitions for the relationship model.

    Returns:
        The conditions map (same temporal grant condition as the flat model).
    """
    from mcpgateway.services.openfga_sync import build_conditions  # pylint: disable=import-outside-toplevel

    return build_conditions()
