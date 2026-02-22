# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_completion_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
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
    CompletionService,
)


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
async def test_prompt_completion_admin_bypass_can_access_private_prompt(completion_db):
    service = CompletionService()
    request = {
        "ref": {"type": "ref/prompt", "name": "private-prompt"},
        "argument": {"name": "arg", "value": "r"},
    }

    result = await service.handle_completion(completion_db, request, user_email=None, token_teams=None)
    assert result.completion["values"] == ["red", "green"]


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
async def test_resource_completion_admin_bypass_includes_all_visible_records(completion_db):
    service = CompletionService()
    request = {
        "ref": {"type": "ref/resource", "uri": "template://resource"},
        "argument": {"name": "uri", "value": "file://"},
    }

    result = await service.handle_completion(completion_db, request, user_email=None, token_teams=None)
    assert set(result.completion["values"]) == {"file://public.txt", "file://team.txt", "file://private.txt"}
