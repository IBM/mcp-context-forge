# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_catalog.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Stable catalog registration for authenticated reverse-proxy servers.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Literal
import uuid

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.orm import Session

from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Server as DbServer
from mcpgateway.schemas import GatewayRead, ServerCreate, ServerRead, ServerUpdate
from mcpgateway.services.gateway_service import (
    GatewayNameConflictError,
    GatewayService,
    ReverseProxyGatewayRegistration,
    ReverseProxyGatewayScope,
)
from mcpgateway.services.reverse_proxy_protocol import RegistrationServer
from mcpgateway.services.server_service import ServerNameConflictError, ServerService
from mcpgateway.utils.create_slug import slugify


CatalogVisibility = Literal["team", "public"]
# Stable forever: changing this namespace would orphan existing proxy catalog rows.
REVERSE_PROXY_CATALOG_NAMESPACE: Final = uuid.UUID("8f3b2d0f-7dc0-5c87-8a1e-a56f4d2bb8d1")


@dataclass(frozen=True, slots=True)
class AuthenticatedRegistrationContext:
    """Trusted ownership context derived before catalog registration."""

    owner_email: str
    team_id: str | None

    @property
    def canonical_owner_email(self) -> str:
        """Return the canonical authenticated owner."""
        return self.owner_email.strip().casefold()

    @property
    def canonical_team_id(self) -> str | None:
        """Return the canonical trusted team identifier when present."""
        return self.team_id.strip().casefold() if self.team_id is not None else None

    @property
    def visibility(self) -> CatalogVisibility:
        """Use team scope only when trusted team context exists."""
        return "team" if self.canonical_team_id is not None else "public"

    @property
    def scope_key(self) -> str:
        """Return the stable identity component for team or public scope."""
        team_id = self.canonical_team_id
        return f"team:{team_id}" if team_id is not None else "public"


@dataclass(frozen=True, slots=True)
class ReverseProxyCatalogEntry:
    """Matching gateway and empty virtual server created for one stable proxy."""

    stable_id: str
    gateway: GatewayRead
    server: ServerRead


@dataclass(frozen=True, slots=True)
class ReverseProxyCatalogConflictError(Exception):
    """Fail-closed conflict between stable proxy identity and persisted catalog state."""

    stable_id: str
    reason: str

    def __str__(self) -> str:
        """Return a safe conflict description."""
        return f"reverse-proxy catalog conflict for {self.stable_id}: {self.reason}"


def stable_proxy_id(context: AuthenticatedRegistrationContext, server: RegistrationServer) -> str:
    """Derive a deterministic UUIDv5 from authenticated owner, scope, and normalized name."""
    identity = f"owner={context.canonical_owner_email}|scope={context.scope_key}|name={slugify(server.name)}"
    return uuid.uuid5(REVERSE_PROXY_CATALOG_NAMESPACE, identity).hex


