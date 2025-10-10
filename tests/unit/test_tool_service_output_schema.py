import asyncio
from unittest.mock import MagicMock

import pytest

from mcpgateway.services.tool_service import ToolService
from mcpgateway.models import TextContent


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        return None


class FakeHttpClient:
    def __init__(self, response: FakeResponse):
        self._response = response

    async def request(self, method, url, json=None, headers=None):
        return self._response

    async def get(self, url, params=None, headers=None):
        return self._response


class DummyTool:
    def __init__(self):
        self.name = "dummy"
        self.enabled = True
        self.reachable = True
        self.integration_type = "REST"
        self.url = "http://example.local"
        self.request_type = "POST"
        self.headers = {}
        self.auth_type = None
        self.auth_value = None
        self.jsonpath_filter = ""
        # Provide an output_schema to trigger structured-content behavior
        self.output_schema = {"type": "object", "properties": {"y": {"type": "number"}}}
        # Minimal attributes expected by ToolService.invoke_tool
        self.id = 1
        self.gateway_id = None


@pytest.mark.asyncio
async def test_invoke_tool_returns_structured_content_when_output_schema_present():
    svc = ToolService()

    # fake DB that returns our dummy tool for the select
    db = MagicMock()
    fake_tool = DummyTool()
    # db.execute(...).scalar_one_or_none() should return the tool
    m = MagicMock()
    m.scalar_one_or_none.return_value = fake_tool
    db.execute.return_value = m

    # Replace the http client with a fake response returning JSON
    svc._http_client = FakeHttpClient(FakeResponse({"y": 10.0, "z": 20.0, "result": 30.0}, status_code=200))

    result = await svc.invoke_tool(db, "dummy", {})

    dumped = result.model_dump()
    assert isinstance(dumped, dict)
    # New behavior: when structuredContent is present and valid we remove
    # the unstructured textual `content` entry and return the parsed object
    # in `structuredContent` (clients should prefer structuredContent).
    assert "structuredContent" in dumped
    structured = dumped["structuredContent"]
    assert isinstance(structured, dict)
    assert structured.get("y") == 10.0
    assert structured.get("z") == 20.0
    assert structured.get("result") == 30.0
    # content may be empty when structuredContent is valid
    assert dumped.get("content", []) == []
