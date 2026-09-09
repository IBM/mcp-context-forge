# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_completion_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from types import SimpleNamespace

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.common.models import (
    CompleteResult,
)
from mcpgateway.db import Base, Prompt as DbPrompt, Resource as DbResource
from mcpgateway.services.completion_service import (
    CompletionError,
    CompletionInternalError,
    CompletionInvalidParamsError,
    CompletionNotSupportedError,
    CompletionService,
    completion_error_code,
)


def test_completion_not_supported_maps_to_method_not_found():
    assert completion_error_code(CompletionNotSupportedError("x")) == -32601


def test_completion_invalid_params_maps_to_invalid_params():
    assert completion_error_code(CompletionInvalidParamsError("x")) == -32602


def test_completion_internal_error_maps_to_internal_error():
    assert completion_error_code(CompletionInternalError("x")) == -32603


def test_unclassified_completion_error_defaults_to_internal_error():
    assert completion_error_code(CompletionError("x")) == -32603


def test_subclasses_are_completion_errors():
    assert issubclass(CompletionNotSupportedError, CompletionError)
    assert issubclass(CompletionInvalidParamsError, CompletionError)
    assert issubclass(CompletionInternalError, CompletionError)


class FakeScalarOneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeScalarsAllResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class DummyPrompt:
    def __init__(self, name, argument_schema):
        self.name = name
        self.argument_schema = argument_schema
        self.is_active = True


class DummyResource:
    def __init__(self, uri):
        self.uri = uri
        self.is_active = True


@pytest.mark.asyncio
async def test_handle_completion_missing_ref_or_arg():
    service = CompletionService()
    with pytest.raises(CompletionError) as exc:
        await service.handle_completion(None, {})
    assert "Missing reference type or argument name" in str(exc.value)


@pytest.mark.asyncio
async def test_handle_completion_invalid_ref_type():
    service = CompletionService()
    request = {"ref": {"type": "ref/unknown"}, "argument": {"name": "arg", "value": ""}}
    with pytest.raises(CompletionError) as exc:
        await service.handle_completion(None, request)
    assert "Invalid reference type: ref/unknown" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_prompt_missing_name():
    service = CompletionService()
    with pytest.raises(CompletionError) as exc:
        await service._complete_prompt_argument(None, {}, "arg1", "")
    assert "Missing prompt name" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_prompt_not_found():
    service = CompletionService()

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(None)

    with pytest.raises(CompletionError) as exc:
        await service._complete_prompt_argument(DummySession(), {"name": "nonexistent"}, "arg", "")
    assert "Prompt not found: nonexistent" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_prompt_argument_not_found():
    service = CompletionService()
    prompt = DummyPrompt("p1", {"properties": {"p": {"name": "other"}}})

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(prompt)

    with pytest.raises(CompletionError) as exc:
        await service._complete_prompt_argument(DummySession(), {"name": "p1"}, "arg", "")
    assert "Argument not found: arg" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_prompt_enum_values():
    service = CompletionService()
    schema = {"properties": {"p": {"name": "arg1", "enum": ["Apple", "Banana", "Cherry"]}}}
    prompt = DummyPrompt("p1", schema)

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(prompt)

    result = await service._complete_prompt_argument(DummySession(), {"name": "p1"}, "arg1", "an")
    assert isinstance(result, CompleteResult)
    comp = result.completion
    assert comp["values"] == ["Banana"]
    assert comp["total"] == 1
    assert comp["hasMore"] is False


@pytest.mark.asyncio
async def test_custom_completions_override_enum():
    service = CompletionService()
    service.register_completions("arg1", ["dog", "cat", "ferret"])
    schema = {"properties": {"p": {"name": "arg1"}}}
    prompt = DummyPrompt("p1", schema)

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(prompt)

    result = await service._complete_prompt_argument(DummySession(), {"name": "p1"}, "arg1", "er")
    comp = result.completion
    assert comp["values"] == ["ferret"]
    assert comp["total"] == 1
    assert comp["hasMore"] is False


