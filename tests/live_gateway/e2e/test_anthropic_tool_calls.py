# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_anthropic_tool_calls.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise a two-turn tool exchange through the gateway's Chat Completions API.
"""

# Standard
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

# Third-Party
import pytest

# Local
from tests.live_gateway.e2e.test_candidate_credential_handshake import isolated_gateway  # noqa: F401  pylint: disable=unused-import

pytestmark = pytest.mark.e2e


def test_anthropic_tool_round_trip(isolated_gateway):  # noqa: F811  pylint: disable=redefined-outer-name
    """Return two tool results in reverse order and read the provider's final answer."""
    client, *_ = isolated_gateway
    received = []
    schema = {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}

    class MessagesHandler(BaseHTTPRequestHandler):
        """Record Anthropic Messages requests from the real gateway."""

        def do_POST(self):
            """Request two tools on the first turn and read their results on the second."""
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, body))
            if len(received) == 1:
                content = [
                    {"type": "tool_use", "id": "lookup", "name": "search_docs", "input": {"topic": "MCP"}},
                    {"type": "tool_use", "id": "version", "name": "read_version", "input": {}},
                ]
                reason = "tool_use"
            else:
                results = {block["tool_use_id"]: block["content"] for block in body["messages"][-1]["content"]}
                content = [{"type": "text", "text": f"{results['lookup']} ({results['version']})"}]
                reason = "end_turn"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"id": "msg_test", "role": "assistant", "type": "message", "content": content, "stop_reason": reason}).encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), MessagesHandler) as upstream:
        thread = Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        try:
            provider = client.post("/v1/llm/providers", json={"name": "anthropic-test", "provider_type": "anthropic", "api_base": f"http://127.0.0.1:{upstream.server_port}"})
            provider.raise_for_status()
            client.post("/v1/llm/models", json={"model_id": "claude-test", "model_name": "Claude Test", "provider_id": provider.json()["id"]}).raise_for_status()
            tools = [
                {"type": "function", "function": {"name": "search_docs", "parameters": schema}},
                {"type": "function", "function": {"name": "read_version"}},
            ]
            messages = [{"role": "user", "content": "Find the MCP reference and its version."}]
            request = {"model": "claude-test", "tools": tools, "messages": messages}
            reply = client.post("/v1/chat/completions", json={**request, "tool_choice": "required"})
            reply.raise_for_status()
            path, sent = received[0]
            assert path == "/v1/messages"
            assert sent["tools"] == [{"name": "search_docs", "input_schema": schema}, {"name": "read_version", "input_schema": {"type": "object", "properties": {}}}]
            assert sent["tool_choice"] == {"type": "any"}
            choice = reply.json()["choices"][0]
            assert choice["finish_reason"] == "tool_calls"
            assistant = choice["message"]
            assert assistant["content"] is None
            lookup, version = assistant["tool_calls"]
            assert (lookup["function"]["name"], version["function"]["name"]) == ("search_docs", "read_version")
            docs = {"MCP": "Model Context Protocol"}
            found = docs[json.loads(lookup["function"]["arguments"])["topic"]]
            messages.extend([assistant, {"role": "tool", "tool_call_id": version["id"], "content": "v1"}, {"role": "tool", "tool_call_id": lookup["id"], "content": found}])
            final = client.post("/v1/chat/completions", json=request)
            final.raise_for_status()
            assert final.json()["choices"][0]["message"]["content"] == "Model Context Protocol (v1)"
            assert received[1][1]["messages"][1:] == [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "lookup", "name": "search_docs", "input": {"topic": "MCP"}},
                        {"type": "tool_use", "id": "version", "name": "read_version", "input": {}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "version", "content": "v1"},
                        {"type": "tool_result", "tool_use_id": "lookup", "content": "Model Context Protocol"},
                    ],
                },
            ]
            invalid = client.post("/v1/chat/completions", json={**request, "messages": [{"role": "tool", "content": found}]})
            assert invalid.status_code == 400
            assert len(received) == 2
        finally:
            upstream.shutdown()
            thread.join()
