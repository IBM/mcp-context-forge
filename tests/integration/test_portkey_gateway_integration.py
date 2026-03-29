# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_portkey_gateway_integration.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for the Portkey external LLM gateway runtime.
"""

# Standard
import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import shutil
import socket
import subprocess
import threading
import time
from unittest.mock import MagicMock
import uuid
from typing import Any, Dict, List, Optional

# Third-Party
import httpx
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import LLMModel, LLMProvider, LLMProviderType
from mcpgateway.llm_schemas import ChatCompletionRequest, ChatMessage
from mcpgateway.routers import llm_admin_router
from mcpgateway.services.llm_proxy_service import LLMProxyService

pytestmark = pytest.mark.integration


def _get_free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_http(url: str, timeout: float = 30.0) -> None:
    """Wait until an HTTP endpoint responds with any status code."""
    deadline = time.time() + timeout
    last_error: Optional[Exception] = None

    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=1.0)
            response.read()
            return
        except Exception as exc:  # pragma: no cover - exercised only on retry paths
            last_error = exc
            time.sleep(0.2)

    raise RuntimeError(f"Timed out waiting for HTTP endpoint {url}: {last_error}")


class _RequestRecorder:
    """Thread-safe request recorder for the mock upstream server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: List[Dict[str, Any]] = []

    def add(self, method: str, path: str, headers: Dict[str, str], body: Optional[Dict[str, Any]]) -> None:
        with self._lock:
            self._records.append(
                {
                    "method": method,
                    "path": path,
                    "headers": headers,
                    "body": body,
                }
            )

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._records)


