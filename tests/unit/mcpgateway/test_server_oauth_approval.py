# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_server_oauth_approval.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Check virtual-server OAuth approval, migration, and session boundaries.
"""

# Standard
from contextlib import asynccontextmanager
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.cache.session_registry import SessionRegistry
from mcpgateway.db import Base, Server
from mcpgateway.schemas import ServerCreate, ServerUpdate
from mcpgateway.services.server_service import ServerError, ServerLockConflictError, ServerNotFoundError, ServerService
from mcpgateway.transports import streamablehttp_transport as transport
from mcpgateway.utils.server_oauth import resolve_server_oauth_issuers, server_oauth_context_is_current, server_oauth_is_approved

CONFIG = {"authorization_servers": ["https://issuer.example.com"]}


@pytest.mark.parametrize(
    "config,allow_localhost,expected",
    [
        (CONFIG, False, ["https://issuer.example.com"]),
        ({"authorization_servers": [None, 4, "", " "]}, False, []),
        ({"authorization_servers": "invalid", "authorization_server": " https://issuer.example.com "}, False, ["https://issuer.example.com"]),
        ({"authorization_servers": ["https://issuer.example.com:invalid"]}, False, []),
        ({"authorization_servers": ["https:///missing-host"]}, False, []),
        ({"authorization_servers": ["ftp://issuer.example.com"]}, True, []),
        ({"authorization_servers": ["http://localhost"]}, False, []),
        ({"authorization_servers": ["http://localhost", "http://127.0.0.1", "http://[::1]"]}, True, ["http://localhost", "http://127.0.0.1", "http://[::1]"]),
        ({"authorization_server": "http://issuer.example.com"}, True, []),
        ({"authorization_servers": []}, False, []),
    ],
)
def test_issuer_validation_preserves_scheme_and_localhost_policy(monkeypatch, config, allow_localhost, expected):
    """Only HTTPS or explicitly permitted loopback HTTP issuers can receive approval."""
    monkeypatch.setattr("mcpgateway.utils.server_oauth.settings.ssrf_allow_localhost", allow_localhost)
    assert resolve_server_oauth_issuers(config) == expected


@pytest.mark.parametrize(
    "context,scope",
    [
        ({"auth_method": "oauth_access_token"}, None),
        ({"auth_method": "oauth_access_token", "oauth_server_id": 1, "oauth_config_generation": "current"}, None),
        ({"auth_method": "oauth_access_token", "oauth_server_id": "server", "oauth_config_generation": "current"}, "another-server"),
    ],
)
def test_missing_or_mismatched_oauth_provenance_fails_without_lookup(context, scope):
    """Legacy and cross-server OAuth identities cannot reach a database lookup or dispatch."""
    db = MagicMock()
    assert not server_oauth_context_is_current(db, context, scope)
    db.execute.assert_not_called()


def test_absent_approval_state_and_independent_authentication():
    """Absent approval fails closed while independent authentication retains its own policy."""
    assert not server_oauth_is_approved(None)
    assert not server_oauth_is_approved(SimpleNamespace(oauth_enabled=True))
    db = MagicMock()
    assert server_oauth_context_is_current(db, {"auth_method": "jwt"})
    db.execute.assert_not_called()


@pytest.fixture
def approval_db():
    """Provide an isolated SQLite database with the complete application schema."""
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    engine.dispose()


@pytest.fixture
def approval_service(monkeypatch):
    """Disable external notifications and audit sinks for isolated persistence tests."""
    service = ServerService()
    service._audit_trail = MagicMock()
    service._structured_logger = MagicMock()
    service._notify_server_added = AsyncMock()
    service._notify_server_updated = AsyncMock()
    monkeypatch.setattr("mcpgateway.services.server_service.notify_dataplane", lambda: None)
    monkeypatch.setattr("mcpgateway.services.server_service._get_registry_cache", lambda: SimpleNamespace(invalidate_servers=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.server_service._get_tool_lookup_cache", lambda: SimpleNamespace(invalidate_server=AsyncMock()))
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_config_save_requires_authorized_approval(approval_db, approval_service, authorized):
    """Only authorized OAuth saves approve a new configuration generation."""
    created = await approval_service.register_server(approval_db, ServerCreate(name="approved", oauth_enabled=True, oauth_config=CONFIG), oauth_authorized=authorized)
    stored = approval_db.get(Server, created.id)
    assert stored.oauth_config_approved is authorized
    assert isinstance(stored.oauth_config_generation, str)
    assert created.oauth_config_approved is authorized


@pytest.mark.asyncio
async def test_reapproval_requires_reviewed_version(approval_db, approval_service):
    """Reapproval preserves settings and rejects a stale reviewed version."""
    server = Server(name="pending", oauth_enabled=True, oauth_config=dict(CONFIG), version=3)
    approval_db.add(server)
    approval_db.commit()
    with pytest.raises(ServerLockConflictError):
        await approval_service.approve_oauth_config(approval_db, server.id, 2, user_id="reviewer@example.com")
    assert server.oauth_config_approved is False
    approval_service._audit_trail.log_action.assert_not_called()
    result = await approval_service.approve_oauth_config(approval_db, server.id, 3, user_id="reviewer@example.com")
    approval_db.refresh(server)
    assert result == {"oauth_config_approved": True, "version": 4}
    assert server.oauth_config == CONFIG
    assert server.oauth_config_generation
    event = approval_service._audit_trail.log_action.call_args.kwargs
    assert event["user_id"] == "reviewer@example.com"
    assert event["action"] == "approve_server_oauth"
    assert event["resource_id"] == server.id
    assert event["details"] == {"oauth_config_generation": server.oauth_config_generation, "reviewed_version": 3, "version": 4}
    assert "db" not in event


@pytest.mark.asyncio
async def test_reapproval_rejects_missing_server(approval_db, approval_service):
    """Approval cannot create a server through an unknown identifier."""
    with pytest.raises(ServerNotFoundError):
        await approval_service.approve_oauth_config(approval_db, "missing", 1, user_id="reviewer@example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,config", [(False, CONFIG), (True, None), (True, {}), (True, {"authorization_servers": ["ftp://issuer.example.com"]})])
async def test_reapproval_requires_usable_enabled_configuration(approval_db, approval_service, enabled, config):
    """Disabled, absent, and invalid issuers remain unapproved after attempted review."""
    server = Server(name="pending", oauth_enabled=enabled, oauth_config=config, version=1)
    approval_db.add(server)
    approval_db.commit()
    with pytest.raises(ServerError):
        await approval_service.approve_oauth_config(approval_db, server.id, 1, user_id="reviewer@example.com")
    assert server.oauth_config_approved is False
    assert server.oauth_config_generation is None
    approval_service._audit_trail.log_action.assert_not_called()


@pytest.mark.asyncio
async def test_reapproval_rolls_back_when_concurrent_update_wins(approval_db, approval_service, monkeypatch):
    """Approval fails when the conditional write detects a concurrent configuration change."""
    server = Server(name="pending", oauth_enabled=True, oauth_config=CONFIG, version=1)
    approval_db.add(server)
    approval_db.commit()
    monkeypatch.setattr("mcpgateway.services.server_service.get_for_update", lambda *_args, **_kwargs: server)
    proxy = MagicMock(wraps=approval_db)
    proxy.execute.return_value = SimpleNamespace(rowcount=0)
    with pytest.raises(ServerLockConflictError):
        await approval_service.approve_oauth_config(proxy, server.id, 1, user_id="reviewer@example.com")
    proxy.rollback.assert_called_once()
    proxy.commit.assert_not_called()
    approval_db.refresh(server)
    assert server.oauth_config_approved is False


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("secret_value", ["same-secret", "masked"])
async def test_unchanged_oauth_save_preserves_trust(approval_db, approval_service, approved, secret_value):
    """Unchanged settings preserve pending approval and active session generations, including masked secrets."""
    from mcpgateway.config import settings

    config = {**CONFIG, "resource": "learned", "client_secret": "same-secret"}  # pragma: allowlist secret
    created = await approval_service.register_server(approval_db, ServerCreate(name="unchanged", oauth_enabled=True, oauth_config=config), oauth_authorized=True)
    server = approval_db.get(Server, created.id)
    server.oauth_config_approved = approved
    approval_db.commit()
    generation = server.oauth_config_generation
    encrypted_config = dict(server.oauth_config)
    context = {"auth_method": "oauth_access_token", "oauth_server_id": server.id, "oauth_config_generation": generation}
    submitted = {**config, "client_secret": settings.masked_auth_value if secret_value == "masked" else secret_value}
    await approval_service.update_server(approval_db, server.id, ServerUpdate(description="metadata", oauth_enabled=True, oauth_config=submitted), user_email="", oauth_authorized=True)
    assert server.oauth_config_approved is approved
    assert server.oauth_config_generation == generation
    assert server.oauth_config == encrypted_config
    assert server_oauth_context_is_current(approval_db, context, server.id) is approved
    audit = approval_service._audit_trail.log_action.call_args.kwargs
    assert audit["details"]["oauth_changed"] is False
    assert "same-secret" not in str(audit)
    assert "db" not in audit


@pytest.mark.asyncio
async def test_request_validation_cache_tracks_identity_and_scope(approval_db, monkeypatch):
    """Approval queries repeat only for a new request, identity, scope, generation, or forced validation."""
    server = Server(name="trusted", oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=True, oauth_config_generation="current")
    approval_db.add(server)
    approval_db.commit()
    proxy = MagicMock(wraps=approval_db)

    @asynccontextmanager
    async def get_db():
        yield proxy

    monkeypatch.setattr(transport, "get_db", get_db)
    context = {"user_id": "one", "is_authenticated": True, "auth_method": "oauth_access_token", "oauth_server_id": server.id, "oauth_config_generation": "current"}
    monkeypatch.setattr(transport, "_resolve_request_context", AsyncMock(return_value=(server.id, {}, context)))
    request_token = transport._oauth_validation_request_var.set(object())
    cache_token = transport._oauth_validated_context_var.set(None)
    checked_token = transport._oauth_checked_var.set(True)
    try:
        await transport._check_server_oauth_enforcement(server.id, context)
        await transport._check_server_oauth_enforcement(server.id, context)
        await transport._get_request_context_or_default()
        await transport._get_request_context_or_default()
        assert proxy.execute.call_count == 1
        await transport._validate_server_oauth_context(server.id, context, fresh=True)
        assert proxy.execute.call_count == 2
        await transport._validate_server_oauth_context(server.id, {**context, "user_id": "two"})
        assert proxy.execute.call_count == 3
        transport._oauth_validation_request_var.set(object())
        await transport._validate_server_oauth_context(server.id, context)
        assert proxy.execute.call_count == 4
        with pytest.raises(HTTPException):
            await transport._validate_server_oauth_context("other-server", context)
        with pytest.raises(HTTPException):
            await transport._validate_server_oauth_context(server.id, {**context, "oauth_config_generation": "old"})
        server.oauth_config_approved = False
        approval_db.commit()
        transport._oauth_validation_request_var.set(object())
        with pytest.raises(HTTPException):
            await transport._validate_server_oauth_context(server.id, context)
    finally:
        transport._oauth_validation_request_var.reset(request_token)
        transport._oauth_validated_context_var.reset(cache_token)
        transport._oauth_checked_var.reset(checked_token)


@pytest.mark.asyncio
async def test_sdk_scope_validation_does_not_reuse_inherited_request_cache(approval_db, monkeypatch):
    """SDK requests override inherited task context and require validation for each new scope."""
    server = Server(name="sdk", oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=True, oauth_config_generation="current")
    approval_db.add(server)
    approval_db.commit()
    proxy = MagicMock(wraps=approval_db)

    @asynccontextmanager
    async def get_db():
        yield proxy

    monkeypatch.setattr(transport, "get_db", get_db)
    scope = {"mcpgateway.oauth_validation_request": object()}
    monkeypatch.setattr(transport, "mcp_app", SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(scope=scope))))
    context = {"auth_method": "oauth_access_token", "oauth_server_id": server.id, "oauth_config_generation": "current"}
    token = transport._oauth_validated_context_var.set(None)
    try:
        await transport._validate_server_oauth_context(server.id, context)
        await transport._validate_server_oauth_context(server.id, context)
        assert proxy.execute.call_count == 1
        scope["mcpgateway.oauth_validation_request"] = object()
        await transport._validate_server_oauth_context(server.id, context)
        assert proxy.execute.call_count == 2
        scope.clear()
        await transport._validate_server_oauth_context(server.id, context)
        await transport._validate_server_oauth_context(server.id, context)
        assert proxy.execute.call_count == 4
        transport.mcp_app.request_context.request = None
        await transport._validate_server_oauth_context(server.id, context)
        await transport._validate_server_oauth_context(server.id, context)
        assert proxy.execute.call_count == 6
    finally:
        transport._oauth_validated_context_var.reset(token)


def test_invalid_issuer_warning_omits_url_secrets(caplog):
    """Rejected issuer warnings cannot expose credentials, query tokens, or injected log lines."""
    rejected = "ftp://user:password@example.com/path?token=sensitive\nspoofed"  # pragma: allowlist secret
    assert resolve_server_oauth_issuers({"authorization_servers": [rejected]}) == []
    assert "Ignoring invalid OAuth authorization server" in caplog.text
    assert all(value not in caplog.text for value in ("password", "sensitive", "spoofed"))


def test_pending_configuration_suppresses_protected_resource_metadata(approval_db, approval_service):
    """Public OAuth metadata excludes an issuer that still requires administrator approval."""
    server = Server(name="pending", enabled=True, visibility="public", oauth_enabled=True, oauth_config=CONFIG)
    approval_db.add(server)
    approval_db.commit()
    with pytest.raises(ServerError, match="requires administrator approval"):
        approval_service.get_oauth_protected_resource_metadata(approval_db, server.id, "https://gateway.example.com/mcp")


@pytest.mark.asyncio
async def test_metadata_edits_preserve_approval_and_oauth_generation(approval_db, approval_service):
    """Unrelated edits preserve pending or approved OAuth trust state."""
    created = await approval_service.register_server(approval_db, ServerCreate(name="trusted", oauth_enabled=True, oauth_config=CONFIG), oauth_authorized=True)
    stored = approval_db.get(Server, created.id)
    generation = stored.oauth_config_generation
    await approval_service.update_server(approval_db, stored.id, ServerUpdate(description="metadata"), user_email="")
    assert stored.oauth_config_approved is True
    assert stored.oauth_config_generation == generation
    stored.oauth_config_approved = False
    approval_db.commit()
    await approval_service.update_server(approval_db, stored.id, ServerUpdate(description="another edit"), user_email="")
    assert stored.oauth_config_approved is False
    assert stored.oauth_config_generation == generation


@pytest.mark.asyncio
async def test_config_replacement_and_disable_invalidate_sessions(approval_db, approval_service):
    """OAuth configuration saves invalidate old session generations while metadata edits preserve them."""
    created = await approval_service.register_server(approval_db, ServerCreate(name="trusted", oauth_enabled=True, oauth_config=CONFIG), oauth_authorized=True)
    server = approval_db.get(Server, created.id)
    context = {"auth_method": "oauth_access_token", "oauth_server_id": server.id, "oauth_config_generation": server.oauth_config_generation}
    assert server_oauth_context_is_current(approval_db, context, server.id)
    await approval_service.update_server(approval_db, server.id, ServerUpdate(oauth_config={**CONFIG, "audience": "replacement"}), user_email="", oauth_authorized=True)
    assert server.oauth_config_approved is True
    assert not server_oauth_context_is_current(approval_db, context, server.id)
    await approval_service.update_server(approval_db, server.id, ServerUpdate(oauth_enabled=False), user_email="", oauth_authorized=True)
    assert server.oauth_config_approved is False
    assert server.oauth_config is None


@pytest.mark.asyncio
async def test_unapproved_issuer_fails_before_claim_verification(monkeypatch):
    """Pending issuers cannot verify claims or resolve a local administrator."""
    server = SimpleNamespace(oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=False, oauth_config_generation=None)
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = server

    @asynccontextmanager
    async def get_db():
        yield db

    monkeypatch.setattr(transport, "get_db", get_db)
    verify = AsyncMock()
    monkeypatch.setattr(transport, "verify_oauth_access_token", verify)
    user_lookup = MagicMock()
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", user_lookup)
    send = AsyncMock()
    handler = transport._StreamableHttpAuthHandler({"path": "/servers/pending/mcp", "type": "http", "headers": []}, AsyncMock(), send)
    result = await handler._try_oauth_access_token("forged-token", {"iss": "https://issuer.example.com", "email": "admin@example.com"})
    assert result is transport.OAuthAuthResult.FAILED
    assert send.call_args_list[0].args[0]["status"] == 503
    verify.assert_not_awaited()
    user_lookup.assert_not_called()


@pytest.mark.asyncio
async def test_pending_server_preserves_independent_issuer_authentication(monkeypatch):
    """An unmatched issuer retains independent trusted-provider verification."""
    server = SimpleNamespace(oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=False, oauth_config_generation=None)
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = server

    @asynccontextmanager
    async def get_db():
        yield db

    monkeypatch.setattr(transport, "get_db", get_db)
    send = AsyncMock()
    handler = transport._StreamableHttpAuthHandler({"path": "/servers/pending/mcp", "type": "http", "headers": []}, AsyncMock(), send)
    result = await handler._try_oauth_access_token("independent-token", {"iss": "https://trusted-sso.example.com"})
    assert result is transport.OAuthAuthResult.NOT_APPLICABLE
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_cached_authenticated_context_cannot_bypass_reapproval(approval_db, monkeypatch):
    """Cached authenticated contexts recheck current approval before dispatch."""
    server = Server(name="pending", oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=False, oauth_config_generation="old")
    approval_db.add(server)
    approval_db.commit()

    @asynccontextmanager
    async def get_db():
        yield approval_db

    monkeypatch.setattr(transport, "get_db", get_db)
    context = {"is_authenticated": True, "auth_method": "oauth_access_token", "oauth_server_id": server.id, "oauth_config_generation": "old"}
    cache_token = transport._oauth_checked_var.set(True)
    try:
        with pytest.raises(HTTPException) as error:
            await transport._check_server_oauth_enforcement(server.id, context)
        assert error.value.status_code == 401
    finally:
        transport._oauth_checked_var.reset(cache_token)


@pytest.mark.asyncio
async def test_session_approval_lookup_failure_fails_closed(monkeypatch):
    """An unavailable approval database blocks OAuth session restoration."""
    from sqlalchemy.exc import SQLAlchemyError

    @asynccontextmanager
    async def get_db():
        raise SQLAlchemyError("unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(transport, "get_db", get_db)
    with pytest.raises(HTTPException) as error:
        await transport._validate_server_oauth_context("server-id", {"auth_method": "oauth_access_token", "oauth_server_id": "server-id", "oauth_config_generation": "current"})
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_configuration_replacement_during_verification_clears_identity(monkeypatch):
    """A configuration change during verification removes the stale authenticated identity."""
    server = SimpleNamespace(oauth_enabled=True, oauth_config={**CONFIG, "resource": "audience"}, oauth_config_approved=True, oauth_config_generation="old")
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = server

    @asynccontextmanager
    async def get_db():
        yield db

    monkeypatch.setattr(transport, "get_db", get_db)
    monkeypatch.setattr(transport, "verify_oauth_access_token", AsyncMock(return_value={"email": "user@example.com"}))
    monkeypatch.setattr(transport, "_persist_learned_server_audience", MagicMock())
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", MagicMock(return_value=SimpleNamespace(is_active=True, is_admin=False)))
    monkeypatch.setattr("mcpgateway.auth._resolve_teams_from_db", AsyncMock(return_value=["team"]))
    monkeypatch.setattr(transport, "_validate_server_oauth_context", AsyncMock(side_effect=HTTPException(status_code=401, detail="Configuration changed")))
    send = AsyncMock()
    handler = transport._StreamableHttpAuthHandler({"path": "/servers/pending/mcp", "type": "http", "headers": []}, AsyncMock(), send)
    context_token = transport.user_context_var.set({})
    try:
        result = await handler._try_oauth_access_token("verified-token", {"iss": "https://issuer.example.com"})
        assert result is transport.OAuthAuthResult.FAILED
        assert transport.user_context_var.get() == {}
        assert send.call_args_list[0].args[0]["status"] == 401
    finally:
        transport.user_context_var.reset(context_token)


@pytest.mark.parametrize("approved,generation", [(False, "current"), (True, "superseded"), (True, None)])
def test_audience_learning_never_updates_unapproved_or_superseded_config(approval_db, approved, generation):
    """Audience learning requires the same still-approved configuration generation."""
    server = Server(name="pending", oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=approved, oauth_config_generation="current")
    approval_db.add(server)
    approval_db.commit()
    transport._persist_learned_server_audience(server.id, {"aud": "learned"}, approval_db, generation=generation)
    approval_db.refresh(server)
    assert server.oauth_config == CONFIG
    assert server.oauth_config_approved is approved


def test_audience_learning_preserves_approved_generation(approval_db):
    """Approved audience learning preserves configuration approval and session generation."""
    server = Server(name="trusted", oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=True, oauth_config_generation="current")
    approval_db.add(server)
    approval_db.commit()
    transport._persist_learned_server_audience(server.id, {"aud": "learned"}, approval_db, generation="current")
    approval_db.refresh(server)
    assert server.oauth_config["resource"] == "learned"
    assert server.oauth_config_approved is True
    assert server.oauth_config_generation == "current"


@pytest.mark.parametrize("approved", [False, True])
def test_initialize_capability_advertises_only_approved_issuers(approval_db, monkeypatch, approved):
    """MCP initialization advertises an issuer only after administrator approval."""
    server = Server(name="trusted", oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=approved, oauth_config_generation="current")
    approval_db.add(server)
    approval_db.commit()
    proxy = MagicMock()
    proxy.get.return_value = server
    monkeypatch.setattr("mcpgateway.db.SessionLocal", lambda: proxy)
    registry = SessionRegistry(backend="memory")
    result = registry._get_oauth_experimental_config(server.id)
    assert (result is not None) is approved
    if approved:
        assert result["oauth"]["authorization_servers"] == CONFIG["authorization_servers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("generation", [None, "old", "current"])
async def test_affinity_rpc_revalidates_forwarded_oauth_generation(approval_db, monkeypatch, generation):
    """Trusted affinity dispatch rejects legacy or superseded OAuth contexts before RPC execution."""
    # First-Party
    from mcpgateway import main

    server = Server(name="trusted", oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=True, oauth_config_generation="current")
    approval_db.add(server)
    approval_db.commit()
    context = {"auth_method": "oauth_access_token", "oauth_server_id": server.id, "oauth_config_generation": generation}
    request = SimpleNamespace(state=SimpleNamespace(_mcp_internal_auth_context=context))
    monkeypatch.setattr(main, "_build_internal_mcp_forwarded_user", lambda _request: {"email": "admin@example.com"})
    proxy = MagicMock(wraps=approval_db)
    proxy.is_active = False
    proxy.close = MagicMock()
    monkeypatch.setattr(main, "SessionLocal", lambda: proxy)
    dispatch = AsyncMock(return_value={"result": {}})
    monkeypatch.setattr(main, "_handle_rpc_authenticated", dispatch)
    if generation == "current":
        await main.handle_internal_mcp_rpc(request)
        dispatch.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as error:
            await main.handle_internal_mcp_rpc(request)
        assert error.value.status_code == 401
        dispatch.assert_not_awaited()


def test_concurrent_audience_learning_keeps_first_resource(approval_db):
    """A stale learning snapshot cannot overwrite the first resource in the same generation."""
    server = Server(name="trusted", oauth_enabled=True, oauth_config={**CONFIG, "resource": "first"}, oauth_config_approved=True, oauth_config_generation="current", version=2)
    approval_db.add(server)
    approval_db.commit()
    stale = SimpleNamespace(id=server.id, oauth_enabled=True, oauth_config=dict(CONFIG), oauth_config_approved=True, oauth_config_generation="current", version=1)
    proxy = MagicMock()
    selected = MagicMock()
    selected.scalar_one_or_none.return_value = stale
    proxy.execute.side_effect = lambda statement: selected if statement.is_select else approval_db.execute(statement)
    proxy.commit.side_effect = approval_db.commit
    transport._persist_learned_server_audience(server.id, {"aud": "second"}, proxy, generation="current")
    approval_db.refresh(server)
    assert server.oauth_config["resource"] == "first"
    assert server.version == 2


@pytest.mark.asyncio
async def test_audience_learning_invalidates_stale_review(approval_db, approval_service):
    """Learning changes the reviewed version without invalidating the OAuth generation."""
    server = Server(name="trusted", oauth_enabled=True, oauth_config=CONFIG, oauth_config_approved=True, oauth_config_generation="current", version=1)
    approval_db.add(server)
    approval_db.commit()
    transport._persist_learned_server_audience(server.id, {"aud": "learned"}, approval_db, generation="current")
    approval_db.refresh(server)
    assert server.version == 2
    with pytest.raises(ServerLockConflictError):
        await approval_service.approve_oauth_config(approval_db, server.id, 1, user_id="reviewer@example.com")


def test_approval_migration_round_trip():
    """Migration preserves old settings and requires approval after every upgrade."""
    migration = importlib.import_module("mcpgateway.alembic.versions.b7e291a4c630_require_server_oauth_approval")
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    servers = sa.Table("servers", metadata, sa.Column("id", sa.String(), primary_key=True), sa.Column("oauth_enabled", sa.Boolean()), sa.Column("oauth_config", sa.JSON()))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(servers.insert().values(id="existing", oauth_enabled=True, oauth_config=CONFIG))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
            row = connection.execute(sa.text("SELECT oauth_config_approved, oauth_config_generation FROM servers")).one()
            assert not row[0]
            assert row[1] is None
            migration.downgrade()
            migration.upgrade()
            assert connection.execute(sa.select(servers.c.oauth_config)).scalar_one() == CONFIG
            assert not connection.execute(sa.text("SELECT oauth_config_approved FROM servers")).scalar_one()
    engine.dispose()
