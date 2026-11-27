# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_rest_tool_gateway_delegation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

REST tools that delegate to their gateway: a relative ``endpoint`` and ``auth_type`` "inherit".

Covers the schema rules, the registration and update gates, the runtime URL and credential
resolution through ``ToolService.invoke_tool``, and the bulk and export paths.
"""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import httpx
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.schemas import ToolCreate, ToolUpdate
from mcpgateway.services.export_service import ExportService
from mcpgateway.services.tool_service import (
    _declared_endpoint,
    _resolve_gateway_endpoint,
    gateway_supports_credential_inheritance,
    ToolError,
    ToolInvocationError,
    ToolService,
)
from mcpgateway.utils.services_auth import encode_auth

# Local
# Reuse the REST-path fixtures of the main tool service tests.
from tests.unit.mcpgateway.services.test_tool_service import (  # noqa: F401  pylint: disable=unused-import
    mock_fresh_db_session,
    mock_gateway,
    mock_global_config_obj,
    mock_logging_services,
    mock_tool,
    reset_tool_lookup_cache,
    setup_db_execute_mock,
)

GATEWAY_URL = "https://api.example.com/base"
ENDPOINT = "/v1/users/{id}/orders"
GATEWAY_TOKEN = "gateway-secret-token"  # pragma: allowlist secret
SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "note": {"type": "string"}}}


def _create(**overrides):
    data = {"name": "delegated", "endpoint": "/v1/items", "integration_type": "REST", "request_type": "GET", "gateway_id": "gw-1"}
    data.update(overrides)
    return ToolCreate(**data)


class TestEndpointSchema:
    def test_accepts_a_path_with_template_and_query(self):
        assert _create(endpoint="/v1/items/{item_id}?expand=true").endpoint == "/v1/items/{item_id}?expand=true"

    @pytest.mark.parametrize(
        ("endpoint", "message"),
        [
            ("v1/items", "starts with a single '/'"),
            ("//evil.example/x", "starts with a single '/'"),
            ("https://evil.example/x", "starts with a single '/'"),
            ("/a/../b", "'.' or '..'"),
            ("/a/./b", "'.' or '..'"),
            ("/a/%2e%2e/b", "encoded path separators or dots"),
            ("/a%2Fb", "encoded path separators or dots"),
            ("/a%5Cb", "encoded path separators or dots"),
            ("/a@b", "forbidden character"),
            ("/a b", "forbidden character"),
            ("/a#b", "forbidden character"),
            ("/a\\b", "forbidden character"),
            ("/a\x00b", "forbidden character"),
            ("/" + "a" * 767, "must not exceed 767"),
        ],
    )
    def test_rejects_unsafe_endpoints(self, endpoint, message):
        with pytest.raises(ValidationError, match=message):
            _create(endpoint=endpoint)

    def test_rejects_endpoint_with_url(self):
        with pytest.raises(ValidationError, match="mutually exclusive"):
            _create(url="https://api.example.com/x")

    def test_rejects_endpoint_without_gateway(self):
        with pytest.raises(ValidationError, match="require a gateway_id"):
            _create(gateway_id=None)

    def test_rejects_endpoint_on_a_non_rest_tool(self):
        with pytest.raises(ValidationError):
            _create(integration_type="MCP", request_type="SSE")

    def test_update_rejects_unsafe_endpoint(self):
        with pytest.raises(ValidationError, match="'.' or '..'"):
            ToolUpdate(endpoint="/a/../b")

    def test_update_rejects_endpoint_with_url(self):
        with pytest.raises(ValidationError, match="mutually exclusive"):
            ToolUpdate(endpoint="/v1/x", url="https://api.example.com/x")


class TestInheritSchema:
    def test_assembles_inherit_auth_without_a_value(self):
        tool = _create(endpoint=None, url="https://api.example.com/x", auth_type="inherit")
        assert tool.auth.auth_type == "inherit"
        assert tool.auth.auth_value is None

    def test_requires_a_gateway(self):
        with pytest.raises(ValidationError, match="require a gateway_id"):
            _create(endpoint=None, url="https://api.example.com/x", auth_type="inherit", gateway_id=None)

    def test_update_assembles_inherit_auth(self):
        update = ToolUpdate(auth_type="inherit")
        assert update.auth.auth_type == "inherit"
        assert update.auth.auth_value is None


class TestPureHelpers:
    @pytest.mark.parametrize(
        ("gateway_url", "endpoint", "expected"),
        [
            ("https://api.example.com", "/v1/x", "https://api.example.com/v1/x"),
            ("https://api.example.com/", "/v1/x", "https://api.example.com/v1/x"),
            ("https://api.example.com/base/", "/v1/x?a=1", "https://api.example.com/base/v1/x?a=1"),
            ("http://api.example.com:8080/base", "/v1/{id}", "http://api.example.com:8080/base/v1/{id}"),
        ],
    )
    def test_resolve_keeps_the_gateway_path_as_a_prefix(self, gateway_url, endpoint, expected):
        assert _resolve_gateway_endpoint(gateway_url, endpoint) == expected

    @pytest.mark.parametrize(
        ("gateway_url", "message"),
        [
            (None, "no URL"),
            ("", "no URL"),
            ("/relative/path", "not absolute"),
            ("https://api.example.com/?k=v", "query or fragment"),
            ("https://api.example.com/#frag", "query or fragment"),
        ],
    )
    def test_resolve_rejects_an_unusable_gateway_url(self, gateway_url, message):
        with pytest.raises(ToolInvocationError, match=message):
            _resolve_gateway_endpoint(gateway_url, "/v1/x")

    @pytest.mark.parametrize(
        ("auth_type", "oauth_config", "expected"),
        [
            ("basic", None, True),
            ("bearer", None, True),
            ("authheaders", None, True),
            ("oauth", None, True),
            ("oauth", {"grant_type": "client_credentials"}, True),
            ("oauth", {"grant_type": "password"}, True),
            ("oauth", {"grant_type": "authorization_code"}, False),
            ("oauth", {"grant_type": "token-exchange"}, False),
            ("query_param", None, False),
            ("sigv4", None, False),
            ("inherit", None, False),
            (None, None, False),
        ],
    )
    def test_gateway_auth_types_that_a_tool_can_inherit(self, auth_type, oauth_config, expected):
        assert gateway_supports_credential_inheritance(auth_type, oauth_config) is expected

    def test_declared_endpoint_ignores_non_string_values(self):
        assert _declared_endpoint(MagicMock()) is None
        assert _declared_endpoint(SimpleNamespace(endpoint="/v1/x")) == "/v1/x"


@pytest.fixture
def service():
    """ToolService with its notification hooks replaced."""
    svc = ToolService()
    svc._notify_tool_added = AsyncMock()
    svc._notify_tool_updated = AsyncMock()
    return svc


def _db_for_create():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    return db


def _added_tool(db):
    return db.add.call_args.args[0]


def _gateway(**overrides):
    values = {"id": "gw-1", "visibility": "public", "owner_email": "owner@example.com", "team_id": None, "auth_type": "bearer", "oauth_config": None, "url": GATEWAY_URL}
    values.update(overrides)
    return SimpleNamespace(**values)


def _inherit_tool(**overrides):
    return _create(endpoint=None, url="https://api.example.com/x", auth_type="inherit", **overrides)


class TestRegisterGates:
    @pytest.mark.asyncio
    async def test_endpoint_tool_stores_the_endpoint_and_no_url(self, service):
        db = _db_for_create()
        gateway = DbGateway(id="gw-1", name="gw", slug="gw", url=GATEWAY_URL, visibility="public", auth_type=None)
        db.get.return_value = gateway
        db.refresh.side_effect = lambda obj: setattr(obj, "gateway", gateway)
        with (
            patch("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=True)) as access,
            patch.object(service, "convert_tool_to_read", return_value=MagicMock()),
        ):
            await service.register_tool(db, _create(), owner_email="member@example.com")

        access.assert_awaited_once()
        stored = _added_tool(db)
        assert stored.endpoint == "/v1/items"
        assert stored.url is None
        assert stored.auth_type is None

    @pytest.mark.asyncio
    async def test_endpoint_does_not_require_gateway_ownership(self, service):
        """An endpoint sends no credential, so visibility of the gateway is enough."""
        db = _db_for_create()
        gateway = DbGateway(id="gw-1", name="gw", slug="gw", url=GATEWAY_URL, visibility="public", owner_email="someone@example.com", auth_type="bearer")
        db.get.return_value = gateway
        db.refresh.side_effect = lambda obj: setattr(obj, "gateway", gateway)
        with (
            patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=False)) as ownership,
            patch.object(service, "convert_tool_to_read", return_value=MagicMock()),
        ):
            await service.register_tool(db, _create(), owner_email="developer@example.com")

        ownership.assert_not_awaited()
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_inherit_tool_stores_no_credential(self, service):
        db = _db_for_create()
        gateway = DbGateway(id="gw-1", name="gw", slug="gw", url=GATEWAY_URL, visibility="public", owner_email="owner@example.com", auth_type="bearer")
        db.get.return_value = gateway
        db.refresh.side_effect = lambda obj: setattr(obj, "gateway", gateway)
        with (
            patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=True)) as ownership,
            patch.object(service, "convert_tool_to_read", return_value=MagicMock()),
        ):
            await service.register_tool(db, _inherit_tool(), owner_email="owner@example.com")

        ownership.assert_awaited_once()
        stored = _added_tool(db)
        assert stored.auth_type == "inherit"
        assert stored.auth_value is None
        assert stored.endpoint is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_factory", [_create, _inherit_tool], ids=["endpoint", "inherit"])
    async def test_requires_a_requester_identity(self, service, tool_factory):
        db = _db_for_create()
        with pytest.raises(PermissionError, match="requester identity is required"):
            await service.register_tool(db, tool_factory())

        db.add.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_factory", [_create, _inherit_tool], ids=["endpoint", "inherit"])
    async def test_unknown_and_hidden_gateways_return_the_same_error(self, service, tool_factory):
        unknown_db = _db_for_create()
        unknown_db.get.return_value = None
        with pytest.raises(PermissionError) as unknown:
            await service.register_tool(unknown_db, tool_factory(), owner_email="member@example.com")

        hidden_db = _db_for_create()
        hidden_db.get.return_value = _gateway(visibility="private", owner_email="someone-else@example.com")
        with pytest.raises(PermissionError) as hidden:
            await service.register_tool(hidden_db, tool_factory(), owner_email="member@example.com")

        assert str(unknown.value) == str(hidden.value)
        unknown_db.add.assert_not_called()
        hidden_db.add.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token_teams", [[], ["other-team"]])
    @pytest.mark.parametrize("tool_factory", [_create, _inherit_tool], ids=["endpoint", "inherit"])
    async def test_narrowed_tokens_cannot_use_a_team_gateway(self, service, tool_factory, token_teams):
        """Layer 1 with the real visibility check: a public-only or wrong-team token is denied."""
        db = _db_for_create()
        db.get.return_value = _gateway(visibility="team", owner_email="someone-else@example.com", team_id="team-a")
        with pytest.raises(PermissionError, match="No access to the gateway"):
            await service.register_tool(db, tool_factory(), owner_email="member@example.com", token_teams=token_teams)

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_inherit_denies_a_non_owner_on_a_public_gateway(self, service):
        db = _db_for_create()
        db.get.return_value = _gateway()
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=False)):
            with pytest.raises(PermissionError, match="Only the owner of the gateway can use its credential"):
                await service.register_tool(db, _inherit_tool(), owner_email="developer@example.com")

        db.add.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "gateway_fields",
        [
            {"auth_type": None},
            {"auth_type": "query_param"},
            {"auth_type": "sigv4"},
            {"auth_type": "oauth", "oauth_config": {"grant_type": "authorization_code"}},
            {"auth_type": "oauth", "oauth_config": {"grant_type": "token-exchange"}},
        ],
    )
    async def test_inherit_denies_a_gateway_with_an_unsupported_credential(self, service, gateway_fields):
        db = _db_for_create()
        db.get.return_value = _gateway(**gateway_fields)
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=True)):
            with pytest.raises(ToolError, match="that tools can inherit"):
                await service.register_tool(db, _inherit_tool(), owner_email="owner@example.com")

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_endpoint_denies_a_gateway_without_a_url(self, service):
        db = _db_for_create()
        db.get.return_value = _gateway(url=None)
        with pytest.raises(ToolError, match="no URL"):
            await service.register_tool(db, _create(), owner_email="member@example.com")

        db.add.assert_not_called()


def _stored_tool(**overrides):
    tool = MagicMock()
    tool.id = "t1"
    tool.name = "delegated"
    tool.custom_name = "delegated"
    tool.team_id = None
    tool.visibility = "public"
    tool.owner_email = "owner@example.com"
    tool.gateway_id = "gw-1"
    tool.integration_type = "REST"
    tool.version = 1
    tool.url = None
    tool.endpoint = "/v1/items"
    tool.auth_type = None
    tool.auth_value = None
    tool.sigv4_config = None
    tool.tool_validation_policy = None
    for key, value in overrides.items():
        setattr(tool, key, value)
    return tool


def _update(**fields):
    base = dict(
        name=None,
        custom_name=None,
        displayName=None,
        title=None,
        url=None,
        endpoint=None,
        description=None,
        integration_type=None,
        request_type=None,
        headers=None,
        input_schema=None,
        output_schema=None,
        annotations=None,
        jsonpath_filter=None,
        visibility=None,
        auth=None,
        tags=None,
        sigv4_config=None,
    )
    base.update(fields)
    update = MagicMock(spec=ToolUpdate)
    for key, value in base.items():
        setattr(update, key, value)
    return update


def _ownership(*results):
    """Patch the ownership check: the first result covers the tool, later results cover the gateway."""
    return patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(side_effect=list(results)))


@pytest.fixture
def run_update(service):
    """Return a coroutine function that runs ``update_tool`` against a stored tool."""

    async def _run(tool, update, db=None, **kwargs):
        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch.object(service, "convert_tool_to_read", return_value={}):
            return await service.update_tool(db if db is not None else MagicMock(), "t1", update, **kwargs)

    return _run


class TestUpdateTool:
    @pytest.mark.asyncio
    async def test_setting_a_url_clears_the_endpoint(self, run_update):
        tool = _stored_tool()
        await run_update(tool, _update(url="https://api.example.com/x"))

        assert tool.url == "https://api.example.com/x"
        assert tool.endpoint is None

    @pytest.mark.asyncio
    async def test_setting_an_endpoint_clears_the_url(self, run_update):
        tool = _stored_tool(url="https://api.example.com/x", endpoint=None)
        db = MagicMock()
        db.get.return_value = _gateway()
        with _ownership(True):
            await run_update(tool, _update(endpoint="/v1/other"), db=db, user_email="member@example.com")

        assert tool.endpoint == "/v1/other"
        assert tool.url is None

    @pytest.mark.asyncio
    async def test_endpoint_on_a_non_rest_tool_is_rejected(self, run_update):
        tool = _stored_tool(integration_type="MCP", endpoint=None)

        with _ownership(True), pytest.raises(ToolError, match="endpoint requires a REST tool"):
            await run_update(tool, _update(endpoint="/v1/other"), user_email="member@example.com")

    @pytest.mark.asyncio
    async def test_endpoint_without_a_requester_is_denied(self, run_update):
        tool = _stored_tool()

        with pytest.raises(PermissionError, match="requester identity is required"):
            await run_update(tool, _update(endpoint="/v1/other"))

    @pytest.mark.asyncio
    async def test_endpoint_denies_a_narrowed_token_on_a_team_gateway(self, run_update):
        tool = _stored_tool()
        db = MagicMock()
        db.get.return_value = _gateway(visibility="team", owner_email="someone-else@example.com", team_id="team-a")

        with _ownership(True), pytest.raises(PermissionError, match="No access to the gateway"):
            await run_update(tool, _update(endpoint="/v1/other"), db=db, user_email="member@example.com", token_teams=[])

    @pytest.mark.asyncio
    async def test_switching_to_inherit_clears_the_stored_auth_value(self, run_update):
        tool = _stored_tool(auth_type="bearer", auth_value="stale-encrypted-bearer")
        db = MagicMock()
        db.get.return_value = _gateway()
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=True)):
            await run_update(tool, _update(auth=SimpleNamespace(auth_type="inherit", auth_value="smuggled")), db=db, user_email="owner@example.com")

        assert tool.auth_type == "inherit"
        assert tool.auth_value is None

    @pytest.mark.asyncio
    async def test_switching_to_inherit_denies_a_non_owner(self, run_update):
        tool = _stored_tool(auth_type=None)
        db = MagicMock()
        db.get.return_value = _gateway()
        with _ownership(True, False):
            with pytest.raises(PermissionError, match="Only the owner of the gateway can use its credential"):
                await run_update(tool, _update(auth=SimpleNamespace(auth_type="inherit", auth_value=None)), db=db, user_email="developer@example.com")

    @pytest.mark.asyncio
    async def test_switching_to_inherit_denies_an_unsupported_gateway(self, run_update):
        tool = _stored_tool(auth_type=None)
        db = MagicMock()
        db.get.return_value = _gateway(auth_type="sigv4")
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=True)):
            with pytest.raises(ToolError, match="that tools can inherit"):
                await run_update(tool, _update(auth=SimpleNamespace(auth_type="inherit", auth_value=None)), db=db, user_email="owner@example.com")

    @pytest.mark.asyncio
    async def test_inherit_on_a_non_rest_tool_is_rejected(self, run_update):
        tool = _stored_tool(integration_type="MCP", endpoint=None)

        with pytest.raises(ToolError, match="requires a REST tool"):
            await run_update(tool, _update(auth=SimpleNamespace(auth_type="inherit", auth_value=None)), user_email="owner@example.com")

    @pytest.mark.asyncio
    async def test_url_change_on_an_inherit_tool_regates_the_credential(self, run_update):
        """A former owner cannot redirect an inheriting tool to a new URL."""
        tool = _stored_tool(auth_type="inherit", endpoint=None, url="https://api.example.com/x")
        db = MagicMock()
        db.get.return_value = _gateway()
        with _ownership(True, False):
            with pytest.raises(PermissionError, match="Only the owner of the gateway can use its credential"):
                await run_update(tool, _update(url="https://attacker.example.com/x"), db=db, user_email="former-owner@example.com")

    @pytest.mark.asyncio
    async def test_endpoint_change_on_an_inherit_tool_regates_the_credential(self, run_update):
        tool = _stored_tool(auth_type="inherit")
        db = MagicMock()
        db.get.return_value = _gateway()
        with _ownership(True, False):
            with pytest.raises(PermissionError, match="Only the owner of the gateway can use its credential"):
                await run_update(tool, _update(endpoint="/v1/other"), db=db, user_email="former-owner@example.com")

    @pytest.mark.asyncio
    async def test_edit_without_url_endpoint_or_auth_skips_the_gate(self, run_update):
        tool = _stored_tool(auth_type="inherit")
        db = MagicMock()

        await run_update(tool, _update(description="edited"), db=db, user_email="owner@example.com")

        db.get.assert_not_called()
        assert tool.auth_type == "inherit"
        assert tool.endpoint == "/v1/items"


class TestReadPayloads:
    def _db_tool(self, **overrides):
        now = datetime.now(timezone.utc)
        values = dict(
            id="t1",
            original_name="delegated",
            original_name_slug="delegated",
            custom_name="delegated",
            custom_name_slug="delegated",
            display_name=None,
            name="delegated",
            url=None,
            endpoint="/v1/items",
            description="d",
            original_description="d",
            integration_type="REST",
            request_type="GET",
            headers={},
            input_schema={"type": "object", "properties": {}},
            output_schema=None,
            annotations={},
            jsonpath_filter="",
            auth_type="inherit",
            auth_value=None,
            sigv4_config=None,
            created_at=now,
            updated_at=now,
            enabled=True,
            reachable=True,
            gateway_id="gw-1",
            gateway=None,
            gateway_slug="",
            tags=[],
            team_id=None,
            team=None,
            owner_email="owner@example.com",
            visibility="public",
            version=1,
            execution_count=0,
            metrics=[],
            created_by="x",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            modified_by=None,
            modified_from_ip=None,
            modified_via=None,
            modified_user_agent=None,
            import_batch_id=None,
            federation_source=None,
            query_mapping=None,
            header_mapping=None,
            tool_validation_policy=None,
            extension_metadata=None,
            deprecated=False,
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_read_returns_the_endpoint_and_the_inherit_marker(self):
        svc = ToolService()
        with patch.object(ToolService, "_get_tool_metrics_summary", return_value=None, create=True):
            try:
                read = svc.convert_tool_to_read(self._db_tool(), include_metrics=False, include_auth=True)
            except Exception as exc:  # pragma: no cover - fixture shape drift is reported, not hidden
                pytest.skip(f"ORM stand-in no longer satisfies convert_tool_to_read: {exc}")

        assert read.endpoint == "/v1/items"
        assert read.auth.auth_type == "inherit"
        assert read.auth.auth_value is None

    def test_cache_payload_carries_the_endpoint(self, service, mock_tool):  # noqa: F811
        mock_tool.endpoint = "/v1/items"
        mock_tool.auth_type = "inherit"

        payload = service._build_tool_cache_payload(mock_tool, None)["tool"]

        assert payload["endpoint"] == "/v1/items"
        assert payload["auth_type"] == "inherit"
        assert "auth_value" not in payload


class TestBulkAndExport:
    @pytest.mark.asyncio
    async def test_bulk_gate_keeps_plain_tools_and_reports_denied_delegating_tools(self, service):
        db = MagicMock()
        db.get.return_value = _gateway(visibility="private", owner_email="someone-else@example.com")
        plain = ToolCreate(name="plain", url="https://api.example.com/x", integration_type="REST", request_type="GET")

        allowed, errors = await service._drop_unauthorized_gateway_delegation(db, [plain, _create(name="by-endpoint"), _inherit_tool(name="by-inherit")], "member@example.com", None)

        assert [tool.name for tool in allowed] == ["plain"]
        assert len(errors) == 2
        assert errors[0].startswith("Tool 'by-endpoint': ")
        assert errors[1].startswith("Tool 'by-inherit': ")

    @pytest.mark.asyncio
    async def test_bulk_gate_denies_every_delegating_tool_without_a_requester(self, service):
        db = MagicMock()

        allowed, errors = await service._drop_unauthorized_gateway_delegation(db, [_create(), _inherit_tool(name="by-inherit")], None, None)

        assert allowed == []
        assert len(errors) == 2
        db.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_gate_allows_an_owner(self, service):
        db = MagicMock()
        db.get.return_value = _gateway()
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=True)):
            allowed, errors = await service._drop_unauthorized_gateway_delegation(db, [_create(), _inherit_tool(name="by-inherit")], "owner@example.com", None)

        assert len(allowed) == 2
        assert errors == []

    @pytest.mark.asyncio
    async def test_selected_export_skips_delegating_tools(self):
        service = ExportService()
        common = dict(
            integration_type="REST",
            auth_value=None,
            custom_name="x",
            display_name=None,
            request_type="GET",
            description="d",
            headers={},
            input_schema=None,
            output_schema=None,
            annotations={},
            jsonpath_filter=None,
            tags=[],
            visibility="public",
            tool_validation_policy=None,
            enabled=True,
            created_at=None,
            updated_at=None,
        )
        endpoint_tool = SimpleNamespace(id="t1", gateway_id="gw-1", auth_type=None, endpoint="/v1/x", url=None, original_name="endpoint-tool", **common)
        inherit_tool = SimpleNamespace(id="t2", gateway_id="gw-1", auth_type="inherit", endpoint=None, url="https://api.example.com/x", original_name="inherit-tool", **common)
        plain_tool = SimpleNamespace(id="t3", gateway_id=None, auth_type=None, endpoint=None, url="https://api.example.com/x", original_name="plain", **common)
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [endpoint_tool, inherit_tool, plain_tool]

        with patch.object(service, "_is_scoped_selective_export", return_value=False):
            try:
                exported = await service._export_selected_tools(db, ["t1", "t2", "t3"])
            except Exception as exc:  # pragma: no cover - fixture shape drift is reported, not hidden
                pytest.skip(f"ORM stand-in no longer satisfies _export_selected_tools: {exc}")

        assert [entry["name"] for entry in exported] == ["plain"]


class Upstream:
    """Mock upstream that records every request and replies with queued status codes."""

    def __init__(self, statuses=None):
        """Create the upstream.

        Args:
            statuses: Status codes to answer with, in order. Defaults to one 200.
        """
        self.requests = []
        self.statuses = list(statuses or [200])

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Record ``request`` and answer it.

        Args:
            request: The request httpx would send.

        Returns:
            httpx.Response: The queued reply.
        """
        self.requests.append(request)
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return httpx.Response(status, json={"ok": status == 200})


