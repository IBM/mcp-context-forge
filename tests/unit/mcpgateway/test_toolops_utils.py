# -*- coding: utf-8 -*-
"""Tests for toolops utility helpers."""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.toolops.utils import db_util, format_conversion, llm_util


def test_convert_to_toolops_spec_with_output_schema():
    mcp_tool = {
        "description": "desc",
        "displayName": "Display",
        "id": "tool-1",
        "inputSchema": {"description": "in", "properties": {"a": 1}, "required": ["a"]},
        "outputSchema": {"description": "out", "properties": {"b": 2}, "required": ["b"]},
        "name": "Tool",
    }

    result = format_conversion.convert_to_toolops_spec(mcp_tool)

    assert result["description"] == "desc"
    assert result["display_name"] == "Display"
    assert result["input_schema"]["properties"] == {"a": 1}
    assert result["output_schema"]["properties"] == {"b": 2}
    assert result["name"] == "Tool"


def test_convert_to_toolops_spec_without_output_schema():
    mcp_tool = {
        "description": "desc",
        "displayName": "Display",
        "id": "tool-1",
        "inputSchema": {"description": "in", "properties": {}, "required": []},
        "name": "Tool",
    }

    result = format_conversion.convert_to_toolops_spec(mcp_tool)

    assert result["output_schema"] == {}


def test_post_process_nl_test_cases_removes_keys():
    nl_test_cases = {"Test_scenarios": [{"scenario_type": "t", "input": "x", "other": 1}]}

    processed = format_conversion.post_process_nl_test_cases(nl_test_cases)

    assert processed == [{"other": 1}]


def test_populate_testcases_table_inserts_new_record():
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None

    with patch("mcpgateway.toolops.utils.db_util.TestCaseRecord") as MockRecord:
        db_util.populate_testcases_table("tool-1", [{"a": 1}], "in-progress", db)
        MockRecord.assert_called_with(tool_id="tool-1", test_cases=[{"a": 1}], run_status="in-progress")
        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()


def test_populate_testcases_table_updates_existing_record():
    db = MagicMock()
    existing = SimpleNamespace(test_cases=[], run_status="")
    db.query.return_value.filter_by.return_value.first.return_value = existing

    db_util.populate_testcases_table("tool-1", [{"a": 1}], "completed", db)

    assert existing.test_cases == [{"a": 1}]
    assert existing.run_status == "completed"
    db.add.assert_not_called()
    db.commit.assert_called_once()
    db.refresh.assert_called_once()


def test_query_testcases_table_returns_record():
    db = MagicMock()
    record = SimpleNamespace(tool_id="tool-1")
    db.query.return_value.filter_by.return_value.first.return_value = record

    assert db_util.query_testcases_table("tool-1", db) is record


def test_query_tool_auth_success():
    db = MagicMock()
    tool_record = SimpleNamespace(auth_value="encoded")
    db.query.return_value.filter_by.return_value.first.return_value = tool_record

    with patch("mcpgateway.toolops.utils.db_util.decode_auth", return_value="decoded"):
        auth = db_util.query_tool_auth("tool-1", db)

    assert auth == "decoded"


def test_query_tool_auth_exception():
    db = MagicMock()
    db.query.side_effect = Exception("boom")

    assert db_util.query_tool_auth("tool-1", db) is None


def test_get_llm_instance_unknown_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")

    llm_instance, llm_config = llm_util.get_llm_instance()

    assert llm_instance is None
    assert llm_config is None


def test_get_llm_instance_openai_sets_default_headers(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://rits.fmaas.res.ibm.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4")

    class DummyProvider:
        def __init__(self, config):
            self.config = config

        def get_llm(self, model_type="chat"):
            return f"llm-{model_type}"

    monkeypatch.setattr(llm_util, "OpenAIProvider", DummyProvider)

    llm_instance, llm_config = llm_util.get_llm_instance("completion")

    assert llm_instance == "llm-completion"
    assert llm_config.default_headers == {"RITS_API_KEY": "key"}


def test_get_llm_instance_anthropic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-3")

    class DummyProvider:
        def __init__(self, config):
            self.config = config

        def get_llm(self, model_type="chat"):
            return f"llm-{model_type}"

    monkeypatch.setattr(llm_util, "AnthropicProvider", DummyProvider)

    llm_instance, llm_config = llm_util.get_llm_instance("chat")

    assert llm_instance == "llm-chat"
    assert llm_config.api_key == "key"
    assert llm_config.model == "claude-3"


def test_get_llm_instance_ollama(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    class DummyProvider:
        def __init__(self, config):
            self.config = config

        def get_llm(self, model_type="chat"):
            return f"llm-{model_type}"

    monkeypatch.setattr(llm_util, "OllamaProvider", DummyProvider)

    llm_instance, llm_config = llm_util.get_llm_instance("completion")

    assert llm_instance == "llm-completion"
    assert llm_config.model == "llama3"
    assert llm_config.base_url == "http://localhost:11434"


def test_execute_prompt_success(monkeypatch: pytest.MonkeyPatch):
    class DummyLLM:
        def invoke(self, prompt, stop=None):
            return "hello <|eom_id|>"

    monkeypatch.setattr(llm_util, "get_llm_instance", lambda model_type="completion": (DummyLLM(), None))

    response = llm_util.execute_prompt("hi")

    assert response == "hello"


def test_execute_prompt_error(monkeypatch: pytest.MonkeyPatch):
    class DummyLLM:
        def invoke(self, prompt, stop=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(llm_util, "get_llm_instance", lambda model_type="completion": (DummyLLM(), None))

    response = llm_util.execute_prompt("hi")

    assert response == ""