def _lock_catalog_registration(db: Session, catalog_id: str) -> None:
    """Acquire a transaction-scoped database lock for one stable registration."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        lock_key = int(catalog_id[:16], 16)
        if lock_key >= 2**63:
            lock_key -= 2**64
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
    elif dialect == "sqlite":
        db.execute(update(DbGateway).where(DbGateway.id == "__reverse_proxy_catalog_lock__").values(id=DbGateway.id))


class ReverseProxyCatalogService:
    """Create or reconcile stable reverse-proxy gateway/server catalog pairs."""

    def __init__(self, gateway_service: GatewayService | None = None, server_service: ServerService | None = None) -> None:
        """Initialize with the existing catalog services."""
        self._gateway_service = gateway_service or GatewayService()
        self._server_service = server_service or ServerService()

    async def register(
        self,
        db: Session,
        context: AuthenticatedRegistrationContext,
        registration: RegistrationServer,
    ) -> ReverseProxyCatalogEntry:
        """Create or reconcile the authenticated proxy's stable catalog pair."""
        catalog_id = stable_proxy_id(context, registration)
        scope = ReverseProxyGatewayScope(team_id=context.canonical_team_id, visibility=context.visibility)
        lock_identity = f"scope={context.scope_key}|name={slugify(registration.name)}"
        lock_id = uuid.uuid5(REVERSE_PROXY_CATALOG_NAMESPACE, lock_identity).hex
        try:
            _lock_catalog_registration(db, lock_id)
            server_scope_conflict = and_(DbServer.name == registration.name, DbServer.visibility == scope.visibility)
            if scope.visibility == "team":
                server_scope_conflict = and_(server_scope_conflict, DbServer.team_id == scope.team_id)
            candidates = db.execute(select(DbServer).where(or_(DbServer.id == catalog_id, server_scope_conflict)).with_for_update()).scalars().all()
            existing = next((candidate for candidate in candidates if candidate.id == catalog_id), None)
            conflicts = [candidate for candidate in candidates if candidate.id != catalog_id]
            if conflicts:
                raise ReverseProxyCatalogConflictError(stable_id=catalog_id, reason="virtual server name is already registered in this scope")

            if existing is not None:
                identity_matches = (
                    existing.created_via == "reverse_proxy"
                    and existing.name == registration.name
                    and existing.owner_email == context.canonical_owner_email
                    and existing.team_id == scope.team_id
                    and existing.visibility == scope.visibility
                )
                if not identity_matches:
                    raise ReverseProxyCatalogConflictError(stable_id=catalog_id, reason="stable ID belongs to different virtual server state")

            description_was_provided = "description" in registration.model_fields_set
            effective_description = registration.description if existing is None or description_was_provided else existing.description
            gateway_registration = ReverseProxyGatewayRegistration(
                stable_id=catalog_id,
                name=registration.name,
                description=effective_description,
                owner_email=context.canonical_owner_email,
                scope=scope,
            )
            gateway_created = db.get(DbGateway, catalog_id) is None
            await self._gateway_service.register_reverse_proxy_gateway(db, gateway_registration, commit=False)
            server_changed = existing is None or (description_was_provided and existing.description != registration.description)
            if existing is not None and server_changed:
                if registration.description is None:
                    existing.description = None
                    existing.updated_at = datetime.now(timezone.utc)
                    existing.modified_by = context.canonical_owner_email
                    existing.modified_via = "reverse_proxy"
                    existing.version += 1
                    db.flush()
                else:
                    await self._server_service.update_server(
                        db,
                        catalog_id,
                        ServerUpdate(
                            id=None,
                            name=registration.name,
                            description=registration.description,
                            icon=None,
                            tags=None,
                            team_id=None,
                            owner_email=None,
                            visibility=None,
                            oauth_enabled=None,
                            oauth_config=None,
                            associated_tools=None,
                            associated_resources=None,
                            associated_prompts=None,
                            associated_a2a_agents=None,
                        ),
                        context.canonical_owner_email,
                        modified_by=context.canonical_owner_email,
                        modified_via="reverse_proxy",
                        commit=False,
                    )
            elif existing is None:
                await self._server_service.register_server(
                    db,
                    ServerCreate(
                        id=catalog_id,
                        name=registration.name,
                        description=registration.description,
                        icon=None,
                        tags=[],
                        associated_tools=[],
                        associated_resources=[],
                        associated_prompts=[],
                        associated_a2a_agents=[],
                        team_id=None,
                        owner_email=None,
                        visibility="public",
                        oauth_enabled=False,
                        oauth_config=None,
                    ),
                    created_by=context.canonical_owner_email,
                    created_via="reverse_proxy",
                    team_id=scope.team_id,
                    owner_email=context.canonical_owner_email,
                    visibility=scope.visibility,
                    commit=False,
                )
            db.commit()
        except GatewayNameConflictError as exc:
            raise ReverseProxyCatalogConflictError(stable_id=catalog_id, reason=str(exc)) from exc
        except ServerNameConflictError as exc:
            raise ReverseProxyCatalogConflictError(stable_id=catalog_id, reason=str(exc)) from exc
        finally:
            if db.in_transaction():
                db.rollback()

        db_gateway = db.get(DbGateway, catalog_id)
        db_server = db.get(DbServer, catalog_id)
        if db_gateway is None or db_server is None:
            raise ReverseProxyCatalogConflictError(stable_id=catalog_id, reason="catalog pair was not persisted")
        await self._gateway_service.finalize_reverse_proxy_gateway(db_gateway, gateway_registration, created=gateway_created)
        if server_changed:
            await self._server_service.finalize_reverse_proxy_server(
                db_server,
                created=existing is None,
                user_email=context.canonical_owner_email,
            )
        return ReverseProxyCatalogEntry(
            stable_id=catalog_id,
            gateway=self._gateway_service.convert_gateway_to_read(db_gateway),
            server=self._server_service.convert_server_to_read(db_server),
        )
