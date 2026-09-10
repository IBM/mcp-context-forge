# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/trusted_claims.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Trusted claims extraction and group-to-team resolution (issues #5899, #5976).

This module maps a verified external-IdP JWT payload to a virtual principal
per the pinned trust-mode contract. It also hosts the group-mapping resolver,
the group-overage marker detector shared with the SSO enrichment path, and
the overage policy dispatch (:func:`resolve_overage_groups`, issue #5977).

Claim readers support dotted paths one or more levels deep (for example the
Keycloak ``realm_access.roles`` shape). Each path segment must name a JSON
object member; traversal through arrays or scalar values is not supported and
resolves to "claim absent". A missing optional claim yields the field
default; a missing required claim is an extraction error.

PRINCIPAL CONTRACT (VirtualPrincipal):

- ``user_id``: required, opaque string. Read from the claim named by
  ``jwt_claim_user_id``. No UUID heuristic applies in trust mode. A missing
  mapped claim raises an extraction error with 401 semantics; the value never
  defaults to the email claim.
- ``email``: optional, None allowed. Read from the claim named by
  ``jwt_claim_email``. Audit-path writes degrade to the ``"unknown"``
  sentinel string (never None) because ``AuditTrail.user_id`` is
  ``nullable=False``; ``ObservabilityTrace.user_email`` is nullable and
  accepts None. See :attr:`VirtualPrincipal.audit_identity`.
- ``full_name``: optional, default None. Read from the ``name`` claim.
- ``teams``: normalized list of team ID strings. The claim named by
  ``jwt_claim_teams`` accepts a list of strings or a list of ``{id, name}``
  mappings, mirroring ``normalize_token_teams`` in ``auth_context.py``.
  Mapped team IDs from the external-group resolver are appended. External
  group IDs never enter ``teams`` directly. When every external group is
  unmapped and the token carries no teams claim, ``teams`` is ``[]``
  (public-only access; the principal still authenticates).
- ``roles``: list of role names. The claim named by ``jwt_claim_roles``
  merges with role names returned by the group-mapping resolver before
  resolution. Role names resolve to permission sets via the server-side
  ``roles`` table only; permissions are never embedded in or read from the
  token. Unknown role names are ignored with a WARNING log (fail-closed).
- ``is_admin``: bool, default False. Read from the claim named by
  ``jwt_claim_admin``.
- ``auth_provider``: the token issuer (``iss``) when present, else the
  string ``"jwt-trust"``.
- ``token_use``: the constant string ``"trusted"``.

Revocation: the claim named by ``jwt_trust_revocation_claim`` (default
``jti``; ``uti`` supported for Entra trust roots) is the revocation
identifier. A trust-eligible token missing the configured claim is rejected
with 401 semantics.
"""

# Standard
from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional, Tuple

# Third-Party
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import ExternalGroupMapping, Role, SSOProvider
from mcpgateway.utils.entra_graph_client import EntraGraphClient, EntraGraphError

logger = logging.getLogger(__name__)

#: Sentinel written on the AuditTrail path when the token carries no email.
AUDIT_UNKNOWN_SENTINEL = "unknown"


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


@dataclass
class VirtualPrincipal:
    """Virtual principal extracted from a trusted external-IdP token.

    Exposes the attributes downstream consumers read (``.email``,
    ``.is_admin``, ``.full_name``) per the pinned contract in the module
    docstring. Instances are synthetic: they are never persisted and never
    cached as ORM rows.
    """

    user_id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    teams: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    is_admin: bool = False
    auth_provider: str = "jwt-trust"
    token_use: str = "trusted"

    @property
    def audit_identity(self) -> str:
        """Identity string for the AuditTrail path.

        ``AuditTrail.user_id`` is ``nullable=False``, so an absent email
        degrades to the ``"unknown"`` sentinel string; a None write never
        occurs on this path.

        Returns:
            The principal email, or the ``"unknown"`` sentinel.
        """
        return self.email or AUDIT_UNKNOWN_SENTINEL


def _get_claim(payload: Dict[str, Any], claim_path: str) -> Any:
    """Read a claim by dotted path.

    Each segment must name a JSON object member. Traversal through arrays or
    scalar values is not supported and resolves to None (claim absent).

    Args:
        payload: Verified JWT payload.
        claim_path: Claim name, optionally dotted (``realm_access.roles``).

    Returns:
        The claim value, or None when the path does not resolve.
    """
    node: Any = payload
    for segment in claim_path.split("."):
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node


def _normalize_teams_claim(value: Any) -> List[str]:
    """Normalize a teams claim to a list of team ID strings.

    Mirrors ``normalize_token_teams`` in ``auth_context.py``: a list of
    strings passes through; a list of ``{id, name}`` mappings contributes
    each ``id``; other entries are dropped.

    Args:
        value: Raw teams claim value.

    Returns:
        List of team ID strings.
    """
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    for team in value:
        if isinstance(team, dict):
            team_id = team.get("id")
            if team_id:
                normalized.append(str(team_id))
        elif isinstance(team, str):
            normalized.append(team)
    return normalized


def detect_overage_marker(payload: Dict[str, Any]) -> bool:
    """Detect the Entra group-overage marker shapes in a token payload.

    When a user exceeds the group-claim limit, Entra emits overage markers
    instead of an inline groups array: ``_claim_names`` containing
    ``groups``, a ``hasgroups`` key, a ``groups:srcN`` key, or a string-typed
    ``groups`` claim. Shared with the SSO enrichment path; detection only —
    resolution behavior follows ``jwt_trust_overage_policy``.

    Args:
        payload: Token claims dict.

    Returns:
        True when any overage marker is present.
    """
    claim_names = payload.get("_claim_names", {})
    if isinstance(claim_names, dict) and "groups" in claim_names:
        return True
    if payload.get("hasgroups"):
        return True
    if any(isinstance(key, str) and key.startswith("groups:src") for key in payload):
        return True
    return isinstance(payload.get("groups"), str)


def extract_revocation_id(payload: Dict[str, Any], settings: Any) -> str:
    """Extract the revocation identifier honoring the configured claim.

    The claim named by ``jwt_trust_revocation_claim`` (default ``jti``;
    ``uti`` supported for Entra trust roots) carries the revocation
    identifier. A trust-eligible token missing the configured claim is
    rejected with 401 semantics.

    Args:
        payload: Verified JWT payload.
        settings: Settings object carrying ``jwt_trust_revocation_claim``.

    Returns:
        The revocation identifier string.

    Raises:
        HTTPException: 401 when the configured claim is absent or empty.
    """
    claim = settings.jwt_trust_revocation_claim
    value = _get_claim(payload, claim)
    if not value or not isinstance(value, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Trust-eligible token is missing the revocation claim {claim!r}.",
        )
    return value


def extract_trusted_principal(payload: Dict[str, Any], settings: Any, db: Session) -> VirtualPrincipal:
    """Extract a virtual principal from a verified trusted-IdP JWT payload.

    Implements the pinned contract documented in the module docstring:

    - ``user_id`` (required, opaque): read from the claim named by
      ``jwt_claim_user_id``; a missing mapped claim raises 401 and never
      defaults to email.
    - ``email`` (optional, None allowed): read from ``jwt_claim_email``.
    - ``full_name`` (optional, default None): read from the ``name`` claim.
    - ``teams`` (list of strings): the ``jwt_claim_teams`` claim normalized
      (list of strings or list of ``{id, name}``, mirroring
      ``normalize_token_teams``), plus team IDs returned by the
      external-group resolver. External group IDs never enter ``teams``
      directly. All groups unmapped and no teams claim yields ``[]``
      (public-only access; the principal still authenticates).
    - ``roles`` (list of strings): the ``jwt_claim_roles`` claim merged with
      resolver-supplied role names, then validated against the server-side
      ``roles`` table; unknown names are skipped with a WARNING log
      (fail-closed). Permissions are never read from the token.
    - ``is_admin`` (bool, default False): read from ``jwt_claim_admin``.
    - ``auth_provider``: the token issuer (``iss``) when present, else
      ``"jwt-trust"``.
    - ``token_use``: the constant ``"trusted"``.

    The token must carry the revocation claim named by
    ``jwt_trust_revocation_claim``; a missing claim raises 401.

    Args:
        payload: Verified JWT payload from a trusted external IdP.
        settings: Settings object carrying the ``jwt_claim_*`` and
            ``jwt_trust_revocation_claim`` mappings.
        db: Database session for the group-mapping resolver and the
            server-side roles table.

    Returns:
        VirtualPrincipal matching the pinned contract.

    Raises:
        HTTPException: 401 when the mapped user_id claim or the configured
            revocation claim is absent.
    """
    extract_revocation_id(payload, settings)

    user_id = _get_claim(payload, settings.jwt_claim_user_id)
    if not user_id or not isinstance(user_id, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Trust-eligible token is missing the user_id claim {settings.jwt_claim_user_id!r}.",
        )

    issuer = payload.get("iss") or "jwt-trust"
    tenant = payload.get("tid")

    teams = _normalize_teams_claim(_get_claim(payload, settings.jwt_claim_teams))
    role_names: List[str] = []
    raw_roles = _get_claim(payload, settings.jwt_claim_roles)
    if isinstance(raw_roles, list):
        role_names.extend(str(role) for role in raw_roles)

    # External groups are NOT teams: group-claim values are external group
    # IDs that feed the mapping resolver. Resolver team IDs and role names
    # merge here, before server-side roles-table resolution.
    external_groups = payload.get("groups")
    if isinstance(external_groups, list) and external_groups:
        mapped_team_ids, mapped_role_names = resolve_external_groups_to_teams(issuer, tenant, [str(group) for group in external_groups], db)
        for team_id in mapped_team_ids:
            if team_id not in teams:
                teams.append(team_id)
        for role_name in mapped_role_names:
            if role_name not in role_names:
                role_names.append(role_name)

    known_roles = {row[0] for row in db.query(Role.name).filter(Role.is_active.is_(True)).all()}
    roles: List[str] = []
    for role_name in role_names:
        if role_name in known_roles:
            if role_name not in roles:
                roles.append(role_name)
        else:
            logger.warning("Ignoring unknown role name %r from trusted token for user %s (fail-closed).", role_name, user_id)

    full_name = payload.get("name")

    email = _get_claim(payload, settings.jwt_claim_email)

    return VirtualPrincipal(
        user_id=user_id,
        email=email if isinstance(email, str) else None,
        full_name=full_name if isinstance(full_name, str) else None,
        teams=teams,
        roles=roles,
        is_admin=bool(_get_claim(payload, settings.jwt_claim_admin)),
        auth_provider=issuer,
        token_use="trusted",
    )


async def resolve_overage_groups(payload: Dict[str, Any], settings: Any, db: Session, graph_client: Optional[Any] = None) -> List[str]:
    """Apply ``jwt_trust_overage_policy`` to an overage-marked trusted token.

    Dispatches on the configured policy:

    - ``fail_closed`` (default): reject with 401 and an actionable detail.
    - ``graph_lookup``: resolve the user's security groups through the
      app-only Microsoft Graph client (oid-keyed cache). The SSO provider
      record matching the token issuer supplies the encrypted client
      credentials; the inbound bearer token is never used. Any acquisition
      failure rejects with 401.
    - ``proceed_without_groups``: continue with an empty group list and emit
      a WARNING log carrying the user's oid on every overage-triggered
      request.

    Args:
        payload: Verified JWT payload carrying an overage marker (see
            :func:`detect_overage_marker`).
        settings: Settings object carrying ``jwt_trust_overage_policy`` and
            ``jwt_claim_user_id``.
        db: Database session for the SSO provider lookup.
        graph_client: Optional EntraGraphClient override (tests).

    Returns:
        List of external group object IDs. Empty under
        ``proceed_without_groups``.

    Raises:
        HTTPException: 401 under ``fail_closed``, or under ``graph_lookup``
            when the oid claim, the provider record, or the Graph resolution
            fails.
    """
    policy = getattr(settings, "jwt_trust_overage_policy", "fail_closed")
    oid = payload.get("oid")
    log_id = oid if isinstance(oid, str) and oid else _get_claim(payload, settings.jwt_claim_user_id)

    if policy == "fail_closed":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token carries an Entra group-overage marker (groups claim omitted) and jwt_trust_overage_policy is 'fail_closed'. "
            "Set jwt_trust_overage_policy to 'graph_lookup' or 'proceed_without_groups' to admit overage tokens.",
        )

    if policy == "proceed_without_groups":
        logger.warning(
            "Entra group overage for oid %s: group resolution skipped; proceeding without groups (jwt_trust_overage_policy=proceed_without_groups).",
            log_id,
        )
        return []

    # graph_lookup
    if not isinstance(oid, str) or not oid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="jwt_trust_overage_policy 'graph_lookup' requires the token 'oid' claim for the Graph user lookup.",
        )

    issuer = payload.get("iss")
    provider = db.query(SSOProvider).filter(SSOProvider.issuer == issuer, SSOProvider.is_enabled.is_(True)).first()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"No enabled SSO provider matches token issuer {issuer!r}; cannot resolve the group overage via Microsoft Graph.",
        )

    client = graph_client or EntraGraphClient()
    try:
        return await client.get_member_groups(provider, oid, token_exp=payload.get("exp"))
    except EntraGraphError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Group overage resolution via Microsoft Graph failed for oid {oid}: {exc}",
        ) from exc
