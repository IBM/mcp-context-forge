# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_a2a_gateway_e2e.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

End-to-end tests for the A2A Gateway Router.

Tests the full application stack with a real temporary SQLite database,
JWT authentication, RBAC role seeding, and mocked downstream agent HTTP calls.
Covers agent card discovery, JSON-RPC dispatch (message/send, tasks/get,
tasks/cancel, streaming, push notification config), error paths, and
access-control deny paths.
"""

# Standard
# CRITICAL: Set environment variables BEFORE any mcpgateway imports!
import os

os.environ["MCPGATEWAY_ADMIN_API_ENABLED"] = "true"
os.environ["MCPGATEWAY_UI_ENABLED"] = "false"
os.environ["MCPGATEWAY_A2A_ENABLED"] = "true"
os.environ["MCPGATEWAY_A2A_GATEWAY_ENABLED"] = "true"

# Standard
import datetime  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

# Third-Party
import jwt  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from sqlalchemy import select  # noqa: E402

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")


# -------------------------
# Test Configuration
# -------------------------
TEST_JWT_SECRET = "e2e-test-jwt-secret-key-with-minimum-32-bytes"


def create_test_jwt_token(email="admin@example.com", teams=None, is_admin=False):
    """Create a JWT token for E2E testing."""
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=60)
    payload = {
        "sub": email,
        "email": email,
        "iat": int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        "exp": int(expire.timestamp()),
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
    }
    if teams is not None:
        payload["teams"] = teams
    if is_admin:
        payload["is_admin"] = True
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


TEST_JWT_TOKEN = create_test_jwt_token(email="admin@example.com", teams=[], is_admin=True)
TEST_AUTH_HEADER = {"Authorization": f"Bearer {TEST_JWT_TOKEN}"}

# Local
from tests.utils.rbac_mocks import create_mock_email_user, create_mock_user_context  # noqa: E402

TEST_USER = create_mock_email_user(email="admin@example.com", full_name="Test Admin", is_admin=True, is_active=True)

# Route prefix from settings
from mcpgateway.config import settings  # noqa: E402

_PREFIX = f"/{settings.a2a_gateway_route_prefix.strip('/')}"


# -------------------------
# Fixtures
# -------------------------
@pytest_asyncio.fixture
async def client(app_with_temp_db):
    """Create an async test client with auth bypassed and RBAC seeded."""
    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.config import settings
    from mcpgateway.db import EmailUser, Role, UserRole, get_db
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.routers.a2a_gateway import get_db as a2a_get_db
    from mcpgateway.utils.create_jwt_token import get_jwt_token
    from mcpgateway.utils.verify_credentials import require_admin_auth

    # Override JWT secret
    original_jwt_secret = settings.jwt_secret_key
    if hasattr(original_jwt_secret, "get_secret_value"):
        settings.jwt_secret_key = SecretStr(TEST_JWT_SECRET)
    else:
        settings.jwt_secret_key = TEST_JWT_SECRET

    # Get test DB session
    test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
    if callable(test_db_dependency):
        test_db_gen = test_db_dependency()
        test_db_session = next(test_db_gen)
    else:
        test_db_session = test_db_dependency

    # Seed RBAC: EmailUser + platform_admin role + UserRole assignment
    if test_db_session.get(EmailUser, "admin@example.com") is None:
        test_db_session.add(
            EmailUser(
                email="admin@example.com",
                password_hash="not-a-real-hash",
                full_name="Test Admin",
                is_admin=True,
                is_active=True,
            )
        )
        test_db_session.commit()

    role = test_db_session.execute(select(Role).where(Role.name == "platform_admin", Role.scope == "global")).scalars().first()
    if role is None:
        role = Role(
            name="platform_admin",
            description="Test platform admin role",
            scope="global",
            permissions=["*"],
            created_by="admin@example.com",
            is_system_role=True,
            is_active=True,
        )
        test_db_session.add(role)
        test_db_session.commit()
        test_db_session.refresh(role)

    assignment = (
        test_db_session.execute(
            select(UserRole).where(
                UserRole.user_email == "admin@example.com",
                UserRole.role_id == role.id,
                UserRole.scope == "global",
                UserRole.scope_id.is_(None),
                UserRole.is_active.is_(True),
            )
        )
        .scalars()
        .first()
    )
    if assignment is None:
        test_db_session.add(
            UserRole(
                user_email="admin@example.com",
                role_id=role.id,
                scope="global",
                scope_id=None,
                granted_by="admin@example.com",
                is_active=True,
            )
        )
        test_db_session.commit()

    test_user_context = create_mock_user_context(email="admin@example.com", full_name="Test Admin", is_admin=True)
    test_user_context["db"] = test_db_session

    async def mock_require_admin_auth():
        return "admin@example.com"

    async def mock_get_jwt_token():
        return TEST_JWT_TOKEN

    # Override dependencies
    app_with_temp_db.dependency_overrides[get_current_user] = lambda: TEST_USER
    app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = lambda: test_user_context
    app_with_temp_db.dependency_overrides[require_admin_auth] = mock_require_admin_auth
    app_with_temp_db.dependency_overrides[get_jwt_token] = mock_get_jwt_token

    # Make the a2a_gateway router's get_db create fresh sessions from the patched SessionLocal.
    # resolve_agent() calls db.close() on the session, so each request needs its own session.
    import mcpgateway.db as db_mod

    def test_a2a_get_db():
        db = db_mod.SessionLocal()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app_with_temp_db.dependency_overrides[a2a_get_db] = test_a2a_get_db

    transport = ASGITransport(app=app_with_temp_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Cleanup
    app_with_temp_db.dependency_overrides.pop(get_current_user, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)
    app_with_temp_db.dependency_overrides.pop(require_admin_auth, None)
    app_with_temp_db.dependency_overrides.pop(get_jwt_token, None)
    app_with_temp_db.dependency_overrides.pop(a2a_get_db, None)
    settings.jwt_secret_key = original_jwt_secret


@pytest.fixture
def seed_agent(app_with_temp_db):
    """Seed a public A2A agent in the test database and return it.

    Note: The A2AAgent model has a before_insert event that overrides the slug
    with slugify(name). So the slug is always derived from the name. Pass unique
    names to avoid collisions.
    """
    import mcpgateway.db as db_mod
    from mcpgateway.db import A2AAgent
    from mcpgateway.utils.create_slug import slugify

    def _seed(
        name="Echo Agent",
        endpoint_url="https://downstream.example.com/a2a",
        enabled=True,
        visibility="public",
        capabilities=None,
        tags=None,
        auth_type=None,
        auth_value=None,
    ):
        expected_slug = slugify(name)
        db = db_mod.SessionLocal()
        try:
            # Check if already exists (slug is auto-generated from name)
            existing = db.execute(select(A2AAgent).where(A2AAgent.slug == expected_slug)).scalars().first()
            if existing:
                db.expunge(existing)
                return existing

            agent = A2AAgent(
                name=name,
                slug=expected_slug,
                description=f"Test agent: {name}",
                endpoint_url=endpoint_url,
                agent_type="jsonrpc",
                protocol_version="1.0",
                capabilities=capabilities or {"streaming": True, "pushNotifications": False},
                config={},
                auth_type=auth_type,
                auth_value=auth_value,
                enabled=enabled,
                reachable=True,
                tags=tags or ["test"],
                visibility=visibility,
                owner_email="admin@example.com",
            )
            db.add(agent)
            db.commit()
            db.refresh(agent)
            db.expunge(agent)
            return agent
        finally:
            db.close()

    return _seed


# -------------------------
# Agent Card Discovery
# -------------------------
class TestAgentCardDiscovery:
    """E2E tests for GET /{prefix}/{agent_id}/.well-known/agent-card.json."""

    @pytest.mark.asyncio
    async def test_agent_card_returns_valid_card(self, client, seed_agent):
        agent = seed_agent(name="Card Test Agent")

        response = await client.get(
            f"{_PREFIX}/{agent.id}/.well-known/agent-card.json",
            headers=TEST_AUTH_HEADER,
        )

        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "Card Test Agent"
        assert f"{_PREFIX}/{agent.id}" in card["url"]
        assert card["protocolVersion"] == "1.0"
        assert "capabilities" in card
        assert card["capabilities"]["streaming"] is True

    @pytest.mark.asyncio
    async def test_agent_card_not_found(self, client):
        response = await client.get(
            f"{_PREFIX}/nonexistent-id/.well-known/agent-card.json",
            headers=TEST_AUTH_HEADER,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_agent_card_disabled_agent(self, client, seed_agent):
        agent = seed_agent(name="Disabled Card Agent", enabled=False)

        response = await client.get(
            f"{_PREFIX}/{agent.id}/.well-known/agent-card.json",
            headers=TEST_AUTH_HEADER,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_agent_card_includes_tags_as_skills(self, client, seed_agent):
        agent = seed_agent(name="Tagged Skills Agent", tags=["math", "coding"])

        response = await client.get(
            f"{_PREFIX}/{agent.id}/.well-known/agent-card.json",
            headers=TEST_AUTH_HEADER,
        )

        assert response.status_code == 200
        card = response.json()
        assert len(card["skills"]) == 2
        skill_ids = [s["id"] for s in card["skills"]]
        assert "math" in skill_ids
        assert "coding" in skill_ids


# -------------------------
# Non-Streaming JSON-RPC
# -------------------------
class TestMessageSend:
    """E2E tests for message/send via POST /{prefix}/{agent_id}."""

    @pytest.mark.asyncio
    async def test_message_send_success(self, client, seed_agent):
        agent = seed_agent(name="Send Test Agent")

        downstream_response = {
            "jsonrpc": "2.0",
            "result": {
                "id": "task-abc",
                "status": {"state": "completed"},
                "artifacts": [{"parts": [{"kind": "text", "text": "Hello back!"}]}],
            },
            "id": 1,
        }

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = downstream_response

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_http_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_http_client):
            response = await client.post(
                f"{_PREFIX}/{agent.id}",
                json={
                    "jsonrpc": "2.0",
                    "method": "message/send",
                    "params": {
                        "message": {
                            "messageId": "msg-1",
                            "role": "user",
                            "parts": [{"kind": "text", "text": "Hello"}],
                        }
                    },
                    "id": 1,
                },
                headers=TEST_AUTH_HEADER,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["result"]["id"] == "task-abc"
        assert data["result"]["status"]["state"] == "completed"

    @pytest.mark.asyncio
    async def test_message_send_downstream_error(self, client, seed_agent):
        agent = seed_agent(name="Send Error Agent")

        mock_http_response = MagicMock()
        mock_http_response.status_code = 500
        mock_http_response.text = "Internal Server Error"

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_http_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_http_client):
            response = await client.post(
                f"{_PREFIX}/{agent.id}",
                json={
                    "jsonrpc": "2.0",
                    "method": "message/send",
                    "params": {},
                    "id": 2,
                },
                headers=TEST_AUTH_HEADER,
            )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32603


class TestTaskOperations:
    """E2E tests for tasks/get and tasks/cancel."""

    @pytest.mark.asyncio
    async def test_tasks_get(self, client, seed_agent):
        agent = seed_agent(name="Task Get Agent")

        downstream_response = {
            "jsonrpc": "2.0",
            "result": {
                "id": "task-xyz",
                "status": {"state": "working"},
            },
            "id": 3,
        }

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = downstream_response

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_http_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_http_client):
            response = await client.post(
                f"{_PREFIX}/{agent.id}",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/get",
                    "params": {"id": "task-xyz"},
                    "id": 3,
                },
                headers=TEST_AUTH_HEADER,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["id"] == "task-xyz"
        assert data["result"]["status"]["state"] == "working"

    @pytest.mark.asyncio
    async def test_tasks_cancel(self, client, seed_agent):
        agent = seed_agent(name="Task Cancel Agent")

        downstream_response = {
            "jsonrpc": "2.0",
            "result": {
                "id": "task-cancel-1",
                "status": {"state": "canceled"},
            },
            "id": 4,
        }

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = downstream_response

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_http_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_http_client):
            response = await client.post(
                f"{_PREFIX}/{agent.id}",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/cancel",
                    "params": {"id": "task-cancel-1"},
                    "id": 4,
                },
                headers=TEST_AUTH_HEADER,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["status"]["state"] == "canceled"


class TestPushNotificationConfig:
    """E2E tests for tasks/pushNotificationConfig/* methods."""

    @pytest.mark.asyncio
    async def test_push_notification_config_set(self, client, seed_agent):
        agent = seed_agent(name="Push Config Agent")

        downstream_response = {"jsonrpc": "2.0", "result": {"id": "push-1"}, "id": 5}

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = downstream_response

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_http_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_http_client):
            response = await client.post(
                f"{_PREFIX}/{agent.id}",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/pushNotificationConfig/set",
                    "params": {"taskId": "task-1", "pushNotificationConfig": {"url": "https://webhook.example.com"}},
                    "id": 5,
                },
                headers=TEST_AUTH_HEADER,
            )

        assert response.status_code == 200
        assert "result" in response.json()


# -------------------------
# Authenticated Extended Card
# -------------------------
class TestGetAuthenticatedExtendedCard:
    """E2E tests for agent/getAuthenticatedExtendedCard."""

    @pytest.mark.asyncio
    async def test_authenticated_card_success(self, client, seed_agent):
        agent = seed_agent(name="Auth Card Agent")

        response = await client.post(
            f"{_PREFIX}/{agent.id}",
            json={
                "jsonrpc": "2.0",
                "method": "agent/getAuthenticatedExtendedCard",
                "params": {},
                "id": 6,
            },
            headers=TEST_AUTH_HEADER,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["name"] == "Auth Card Agent"
        assert f"{_PREFIX}/{agent.id}" in data["result"]["url"]

    @pytest.mark.asyncio
    async def test_authenticated_card_not_found(self, client):
        response = await client.post(
            f"{_PREFIX}/nonexistent-id",
            json={
                "jsonrpc": "2.0",
                "method": "agent/getAuthenticatedExtendedCard",
                "params": {},
                "id": 7,
            },
            headers=TEST_AUTH_HEADER,
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32603


# -------------------------
# JSON-RPC Validation
# -------------------------
class TestJsonRpcValidation:
    """E2E tests for JSON-RPC protocol validation."""

    @pytest.mark.asyncio
    async def test_invalid_json_body(self, client, seed_agent):
        agent = seed_agent(name="Json Error Agent")

        response = await client.post(
            f"{_PREFIX}/{agent.id}",
            content=b"this is not json",
            headers={**TEST_AUTH_HEADER, "Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["error"]["code"] == -32700  # Parse Error

    @pytest.mark.asyncio
    async def test_missing_jsonrpc_version(self, client, seed_agent):
        agent = seed_agent(name="Version Check Agent")

        response = await client.post(
            f"{_PREFIX}/{agent.id}",
            json={"method": "message/send", "params": {}, "id": 1},
            headers=TEST_AUTH_HEADER,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["error"]["code"] == -32600  # Invalid Request

    @pytest.mark.asyncio
    async def test_unknown_method(self, client, seed_agent):
        agent = seed_agent(name="Method Check Agent")

        response = await client.post(
            f"{_PREFIX}/{agent.id}",
            json={"jsonrpc": "2.0", "method": "unknown/method", "params": {}, "id": 1},
            headers=TEST_AUTH_HEADER,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["error"]["code"] == -32601  # Method Not Found

    @pytest.mark.asyncio
    async def test_missing_method_field(self, client, seed_agent):
        agent = seed_agent(name="No Method Agent")

        response = await client.post(
            f"{_PREFIX}/{agent.id}",
            json={"jsonrpc": "2.0", "params": {}, "id": 1},
            headers=TEST_AUTH_HEADER,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["error"]["code"] == -32600


# -------------------------
# Agent Not Found / Disabled
# -------------------------
class TestAgentErrorPaths:
    """E2E tests for agent resolution error paths."""

    @pytest.mark.asyncio
    async def test_agent_not_found_returns_jsonrpc_error(self, client):
        response = await client.post(
            f"{_PREFIX}/does-not-exist",
            json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 10},
            headers=TEST_AUTH_HEADER,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["error"]["code"] == -32603
        assert "not found" in data["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_disabled_agent_returns_jsonrpc_error(self, client, seed_agent):
        agent = seed_agent(name="Disabled RPC Agent", enabled=False)

        response = await client.post(
            f"{_PREFIX}/{agent.id}",
            json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 11},
            headers=TEST_AUTH_HEADER,
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "disabled" in data["error"]["message"].lower()


# -------------------------
# Streaming (message/stream)
# -------------------------
class TestStreaming:
    """E2E tests for message/stream SSE streaming."""

    @pytest.mark.asyncio
    async def test_message_stream_returns_sse(self, client, seed_agent):
        """Streaming requests should return text/event-stream content type."""
        agent = seed_agent(name="Stream Test Agent")

        # Mock the SSE streaming to yield a few events
        async def mock_stream_jsonrpc(*args, **kwargs):
            yield 'data: {"jsonrpc":"2.0","result":{"id":"task-s1","status":{"state":"working"}},"id":1}\n\n'
            yield 'data: {"jsonrpc":"2.0","result":{"id":"task-s1","status":{"state":"completed"},"artifacts":[{"parts":[{"kind":"text","text":"Done!"}]}]},"id":1}\n\n'

        with patch("mcpgateway.routers.a2a_gateway._client_service") as mock_client:
            mock_client.stream_jsonrpc = mock_stream_jsonrpc

            response = await client.post(
                f"{_PREFIX}/{agent.id}",
                json={
                    "jsonrpc": "2.0",
                    "method": "message/stream",
                    "params": {
                        "message": {
                            "messageId": "msg-stream-1",
                            "role": "user",
                            "parts": [{"kind": "text", "text": "Stream me"}],
                        }
                    },
                    "id": 1,
                },
                headers=TEST_AUTH_HEADER,
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        body = response.text
        assert "task-s1" in body
        assert "completed" in body


# -------------------------
# Full Lifecycle
# -------------------------
class TestFullLifecycle:
    """E2E test for a full agent interaction lifecycle: register -> discover -> send -> get task."""

    @pytest.mark.asyncio
    async def test_full_flow(self, client, seed_agent):
        # 1. Register agent
        agent = seed_agent(name="Lifecycle Agent")

        # 2. Discover agent card
        card_response = await client.get(
            f"{_PREFIX}/{agent.id}/.well-known/agent-card.json",
            headers=TEST_AUTH_HEADER,
        )
        assert card_response.status_code == 200
        card = card_response.json()
        assert card["name"] == "Lifecycle Agent"

        # 3. Send message
        send_response_data = {
            "jsonrpc": "2.0",
            "result": {
                "id": "task-lifecycle-1",
                "status": {"state": "completed"},
                "artifacts": [{"parts": [{"kind": "text", "text": "Lifecycle complete!"}]}],
            },
            "id": 1,
        }

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = send_response_data

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_http_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_http_client):
            send_response = await client.post(
                f"{_PREFIX}/{agent.id}",
                json={
                    "jsonrpc": "2.0",
                    "method": "message/send",
                    "params": {
                        "message": {
                            "messageId": "msg-lifecycle-1",
                            "role": "user",
                            "parts": [{"kind": "text", "text": "Start lifecycle"}],
                        }
                    },
                    "id": 1,
                },
                headers=TEST_AUTH_HEADER,
            )

        assert send_response.status_code == 200
        send_data = send_response.json()
        assert send_data["result"]["id"] == "task-lifecycle-1"

        # 4. Get task status
        task_response_data = {
            "jsonrpc": "2.0",
            "result": {
                "id": "task-lifecycle-1",
                "status": {"state": "completed"},
            },
            "id": 2,
        }
        mock_http_response.json.return_value = task_response_data

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_http_client):
            task_response = await client.post(
                f"{_PREFIX}/{agent.id}",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/get",
                    "params": {"id": "task-lifecycle-1"},
                    "id": 2,
                },
                headers=TEST_AUTH_HEADER,
            )

        assert task_response.status_code == 200
        assert task_response.json()["result"]["status"]["state"] == "completed"

        # 5. Get authenticated extended card
        ext_card_response = await client.post(
            f"{_PREFIX}/{agent.id}",
            json={
                "jsonrpc": "2.0",
                "method": "agent/getAuthenticatedExtendedCard",
                "params": {},
                "id": 3,
            },
            headers=TEST_AUTH_HEADER,
        )

        assert ext_card_response.status_code == 200
        ext_card = ext_card_response.json()
        assert ext_card["result"]["name"] == "Lifecycle Agent"
