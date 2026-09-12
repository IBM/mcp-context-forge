# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/role_resolution.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Scope-exact role-name resolution for external group mappings.

Shared by the admin CRUD router (write-time validation) and the trust-mode
claims module (read-time merge of mapping-supplied role names). It lives in
a neutral module because the claims module cannot import the router without
an import cycle (router -> verify_credentials -> sso_service ->
trusted_claims).

The rule (finding NB6): a mapping's cf_role resolves to exactly ONE active
roles row — team scope preferred, global scope as fallback, lowest role id
as tie-break, inactive rows never resolve, rows are never unioned.
"""

# Standard
from typing import Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Role

#: Scope preference for cf_role resolution: a mapping's context is a team,
#: so a team-scoped role wins over a global-scoped role of the same name.
MAPPING_ROLE_SCOPE_PREFERENCE = ("team", "global")


def resolve_mapping_role(db: Session, cf_role: str, cf_team_id: Optional[str] = None) -> Optional[Role]:
    """Resolve a mapping's cf_role to exactly one active Role row.

    roles.name is unique only per (name, scope) among active rows (partial
    unique index uq_roles_name_scope_active), so a name-only lookup can
    match several active rows across scopes and union more permissions
    than intended (or pick arbitrarily). Resolution is scope-exact and
    deterministic:

    1. The active team-scoped row wins: the mapping's context is a team
       (cf_team_id).
    2. Otherwise the active global-scoped row.
    3. Otherwise the lowest-id active row of any other scope.

    Duplicate active rows within one scope are impossible via the unique
    index; defended anyway by taking the lowest role id. Rows are never
    unioned. Inactive rows never resolve.

    Args:
        db: Database session.
        cf_role: Role name to resolve.
        cf_team_id: Team context of the mapping (recorded for the scope
            preference; Role.scope is a scope type, not a per-team id).

    Returns:
        Optional[Role]: The single resolved row, or None when no active
            row matches the name.
    """
    rows = db.query(Role).filter(Role.name == cf_role, Role.is_active.is_(True)).all()
    if not rows:
        return None
    for scope in MAPPING_ROLE_SCOPE_PREFERENCE:
        scoped = [row for row in rows if row.scope == scope]
        if scoped:
            return min(scoped, key=lambda row: row.id)
    return min(rows, key=lambda row: row.id)
