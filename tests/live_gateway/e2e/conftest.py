# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/conftest.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared fixtures for the live-gateway end-to-end suite.

Provides the authenticated admin API context, the worker-thread bridge used to
drive the async ``mcp`` SDK client from synchronous Playwright tests, discovery
of the stack's shared ``fast_time`` gateway, and function-scoped factories for
throwaway servers and resources with unconditional cleanup.

The shared gateway is read-only here: this suite never registers, modifies, or
deletes it. Suites that *do* mutate gateway registrations (notably
``tests/live_gateway/mcp/test_mcp_rbac_transport.py``, which deletes by upstream
URL) must not run concurrently with this one.

Requirements:
    - ContextForge running with docker-compose (default: http://localhost:8080)
    - fast_time_server auto-registered as the ``fast_time`` gateway
    - ``mcp`` SDK installed (core dependency)
    - playwright installed: pip install playwright
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from collections.abc import AsyncIterator
import concurrent.futures
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
import logging
import os
import time
from typing import Any, Callable, Generator
import uuid

# Third-Party
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

pytest.importorskip("playwright", reason="playwright is not installed – pip install playwright")
# Third-Party
from playwright.sync_api import APIRequestContext, APIResponse, Playwright

# Local
from tests.helpers.api_helpers import ApiTestHelper
from tests.helpers.auth import make_test_jwt
from ..helpers.mcp_test_helpers import BASE_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
E2E_PREFIX = "e2e-lifecycle"

# Must match the docker-compose gateway JWT_SECRET_KEY.
_JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
_ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
_CLIENT_TIMEOUT = float(os.getenv("MCP_E2E_CLIENT_TIMEOUT", "5.0"))

# The stack auto-registers fast_time_server from docker-compose.yml. Both the
# name and the upstream URL are asserted so a same-named gateway pointing
# somewhere else fails loudly instead of producing confusing catalogs.
SHARED_GATEWAY_NAME = "fast_time"
SHARED_GATEWAY_URL = "http://fast_time_server:9080/mcp"

_GATEWAY_DISCOVERY_DEADLINE = float(os.getenv("MCP_E2E_GATEWAY_DISCOVERY_DEADLINE", "30.0"))
_CATALOG_SYNC_DEADLINE = float(os.getenv("MCP_E2E_CATALOG_SYNC_DEADLINE", "60.0"))
_CONVERGENCE_DEADLINE = float(os.getenv("MCP_E2E_CONVERGENCE_DEADLINE", "30.0"))
_RETRY_DELAY = 1.0

# Guards the cursor-following loops against a server that keeps handing back a
# cursor; far above any realistic page count for a test stack.
_MAX_PAGES = 50

_MISSING_GATEWAY_HINT = (
    f"Shared gateway {SHARED_GATEWAY_NAME!r} ({SHARED_GATEWAY_URL}) is not registered.\n"
    "This suite reads the stack's auto-registered gateway and never creates one.\n"
    "A gateway-mutating suite (e.g. tests/live_gateway/mcp/test_mcp_rbac_transport.py,\n"
    "which deletes registrations by upstream URL) may have removed it. Restore the\n"
    "stack's auto-registration before rerunning — verify the registration is actually\n"
    "back via GET /gateways rather than assuming a restart re-created it."
)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
def json_or_fail(resp: APIResponse, what: str) -> Any:
    """Parse a JSON body, failing with the status and body when it is not JSON.

    An unexpected 4xx/5xx otherwise surfaces only as a JSON-decoding error,
    which hides the status and message that explain the failure.

    Args:
        resp: Playwright API response to decode.
        what: Short description of the call, used in the failure message.

    Returns:
        The decoded JSON body.

    Raises:
        AssertionError: If the body cannot be decoded as JSON.
    """
    try:
        return resp.json()
    except Exception as exc:  # pylint: disable=broad-except
        body = resp.text()
        raise AssertionError(f"{what}: response was not JSON (HTTP {resp.status}): {body[:500]}") from exc


def _json_or_none(resp: APIResponse) -> Any:
    """Return the decoded body, or None when the call failed or was not JSON.

    Args:
        resp: Playwright API response to decode.

    Returns:
        The decoded JSON body, or None.
    """
    if resp.status != 200:
        return None
    try:
        return resp.json()
    except Exception:  # pylint: disable=broad-except
        return None


def _poll_until(probe: Callable[[], Any], deadline_seconds: float, delay: float = _RETRY_DELAY) -> Any:
    """Call ``probe`` until it returns a truthy value or the deadline expires.

    Args:
        probe: Zero-argument callable returning the value being waited on.
        deadline_seconds: Maximum wall-clock time to keep polling.
        delay: Sleep between attempts.

    Returns:
        The last value returned by ``probe`` (falsy if the deadline expired).
    """
    deadline = time.monotonic() + deadline_seconds
    while True:
        result = probe()
        if result:
            return result
        if time.monotonic() >= deadline:
            return result
        time.sleep(delay)


def list_all_servers(admin_api: APIRequestContext) -> list[dict[str, Any]]:
    """Return every visible server, following cursor pagination.

    ``GET /servers`` applies a default page size, so an unpaginated read can
    silently omit a freshly created server on a busy stack.

    Args:
        admin_api: Authenticated admin API context.

    Returns:
        All server records visible to the caller.
    """
    servers: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(_MAX_PAGES):
        params: dict[str, Any] = {"include_pagination": "true"}
        if cursor:
            params["cursor"] = cursor
        resp = admin_api.get("/servers", params=params)
        body = json_or_fail(resp, "GET /servers")
        assert resp.status == 200, f"GET /servers returned {resp.status}: {resp.text()[:500]}"
        if isinstance(body, list):  # pagination metadata not honoured — single page
            return body
        servers.extend(body.get("servers") or [])
        cursor = body.get("nextCursor")
        if not cursor:
            break
    return servers


# ---------------------------------------------------------------------------
# Model-visibility precondition
# ---------------------------------------------------------------------------
def model_audience_excludes_model(tool: dict[str, Any]) -> bool:
    """Return whether a REST tool record is explicitly hidden from the model.

    Mirrors the gateway's audience rule against the REST payload rather than
    importing the production helper: the expectation must not depend on this
    process's settings, which are independent of the gateway container's.
    Absent ``ui`` metadata means model-facing.

    Args:
        tool: Tool record as returned by the REST API.

    Returns:
        True when the tool declares an audience that omits ``model``.
    """
    metadata = tool.get("extensionMetadata") or tool.get("extension_metadata") or {}
    ui = metadata.get("ui") if isinstance(metadata, dict) else None
    if not isinstance(ui, dict):
        return False
    audience = ui.get("visibility", ui.get("audience"))
    if audience is None:
        return False
    if isinstance(audience, str):
        audience = [audience]
    return "model" not in audience


# ---------------------------------------------------------------------------
# MCP protocol helpers (mirrors tests/live_gateway/mcp/test_mcp_rbac_transport.py)
# ---------------------------------------------------------------------------
def mcp_client_url(server_url: str = BASE_URL) -> str:
    """Return the Streamable HTTP endpoint URL for a gateway or virtual server.

    Args:
        server_url: Gateway base URL, or ``{BASE_URL}/servers/{id}``.

    Returns:
        The ``/mcp/`` endpoint URL.
    """
    return f"{server_url}/mcp/" if not server_url.endswith(("/mcp", "/mcp/")) else server_url.rstrip("/") + "/"


@asynccontextmanager
async def mcp_session(server_url: str, access_token: str | None = None) -> AsyncIterator[ClientSession]:
    """Open an initialized MCP client session over Streamable HTTP.

    Args:
        server_url: Gateway base URL, or ``{BASE_URL}/servers/{id}``.
        access_token: Bearer token presented to the gateway.

    Yields:
        An initialized MCP client session.
    """
    url = mcp_client_url(server_url)
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
    timeout = timedelta(seconds=_CLIENT_TIMEOUT)
    async with streamablehttp_client(url, headers=headers, timeout=timeout, sse_read_timeout=timeout) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
            await session.initialize()
            yield session


async def _async_tools_list(access_token: str, server_url: str) -> list:
    """List tools over MCP.

    Args:
        access_token: Bearer token presented to the gateway.
        server_url: Gateway base URL, or ``{BASE_URL}/servers/{id}``.

    Returns:
        The tools reported by ``tools/list``.
    """
    async with mcp_session(server_url, access_token) as session:
        return (await session.list_tools()).tools


async def _async_resources_list(access_token: str, server_url: str) -> list:
    """List resources over MCP.

    Args:
        access_token: Bearer token presented to the gateway.
        server_url: Gateway base URL, or ``{BASE_URL}/servers/{id}``.

    Returns:
        The resources reported by ``resources/list``.
    """
    async with mcp_session(server_url, access_token) as session:
        return (await session.list_resources()).resources


# ---------------------------------------------------------------------------
# Authentication / transport fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def admin_token() -> str:
    """Un-narrowed platform-admin JWT (``is_admin=true`` with ``teams: null``).

    Both claims are required for the admin visibility bypass, and the exact-404
    contract in the post-delete test is scoped to this identity: a narrowed or
    non-admin token is rejected by the RBAC check before server existence is
    ever evaluated, yielding 403 instead.

    Returns:
        A signed admin JWT.
    """
    return make_test_jwt(_ADMIN_EMAIL, is_admin=True, teams=None, secret=_JWT_SECRET)


@pytest.fixture(scope="module")
def admin_api(playwright: Playwright, admin_token: str) -> Generator[APIRequestContext, None, None]:
    """Admin-authenticated API context.

    Args:
        playwright: Playwright entrypoint fixture.
        admin_token: Un-narrowed platform-admin JWT.

    Yields:
        An authenticated API request context bound to ``BASE_URL``.
    """
    ctx = ApiTestHelper.new_context(playwright, BASE_URL, admin_token)
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="session")
def run_async() -> Generator[Callable[[Any], Any], None, None]:
    """Bridge async MCP client calls out of the synchronous Playwright tests.

    The executor is owned by this fixture and shut down at session teardown,
    rather than leaking as a module-level global.

    Yields:
        A callable running a coroutine on a worker thread and returning its result.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="e2e-mcp")

    def _run(coro: Any) -> Any:
        return pool.submit(asyncio.run, coro).result()

    yield _run
    pool.shutdown(wait=True)


class _McpProbe:
    """Synchronous facade over the async MCP client for one authenticated identity."""

    def __init__(self, run: Callable[[Any], Any], token: str) -> None:
        """Store the async bridge and bearer token.

        Args:
            run: Callable executing a coroutine on a worker thread.
            token: Bearer token presented to the gateway.
        """
        self._run = run
        self._token = token

    def tools(self, server_url: str) -> list:
        """List tools over MCP.

        Args:
            server_url: Gateway base URL, or ``{BASE_URL}/servers/{id}``.

        Returns:
            The tools reported by ``tools/list``.
        """
        return self._run(_async_tools_list(self._token, server_url))

    def resources(self, server_url: str) -> list:
        """List resources over MCP.

        Args:
            server_url: Gateway base URL, or ``{BASE_URL}/servers/{id}``.

        Returns:
            The resources reported by ``resources/list``.
        """
        return self._run(_async_resources_list(self._token, server_url))

    def tool_names_when_ready(self, server_url: str, expected: set[str]) -> set[str]:
        """Poll ``tools/list`` until it reports exactly ``expected``.

        Retries only while converging on the expected catalog — an arbitrary
        successful response is not accepted as readiness.

        Args:
            server_url: Gateway base URL, or ``{BASE_URL}/servers/{id}``.
            expected: Tool names the virtual server should expose.

        Returns:
            The last observed set of tool names.
        """
        return self._names_when_ready(lambda: {tool.name for tool in self.tools(server_url)}, expected)

    def resource_uris_when_ready(self, server_url: str, expected: set[str]) -> set[str]:
        """Poll ``resources/list`` until it reports exactly ``expected``.

        Args:
            server_url: Gateway base URL, or ``{BASE_URL}/servers/{id}``.
            expected: Resource URIs the virtual server should expose.

        Returns:
            The last observed set of resource URIs.
        """
        return self._names_when_ready(lambda: {str(resource.uri) for resource in self.resources(server_url)}, expected)

    def _names_when_ready(self, probe: Callable[[], set[str]], expected: set[str]) -> set[str]:
        """Poll ``probe`` until it equals ``expected`` or the deadline expires.

        Args:
            probe: Callable returning the currently observed names.
            expected: The names being converged on.

        Returns:
            The last observed names.
        """
        deadline = time.monotonic() + _CONVERGENCE_DEADLINE
        observed: set[str] = set()
        while True:
            try:
                observed = probe()
                if observed == expected:
                    return observed
            except Exception as exc:  # pylint: disable=broad-except
                if time.monotonic() >= deadline:
                    raise
                logger.debug("MCP discovery not ready yet: %s", exc)
            if time.monotonic() >= deadline:
                return observed
            time.sleep(_RETRY_DELAY)


@pytest.fixture(scope="module")
def mcp(run_async: Callable[[Any], Any], admin_token: str) -> _McpProbe:
    """MCP probe bound to the admin identity.

    Args:
        run_async: Worker-thread bridge for coroutines.
        admin_token: Un-narrowed platform-admin JWT.

    Returns:
        A synchronous MCP probe.
    """
    return _McpProbe(run_async, admin_token)


# ---------------------------------------------------------------------------
# Shared (read-only) gateway discovery
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def shared_gateway(admin_api: APIRequestContext) -> dict[str, Any]:
    """Discover the stack's auto-registered ``fast_time`` gateway and its catalog.

    Read-only: the gateway is never registered, modified, or deleted here.
    Missing registration and an empty catalog are reported as distinct failures
    so the cause is obvious from the message alone.

    Args:
        admin_api: Authenticated admin API context.

    Returns:
        Mapping with the gateway ``id``, ``name``, and its enabled ``tools``.
    """

    def _find() -> dict[str, Any] | None:
        gateways = _json_or_none(admin_api.get("/gateways")) or []
        for gateway in gateways:
            if gateway.get("name") == SHARED_GATEWAY_NAME:
                return gateway
        return None

    gateway = _poll_until(_find, _GATEWAY_DISCOVERY_DEADLINE)
    if not gateway:
        pytest.fail(_MISSING_GATEWAY_HINT)

    actual_url = (gateway.get("url") or "").rstrip("/")
    assert actual_url == SHARED_GATEWAY_URL.rstrip("/"), f"Gateway {SHARED_GATEWAY_NAME!r} points at {actual_url!r}, expected {SHARED_GATEWAY_URL!r}. Refusing to run against an unexpected upstream."

    gateway_id = gateway["id"]

    def _tools() -> list[dict[str, Any]]:
        tools = _json_or_none(admin_api.get("/tools")) or []
        return [tool for tool in tools if tool.get("gatewayId") == gateway_id and tool.get("enabled", True)]

    tools = _poll_until(_tools, _CATALOG_SYNC_DEADLINE)
    assert tools, (
        f"Gateway {SHARED_GATEWAY_NAME!r} (id={gateway_id}) is registered but reported no "
        f"enabled tools within {_CATALOG_SYNC_DEADLINE:.0f}s. The registration exists, so this "
        "is a tool-synchronisation problem rather than a missing gateway — check the upstream "
        "fast_time_server and the gateway's last sync status."
    )

    hidden = sorted(tool.get("name", "?") for tool in tools if model_audience_excludes_model(tool))
    assert not hidden, (
        f"Tools {hidden} declare an audience that excludes 'model', so the gateway may omit them "
        "from tools/list while REST still reports them. This suite compares the two sets directly; "
        "narrow the selection before comparing."
    )

    logger.info("Using shared gateway %s (id=%s) with %d tools", SHARED_GATEWAY_NAME, gateway_id, len(tools))
    return {"id": gateway_id, "name": SHARED_GATEWAY_NAME, "tools": tools}


# ---------------------------------------------------------------------------
# Owned-object registry and cleanup
# ---------------------------------------------------------------------------
class _OwnedObjects:
    """Ids created by a single test, tracked for unconditional cleanup.

    Membership is explicit: objects are never selected for deletion by name
    prefix, so a parallel run or an unrelated object is never collateral.
    """

    def __init__(self) -> None:
        """Initialise empty id registries."""
        self.server_ids: list[str] = []
        self.resource_ids: list[str] = []


def _register_id(registry: list[str], resp: APIResponse) -> None:
    """Record a created object's id before any contract assertion runs.

    Best-effort by design: a malformed body must not mask the assertion failure
    the test is about to raise, but a usable id must still reach cleanup.

    Args:
        registry: List collecting ids for later deletion.
        resp: Creation response to read the id from.
    """
    with suppress(Exception):
        body = resp.json()
        if isinstance(body, dict) and body.get("id"):
            registry.append(body["id"])


def _delete_owned(admin_api: APIRequestContext, path: str, object_id: str) -> str | None:
    """Delete one owned object, returning a description of an unexpected outcome.

    Args:
        admin_api: Authenticated admin API context.
        path: Collection path, e.g. ``/servers``.
        object_id: Id of the object to delete.

    Returns:
        None when the object is gone, otherwise a failure description.
    """
    try:
        resp = admin_api.delete(f"{path}/{object_id}")
    except Exception as exc:  # pylint: disable=broad-except
        return f"DELETE {path}/{object_id} raised {type(exc).__name__}: {exc}"
    if resp.status in (200, 204, 404):  # 404 == already deleted by the test itself
        return None
    return f"DELETE {path}/{object_id} returned {resp.status}: {resp.text()[:200]}"


@pytest.fixture
def owned_objects(admin_api: APIRequestContext) -> Generator[_OwnedObjects, None, None]:
    """Track objects created by one test and remove them unconditionally.

    Servers are deleted before resources so no association outlives its parent.
    Every deletion is attempted even after one fails; failures are aggregated so
    teardown reports all of them at once.

    Args:
        admin_api: Authenticated admin API context.

    Yields:
        The registry the factories record ids in.
    """
    owned = _OwnedObjects()
    yield owned

    failures: list[str] = []
    for server_id in owned.server_ids:
        failure = _delete_owned(admin_api, "/servers", server_id)
        if failure:
            failures.append(failure)
    for resource_id in owned.resource_ids:
        failure = _delete_owned(admin_api, "/resources", resource_id)
        if failure:
            failures.append(failure)

    if failures:
        pytest.fail("Cleanup did not remove every owned object:\n  " + "\n  ".join(failures))


# ---------------------------------------------------------------------------
# Ephemeral object factories
# ---------------------------------------------------------------------------
@pytest.fixture
def create_server(admin_api: APIRequestContext, owned_objects: _OwnedObjects) -> Callable[..., APIResponse]:
    """Return a factory creating throwaway virtual servers.

    The raw ``POST /servers`` response is returned rather than a parsed record,
    so the creation-contract test can assert on the status and body directly.

    Args:
        admin_api: Authenticated admin API context.
        owned_objects: Registry receiving the created ids.

    Returns:
        Callable creating a virtual server and returning the raw response.
    """

    def _create(
        *,
        tool_ids: list[str] | None = None,
        resource_ids: list[str] | None = None,
        name: str | None = None,
        visibility: str = "public",
    ) -> APIResponse:
        payload: dict[str, Any] = {
            "server": {
                "name": name or f"{E2E_PREFIX}-srv-{uuid.uuid4().hex[:8]}",
                "description": "Virtual-server lifecycle E2E fixture",
                "associated_tools": list(tool_ids or []),
                "associated_resources": list(resource_ids or []),
            },
            "visibility": visibility,
        }
        resp = admin_api.post("/servers", data=payload)
        _register_id(owned_objects.server_ids, resp)
        return resp

    return _create


@pytest.fixture
def create_resource(admin_api: APIRequestContext, owned_objects: _OwnedObjects) -> Callable[..., APIResponse]:
    """Return a factory creating throwaway resources.

    ``uri_template`` is deliberately never set: ``list_server_resources``
    filters on ``uri_template IS NULL``, so a template resource would be
    omitted from the virtual server's MCP catalog while its REST association
    still looked healthy.

    Args:
        admin_api: Authenticated admin API context.
        owned_objects: Registry receiving the created ids.

    Returns:
        Callable creating a resource and returning the raw response.
    """

    def _create(*, visibility: str = "public") -> APIResponse:
        uid = uuid.uuid4().hex[:8]
        payload: dict[str, Any] = {
            "resource": {
                "uri": f"test://{E2E_PREFIX}/{uid}",
                "name": f"{E2E_PREFIX}-res-{uid}",
                "description": "Virtual-server lifecycle E2E fixture",
                "mimeType": "text/plain",
                "content": f"lifecycle fixture {uid}",
            },
            "visibility": visibility,
        }
        resp = admin_api.post("/resources", data=payload)
        _register_id(owned_objects.resource_ids, resp)
        return resp

    return _create
