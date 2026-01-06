# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_elicitation_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
Unit tests for elicitation services.
"""

import asyncio
import pytest
import time
from unittest.mock import MagicMock

import mcpgateway.services.elicitation_service as svc


class DummyElicitResult:
    def __init__(self, action, content=None):
        self.action = action
        self.content = content


# --------------------------------------------------------------------------- #
# SERVICE INITIALIZATION AND CLEANUP
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_service_start_and_shutdown(monkeypatch):
    service = svc.ElicitationService(default_timeout=0.1, max_concurrent=2, cleanup_interval=1)
    await service.start()
    assert isinstance(service._cleanup_task, asyncio.Task)

    # Insert a pending elicitation
    fut = asyncio.Future()
    p = svc.PendingElicitation(
        request_id="abc",
        upstream_session_id="u",
        downstream_session_id="d",
        created_at=time.time(),
        timeout=1,
        message="m",
        schema={"type": "object", "properties": {}},
        future=fut,
    )
    service._pending[p.request_id] = p
    await service.shutdown()
    assert len(service._pending) == 0


@pytest.mark.asyncio
async def test_create_elicitation_and_complete(monkeypatch):
    service = svc.ElicitationService(default_timeout=0.5)
    monkeypatch.setattr(service, "_validate_schema", lambda s: None)

    async def complete_later(req_id):
        await asyncio.sleep(0.05)
        result = DummyElicitResult("accept", {"field": "value"})
        service.complete_elicitation(req_id, result)

    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    task = asyncio.create_task(
        service.create_elicitation("u", "d", "msg", schema, timeout=0.5)
    )

    # give coroutine time to execute and create _pending
    for _ in range(30):
        if service._pending:
            break
        await asyncio.sleep(0.02)
    assert service._pending, "Expected at least one pending elicitation"

    rid = next(iter(service._pending.keys()))
    asyncio.create_task(complete_later(rid))

    result = await task
    assert result.action == "accept"


@pytest.mark.asyncio
async def test_create_elicitation_limit_and_timeout(monkeypatch):
    service = svc.ElicitationService(max_concurrent=1, default_timeout=0.01)
    service._pending = {"1": MagicMock()}
    with pytest.raises(ValueError):
        await service.create_elicitation("u", "d", "msg", {"type": "object", "properties": {}})

    # Reset pending to allow next test
    service._pending.clear()

    # timeout path
    with pytest.raises(asyncio.TimeoutError):
        await service.create_elicitation("u", "d", "msg", {"type": "object", "properties": {}}, timeout=0.001)


def test_complete_get_and_count(monkeypatch):
    service = svc.ElicitationService()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    future = loop.create_future()
    e = svc.PendingElicitation("id", "u", "d", time.time(), 1, "m", {"type": "object", "properties": {}}, future)
    service._pending[e.request_id] = e
    res = DummyElicitResult("accept")
    assert service.complete_elicitation("id", res)
    assert not service.complete_elicitation("id", res)
    assert not service.complete_elicitation("missing", res)
    assert service.get_pending_elicitation("id") is not None
    assert isinstance(service.get_pending_for_session("u"), list)
    assert service.get_pending_count() >= 0
    loop.close()


# --------------------------------------------------------------------------- #
# CLEANUP LOOP AND EXPIRED CLEANUP
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_cleanup_expired(monkeypatch):
    service = svc.ElicitationService()
    fut = asyncio.Future()
    e = svc.PendingElicitation("x", "u", "d", time.time() - 100, 0.1, "m", {"type": "object", "properties": {}}, fut)
    service._pending[e.request_id] = e
    await service._cleanup_expired()
    assert e.request_id not in service._pending


@pytest.mark.asyncio
async def test_cleanup_loop_cancel(monkeypatch):
    s = svc.ElicitationService()
    task = asyncio.create_task(s._cleanup_loop())
    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.sleep(0.01)  # give cancellation a tick
    assert task.cancelled() or task.done()


# --------------------------------------------------------------------------- #
# SCHEMA VALIDATION TESTS
# --------------------------------------------------------------------------- #

def test_validate_schema_success(monkeypatch):
    s = svc.ElicitationService()
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "email": {"type": "string", "format": "email"},
        },
    }
    s._validate_schema(schema)


def test_validate_schema_failures(monkeypatch):
    s = svc.ElicitationService()
    with pytest.raises(ValueError):
        s._validate_schema("bad")
    with pytest.raises(ValueError):
        s._validate_schema({"type": "wrong"})
    with pytest.raises(ValueError):
        s._validate_schema({"type": "object", "properties": "bad"})

    bad_type = {"type": "object", "properties": {"x": {"type": "complex"}}}
    with pytest.raises(ValueError):
        s._validate_schema(bad_type)

    bad_nested = {"type": "object", "properties": {"y": {"type": "string", "properties": {}}}}
    with pytest.raises(ValueError):
        s._validate_schema(bad_nested)


def test_validate_schema_warns(monkeypatch, caplog):
    s = svc.ElicitationService()
    schema = {"type": "object", "properties": {"f": {"type": "string", "format": "unknown"}}}
    s._validate_schema(schema)
    assert "non-standard format" in caplog.text


# --------------------------------------------------------------------------- #
# GLOBAL SINGLETON TESTS
# --------------------------------------------------------------------------- #

def test_global_singleton(monkeypatch):
    s1 = svc.get_elicitation_service()
    assert isinstance(s1, svc.ElicitationService)
    s2 = svc.ElicitationService()
    svc.set_elicitation_service(s2)
    assert svc.get_elicitation_service() is s2
