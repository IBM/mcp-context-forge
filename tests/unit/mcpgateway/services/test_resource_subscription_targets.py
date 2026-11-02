# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_resource_subscription_targets.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for ResourceService.resolve_subscription_targets (#6644).
"""

# Standard
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.services import resource_service as resource_service_module
from mcpgateway.services.resource_service import MAX_RESOURCE_SUBSCRIPTIONS_PER_LISTEN, ResourceService
from mcpgateway.services.resource_subscription_relay import UpstreamResourceTarget

OWNER = "owner@example.com"
OTHER = "other@example.com"


def _gateway(db, **overrides):
    """Persist an enabled streamable-HTTP gateway and return it."""
    gid = uuid.uuid4().hex
    values = {"id": gid, "name": f"gw-{gid[:6]}", "slug": f"gw-{gid[:6]}", "url": f"https://{gid[:6]}.example.com/mcp", "description": "", "capabilities": {}, "transport": "STREAMABLEHTTP"}
    values.update(overrides)
    gateway = DbGateway(**values)
    db.add(gateway)
    db.flush()
    return gateway


def _resource(db, uri, gateway=None, **overrides):
    """Persist an enabled resource and return it."""
    values = {"uri": uri, "name": uri, "gateway_id": gateway.id if gateway else None, "visibility": "public", "owner_email": OWNER, "team_id": None}
    values.update(overrides)
    resource = DbResource(**values)
    db.add(resource)
    db.flush()
    return resource


@pytest.fixture
def db(test_db):
    """Yield a real session and roll back everything the test wrote."""
    yield test_db
    test_db.rollback()


@pytest.fixture(autouse=True)
def no_admin(monkeypatch):
    """Treat every caller as a non-admin."""
    monkeypatch.setattr(resource_service_module, "is_user_admin", lambda *_a, **_k: False)


async def _resolve(db, uris, *, server_id=None, user_email=OWNER, token_teams=("t1",)):
    """Call the resolver with list-typed token teams."""
    teams = list(token_teams) if token_teams is not None else None
    return await ResourceService().resolve_subscription_targets(db, uris, server_id=server_id, user_email=user_email, token_teams=teams)


async def test_visible_gateway_resource_is_honored(db):
    """A public resource on a streamable-HTTP gateway resolves to one upstream target with gateway auth headers."""
    gateway = _gateway(db, auth_type="bearer", auth_value={"Authorization": "Bearer up-token"})  # pragma: allowlist secret
    _resource(db, "test://visible", gateway)

    targets = await _resolve(db, ["test://visible"])

    assert targets == {"test://visible": [UpstreamResourceTarget(gateway_id=gateway.id, url=gateway.url, uri="test://visible", headers=(("Authorization", "Bearer up-token"),))]}


async def test_other_team_resource_is_dropped(db):
    """A team resource outside the caller's token teams is not honored."""
    _resource(db, "test://team", _gateway(db), visibility="team", team_id="t2", owner_email=OTHER)

    assert await _resolve(db, ["test://team"]) == {}


async def test_public_only_token_sees_only_public(db):
    """A public-only token cannot subscribe to a team resource, even of its own team."""
    gateway = _gateway(db)
    _resource(db, "test://pub", gateway)
    _resource(db, "test://team1", gateway, visibility="team", team_id="t1")

    assert set(await _resolve(db, ["test://pub", "test://team1"], token_teams=())) == {"test://pub"}


async def test_uri_outside_virtual_server_is_dropped(db):
    """On /servers/{id}/mcp only resources attached to that virtual server are honored."""
    gateway = _gateway(db)
    inside = _resource(db, "test://inside", gateway)
    _resource(db, "test://outside", gateway)
    server = DbServer(id=uuid.uuid4().hex, name=f"vs-{uuid.uuid4().hex[:6]}", description="", visibility="public")
    server.resources.append(inside)
    db.add(server)
    db.flush()

    assert set(await _resolve(db, ["test://inside", "test://outside"], server_id=server.id)) == {"test://inside"}


@pytest.mark.parametrize(
    "gateway_overrides, resource_overrides",
    [
        ({"transport": "SSE"}, {}),
        ({"auth_type": "oauth"}, {}),
        ({"enabled": False}, {}),
        ({}, {"enabled": False}),
        ({"auth_type": "query_param"}, {}),
        ({"ca_certificate": "-----BEGIN CERTIFICATE-----"}, {}),
        ({"client_cert": "-----BEGIN CERTIFICATE-----"}, {}),
    ],
    ids=["sse-gateway", "oauth-gateway", "disabled-gateway", "disabled-resource", "query-param-auth", "private-ca", "mtls"],
)
async def test_unwatchable_resources_are_dropped(db, gateway_overrides, resource_overrides):
    """Upstreams a standing stream cannot reach with stored headers alone, disabled gateways, and disabled resources are not honored."""
    _resource(db, "test://skip", _gateway(db, **gateway_overrides), **resource_overrides)

    assert await _resolve(db, ["test://skip"]) == {}


async def test_local_and_unknown_uris_are_dropped(db):
    """A resource with no upstream gateway and an unknown URI are not honored."""
    _resource(db, "test://local")

    assert await _resolve(db, ["test://local", "test://missing"]) == {}


async def test_duplicates_collapse_and_cap_applies(db):
    """Repeated URIs count once and at most MAX_RESOURCE_SUBSCRIPTIONS_PER_LISTEN URIs are honored."""
    gateway = _gateway(db)
    uris = [f"test://r{i}" for i in range(MAX_RESOURCE_SUBSCRIPTIONS_PER_LISTEN + 3)]
    for uri in uris:
        _resource(db, uri, gateway)

    targets = await _resolve(db, ["test://r0", "test://r0", *uris])

    assert len(targets) == MAX_RESOURCE_SUBSCRIPTIONS_PER_LISTEN
    assert "test://r0" in targets


async def test_same_uri_on_two_gateways_yields_two_targets(db):
    """A URI served by two visible upstreams watches both."""
    first, second = _gateway(db), _gateway(db)
    _resource(db, "test://shared", first)
    _resource(db, "test://shared", second)

    targets = await _resolve(db, ["test://shared"])

    assert {target.gateway_id for target in targets["test://shared"]} == {first.id, second.id}
