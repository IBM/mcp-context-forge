# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_dataplane_plugin_publication.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box control-plane HTTP mutations to published Redis plugin configuration.

Run against a dedicated gateway with DATAPLANE_PUBLISHER=true, a short publish
interval, and PLUGINS_ENABLED=true. Set DATAPLANE_PLUGIN_E2E_REDIS_URL to its
Redis URL and DATAPLANE_PLUGIN_E2E_NAME to a configured plugin name. The shared
fixtures require fast-time-server at FAST_TIME_SERVER_URL. MCP_CLI_BASE_URL and
JWT_SECRET_KEY must match the gateway. No gateway internals are imported.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

import msgpack
import pytest
from redis import Redis

from tests.live_gateway.plugins import _helpers

REDIS_URL = os.getenv("DATAPLANE_PLUGIN_E2E_REDIS_URL")
PLUGIN_NAME = os.getenv("DATAPLANE_PLUGIN_E2E_NAME", "PublisherGuard")
PLUGIN_KEY = "ContextForgeGatewayRuntimePluginConfig"
pytestmark = [pytest.mark.e2e, pytest.mark.skipif(not REDIS_URL, reason="requires a dedicated dataplane publisher stack")]


def _wait_for_document(redis: Redis, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """Wait for a complete publisher cycle to expose the expected policy."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        raw = redis.get(PLUGIN_KEY)
        if raw is not None:
            document: dict[str, Any] = msgpack.unpackb(raw, raw=False)
            if predicate(document):
                return document
        time.sleep(0.2)
    pytest.fail("Dataplane policy did not reflect the HTTP mutation within 30 seconds")


def _plugin(document: dict[str, Any], context_id: str) -> dict[str, Any] | None:
    """Find the configured plugin in a published scoped policy."""
    return next((plugin for plugin in document["contexts"].get(context_id, {}).get("plugins", []) if plugin["name"] == PLUGIN_NAME), None)


def test_binding_changes_reach_dataplane_redis(admin_client, fast_time_server):
    """Add, update, disable and remove a binding through the live gateway API."""
    assert REDIS_URL is not None
    context_id = f"{fast_time_server['team_id']}::{fast_time_server['echo_tool']}"
    with Redis.from_url(REDIS_URL) as redis:
        initial = _wait_for_document(redis, lambda doc: _plugin(doc, context_id) is not None)
        assert initial["version"] == 2
        assert initial["enabled"] is True
        original = _plugin(initial, context_id)
        assert original is not None

        # The routed upstream name must retain its owning team and canonical
        # gateway name, so direct and aliased routes can select the same policy.
        user_configs = []
        for key in redis.scan_iter(match=b"\x92\xaaUserConfig*"):
            raw = redis.get(key)
            if raw is not None:  # A snapshot can expire between SCAN and GET.
                user_configs.append(msgpack.unpackb(raw, raw=False))
        contexts = [
            context
            for config in user_configs
            for virtual_host in config["virtual_hosts"].values()
            for backend in virtual_host["backends"].values()
            for context in backend["tool_policy_contexts"].values()
            if context["context_id"] == context_id
        ]
        assert contexts
        assert all(context["team_id"] == fast_time_server["team_id"] and context["name"] == fast_time_server["echo_tool"] for context in contexts)

        binding_id = None
        try:
            for mode, expected_mode, priority in [("enforce_ignore_error", "sequential", 7), ("permissive", "transform", 8), ("disabled", "disabled", 9)]:
                override_config = {**(original["config"] or {}), "publisher_test_revision": priority}
                binding = _helpers.create_tool_plugin_binding(
                    admin_client,
                    team_id=fast_time_server["team_id"],
                    tool_name=fast_time_server["echo_tool"],
                    plugin_id=PLUGIN_NAME,
                    config=override_config,
                    mode=mode,
                    priority=priority,
                )
                binding_id = binding["id"]
                document = _wait_for_document(redis, lambda doc: (_plugin(doc, context_id) or {}).get("priority") == priority)
                effective = _plugin(document, context_id)
                assert effective is not None
                assert effective["mode"] == expected_mode
                assert effective["config"] == override_config
                if mode == "enforce_ignore_error":
                    assert effective["on_error"] == "ignore"
                assert document["global"]["plugins"] == initial["global"]["plugins"]
        finally:
            if binding_id is not None:
                response = admin_client.delete(f"/v1/tools/plugin_bindings/{binding_id}")
                assert response.status_code == 200, response.text

        _wait_for_document(redis, lambda doc: _plugin(doc, context_id) == original)
        assert redis.ttl(PLUGIN_KEY) > 0
