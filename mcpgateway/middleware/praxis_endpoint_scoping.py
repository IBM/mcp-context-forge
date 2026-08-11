# -*- coding: utf-8 -*-
"""Bearer-only authorization for target-bound Praxis machine routes."""

from dataclasses import dataclass
import hashlib
import hmac
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.db import EmailApiToken, Permissions, PraxisReplica, PraxisReplicaCredential, PraxisRollout, PraxisTarget, Role, SessionLocal, TokenRevocation, UserRole, utc_now
from mcpgateway.services.praxis_replica_identity import PRAXIS_REPLICA_PERMISSIONS, PRAXIS_REPLICA_ROLE, PRAXIS_TOKEN_AUDIENCE, praxis_replica_principal
from mcpgateway.praxis_feature_gates import require_praxis_activation, require_praxis_artifact_delivery
from mcpgateway.services.praxis_bundle_observability import emit_praxis_event, PraxisLifecycleEvent, PraxisOutcome, PraxisTransition
from mcpgateway.utils.jwt_config_helper import get_jwt_public_key_or_secret, validate_jwt_algo_and_keys

_security = HTTPBearer(auto_error=False)
_DENIED = "Access denied"
_MACHINE_STAGE_GATES: dict[str, Callable[[], None]] = {
    Permissions.PRAXIS_ARTIFACTS_READ: require_praxis_artifact_delivery,
    Permissions.PRAXIS_REPORTS_WRITE: require_praxis_activation,
}


@dataclass(frozen=True, slots=True)
class PraxisReplicaRequestIdentity:
    """Server-side identity resolved only from an active credential JTI binding."""

    target_id: str
    replica_id: str
    jti: str


class UnsupportedPraxisPermissionError(Exception):
    """A route requested a permission outside the machine contract."""

    def __str__(self) -> str:
        """Return the stable configuration error."""
        return "unsupported Praxis machine permission"


async def authorize_praxis_replica(request: Request, raw_token: str, required_permission: str, db: Session) -> PraxisReplicaRequestIdentity:
    """Authorize one HTTPS request against catalog, JTI binding, scope, and role."""
    if request.url.scheme != "https":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="HTTPS required")
    try:
        validate_jwt_algo_and_keys()
        payload = jwt.decode(
            raw_token,
            get_jwt_public_key_or_secret(),
            algorithms=[settings.jwt_algorithm],
            audience=PRAXIS_TOKEN_AUDIENCE,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "jti", "aud", "iss"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"}) from None
    if payload.get("token_use") != "praxis_replica":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"})
    payload_scopes = payload.get("scopes")
    if not isinstance(payload_scopes, dict) or set(payload_scopes.get("permissions") or []) != PRAXIS_REPLICA_PERMISSIONS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED)
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"})

    now = utc_now()
    catalog = db.scalar(
        select(EmailApiToken).where(
            EmailApiToken.jti == jti,
            EmailApiToken.is_active.is_(True),
            EmailApiToken.expires_at.is_not(None),
            EmailApiToken.expires_at > now,
        )
    )
    if catalog is None or not hmac.compare_digest(catalog.token_hash, hashlib.sha256(raw_token.encode()).hexdigest()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"})
    if db.get(TokenRevocation, jti) is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"})
    if set(catalog.resource_scopes or []) != PRAXIS_REPLICA_PERMISSIONS or required_permission not in PRAXIS_REPLICA_PERMISSIONS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED)

    binding = db.scalar(
        select(PraxisReplicaCredential).where(
            PraxisReplicaCredential.jti == jti,
            PraxisReplicaCredential.revoked_at.is_(None),
            PraxisReplicaCredential.expires_at > now,
        )
    )
    if binding is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"})
    replica = db.scalar(
        select(PraxisReplica).where(
            PraxisReplica.id == binding.replica_id,
            PraxisReplica.target_id == binding.target_id,
            PraxisReplica.enabled.is_(True),
            PraxisReplica.revoked_at.is_(None),
        )
    )
    if replica is None or catalog.user_email != praxis_replica_principal(replica.id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"})
    target = db.get(PraxisTarget, binding.target_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"})
    if not target.enabled:
        stop_is_current = db.scalar(
            select(PraxisRollout.rollout_id).where(
                PraxisRollout.target_id == target.id,
                PraxisRollout.rollout_id == target.desired_rollout_id,
                PraxisRollout.action == "stop",
            )
        )
        if request.url.path != "/praxis/v1/desired" or stop_is_current is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"})

    role = db.scalar(
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_email == catalog.user_email,
            UserRole.scope == "global",
            UserRole.is_active.is_(True),
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > now),
            Role.name == PRAXIS_REPLICA_ROLE,
            Role.scope == "global",
            Role.is_active.is_(True),
        )
    )
    if role is None or set(role.permissions) != PRAXIS_REPLICA_PERMISSIONS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_DENIED)

    binding.last_seen_at = now
    replica.last_heartbeat_at = now
    db.commit()
    return PraxisReplicaRequestIdentity(target_id=binding.target_id, replica_id=binding.replica_id, jti=jti)


def require_praxis_replica(required_permission: str) -> Callable[..., Awaitable[PraxisReplicaRequestIdentity]]:
    """Build a FastAPI dependency for one exact Praxis machine permission."""
    if required_permission not in PRAXIS_REPLICA_PERMISSIONS:
        raise UnsupportedPraxisPermissionError

    async def dependency(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
    ) -> PraxisReplicaRequestIdentity:
        _MACHINE_STAGE_GATES[required_permission]()
        if credentials is None or credentials.scheme.lower() != "bearer":
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.REJECTED_CREDENTIAL, PraxisOutcome.REJECTED, reason="credential_denied"))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_DENIED, headers={"WWW-Authenticate": "Bearer"})
        try:
            with SessionLocal() as db:
                identity = await authorize_praxis_replica(request, credentials.credentials, required_permission, db)
        except HTTPException:
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.REJECTED_CREDENTIAL, PraxisOutcome.REJECTED, reason="credential_denied"))
            raise
        return identity

    return dependency
