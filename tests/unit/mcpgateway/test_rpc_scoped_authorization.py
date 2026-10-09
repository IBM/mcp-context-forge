# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_rpc_scoped_authorization.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Authenticated integration coverage for scoped public ``/rpc`` tool calls.
"""

# Standard
from datetime import datetime, timezone
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.auth as auth_mod
import mcpgateway.db as db_mod
import mcpgateway.main as main_mod
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailTeamMember, EmailUser, Gateway, Role, Server, UserRole
from tests.helpers.auth import make_auth_headers, make_test_jwt


CALLER_EMAIL = "rpc-scoped-caller@example.com"
OWNER_EMAIL = "rpc-scoped-owner@example.com"
TEAM_A_ID = "rpc-scoped-team-a"
TEAM_B_ID = "rpc-scoped-team-b"
SERVER_A_ID = "rpc-scoped-server-a"
SERVER_B_ID = "rpc-scoped-server-b"
DIRECT_GATEWAY_ID = "rpc-scoped-direct-gateway"


def _rpc_body(server_id: str, *, request_id: str = "scoped-authz") -> dict:
    """Build a scoped tools/call request."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": "qualified-tool", "server_id": server_id, "arguments": {}},
    }


def _legacy_rpc_body(server_id: str, *, request_id: str = "legacy-scoped-authz") -> dict:
    """Build a scoped legacy direct-method tool request."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "qualified-tool",
        "params": {"server_id": server_id, "query": "cloudflare"},
    }


def _token(*, permissions: list[str], teams: list[str] | None = None, server_id: str | None = None) -> str:
    """Mint an API-token JWT with real team and permission scopes."""
    scopes: dict[str, object] = {"permissions": permissions}
    if server_id is not None:
        scopes["server_id"] = server_id
    return make_test_jwt(
        CALLER_EMAIL,
        teams=[TEAM_A_ID] if teams is None else teams,
        scopes=scopes,
        auth_provider="api_token",
        include_user_data=True,
        extra_payload={"jti": uuid.uuid4().hex, "token_use": "api"},
    )


@pytest.fixture
def scoped_rpc_client():
    """Run the application against a real temporary RBAC and server database."""
    # Third-Party
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database_url = f"sqlite:///{path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    mp.setattr(settings, "database_url", database_url, raising=False)
    mp.setattr(settings, "auth_required", True)
    mp.setattr(settings, "mcp_client_auth_enabled", True)
    mp.setattr(settings, "require_user_in_db", True)
    mp.setattr(settings, "auth_cache_enabled", False)
    mp.setattr(settings, "auth_cache_batch_queries", False)
    mp.setattr(settings, "permission_audit_enabled", False)
    mp.setattr(settings, "mcpgateway_direct_proxy_enabled", True)

    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", test_session_local, raising=False)
    mp.setattr(main_mod, "SessionLocal", test_session_local, raising=False)
    mp.setattr(auth_mod, "SessionLocal", test_session_local, raising=False)

    # These modules import SessionLocal directly and may run from middleware.
    import mcpgateway.middleware.auth_middleware as auth_middleware_mod
    import mcpgateway.services.audit_trail_service as audit_trail_mod
    import mcpgateway.services.log_aggregator as log_aggregator_mod
    import mcpgateway.services.security_logger as security_logger_mod
    import mcpgateway.services.structured_logger as structured_logger_mod

    for module in (auth_middleware_mod, audit_trail_mod, log_aggregator_mod, security_logger_mod, structured_logger_mod):
        mp.setattr(module, "SessionLocal", test_session_local, raising=False)

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = test_session_local()
        try:
            yield db
        finally:
            db.close()

    from mcpgateway.db import get_db as db_get_db
    from mcpgateway.middleware.rbac import get_db as rbac_get_db
    from mcpgateway.routers.auth import get_db as auth_get_db

    main_mod.app.dependency_overrides[db_get_db] = override_get_db
    main_mod.app.dependency_overrides[rbac_get_db] = override_get_db
    main_mod.app.dependency_overrides[auth_get_db] = override_get_db

    now = datetime.now(timezone.utc)
    with test_session_local() as db:
        caller = EmailUser(
            email=CALLER_EMAIL,
            full_name="Scoped RPC Caller",
            is_admin=False,
            is_active=True,
            auth_provider="api_token",
            email_verified_at=now,
        )
        owner = EmailUser(
            email=OWNER_EMAIL,
            full_name="Scoped RPC Owner",
            is_admin=False,
            is_active=True,
            auth_provider="local",
            email_verified_at=now,
        )
        db.add_all([caller, owner])
        db.flush()

        db.add_all(
            [
                EmailTeam(id=TEAM_A_ID, name="Scoped RPC Team A", slug=f"rpc-team-a-{uuid.uuid4().hex}", created_by=OWNER_EMAIL, visibility="private"),
                EmailTeam(id=TEAM_B_ID, name="Scoped RPC Team B", slug=f"rpc-team-b-{uuid.uuid4().hex}", created_by=OWNER_EMAIL, visibility="private"),
            ]
        )
        db.flush()
        db.add(EmailTeamMember(team_id=TEAM_A_ID, user_email=CALLER_EMAIL, role="member", invited_by=OWNER_EMAIL, is_active=True))

        role = Role(
            name=f"rpc-scoped-executor-{uuid.uuid4().hex}",
            scope="team",
            permissions=["servers.use", "tools.execute"],
            created_by=OWNER_EMAIL,
            is_active=True,
        )
        db.add(role)
        db.flush()
        db.add(UserRole(user_email=CALLER_EMAIL, role_id=role.id, scope="team", scope_id=TEAM_A_ID, granted_by=OWNER_EMAIL, is_active=True))
        db.add_all(
            [
                Server(id=SERVER_A_ID, name="Scoped RPC Server A", team_id=TEAM_A_ID, owner_email=OWNER_EMAIL, visibility="team", enabled=True, tags=[]),
                Server(id=SERVER_B_ID, name="Scoped RPC Server B", team_id=TEAM_B_ID, owner_email=OWNER_EMAIL, visibility="team", enabled=True, tags=[]),
                Gateway(
                    id=DIRECT_GATEWAY_ID,
                    name="Scoped RPC Direct Gateway",
                    slug=f"rpc-direct-gateway-{uuid.uuid4().hex}",
                    url="http://direct-gateway.example/mcp",
                    capabilities={},
                    gateway_mode="direct_proxy",
                    visibility="public",
                    owner_email=OWNER_EMAIL,
                ),
            ]
        )
        db.commit()

    client = TestClient(main_mod.app)
    yield client

    client.close()
    main_mod.app.dependency_overrides.pop(db_get_db, None)
    main_mod.app.dependency_overrides.pop(rbac_get_db, None)
    main_mod.app.dependency_overrides.pop(auth_get_db, None)
    mp.undo()
    engine.dispose()
    os.unlink(path)


def _assert_not_dispatched(forward_request: AsyncMock, execute_call: AsyncMock) -> None:
    """Assert authorization stopped the request before routing or execution."""
    forward_request.assert_not_awaited()
    execute_call.assert_not_awaited()


def test_scoped_rpc_requires_authentication(scoped_rpc_client: TestClient) -> None:
    """Unauthenticated public RPC calls must be rejected before dispatch."""
    with (
        patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new_callable=AsyncMock) as forward_request,
        patch("mcpgateway.main._execute_rpc_tools_call", new_callable=AsyncMock) as execute_call,
    ):
        response = scoped_rpc_client.post("/rpc", json=_rpc_body(SERVER_A_ID))

    assert response.status_code == 401
    _assert_not_dispatched(forward_request, execute_call)


@pytest.mark.parametrize(
    ("permissions", "required_permission", "expected_status", "expected_code"),
    [
        (["tools.read"], "tools.execute", 200, -32003),
        (["servers.read"], "servers.use", 403, None),
    ],
    ids=["missing-tools-execute", "missing-servers-use"],
)
def test_scoped_rpc_enforces_token_permission_caps(
    scoped_rpc_client: TestClient,
    permissions: list[str],
    required_permission: str,
    expected_status: int,
    expected_code: int | None,
) -> None:
    """Token scopes must grant transport use and method execution."""
    with (
        patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new_callable=AsyncMock) as forward_request,
        patch("mcpgateway.main._execute_rpc_tools_call", new_callable=AsyncMock) as execute_call,
    ):
        response = scoped_rpc_client.post(
            "/rpc",
            headers=make_auth_headers(_token(permissions=permissions)),
            json=_rpc_body(SERVER_A_ID, request_id=required_permission),
        )

    assert response.status_code == expected_status
    if expected_code is not None:
        assert response.json()["error"]["code"] == expected_code
    _assert_not_dispatched(forward_request, execute_call)


def test_scoped_rpc_rejects_server_scoped_token_mismatch(scoped_rpc_client: TestClient) -> None:
    """A token bound to one server cannot select another server."""
    with (
        patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new_callable=AsyncMock) as forward_request,
        patch("mcpgateway.main._execute_rpc_tools_call", new_callable=AsyncMock) as execute_call,
    ):
        response = scoped_rpc_client.post(
            "/rpc",
            headers=make_auth_headers(_token(permissions=["tools.execute"], server_id=SERVER_A_ID)),
            json=_rpc_body(SERVER_B_ID),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == -32003
    _assert_not_dispatched(forward_request, execute_call)


def test_scoped_rpc_hides_inaccessible_and_missing_servers_equally(scoped_rpc_client: TestClient) -> None:
    """Wrong-team and unknown servers must expose the same generic error shape."""
    responses = []
    normalized_errors = []
    with (
        patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new_callable=AsyncMock) as forward_request,
        patch("mcpgateway.main._execute_rpc_tools_call", new_callable=AsyncMock) as execute_call,
    ):
        for server_id in (SERVER_B_ID, "rpc-scoped-missing"):
            responses.append(
                scoped_rpc_client.post(
                    "/rpc",
                    headers=make_auth_headers(_token(permissions=["tools.execute"])),
                    json=_rpc_body(server_id, request_id=server_id),
                )
            )

    for response, server_id in zip(responses, (SERVER_B_ID, "rpc-scoped-missing")):
        assert response.status_code == 200
        error = response.json()["error"]
        assert error == {"code": -32002, "message": f"Server not found: {server_id}", "data": {"server_id": server_id}}
        normalized_errors.append({"code": error["code"], "message": error["message"].replace(server_id, "<server>"), "data": {"server_id": "<server>"}})
    assert normalized_errors[0] == normalized_errors[1]
    _assert_not_dispatched(forward_request, execute_call)


def test_public_rpc_cannot_forge_internal_runtime_scope(scoped_rpc_client: TestClient) -> None:
    """Untrusted runtime headers cannot replace the public request's server scope."""
    forged_headers = {
        "x-contextforge-mcp-runtime": "rust",
        "x-contextforge-server-id": SERVER_A_ID,
        "x-contextforge-mcp-runtime-auth": "forged",  # pragma: allowlist secret
        "x-contextforge-auth-context": "forged",
    }
    with (
        patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new_callable=AsyncMock) as forward_request,
        patch("mcpgateway.main._execute_rpc_tools_call", new_callable=AsyncMock) as execute_call,
    ):
        response = scoped_rpc_client.post(
            "/rpc",
            headers=make_auth_headers(_token(permissions=["tools.execute"]), extra_headers=forged_headers),
            json=_rpc_body(SERVER_B_ID),
        )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32002
    _assert_not_dispatched(forward_request, execute_call)


