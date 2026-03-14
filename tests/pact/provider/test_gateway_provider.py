# -*- coding: utf-8 -*-
"""Provider contract tests: Clients calling Gateway APIs.

These tests verify that the Gateway correctly fulfils the contracts
defined by its consumers. The Gateway is started as a real ASGI
application via Starlette's TestClient and the Pact verifier replays
recorded interactions against it.
"""

import os
import threading
import time

import pytest
import uvicorn

from pact import Verifier


PROVIDER_NAME = "mcp-gateway-api"
PROVIDER_HOST = "127.0.0.1"
PROVIDER_PORT = 18927  # Ephemeral-range port for test isolation

PACT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "pacts")


def _find_pact_files():
    """Return list of pact JSON files in the pacts directory."""
    if not os.path.isdir(PACT_DIR):
        return []
    return [os.path.join(PACT_DIR, f) for f in os.listdir(PACT_DIR) if f.endswith(".json")]


def _setup_provider_state(state_name, action="setup", **kwargs):
    """Set up provider states for contract verification.

    This handler is called by the Pact verifier before each interaction
    to prepare the provider with the correct test data.
    """
    pass


@pytest.mark.pact
class TestGatewayProviderToolsAPI:
    """Verify Gateway tools API against consumer contracts."""

    def test_list_tools_contract(self, provider_client):
        """Verify GET /tools returns expected contract shape."""
        response = provider_client.get("/tools")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)

    def test_create_and_get_tool_contract(self, provider_client):
        """Verify POST /tools and GET /tools/{id} contract shape."""
        # FastAPI expects body params nested under parameter names when multiple Body() params exist
        payload = {
            "tool": {
                "name": "pact-test-tool",
                "url": "http://example.com/api/test",
                "description": "A tool created for contract testing",
                "integration_type": "REST",
                "request_type": "GET",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
        create_resp = provider_client.post("/tools", json=payload)
        assert create_resp.status_code in (200, 201)
        created = create_resp.json()
        assert "id" in created
        assert created["originalName"] == "pact-test-tool"
        assert created["description"] == "A tool created for contract testing"
        assert created["requestType"] == "GET"
        assert created["integrationType"] == "REST"

        # Verify GET by ID
        get_resp = provider_client.get(f"/tools/{created['id']}")
        assert get_resp.status_code == 200
        fetched = get_resp.json()
        assert fetched["id"] == created["id"]
        assert fetched["originalName"] == "pact-test-tool"


@pytest.mark.pact
class TestGatewayProviderResourcesAPI:
    """Verify Gateway resources API against consumer contracts."""

    def test_list_resources_contract(self, provider_client):
        """Verify GET /resources returns expected contract shape."""
        response = provider_client.get("/resources")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)

    def test_create_and_get_resource_contract(self, provider_client):
        """Verify POST /resources and GET /resources/{id}/info contract shape."""
        payload = {
            "resource": {
                "uri": "file:///pact-test-resource.txt",
                "name": "pact-test-resource",
                "description": "A resource for contract testing",
                "mime_type": "text/plain",
                "content": "Contract test content",
            },
        }
        create_resp = provider_client.post("/resources", json=payload)
        assert create_resp.status_code in (200, 201)
        created = create_resp.json()
        assert "id" in created
        assert created["name"] == "pact-test-resource"
        assert created["uri"] == "file:///pact-test-resource.txt"
        assert created["enabled"] is True

        # Verify GET info by ID
        info_resp = provider_client.get(f"/resources/{created['id']}/info")
        assert info_resp.status_code == 200
        fetched = info_resp.json()
        assert fetched["id"] == created["id"]
        assert fetched["name"] == "pact-test-resource"


@pytest.mark.pact
class TestGatewayProviderPromptsAPI:
    """Verify Gateway prompts API against consumer contracts."""

    def test_list_prompts_contract(self, provider_client):
        """Verify GET /prompts returns expected contract shape."""
        response = provider_client.get("/prompts")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)

    def test_create_and_get_prompt_contract(self, provider_client):
        """Verify POST /prompts and GET /prompts/{id} contract shape."""
        payload = {
            "prompt": {
                "name": "pact-test-prompt",
                "description": "A prompt for contract testing",
                "template": "Please summarize the following: {{text}}",
                "arguments": [{"name": "text", "description": "Text to summarize", "required": True}],
            },
        }
        create_resp = provider_client.post("/prompts", json=payload)
        assert create_resp.status_code in (200, 201)
        created = create_resp.json()
        assert "id" in created
        assert created["name"] == "pact-test-prompt"
        assert created["description"] == "A prompt for contract testing"
        assert created["template"] == "Please summarize the following: {{text}}"
        assert created["enabled"] is True
        assert len(created["arguments"]) == 1

        # Verify GET by ID
        get_resp = provider_client.get(f"/prompts/{created['id']}")
        assert get_resp.status_code == 200


@pytest.mark.pact
class TestGatewayProviderServersAPI:
    """Verify Gateway servers (virtual MCP servers) API contract shape."""

    def test_list_servers_contract(self, provider_client):
        """Verify GET /servers returns expected contract shape."""
        response = provider_client.get("/servers")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)


@pytest.mark.pact
class TestGatewayProviderGatewaysAPI:
    """Verify Gateway federation (gateways) API contract shape."""

    def test_list_gateways_contract(self, provider_client):
        """Verify GET /gateways returns expected contract shape."""
        response = provider_client.get("/gateways")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)


@pytest.mark.pact
class TestGatewayProviderPactVerification:
    """Verify Gateway against generated consumer pact files.

    This test runs the Pact verifier against all pact files found in
    the pacts/ directory.  It is skipped when no pact files exist
    (i.e. consumer tests have not been run yet).
    """

    def test_verify_consumer_pacts(self, provider_app):
        """Verify provider against all consumer pact files."""
        pact_files = _find_pact_files()
        if not pact_files:
            pytest.skip("No pact files found - run consumer tests first (make pact-consumer)")

        # Start the provider app on a background thread
        config = uvicorn.Config(provider_app, host=PROVIDER_HOST, port=PROVIDER_PORT, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        # Wait for server readiness
        import httpx

        for _ in range(50):
            try:
                httpx.get(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}/health", timeout=0.5)
                break
            except (httpx.ConnectError, httpx.ReadError):
                time.sleep(0.1)

        try:
            verifier = Verifier(PROVIDER_NAME, f"http://{PROVIDER_HOST}:{PROVIDER_PORT}")
            for pf in pact_files:
                verifier.add_source(pf)
            verifier.state_handler(_setup_provider_state, teardown=False)
            verifier.verify()
        finally:
            server.should_exit = True
            thread.join(timeout=5)
