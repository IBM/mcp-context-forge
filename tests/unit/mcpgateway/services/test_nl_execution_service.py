# -*- coding: utf-8 -*-
"""Unit tests for NLExecutionService."""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.nl_execution_service import (
    IntentClassification,
    NLExecutionService,
    SlotFillingResult,
    ToolCandidate,
    ToolMatch,
)


@pytest.mark.asyncio
async def test_execute_no_tool_needed(monkeypatch: pytest.MonkeyPatch):
    service = NLExecutionService()
    intent = IntentClassification(intent="question", confidence=0.9, domain=None, requires_tool=False)
    monkeypatch.setattr(service, "_classify_intent", AsyncMock(return_value=intent))
    monkeypatch.setattr(service, "_handle_non_tool_query", AsyncMock(return_value="hello"))

    result = await service.execute(query="hi", db=MagicMock(), user_ctx={}, request_headers={})

    assert result["type"] == "no_tool_needed"
    assert result["response"] == "hello"


@pytest.mark.asyncio
async def test_execute_clarification_needed(monkeypatch: pytest.MonkeyPatch):
    service = NLExecutionService()
    tool = ToolCandidate(
        name="weather",
        description="Weather lookup",
        input_schema={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
        visibility="public",
    )
    match = ToolMatch(tool=tool, confidence=0.9, reasoning=None, is_primary=True)
    intent = IntentClassification(intent="tool_execution", confidence=0.9, domain=None, requires_tool=True)

    monkeypatch.setattr(service, "_classify_intent", AsyncMock(return_value=intent))
    monkeypatch.setattr(service, "_match_tools", AsyncMock(return_value=[match]))
    monkeypatch.setattr(service, "_can_execute_tool", AsyncMock(return_value=True))
    monkeypatch.setattr(
        service,
        "_fill_slots",
        AsyncMock(
            return_value=SlotFillingResult(
                parameters={},
                missing_required=["city"],
                inferred_params={},
                validation_errors=[],
                confidence=0.8,
                needs_clarification=True,
            )
        ),
    )
    monkeypatch.setattr(service, "_generate_clarification", AsyncMock(return_value="Which city?"))

    result = await service.execute(query="weather", db=MagicMock(), user_ctx={}, request_headers={})

    assert result["type"] == "clarification_needed"
    assert result["pending_tool"] == "weather"
    assert result["response"] == "Which city?"


@pytest.mark.asyncio
async def test_execute_confirmation_needed(monkeypatch: pytest.MonkeyPatch):
    service = NLExecutionService()
    tool = ToolCandidate(
        name="deploy-service",
        description="Deploy service",
        input_schema={"type": "object", "properties": {"env": {"type": "string"}}, "required": ["env"]},
        visibility="public",
        annotations={"risk_level": "high"},
    )
    match = ToolMatch(tool=tool, confidence=0.9, reasoning=None, is_primary=True)
    intent = IntentClassification(intent="tool_execution", confidence=0.9, domain=None, requires_tool=True)

    monkeypatch.setattr(service, "_classify_intent", AsyncMock(return_value=intent))
    monkeypatch.setattr(service, "_match_tools", AsyncMock(return_value=[match]))
    monkeypatch.setattr(service, "_can_execute_tool", AsyncMock(return_value=True))
    monkeypatch.setattr(
        service,
        "_fill_slots",
        AsyncMock(
            return_value=SlotFillingResult(
                parameters={"env": "production"},
                missing_required=[],
                inferred_params={},
                validation_errors=[],
                confidence=0.9,
                needs_clarification=False,
            )
        ),
    )

    result = await service.execute(query="deploy to production", db=MagicMock(), user_ctx={}, request_headers={})

    assert result["type"] == "confirmation_needed"
    assert result["pending_tool"] == "deploy-service"


@pytest.mark.asyncio
async def test_execute_success(monkeypatch: pytest.MonkeyPatch):
    service = NLExecutionService()
    tool = ToolCandidate(
        name="get-time",
        description="Get system time",
        input_schema={"type": "object", "properties": {}},
        visibility="public",
    )
    match = ToolMatch(tool=tool, confidence=0.9, reasoning=None, is_primary=True)
    intent = IntentClassification(intent="tool_execution", confidence=0.9, domain=None, requires_tool=True)

    monkeypatch.setattr(service, "_classify_intent", AsyncMock(return_value=intent))
    monkeypatch.setattr(service, "_match_tools", AsyncMock(return_value=[match]))
    monkeypatch.setattr(service, "_can_execute_tool", AsyncMock(return_value=True))
    monkeypatch.setattr(
        service,
        "_fill_slots",
        AsyncMock(
            return_value=SlotFillingResult(
                parameters={},
                missing_required=[],
                inferred_params={},
                validation_errors=[],
                confidence=0.9,
                needs_clarification=False,
            )
        ),
    )
    monkeypatch.setattr(service, "_invoke_tool", AsyncMock(return_value={"content": "ok", "is_error": False}))
    monkeypatch.setattr(service, "_format_response_with_followups", AsyncMock(return_value=("ok", [])))

    result = await service.execute(query="time", db=MagicMock(), user_ctx={}, request_headers={})

    assert result["type"] == "success"
    assert result["tool_used"] == "get-time"


@pytest.mark.asyncio
async def test_confirm_success(monkeypatch: pytest.MonkeyPatch):
    service = NLExecutionService()
    tool = ToolCandidate(
        name="get-time",
        description="Get system time",
        input_schema={"type": "object", "properties": {}},
        visibility="public",
    )
    session_id = "session-123"

    context = {
        "session_id": session_id,
        "messages": [],
        "extracted_entities": {},
        "pending_execution": {"tool": tool.name, "params": {}},
        "clarification_rounds": 0,
    }
    await service._context_manager.save_context(context)

    monkeypatch.setattr(service, "_load_tool_candidate", AsyncMock(return_value=tool))
    monkeypatch.setattr(service, "_can_execute_tool", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_invoke_tool", AsyncMock(return_value={"content": "ok", "is_error": False}))
    monkeypatch.setattr(service, "_format_response_with_followups", AsyncMock(return_value=("ok", [])))

    result = await service.confirm(
        session_id=session_id,
        db=MagicMock(),
        user_ctx={},
        request_headers={},
        confirm=True,
    )

    assert result["type"] == "success"
    assert result["tool_used"] == "get-time"