def test_public_rpc_rejects_gateway_routing_override_with_server_scope(scoped_rpc_client: TestClient) -> None:
    """A public routing header cannot bypass virtual-server tool membership."""
    with (
        patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new_callable=AsyncMock, return_value=None) as forward_request,
        patch("mcpgateway.services.tool_service.mcp_proxy_client") as proxy_client,
        patch.object(main_mod.tool_service, "_select_invocable_tool", new_callable=AsyncMock) as select_tool,
    ):
        response = scoped_rpc_client.post(
            "/rpc",
            headers=make_auth_headers(
                _token(permissions=["tools.execute"]),
                extra_headers={"x-context-forge-gateway-id": DIRECT_GATEWAY_ID},
            ),
            json=_rpc_body(SERVER_A_ID, request_id="gateway-routing-override"),
        )

    assert response.status_code == 200
    assert response.json()["error"] == {"code": -32601, "message": "Tool not found: qualified-tool"}
    forward_request.assert_awaited_once()
    select_tool.assert_not_awaited()
    proxy_client.assert_not_called()


def test_scoped_rpc_allows_authorized_server(scoped_rpc_client: TestClient) -> None:
    """A correctly scoped caller reaches execution after every auth layer passes."""
    with (
        patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new_callable=AsyncMock, return_value=None) as forward_request,
        patch("mcpgateway.main._execute_rpc_tools_call", new_callable=AsyncMock, return_value={"content": []}) as execute_call,
    ):
        response = scoped_rpc_client.post(
            "/rpc",
            headers=make_auth_headers(_token(permissions=["tools.execute"])),
            json=_rpc_body(SERVER_A_ID),
        )

    assert response.status_code == 200
    assert response.json()["result"] == {"content": []}
    forward_request.assert_awaited_once()
    execute_call.assert_awaited_once()


