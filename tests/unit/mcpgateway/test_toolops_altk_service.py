# -*- coding: utf-8 -*-
"""Tests for toolops_altk_service."""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
import mcpgateway.toolops.toolops_altk_service as svc


class DummyTool:
    """Simple tool stand-in with to_dict support."""

    def __init__(self, url: str = "http://example.com/mcp") -> None:
        self.url = url
        self.name = "tool-name"
        self.description = "tool-desc"

    def to_dict(self, use_alias: bool = True):  # noqa: ARG002 - matches real signature
        return {"url": self.url, "name": self.name, "description": self.description}


def test_custom_execute_prompt_success(monkeypatch):
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="ok")
    monkeypatch.setattr(svc, "get_llm_instance", lambda model_type="chat": (llm, None))
    assert svc.custom_mcp_cf_execute_prompt("hello") == "ok"


def test_custom_execute_prompt_error(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("fail")

    monkeypatch.setattr(svc, "get_llm_instance", _boom)
    assert svc.custom_mcp_cf_execute_prompt("hello") == ""


@pytest.mark.asyncio
async def test_validation_generate_test_cases_generate(monkeypatch):
    tool_service = MagicMock()
    tool_service.get_tool = AsyncMock(return_value=DummyTool())
    monkeypatch.setattr(svc, "convert_to_toolops_spec", lambda payload: {"spec": payload})
    monkeypatch.setattr(svc, "post_process_nl_test_cases", lambda cases: ["final"])
    statuses = []
    monkeypatch.setattr(svc, "populate_testcases_table", lambda _tool_id, _tcs, status, _db: statuses.append(status))

    class DummyTestcaseGen:
        def __init__(self, **_kwargs):
            pass

        def testcase_generation_full_pipeline(self, _spec):
            return (["case"], None)

    class DummyNlGen:
        def __init__(self, **_kwargs):
            pass

        def generate_nl(self, _cases):
            return ["utterance"]

    monkeypatch.setattr(svc, "TestcaseGeneration", DummyTestcaseGen)
    monkeypatch.setattr(svc, "NlUtteranceGeneration", DummyNlGen)

    result = await svc.validation_generate_test_cases("tool-1", tool_service, db=MagicMock(), mode="generate")
    assert result == ["final"]
    assert statuses == ["in-progress", "completed"]


@pytest.mark.asyncio
async def test_validation_generate_test_cases_query(monkeypatch):
    tool_service = MagicMock()
    tool_service.get_tool = AsyncMock(return_value=DummyTool())
    record = MagicMock(run_status="completed", test_cases=[{"case": 1}])
    monkeypatch.setattr(svc, "query_testcases_table", lambda _tool_id, _db: record)

    result = await svc.validation_generate_test_cases("tool-1", tool_service, db=MagicMock(), mode="query")
    assert result == [{"case": 1}]


@pytest.mark.asyncio
async def test_validation_generate_test_cases_status_not_initiated(monkeypatch):
    tool_service = MagicMock()
    tool_service.get_tool = AsyncMock(return_value=DummyTool())
    monkeypatch.setattr(svc, "query_testcases_table", lambda _tool_id, _db: None)

    result = await svc.validation_generate_test_cases("tool-1", tool_service, db=MagicMock(), mode="status")
    assert result == [{"status": "not-initiated", "tool_id": "tool-1"}]


@pytest.mark.asyncio
async def test_validation_generate_test_cases_error(monkeypatch):
    tool_service = MagicMock()
    tool_service.get_tool = AsyncMock(side_effect=RuntimeError("boom"))
    statuses = []
    monkeypatch.setattr(svc, "populate_testcases_table", lambda _tool_id, _tcs, status, _db: statuses.append(status))

    result = await svc.validation_generate_test_cases("tool-1", tool_service, db=MagicMock(), mode="generate")
    assert result[0]["status"] == "error"
    assert "boom" in result[0]["error_message"]
    assert "failed" in statuses


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected_transport"),
    [
        ("/mcp", "streamable_http"),
        ("/sse", "sse"),
        ("http://example.com/stdio", "stdio"),
    ],
)
async def test_execute_tool_nl_test_cases_transport(monkeypatch, path, expected_transport):
    url = path if path.startswith("http") else f"http://example.com{path}"
    tool_service = MagicMock()
    tool_service.get_tool = AsyncMock(return_value=DummyTool(url))
    monkeypatch.setattr(svc, "query_tool_auth", lambda _tool_id, _db: {"Authorization": "Bearer t"})
    monkeypatch.setattr(svc, "TOOLOPS_LLM_CONFIG", svc.LLMConfig(provider="ollama", config={}))

    created_configs = []

    class DummyChatService:
        def __init__(self, config):
            created_configs.append(config)
            self.initialize = AsyncMock()
            self.chat = AsyncMock(side_effect=["ok", RuntimeError("fail")])

    monkeypatch.setattr(svc, "MCPChatService", DummyChatService)

    result = await svc.execute_tool_nl_test_cases("tool-1", ["hi", "bye"], tool_service, db=MagicMock())
    assert result[0] == "ok"
    assert "fail" in result[1]
    assert created_configs[0].mcp_server.transport == expected_transport


@pytest.mark.asyncio
async def test_enrich_tool_updates_description(monkeypatch):
    tool_service = MagicMock()
    tool_service.get_tool = AsyncMock(return_value=DummyTool())
    tool_service.update_tool = AsyncMock()

    class DummyEnrichment:
        async def enrich_mc_cf_tool(self, mcp_cf_toolspec):  # noqa: ARG002 - required signature
            return "enriched"

    monkeypatch.setattr(svc, "ToolOpsMCPCFToolEnrichment", lambda llm_client=None, gen_mode=None: DummyEnrichment())

    description, tool_schema = await svc.enrich_tool("tool-1", tool_service, db=MagicMock())
    assert description == "enriched"
    assert tool_schema.name == "tool-name"
    tool_service.update_tool.assert_awaited_once()