@pytest.mark.asyncio
async def test_complete_resource_missing_uri():
    service = CompletionService()

    class DummySession:
        pass

    with pytest.raises(CompletionError) as exc:
        # 3 args: session, ref dict, and the value
        await service._complete_resource_uri(DummySession(), {}, "")
    assert "Missing URI template" in str(exc.value)


@pytest.mark.asyncio
async def test_complete_resource_values():
    service = CompletionService()
    resources = [DummyResource("foo"), DummyResource("bar"), DummyResource("bazfoo")]

    class DummySession:
        def execute(self, query):
            return FakeScalarsAllResult(resources)

    result = await service._complete_resource_uri(DummySession(), {"uri": "template"}, "foo")
    comp = result.completion
    assert set(comp["values"]) == {"foo", "bazfoo"}
    assert comp["total"] == 2
    assert comp["hasMore"] is False


@pytest.mark.asyncio
async def test_handle_completion_resource_ref_path():
    service = CompletionService()
    resources = [DummyResource("https://example.com/a"), DummyResource("https://example.com/b")]

    class DummySession:
        def execute(self, query):
            return FakeScalarsAllResult(resources)

    request = {
        "ref": {"type": "ref/resource", "uri": "template://resource"},
        "argument": {"name": "uri", "value": "example.com"},
    }
    result = await service.handle_completion(DummySession(), request)

    comp = result.completion
    assert comp["total"] == 2
    assert len(comp["values"]) == 2


@pytest.mark.asyncio
async def test_unregister_completions():
    service = CompletionService()
    service.register_completions("arg1", ["a", "b"])
    service.unregister_completions("arg1")
    schema = {"properties": {"p": {"name": "arg1"}}}
    prompt = DummyPrompt("p1", schema)

    class DummySession:
        def execute(self, query):
            return FakeScalarOneResult(prompt)

    result = await service._complete_prompt_argument(DummySession(), {"name": "p1"}, "arg1", "a")
    comp = result.completion
    assert comp["values"] == []
    assert comp["total"] == 0
    assert comp["hasMore"] is False


@pytest.mark.asyncio
async def test_resolve_team_ids_uses_team_management_service_when_token_teams_absent(monkeypatch):
    service = CompletionService()

    class MockTeamService:
        def __init__(self, _db):
            pass

        async def get_user_teams(self, _user_email):
            return [SimpleNamespace(id="team-1"), SimpleNamespace(id="team-2")]

    monkeypatch.setattr("mcpgateway.services.team_management_service.TeamManagementService", MockTeamService)

    team_ids = await service._resolve_team_ids(db=object(), user_email="member@example.com", token_teams=None)
    assert team_ids == ["team-1", "team-2"]


