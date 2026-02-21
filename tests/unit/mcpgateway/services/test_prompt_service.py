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
from types import SimpleNamespace
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
from mcpgateway.schemas import PromptArgument, PromptCreate, PromptRead, PromptUpdate

from mcpgateway.services.prompt_service import (
    PromptError,
    PromptNameConflictError,
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


class TestPromptServiceInit:
    def test_plugins_enabled_env_flag_false_disables_plugin_manager(self, monkeypatch):
        """Cover env-override parsing in PromptService.__init__ (PLUGINS_ENABLED)."""
        monkeypatch.setenv("PLUGINS_ENABLED", " false ")
        svc = PromptService()
        assert svc._plugin_manager is None


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
    async def test_register_prompt_argument_description_included_in_schema(self, prompt_service, test_db):
        """Cover argument.description -> schema['description'] branch."""
        test_db.execute = Mock(return_value=_make_execute_result(scalar=None))
        test_db.add, test_db.commit, test_db.refresh = Mock(), Mock(), Mock()
        prompt_service._notify_prompt_added = AsyncMock()

        with (
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache,
            patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_metrics_cache,
        ):
            mock_cache = AsyncMock()
            mock_cache.invalidate_prompts = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_admin_cache.invalidate_tags = AsyncMock()
            mock_metrics_cache.invalidate_prefix_async = AsyncMock()
            mock_metrics_cache.invalidate_async = AsyncMock()

            pc = PromptCreate(
                name="hello",
                description="greet a user",
                template="Hello {{ name }}!",
                arguments=[PromptArgument(name="name", description="who")],
            )

            res = await prompt_service.register_prompt(test_db, pc)

        assert res["arguments"][0]["description"] == "who"
        assert res["arguments"][0]["required"] is True

    @pytest.mark.asyncio
    async def test_register_prompt_gateway_relationship_is_set(self, prompt_service, test_db):
        """Cover gateway relationship assignment when gateway_id resolves to a gateway."""
        gateway = MagicMock()
        gateway.id = "gw-1"
        gateway.name = "Gateway One"

        test_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=gateway),  # gateway lookup
                _make_execute_result(scalar=None),  # conflict check
            ]
        )
        test_db.add, test_db.commit, test_db.refresh = Mock(), Mock(), Mock()
        prompt_service._notify_prompt_added = AsyncMock()

        with (
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache,
            patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_metrics_cache,
        ):
            mock_cache = AsyncMock()
            mock_cache.invalidate_prompts = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_admin_cache.invalidate_tags = AsyncMock()
            mock_metrics_cache.invalidate_prefix_async = AsyncMock()
            mock_metrics_cache.invalidate_async = AsyncMock()

            pc = PromptCreate(
                name="hello",
                description="greet a user",
                template="Hello!",
                arguments=[],
                gateway_id="gw-1",
            )

            _ = await prompt_service.register_prompt(test_db, pc)

        added = test_db.add.call_args.args[0]
        assert added.gateway is gateway
        assert getattr(added, "gateway_name_cache") == "Gateway One"

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
    async def test_register_prompt_team_visibility_conflict_hits_team_branch(self, prompt_service, test_db):
        """Existing team prompt with same name+team_id triggers the team conflict branch."""
        existing = MagicMock()
        existing.enabled = True
        existing.id = 123
        existing.visibility = "team"
        test_db.execute = Mock(return_value=_make_execute_result(scalar=existing))
        test_db.rollback = Mock()

        pc = PromptCreate(name="hello", description="", template="X", arguments=[])

        with pytest.raises(PromptNameConflictError):
            await prompt_service.register_prompt(test_db, pc, visibility="team", team_id="team-1")

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
    async def test_get_prompt_observability_start_span_exception_is_swallowed(self, prompt_service, test_db):
        """Covers start_span() exception path (should not break prompt rendering)."""
        from contextlib import contextmanager

        db_prompt = _build_db_prompt(template="Hello!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))

        obs = MagicMock()
        obs.start_span.side_effect = Exception("boom")

        @contextmanager
        def _no_span(*_a, **_kw):
            yield None

        with (
            patch("mcpgateway.services.prompt_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.prompt_service.ObservabilityService", return_value=obs),
            patch("mcpgateway.services.prompt_service.create_span", _no_span),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_get_buf,
        ):
            mock_trace.get.return_value = "trace-1"
            mock_get_buf.return_value.record_prompt_metric = Mock()
            result = await prompt_service.get_prompt(test_db, "1", {})

        assert result.messages[0].content.text == "Hello!"

    @pytest.mark.asyncio
    async def test_get_prompt_observability_end_span_success_and_metrics_error(self, prompt_service, test_db):
        """Covers observability span start+end plus metrics buffer exception handling."""
        from contextlib import contextmanager

        db_prompt = _build_db_prompt(template="Hello, {{ name }}!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))

        span = MagicMock()

        @contextmanager
        def _span_cm(*_a, **_kw):
            yield span

        obs = MagicMock()
        obs.start_span.return_value = "span-1"
        obs.end_span = Mock()

        metrics_buffer = MagicMock()
        metrics_buffer.record_prompt_metric.side_effect = Exception("metrics boom")

        with (
            patch("mcpgateway.services.prompt_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.prompt_service.ObservabilityService", return_value=obs),
            patch("mcpgateway.services.prompt_service.create_span", _span_cm),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=metrics_buffer),
        ):
            mock_trace.get.return_value = "trace-1"
            result = await prompt_service.get_prompt(test_db, "1", {"name": "Alice"})

        assert result.messages[0].content.text == "Hello, Alice!"
        obs.end_span.assert_called_once()
        span.set_attribute.assert_any_call("success", True)

    @pytest.mark.asyncio
    async def test_get_prompt_observability_end_span_exception_is_caught(self, prompt_service, test_db):
        from contextlib import contextmanager

        db_prompt = _build_db_prompt(template="Hello!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))

        @contextmanager
        def _no_span(*_a, **_kw):
            yield None

        obs = MagicMock()
        obs.start_span.return_value = "span-1"
        obs.end_span.side_effect = Exception("end boom")

        with (
            patch("mcpgateway.services.prompt_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.prompt_service.ObservabilityService", return_value=obs),
            patch("mcpgateway.services.prompt_service.create_span", _no_span),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_get_buf,
        ):
            mock_trace.get.return_value = "trace-1"
            mock_get_buf.return_value.record_prompt_metric = Mock()
            result = await prompt_service.get_prompt(test_db, "1", {})

        assert result.messages[0].content.text == "Hello!"

    @pytest.mark.asyncio
    async def test_get_prompt_access_denied_raises_generic_not_found(self, prompt_service, test_db):
        db_prompt = _build_db_prompt(template="Hello!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))
        prompt_service._check_prompt_access = AsyncMock(return_value=False)

        with patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_get_buf:
            mock_get_buf.return_value.record_prompt_metric = Mock()
            with pytest.raises(PromptNotFoundError, match="Prompt not found"):
                await prompt_service.get_prompt(test_db, "1", {})

    @pytest.mark.asyncio
    async def test_get_prompt_server_scoping_not_attached_raises_not_found(self, prompt_service, test_db):
        db_prompt = _build_db_prompt(template="Hello!")
        prompt_service._check_prompt_access = AsyncMock(return_value=True)

        server_match_result = MagicMock()
        server_match_result.first.return_value = None
        test_db.execute = Mock(side_effect=[_make_execute_result(scalar=db_prompt), server_match_result])

        with patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_get_buf:
            mock_get_buf.return_value.record_prompt_metric = Mock()
            with pytest.raises(PromptNotFoundError, match="Prompt not found"):
                await prompt_service.get_prompt(test_db, "1", {}, server_id="server-1")

    @pytest.mark.asyncio
    async def test_get_prompt_render_error_sets_span_attributes(self, prompt_service, test_db):
        """Covers span attribute setting on render errors."""
        from contextlib import contextmanager

        db_prompt = _build_db_prompt(template="Hello, {{ name }}!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))
        db_prompt.validate_arguments.side_effect = Exception("bad args")

        span = MagicMock()

        @contextmanager
        def _span_cm(*_a, **_kw):
            yield span

        with (
            patch("mcpgateway.services.prompt_service.create_span", _span_cm),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_get_buf,
        ):
            mock_get_buf.return_value.record_prompt_metric = Mock()
            with pytest.raises(PromptError, match="Failed to process prompt"):
                await prompt_service.get_prompt(test_db, "1", {"name": "Alice"})

        span.set_attribute.assert_any_call("error", True)

    @pytest.mark.asyncio
    async def test_get_prompt_plugin_pre_and_post_hooks_modify_payload_and_result(self, prompt_service, test_db):
        """Covers plugin hook paths including GlobalContext update when provided."""
        from contextlib import contextmanager
        from mcpgateway.plugins.framework import GlobalContext, PromptHookType, PromptPosthookPayload, PromptPrehookPayload

        db_prompt = _build_db_prompt(template="Hello, {{ name }}!")

        server_match_result = MagicMock()
        server_match_result.first.return_value = ("ok",)

        test_db.execute = Mock(side_effect=[_make_execute_result(scalar=db_prompt), server_match_result])

        plugin_mgr = MagicMock()
        plugin_mgr.has_hooks_for.side_effect = lambda hook: hook in {PromptHookType.PROMPT_PRE_FETCH, PromptHookType.PROMPT_POST_FETCH}

        pre_payload = PromptPrehookPayload(prompt_id="1", args={"name": "Alice"})
        pre_result = SimpleNamespace(modified_payload=pre_payload)

        modified = PromptResult(messages=[Message(role=Role.ASSISTANT, content=TextContent(type="text", text="post"))], description="post")
        post_payload = PromptPosthookPayload(prompt_id="1", result=modified)
        post_result = SimpleNamespace(modified_payload=post_payload)

        plugin_mgr.invoke_hook = AsyncMock(side_effect=[(pre_result, {"ctx": 1}), (post_result, {"ctx": 1})])

        prompt_service._plugin_manager = plugin_mgr

        @contextmanager
        def _no_span(*_a, **_kw):
            yield None

        global_ctx = GlobalContext(request_id="req-1")

        with (
            patch("mcpgateway.services.prompt_service.create_span", _no_span),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_get_buf,
        ):
            mock_get_buf.return_value.record_prompt_metric = Mock()
            result = await prompt_service.get_prompt(
                test_db,
                "1",
                {"name": "Bob"},
                user="user@test.com",
                server_id="server-1",
                tenant_id="tenant-1",
                plugin_context_table={"existing": True},
                plugin_global_context=global_ctx,
            )

        assert result.messages[0].role == Role.ASSISTANT
        assert result.messages[0].content.text == "post"
        assert global_ctx.user == "user@test.com"
        assert global_ctx.server_id == "server-1"
        assert global_ctx.tenant_id == "tenant-1"

    @pytest.mark.asyncio
    async def test_get_prompt_plugin_hooks_create_global_context_when_missing(self, prompt_service, test_db):
        """Covers GlobalContext creation fallback when middleware didn't provide one."""
        from contextlib import contextmanager
        from mcpgateway.plugins.framework import PromptHookType, PromptPrehookPayload

        db_prompt = _build_db_prompt(template="Hello, {{ name }}!")
        test_db.execute = Mock(return_value=_make_execute_result(scalar=db_prompt))

        plugin_mgr = MagicMock()
        plugin_mgr.has_hooks_for.side_effect = lambda hook: hook == PromptHookType.PROMPT_PRE_FETCH

        pre_payload = PromptPrehookPayload(prompt_id="1", args={"name": "Alice"})
        pre_result = SimpleNamespace(modified_payload=pre_payload)
        plugin_mgr.invoke_hook = AsyncMock(return_value=(pre_result, {"ctx": 1}))

        prompt_service._plugin_manager = plugin_mgr

        @contextmanager
        def _no_span(*_a, **_kw):
            yield None

        with (
            patch("mcpgateway.services.prompt_service.create_span", _no_span),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_get_buf,
        ):
            mock_get_buf.return_value.record_prompt_metric = Mock()
            result = await prompt_service.get_prompt(test_db, "1", {"name": "Bob"}, user="user@test.com")

        assert result.messages[0].content.text == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_get_prompt_details_not_found(self, prompt_service, test_db):
        test_db.get = Mock(return_value=None)

        with pytest.raises(PromptNotFoundError, match="Prompt not found: 999"):
            await prompt_service.get_prompt_details(test_db, 999)

    @pytest.mark.asyncio
    async def test_get_prompt_details_inactive(self, prompt_service, test_db):
        prompt = _build_db_prompt(is_active=False)
        test_db.get = Mock(return_value=prompt)
        prompt_service.convert_prompt_to_read = Mock(return_value={"id": 1, "enabled": False})

        result = await prompt_service.get_prompt_details(test_db, 1, include_inactive=True)
        assert result["id"] == 1

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

    def test_parse_messages_starts_with_assistant_and_user_header_flushes_previous(self, prompt_service):
        """Covers branches where a role header appears before any accumulated text."""
        text = "# Assistant:\nHi\n# User:\nHello"
        msgs = prompt_service._parse_messages(text)
        assert len(msgs) == 2
        assert msgs[0].role == Role.ASSISTANT
        assert msgs[1].role == Role.USER

    def test_parse_messages_header_only_returns_empty(self, prompt_service):
        """Covers final 'no current_text' branch."""
        assert prompt_service._parse_messages("# User:") == []

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
    async def test_aggregate_metrics_cache_hit_returns_cached(self, prompt_service, test_db):
        cached = {"total_executions": 123}
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=True),
            patch("mcpgateway.cache.metrics_cache.metrics_cache.get_async", return_value=cached),
            patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined") as mock_agg,
        ):
            result = await prompt_service.aggregate_metrics(test_db)
        assert result is cached
        mock_agg.assert_not_called()

    @pytest.mark.asyncio
    async def test_aggregate_metrics_cache_disabled_skips_cache_get_set(self, prompt_service, test_db):
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        mock_result = AggregatedMetrics(
            total_executions=1,
            successful_executions=1,
            failed_executions=0,
            failure_rate=0.0,
            min_response_time=0.1,
            max_response_time=0.1,
            avg_response_time=0.1,
            last_execution_time="2025-01-01T00:00:00+00:00",
            raw_count=1,
            rollup_count=0,
        )

        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=False),
            patch("mcpgateway.cache.metrics_cache.metrics_cache.get_async") as mock_get,
            patch("mcpgateway.cache.metrics_cache.metrics_cache.set_async") as mock_set,
            patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result),
        ):
            result = await prompt_service.aggregate_metrics(test_db)
        assert result["total_executions"] == 1
        mock_get.assert_not_called()
        mock_set.assert_not_called()

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
    async def test_check_prompt_access_private_denied_to_non_owner_when_authenticated(self, prompt_service, mock_db):
        """Private prompts should be denied to authenticated non-owners (covers prompt_team_id=None path)."""
        private_prompt = self._create_mock_prompt(visibility="private", owner_email="owner@test.com", team_id=None)

        assert await prompt_service._check_prompt_access(mock_db, private_prompt, user_email="other@test.com", token_teams=["team-1"]) is False

    @pytest.mark.asyncio
    async def test_check_prompt_access_team_prompt_allowed_to_member(self, prompt_service, mock_db):
        """Team prompts should be accessible to team members."""
        team_prompt = self._create_mock_prompt(visibility="team", owner_email="owner@test.com", team_id="team-abc")

        # Team member via token_teams
        assert await prompt_service._check_prompt_access(mock_db, team_prompt, user_email="member@test.com", token_teams=["team-abc"]) is True

    @pytest.mark.asyncio
    async def test_check_prompt_access_team_prompt_db_lookup_allows_member(self, prompt_service, mock_db):
        """Team prompts should consult DB when token_teams is None."""
        team_prompt = self._create_mock_prompt(visibility="team", owner_email="owner@test.com", team_id="team-abc")

        team = MagicMock()
        team.id = "team-abc"

        with patch("mcpgateway.services.prompt_service.TeamManagementService") as MockTMS:
            mock_ts = MagicMock()
            mock_ts.get_user_teams = AsyncMock(return_value=[team])
            MockTMS.return_value = mock_ts

            assert await prompt_service._check_prompt_access(mock_db, team_prompt, user_email="member@test.com", token_teams=None) is True

    @pytest.mark.asyncio
    async def test_check_prompt_access_team_prompt_denied_to_non_member(self, prompt_service, mock_db):
        """Team prompts should be denied to non-members."""
        team_prompt = self._create_mock_prompt(visibility="team", owner_email="owner@test.com", team_id="team-abc")

        # Non-member
        assert await prompt_service._check_prompt_access(mock_db, team_prompt, user_email="outsider@test.com", token_teams=["other-team"]) is False