def test_legacy_scoped_rpc_hides_inaccessible_and_missing_servers_equally(scoped_rpc_client: TestClient) -> None:
    """Legacy direct-method calls enforce the same server non-disclosure policy."""
    responses = []
    normalized_errors = []
    with (
        patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new_callable=AsyncMock, return_value=None) as forward_request,
        patch.object(main_mod.tool_service, "invoke_tool", new_callable=AsyncMock) as invoke_tool,
    ):
        for server_id in (SERVER_B_ID, "rpc-scoped-missing"):
            responses.append(
                scoped_rpc_client.post(
                    "/rpc",
                    headers=make_auth_headers(_token(permissions=["tools.execute"])),
                    json=_legacy_rpc_body(server_id, request_id=f"legacy-{server_id}"),
                )
            )

    for response, server_id in zip(responses, (SERVER_B_ID, "rpc-scoped-missing")):
        assert response.status_code == 200
        error = response.json()["error"]
        assert error == {"code": -32002, "message": f"Server not found: {server_id}", "data": {"server_id": server_id}}
        normalized_errors.append({"code": error["code"], "message": error["message"].replace(server_id, "<server>"), "data": {"server_id": "<server>"}})
    assert normalized_errors[0] == normalized_errors[1]
    assert forward_request.await_count == 2
    invoke_tool.assert_not_awaited()


def test_legacy_scoped_rpc_allows_authorized_server(scoped_rpc_client: TestClient) -> None:
    """An accessible server still reaches legacy direct-method tool invocation."""
    with (
        patch("mcpgateway.main._maybe_forward_affinitized_rpc_request", new_callable=AsyncMock, return_value=None) as forward_request,
        patch.object(main_mod.tool_service, "invoke_tool", new_callable=AsyncMock, return_value={"content": []}) as invoke_tool,
    ):
        response = scoped_rpc_client.post(
            "/rpc",
            headers=make_auth_headers(_token(permissions=["tools.execute"])),
            json=_legacy_rpc_body(SERVER_A_ID),
        )

    assert response.status_code == 200
    assert response.json()["result"] == {"content": []}
    forward_request.assert_awaited_once()
    invoke_tool.assert_awaited_once()
    assert invoke_tool.await_args.kwargs["name"] == "qualified-tool"
    assert invoke_tool.await_args.kwargs["server_id"] == SERVER_A_ID
