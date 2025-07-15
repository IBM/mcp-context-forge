# -*- coding: utf-8 -*-
"""
Unit-tests for PromptService.

All tests run entirely with `MagicMock` / `AsyncMock`; no live DB or Jinja
environment is required.  Where `PromptService` returns Pydantic models we
monkey-patch the `model_validate` method so that it simply echoes the raw
dict we pass in - that keeps validation out of scope for these pure-unit
tests.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock

# Third-Party
import pytest
import asyncio
# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import PromptMetric
from mcpgateway.models import Message, PromptResult, Role
from mcpgateway.schemas import PromptCreate, PromptRead, PromptUpdate
from mcpgateway.services.prompt_service import (
    PromptError,
    PromptNotFoundError,
    PromptService,
    PromptValidationError
)
from sqlalchemy.exc import IntegrityError
# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_execute_result(*, scalar: Any = None, scalars_list: Optional[list] = None):
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
    p.description = desc
    p.template = template
    p.argument_schema = {"properties": {"name": {"type": "string"}}, "required": ["name"]}
    p.created_at = p.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    p.is_active = is_active
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

        with pytest.raises(PromptError) as exc_info:
            await prompt_service.register_prompt(test_db, pc)

        assert "already exists" in str(exc_info.value)
    
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
    async def test_register_prompt_integrity_error(self, prompt_service, test_db):
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add, test_db.commit, test_db.refresh = Mock(), Mock(), Mock()
        prompt_service._notify_prompt_added = AsyncMock()
        test_db.commit.side_effect = IntegrityError("fail", None, None)
        pc = PromptCreate(name="fail", description="", template="ok", arguments=[])
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.register_prompt(test_db, pc)
        assert "already exists" in str(exc_info.value)
    # ──────────────────────────────────────────────────────────────────
    #   get_prompt
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_prompt_rendered(self, prompt_service, test_db):
        """Prompt is fetched and rendered into Message objects."""
        db_prompt = _build_db_prompt(template="Hello, {{ name }}!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))

        pr: PromptResult = await prompt_service.get_prompt(test_db, "hello", {"name": "Alice"})

        assert isinstance(pr, PromptResult)
        assert len(pr.messages) == 1
        msg: Message = pr.messages[0]
        assert msg.role == Role.USER
        assert msg.content.text == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_get_prompt_not_found(self, prompt_service, test_db):
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))

        with pytest.raises(PromptNotFoundError):
            await prompt_service.get_prompt(test_db, "missing")
    
    @pytest.mark.asyncio
    async def test_get_prompt_inactive(self, prompt_service, test_db):
        inactive = _build_db_prompt(is_active=False)
        test_db.execute = Mock(side_effect=[
            _make_execute_result(scalar=None),  # active
            _make_execute_result(scalar=inactive),  # inactive
        ])
        with pytest.raises(PromptNotFoundError) as exc_info:
            await prompt_service.get_prompt(test_db, "hello")
        assert "inactive" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_prompt_render_error(self, prompt_service, test_db):
        db_prompt = _build_db_prompt(template="Hello, {{ name }}!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))
        db_prompt.validate_arguments.side_effect = Exception("bad args")
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.get_prompt(test_db, "hello", {"name": "Alice"})
        assert "Failed to process prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_prompt_details_not_found(self, prompt_service, test_db):
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        with pytest.raises(PromptNotFoundError):
            await prompt_service.get_prompt_details(test_db, "missing")

    @pytest.mark.asyncio
    async def test_get_prompt_details_inactive(self, prompt_service, test_db):
        inactive = _build_db_prompt(is_active=False)
        test_db.execute = Mock(side_effect=[_make_execute_result(scalar=None), _make_execute_result(scalar=inactive)])
        with pytest.raises(PromptNotFoundError):
            await prompt_service.get_prompt_details(test_db, "hello")


    # ──────────────────────────────────────────────────────────────────
    #   update_prompt
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_update_prompt_success(self, prompt_service, test_db):
        existing = _build_db_prompt()
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
        res = await prompt_service.update_prompt(test_db, "hello", upd)

        test_db.commit.assert_called_once()
        prompt_service._notify_prompt_updated.assert_called_once()
        assert res["description"] == "new desc"
        assert res["template"] == "Hi, {{ name }}!"

    @pytest.mark.asyncio
    async def test_update_prompt_name_conflict(self, prompt_service, test_db):
        existing = _build_db_prompt()
        conflicting = _build_db_prompt(pid=2, name="other")
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=existing),
                _make_execute_result(scalar=conflicting),
            ]
        )
        upd = PromptUpdate(name="other")
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.update_prompt(test_db, "hello", upd)

        assert "already exists" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_prompt_not_found(self, prompt_service, test_db):
        test_db.execute = Mock(side_effect=[
            _make_execute_result(scalar=None),  # active
            _make_execute_result(scalar=None),  # inactive
        ])
        upd = PromptUpdate(description="desc")
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.update_prompt(test_db, "missing", upd)
        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_prompt_inactive(self, prompt_service, test_db):
        inactive = _build_db_prompt(is_active=False)
        test_db.execute = Mock(side_effect=[
            _make_execute_result(scalar=None),  # active
            _make_execute_result(scalar=inactive),  # inactive
        ])
        upd = PromptUpdate(description="desc")
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.update_prompt(test_db, "hello", upd)
        assert "inactive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_prompt_exception(self, prompt_service, test_db):
        existing = _build_db_prompt()
        test_db.execute = Mock(side_effect=[_make_execute_result(scalar=existing), _make_execute_result(scalar=None)])
        test_db.commit = Mock(side_effect=Exception("fail"))
        upd = PromptUpdate(description="desc")
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.update_prompt(test_db, "hello", upd)
        assert "Failed to update prompt" in str(exc_info.value)

    # ──────────────────────────────────────────────────────────────────
    #   toggle status
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_toggle_prompt_status(self, prompt_service, test_db):
        p = _build_db_prompt(is_active=True)
        test_db.get, test_db.commit, test_db.refresh = Mock(return_value=p), Mock(), Mock()
        prompt_service._notify_prompt_deactivated = AsyncMock()

        res = await prompt_service.toggle_prompt_status(test_db, 1, activate=False)

        assert p.is_active is False
        prompt_service._notify_prompt_deactivated.assert_called_once()
        assert res["is_active"] is False

    @pytest.mark.asyncio
    async def test_toggle_prompt_status_not_found(self, prompt_service, test_db):
        test_db.get = Mock(return_value=None)
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.toggle_prompt_status(test_db, 999, activate=True)
        assert "Prompt not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_toggle_prompt_status_exception(self, prompt_service, test_db):
        p = _build_db_prompt(is_active=True)
        test_db.get = Mock(return_value=p)
        test_db.commit = Mock(side_effect=Exception("fail"))
        with pytest.raises(PromptError) as exc_info:
            await prompt_service.toggle_prompt_status(test_db, 1, activate=False)
        assert "Failed to toggle prompt status" in str(exc_info.value)

    # ──────────────────────────────────────────────────────────────────
    #   delete_prompt
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_prompt_success(self, prompt_service, test_db):
        p = _build_db_prompt()
        test_db.execute = Mock(return_value=_make_execute_result(scalar=p))
        test_db.delete, test_db.commit = Mock(), Mock()
        prompt_service._notify_prompt_deleted = AsyncMock()

        await prompt_service.delete_prompt(test_db, "hello")

        test_db.delete.assert_called_once_with(p)
        prompt_service._notify_prompt_deleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_prompt_not_found(self, prompt_service, test_db):
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        with pytest.raises(PromptNotFoundError):
            await prompt_service.delete_prompt(test_db, "missing")

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
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        prompt_service._event_subscribers.extend([q1, q2])
        event = {"type": "test"}
        await prompt_service._publish_event(event)
        assert await q1.get() == event
        assert await q2.get() == event

    # ──────────────────────────────────────────────────────────────────
    #   Validation & Exception Handling
    # ──────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
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
    
    def test_get_required_arguments(self, prompt_service):
        template = "Hello, {{ name }}! Your code is {{ code }}."
        required = prompt_service._get_required_arguments(template)
        assert "name" in required
        assert "code" in required
    
    def test_render_template_fallback_and_error(self, prompt_service):
        # Patch jinja_env.from_string to raise
        prompt_service._jinja_env.from_string = Mock(side_effect=Exception("bad"))
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
        # Metrics numbers to be returned by scalar() calls
        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=10),  # total
                _make_execute_result(scalar=8),  # successful
                _make_execute_result(scalar=2),  # failed
                _make_execute_result(scalar=0.1),  # min_rt
                _make_execute_result(scalar=0.9),  # max_rt
                _make_execute_result(scalar=0.5),  # avg_rt
                _make_execute_result(scalar=datetime(2025, 1, 1, tzinfo=timezone.utc)),  # last_time
            ]
        )

        metrics = await prompt_service.aggregate_metrics(test_db)
        assert metrics["total_executions"] == 10
        assert metrics["successful_executions"] == 8
        assert metrics["failed_executions"] == 2
        assert metrics["failure_rate"] == 0.2

        # reset_metrics
        test_db.execute = Mock()
        test_db.commit = Mock()
        await prompt_service.reset_metrics(test_db)
        test_db.execute.assert_called()
        test_db.commit.assert_called_once()