# --------------------------------------------------------------------------- #
# Prompt Namespacing tests                                                    #
# --------------------------------------------------------------------------- #


class TestPromptGatewayNamespacing:
    """Test prompt namespacing by gateway_id."""

    @pytest.mark.asyncio
    async def test_prompt_namespacing_different_gateways(self, prompt_service, test_db):
        """Test: Same `name` can be registered for **different** gateways (same team/owner).

        Verifies that the conflict query includes gateway_id in the filter by capturing
        the executed SQL and checking for the gateway_id clause.
        """
        from mcpgateway.db import Gateway as DbGateway

        # Setup prompt create data
        pc = PromptCreate(
            name="hello",
            description="greet a user",
            template="Hello {{ name }}!",
            arguments=[],
            gateway_id="gateway-2"
        )

        # Track executed queries to verify gateway_id filtering
        executed_queries = []

        def capture_execute(stmt):
            executed_queries.append(str(stmt))
            # First call: gateway lookup (returns None - no gateway found)
            # Second call: conflict check (returns None - no conflict)
            return _make_execute_result(scalar=None)

        test_db.execute = Mock(side_effect=capture_execute)
        test_db.add, test_db.commit, test_db.refresh = Mock(), Mock(), Mock()

        prompt_service._notify_prompt_added = AsyncMock()

        # Execution
        _ = await prompt_service.register_prompt(test_db, pc)

        # Verification: check that gateway_id was included in the conflict query
        test_db.add.assert_called_once()
        stmt = test_db.add.call_args[0][0]
        assert stmt.name == "hello"
        assert stmt.gateway_id == "gateway-2"

        # Verify the conflict check query included gateway_id
        # The second query should be the conflict check
        assert len(executed_queries) >= 2, "Expected at least 2 queries (gateway lookup + conflict check)"
        conflict_query = executed_queries[1]
        assert "gateway_id" in conflict_query, f"Conflict query must filter by gateway_id: {conflict_query}"

    @pytest.mark.asyncio
    async def test_prompt_namespacing_same_gateway(self, prompt_service, test_db):
        """Test: Same `name` **cannot** be registered for the **same** gateway (same team/owner)."""
        from mcpgateway.db import Gateway as DbGateway

        # Setup existing prompt
        existing = _build_db_prompt(name="hello")
        existing.gateway_id = "gateway-1"
        existing.visibility = "public"

        call_count = [0]

        def mock_execute(stmt):
            call_count[0] += 1
            query_str = str(stmt)
            if call_count[0] == 1:
                # First call: gateway lookup - return None
                return _make_execute_result(scalar=None)
            # Second call: conflict check - return existing prompt
            # Verify gateway_id is in the query
            assert "gateway_id" in query_str, f"Conflict query must include gateway_id: {query_str}"
            return _make_execute_result(scalar=existing)

        test_db.execute = Mock(side_effect=mock_execute)

        pc = PromptCreate(
            name="hello",
            description="",
            template="X",
            arguments=[],
            gateway_id="gateway-1"
        )

        with pytest.raises(PromptError) as exc_info:
            await prompt_service.register_prompt(test_db, pc)

        assert "already exists" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_prompt_namespacing_local_prompts(self, prompt_service, test_db):
        """Test: Local prompts (`gateway_id=NULL`) still enforce uniqueness per team/owner."""
        # Setup existing local prompt
        existing = _build_db_prompt(name="hello")
        existing.gateway_id = None
        existing.visibility = "public"

        # Track executed queries to verify gateway_id filtering
        executed_queries = []

        def mock_execute(stmt):
            query_str = str(stmt)
            executed_queries.append(query_str)
            # When gateway_id=None, no gateway lookup occurs - first call is conflict check
            # Return existing prompt to trigger conflict error
            return _make_execute_result(scalar=existing)

        test_db.execute = Mock(side_effect=mock_execute)

        pc = PromptCreate(
            name="hello",
            description="",
            template="X",
            arguments=[],
            gateway_id=None
        )

        with pytest.raises(PromptError) as exc_info:
            await prompt_service.register_prompt(test_db, pc)

        assert "already exists" in str(exc_info.value)

        # Verify the conflict check query included gateway_id
        assert len(executed_queries) >= 1, "Expected at least 1 query (conflict check)"
        conflict_query = executed_queries[0]
        assert "gateway_id" in conflict_query, f"Conflict query must include gateway_id: {conflict_query}"


