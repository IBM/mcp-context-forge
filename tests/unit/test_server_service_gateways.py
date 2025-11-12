import types
from datetime import datetime, timezone
from types import SimpleNamespace

from mcpgateway.services.server_service import ServerService


def test_convert_server_to_read_includes_gateways():
    svc = ServerService()
    now = datetime.now(timezone.utc)

    # Create fake gateway and tool objects
    gw = SimpleNamespace(name="gateway-1")
    tool = SimpleNamespace(name="tool-1", gateway=gw)

    # Minimal server-like object expected by _convert_server_to_read
    server = SimpleNamespace(
        id="s1",
        name="Server 1",
        description="desc",
        icon=None,
        created_at=now,
        updated_at=now,
        is_active=True,
        metrics=[],
        tools=[tool],
        resources=[],
        prompts=[],
        a2a_agents=[],
        tags=[],
    )

    result = svc._convert_server_to_read(server)
    data = result.model_dump(by_alias=True)

    assert "associatedGateways" in data
    assert data["associatedGateways"] == ["gateway-1"]
