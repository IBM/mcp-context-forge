# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_prompt_audit_no_db.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Regression tests: audit_trail.log_action() must NEVER receive a shared
``db`` session from prompt-service CRUD paths.

Passing the caller's ``db`` session caused inactive-transaction errors
when the audit trail wrote to the same connection that the CRUD operation
was using.  The fix ensures each audit write creates its own session.

These tests call the real service methods (with a mocked DB layer) and
then assert that every ``audit_trail.log_action()`` invocation was
performed **without** a ``db`` keyword argument.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.schemas import PromptCreate, PromptRead, PromptUpdate
from mcpgateway.services.prompt_service import PromptError, PromptService


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_execute_result(*, scalar: Any = None, scalars_list: list | None = None) -> MagicMock:
    """Return a MagicMock that mimics a SQLAlchemy Result object."""
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
    p.enabled = is_active
    p.visibility = "public"
    p.team_id = None
    p.owner_email = "owner@example.com"
    p.gateway_id = None
    p.gateway = None
    p.metrics = []
    p.validate_arguments = Mock()
    return p


def _assert_no_db_passed(mock_audit: MagicMock, *, expected_action: str | None = None, resource_type: str | None = None) -> None:
    """Assert that none of the log_action calls received a ``db`` argument."""
    calls = mock_audit.log_action.call_args_list
    for call in calls:
        assert "db" not in call.kwargs, (
            f"audit_trail.log_action() was called with db= keyword argument: {call}"
        )
        # db is the 22nd positional parameter (0-indexed) after self;
        # if passed positionally it would appear at index 22 in args.
        assert len(call.args) < 23, (
            f"audit_trail.log_action() received too many positional args (db may be positional): {call}"
        )
    if expected_action is not None:
        actions = [call.kwargs.get("action") for call in calls]
        assert expected_action in actions, f"expected action {expected_action!r} not found in calls: {actions}"
    if resource_type is not None:
        for call in calls:
            assert call.kwargs.get("resource_type") == resource_type, f"unexpected resource_type in call: {call}"


# ---------------------------------------------------------------------------
# auto-use fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_promptread(monkeypatch):
    """Bypass Pydantic validation: make PromptRead.model_validate a pass-through."""
    monkeypatch.setattr(PromptRead, "model_validate", staticmethod(lambda d: d))


@pytest.fixture(autouse=True)
def reset_jinja_singleton():
    """Reset the module-level Jinja environment singleton before each test."""
    import mcpgateway.services.prompt_service as ps

    ps._JINJA_ENV = None
    ps._compile_jinja_template.cache_clear()
    yield
    ps._JINJA_ENV = None
    ps._compile_jinja_template.cache_clear()


@pytest.fixture
def prompt_service():
    return PromptService()


# ---------------------------------------------------------------------------
# Regression: audit_trail.log_action must NOT receive db=
# ---------------------------------------------------------------------------