class TestPromptBulkRegistration:
    """Additional coverage for bulk prompt registration branches."""

    @pytest.mark.asyncio
    async def test_register_prompts_bulk_empty_returns_zeroes(self, prompt_service):
        result = await prompt_service.register_prompts_bulk(db=MagicMock(), prompts=[])

        assert result == {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

    @pytest.mark.asyncio
    async def test_register_prompts_bulk_update_conflict_updates_existing(self, prompt_service):
        existing = MagicMock(spec=DbPrompt)
        existing.name = prompt_service._compute_prompt_name("custom")
        existing.gateway_id = None
        existing.description = "Old"
        existing.template = "Old {{ name }}"
        existing.argument_schema = {}
        existing.tags = ["old"]
        existing.custom_name = "old"
        existing.display_name = "old"
        existing.version = 1

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [existing]
        db.add_all = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        prompt_service._notify_prompt_added = AsyncMock()

        prompt = PromptCreate(
            name="prompt",
            custom_name="custom",
            display_name="display",
            description="New desc",
            template="Hello {{ name }}",
            arguments=[PromptArgument(name="name", description="who")],
            tags=["new"],
        )

        result = await prompt_service.register_prompts_bulk(
            db=db,
            prompts=[prompt],
            created_by="tester",
            conflict_strategy="update",
        )

        assert result["updated"] == 1
        assert existing.description == "New desc"
        assert existing.template == "Hello {{ name }}"
        assert existing.tags[0]["id"] == "new"
        assert existing.tags[0]["label"] == "new"
        assert existing.custom_name == "custom"
        assert existing.display_name == "display"
        assert existing.version == 2
        assert existing.argument_schema["properties"]["name"]["description"] == "who"
        db.add_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_prompts_bulk_update_conflict_skips_custom_and_display_when_missing(self, prompt_service):
        """Covers 'custom_name/display_name is None' branches during bulk update."""
        existing = MagicMock(spec=DbPrompt)
        existing.name = prompt_service._compute_prompt_name("prompt")
        existing.gateway_id = None
        existing.description = "Old"
        existing.template = "Old {{ name }}"
        existing.argument_schema = {}
        existing.tags = []
        existing.custom_name = "keep-custom"
        existing.display_name = "keep-display"
        existing.version = 1

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [existing]
        db.add_all = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        prompt_service._notify_prompt_added = AsyncMock()

        prompt = PromptCreate(
            name="prompt",
            description="New desc",
            template="Hello {{ name }}",
            arguments=[PromptArgument(name="name")],
            tags=["new"],
        )

        result = await prompt_service.register_prompts_bulk(
            db=db,
            prompts=[prompt],
            created_by="tester",
            conflict_strategy="update",
        )

        assert result["updated"] == 1
        assert existing.custom_name == "keep-custom"
        assert existing.display_name == "keep-display"

    @pytest.mark.asyncio
    async def test_register_prompts_bulk_rename_conflict_with_gateway(self, prompt_service):
        gateway = MagicMock()
        gateway.id = "gw-1"
        gateway.name = "Gateway One"

        computed_name = prompt_service._compute_prompt_name("conflict", gateway=gateway)
        existing = MagicMock(spec=DbPrompt)
        existing.name = computed_name
        existing.gateway_id = "gw-1"

        gateway_result = MagicMock()
        gateway_result.scalars.return_value.all.return_value = [gateway]
        prompts_result = MagicMock()
        prompts_result.scalars.return_value.all.return_value = [existing]

        db = MagicMock()
        db.execute.side_effect = [gateway_result, prompts_result]
        db.add_all = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        prompt_service._notify_prompt_added = AsyncMock()

        prompt = PromptCreate(
            name="conflict",
            template="Hello {{ name }}",
            arguments=[],
            gateway_id="gw-1",
        )

        result = await prompt_service.register_prompts_bulk(
            db=db,
            prompts=[prompt],
            created_by="tester",
            conflict_strategy="rename",
            visibility="team",
            team_id="team-1",
        )

        assert result["created"] == 1
        added = db.add_all.call_args.args[0][0]
        assert added.custom_name.startswith("conflict_imported_")
        assert added.display_name.startswith("conflict_imported_")
        assert added.gateway is gateway
        assert added.gateway_name_cache == "Gateway One"
        assert added.team_id == "team-1"
        assert added.visibility == "team"

    @pytest.mark.asyncio
    async def test_register_prompts_bulk_creates_new_prompt_with_gateway_sets_relationship(self, prompt_service):
        """Covers new prompt creation branch with gateway relationship assignment."""
        gateway = MagicMock()
        gateway.id = "gw-1"
        gateway.name = "Gateway One"

        gateway_result = MagicMock()
        gateway_result.scalars.return_value.all.return_value = [gateway]
        prompts_result = MagicMock()
        prompts_result.scalars.return_value.all.return_value = []

        db = MagicMock()
        db.execute.side_effect = [gateway_result, prompts_result]
        db.add_all = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        prompt_service._notify_prompt_added = AsyncMock()

        prompt = PromptCreate(
            name="new",
            template="Hello!",
            arguments=[],
            gateway_id="gw-1",
        )

        result = await prompt_service.register_prompts_bulk(
            db=db,
            prompts=[prompt],
            created_by="tester",
            conflict_strategy="skip",
        )

        assert result["created"] == 1
        added = db.add_all.call_args.args[0][0]
        assert added.gateway is gateway
        assert added.gateway_name_cache == "Gateway One"

    @pytest.mark.asyncio
    async def test_register_prompts_bulk_fail_conflict_records_error(self, prompt_service):
        existing = MagicMock(spec=DbPrompt)
        existing.name = "conflict"
        existing.gateway_id = None

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [existing]
        db.commit = MagicMock()
        db.refresh = MagicMock()
        prompt_service._notify_prompt_added = AsyncMock()

        prompt = PromptCreate(
            name="conflict",
            template="Hello {{ name }}",
            arguments=[],
        )

        result = await prompt_service.register_prompts_bulk(
            db=db,
            prompts=[prompt],
            created_by="tester",
            conflict_strategy="fail",
            visibility="private",
            owner_email="owner@example.com",
        )

        assert result["failed"] == 1
        assert any("Prompt name conflict" in err for err in result["errors"])

    @pytest.mark.asyncio
    async def test_register_prompts_bulk_invalid_template_counts_failed(self, prompt_service):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []
        db.commit = MagicMock()
        db.refresh = MagicMock()
        prompt_service._notify_prompt_added = AsyncMock()

        prompt = SimpleNamespace(
            name="bad",
            template="Hello {{ invalid",
            description=None,
            arguments=[],
            tags=[],
            custom_name=None,
            display_name=None,
            gateway_id=None,
            team_id=None,
            owner_email=None,
            visibility="public",
        )

        result = await prompt_service.register_prompts_bulk(
            db=db,
            prompts=[prompt],
            created_by="tester",
            conflict_strategy="skip",
        )

        assert result["failed"] == 1
        assert any("Failed to process prompt" in err for err in result["errors"])


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


class TestGetTopPrompts:
    """Tests for get_top_prompts (lines 236-287)."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_cache_hit(self, prompt_service):
        db = MagicMock()
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=True),
            patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_cache,
        ):
            mock_cache.get_async = AsyncMock(return_value=[{"id": 1, "name": "cached"}])
            result = await prompt_service.get_top_prompts(db)
        assert result == [{"id": 1, "name": "cached"}]

    @pytest.mark.asyncio
    async def test_cache_miss_queries_db(self, prompt_service):
        db = MagicMock()
        mock_results = MagicMock()
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=True),
            patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_cache,
            patch("mcpgateway.services.metrics_query_service.get_top_performers_combined", return_value=mock_results),
            patch("mcpgateway.services.prompt_service.build_top_performers", return_value=["top1"]),
        ):
            mock_cache.get_async = AsyncMock(return_value=None)
            mock_cache.set_async = AsyncMock()
            result = await prompt_service.get_top_prompts(db, limit=3)
        assert result == ["top1"]
        mock_cache.set_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_disabled(self, prompt_service):
        db = MagicMock()
        mock_results = MagicMock()
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=False),
            patch("mcpgateway.services.metrics_query_service.get_top_performers_combined", return_value=mock_results),
            patch("mcpgateway.services.prompt_service.build_top_performers", return_value=["top1"]),
        ):
            result = await prompt_service.get_top_prompts(db)
        assert result == ["top1"]

    @pytest.mark.asyncio
    async def test_include_deleted(self, prompt_service):
        db = MagicMock()
        mock_results = MagicMock()
        with (
            patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=False),
            patch("mcpgateway.services.metrics_query_service.get_top_performers_combined", return_value=mock_results) as mock_gtp,
            patch("mcpgateway.services.prompt_service.build_top_performers", return_value=[]),
        ):
            await prompt_service.get_top_prompts(db, include_deleted=True)
            assert mock_gtp.call_args[1]["include_deleted"] is True


class TestConvertPromptToRead:
    """Tests for convert_prompt_to_read (lines 289-375)."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    def test_without_metrics(self, prompt_service):
        p = _build_db_prompt(pid=10, name="my-prompt", desc="A prompt")
        result = prompt_service.convert_prompt_to_read(p, include_metrics=False)
        assert result["id"] == 10
        assert result["name"] == "my-prompt"
        assert result["metrics"] is None

    def test_with_metrics(self, prompt_service):
        m1 = MagicMock()
        m1.is_success = True
        m1.response_time = 0.5
        m1.timestamp = datetime(2025, 6, 1, tzinfo=timezone.utc)
        m2 = MagicMock()
        m2.is_success = False
        m2.response_time = 1.0
        m2.timestamp = datetime(2025, 6, 2, tzinfo=timezone.utc)

        p = _build_db_prompt(pid=11, metrics=[m1, m2])
        result = prompt_service.convert_prompt_to_read(p, include_metrics=True)
        assert result["metrics"]["totalExecutions"] == 2
        assert result["metrics"]["successfulExecutions"] == 1
        assert result["metrics"]["failedExecutions"] == 1
        assert result["metrics"]["avgResponseTime"] == 0.75
        assert result["metrics"]["minResponseTime"] == 0.5
        assert result["metrics"]["maxResponseTime"] == 1.0

    def test_with_empty_metrics(self, prompt_service):
        p = _build_db_prompt(pid=12, metrics=[])
        result = prompt_service.convert_prompt_to_read(p, include_metrics=True)
        assert result["metrics"]["totalExecutions"] == 0
        assert result["metrics"]["avgResponseTime"] is None

    def test_arguments_from_schema(self, prompt_service):
        p = _build_db_prompt()
        p.argument_schema = {"properties": {"name": {"type": "string", "description": "User name"}}, "required": ["name"]}
        result = prompt_service.convert_prompt_to_read(p)
        assert len(result["arguments"]) == 1
        assert result["arguments"][0]["name"] == "name"
        assert result["arguments"][0]["required"] is True


class TestGetTeamName:
    """Tests for _get_team_name (lines 377-391)."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    def test_none_team_id(self, prompt_service):
        db = MagicMock()
        assert prompt_service._get_team_name(db, None) is None

    def test_team_found(self, prompt_service):
        db = MagicMock()
        mock_team = MagicMock()
        mock_team.name = "Engineering"
        db.query.return_value.filter.return_value.first.return_value = mock_team
        assert prompt_service._get_team_name(db, "team-1") == "Engineering"

    def test_team_not_found(self, prompt_service):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        assert prompt_service._get_team_name(db, "team-99") is None


class TestComputePromptName:
    """Tests for _compute_prompt_name (lines 393-407)."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    def test_no_gateway(self, prompt_service):
        result = prompt_service._compute_prompt_name("My Prompt")
        assert result == "my-prompt"

    def test_with_gateway(self, prompt_service, monkeypatch):
        monkeypatch.setattr("mcpgateway.services.prompt_service.settings", MagicMock(gateway_tool_name_separator="__"))
        gateway = MagicMock()
        gateway.name = "Test Gateway"
        result = prompt_service._compute_prompt_name("My Prompt", gateway=gateway)
        assert result == "test-gateway__my-prompt"


class TestListPromptsAdvanced:
    """Tests for list_prompts pagination and filtering (lines 969-1152)."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_page_based_pagination(self, prompt_service):
        db = MagicMock()
        mock_prompt = _build_db_prompt()
        mock_prompt.team_id = None

        with (
            patch.object(prompt_service, "convert_prompt_to_read", return_value="converted"),
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.prompt_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
        ):
            mock_paginate.return_value = {
                "data": [mock_prompt],
                "pagination": {"page": 1, "per_page": 10, "total": 1},
                "links": {"self": "/admin/prompts?page=1"},
            }

            result = await prompt_service.list_prompts(db, page=1, per_page=10)

        assert "data" in result
        assert "pagination" in result
        assert result["data"] == ["converted"]

    @pytest.mark.asyncio
    async def test_cache_hit(self, prompt_service):
        db = MagicMock()
        with patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.hash_filters.return_value = "hash"
            mock_cache.get = AsyncMock(return_value={"prompts": [{"id": 1, "name": "cached"}], "next_cursor": None})
            mock_cache_fn.return_value = mock_cache

            result, cursor = await prompt_service.list_prompts(db)
        assert len(result) == 1
        assert cursor is None

    @pytest.mark.asyncio
    async def test_token_teams_empty_public_only(self, prompt_service):
        """Empty token_teams should only show public prompts."""
        db = MagicMock()
        mock_prompt = _build_db_prompt()
        mock_prompt.team_id = None

        with (
            patch.object(prompt_service, "convert_prompt_to_read", return_value="converted"),
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.prompt_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_paginate.return_value = ([mock_prompt], None)

            result, cursor = await prompt_service.list_prompts(db, token_teams=[])
        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_token_teams_with_teams(self, prompt_service):
        db = MagicMock()
        mock_prompt = _build_db_prompt()
        mock_prompt.team_id = "team-1"

        with (
            patch.object(prompt_service, "convert_prompt_to_read", return_value="converted"),
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.prompt_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_paginate.return_value = ([mock_prompt], None)

            result, cursor = await prompt_service.list_prompts(db, token_teams=["team-1"])
        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_user_email_with_team_id_no_access(self, prompt_service):
        db = MagicMock()

        with (
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.prompt_service.TeamManagementService") as MockTMS,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_ts = MagicMock()
            mock_ts.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_ts

            result, cursor = await prompt_service.list_prompts(db, user_email="user@test.com", team_id="team-99")
        assert result == []

    @pytest.mark.asyncio
    async def test_user_email_empty_string_treated_as_public_only(self, prompt_service):
        """An empty (but present) user_email should still apply secure public-only filtering."""
        db = MagicMock()
        mock_prompt = _build_db_prompt()
        mock_prompt.team_id = None

        with (
            patch.object(prompt_service, "convert_prompt_to_read", return_value="converted"),
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.prompt_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_paginate.return_value = ([mock_prompt], None)

            result, _ = await prompt_service.list_prompts(db, user_email="")

        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_token_teams_with_team_id_access_and_visibility_filter(self, prompt_service):
        """Covers team_id access conditions + visibility filter branch."""
        db = MagicMock()
        mock_prompt = _build_db_prompt()
        mock_prompt.team_id = "team-1"

        with (
            patch.object(prompt_service, "convert_prompt_to_read", return_value="converted"),
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.prompt_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_paginate.return_value = ([mock_prompt], None)

            result, _ = await prompt_service.list_prompts(
                db,
                user_email="user@test.com",
                token_teams=["team-1"],
                team_id="team-1",
                visibility="team",
            )

        assert result == ["converted"]


class TestListPromptsForUser:
    """Tests for list_prompts_for_user (lines 1154-1243)."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_basic_listing(self, prompt_service):
        db = MagicMock()
        mock_prompt = MagicMock()
        mock_prompt.team_id = None
        db.execute.return_value.scalars.return_value.all.return_value = [mock_prompt]

        prompt_service.convert_prompt_to_read = MagicMock(return_value="converted")

        with patch("mcpgateway.services.prompt_service.TeamManagementService") as MockTMS:
            mock_ts = MagicMock()
            mock_ts.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_ts

            result = await prompt_service.list_prompts_for_user(db, "user@test.com")

        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_team_no_access(self, prompt_service):
        db = MagicMock()
        with patch("mcpgateway.services.prompt_service.TeamManagementService") as MockTMS:
            mock_ts = MagicMock()
            mock_ts.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_ts

            result = await prompt_service.list_prompts_for_user(db, "user@test.com", team_id="team-99")
        assert result == []

    @pytest.mark.asyncio
    async def test_team_with_access(self, prompt_service):
        db = MagicMock()
        mock_prompt = MagicMock()
        mock_prompt.team_id = "team-1"

        # Use side_effect to return different results for sequential db.execute() calls
        main_result = MagicMock()
        main_result.scalars.return_value.all.return_value = [mock_prompt]
        team_result = MagicMock()
        team_result.all.return_value = [MagicMock(id="team-1", name="Team")]
        db.execute = MagicMock(side_effect=[main_result, team_result])

        prompt_service.convert_prompt_to_read = MagicMock(return_value="converted")

        team = MagicMock()
        team.id = "team-1"
        team.name = "Team"

        with patch("mcpgateway.services.prompt_service.TeamManagementService") as MockTMS:
            mock_ts = MagicMock()
            mock_ts.get_user_teams = AsyncMock(return_value=[team])
            MockTMS.return_value = mock_ts

            result = await prompt_service.list_prompts_for_user(db, "user@test.com", team_id="team-1")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_conversion_error_skipped(self, prompt_service):
        db = MagicMock()
        mock_prompt = MagicMock()
        mock_prompt.team_id = None
        db.execute.return_value.scalars.return_value.all.return_value = [mock_prompt]

        prompt_service.convert_prompt_to_read = MagicMock(side_effect=ValueError("bad"))

        with patch("mcpgateway.services.prompt_service.TeamManagementService") as MockTMS:
            mock_ts = MagicMock()
            mock_ts.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_ts

            result = await prompt_service.list_prompts_for_user(db, "user@test.com")

        assert result == []

    @pytest.mark.asyncio
    async def test_visibility_filter(self, prompt_service):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []

        with patch("mcpgateway.services.prompt_service.TeamManagementService") as MockTMS:
            mock_ts = MagicMock()
            mock_ts.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_ts

            result = await prompt_service.list_prompts_for_user(db, "user@test.com", visibility="private")

        assert result == []

    @pytest.mark.asyncio
    async def test_include_inactive(self, prompt_service):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []

        with patch("mcpgateway.services.prompt_service.TeamManagementService") as MockTMS:
            mock_ts = MagicMock()
            mock_ts.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_ts

            result = await prompt_service.list_prompts_for_user(db, "user@test.com", include_inactive=True)

        assert result == []


class TestRecordPromptMetric:
    """Tests for _record_prompt_metric (lines 1348-1370)."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_success(self, prompt_service):
        db = MagicMock()
        prompt = _build_db_prompt(pid="prompt-1")
        import time
        start = time.monotonic() - 0.5
        await prompt_service._record_prompt_metric(db, prompt, start, True, None)
        db.add.assert_called_once()
        metric = db.add.call_args[0][0]
        assert metric.prompt_id == "prompt-1"
        assert metric.is_success is True
        assert metric.response_time > 0
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure(self, prompt_service):
        db = MagicMock()
        prompt = _build_db_prompt(pid="prompt-2")
        import time
        start = time.monotonic()
        await prompt_service._record_prompt_metric(db, prompt, start, False, "error msg")
        metric = db.add.call_args[0][0]
        assert metric.is_success is False
        assert metric.error_message == "error msg"


# ---------------------------------------------------------------------------
#  Additional coverage: list_server_prompts
# ---------------------------------------------------------------------------


class TestListServerPrompts:
    """Cover lines 1289-1346: list_server_prompts server association + team batch fetch."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_basic_listing(self, prompt_service):
        """Basic listing returns prompts for a server."""
        db = MagicMock()
        mock_prompt = MagicMock()
        mock_prompt.team_id = None

        # First execute: prompt query
        prompt_result = MagicMock()
        prompt_result.scalars.return_value.all.return_value = [mock_prompt]
        db.execute = MagicMock(return_value=prompt_result)
        db.commit = MagicMock()

        prompt_service.convert_prompt_to_read = MagicMock(return_value="converted")

        result = await prompt_service.list_server_prompts(db, "server-1")
        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_include_inactive_true_skips_enabled_filter(self, prompt_service):
        """Covers include_inactive=True branch (skips DbPrompt.enabled filter)."""
        db = MagicMock()
        prompt_result = MagicMock()
        prompt_result.scalars.return_value.all.return_value = []
        db.execute = MagicMock(return_value=prompt_result)
        db.commit = MagicMock()

        result = await prompt_service.list_server_prompts(db, "server-1", include_inactive=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_user_email_db_team_lookup_path(self, prompt_service):
        """Covers TeamManagementService DB lookup path when token_teams is None."""
        db = MagicMock()
        mock_prompt = MagicMock()
        mock_prompt.team_id = None

        prompt_result = MagicMock()
        prompt_result.scalars.return_value.all.return_value = [mock_prompt]
        db.execute = MagicMock(return_value=prompt_result)
        db.commit = MagicMock()

        prompt_service.convert_prompt_to_read = MagicMock(return_value="converted")

        team = MagicMock()
        team.id = "team-1"

        with patch("mcpgateway.services.prompt_service.TeamManagementService") as MockTMS:
            mock_ts = MagicMock()
            mock_ts.get_user_teams = AsyncMock(return_value=[team])
            MockTMS.return_value = mock_ts

            result = await prompt_service.list_server_prompts(db, "server-1", user_email="user@test.com")

        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_user_email_empty_string_sets_team_ids_empty(self, prompt_service):
        """Empty string user_email is treated as provided but unauthenticated (public-only)."""
        db = MagicMock()
        prompt_result = MagicMock()
        prompt_result.scalars.return_value.all.return_value = []
        db.execute = MagicMock(return_value=prompt_result)
        db.commit = MagicMock()

        result = await prompt_service.list_server_prompts(db, "server-1", user_email="")
        assert result == []

    @pytest.mark.asyncio
    async def test_with_team_batch_fetch(self, prompt_service):
        """Prompts with team_ids trigger batch team name fetch."""
        db = MagicMock()
        mock_prompt = MagicMock()
        mock_prompt.team_id = "team-1"

        # First call: prompt query; second call: team name batch query
        prompt_result = MagicMock()
        prompt_result.scalars.return_value.all.return_value = [mock_prompt]
        team_result = MagicMock()
        team_row = MagicMock()
        team_row.id = "team-1"
        team_row.name = "Engineering"
        team_result.all.return_value = [team_row]
        db.execute = MagicMock(side_effect=[prompt_result, team_result])
        db.commit = MagicMock()

        prompt_service.convert_prompt_to_read = MagicMock(return_value="converted")

        result = await prompt_service.list_server_prompts(db, "server-1")
        assert result == ["converted"]
        # team was set on the prompt
        assert mock_prompt.team == "Engineering"

    @pytest.mark.asyncio
    async def test_with_token_teams_public_only(self, prompt_service):
        """token_teams=[] restricts to public-only prompts."""
        db = MagicMock()
        prompt_result = MagicMock()
        prompt_result.scalars.return_value.all.return_value = []
        db.execute = MagicMock(return_value=prompt_result)
        db.commit = MagicMock()

        result = await prompt_service.list_server_prompts(db, "server-1", token_teams=[])
        assert result == []

    @pytest.mark.asyncio
    async def test_with_token_teams_scoped(self, prompt_service):
        """token_teams=["team-1"] shows public + team prompts."""
        db = MagicMock()
        mock_prompt = MagicMock()
        mock_prompt.team_id = "team-1"

        prompt_result = MagicMock()
        prompt_result.scalars.return_value.all.return_value = [mock_prompt]
        team_result = MagicMock()
        team_result.all.return_value = []
        db.execute = MagicMock(side_effect=[prompt_result, team_result])
        db.commit = MagicMock()

        prompt_service.convert_prompt_to_read = MagicMock(return_value="converted")

        result = await prompt_service.list_server_prompts(db, "server-1", token_teams=["team-1"], user_email="user@test.com")
        assert result == ["converted"]

    @pytest.mark.asyncio
    async def test_conversion_error_skipped(self, prompt_service):
        """Conversion errors for individual prompts don't fail the whole list."""
        db = MagicMock()
        p1 = MagicMock()
        p1.team_id = None
        p2 = MagicMock()
        p2.team_id = None

        prompt_result = MagicMock()
        prompt_result.scalars.return_value.all.return_value = [p1, p2]
        db.execute = MagicMock(return_value=prompt_result)
        db.commit = MagicMock()

        prompt_service.convert_prompt_to_read = MagicMock(side_effect=[ValueError("bad"), "ok"])

        result = await prompt_service.list_server_prompts(db, "server-1")
        assert result == ["ok"]


# ---------------------------------------------------------------------------
#  Additional coverage: update_prompt name conflict detection
# ---------------------------------------------------------------------------


class TestUpdatePromptNameConflict:
    """Cover lines 1800-1810: team/private name conflict in update_prompt."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_team_name_conflict(self, prompt_service):
        """Name conflict in team visibility raises PromptError."""
        existing = _build_db_prompt(name="old-name")
        existing.visibility = "team"
        existing.team_id = "team-1"
        existing.custom_name = "old-name"
        existing.gateway = None
        existing.gateway_id = None
        existing.owner_email = "owner@test.com"

        conflicting = MagicMock()
        conflicting.enabled = True
        conflicting.id = 99
        conflicting.visibility = "team"

        with (
            patch("mcpgateway.services.prompt_service.get_for_update") as mock_gfu,
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
        ):
            mock_gfu.side_effect = [existing, conflicting]  # first: get prompt, second: conflict check

            upd = PromptUpdate(name="new-name")

            with pytest.raises(PromptError):
                await prompt_service.update_prompt(MagicMock(), 1, upd)

    @pytest.mark.asyncio
    async def test_private_name_conflict(self, prompt_service):
        """Name conflict in private visibility raises PromptError."""
        existing = _build_db_prompt(name="old-name")
        existing.visibility = "private"
        existing.team_id = None
        existing.custom_name = "old-name"
        existing.gateway = None
        existing.gateway_id = None
        existing.owner_email = "owner@test.com"

        conflicting = MagicMock()
        conflicting.enabled = True
        conflicting.id = 99
        conflicting.visibility = "private"

        with (
            patch("mcpgateway.services.prompt_service.get_for_update") as mock_gfu,
        ):
            mock_gfu.side_effect = [existing, conflicting]

            upd = PromptUpdate(name="new-name")

            with pytest.raises(PromptError):
                await prompt_service.update_prompt(MagicMock(), 1, upd)


# ---------------------------------------------------------------------------
#  Additional coverage: update_prompt field updates and exception handlers
# ---------------------------------------------------------------------------


class TestUpdatePromptFieldsAndExceptions:
    """Cover lines 1822-1873, 1924-1953."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_update_with_arguments_and_version(self, prompt_service):
        """Updating template+arguments regenerates argument schema and increments version."""
        existing = _build_db_prompt(name="my-prompt")
        existing.visibility = "public"
        existing.team_id = "t1"
        existing.custom_name = "my-prompt"
        existing.gateway = None
        existing.gateway_id = None
        existing.owner_email = "owner@test.com"
        existing.version = 3

        db = MagicMock()

        with (
            patch("mcpgateway.services.prompt_service.get_for_update", return_value=existing),
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_admin_cache.invalidate_tags = AsyncMock()
            db.commit = Mock()
            db.refresh = Mock()
            prompt_service._notify_prompt_updated = AsyncMock()
            prompt_service.convert_prompt_to_read = Mock(return_value={"id": 1})

            upd = PromptUpdate(
                template="Hi {{ user }}!",
                arguments=[PromptArgument(name="user", description="Username")],
                visibility="public",
                tags=["v2"],
            )

            result = await prompt_service.update_prompt(db, 1, upd, modified_by="admin", modified_from_ip="1.2.3.4", modified_via="api", modified_user_agent="test-agent")

        assert existing.template == "Hi {{ user }}!"
        assert existing.argument_schema["properties"]["user"]["description"] == "Username"
        assert existing.version == 4
        assert existing.tags is not None
        assert existing.visibility == "public"

    @pytest.mark.asyncio
    async def test_update_permission_denied(self, prompt_service):
        """Permission error during update is propagated."""
        existing = _build_db_prompt(name="owned")
        existing.visibility = "public"
        existing.team_id = None
        existing.custom_name = "owned"
        existing.gateway = None
        existing.gateway_id = None
        existing.owner_email = "owner@test.com"

        db = MagicMock()
        db.rollback = Mock()

        with (
            patch("mcpgateway.services.prompt_service.get_for_update", return_value=existing),
            patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=False)),
        ):
            upd = PromptUpdate(description="new desc")

            with pytest.raises(PermissionError, match="Only the owner"):
                await prompt_service.update_prompt(db, 1, upd, user_email="other@test.com")

    @pytest.mark.asyncio
    async def test_update_integrity_error(self, prompt_service):
        """IntegrityError during update is propagated."""
        existing = _build_db_prompt(name="my-prompt")
        existing.visibility = "public"
        existing.team_id = None
        existing.custom_name = "my-prompt"
        existing.gateway = None
        existing.gateway_id = None
        existing.owner_email = "owner@test.com"

        db = MagicMock()
        db.commit = Mock(side_effect=IntegrityError("dup", None, BaseException()))
        db.rollback = Mock()

        with patch("mcpgateway.services.prompt_service.get_for_update", return_value=existing):
            upd = PromptUpdate(description="new desc")

            with pytest.raises(IntegrityError):
                await prompt_service.update_prompt(db, 1, upd)

    @pytest.mark.asyncio
    async def test_update_name_on_gateway_prompt(self, prompt_service):
        """Updating name on a gateway prompt sets custom_name instead of original_name."""
        existing = _build_db_prompt(name="gw__old")
        existing.visibility = "public"
        existing.team_id = None
        existing.custom_name = "old"
        existing.gateway = MagicMock()
        existing.gateway.name = "gw"
        existing.gateway_id = "gw-1"
        existing.owner_email = "owner@test.com"
        existing.version = 1

        db = MagicMock()

        with (
            patch("mcpgateway.services.prompt_service.get_for_update", side_effect=[existing, None]),
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_admin_cache.invalidate_tags = AsyncMock()
            db.commit = Mock()
            db.refresh = Mock()
            prompt_service._notify_prompt_updated = AsyncMock()
            prompt_service.convert_prompt_to_read = Mock(return_value={"id": 1})

            upd = PromptUpdate(name="new-name", custom_name="custom")

            await prompt_service.update_prompt(db, 1, upd)

        assert existing.custom_name == "custom"

    @pytest.mark.asyncio
    async def test_update_name_on_local_prompt_sets_original_name_and_custom_name_and_initializes_version(self, prompt_service):
        """Covers local prompt name handling (original_name/custom_name) and version initialization."""
        existing = _build_db_prompt(name="old-name")
        existing.visibility = "public"
        existing.team_id = None
        existing.custom_name = "old-name"
        existing.original_name = "old-name"
        existing.gateway = None
        existing.gateway_id = None
        existing.owner_email = "owner@test.com"
        existing.version = None  # force version init branch

        db = MagicMock()

        with (
            patch("mcpgateway.services.prompt_service.get_for_update", side_effect=[existing, None]),  # prompt then conflict-check
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_admin_cache.invalidate_tags = AsyncMock()
            db.commit = Mock()
            db.refresh = Mock()
            prompt_service._notify_prompt_updated = AsyncMock()
            prompt_service.convert_prompt_to_read = Mock(return_value={"id": 1})

            upd = PromptUpdate(name="new-name")
            await prompt_service.update_prompt(db, 1, upd)

        assert existing.original_name == "new-name"
        assert existing.custom_name == "new-name"
        assert existing.version == 1

    @pytest.mark.asyncio
    async def test_update_arguments_without_description_skips_description_key(self, prompt_service):
        """Covers arg.description is None branch when rebuilding argument_schema."""
        existing = _build_db_prompt(name="my-prompt")
        existing.visibility = "public"
        existing.team_id = None
        existing.custom_name = "my-prompt"
        existing.gateway = None
        existing.gateway_id = None
        existing.owner_email = "owner@test.com"
        existing.version = 1

        db = MagicMock()

        with (
            patch("mcpgateway.services.prompt_service.get_for_update", return_value=existing),
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache,
        ):
            mock_cache = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_admin_cache.invalidate_tags = AsyncMock()
            db.commit = Mock()
            db.refresh = Mock()
            prompt_service._notify_prompt_updated = AsyncMock()
            prompt_service.convert_prompt_to_read = Mock(return_value={"id": 1})

            upd = PromptUpdate(arguments=[PromptArgument(name="user")])
            await prompt_service.update_prompt(db, 1, upd)

        assert existing.argument_schema["properties"]["user"] == {"type": "string"}


# ---------------------------------------------------------------------------
#  Additional coverage: set_prompt_state lock conflict + permission
# ---------------------------------------------------------------------------


class TestSetPromptStateLockAndPermission:
    """Cover lines 2044-2057: lock conflict and permission check in set_prompt_state."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_lock_conflict(self, prompt_service):
        """OperationalError during row lock raises PromptLockConflictError."""
        from sqlalchemy.exc import OperationalError
        from mcpgateway.services.prompt_service import PromptLockConflictError

        db = MagicMock()
        db.rollback = Mock()

        with patch("mcpgateway.services.prompt_service.get_for_update", side_effect=OperationalError("locked", None, BaseException())):
            with pytest.raises(PromptLockConflictError, match="currently being modified"):
                await prompt_service.set_prompt_state(db, 1, activate=True)

    @pytest.mark.asyncio
    async def test_permission_denied(self, prompt_service):
        """Non-owner user gets PermissionError when toggling prompt state."""
        prompt = _build_db_prompt()
        prompt.enabled = True

        db = MagicMock()
        db.rollback = Mock()

        with (
            patch("mcpgateway.services.prompt_service.get_for_update", return_value=prompt),
            patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", new=AsyncMock(return_value=False)),
        ):
            with pytest.raises(PermissionError, match="Only the owner"):
                await prompt_service.set_prompt_state(db, 1, activate=False, user_email="other@test.com")


class TestSetPromptStateAdditionalBranches:
    """Covers skip_cache_invalidation and 'no-op' state updates."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_no_state_change_skips_commit_and_notifications(self, prompt_service):
        prompt = _build_db_prompt()
        prompt.enabled = True

        db = MagicMock()
        db.commit = Mock()
        db.refresh = Mock()

        prompt_service._notify_prompt_activated = AsyncMock()
        prompt_service._notify_prompt_deactivated = AsyncMock()
        prompt_service.convert_prompt_to_read = Mock(return_value={"enabled": True})
        prompt_service._get_team_name = Mock(return_value=None)

        with patch("mcpgateway.services.prompt_service.get_for_update", return_value=prompt):
            res = await prompt_service.set_prompt_state(db, 1, activate=True)

        db.commit.assert_not_called()
        prompt_service._notify_prompt_activated.assert_not_called()
        prompt_service._notify_prompt_deactivated.assert_not_called()
        assert res["enabled"] is True

    @pytest.mark.asyncio
    async def test_skip_cache_invalidation_true_does_not_touch_registry_cache(self, prompt_service):
        prompt = _build_db_prompt()
        prompt.enabled = True

        db = MagicMock()
        db.commit = Mock()
        db.refresh = Mock()

        prompt_service._notify_prompt_deactivated = AsyncMock()
        prompt_service.convert_prompt_to_read = Mock(return_value={"enabled": False})
        prompt_service._get_team_name = Mock(return_value=None)

        with (
            patch("mcpgateway.services.prompt_service.get_for_update", return_value=prompt),
            patch("mcpgateway.services.prompt_service._get_registry_cache") as mock_cache_fn,
        ):
            res = await prompt_service.set_prompt_state(db, 1, activate=False, skip_cache_invalidation=True)

        mock_cache_fn.assert_not_called()
        prompt_service._notify_prompt_deactivated.assert_awaited_once()
        assert res["enabled"] is False


# ---------------------------------------------------------------------------
#  Additional coverage: event notification methods
# ---------------------------------------------------------------------------


class TestPromptEventNotifications:
    """Cover lines 2501-2586: _notify_prompt_* event publishing methods."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_notify_prompt_added(self, prompt_service):
        prompt = _build_db_prompt(pid=1, name="test")
        prompt_service._event_service.publish_event = AsyncMock()

        await prompt_service._notify_prompt_added(prompt)

        event = prompt_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "prompt_added"
        assert event["data"]["name"] == "test"

    @pytest.mark.asyncio
    async def test_notify_prompt_updated(self, prompt_service):
        prompt = _build_db_prompt(pid=2, name="updated")
        prompt_service._event_service.publish_event = AsyncMock()

        await prompt_service._notify_prompt_updated(prompt)

        event = prompt_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "prompt_updated"

    @pytest.mark.asyncio
    async def test_notify_prompt_activated(self, prompt_service):
        prompt = _build_db_prompt(pid=3, name="active")
        prompt_service._event_service.publish_event = AsyncMock()

        await prompt_service._notify_prompt_activated(prompt)

        event = prompt_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "prompt_activated"
        assert event["data"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_notify_prompt_deactivated(self, prompt_service):
        prompt = _build_db_prompt(pid=4, name="inactive")
        prompt_service._event_service.publish_event = AsyncMock()

        await prompt_service._notify_prompt_deactivated(prompt)

        event = prompt_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "prompt_deactivated"
        assert event["data"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_notify_prompt_deleted(self, prompt_service):
        prompt_service._event_service.publish_event = AsyncMock()

        await prompt_service._notify_prompt_deleted({"id": 5, "name": "deleted"})

        event = prompt_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "prompt_deleted"

    @pytest.mark.asyncio
    async def test_notify_prompt_removed(self, prompt_service):
        prompt = _build_db_prompt(pid=6, name="removed")
        prompt_service._event_service.publish_event = AsyncMock()

        await prompt_service._notify_prompt_removed(prompt)

        event = prompt_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "prompt_removed"
        assert event["data"]["enabled"] is False


class TestPromptSubscribeEvents:
    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_subscribe_events_empty_generator_exits(self, prompt_service):
        async def _empty_events():
            if False:
                yield {"type": "never"}

        prompt_service._event_service.subscribe_events = _empty_events

        events = []
        async for event in prompt_service.subscribe_events():
            events.append(event)

        assert events == []


# ---------------------------------------------------------------------------
#  Additional coverage: register_prompts_bulk chunk exception
# ---------------------------------------------------------------------------


class TestRegisterPromptsBulkChunkException:
    """Cover lines 938-943: chunk-level exception in register_prompts_bulk."""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_chunk_commit_exception(self, prompt_service):
        """Exception during chunk commit is caught and recorded in stats."""
        db = MagicMock()
        # Empty existing prompts list
        db.execute.return_value.scalars.return_value.all.return_value = []
        db.add_all = MagicMock()
        db.commit = MagicMock(side_effect=RuntimeError("db crash"))
        db.rollback = MagicMock()
        prompt_service._notify_prompt_added = AsyncMock()

        prompt = PromptCreate(
            name="test-prompt",
            description="desc",
            template="Hello {{ name }}",
            arguments=[],
        )

        result = await prompt_service.register_prompts_bulk(
            db=db,
            prompts=[prompt],
            created_by="tester",
            conflict_strategy="skip",
        )

        assert result["failed"] >= 1
        assert any("Chunk processing failed" in err for err in result["errors"])
