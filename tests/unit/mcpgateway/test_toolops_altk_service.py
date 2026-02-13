# -*- coding: utf-8 -*-
"""Tests for toolops_altk_service."""

# Standard
import importlib.util
import sys
import types
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import orjson
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
async def test_validation_generate_test_cases_status_with_record(monkeypatch):
    tool_service = MagicMock()
    tool_service.get_tool = AsyncMock(return_value=DummyTool())
    record = MagicMock(run_status="in-progress")
    monkeypatch.setattr(svc, "query_testcases_table", lambda _tool_id, _db: record)

    result = await svc.validation_generate_test_cases("tool-1", tool_service, db=MagicMock(), mode="status")
    assert result == [{"status": "in-progress", "tool_id": "tool-1"}]


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


@pytest.mark.asyncio
async def test_enrich_tool_update_tool_failure_does_not_raise(monkeypatch):
    tool_service = MagicMock()
    tool_service.get_tool = AsyncMock(return_value=DummyTool())
    tool_service.update_tool = AsyncMock(side_effect=RuntimeError("update boom"))

    class DummyEnrichment:
        async def enrich_mc_cf_tool(self, mcp_cf_toolspec):  # noqa: ARG002 - required signature
            return "enriched"

    monkeypatch.setattr(svc, "ToolOpsMCPCFToolEnrichment", lambda llm_client=None, gen_mode=None: DummyEnrichment())

    description, tool_schema = await svc.enrich_tool("tool-1", tool_service, db=MagicMock())
    assert description == "enriched"
    assert tool_schema.name == "tool-name"


@pytest.mark.asyncio
async def test_enrich_tool_conversion_failure_raises(monkeypatch):
    tool_service = MagicMock()
    tool_service.get_tool = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await svc.enrich_tool("tool-1", tool_service, db=MagicMock())


@pytest.mark.asyncio
async def test_execute_tool_nl_testcases_json_decode_error_maps_to_http_400(monkeypatch):
    """Router should map JSON decode issues to HTTP 400 for execute endpoint."""
    # First-Party
    from mcpgateway.routers import toolops_router as router

    try:
        orjson.loads("{")
    except orjson.JSONDecodeError as exc:
        json_error = exc

    monkeypatch.setattr(router, "execute_tool_nl_test_cases", AsyncMock(side_effect=json_error))

    with pytest.raises(HTTPException) as exc_info:
        await router.execute_tool_nl_testcases(
            router.ToolNLTestInput(tool_id="tool-1", tool_nl_test_cases=["ping"]),
            db=MagicMock(),
            _user={"email": "test@example.com"},
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid JSON in request body"


def test_import_with_altk_present_overrides_execute_prompt_and_builds_llm_config(monkeypatch):
    # Patch MCP-CF get_llm_instance (imported by toolops module at import time) so the module creates TOOLOPS_LLM_CONFIG.
    import mcpgateway.toolops.utils.llm_util as mcpgw_llm_util

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(mcpgw_llm_util, "get_llm_instance", lambda *_a, **_k: (MagicMock(), {}))

    # Create a fake ALTK package tree so the optional imports succeed.
    def _pkg(name: str) -> types.ModuleType:
        m = types.ModuleType(name)
        m.__path__ = []  # mark as a package
        monkeypatch.setitem(sys.modules, name, m)
        return m

    def _mod(name: str) -> types.ModuleType:
        m = types.ModuleType(name)
        monkeypatch.setitem(sys.modules, name, m)
        return m

    pkgs = [
        "altk",
        "altk.build_time",
        "altk.build_time.test_case_generation_toolkit",
        "altk.build_time.test_case_generation_toolkit.src",
        "altk.build_time.test_case_generation_toolkit.src.toolops",
        "altk.build_time.test_case_generation_toolkit.src.toolops.enrichment",
        "altk.build_time.test_case_generation_toolkit.src.toolops.enrichment.mcp_cf_tool_enrichment",
        "altk.build_time.test_case_generation_toolkit.src.toolops.generation",
        "altk.build_time.test_case_generation_toolkit.src.toolops.generation.nl_utterance_generation",
        "altk.build_time.test_case_generation_toolkit.src.toolops.generation.test_case_generation",
        "altk.build_time.test_case_generation_toolkit.src.toolops.utils",
    ]
    for p in pkgs:
        _pkg(p)

    prompt_utils_obj = types.SimpleNamespace(execute_prompt=None)
    nlg_util_obj = types.SimpleNamespace(execute_prompt=None)
    prompt_execution_obj = types.SimpleNamespace(execute_prompt=None)
    llm_util_obj = types.SimpleNamespace(execute_prompt=None)

    # altk...mcp_cf_tool_enrichment provides prompt_utils
    sys.modules["altk.build_time.test_case_generation_toolkit.src.toolops.enrichment.mcp_cf_tool_enrichment"].prompt_utils = prompt_utils_obj
    enrichment_mod = _mod("altk.build_time.test_case_generation_toolkit.src.toolops.enrichment.mcp_cf_tool_enrichment.enrichment")
    enrichment_mod.ToolOpsMCPCFToolEnrichment = object

    # altk...nl_utterance_generation provides NlUtteranceGeneration and nlg_util
    nl_mod = _mod("altk.build_time.test_case_generation_toolkit.src.toolops.generation.nl_utterance_generation.nl_utterance_generation")
    nl_mod.NlUtteranceGeneration = object
    nl_utils_mod = _mod("altk.build_time.test_case_generation_toolkit.src.toolops.generation.nl_utterance_generation.nl_utterance_generation_utils")
    nl_utils_mod.nlg_util = nlg_util_obj

    # altk...test_case_generation provides TestcaseGeneration and prompt_execution
    tc_mod = _mod("altk.build_time.test_case_generation_toolkit.src.toolops.generation.test_case_generation.test_case_generation")
    tc_mod.TestcaseGeneration = object
    tc_utils_mod = _mod("altk.build_time.test_case_generation_toolkit.src.toolops.generation.test_case_generation.test_case_generation_utils")
    tc_utils_mod.prompt_execution = prompt_execution_obj

    # altk...toolops.utils provides llm_util
    sys.modules["altk.build_time.test_case_generation_toolkit.src.toolops.utils"].llm_util = llm_util_obj

    # Import the module under an alternate name so we don't disturb the already-imported module used by other tests.
    spec = importlib.util.spec_from_file_location("mcpgateway.toolops._toolops_altk_service_altk_present", svc.__file__)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    assert module.TOOLOPS_LLM_CONFIG is not None
    assert module.llm_util.execute_prompt is module.custom_mcp_cf_execute_prompt
    assert module.prompt_execution.execute_prompt is module.custom_mcp_cf_execute_prompt
    assert module.nlg_util.execute_prompt is module.custom_mcp_cf_execute_prompt
    assert module.prompt_utils.execute_prompt is module.custom_mcp_cf_execute_prompt
