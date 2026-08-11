# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/praxis_replica_identity.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Target-bound identity and credential rotation for Praxis replicas.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import uuid

import jwt
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.db import EmailApiToken, EmailUser, Permissions, PraxisReplica, PraxisReplicaCredential, Role, TokenRevocation, UserRole, utc_now
from mcpgateway.utils.jwt_config_helper import get_jwt_private_key_or_secret, validate_jwt_algo_and_keys

PRAXIS_TOKEN_AUDIENCE = "praxis-config"
PRAXIS_REPLICA_ROLE = "praxis_replica"
PRAXIS_REPLICA_PERMISSIONS = frozenset({Permissions.PRAXIS_ARTIFACTS_READ, Permissions.PRAXIS_REPORTS_WRITE})


class PraxisReplicaIdentityError(Exception):
    """Base error for sanitized replica identity failures."""


class PraxisReplicaNotAvailableError(PraxisReplicaIdentityError):
    """The requested replica is absent, disabled, or revoked."""

    def __str__(self) -> str:
        """Return a stable sanitized message."""
        return "praxis replica is not available"


class PraxisReplicaRoleError(PraxisReplicaIdentityError):
    """The least-privilege machine role is missing or malformed."""

    def __str__(self) -> str:
        """Return a stable sanitized message."""
        return "praxis replica role is unavailable"


class PraxisCredentialLimitError(PraxisReplicaIdentityError):
    """Issuance would exceed the two-active-JTI invariant."""

    def __str__(self) -> str:
        """Return a stable sanitized message."""
        return "praxis replica already has two active credentials"


class PraxisCredentialConflictError(PraxisReplicaIdentityError):
    """A concurrent credential mutation won the transaction race."""

    def __str__(self) -> str:
        """Return a stable sanitized message."""
        return "praxis credential mutation conflicted"


@dataclass(frozen=True, slots=True)
class IssuedPraxisCredential:
    """One raw credential returned exactly once to its provisioning caller."""

    jti: str
    raw_token: str
    target_id: str
    replica_id: str
    credential_epoch: int
    expires_at: datetime


def praxis_replica_principal(replica_id: str) -> str:
    """Derive a non-loginable catalog principal without exposing replica names."""
    digest = hashlib.sha256(replica_id.encode()).hexdigest()
    return f"praxis-{digest}@replica.invalid"


