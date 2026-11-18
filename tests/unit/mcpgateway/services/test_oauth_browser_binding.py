# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oauth_browser_binding.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify downstream OAuth transaction binding and single consumption.
"""

# Standard
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
import pytest

# First-Party
import mcpgateway.services.oauth_manager as oauth_module
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", [None, "wrong", "a" * 129])
async def test_binding_denials_consume_state(monkeypatch, binding):
    """Reject another browser before any exchange and prevent replay."""
    monkeypatch.setattr(oauth_module, "get_settings", lambda: SimpleNamespace(cache_type="memory"))
    manager = OAuthManager()
    await manager._store_authorization_state("gw", "state", browser_binding_hash=hashlib.sha256(b"right").hexdigest())
    with pytest.raises(OAuthError):
        await manager.consume_and_validate_authorization_state("gw", "state", binding)
    with pytest.raises(OAuthError):
        await manager.consume_and_validate_authorization_state("gw", "state", "right")


@pytest.mark.asyncio
async def test_same_browser_and_legacy_state(monkeypatch):
    """Accept a matching browser once and reject transactions without binding."""
    monkeypatch.setattr(oauth_module, "get_settings", lambda: SimpleNamespace(cache_type="memory"))
    manager = OAuthManager()
    await manager._store_authorization_state("gw", "valid", app_user_email="owner@example.test", browser_binding_hash=hashlib.sha256(b"right").hexdigest())
    context = await manager.consume_and_validate_authorization_state("gw", "valid", "right")
    assert context["app_user_email"] == "owner@example.test"
    with pytest.raises(OAuthError):
        await manager.consume_and_validate_authorization_state("gw", "valid", "right")
    await manager._store_authorization_state("gw", "legacy")
    with pytest.raises(OAuthError):
        await manager.consume_and_validate_authorization_state("gw", "legacy", "right")


@pytest.mark.asyncio
@pytest.mark.parametrize("code,error", [("code", None), (None, "access_denied"), (None, None)])
async def test_callback_rejects_cross_browser_before_discovery(monkeypatch, code, error):
    """Reject all unbound callback branches and clear their final response cookie."""
    # Third-Party
    from starlette.requests import Request

    # First-Party
    from mcpgateway.routers.oauth_router import _binding_cookie_name, oauth_callback

    monkeypatch.setattr(oauth_module, "get_settings", lambda: SimpleNamespace(cache_type="memory"))
    manager = OAuthManager()
    await manager._store_authorization_state("gw", "state", browser_binding_hash=hashlib.sha256(b"right").hexdigest())
    gateway = Mock(oauth_config={"client_id": "binding-client", "token_url": "https://provider.example/token"})
    db = Mock()
    db.execute.return_value.scalar_one_or_none.return_value = gateway
    request = Request({"type": "http", "method": "GET", "scheme": "https", "path": "/oauth/callback", "root_path": "", "query_string": b"", "headers": []})
    discovery = AsyncMock()
    exchange = AsyncMock()
    storage = Mock()
    monkeypatch.setattr(OAuthManager, "validate_authorization_response_issuer", discovery)
    monkeypatch.setattr(OAuthManager, "_exchange_code_for_tokens", exchange)
    monkeypatch.setattr("mcpgateway.routers.oauth_router.TokenStorageService", storage)
    response = await oauth_callback(request=request, code=code, state="state", error=error, error_description=None, iss=None, db=db)
    discovery.assert_not_awaited()
    exchange.assert_not_awaited()
    storage.assert_not_called()
    assert response.status_code == 400
    assert _binding_cookie_name("state") in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert "Domain=" not in response.headers["set-cookie"]
    assert await manager._validate_and_retrieve_state("gw", "state") is None


def _claim_in_worker(database_url, barrier, results, atomic_claim):
    """Attempt one transaction claim from an independent worker and database session."""
    # Standard
    import asyncio
    from contextlib import nullcontext

    # Third-Party
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Query, sessionmaker

    # First-Party
    import mcpgateway.db as database

    engine = create_engine(database_url)
    factory = sessionmaker(bind=engine)

    def get_db():
        with factory() as session:
            yield session

    database.get_db = get_db
    # Third-Party
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    oauth_module.get_settings = lambda: SimpleNamespace(cache_type="database")

    def synchronize_read(execution):
        """Let both workers read the transaction before either claims it."""
        if execution.is_select:
            result = execution.invoke_statement().freeze()
            barrier.wait(timeout=10)
            return result()
        return execution.invoke_statement()

    event.listen(Session, "do_orm_execute", synchronize_read, retval=True)
    try:
        with nullcontext() if atomic_claim else patch.object(Query, "update", return_value=1):
            asyncio.run(OAuthManager().consume_and_validate_authorization_state("gw", "shared", "right"))
        results.put(True)
    except OAuthError:
        results.put(False)
    finally:
        engine.dispose()


@pytest.mark.parametrize("atomic_claim", [True, False], ids=["atomic", "non-atomic-control"])
def test_database_claim_across_workers(tmp_path, atomic_claim):
    """Require one atomic winner and demonstrate duplicate consumption without the claim."""
    # Standard
    from datetime import datetime, timedelta, timezone
    import multiprocessing

    # Third-Party
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    # First-Party
    from mcpgateway.db import OAuthState

    url = f"sqlite:///{tmp_path / 'states.db'}"
    engine = create_engine(url)
    OAuthState.__table__.create(engine)
    with Session(engine) as session:
        session.add(OAuthState(gateway_id="gw", state="shared", expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), browser_binding_hash=hashlib.sha256(b"right").hexdigest()))
        session.commit()
    engine.dispose()
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    workers = [context.Process(target=_claim_in_worker, args=(url, barrier, results, atomic_claim)) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        assert sorted(results.get(timeout=20) for _ in workers) == ([False, True] if atomic_claim else [True, True])
        for worker in workers:
            worker.join(timeout=10)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join()
        results.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_error", [None, "access_denied"])
async def test_issuer_failure_consumes_state_before_exchange(monkeypatch, provider_error):
    """Consume bound success and provider-error transactions before issuer validation."""
    # Third-Party
    from starlette.requests import Request

    # First-Party
    from mcpgateway.routers.oauth_router import _binding_cookie_name, oauth_callback

    monkeypatch.setattr(oauth_module, "get_settings", lambda: SimpleNamespace(cache_type="memory"))
    state = "popup.bound-state"
    manager = OAuthManager()
    await manager._store_authorization_state("gw", state, app_user_email="owner@example.com", browser_binding_hash=hashlib.sha256(b"right").hexdigest())
    gateway = Mock(
        url="https://upstream.example/mcp",
        ca_certificate=None,
        client_cert=None,
        client_key=None,
        oauth_config={"client_id": "binding-client", "token_url": "https://provider.example/token", "issuer": "https://provider.example"},
    )
    db = Mock()
    db.execute.return_value.scalar_one_or_none.return_value = gateway
    request = Request(
        {"type": "http", "method": "GET", "scheme": "https", "path": "/oauth/callback", "root_path": "", "query_string": b"", "headers": [(b"cookie", f"{_binding_cookie_name(state)}=right".encode())]}
    )
    discovery = AsyncMock(side_effect=OAuthError("issuer mismatch", error_code="issuer_mismatch"))
    exchange = AsyncMock()
    storage = Mock()
    monkeypatch.setattr(OAuthManager, "validate_authorization_response_issuer", discovery)
    monkeypatch.setattr(OAuthManager, "_exchange_code_for_tokens", exchange)
    monkeypatch.setattr("mcpgateway.routers.oauth_router.TokenStorageService", storage)
    response = await oauth_callback(request=request, code=None if provider_error else "code", state=state, error=provider_error, error_description=None, iss="https://other.example", db=db)
    assert response.status_code == 400
    discovery.assert_awaited_once()
    exchange.assert_not_awaited()
    storage.assert_not_called()
    assert await manager._validate_and_retrieve_state("gw", state) is None
    assert "Max-Age=0" in response.headers["set-cookie"]
