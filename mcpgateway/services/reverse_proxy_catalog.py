# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_catalog.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Stable catalog registration for authenticated reverse-proxy servers.
"""

from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Final, Literal
import uuid

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.orm import Session

from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import fresh_db_session
from mcpgateway.db import Server as DbServer
from mcpgateway.schemas import GatewayRead, ServerCreate, ServerRead, ServerUpdate
from mcpgateway.services.gateway_service import (
    _get_registry_cache,
    _get_tool_lookup_cache,
    audit_trail,
    GatewayNameConflictError,
    GatewayService,
    structured_logger,
)
from mcpgateway.services.reverse_proxy_protocol import is_internal_proxied_gateway, RegistrationServer
from mcpgateway.services.reverse_proxy_sessions import ReverseProxyEviction, ReverseProxySessionManager
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
    gateway_created: bool = False
    server_created: bool = False
    server_changed: bool = False


@dataclass(frozen=True, slots=True)
class ReverseProxyCatalogConflictError(Exception):
    """Fail-closed conflict between stable proxy identity and persisted catalog state."""

    stable_id: str
    reason: str

    def __str__(self) -> str:
        """Return a safe conflict description."""
        return f"reverse-proxy catalog conflict for {self.stable_id}: {self.reason}"


@dataclass(frozen=True, slots=True)
class ReverseProxyGatewayScope:
    """Trusted catalog scope for an internal reverse-proxy gateway."""

    team_id: str | None
    visibility: Literal["team", "public"]


@dataclass(frozen=True, slots=True)
class ReverseProxyGatewayRegistration:
    """Internal reverse-proxy gateway values derived from authenticated context."""

    stable_id: str
    name: str
    description: str | None
    owner_email: str
    scope: ReverseProxyGatewayScope


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
    """Create or reconcile stable reverse-proxy gateway/server catalog pairs, and own their internal PROXIED gateway rows."""

    def __init__(self, gateway_service: GatewayService | None = None, server_service: ServerService | None = None) -> None:
        """Initialize with the existing catalog services."""
        self._gateway_service = gateway_service or GatewayService()
        self._server_service = server_service or ServerService()

    async def register(
        self,
        db: Session,
        context: AuthenticatedRegistrationContext,
        registration: RegistrationServer,
        *,
        commit: bool = True,
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
            await self.register_reverse_proxy_gateway(db, gateway_registration, commit=False)
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
            if commit:
                db.commit()
            else:
                db.flush()
        except GatewayNameConflictError as exc:
            db.rollback()
            raise ReverseProxyCatalogConflictError(stable_id=catalog_id, reason=str(exc)) from exc
        except ServerNameConflictError as exc:
            db.rollback()
            raise ReverseProxyCatalogConflictError(stable_id=catalog_id, reason=str(exc)) from exc
        except Exception:
            db.rollback()
            raise

        db_gateway = db.get(DbGateway, catalog_id)
        db_server = db.get(DbServer, catalog_id)
        if db_gateway is None or db_server is None:
            raise ReverseProxyCatalogConflictError(stable_id=catalog_id, reason="catalog pair was not persisted")
        entry = ReverseProxyCatalogEntry(
            stable_id=catalog_id,
            gateway=self._gateway_service.convert_gateway_to_read(db_gateway),
            server=self._server_service.convert_server_to_read(db_server),
            gateway_created=gateway_created,
            server_created=existing is None,
            server_changed=server_changed,
        )
        if commit:
            await self.publish_post_commit_effects(db, context, registration, entry)
        return entry

    async def publish_post_commit_effects(
        self,
        db: Session,
        context: AuthenticatedRegistrationContext,
        registration: RegistrationServer,
        entry: ReverseProxyCatalogEntry,
    ) -> None:
        """Publish catalog notifications only after the caller commits staged rows."""
        db_gateway = db.get(DbGateway, entry.stable_id)
        db_server = db.get(DbServer, entry.stable_id)
        if db_gateway is None or db_server is None:
            raise ReverseProxyCatalogConflictError(stable_id=entry.stable_id, reason="catalog pair was not persisted")
        gateway_registration = ReverseProxyGatewayRegistration(
            stable_id=entry.stable_id,
            name=registration.name,
            description=db_gateway.description,
            owner_email=context.canonical_owner_email,
            scope=ReverseProxyGatewayScope(team_id=context.canonical_team_id, visibility=context.visibility),
        )
        await self.finalize_reverse_proxy_gateway(db_gateway, gateway_registration, created=entry.gateway_created)
        if entry.server_changed:
            await self._server_service.finalize_reverse_proxy_server(
                db_server,
                created=entry.server_created,
                user_email=context.canonical_owner_email,
            )

    async def register_reverse_proxy_gateway(self, db: Session, registration: ReverseProxyGatewayRegistration, *, commit: bool = True) -> GatewayRead:
        """Create or reconcile an internal PROXIED gateway without network initialization."""
        internal_url = f"reverse-proxy://catalog/{registration.stable_id}"
        scope = registration.scope
        slug_name = slugify(registration.name)
        scope_conflict = and_(DbGateway.slug == slug_name, DbGateway.visibility == scope.visibility)
        if scope.visibility == "team":
            scope_conflict = and_(scope_conflict, DbGateway.team_id == scope.team_id)

        candidates = db.execute(select(DbGateway).where(or_(DbGateway.id == registration.stable_id, DbGateway.url == internal_url, scope_conflict)).with_for_update()).scalars().all()
        existing = next((candidate for candidate in candidates if candidate.id == registration.stable_id), None)
        conflicts = [candidate for candidate in candidates if candidate.id != registration.stable_id]
        if conflicts:
            conflict = conflicts[0]
            raise GatewayNameConflictError(conflict.slug, enabled=conflict.enabled, gateway_id=conflict.id, visibility=conflict.visibility)

        if existing is not None:
            identity_matches = (
                is_internal_proxied_gateway(existing)
                and existing.url == internal_url
                and existing.slug == slug_name
                and existing.name == registration.name
                and existing.owner_email == registration.owner_email
                and existing.team_id == scope.team_id
                and existing.visibility == scope.visibility
            )
            if not identity_matches:
                raise GatewayNameConflictError(existing.slug, enabled=existing.enabled, gateway_id=existing.id, visibility=existing.visibility)
            existing.description = registration.description
            existing.enabled = True
            existing.reachable = True
            existing.status = "active"
            existing.status_message = None
            existing.last_error = None
            existing.last_seen = datetime.now(timezone.utc)
            existing.modified_by = registration.owner_email
            existing.modified_via = "reverse_proxy"
            if commit:
                db.commit()
                db.refresh(existing)
                await self.finalize_reverse_proxy_gateway(existing, registration, created=False)
            else:
                db.flush()
            return self._gateway_service.convert_gateway_to_read(existing)

        now = datetime.now(timezone.utc)
        db_gateway = DbGateway(
            id=registration.stable_id,
            name=registration.name,
            slug=slug_name,
            url=internal_url,
            description=registration.description,
            tags=[],
            transport="PROXIED",
            capabilities={},
            last_seen=now,
            tools=[],
            resources=[],
            prompts=[],
            created_by=registration.owner_email,
            created_via="reverse_proxy",
            version=1,
            team_id=scope.team_id,
            owner_email=registration.owner_email,
            visibility=scope.visibility,
            status="active",
            enabled=True,
            reachable=True,
        )
        db.add(db_gateway)
        if not commit:
            db.flush()
            return self._gateway_service.convert_gateway_to_read(db_gateway)

        db.commit()
        db.refresh(db_gateway)
        await self.finalize_reverse_proxy_gateway(db_gateway, registration, created=True)
        return self._gateway_service.convert_gateway_to_read(db_gateway)

    async def mark_reverse_proxy_gateways_unreachable(
        self,
        session_manager: ReverseProxySessionManager,
        evictions: tuple[ReverseProxyEviction, ...],
        *,
        seen_at: datetime,
        authority_guard: Callable[[ReverseProxyEviction], AbstractAsyncContextManager[bool]] | None = None,
    ) -> None:
        """Persist generation-safe disconnect state for authoritative PROXIED rows.

        When ``authority_guard`` is given it is entered around the whole
        check-and-commit window, so a distributed guard can serialize this
        write against a concurrent replacement registration; the write is
        skipped whenever the guard yields ``False``.
        """
        if not evictions:
            return
        changed = False
        first_error: Exception | None = None
        for eviction in evictions:
            try:
                async with session_manager.registration_lock(eviction.stable_id):
                    if session_manager.resolve_connection_id(eviction.stable_id) is not None:
                        continue
                    guard = authority_guard(eviction) if authority_guard is not None else nullcontext(True)
                    async with guard as permitted:
                        if not permitted:
                            continue
                        with fresh_db_session() as db:
                            gateway = db.get(DbGateway, str(eviction.stable_id))
                            if gateway is not None and is_internal_proxied_gateway(gateway):
                                gateway.reachable = False
                                gateway.last_seen = seen_at
                                db.commit()
                                changed = True
            except Exception as persistence_error:  # pylint: disable=broad-exception-caught
                if first_error is None:
                    first_error = persistence_error
        if changed:
            try:
                await _get_registry_cache().invalidate_gateways()
            except Exception as cache_error:  # pylint: disable=broad-exception-caught
                if first_error is None:
                    first_error = cache_error
        if first_error is not None:
            raise first_error

    async def finalize_reverse_proxy_gateway(self, db_gateway: DbGateway, registration: ReverseProxyGatewayRegistration, *, created: bool) -> None:
        """Publish reverse-proxy gateway effects after its transaction commits."""
        cache = _get_registry_cache()
        if not created:
            await cache.invalidate_gateways()
            return

        internal_url = f"reverse-proxy://catalog/{registration.stable_id}"
        scope = registration.scope
        await self._gateway_service._notify_gateway_added(db_gateway)  # pylint: disable=protected-access
        await cache.invalidate_gateways()
        tool_lookup_cache = _get_tool_lookup_cache()
        await tool_lookup_cache.invalidate_gateway(registration.stable_id)

        # First-Party
        from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

        await admin_stats_cache.invalidate_tags()
        audit_trail.log_action(
            user_id=registration.owner_email,
            action="create_gateway",
            resource_type="gateway",
            resource_id=registration.stable_id,
            resource_name=registration.name,
            user_email=registration.owner_email,
            team_id=scope.team_id,
            new_values={"name": registration.name, "url": internal_url, "visibility": scope.visibility, "transport": "PROXIED"},
            context={"created_via": "reverse_proxy"},
        )
        structured_logger.log(
            level="INFO",
            message="Gateway created successfully",
            event_type="gateway_created",
            component="gateway_service",
            user_id=registration.owner_email,
            user_email=registration.owner_email,
            team_id=scope.team_id,
            resource_type="gateway",
            resource_id=registration.stable_id,
            custom_fields={"gateway_name": registration.name, "gateway_url": internal_url, "visibility": scope.visibility, "transport": "PROXIED"},
        )
