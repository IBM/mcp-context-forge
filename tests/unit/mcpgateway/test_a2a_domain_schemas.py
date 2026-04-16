# -*- coding: utf-8 -*-
"""Tests for A2A v1 domain schemas."""

# Standard
from datetime import datetime, timezone

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import (
    A2ATaskCreate,
    A2ATaskRead,
    A2ATaskUpdate,
    ServerInterfaceCreate,
    ServerInterfaceRead,
)


class TestA2ATaskCreate:
    def test_minimal_fields(self):
        task = A2ATaskCreate(a2a_agent_id="agent-1", task_id="task-1")
        assert task.state == "submitted"
        assert task.context_id is None
        assert task.payload is None

    def test_all_fields(self):
        task = A2ATaskCreate(
            a2a_agent_id="agent-1",
            task_id="task-1",
            context_id="ctx-1",
            state="working",
            payload={"key": "value"},
            latest_message={"role": "agent", "parts": [{"text": "hi"}]},
            last_error=None,
        )
        assert task.state == "working"
        assert task.payload == {"key": "value"}

    def test_missing_required_field_raises(self):
        with pytest.raises(Exception):
            A2ATaskCreate(task_id="task-1")  # missing a2a_agent_id


class TestA2ATaskRead:
    def test_from_dict(self):
        now = datetime.now(timezone.utc)
        task = A2ATaskRead(
            id="id-1",
            a2a_agent_id="agent-1",
            task_id="task-1",
            state="completed",
            created_at=now,
            updated_at=now,
        )
        assert task.id == "id-1"
        assert task.completed_at is None

    def test_serialization_round_trip(self):
        now = datetime.now(timezone.utc)
        task = A2ATaskRead(
            id="id-1",
            a2a_agent_id="agent-1",
            task_id="task-1",
            state="completed",
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
        data = task.model_dump()
        assert data["state"] == "completed"
        assert data["completed_at"] is not None


class TestA2ATaskUpdate:
    def test_all_optional(self):
        update = A2ATaskUpdate()
        assert update.state is None
        assert update.payload is None

    def test_partial_update(self):
        update = A2ATaskUpdate(state="failed", last_error="timeout")
        assert update.state == "failed"
        assert update.last_error == "timeout"


class TestServerInterfaceCreate:
    def test_minimal_fields(self):
        iface = ServerInterfaceCreate(server_id="srv-1", protocol="a2a-jsonrpc", binding="https://example.com/")
        assert iface.enabled is True
        assert iface.config is None

    def test_all_fields(self):
        iface = ServerInterfaceCreate(
            server_id="srv-1",
            protocol="a2a-jsonrpc",
            binding="https://example.com/",
            version="1.0",
            tenant="team-1",
            enabled=False,
            config={"key": "value"},
        )
        assert iface.enabled is False
        assert iface.tenant == "team-1"


class TestServerInterfaceRead:
    def test_from_dict(self):
        now = datetime.now(timezone.utc)
        iface = ServerInterfaceRead(
            id="iface-1",
            server_id="srv-1",
            protocol="a2a-jsonrpc",
            binding="https://example.com/",
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        assert iface.id == "iface-1"
        assert iface.version is None