@pytest.fixture
def completion_db():
    """Create an isolated in-memory DB session for completion visibility tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    prompt_schema = {"properties": {"arg": {"name": "arg", "enum": ["red", "green", "blue"]}}}

    db.add_all(
        [
            DbPrompt(
                original_name="public-prompt",
                custom_name="public-prompt",
                custom_name_slug="public-prompt",
                name="public-prompt",
                template="public",
                argument_schema=prompt_schema,
                visibility="public",
                owner_email="owner@example.com",
                team_id=None,
                enabled=True,
            ),
            DbPrompt(
                original_name="team-prompt",
                custom_name="team-prompt",
                custom_name_slug="team-prompt",
                name="team-prompt",
                template="team",
                argument_schema=prompt_schema,
                visibility="team",
                team_id="team-1",
                owner_email="teammate@example.com",
                enabled=True,
            ),
            DbPrompt(
                original_name="private-prompt",
                custom_name="private-prompt",
                custom_name_slug="private-prompt",
                name="private-prompt",
                template="private",
                argument_schema=prompt_schema,
                visibility="private",
                owner_email="owner@example.com",
                team_id=None,
                enabled=True,
            ),
        ]
    )

    db.add_all(
        [
            DbResource(
                uri="file://public.txt",
                name="Public Resource",
                text_content="public",
                visibility="public",
                owner_email="owner@example.com",
                enabled=True,
            ),
            DbResource(
                uri="file://team.txt",
                name="Team Resource",
                text_content="team",
                visibility="team",
                team_id="team-1",
                owner_email="teammate@example.com",
                enabled=True,
            ),
            DbResource(
                uri="file://private.txt",
                name="Private Resource",
                text_content="private",
                visibility="private",
                owner_email="owner@example.com",
                enabled=True,
            ),
        ]
    )
    db.commit()

    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_prompt_completion_public_only_token_cannot_access_private_prompt(completion_db):
    service = CompletionService()
    request = {
        "ref": {"type": "ref/prompt", "name": "private-prompt"},
        "argument": {"name": "arg", "value": "r"},
    }

    with pytest.raises(CompletionError, match="Prompt not found"):
        await service.handle_completion(completion_db, request, user_email="owner@example.com", token_teams=[])


@pytest.mark.asyncio
async def test_prompt_completion_team_token_can_access_team_prompt(completion_db):
    service = CompletionService()
    request = {
        "ref": {"type": "ref/prompt", "name": "team-prompt"},
        "argument": {"name": "arg", "value": "r"},
    }

    result = await service.handle_completion(completion_db, request, user_email="member@example.com", token_teams=["team-1"])
    assert result.completion["values"] == ["red", "green"]


@pytest.mark.asyncio
async def test_prompt_completion_admin_bypass_denies_private_prompt(completion_db):
    """SECURITY: admin bypass must not complete for another user's private prompt.

    Regression for PR #4341 follow-up — the private prompt is filtered out at the query
    level, so the completion resolver reports "not found" (raises CompletionError) rather
    than returning its argument values, which matches the generic-not-found disclosure policy.
    """
    # First-Party
    from mcpgateway.services.completion_service import CompletionError

    service = CompletionService()
    request = {
        "ref": {"type": "ref/prompt", "name": "private-prompt"},
        "argument": {"name": "arg", "value": "r"},
    }

    with pytest.raises(CompletionError):
        await service.handle_completion(completion_db, request, user_email=None, token_teams=None)


@pytest.mark.asyncio
async def test_resource_completion_public_only_token_filters_private_and_team(completion_db):
    service = CompletionService()
    request = {
        "ref": {"type": "ref/resource", "uri": "template://resource"},
        "argument": {"name": "uri", "value": "file://"},
    }

    result = await service.handle_completion(completion_db, request, user_email="owner@example.com", token_teams=[])
    assert set(result.completion["values"]) == {"file://public.txt"}


@pytest.mark.asyncio
async def test_resource_completion_team_token_includes_public_and_team_only(completion_db):
    service = CompletionService()
    request = {
        "ref": {"type": "ref/resource", "uri": "template://resource"},
        "argument": {"name": "uri", "value": "file://"},
    }

    result = await service.handle_completion(completion_db, request, user_email="member@example.com", token_teams=["team-1"])
    assert set(result.completion["values"]) == {"file://public.txt", "file://team.txt"}
    assert "file://private.txt" not in result.completion["values"]


@pytest.mark.asyncio
async def test_resource_completion_admin_bypass_excludes_private(completion_db):
    """SECURITY: admin bypass sees public + team resource completions but NEVER private.

    Regression for PR #4341 follow-up — admin bypass must not reveal private URIs via completion.
    """
    service = CompletionService()
    request = {
        "ref": {"type": "ref/resource", "uri": "template://resource"},
        "argument": {"name": "uri", "value": "file://"},
    }

    result = await service.handle_completion(completion_db, request, user_email=None, token_teams=None)
    assert set(result.completion["values"]) == {"file://public.txt", "file://team.txt"}
    assert "file://private.txt" not in result.completion["values"]


# ---------------------------------------------------------------------------
# Task 2: _acquire_upstream_session() — registry + mcp_proxy_client fallback
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager  # noqa: E402  # Standard, grouped near first use per existing file layout
from unittest.mock import AsyncMock  # noqa: E402


class _FakeClient:
    def __init__(self, *, protocol_version="2025-11-25", supports_completions=True):
        self.session = SimpleNamespace(
            protocol_version=protocol_version,
            server_capabilities=SimpleNamespace(completions=object() if supports_completions else None),
            complete=AsyncMock(),
        )


class _FakeGateway:
    id = "gw-1"
    url = "https://upstream.example.com/mcp"
    transport = "streamable_http"
    auth_type = None
    auth_query_params = None


@pytest.mark.asyncio
async def test_acquire_upstream_session_uses_registry_when_downstream_session_in_scope(monkeypatch):
    fake_upstream = SimpleNamespace(session=SimpleNamespace(protocol_version="2026-07-28"))

    @asynccontextmanager
    async def fake_acquire(self, **kwargs):
        yield fake_upstream

    class _FakeRegistry:
        acquire = fake_acquire

    monkeypatch.setattr(
        "mcpgateway.services.completion_service._downstream_session_id_from_request",
        lambda: "downstream-1",
    )
    monkeypatch.setattr(
        "mcpgateway.services.completion_service.get_upstream_session_registry",
        lambda: _FakeRegistry(),
    )

    service = CompletionService()
    async with service._acquire_upstream_session(_FakeGateway()) as session:
        assert session is fake_upstream.session


@pytest.mark.asyncio
async def test_acquire_upstream_session_falls_back_to_mcp_proxy_client_without_downstream_session(monkeypatch):
    fake_client = _FakeClient(protocol_version="2025-11-25")

    @asynccontextmanager
    async def fake_mcp_proxy_client(**kwargs):
        yield fake_client

    monkeypatch.setattr(
        "mcpgateway.services.completion_service._downstream_session_id_from_request",
        lambda: None,
    )
    monkeypatch.setattr(
        "mcpgateway.services.completion_service.mcp_proxy_client",
        fake_mcp_proxy_client,
    )

    service = CompletionService()
    async with service._acquire_upstream_session(_FakeGateway()) as session:
        assert session is fake_client.session


# ---------------------------------------------------------------------------
# Task 3: _error_from_upstream() and _forward_completion_upstream()
# ---------------------------------------------------------------------------

from mcp import MCPError as McpError  # noqa: E402
from mcp.types import PromptReference  # noqa: E402


def test_error_from_upstream_maps_known_codes():
    err = McpError(code=-32602, message="unknown prompt")
    result = CompletionService._error_from_upstream(err, "gw-1")
    assert isinstance(result, CompletionInvalidParamsError)
    assert "gw-1" in str(result)


def test_error_from_upstream_defaults_unknown_code_to_internal():
    err = McpError(code=-32000, message="weird")
    assert isinstance(CompletionService._error_from_upstream(err, "gw-1"), CompletionInternalError)


def _patch_upstream(monkeypatch, session):
    @asynccontextmanager
    async def _fake_acquire(self, gateway):
        yield session

    monkeypatch.setattr(CompletionService, "_acquire_upstream_session", _fake_acquire)


@pytest.mark.asyncio
async def test_forward_completion_upstream_uses_has_more_snake_case_attribute(monkeypatch):
    from mcp_types._types import Completion, CompleteResult as SdkCompleteResult

    real_completion = Completion(values=["a", "b"], total=5, has_more=True)

    async def fake_complete(ref, argument, context_arguments=None):
        return SdkCompleteResult(completion=real_completion)

    session = SimpleNamespace(
        server_capabilities=SimpleNamespace(completions=object()),
        complete=fake_complete,
    )
    _patch_upstream(monkeypatch, session)

    service = CompletionService()
    result = await service._forward_completion_upstream(_FakeGateway(), PromptReference(type="ref/prompt", name="p"), {"name": "arg", "value": ""})
    # Regression guard for spec §2 row 11: a fake that returns a real SDK
    # Completion (has_more=True) must round-trip hasMore=True, not silently
    # become False/None because the service read the wrong attribute name.
    assert result.completion["hasMore"] is True
    assert result.completion["total"] == 5
    assert result.completion["values"] == ["a", "b"]


@pytest.mark.asyncio
async def test_forward_completion_upstream_raises_not_supported_without_capability(monkeypatch):
    session = SimpleNamespace(server_capabilities=SimpleNamespace(completions=None))
    _patch_upstream(monkeypatch, session)

    service = CompletionService()
    with pytest.raises(CompletionNotSupportedError):
        await service._forward_completion_upstream(_FakeGateway(), PromptReference(type="ref/prompt", name="p"), {"name": "arg", "value": ""})


# ---------------------------------------------------------------------------
# Task 4: _complete_prompt_argument() — federated dispatch + local fallback
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock  # noqa: E402


class _DummyPromptForForwarding:
    def __init__(self, name, schema, gateway_id=None, gateway=None, original_name=None):
        self.name = name
        self.argument_schema = schema
        self.gateway_id = gateway_id
        self.gateway = gateway
        self.original_name = original_name


class _DummyGatewayForForwarding:
    id = "gw-1"
    url = "https://upstream.example.com/mcp"
    transport = "streamable_http"
    auth_type = None
    auth_query_params = None


def _db_returning(value):
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = value
    return db


@pytest.mark.asyncio
async def test_federated_prompt_completion_is_answered_by_upstream(monkeypatch):
    gateway = _DummyGatewayForForwarding()
    prompt = _DummyPromptForForwarding("upstream-prompt", {"properties": {}}, gateway_id="gw-1", gateway=gateway, original_name="prompt")
    db = _db_returning(prompt)

    async def fake_forward(self, gw, ref, argument, context=None):
        assert gw is gateway
        return SimpleNamespace(completion={"values": ["from-upstream"], "total": 1, "hasMore": False})

    monkeypatch.setattr(CompletionService, "_forward_completion_upstream", fake_forward)
    service = CompletionService()
    result = await service._complete_prompt_argument(db, {"name": "upstream-prompt"}, "arg", "")
    assert result.completion["values"] == ["from-upstream"]


@pytest.mark.asyncio
async def test_federated_prompt_falls_back_to_local_enum_when_unsupported(monkeypatch):
    gateway = _DummyGatewayForForwarding()
    # "blue" (not "green") as the non-matching enum value: "r" is a substring
    # of "green" too ("g-R-een"), which would make this assertion pass
    # vacuously regardless of whether the fallback filter actually ran.
    schema = {"properties": {"color": {"name": "color", "enum": ["red", "blue"]}}}
    prompt = _DummyPromptForForwarding("upstream-prompt", schema, gateway_id="gw-1", gateway=gateway, original_name="prompt")
    db = _db_returning(prompt)

    async def fake_forward(self, gw, ref, argument, context=None):
        raise CompletionNotSupportedError("nope")

    monkeypatch.setattr(CompletionService, "_forward_completion_upstream", fake_forward)
    service = CompletionService()
    result = await service._complete_prompt_argument(db, {"name": "upstream-prompt"}, "color", "r")
    assert result.completion["values"] == ["red"]


@pytest.mark.asyncio
async def test_federated_prompt_internal_error_does_not_fall_back(monkeypatch):
    gateway = _DummyGatewayForForwarding()
    schema = {"properties": {"color": {"name": "color", "enum": ["red"]}}}
    prompt = _DummyPromptForForwarding("upstream-prompt", schema, gateway_id="gw-1", gateway=gateway, original_name="prompt")
    db = _db_returning(prompt)

    async def fake_forward(self, gw, ref, argument, context=None):
        raise CompletionInternalError("boom")

    monkeypatch.setattr(CompletionService, "_forward_completion_upstream", fake_forward)
    service = CompletionService()
    with pytest.raises(CompletionInternalError):
        await service._complete_prompt_argument(db, {"name": "upstream-prompt"}, "color", "r")


@pytest.mark.asyncio
async def test_local_prompt_completion_still_answered_locally(monkeypatch):
    prompt = _DummyPromptForForwarding("local-prompt", {"properties": {"color": {"name": "color", "enum": ["blue"]}}}, gateway_id=None)
    db = _db_returning(prompt)

    def fail_forward(*a, **kw):
        raise AssertionError("must not forward a non-federated prompt")

    monkeypatch.setattr(CompletionService, "_forward_completion_upstream", fail_forward)
    service = CompletionService()
    result = await service._complete_prompt_argument(db, {"name": "local-prompt"}, "color", "b")
    assert result.completion["values"] == ["blue"]