class TestAuditTrailNoDbSession:
    """Regression suite: CRUD audit calls must not pass the shared db session."""

    @pytest.mark.asyncio
    async def test_create_prompt_audit_no_db_kwarg(self, prompt_service, test_db):
        """register_prompt must call audit_trail.log_action without db=."""
        with patch("mcpgateway.services.prompt_service.audit_trail") as mock_audit, \
             patch("mcpgateway.services.prompt_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)

            test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
            test_db.add = Mock()
            test_db.commit = Mock()
            test_db.refresh = Mock()
            prompt_service._notify_prompt_added = AsyncMock()

            pc = PromptCreate(
                name="audit-test",
                description="regression test",
                template="Hello {{ name }}!",
                arguments=[],
            )

            await prompt_service.register_prompt(db=test_db, prompt=pc, created_by="tester")

            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="create_prompt", resource_type="prompt")

    @pytest.mark.asyncio
    async def test_register_prompt_audit_failure_does_not_block_already_committed_prompt(self, prompt_service, test_db):
        """If audit_trail.log_action() raises, the prompt row is already committed (db.commit ran first)."""
        with patch("mcpgateway.services.prompt_service.audit_trail") as mock_audit, \
             patch("mcpgateway.services.prompt_service.structured_logger"):
            mock_audit.log_action = MagicMock(side_effect=Exception("audit backend unavailable"))

            prompt_service._notify_prompt_added = AsyncMock()

            pc = PromptCreate(
                name="audit-failure-test",
                description="regression test",
                template="Hello {{ name }}!",
                arguments=[],
            )

            with pytest.raises(PromptError):
                await prompt_service.register_prompt(db=test_db, prompt=pc, created_by="tester")

            committed = test_db.query(DbPrompt).filter(DbPrompt.name == "audit-failure-test").one_or_none()
            assert committed is not None, "prompt row should already be committed before audit_trail.log_action() runs"

    @pytest.mark.asyncio
    async def test_get_prompt_audit_no_db_kwarg(self, prompt_service, test_db):
        """get_prompt must call audit_trail.log_action without db=."""
        with patch("mcpgateway.services.prompt_service.audit_trail") as mock_audit, \
             patch("mcpgateway.services.prompt_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)

            fake_prompt = _build_db_prompt(pid=42, name="view-test", template="Hello!")
            test_db.execute = Mock(return_value=_make_execute_result(scalar=fake_prompt))

            await prompt_service.get_prompt(
                db=test_db,
                prompt_id="42",
                user="viewer",
            )

            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="view_prompt", resource_type="prompt")

    @pytest.mark.asyncio
    async def test_update_prompt_audit_no_db_kwarg(self, prompt_service, test_db):
        """update_prompt must call audit_trail.log_action without db=."""
        with patch("mcpgateway.services.prompt_service.audit_trail") as mock_audit, \
             patch("mcpgateway.services.prompt_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)

            fake_prompt = _build_db_prompt(pid=10, name="update-test")
            fake_prompt.team_id = "team-123"
            test_db.get = Mock(return_value=fake_prompt)
            test_db.execute = Mock(
                side_effect=[
                    _make_execute_result(scalar=fake_prompt),
                    _make_execute_result(scalar=None),
                ]
            )
            test_db.commit = Mock()
            test_db.refresh = Mock()
            prompt_service._notify_prompt_updated = AsyncMock()

            pu = PromptUpdate(description="updated description")

            await prompt_service.update_prompt(
                db=test_db,
                prompt_id=10,
                prompt_update=pu,
                modified_by="updater",
            )

            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="update_prompt", resource_type="prompt")

    @pytest.mark.asyncio
    async def test_delete_prompt_audit_no_db_kwarg(self, prompt_service, test_db):
        """delete_prompt must call audit_trail.log_action without db=."""
        with patch("mcpgateway.services.prompt_service.audit_trail") as mock_audit, \
             patch("mcpgateway.services.prompt_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)

            fake_prompt = _build_db_prompt(pid=99, name="delete-test")
            test_db.get = Mock(return_value=fake_prompt)
            test_db.delete = Mock()
            test_db.commit = Mock()
            prompt_service._notify_prompt_deleted = AsyncMock()

            await prompt_service.delete_prompt(
                db=test_db,
                prompt_id=99,
            )

            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="delete_prompt", resource_type="prompt")

    @pytest.mark.asyncio
    async def test_set_prompt_state_audit_no_db_kwarg(self, prompt_service, test_db):
        """set_prompt_state must call audit_trail.log_action without db=."""
        with patch("mcpgateway.services.prompt_service.audit_trail") as mock_audit, \
             patch("mcpgateway.services.prompt_service.structured_logger"), \
             patch("mcpgateway.services.prompt_service.get_for_update") as mock_gfu:
            mock_audit.log_action = MagicMock(return_value=None)

            fake_prompt = _build_db_prompt(pid=5, name="state-test")
            fake_prompt.enabled = False  # starting deactivated so activate=True triggers audit
            mock_gfu.return_value = fake_prompt

            test_db.commit = Mock()
            test_db.refresh = Mock()
            prompt_service._notify_prompt_activated = AsyncMock()
            prompt_service._get_team_name = Mock(return_value=None)
            prompt_service.convert_prompt_to_read = Mock(return_value={})

            await prompt_service.set_prompt_state(
                db=test_db,
                prompt_id=5,
                activate=True,
            )

            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="set_prompt_state", resource_type="prompt")

    @pytest.mark.asyncio
    async def test_get_prompt_details_audit_no_db_kwarg(self, prompt_service, test_db):
        """get_prompt_details must call audit_trail.log_action without db=."""
        with patch("mcpgateway.services.prompt_service.audit_trail") as mock_audit, \
             patch("mcpgateway.services.prompt_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)

            fake_prompt = _build_db_prompt(pid=7, name="details-test")
            test_db.get = Mock(return_value=fake_prompt)
            prompt_service._check_prompt_access = AsyncMock(return_value=True)
            prompt_service._get_team_name = Mock(return_value=None)
            prompt_service.convert_prompt_to_read = Mock(return_value={})

            await prompt_service.get_prompt_details(
                db=test_db,
                prompt_id=7,
            )

            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="view_prompt_details", resource_type="prompt")
