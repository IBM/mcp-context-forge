# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/trusted_claims.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Trusted claims extraction and group-to-team resolution. This module will also
host extract_trusted_principal (added by #5899).
"""

# Standard
from typing import List, Optional, Tuple

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import ExternalGroupMapping


def resolve_external_groups_to_teams(issuer: str, tenant: Optional[str], groups: List[str], db: Session) -> Tuple[List[str], List[str]]:
    """Resolve external IdP group IDs to ContextForge team IDs and role names.

    Reads the external_group_mappings table for rows that match the token
    issuer, tenant, and at least one of the supplied external group IDs.
    Unmapped groups contribute nothing (fail-closed): a group with no mapping
    row grants no team and no role. Raw external group IDs never reach
    token_teams; only mapped cf_team_id values are returned.

    Args:
        issuer: Token issuer claim used to scope mapping rows.
        tenant: Token tenant claim. None matches only tenant-less mapping rows.
        groups: External group IDs from the token groups claim.
        db: Database session.

    Returns:
        Tuple[List[str], List[str]]: (team_ids, role_names) in table order,
        de-duplicated. A row with cf_role NULL contributes only its team.

    Examples:
        >>> resolve_external_groups_to_teams("iss", "tenant", [], None)
        ([], [])
    """
    if not groups:
        return [], []

    query = db.query(ExternalGroupMapping).filter(
        ExternalGroupMapping.issuer == issuer,
        ExternalGroupMapping.external_group_id.in_(groups),
    )
    if tenant is None:
        query = query.filter(ExternalGroupMapping.tenant.is_(None))
    else:
        query = query.filter(ExternalGroupMapping.tenant == tenant)

    team_ids: List[str] = []
    role_names: List[str] = []
    for row in query.all():
        if row.cf_team_id and row.cf_team_id not in team_ids:
            team_ids.append(row.cf_team_id)
        if row.cf_role and row.cf_role not in role_names:
            role_names.append(row.cf_role)
    return team_ids, role_names