class PraxisReplicaIdentityService:
    """Serialize replica credential issuance, observation, and revocation."""

    def __init__(self, db: Session) -> None:
        """Bind credential mutations to one caller-owned session."""
        self.db = db

    def issue_credential(self, replica_id: str, *, expires_at: datetime) -> IssuedPraxisCredential:
        """Issue one cataloged, target-bound machine token in one transaction."""
        now = utc_now()
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise PraxisCredentialConflictError

        committed = False
        try:
            replica = self._lock_replica(replica_id)
            active_count = self.db.scalar(
                select(func.count(PraxisReplicaCredential.id)).where(  # pylint: disable=not-callable
                    PraxisReplicaCredential.replica_id == replica.id,
                    PraxisReplicaCredential.revoked_at.is_(None),
                    PraxisReplicaCredential.expires_at > now,
                )
            )
            if (active_count or 0) >= 2:
                raise PraxisCredentialLimitError

            role = self._machine_role()
            principal = self._ensure_machine_principal(replica.id, role.id, now)
            next_epoch = self._increment_epoch(replica)
            jti = str(uuid.uuid4())
            raw_token = self._mint_token(principal, jti, expires_at, now)
            self.db.add_all(
                [
                    EmailApiToken(
                        user_email=principal,
                        name=f"praxis:{replica.id}:{next_epoch}",
                        jti=jti,
                        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                        resource_scopes=sorted(PRAXIS_REPLICA_PERMISSIONS),
                        expires_at=expires_at,
                        is_active=True,
                    ),
                    PraxisReplicaCredential(
                        target_id=replica.target_id,
                        replica_id=replica.id,
                        jti=jti,
                        credential_epoch=next_epoch,
                        issued_at=now,
                        expires_at=expires_at,
                    ),
                ]
            )
            self.db.commit()
            committed = True
            return IssuedPraxisCredential(jti, raw_token, replica.target_id, replica.id, next_epoch, expires_at)
        except IntegrityError:
            self.db.rollback()
        finally:
            if not committed and self.db.in_transaction():
                self.db.rollback()

        raise PraxisCredentialConflictError from None

    def observe_credential(self, jti: str) -> bool:
        """Record that a replica mounted and successfully used a newly issued JTI."""
        now = utc_now()
        credential = self.db.scalar(select(PraxisReplicaCredential).where(PraxisReplicaCredential.jti == jti, PraxisReplicaCredential.revoked_at.is_(None)))
        if credential is None:
            self.db.rollback()
            return False
        credential_expires_at = credential.expires_at.replace(tzinfo=timezone.utc) if credential.expires_at.tzinfo is None else credential.expires_at
        if credential_expires_at <= now:
            self.db.rollback()
            return False
        credential.last_seen_at = now
        replica = self.db.get(PraxisReplica, credential.replica_id)
        if replica is not None:
            replica.last_heartbeat_at = now
        self.db.commit()
        return True

    def revoke_after_observation(self, replica_id: str, *, old_jti: str, new_jti: str) -> bool:
        """Revoke the old JTI only after the replacement has authenticated once."""
        self._lock_replica(replica_id)
        replacement = self.db.scalar(
            select(PraxisReplicaCredential).where(
                PraxisReplicaCredential.replica_id == replica_id,
                PraxisReplicaCredential.jti == new_jti,
                PraxisReplicaCredential.last_seen_at.is_not(None),
                PraxisReplicaCredential.revoked_at.is_(None),
            )
        )
        if replacement is None:
            self.db.rollback()
            return False
        return self._revoke_locked(replica_id, old_jti)

    def revoke_credential(self, replica_id: str, jti: str) -> bool:
        """Revoke one bound JTI while serializing against concurrent issuance."""
        self._lock_replica(replica_id)
        return self._revoke_locked(replica_id, jti)

    def _lock_replica(self, replica_id: str) -> PraxisReplica:
        """Lock one enabled replica row for a serialized credential mutation."""
        if self.db.in_transaction():
            self.db.rollback()
        dialect = self.db.get_bind().dialect.name
        if dialect == "sqlite":
            self.db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        query = select(PraxisReplica).where(PraxisReplica.id == replica_id)
        if dialect == "postgresql":
            query = query.with_for_update()
        replica = self.db.scalar(query)
        if replica is None or not replica.enabled or replica.revoked_at is not None:
            raise PraxisReplicaNotAvailableError
        return replica

    def _machine_role(self) -> Role:
        """Load the fixed active machine role for replica principals."""
        role = self.db.scalar(select(Role).where(Role.name == PRAXIS_REPLICA_ROLE, Role.scope == "global", Role.is_active.is_(True)))
        if role is None or set(role.permissions) != PRAXIS_REPLICA_PERMISSIONS:
            raise PraxisReplicaRoleError
        return role

    def _ensure_machine_principal(self, replica_id: str, role_id: str, now: datetime) -> str:
        """Create or reuse the locked machine user for one replica."""
        principal = praxis_replica_principal(replica_id)
        if self.db.scalar(select(EmailUser).where(EmailUser.email == principal)) is None:
            self.db.add(EmailUser(email=principal, password_hash="!praxis-machine-account", full_name="Praxis replica", auth_provider=PRAXIS_REPLICA_ROLE, email_verified_at=now))
            self.db.flush()
        assignment = self.db.scalar(select(UserRole).where(UserRole.user_email == principal, UserRole.role_id == role_id, UserRole.scope == "global", UserRole.is_active.is_(True)))
        if assignment is None:
            self.db.add(UserRole(user_email=principal, role_id=role_id, scope="global", scope_id=None, granted_by=principal))
        return principal

    def _increment_epoch(self, replica: PraxisReplica) -> int:
        """Atomically advance the replica credential epoch or raise on conflict."""
        current = replica.credential_epoch
        updated_id = self.db.scalar(
            update(PraxisReplica).where(PraxisReplica.id == replica.id, PraxisReplica.credential_epoch == current).values(credential_epoch=current + 1).returning(PraxisReplica.id)
        )
        if updated_id is None:
            raise PraxisCredentialConflictError
        replica.credential_epoch = current + 1
        return current + 1

    def _revoke_locked(self, replica_id: str, jti: str) -> bool:
        """Revoke one active credential inside the replica lock."""
        credential = self.db.scalar(
            select(PraxisReplicaCredential).where(PraxisReplicaCredential.replica_id == replica_id, PraxisReplicaCredential.jti == jti, PraxisReplicaCredential.revoked_at.is_(None))
        )
        if credential is None:
            self.db.rollback()
            return False
        now = utc_now()
        credential.revoked_at = now
        catalog = self.db.scalar(select(EmailApiToken).where(EmailApiToken.jti == jti, EmailApiToken.is_active.is_(True)))
        if catalog is not None:
            catalog.is_active = False
            if self.db.get(TokenRevocation, jti) is None:
                self.db.add(TokenRevocation(jti=jti, revoked_by=catalog.user_email, reason="praxis_rotation", token_expiry=catalog.expires_at))
        replica = self.db.get(PraxisReplica, replica_id)
        if replica is None:
            raise PraxisReplicaNotAvailableError
        self._increment_epoch(replica)
        self.db.commit()
        return True

    @staticmethod
    def _mint_token(principal: str, jti: str, expires_at: datetime, issued_at: datetime) -> str:
        """Sign one expiring machine JWT for the replica principal."""
        validate_jwt_algo_and_keys()
        claims = {
            "sub": principal,
            "jti": jti,
            "iss": settings.jwt_issuer,
            "aud": PRAXIS_TOKEN_AUDIENCE,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "token_use": "praxis_replica",
            "scopes": {"permissions": sorted(PRAXIS_REPLICA_PERMISSIONS)},
        }
        return jwt.encode(claims, get_jwt_private_key_or_secret(), algorithm=settings.jwt_algorithm)