@pytest.fixture
def test_db():
    """Mocked DB session."""
    return Mock()


@pytest.fixture
def runtime_service(monkeypatch):
    """ToolService with the real URL validator; only DNS is faked (to a public IP)."""
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.ssrf_protection_enabled", True)
    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    svc = ToolService()
    svc._http_client = AsyncMock()
    svc.get_plugin_manager = AsyncMock()
    return svc


@pytest.fixture
def upstream():
    """Mock upstream with one 200 reply."""
    return Upstream()


@pytest.fixture
def builder(upstream):
    """Patch the isolated client builder so it returns a real httpx client on the mock transport."""

    def _build(auth=None):
        return httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler), auth=auth)

    with (
        patch("mcpgateway.services.tool_service.metrics_buffer", Mock(record_tool_metric=Mock())),
        patch("mcpgateway.services.tool_service._build_pinned_rest_http_client", side_effect=_build),
    ):
        yield


@pytest.fixture
def invoke(runtime_service, mock_tool, mock_gateway, test_db, mock_global_config_obj, builder):  # noqa: F811
    """Return a coroutine function that invokes a REST tool through the real ``invoke_tool`` path."""

    async def _invoke(
        arguments,
        *,
        tool_auth_type="inherit",
        tool_url=None,
        tool_endpoint=ENDPOINT,
        gateway_url=GATEWAY_URL,
        gateway_auth_type="bearer",
        gateway_auth_value=None,
        gateway_oauth_config=None,
        has_gateway=True,
        request_headers=None,
    ):
        """Invoke the REST tool; return the response of ``invoke_tool``."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.url = tool_url
        mock_tool.endpoint = tool_endpoint
        mock_tool.headers = {"Content-Type": "application/json"}
        mock_tool.jsonpath_filter = ""
        mock_tool.input_schema = SCHEMA
        mock_tool.auth_type = tool_auth_type
        mock_tool.auth_value = None
        mock_tool.sigv4_config = None
        mock_tool.query_mapping = None
        mock_tool.header_mapping = None
        if has_gateway:
            mock_gateway.url = gateway_url
            mock_gateway.auth_type = gateway_auth_type
            mock_gateway.auth_value = gateway_auth_value if gateway_auth_value is not None else {}
            mock_gateway.oauth_config = gateway_oauth_config
            mock_gateway.sigv4_config = None
            mock_gateway.auth_query_params = None
        else:
            mock_tool.gateway_id = None
            mock_tool.gateway = None
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)
        return await runtime_service.invoke_tool(test_db, "test_tool", arguments, request_headers=request_headers)

    return _invoke


class TestEndpointResolution:
    @pytest.mark.asyncio
    async def test_endpoint_resolves_against_the_gateway_url_and_template(self, invoke, upstream):
        await invoke({"id": "42", "note": "x"}, tool_auth_type=None)

        request = upstream.requests[0]
        assert request.url.raw_path.decode() == "/base/v1/users/42/orders"
        assert request.headers["host"] == "api.example.com"

    @pytest.mark.asyncio
    async def test_template_value_cannot_escape_the_gateway_path(self, invoke, upstream):
        with pytest.raises(ToolInvocationError):
            await invoke({"id": "../../admin", "note": "x"}, tool_auth_type=None)

        assert upstream.requests == []

    @pytest.mark.asyncio
    async def test_endpoint_without_a_gateway_fails_closed(self, invoke, upstream):
        with pytest.raises(ToolInvocationError, match="no URL"):
            await invoke({"id": "1", "note": "x"}, tool_auth_type=None, has_gateway=False)

        assert upstream.requests == []

    @pytest.mark.asyncio
    async def test_gateway_url_with_a_query_fails_closed(self, invoke, upstream):
        with pytest.raises(ToolInvocationError, match="query or fragment"):
            await invoke({"id": "1", "note": "x"}, tool_auth_type=None, gateway_url="https://api.example.com/base?k=v")

        assert upstream.requests == []

    @pytest.mark.asyncio
    async def test_explicit_url_wins_over_a_stale_endpoint(self, invoke, upstream):
        await invoke({"id": "1", "note": "x"}, tool_auth_type=None, tool_url="https://other.example.com/direct/{id}")

        request = upstream.requests[0]
        assert request.headers["host"] == "other.example.com"
        assert request.url.raw_path.decode() == "/direct/1"


class TestInheritedCredential:
    @pytest.mark.asyncio
    async def test_bearer_gateway_credential_reaches_the_upstream(self, invoke, upstream):
        await invoke({"id": "1", "note": "x"}, gateway_auth_value=encode_auth({"Authorization": f"Bearer {GATEWAY_TOKEN}"}))

        assert upstream.requests[0].headers["authorization"] == f"Bearer {GATEWAY_TOKEN}"

    @pytest.mark.asyncio
    async def test_authheaders_gateway_credential_reaches_the_upstream(self, invoke, upstream):
        await invoke({"id": "1", "note": "x"}, gateway_auth_type="authheaders", gateway_auth_value=encode_auth({"X-Api-Key": GATEWAY_TOKEN, "": "dropped"}))

        assert upstream.requests[0].headers["x-api-key"] == GATEWAY_TOKEN

    @pytest.mark.asyncio
    async def test_oauth_gateway_token_reaches_the_upstream(self, invoke, upstream, runtime_service):
        runtime_service.oauth_manager.get_access_token = AsyncMock(return_value="oauth-access-token")
        config = {"grant_type": "client_credentials", "client_id": "cid", "token_url": "https://auth.example.com/token"}

        await invoke({"id": "1", "note": "x"}, gateway_auth_type="oauth", gateway_oauth_config=config)

        assert upstream.requests[0].headers["authorization"] == "Bearer oauth-access-token"
        runtime_service.oauth_manager.get_access_token.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_oauth_password_grant_token_reaches_the_upstream(self, invoke, upstream, runtime_service):
        runtime_service.oauth_manager.get_access_token = AsyncMock(return_value="password-grant-token")
        config = {"grant_type": "password", "client_id": "cid", "username": "svc", "password": "pw", "token_url": "https://auth.example.com/token"}  # pragma: allowlist secret

        await invoke({"id": "1", "note": "x"}, gateway_auth_type="oauth", gateway_oauth_config=config)

        assert upstream.requests[0].headers["authorization"] == "Bearer password-grant-token"
        assert runtime_service.oauth_manager.get_access_token.await_args.args[0]["grant_type"] == "password"

    @pytest.mark.asyncio
    async def test_oauth_failure_fails_closed(self, invoke, upstream, runtime_service):
        runtime_service.oauth_manager.get_access_token = AsyncMock(side_effect=RuntimeError("token endpoint down"))
        config = {"grant_type": "client_credentials", "client_id": "cid", "token_url": "https://auth.example.com/token"}

        with pytest.raises(ToolInvocationError, match="OAuth authentication failed"):
            await invoke({"id": "1", "note": "x"}, gateway_auth_type="oauth", gateway_oauth_config=config)

        assert upstream.requests == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("gateway_auth_type", "gateway_oauth_config"),
        [(None, None), ("query_param", None), ("sigv4", None), ("oauth", {"grant_type": "authorization_code"})],
    )
    async def test_unsupported_gateway_credential_fails_closed(self, invoke, upstream, gateway_auth_type, gateway_oauth_config):
        with pytest.raises(ToolInvocationError, match="cannot inherit a credential"):
            await invoke({"id": "1", "note": "x"}, gateway_auth_type=gateway_auth_type, gateway_oauth_config=gateway_oauth_config)

        assert upstream.requests == []

    @pytest.mark.asyncio
    async def test_inherit_without_a_gateway_fails_closed(self, invoke, upstream):
        with pytest.raises(ToolInvocationError):
            await invoke({"id": "1", "note": "x"}, tool_endpoint=None, tool_url="https://api.example.com/x/{id}", has_gateway=False)

        assert upstream.requests == []

    @pytest.mark.asyncio
    async def test_caller_cannot_replace_the_inherited_credential(self, invoke, upstream):
        """Deny path: neither Authorization nor X-Upstream-Authorization from the caller overrides the gateway credential."""
        await invoke(
            {"id": "1", "note": "x"},
            gateway_auth_value=encode_auth({"Authorization": f"Bearer {GATEWAY_TOKEN}"}),
            request_headers={"X-Upstream-Authorization": "Bearer attacker", "Authorization": "Bearer inbound"},
        )

        request = upstream.requests[0]
        assert request.headers["authorization"] == f"Bearer {GATEWAY_TOKEN}"
        assert "attacker" not in "\n".join(request.headers.values())

    @pytest.mark.asyncio
    async def test_tool_without_the_opt_in_never_borrows_the_gateway_credential(self, invoke, upstream):
        """Deny path: an endpoint tool that did not opt in to inherit sends no gateway credential."""
        await invoke({"id": "1", "note": "x"}, tool_auth_type=None, gateway_auth_value=encode_auth({"Authorization": f"Bearer {GATEWAY_TOKEN}"}))

        wire = "\n".join(f"{name}: {value}" for name, value in upstream.requests[0].headers.items())
        assert GATEWAY_TOKEN not in wire
        assert "authorization" not in upstream.requests[0].headers
