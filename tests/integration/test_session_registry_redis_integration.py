# -*- coding: utf-8 -*-
"""Integration tests for Redis-backed SessionRegistry.

Location: ./tests/integration/test_session_registry_redis_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end integration test validating Redis publish/subscribe
behaviour for `SessionRegistry`. The test verifies that messages
published by one registry are delivered to a transport registered
on another registry instance via Redis pubsub and the registry's
`respond()` loop. When required the test will start a temporary
Redis container via Docker and a minimal local `/rpc` endpoint
(aiohttp) to satisfy `generate_response()` RPC calls.

Run guidance: use the `--with-integration` pytest flag so CI or
local reviewers can opt-in to tests that may start external services.
"""

import asyncio
import json
import socket
import subprocess
import time

import pytest

from mcpgateway.cache.session_registry import SessionRegistry

try:
    from aiohttp import web
except Exception:  # pragma: no cover - aiohttp may not be installed
    web = None


def _port_open(host: str, port: int, timeout: float = 0.1) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_redis_broadcast_integration():
    """Integration test: end-to-end Redis broadcast/receive using real Redis.

    This test will try to connect to Redis at localhost:6379. If not available
    and Docker is present, it will start a temporary Redis container.
    The test publishes a message from one registry and ensures the other
    registry's transport receives it.
    """
    redis_host = "127.0.0.1"
    redis_port = 6379
    container_id = None

    # If redis client package is not installed, skip the test
    try:
        from redis.asyncio import Redis  # noqa: F401
    except Exception:
        pytest.skip("redis.asyncio not available")

    # If Redis not available, try to start a Docker container
    if not _port_open(redis_host, redis_port):
        try:
            res = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "-p",
                    f"{redis_port}:6379",
                    "--name",
                    "pytest-redis-integ",
                    "redis:7",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            container_id = res.stdout.strip()
        except Exception as e:
            pytest.skip(f"Redis not available and docker start failed: {e}")

        # Wait for redis to accept connections
        for _ in range(50):
            if _port_open(redis_host, redis_port):
                break
            time.sleep(0.1)
        else:
            # cleanup container if started
            if container_id:
                subprocess.run(["docker", "stop", container_id], check=False)
            pytest.skip("Redis did not start in time")

    redis_url = f"redis://{redis_host}:{redis_port}"
    # Start a minimal HTTP RPC server to satisfy generate_response RPC calls
    rpc_server = None
    rpc_runner = None
    rpc_site = None
    rpc_url = "http://127.0.0.1:8000"
    if web is not None:
        async def rpc_handler(request):
            try:
                data = await request.json()
            except Exception:
                data = {}
            # Return a minimal JSON-RPC response
            return web.json_response({"result": {}})

        app = web.Application()
        app.router.add_post("/rpc", rpc_handler)
        rpc_runner = web.AppRunner(app)
        await rpc_runner.setup()
        rpc_site = web.TCPSite(rpc_runner, "127.0.0.1", 8000)
        await rpc_site.start()
    else:
        rpc_url = "http://localhost"

    reg_a = SessionRegistry(backend="redis", redis_url=redis_url)
    reg_b = SessionRegistry(backend="redis", redis_url=redis_url)
    await reg_a.initialize()
    await reg_b.initialize()

    messages = []
    msg_event = asyncio.Event()

    class DummyTransport:
        async def send_message(self, msg):
            messages.append(msg)
            msg_event.set()

        async def disconnect(self):
            return

        async def is_connected(self):
            return True

    transport = DummyTransport()

    await reg_a.add_session("sid-integ", transport)

    # Start respond listener on reg_a
    task = asyncio.create_task(reg_a.respond(None, {"token": "t"}, "sid-integ", rpc_url))

    # allow subscription to be established
    await asyncio.sleep(0.1)

    await reg_b.broadcast("sid-integ", {"method": "ping", "id": 99})

    try:
        await asyncio.wait_for(msg_event.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        # cleanup
        task.cancel()
        await reg_a.remove_session("sid-integ")
        await reg_a.shutdown()
        await reg_b.shutdown()
        if container_id:
            subprocess.run(["docker", "stop", container_id], check=False)
        pytest.fail("Did not receive message via Redis pubsub in time")

    # Basic assertions
    assert messages, "No messages received"
    assert isinstance(messages[0], dict)

    # Cleanup
    task.cancel()
    await reg_a.remove_session("sid-integ")
    await reg_a.shutdown()
    await reg_b.shutdown()

    if rpc_runner is not None:
        await rpc_runner.cleanup()

    if container_id:
        subprocess.run(["docker", "stop", container_id], check=False)
