# -*- coding: utf-8 -*-
"""Test coverage for metrics API endpoints and service methods.

Tests the include_metrics parameter in service list methods.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from datetime import datetime, timezone
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.db import (
    Prompt,
    PromptMetric,
    Resource,
    ResourceMetric,
    Server,
    ServerMetric,
)
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.server_service import ServerService


@pytest.fixture
def test_server(test_db):
    """Create a test server."""
    server_id = f"test-server-{uuid.uuid4()}"
    server = Server(id=server_id, name="test_server")
    test_db.add(server)
    test_db.commit()
    test_db.refresh(server)
    return server


@pytest.fixture
def test_resource_with_metrics(test_db, test_server):
    """Create a test resource with metrics."""
    resource_id = f"test-resource-{uuid.uuid4()}"
    resource = Resource(id=resource_id, uri="file:///test", name="test_resource")
    test_db.add(resource)

    # Associate with server
    test_server.resources.append(resource)

    # Add a metric
    now = datetime.now(timezone.utc)
    metric = ResourceMetric(resource_id=resource_id, response_time=0.5, is_success=True, timestamp=now)
    test_db.add(metric)
    test_db.commit()
    test_db.refresh(resource)
    return resource


@pytest.fixture
def test_prompt_with_metrics(test_db, test_server):
    """Create a test prompt with metrics."""
    prompt_id = f"test-prompt-{uuid.uuid4()}"
    prompt = Prompt(
        id=prompt_id,
        original_name="test_prompt",
        custom_name="test_prompt",
        custom_name_slug=f"test-prompt-{uuid.uuid4()}",
        name="test_prompt",
        template="Test prompt template",
        argument_schema={},
    )
    test_db.add(prompt)

    # Associate with server
    test_server.prompts.append(prompt)

    # Add a metric
    now = datetime.now(timezone.utc)
    metric = PromptMetric(prompt_id=prompt_id, response_time=0.5, is_success=True, timestamp=now)
    test_db.add(metric)
    test_db.commit()
    test_db.refresh(prompt)
    return prompt


@pytest.fixture
def test_server_with_metrics(test_db):
    """Create a test server with metrics."""
    server_id = f"test-server-{uuid.uuid4()}"
    server = Server(id=server_id, name="test_server")
    test_db.add(server)

    # Add a metric
    now = datetime.now(timezone.utc)
    metric = ServerMetric(server_id=server_id, response_time=0.5, is_success=True, timestamp=now)
    test_db.add(metric)
    test_db.commit()
    test_db.refresh(server)
    return server


@pytest.mark.asyncio
async def test_list_server_resources_with_metrics(test_db, test_server, test_resource_with_metrics):
    """Test list_server_resources with include_metrics=True."""
    resource_svc = ResourceService()
    resources = await resource_svc.list_server_resources(
        test_db,
        server_id=test_server.id,
        include_inactive=False,
        include_metrics=True,
        user_email=None,
        token_teams=None,
    )

    assert len(resources) == 1
    resource_dict = resources[0].model_dump()
    assert "metrics" in resource_dict
    assert resource_dict["metrics"]["total_executions"] == 1


@pytest.mark.asyncio
async def test_list_server_prompts_with_metrics(test_db, test_server, test_prompt_with_metrics):
    """Test list_server_prompts with include_metrics=True."""
    prompt_svc = PromptService()
    prompts = await prompt_svc.list_server_prompts(
        test_db,
        server_id=test_server.id,
        include_inactive=False,
        include_metrics=True,
        user_email=None,
        token_teams=None,
    )

    assert len(prompts) == 1
    prompt_dict = prompts[0].model_dump()
    assert "metrics" in prompt_dict
    assert prompt_dict["metrics"]["total_executions"] == 1


@pytest.mark.asyncio
async def test_list_servers_with_metrics(test_db, test_server_with_metrics):
    """Test list_servers with include_metrics=True."""
    server_svc = ServerService()
    result = await server_svc.list_servers(test_db, include_inactive=False, include_metrics=True, user_email=None, token_teams=None)

    # list_servers returns (list, cursor) tuple
    servers = result[0] if isinstance(result, tuple) else result["data"]

    # Find our test server
    test_servers = [s for s in servers if s.id == test_server_with_metrics.id]
    assert len(test_servers) == 1

    server_dict = test_servers[0].model_dump()
    assert "metrics" in server_dict
    assert server_dict["metrics"]["total_executions"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
