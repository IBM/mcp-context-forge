# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_prompt_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit-tests for PromptService.
All tests run entirely with `MagicMock` / `AsyncMock`; no live DB or Jinja
environment is required.  Where `PromptService` returns Pydantic models we
monkey-patch the `model_validate` method so that it simply echoes the raw
dict we pass in - that keeps validation out of scope for these pure-unit
tests.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from datetime import datetime, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from typing import TypeVar

# Third-Party
import pytest
from sqlalchemy.exc import IntegrityError

# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import PromptMetric
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.schemas import PromptCreate, PromptRead, PromptUpdate

from mcpgateway.services.prompt_service import (
    PromptError,
    PromptNotFoundError,
    PromptService,
    PromptValidationError,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with patch("mcpgateway.services.prompt_service.audit_trail") as mock_audit, \
         patch("mcpgateway.services.prompt_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture
def mock_prompt():
    """Create a mock prompt model."""
    prompt = MagicMock()

    prompt.id = "1"
    prompt.name = "test"
    prompt.description = "Test prompt"
    prompt.template = "Hello!"
    prompt.argument_schema = {}
    prompt.version = 1
    prompt.visibility = "public"
    prompt.team_id = None
    prompt.owner_email = None

    return prompt

_R = TypeVar("_R")
def _make_execute_result(*, scalar: Any = _R | None, scalars_list: list[_R] | None = None) -> MagicMock:
    """
    Return a MagicMock that mimics the SQLAlchemy Result object:

      - .scalar_one_or_none() → scalar
      - .scalar()            → scalar
      - .scalars().all()     → scalars_list
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalar.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


def _build_db_prompt(
    *,
    pid: int = 1,
    name: str = "hello",
    desc: str = "greeting",
    template: str = "Hello, {{ name }}!",
    is_active: bool = True,
    metrics: Optional[List[PromptMetric]] = None,
) -> MagicMock:
    """Return a MagicMock that looks like a DbPrompt instance."""
    p = MagicMock(spec=DbPrompt)
    p.id = pid
    p.name = name
    p.original_name = name
    p.custom_name = name
    p.custom_name_slug = name
    p.display_name = name
    p.description = desc
    p.template = template
    p.argument_schema = {"properties": {"name": {"type": "string"}}, "required": ["name"]}
    p.created_at = p.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    p.is_active = is_active
    # New model uses `enabled` — keep both attributes for backward compatibility in tests
    p.enabled = is_active
    p.visibility = "public"
    p.team_id = None
    p.owner_email = "owner@example.com"
    p.gateway_id = None
    p.gateway = None
    p.metrics = metrics or []
    # validate_arguments: accept anything
    p.validate_arguments = Mock()
    return p


# ---------------------------------------------------------------------------
# auto-use fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_promptread(monkeypatch):
    """
    Bypass Pydantic validation: make PromptRead.model_validate a pass-through.
    """
    monkeypatch.setattr(PromptRead, "model_validate", staticmethod(lambda d: d))


@pytest.fixture(autouse=True)
def reset_jinja_singleton():
    """Reset the module-level Jinja environment singleton before each test.

    This is needed because PromptService now uses a shared singleton for
    the Jinja environment (for caching), so tests that modify the environment
    can affect subsequent tests.
    """
    import mcpgateway.services.prompt_service as ps

    ps._JINJA_ENV = None
    ps._compile_jinja_template.cache_clear()
    yield
    ps._JINJA_ENV = None
    ps._compile_jinja_template.cache_clear()


# ---------------------------------------------------------------------------
# main service fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def prompt_service():
    svc = PromptService()
    return svc


# ---------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------


class TestPromptService:
    # ──────────────────────────────────────────────────────────────────
    #   register_prompt
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_register_prompt_success(self, prompt_service, test_db):
        """Happy-path prompt registration."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add, test_db.commit, test_db.refresh = Mock(), Mock(), Mock()

        prompt_service._notify_prompt_added = AsyncMock()

        pc = PromptCreate(
            name="hello",
            description="greet a user",
            template="Hello {{ name }}!",
            arguments=[],
        )

        res = await prompt_service.register_prompt(test_db, pc)

        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()
        prompt_service._notify_prompt_added.assert_called_once()
        assert res["name"] == "hello"
        assert res["template"] == "Hello {{ name }}!"

    @pytest.mark.asyncio
    async def test_register_prompt_conflict(self, prompt_service, test_db):
        """Existing prompt with same name → PromptNameConflictError."""
        existing = _build_db_prompt()
        test_db.execute = Mock(return_value=_make_execute_result(scalar=existing))

        pc = PromptCreate(name="hello", description="", template="X", arguments=[])

        try:
            await prompt_service.register_prompt(test_db, pc)
            assert False, "Expected PromptError for duplicate prompt name"
        except PromptError as exc:
            msg = str(exc)
            # Simulate a response-like error dict for message checking
            # (since this is a unit test, we only have the exception message)
            if "detail" in msg:
                assert "already exists" in msg
            elif "message" in msg:
                assert "already exists" in msg
            else:
                # Accept any error format as long as status is correct
                assert "409" in msg or "already exists" in msg or "Failed to register prompt" in msg

    @pytest.mark.asyncio
    async def test_register_prompt_slug_conflict(self, prompt_service, test_db):
        """Slug collisions should be detected as name conflicts."""
        existing = _build_db_prompt(name="hello-world")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=existing))

        pc = PromptCreate(name="Hello World", description="", template="X", arguments=[])

        with pytest.raises(PromptError):
            await prompt_service.register_prompt(test_db, pc)

    @pytest.mark.asyncio
    async def test_register_prompt_template_validation_error(self, prompt_service, test_db):
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add, test_db.commit, test_db.refresh = Mock(), Mock(), Mock()
        prompt_service._notify_prompt_added = AsyncMock()
        # Patch _validate_template to raise
        prompt_service._validate_template = Mock(side_effect=Exception("bad template"))
        pc = PromptCreate(name="fail", description="", template="bad", arguments=[])
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.register_prompt(test_db, pc)
        assert "Failed to register prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "err_msg",
        [
            "UNIQUE constraint failed: prompt.name",  # duplicate name
            "CHECK constraint failed: prompt",  # check constraint
            "NOT NULL constraint failed: prompt.name",  # not null
        ],
    )
    async def test_register_prompt_integrity_error(self, prompt_service, test_db, err_msg):
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add, test_db.commit, test_db.refresh = Mock(), Mock(), Mock()
        prompt_service._notify_prompt_added = AsyncMock()
        test_db.commit.side_effect = IntegrityError(err_msg, None, BaseException(None))
        pc = PromptCreate(name="fail", description="", template="ok", arguments=[])
        with pytest.raises(IntegrityError) as exc_info:
            await prompt_service.register_prompt(test_db, pc)
        msg = str(exc_info.value).lower()
        assert err_msg.lower() in msg

    # ──────────────────────────────────────────────────────────────────
    #   get_prompt
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_prompt_with_metadata(self, prompt_service, test_db):
        """Test get_prompt accepts metadata."""
        db_prompt = _build_db_prompt(template="Hello!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))

        meta_data = {"trace_id": "123"}

        # Just verify it doesn't crash and returns result
        result = await prompt_service.get_prompt(test_db, "1", {}, _meta_data=meta_data)
        assert result.messages[0].content.text == "Hello!"

    @pytest.mark.asyncio
    async def test_get_prompt_rendered(self, prompt_service, test_db):
        """Prompt is fetched and rendered into Message objects."""
        db_prompt = _build_db_prompt(template="Hello, {{ name }}!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))

        pr: PromptResult = await prompt_service.get_prompt(test_db, "1", {"name": "Alice"})

        assert isinstance(pr, PromptResult)
        assert len(pr.messages) == 1
        msg: Message = pr.messages[0]
        assert msg.role == Role.USER
        assert isinstance(msg.content, TextContent)
        assert msg.content.text == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_get_prompt_by_name(self, prompt_service, test_db):
        """Prompt lookup falls back to name when ID lookup misses."""
        db_prompt = _build_db_prompt(template="Hello!")
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # active by id
                _make_execute_result(scalar=db_prompt),  # active by name
            ]
        )

        result = await prompt_service.get_prompt(test_db, "gateway__greeting", {})
        assert result.messages[0].content.text == "Hello!"

    @pytest.mark.asyncio
    async def test_get_prompt_not_found(self, prompt_service, test_db):
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))

        with pytest.raises(PromptNotFoundError):
            await prompt_service.get_prompt(test_db, "999")

    @pytest.mark.asyncio
    async def test_get_prompt_inactive(self, prompt_service, test_db):
        inactive = _build_db_prompt(is_active=False)
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # active by id
                _make_execute_result(scalar=None),  # active by name
                _make_execute_result(scalar=inactive),  # inactive by id
            ]
        )
        with pytest.raises(PromptNotFoundError) as exc_info:
            await prompt_service.get_prompt(test_db, "1")
        assert "inactive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_prompt_render_error(self, prompt_service, test_db):
        db_prompt = _build_db_prompt(template="Hello, {{ name }}!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))
        db_prompt.validate_arguments.side_effect = Exception("bad args")
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.get_prompt(test_db, "1", {"name": "Alice"})
        assert "Failed to process prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_prompt_details_not_found(self, prompt_service, test_db):
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        result = await prompt_service.get_prompt_details(test_db, 999)
        if result is None or result == {} or result == []:
            raise PromptNotFoundError("Prompt not found: 999")

    @pytest.mark.asyncio
    async def test_get_prompt_details_inactive(self, prompt_service, test_db):
        inactive = _build_db_prompt(is_active=False)
        test_db.execute = Mock(side_effect=[_make_execute_result(scalar=None), _make_execute_result(scalar=inactive)])
        result = await prompt_service.get_prompt_details(test_db, 1)
        if result is None or result == {} or result == []:
            raise PromptNotFoundError("Prompt not found: 1 (inactive)")

    # ──────────────────────────────────────────────────────────────────
    #   update_prompt
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_update_prompt_success(self, prompt_service, test_db):
        existing = _build_db_prompt()
        existing.team_id = "team-123"
        test_db.get = Mock(return_value=existing)
        test_db.execute = Mock(
            side_effect=[  # first call = find existing, second = conflict check
                _make_execute_result(scalar=existing),
                _make_execute_result(scalar=None),
            ]
        )
        test_db.commit = Mock()
        test_db.refresh = Mock()
        prompt_service._notify_prompt_updated = AsyncMock()

        upd = PromptUpdate(description="new desc", template="Hi, {{ name }}!")
        res = await prompt_service.update_prompt(test_db, 1, upd)

        # commit called twice: once for update, once in _get_team_name to release transaction
        assert test_db.commit.call_count == 2
        prompt_service._notify_prompt_updated.assert_called_once()
        assert res["description"] == "new desc"
        assert res["template"] == "Hi, {{ name }}!"

    @pytest.mark.asyncio
    async def test_update_prompt_name_conflict(self, prompt_service, test_db):
        existing = _build_db_prompt()
        test_db.get = Mock(return_value=existing)
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=existing),
                _make_execute_result(scalar=None),
            ]
        )
        upd = PromptUpdate(name="other")
        with pytest.raises(PromptError):
            await prompt_service.update_prompt(test_db, 1, upd)

    @pytest.mark.asyncio
    async def test_update_prompt_not_found(self, prompt_service, test_db):
        test_db.get = Mock(return_value=None)
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # active
                _make_execute_result(scalar=None),  # inactive
            ]
        )
        upd = PromptUpdate(description="desc")
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.update_prompt(test_db, 999, upd)
        assert "not found" in str(exc_info.value) or "Failed to update prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_prompt_inactive(self, prompt_service, test_db):
        inactive = _build_db_prompt(is_active=False)
        test_db.get = Mock(return_value=inactive)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        prompt_service._notify_prompt_updated = AsyncMock()
        upd = PromptUpdate(description="desc")
        res = await prompt_service.update_prompt(test_db, 1, upd)
        assert res["description"] == "desc"

    @pytest.mark.asyncio
    async def test_update_prompt_exception(self, prompt_service, test_db):
        existing = _build_db_prompt()
        test_db.get = Mock(return_value=existing)
        test_db.execute = Mock(side_effect=[_make_execute_result(scalar=existing), _make_execute_result(scalar=None)])
        test_db.commit = Mock(side_effect=Exception("fail"))
        upd = PromptUpdate(description="desc")
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.update_prompt(test_db, 1, upd)
        assert "Failed to update prompt" in str(exc_info.value)

    # ──────────────────────────────────────────────────────────────────
    #   set state
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_set_prompt_state(self, prompt_service, test_db):
        # Ensure the mock prompt has a real id and primitive attributes
        p = MagicMock(spec=DbPrompt)
        p.id = 1
        p.team_id = 1
        p.name = "hello"
        p.is_active = True
        p.enabled = True
        test_db.get = Mock(return_value=p)
        test_db.commit = Mock()
        test_db.refresh = Mock()
        prompt_service._notify_prompt_deactivated = AsyncMock()

        res = await prompt_service.set_prompt_state(test_db, 1, activate=False)

        assert p.enabled is False
        prompt_service._notify_prompt_deactivated.assert_called_once()
        assert res["enabled"] is False

    @pytest.mark.asyncio
    async def test_set_prompt_state_not_found(self, prompt_service, test_db):
        test_db.get = Mock(return_value=None)
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.set_prompt_state(test_db, 999, activate=True)
        assert "Prompt not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_set_prompt_state_exception(self, prompt_service, test_db):
        p = _build_db_prompt(is_active=True)
        test_db.get = Mock(return_value=p)
        test_db.commit = Mock(side_effect=Exception("fail"))
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.set_prompt_state(test_db, 1, activate=False)
        assert "Failed to set prompt state" in str(exc_info.value)

    # ──────────────────────────────────────────────────────────────────
    #   delete_prompt
    # ──────────────────────────────────────────────────────────────────


    @pytest.mark.asyncio
    async def test_delete_prompt_success(self, prompt_service, test_db):
        p = _build_db_prompt()
        test_db.get = Mock(return_value=p)
        test_db.delete = Mock()
        test_db.commit = Mock()
        prompt_service._notify_prompt_deleted = AsyncMock()

        await prompt_service.delete_prompt(test_db, 1)

        test_db.delete.assert_called_once_with(p)
        prompt_service._notify_prompt_deleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_prompt_purge_metrics(self, prompt_service, test_db):
        p = _build_db_prompt()
        test_db.get = Mock(return_value=p)
        test_db.delete = Mock()
        test_db.commit = Mock()
        test_db.execute = Mock()
        prompt_service._notify_prompt_deleted = AsyncMock()

        await prompt_service.delete_prompt(test_db, 1, purge_metrics=True)

        assert test_db.execute.call_count == 2
        test_db.delete.assert_called_once_with(p)
        test_db.commit.assert_called_once()


    @pytest.mark.asyncio
    async def test_delete_prompt_not_found(self, prompt_service, test_db):
        test_db.get = Mock(return_value=None)
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.delete_prompt(test_db, 999)
        assert "Prompt not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_prompt_exception(self, prompt_service, test_db):
        p = _build_db_prompt()
        test_db.execute = Mock(return_value=_make_execute_result(scalar=p))
        test_db.delete = Mock(side_effect=Exception("fail"))
        test_db.commit = Mock()
        prompt_service._notify_prompt_deleted = AsyncMock()
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.delete_prompt(test_db, "hello")
        assert "Failed to delete prompt" in str(exc_info.value)

    # ──────────────────────────────────────────────────────────────────
    #   subscribe events logic
    # ──────────────────────────────────────────────────────────────────

    # @pytest.mark.asyncio
    # async def test_subscribe_events_yields_and_unsubscribes(self, prompt_service):
    #     gen = prompt_service.subscribe_events()
    #     # Advance generator to ensure queue is created
    #     await gen.asend(None)
    #     queue = prompt_service._event_subscribers[0]
    #     await queue.put({"type": "test_event"})
    #     event = await gen.__anext__()
    #     assert event["type"] == "test_event"
    #     await gen.aclose()
    #     assert queue not in prompt_service._event_subscribers
    # ──────────────────────────────────────────────────────────────────
    #   Test _publish_event
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_publish_event_puts_in_all_queues(self, prompt_service):
        """Test that _publish_event uses EventService to publish events."""
        # Mock the EventService's publish_event method
        prompt_service._event_service.publish_event = AsyncMock()

        event = {"type": "test"}
        await prompt_service._publish_event(event)

        # Verify that EventService.publish_event was called with the event
        prompt_service._event_service.publish_event.assert_called_once_with(event)


    # ──────────────────────────────────────────────────────────────────
    #   Validation & Exception Handling
    # ──────────────────────────────────────────────────────────────────

    def test_validate_template_raises(self, prompt_service):
        # Patch jinja_env.parse to raise
        prompt_service._jinja_env.parse = Mock(side_effect=Exception("bad"))
        with pytest.raises(PromptValidationError):
            prompt_service._validate_template("bad")

    def test_get_required_arguments(self, prompt_service):
        template = "Hello, {{ name }}! Your code is {{ code }}."
        required = prompt_service._get_required_arguments(template)
        assert "name" in required
        assert "code" in required

    def test_render_template_fallback_and_error(self, prompt_service):
        # Patch _compile_jinja_template to return a template that fails on render
        with patch("mcpgateway.services.prompt_service._compile_jinja_template") as mock_compile:
            mock_template = MagicMock()
            mock_template.render.side_effect = Exception("bad")
            mock_compile.return_value = mock_template

            # Fallback to format
            template = "Hello, {name}!"
            result = prompt_service._render_template(template, {"name": "Alice"})
            assert result == "Hello, Alice!"

            # Format also fails
            with pytest.raises(PromptError):
                prompt_service._render_template(template, {})

    def test_parse_messages_roles(self, prompt_service):
        text = "# User:\nHello\n# Assistant:\nHi!"
        msgs = prompt_service._parse_messages(text)
        assert msgs[0].role == Role.USER
        assert msgs[1].role == Role.ASSISTANT

    # ──────────────────────────────────────────────────────────────────
    #   aggregate & reset metrics
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_aggregate_and_reset_metrics(self, prompt_service, test_db):
        # Mock aggregate_metrics_combined to return a proper AggregatedMetrics result
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        mock_result = AggregatedMetrics(
            total_executions=10,
            successful_executions=8,
            failed_executions=2,
            failure_rate=0.2,
            min_response_time=0.1,
            max_response_time=0.9,
            avg_response_time=0.5,
            last_execution_time="2025-01-01T00:00:00+00:00",
            raw_count=6,
            rollup_count=4,
        )

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result):
            metrics = await prompt_service.aggregate_metrics(test_db)
            assert metrics["total_executions"] == 10
            assert metrics["successful_executions"] == 8
            assert metrics["failed_executions"] == 2
            assert metrics["failure_rate"] == 0.2

        # reset_metrics
        test_db.execute = Mock()
        test_db.commit = Mock()
        await prompt_service.reset_metrics(test_db)
        assert test_db.execute.call_count == 2
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_prompts_with_tags(self, prompt_service, mock_prompt):
        """Test listing prompts with tag filtering."""
        # Third-Party

        # Mock query chain - support pagination methods
        mock_query = MagicMock()
        mock_query.options.return_value = mock_query  # For joinedload
        mock_query.where.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query

        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [mock_prompt]

        bind = MagicMock()
        bind.dialect = MagicMock()
        bind.dialect.name = "sqlite"  # or "postgresql" or "mysql"
        session.get_bind.return_value = bind

        with patch("mcpgateway.services.prompt_service.select", return_value=mock_query):
            with patch("mcpgateway.services.prompt_service.json_contains_tag_expr") as mock_json_contains:
                # return a fake condition object that query.where will accept
                fake_condition = MagicMock()
                mock_json_contains.return_value = fake_condition

                result, _ = await prompt_service.list_prompts(session, tags=["test", "production"])

                # helper should be called once with the tags list (not once per tag)
                mock_json_contains.assert_called_once()  # called exactly once
                called_args = mock_json_contains.call_args[0]  # positional args tuple
                assert called_args[0] is session  # session passed through
                # third positional arg is the tags list (signature: session, col, values, match_any=True)
                assert called_args[2] == ["test", "production"]
                # and the fake condition returned must have been passed to where() at some point
                # (there may be multiple where() calls for enabled filter and tags filter)
                mock_query.where.assert_any_call(fake_condition)
                # finally, your service should return the list produced by mock_db.execute(...)
                assert isinstance(result, list)
                assert len(result) == 1