def _make_openai_handler(recorder: _RequestRecorder):
    """Create an OpenAI-compatible mock server handler."""

    class OpenAICompatibleHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
            self.wfile.flush()
            self.close_connection = True

        def _read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            recorder.add("GET", self.path, dict(self.headers.items()), None)
            if self.path == "/v1/models":
                self._send_json(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": "mock-gpt-4o-mini",
                                "object": "model",
                                "created": 1,
                                "owned_by": "integration-test",
                            }
                        ],
                    },
                )
                return

            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            body = self._read_json_body()
            recorder.add("POST", self.path, dict(self.headers.items()), body)

            if self.path != "/v1/chat/completions":
                self._send_json(404, {"error": "not found"})
                return

            if body.get("stream"):
                chunks = [
                    {
                        "id": "chatcmpl-stream",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": body.get("model", "unknown-model"),
                        "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Port"}, "finish_reason": None}],
                    },
                    {
                        "id": "chatcmpl-stream",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": body.get("model", "unknown-model"),
                        "choices": [{"index": 0, "delta": {"content": "key"}, "finish_reason": "stop"}],
                    },
                ]

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True
                return

            payload = {
                "id": "chatcmpl-nonstream",
                "object": "chat.completion",
                "created": 1,
                "model": body.get("model", "unknown-model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Portkey integration response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            }
            self._send_json(200, payload)

    return OpenAICompatibleHandler


@pytest.fixture
def openai_mock_server():
    """Start a mock OpenAI-compatible upstream server on the host."""
    recorder = _RequestRecorder()
    server = ThreadingHTTPServer(("0.0.0.0", 0), _make_openai_handler(recorder))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host_port = int(server.server_address[1])
    try:
        yield {
            "api_base": f"http://127.0.0.1:{host_port}/v1",
            "custom_host": f"http://host.docker.internal:{host_port}/v1",
            "recorder": recorder,
        }
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture(scope="module")
def portkey_gateway_url():
    """Start a real Portkey container and return its mapped /v1 base URL."""
    if shutil.which("docker") is None:
        pytest.skip("docker is required for Portkey integration tests")

    host_port = _get_free_port()
    container_name = f"pytest-portkey-{uuid.uuid4().hex[:8]}"

    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                container_name,
                "--add-host",
                "host.docker.internal:host-gateway",
                "-p",
                f"{host_port}:8787",
                "portkeyai/gateway:latest",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as exc:
        pytest.skip(f"Unable to start Portkey container: {exc}")

    try:
        _wait_for_http(f"http://127.0.0.1:{host_port}/v1/models")
        yield f"http://127.0.0.1:{host_port}/v1"
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


def _create_openai_provider_and_model(
    db: Session,
    api_base: str,
    *,
    portkey_custom_host: Optional[str] = None,
) -> LLMModel:
    """Create a provider/model pair backed by the mock upstream."""
    suffix = uuid.uuid4().hex[:10]
    config: Dict[str, Any] = {}
    if portkey_custom_host:
        config["portkey_custom_host"] = portkey_custom_host

    provider = LLMProvider(
        name=f"Portkey Integration Provider {suffix}",
        slug=f"portkey-integration-provider-{suffix}",
        provider_type=LLMProviderType.OPENAI,
        api_base=api_base,
        enabled=True,
        config=config,
        default_temperature=0.2,
        default_max_tokens=64,
    )
    db.add(provider)
    db.flush()

    model = LLMModel(
        provider_id=provider.id,
        model_id=f"mock-gpt-{suffix}",
        model_name=f"Mock GPT {suffix}",
        model_alias=f"mock-alias-{suffix}",
        supports_chat=True,
        supports_streaming=True,
        enabled=True,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


async def _wait_for_request_count(recorder: _RequestRecorder, expected_count: int, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """Wait until the mock upstream has observed at least the expected number of requests."""
    deadline = time.time() + timeout
    snapshot = recorder.snapshot()
    while len(snapshot) < expected_count and time.time() < deadline:
        await asyncio.sleep(0.1)
        snapshot = recorder.snapshot()

    if len(snapshot) < expected_count:
        raise AssertionError(f"Expected at least {expected_count} upstream requests, got {len(snapshot)}")
    return snapshot


@pytest.mark.asyncio
async def test_portkey_edge_chat_completion_integration(test_db, monkeypatch: pytest.MonkeyPatch, openai_mock_server, portkey_gateway_url):
    """Edge mode should route `/v1/chat/completions` through a real Portkey sidecar."""
    model = _create_openai_provider_and_model(
        test_db,
        openai_mock_server["api_base"],
        portkey_custom_host=openai_mock_server["custom_host"],
    )

    monkeypatch.setattr(settings, "llm_gateway_mode", "edge", raising=False)
    monkeypatch.setattr(settings, "llm_gateway_url", portkey_gateway_url, raising=False)

    service = LLMProxyService()
    await service.initialize()
    try:
        response = await service.chat_completion(
            test_db,
            ChatCompletionRequest(
                model=model.model_id,
                messages=[ChatMessage(role="user", content="hello from integration test")],
            ),
        )
    finally:
        await service.shutdown()

    requests = openai_mock_server["recorder"].snapshot()
    assert response.model == model.model_id
    assert response.choices[0].message.content == "Portkey integration response"
    assert len(requests) == 1
    assert requests[0]["path"] == "/v1/chat/completions"
    assert requests[0]["body"]["model"] == model.model_id


@pytest.mark.asyncio
async def test_portkey_edge_streaming_integration(test_db, monkeypatch: pytest.MonkeyPatch, openai_mock_server, portkey_gateway_url):
    """Edge mode should relay streaming responses through Portkey unchanged."""
    model = _create_openai_provider_and_model(
        test_db,
        openai_mock_server["api_base"],
        portkey_custom_host=openai_mock_server["custom_host"],
    )

    monkeypatch.setattr(settings, "llm_gateway_mode", "edge", raising=False)
    monkeypatch.setattr(settings, "llm_gateway_url", portkey_gateway_url, raising=False)

    service = LLMProxyService()
    await service.initialize()
    try:
        chunks = [
            chunk
            async for chunk in service.chat_completion_stream(
                test_db,
                ChatCompletionRequest(
                    model=model.model_id,
                    stream=True,
                    messages=[ChatMessage(role="user", content="stream please")],
                ),
            )
        ]
    finally:
        await service.shutdown()

    requests = openai_mock_server["recorder"].snapshot()
    assert requests[0]["body"]["stream"] is True
    assert any('"content":"Port"' in chunk or '"content": "Port"' in chunk for chunk in chunks)
    assert any('"content":"key"' in chunk or '"content": "key"' in chunk for chunk in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_portkey_shadow_mode_mirrors_request(test_db, monkeypatch: pytest.MonkeyPatch, openai_mock_server, portkey_gateway_url):
    """Shadow mode should keep the direct response and mirror the request through Portkey."""
    model = _create_openai_provider_and_model(
        test_db,
        openai_mock_server["api_base"],
        portkey_custom_host=openai_mock_server["custom_host"],
    )

    monkeypatch.setattr(settings, "llm_gateway_mode", "shadow", raising=False)
    monkeypatch.setattr(settings, "llm_gateway_url", portkey_gateway_url, raising=False)

    service = LLMProxyService()
    await service.initialize()
    try:
        response = await service.chat_completion(
            test_db,
            ChatCompletionRequest(
                model=model.model_id,
                messages=[ChatMessage(role="user", content="shadow please")],
            ),
        )
        requests = await _wait_for_request_count(openai_mock_server["recorder"], 2)
    finally:
        await service.shutdown()

    assert response.choices[0].message.content == "Portkey integration response"
    assert [request["path"] for request in requests] == ["/v1/chat/completions", "/v1/chat/completions"]


@pytest.mark.asyncio
async def test_portkey_full_mode_fetch_models_integration(test_db, monkeypatch: pytest.MonkeyPatch, openai_mock_server, portkey_gateway_url):
    """Full mode should use Portkey for admin model discovery."""
    model = _create_openai_provider_and_model(
        test_db,
        openai_mock_server["api_base"],
        portkey_custom_host=openai_mock_server["custom_host"],
    )

    monkeypatch.setattr(settings, "llm_gateway_mode", "full", raising=False)
    monkeypatch.setattr(settings, "llm_gateway_url", portkey_gateway_url, raising=False)

    result = await llm_admin_router.fetch_provider_models.__wrapped__(
        MagicMock(),
        model.provider_id,
        db=test_db,
        current_user_ctx={"db": test_db, "email": "integration@example.com"},
    )

    requests = openai_mock_server["recorder"].snapshot()
    assert result["success"] is True
    assert result["count"] == 1
    assert result["models"][0]["id"] == "mock-gpt-4o-mini"
    assert len(requests) == 1
    assert requests[0]["path"] == "/v1/models"
