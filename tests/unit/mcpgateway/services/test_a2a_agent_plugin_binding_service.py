# -*- coding: utf-8 -*-
"""Unit tests for A2AAgentPluginBindingService.

Tests cover:
    - _to_response: ORM → Pydantic conversion helper
    - upsert_binding: insert path, update path, idempotency
    - list_bindings: unfiltered and team-filtered
    - get_bindings_for_agent: standalone function, wildcard vs exact match
    - delete_binding: success, not-found error, forbidden error
    - delete_bindings_by_reference: success, scoped-by-team
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base
from mcpgateway.schemas import A2AAgentPluginBindingResponse
from mcpgateway.services.a2a_agent_plugin_binding_service import (
    A2AAgentPluginBindingForbiddenError,
    A2AAgentPluginBindingNotFoundError,
    A2AAgentPluginBindingService,
    get_bindings_for_agent,
)


def _make_binding(
    id_="binding-001",
    team_id="team-a",
    agent_name="agent_x",
    plugin_id="OutputLengthGuardPlugin",
    mode="enforce",
    priority=50,
    config=None,
    on_error=None,
    binding_reference_id=None,
    created_by="admin@example.com",
    updated_by="admin@example.com",
):
    b = MagicMock()
    b.id = id_
    b.team_id = team_id
    b.agent_name = agent_name
    b.plugin_id = plugin_id
    b.mode = mode
    b.priority = priority
    b.config = config if config is not None else {"enabled": True}
    b.on_error = on_error
    b.binding_reference_id = binding_reference_id
    b.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    b.created_by = created_by
    b.updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    b.updated_by = updated_by
    return b


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def service():
    return A2AAgentPluginBindingService()


class TestToResponse:
    def test_converts_orm_to_pydantic(self):
        binding = _make_binding()
        result = A2AAgentPluginBindingService._to_response(binding)
        assert isinstance(result, A2AAgentPluginBindingResponse)
        assert result.id == "binding-001"
        assert result.team_id == "team-a"
        assert result.agent_name == "agent_x"
        assert result.plugin_id == "OutputLengthGuardPlugin"
        assert result.mode == "enforce"
        assert result.priority == 50
        assert result.config == {"enabled": True}
        assert result.on_error is None
        assert result.binding_reference_id is None
        assert result.created_by == "admin@example.com"
        assert result.updated_by == "admin@example.com"

    def test_converts_with_optional_fields(self):
        binding = _make_binding(
            on_error="fail",
            binding_reference_id="ext-123",
        )
        result = A2AAgentPluginBindingService._to_response(binding)
        assert result.on_error == "fail"
        assert result.binding_reference_id == "ext-123"


class TestUpsertBinding:
    def test_inserts_new_binding(self, service, db_session):
        result = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={"enabled": True},
            on_error=None,

            caller_email="admin@example.com",
        )
        assert result.team_id == "team-a"
        assert result.agent_name == "agent_x"
        assert result.plugin_id == "OutputLengthGuardPlugin"
        assert result.mode == "enforce"
        assert result.priority == 50
        assert result.created_by == "admin@example.com"
        assert result.updated_by == "admin@example.com"
        assert result.id is not None

    def test_upsert_updates_existing(self, service, db_session):
        result1 = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={"enabled": True},
            on_error=None,
            caller_email="admin@example.com",
        )
        original_id = result1.id

        result2 = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="permissive",
            priority=99,
            config={"enabled": True, "max_chars": 500},
            on_error=None,
            caller_email="updater@example.com",
        )
        assert result2.id == original_id
        assert result2.mode == "permissive"
        assert result2.priority == 99
        assert result2.config["max_chars"] == 500
        assert result2.updated_by == "updater@example.com"

    def test_upsert_idempotent_same_data(self, service, db_session):
        result1 = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={"enabled": True},
            on_error=None,
            caller_email="admin@example.com",
        )
        result2 = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={"enabled": True},
            on_error=None,
            caller_email="admin@example.com",
        )
        assert result2.id == result1.id

    def test_upsert_ownership_transfer_warning(self, service, db_session):
        """Changing binding_reference_id on an existing binding logs a warning."""
        result = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-old",
        )
        updated = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-new",
        )
        assert updated.id == result.id
        assert updated.binding_reference_id == "ref-new"

    def test_inserts_wildcard_agent(self, service, db_session):
        result = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="*",
            plugin_id="RateLimiterPlugin",
            mode="permissive",
            priority=10,
            config={"by_user": "60/m"},
            on_error=None,
            caller_email="admin@example.com",
        )
        assert result.agent_name == "*"
        assert result.plugin_id == "RateLimiterPlugin"

    def test_spaces_in_agent_name_stored_as_is(self, service, db_session):
        result = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        assert result.agent_name == ""

    def test_spaces_in_plugin_id_stored_as_is(self, service, db_session):
        result = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        assert result.plugin_id == ""

    @pytest.mark.parametrize(
        "team_id,agent_name,plugin_id,mode,priority,config,on_error,caller_email",
        [
            ("", "agent_x", "OutputLengthGuardPlugin", "enforce", 50, {}, None, "admin@example.com"),
        ],
    )
    def test_empty_team_id_stored_as_is(self, service, db_session, team_id, agent_name, plugin_id, mode, priority, config, on_error, caller_email):
        result = service.upsert_binding(
            db=db_session,
            team_id=team_id,
            agent_name=agent_name,
            plugin_id=plugin_id,
            mode=mode,
            priority=priority,
            config=config,
            on_error=on_error,
            caller_email=caller_email,
        )
        assert result.team_id == ""

    def test_empty_plugin_id_stored_as_is(self, service, db_session):
        result = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        assert result.plugin_id == ""


class TestListBindings:
    def test_list_all_when_empty(self, service, db_session):
        result, total = service.list_bindings(db_session)
        assert result == []
        assert total == 0

    def test_list_all(self, service, db_session):
        for i in range(3):
            service.upsert_binding(
                db=db_session,
                team_id="team-a",
                agent_name=f"agent_{i}",
                plugin_id="OutputLengthGuardPlugin",
                mode="enforce",
                priority=50,
                config={},
                on_error=None,
            caller_email="admin@example.com",
            )
        result, total = service.list_bindings(db_session)
        assert len(result) == 3
        assert total == 3

    def test_filter_by_team(self, service, db_session):
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        service.upsert_binding(
            db=db_session,
            team_id="team-b",
            agent_name="agent_y",
            plugin_id="RateLimiterPlugin",
            mode="permissive",
            priority=30,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        result_a, total_a = service.list_bindings(db_session, team_id="team-a")
        assert len(result_a) == 1
        assert total_a == 1
        assert result_a[0].team_id == "team-a"

        result_b, total_b = service.list_bindings(db_session, team_id="team-b")
        assert len(result_b) == 1
        assert total_b == 1
        assert result_b[0].team_id == "team-b"

        result_c, total_c = service.list_bindings(db_session, team_id="team-c")
        assert len(result_c) == 0
        assert total_c == 0

    def test_filter_by_reference_id(self, service, db_session):
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-001",
        )
        service.upsert_binding(
            db=db_session,
            team_id="team-b",
            agent_name="agent_y",
            plugin_id="RateLimiterPlugin",
            mode="permissive",
            priority=30,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-002",
        )
        result, total = service.list_bindings(db_session, binding_reference_id="ref-001")
        assert len(result) == 1
        assert total == 1
        assert result[0].team_id == "team-a"

        result_empty, total_empty = service.list_bindings(db_session, binding_reference_id="ref-nope")
        assert len(result_empty) == 0
        assert total_empty == 0

    def test_binding_reference_takes_precedence_over_team(self, service, db_session):
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-global",
        )
        result, total = service.list_bindings(db_session, team_id="team-nope", binding_reference_id="ref-global")
        assert len(result) == 1
        assert total == 1
        assert result[0].team_id == "team-a"


class TestGetBindingsForAgent:
    def test_exact_match(self, service, db_session):
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        result = get_bindings_for_agent(db_session, "team-a", "agent_x")
        assert len(result) == 1
        assert result[0].plugin_id == "OutputLengthGuardPlugin"

    def test_prefers_exact_over_wildcard(self, service, db_session):
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="*",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=10,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="permissive",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        result = get_bindings_for_agent(db_session, "team-a", "agent_x")
        assert len(result) == 1
        assert result[0].mode == "permissive"

    def test_wildcard_used_when_no_exact_match(self, service, db_session):
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="*",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=10,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        result = get_bindings_for_agent(db_session, "team-a", "agent_unknown")
        assert len(result) == 1
        assert result[0].agent_name == "*"

    def test_returns_empty_for_unknown_team(self, service, db_session):
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        result = get_bindings_for_agent(db_session, "team-unknown", "agent_x")
        assert len(result) == 0


class TestDeleteBinding:
    def test_delete_success(self, service, db_session):
        b = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        result = service.delete_binding(db_session, b.id)
        assert result.id == b.id
        remaining, total = service.list_bindings(db_session, team_id="team-a")
        assert remaining == []
        assert total == 0

    def test_delete_not_found(self, service, db_session):
        with pytest.raises(A2AAgentPluginBindingNotFoundError, match="not found"):
            service.delete_binding(db_session, "nonexistent-id")

    def test_delete_forbidden(self, service, db_session):
        b = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        with pytest.raises(A2AAgentPluginBindingForbiddenError, match="Not authorized"):
            service.delete_binding(db_session, b.id, allowed_teams={"team-b"})

    def test_delete_allowed_teams_none_bypass(self, service, db_session):
        b = service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        result = service.delete_binding(db_session, b.id, allowed_teams=None)
        assert result.id == b.id


class TestDeleteBindingsByReference:
    def test_delete_by_reference(self, service, db_session):
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-001",
        )
        service.upsert_binding(
            db=db_session,
            team_id="team-b",
            agent_name="agent_y",
            plugin_id="RateLimiterPlugin",
            mode="permissive",
            priority=30,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-001",
        )
        deleted = service.delete_bindings_by_reference(db_session, "ref-001")
        assert len(deleted) == 2
        remaining, total = service.list_bindings(db_session)
        assert remaining == []
        assert total == 0

    def test_delete_by_reference_scoped(self, service, db_session):
        service.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-001",
        )
        service.upsert_binding(
            db=db_session,
            team_id="team-b",
            agent_name="agent_y",
            plugin_id="RateLimiterPlugin",
            mode="permissive",
            priority=30,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-001",
        )
        deleted = service.delete_bindings_by_reference(db_session, "ref-001", allowed_teams={"team-a"})
        assert len(deleted) == 1
        assert deleted[0].team_id == "team-a"

        remaining, total = service.list_bindings(db_session)
        assert len(remaining) == 1
        assert total == 1
        assert remaining[0].team_id == "team-b"

    def test_delete_by_reference_nonexistent(self, service, db_session):
        deleted = service.delete_bindings_by_reference(db_session, "ref-nonexistent")
        assert deleted == []