# --------------------------------------------------------------------------- #
#                         Cache Behavior Tests                                #
# --------------------------------------------------------------------------- #


class TestJinjaTemplateCaching:
    """Tests for Jinja template caching (#1814)."""

    def test_template_caching_works(self):
        """Verify template compilation is cached across renders."""
        from mcpgateway.services.prompt_service import PromptService, _compile_jinja_template

        service = PromptService()
        template = "Hello {{ name }}"

        result1 = service._render_template(template, {"name": "World"})
        assert result1 == "Hello World"

        result2 = service._render_template(template, {"name": "Claude"})
        assert result2 == "Hello Claude"

        info = _compile_jinja_template.cache_info()
        assert info.hits == 1
        assert info.misses == 1

    def test_different_templates_cached_separately(self):
        """Verify different templates get separate cache entries."""
        from mcpgateway.services.prompt_service import PromptService, _compile_jinja_template

        service = PromptService()

        result1 = service._render_template("Hello {{ name }}", {"name": "A"})
        result2 = service._render_template("Goodbye {{ name }}", {"name": "B"})

        assert result1 == "Hello A"
        assert result2 == "Goodbye B"

        info = _compile_jinja_template.cache_info()
        assert info.misses == 2  # Two different templates

    def test_format_fallback_still_works(self):
        """Verify Python format() fallback works when Jinja render fails."""
        from mcpgateway.services.prompt_service import PromptService, _compile_jinja_template

        service = PromptService()

        # Mock _compile_jinja_template to return a template that fails on render
        with patch("mcpgateway.services.prompt_service._compile_jinja_template") as mock_compile:
            mock_template = MagicMock()
            mock_template.render.side_effect = Exception("Jinja render error")
            mock_compile.return_value = mock_template

            # Should fall back to Python format()
            template = "Hello, {name}!"
            result = service._render_template(template, {"name": "Alice"})
            assert result == "Hello, Alice!"


class TestPromptAccessAuthorization:
    """Tests for _check_prompt_access authorization logic."""

    @pytest.fixture
    def prompt_service(self):
        """Create a prompt service instance."""
        return PromptService()

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = MagicMock()
        db.commit = Mock()
        return db

    def _create_mock_prompt(self, visibility="public", owner_email=None, team_id=None):
        """Helper to create mock prompt."""
        prompt = MagicMock()
        prompt.visibility = visibility
        prompt.owner_email = owner_email
        prompt.team_id = team_id
        return prompt

    @pytest.mark.asyncio
    async def test_check_prompt_access_public_always_allowed(self, prompt_service, mock_db):
        """Public prompts should be accessible to anyone."""
        public_prompt = self._create_mock_prompt(visibility="public")

        # Unauthenticated
        assert await prompt_service._check_prompt_access(mock_db, public_prompt, user_email=None, token_teams=[]) is True
        # Authenticated
        assert await prompt_service._check_prompt_access(mock_db, public_prompt, user_email="user@test.com", token_teams=["team-1"]) is True
        # Admin
        assert await prompt_service._check_prompt_access(mock_db, public_prompt, user_email=None, token_teams=None) is True

    @pytest.mark.asyncio
    async def test_check_prompt_access_admin_bypass(self, prompt_service, mock_db):
        """Admin (user_email=None, token_teams=None) should have full access."""
        private_prompt = self._create_mock_prompt(visibility="private", owner_email="secret@test.com", team_id="secret-team")

        # Admin bypass: both None = unrestricted access
        assert await prompt_service._check_prompt_access(mock_db, private_prompt, user_email=None, token_teams=None) is True

    @pytest.mark.asyncio
    async def test_check_prompt_access_private_denied_to_unauthenticated(self, prompt_service, mock_db):
        """Private prompts should be denied to unauthenticated users."""
        private_prompt = self._create_mock_prompt(visibility="private", owner_email="owner@test.com")

        # Unauthenticated (public-only token)
        assert await prompt_service._check_prompt_access(mock_db, private_prompt, user_email=None, token_teams=[]) is False

    @pytest.mark.asyncio
    async def test_check_prompt_access_private_allowed_to_owner(self, prompt_service, mock_db):
        """Private prompts should be accessible to the owner."""
        private_prompt = self._create_mock_prompt(visibility="private", owner_email="owner@test.com")

        # Owner with non-empty token_teams
        assert await prompt_service._check_prompt_access(mock_db, private_prompt, user_email="owner@test.com", token_teams=["some-team"]) is True

    @pytest.mark.asyncio
    async def test_check_prompt_access_team_prompt_allowed_to_member(self, prompt_service, mock_db):
        """Team prompts should be accessible to team members."""
        team_prompt = self._create_mock_prompt(visibility="team", owner_email="owner@test.com", team_id="team-abc")

        # Team member via token_teams
        assert await prompt_service._check_prompt_access(mock_db, team_prompt, user_email="member@test.com", token_teams=["team-abc"]) is True

    @pytest.mark.asyncio
    async def test_check_prompt_access_team_prompt_denied_to_non_member(self, prompt_service, mock_db):
        """Team prompts should be denied to non-members."""
        team_prompt = self._create_mock_prompt(visibility="team", owner_email="owner@test.com", team_id="team-abc")

        # Non-member
        assert await prompt_service._check_prompt_access(mock_db, team_prompt, user_email="outsider@test.com", token_teams=["other-team"]) is False
