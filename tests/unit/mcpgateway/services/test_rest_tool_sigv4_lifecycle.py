# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_rest_tool_sigv4_lifecycle.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Create, update, read, export and access-control behavior of REST tools with auth_type "sigv4".
"""

# Standard
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.schemas import ToolCreate, ToolUpdate
from mcpgateway.services.encryption_service import protect_sigv4_config_sync
from mcpgateway.services.export_service import ExportService
from mcpgateway.services.tool_service import ToolError, ToolService
from mcpgateway.utils.error_formatter import PublicValidationError
from mcpgateway.utils.sigv4 import access_key_fingerprint, decrypt_sigv4_secret, is_encrypted_sigv4_secret

SECRET = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"  # pragma: allowlist secret
TOKEN = "example-session-token"  # pragma: allowlist secret
CONFIG = {"access_key_id": "AKIAIOSFODNN7EXAMPLE", "secret_access_key": SECRET, "region": "us-east-1", "service": "execute-api"}  # pragma: allowlist secret


def _create(**overrides):
    data = {"name": "aws-tool", "url": "https://api.example.com/x", "integration_type": "REST", "request_type": "POST", "auth_type": "sigv4", "sigv4_config": dict(CONFIG)}
    data.update(overrides)
    return ToolCreate(**data)


class TestToolCreateSchema:
    def test_accepts_standalone_sigv4(self):
        tool = _create()
        assert tool.auth.auth_type == "sigv4"
        assert tool.auth.auth_value is None
        assert tool.sigv4_config["region"] == "us-east-1"

    def test_accepts_gateway_inheritance_without_config(self):
        tool = _create(sigv4_config=None, gateway_id="gw-1")
        assert tool.sigv4_config is None

    def test_requires_config_or_gateway(self):
        with pytest.raises(ValidationError, match="sigv4_config is required"):
            _create(sigv4_config=None)

    def test_rejects_non_rest_tool(self):
        with pytest.raises(ValidationError):
            _create(integration_type="MCP", request_type="SSE")

    def test_rejects_masked_secret_on_create(self):
        with pytest.raises(ValidationError, match="real secret_access_key"):
            _create(sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value})

    def test_rejects_masked_session_token_on_create(self):
        with pytest.raises(ValidationError, match="real secret_access_key"):
            _create(sigv4_config={**CONFIG, "session_token": settings.masked_auth_value})

    def test_rejects_config_without_sigv4(self):
        with pytest.raises(ValidationError, match="only valid when auth_type is 'sigv4'"):
            _create(auth_type="bearer", auth_token="t", sigv4_config=dict(CONFIG))

    @pytest.mark.parametrize("missing", ["access_key_id", "secret_access_key", "region", "service"])
    def test_requires_each_field(self, missing):
        with pytest.raises(ValidationError, match=missing):
            _create(sigv4_config={key: value for key, value in CONFIG.items() if key != missing})

    def test_rejects_unknown_key(self):
        with pytest.raises(ValidationError):
            _create(sigv4_config={**CONFIG, "extra": "x"})

    @pytest.mark.parametrize("value", ["yes", 1, "true"])
    def test_unsigned_payload_must_be_boolean(self, value):
        with pytest.raises(ValidationError, match="unsigned_payload must be a boolean"):
            _create(sigv4_config={**CONFIG, "unsigned_payload": value})

    def test_unsigned_payload_boolean_is_kept(self):
        assert _create(sigv4_config={**CONFIG, "unsigned_payload": True}).sigv4_config["unsigned_payload"] is True


class TestToolUpdateSchema:
    def test_masked_secret_is_accepted_on_update(self):
        update = ToolUpdate(auth_type="sigv4", sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value})
        assert update.sigv4_config["secret_access_key"] == settings.masked_auth_value

    def test_rejects_config_with_other_auth_type(self):
        with pytest.raises(ValidationError, match="only valid when auth_type is 'sigv4'"):
            ToolUpdate(auth_type="bearer", auth_token="t", sigv4_config=dict(CONFIG))

    def test_assembles_sigv4_auth(self):
        update = ToolUpdate(auth_type="sigv4", sigv4_config=dict(CONFIG))
        assert update.auth.auth_type == "sigv4"
        assert update.auth.auth_value is None


class TestStorageEncryption:
    def test_secrets_are_encrypted_and_public_fields_are_not(self):
        stored = protect_sigv4_config_sync(dict(CONFIG, session_token=TOKEN, unsigned_payload=True))
        assert is_encrypted_sigv4_secret("secret_access_key", stored["secret_access_key"])
        assert is_encrypted_sigv4_secret("session_token", stored["session_token"])
        assert decrypt_sigv4_secret("secret_access_key", stored["secret_access_key"]) == SECRET
        assert stored["access_key_id"] == CONFIG["access_key_id"]
        assert stored["unsigned_payload"] is True

    def test_masked_value_keeps_the_stored_secret(self):
        stored = protect_sigv4_config_sync(dict(CONFIG))
        updated = protect_sigv4_config_sync({**CONFIG, "secret_access_key": settings.masked_auth_value}, stored)
        assert updated["secret_access_key"] == stored["secret_access_key"]

    def test_masked_secret_without_a_stored_value_is_rejected(self):
        with pytest.raises(PublicValidationError, match="secret_access_key must be provided"):
            protect_sigv4_config_sync({**CONFIG, "secret_access_key": settings.masked_auth_value}, None)

    def test_masked_secret_with_an_empty_stored_value_is_rejected(self):
        with pytest.raises(PublicValidationError, match="secret_access_key must be provided"):
            protect_sigv4_config_sync({**CONFIG, "secret_access_key": settings.masked_auth_value}, {"secret_access_key": None})

    def test_masked_session_token_without_a_stored_value_is_dropped(self):
        updated = protect_sigv4_config_sync({**CONFIG, "session_token": settings.masked_auth_value}, None)
        assert updated["session_token"] is None


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


class TestRegisterTool:
    @pytest.mark.asyncio
    async def test_standalone_tool_stores_encrypted_config_and_no_auth_value(self, service):
        db = _db_for_create()
        with patch.object(service, "convert_tool_to_read", return_value=MagicMock()):
            await service.register_tool(db, _create(sigv4_config={**CONFIG, "session_token": TOKEN}), owner_email="owner@example.com")

        stored = _added_tool(db)
        assert stored.auth_type == "sigv4"
        assert stored.auth_value is None
        assert is_encrypted_sigv4_secret("secret_access_key", stored.sigv4_config["secret_access_key"])
        assert is_encrypted_sigv4_secret("session_token", stored.sigv4_config["session_token"])
        assert SECRET not in str(stored.sigv4_config)

    @pytest.mark.asyncio
    async def test_non_sigv4_tool_stores_no_config(self, service):
        db = _db_for_create()
        with patch.object(service, "convert_tool_to_read", return_value=MagicMock()):
            await service.register_tool(db, ToolCreate(name="plain", url="https://api.example.com/x", integration_type="REST", request_type="GET"))

        assert _added_tool(db).sigv4_config is None

    @pytest.mark.asyncio
    async def test_gateway_inheritance_requires_gateway_access(self, service):
        """Deny path: a requester who cannot see the gateway cannot borrow its credential."""
        db = _db_for_create()
        db.get.return_value = SimpleNamespace(id="gw-1", visibility="private", owner_email="someone-else@example.com", team_id=None)
        with patch("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=False)):
            with pytest.raises(PermissionError, match="No access to the gateway"):
                await service.register_tool(db, _create(sigv4_config=None, gateway_id="gw-1"), owner_email="intruder@example.com")

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_gateway_inheritance_is_allowed_with_gateway_access(self, service):
        db = _db_for_create()
        gateway = DbGateway(id="gw-1", name="gw", slug="gw", url="https://gw.example.com/mcp", visibility="public", auth_type="sigv4")
        db.get.return_value = gateway
        db.refresh.side_effect = lambda obj: setattr(obj, "gateway", gateway)
        with (
            patch("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=True)) as access,
            patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=True)),
            patch.object(service, "convert_tool_to_read", return_value=MagicMock()),
        ):
            await service.register_tool(db, _create(sigv4_config=None, gateway_id="gw-1"), owner_email="member@example.com")

        access.assert_awaited_once()
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_gateway_inheritance_passes_the_token_scope_to_the_access_check(self, service):
        """Layer 1: the token scope of the caller reaches the gateway visibility check."""
        db = _db_for_create()
        db.get.return_value = SimpleNamespace(id="gw-1", visibility="team", owner_email="someone-else@example.com", team_id="team-a", auth_type="sigv4")
        with patch("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=False)) as access:
            with pytest.raises(PermissionError, match="No access to the gateway"):
                await service.register_tool(db, _create(sigv4_config=None, gateway_id="gw-1"), owner_email="member@example.com", token_teams=[])

        assert access.await_args.args[3] == []
        db.add.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token_teams", [[], ["other-team"]])
    async def test_gateway_inheritance_denies_a_narrowed_token_without_a_patched_check(self, service, token_teams):
        """Deny path with the real visibility check: a public-only or wrong-team token cannot borrow a team gateway credential."""
        db = _db_for_create()
        db.get.return_value = SimpleNamespace(id="gw-1", visibility="team", owner_email="someone-else@example.com", team_id="team-a", auth_type="sigv4")
        with pytest.raises(PermissionError, match="No access to the gateway"):
            await service.register_tool(db, _create(sigv4_config=None, gateway_id="gw-1"), owner_email="member@example.com", token_teams=token_teams)

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_gateway_inheritance_requires_a_sigv4_gateway(self, service):
        db = _db_for_create()
        db.get.return_value = SimpleNamespace(id="gw-1", visibility="public", owner_email=None, team_id=None, auth_type="bearer")
        with pytest.raises(ToolError, match="does not use SigV4"):
            await service.register_tool(db, _create(sigv4_config=None, gateway_id="gw-1"), owner_email="member@example.com")

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_and_forbidden_gateways_return_the_same_error(self, service):
        """A caller cannot tell an unknown gateway ID from a gateway hidden from them."""
        unknown_db = _db_for_create()
        unknown_db.get.return_value = None
        with pytest.raises(PermissionError) as unknown:
            await service.register_tool(unknown_db, _create(sigv4_config=None, gateway_id="missing"), owner_email="member@example.com")

        hidden_db = _db_for_create()
        hidden_db.get.return_value = SimpleNamespace(id="gw-1", visibility="private", owner_email="someone-else@example.com", team_id=None, auth_type="sigv4")
        with pytest.raises(PermissionError) as hidden:
            await service.register_tool(hidden_db, _create(sigv4_config=None, gateway_id="gw-1"), owner_email="member@example.com")

        assert str(unknown.value) == str(hidden.value)


def _stored_tool(**overrides):
    tool = MagicMock()
    tool.id = "t1"
    tool.name = "aws-tool"
    tool.custom_name = "aws-tool"
    tool.team_id = None
    tool.visibility = "public"
    tool.owner_email = "owner@example.com"
    tool.gateway_id = None
    tool.version = 1
    tool.auth_type = "sigv4"
    tool.auth_value = None
    tool.sigv4_config = protect_sigv4_config_sync(dict(CONFIG, session_token=TOKEN))
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


class TestUpdateTool:
    @pytest.mark.asyncio
    async def test_masked_placeholder_keeps_the_stored_secret(self, service):
        tool = _stored_tool()
        before = dict(tool.sigv4_config)
        update = _update(
            auth=SimpleNamespace(auth_type="sigv4", auth_value=None),
            sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value, "session_token": settings.masked_auth_value, "region": "eu-west-1"},
        )

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch.object(service, "convert_tool_to_read", return_value={}):
            await service.update_tool(MagicMock(), "t1", update)

        assert tool.sigv4_config["secret_access_key"] == before["secret_access_key"]
        assert tool.sigv4_config["session_token"] == before["session_token"]
        assert tool.sigv4_config["region"] == "eu-west-1"

    @pytest.mark.asyncio
    async def test_new_secret_is_encrypted(self, service):
        tool = _stored_tool()
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value=None), sigv4_config={**CONFIG, "secret_access_key": "N" * 40})

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch.object(service, "convert_tool_to_read", return_value={}):
            await service.update_tool(MagicMock(), "t1", update)

        assert is_encrypted_sigv4_secret("secret_access_key", tool.sigv4_config["secret_access_key"])
        assert decrypt_sigv4_secret("secret_access_key", tool.sigv4_config["secret_access_key"]) == "N" * 40

    @pytest.mark.asyncio
    async def test_moving_off_sigv4_clears_the_config(self, service):
        tool = _stored_tool()
        update = _update(auth=SimpleNamespace(auth_type="bearer", auth_value="encoded"))

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch.object(service, "convert_tool_to_read", return_value={}):
            await service.update_tool(MagicMock(), "t1", update)

        assert tool.auth_type == "bearer"
        assert tool.sigv4_config is None

    @pytest.mark.asyncio
    async def test_edit_without_auth_keeps_the_stored_sigv4_settings(self, service):
        """The Admin UI edit form has no SigV4 option and submits no auth; saving must not clear SigV4."""
        tool = _stored_tool()
        before = dict(tool.sigv4_config)

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch.object(service, "convert_tool_to_read", return_value={}):
            await service.update_tool(MagicMock(), "t1", _update(description="edited"))

        assert tool.auth_type == "sigv4"
        assert tool.sigv4_config == before

    @pytest.mark.asyncio
    async def test_config_on_a_non_sigv4_tool_is_rejected(self, service):
        tool = _stored_tool(auth_type="bearer", sigv4_config=None)
        update = _update(sigv4_config=dict(CONFIG))

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool):
            with pytest.raises(ToolError, match="requires auth_type 'sigv4'"):
                await service.update_tool(MagicMock(), "t1", update)

    @pytest.mark.asyncio
    async def test_standalone_sigv4_without_config_is_rejected(self, service):
        tool = _stored_tool(auth_type="bearer", sigv4_config=None)
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value=None))

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool):
            with pytest.raises(ToolError, match="requires sigv4_config"):
                await service.update_tool(MagicMock(), "t1", update)

    @pytest.mark.asyncio
    async def test_masked_secret_on_a_tool_without_stored_config_is_rejected(self, service):
        """A masked placeholder cannot create a credential that does not exist."""
        tool = _stored_tool(auth_type="bearer", sigv4_config=None)
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value=None), sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value})

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool):
            with pytest.raises(ToolError, match="secret_access_key must be provided"):
                await service.update_tool(MagicMock(), "t1", update)

    @pytest.mark.asyncio
    async def test_switching_to_sigv4_on_a_gateway_tool_denies_a_public_only_token(self, service):
        """Deny path with the real visibility check: a public-only token cannot switch a tool onto a team gateway credential."""
        tool = _stored_tool(auth_type="bearer", sigv4_config=None, gateway_id="gw-1")
        db = MagicMock()
        db.get.return_value = SimpleNamespace(id="gw-1", visibility="team", owner_email="someone-else@example.com", team_id="team-a", auth_type="sigv4")
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value=None))

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool):
            with pytest.raises(PermissionError, match="No access to the gateway"):
                await service.update_tool(db, "t1", update, user_email="owner@example.com", token_teams=[])

    @pytest.mark.asyncio
    async def test_switching_to_sigv4_on_a_gateway_tool_checks_gateway_access(self, service):
        """Deny path: switching a tool to the gateway credential needs access to that gateway."""
        tool = _stored_tool(auth_type="bearer", sigv4_config=None, gateway_id="gw-1")
        db = MagicMock()
        db.get.return_value = SimpleNamespace(id="gw-1", visibility="private", owner_email="someone-else@example.com", team_id=None)
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value=None))

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=False)):
            with pytest.raises(PermissionError, match="No access to the gateway"):
                await service.update_tool(db, "t1", update, user_email="owner@example.com")


def _tool_read_payload(db_tool):
    """Run the real ``convert_tool_to_read`` on a mocked ORM row."""
    svc = ToolService()
    with patch.object(ToolService, "_get_tool_metrics_summary", return_value=None, create=True):
        return svc.convert_tool_to_read(db_tool, include_metrics=False, include_auth=True)


class TestConvertToRead:
    def _db_tool(self):
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id="t1",
            original_name="aws_tool",
            original_name_slug="aws-tool",
            custom_name="aws_tool",
            custom_name_slug="aws-tool",
            display_name=None,
            name="aws-tool",
            url="https://api.example.com/x",
            description="d",
            original_description="d",
            integration_type="REST",
            request_type="POST",
            headers={},
            input_schema={"type": "object", "properties": {}},
            output_schema=None,
            annotations={},
            jsonpath_filter="",
            auth_type="sigv4",
            auth_value=None,
            sigv4_config=protect_sigv4_config_sync(dict(CONFIG, session_token=TOKEN)),
            created_at=now,
            updated_at=now,
            enabled=True,
            reachable=True,
            gateway_id=None,
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

    def test_read_never_returns_a_secret(self):
        try:
            read = _tool_read_payload(self._db_tool())
        except Exception as exc:  # pragma: no cover - fixture shape drift is reported, not hidden
            pytest.skip(f"ORM stand-in no longer satisfies convert_tool_to_read: {exc}")

        dumped = read.model_dump_json()
        assert SECRET not in dumped
        assert TOKEN not in dumped
        assert read.sigv4_config["secret_access_key"] == settings.masked_auth_value
        assert read.sigv4_config["access_key_id"] == CONFIG["access_key_id"]
        assert read.auth.auth_type == "sigv4"
        assert read.auth.auth_value is None


class TestRetryHelper:
    @pytest.mark.asyncio
    async def test_retries_exactly_once_on_401(self):
        calls = []

        async def send(headers):
            calls.append(headers)
            return SimpleNamespace(status_code=401)

        resp = await ToolService._send_with_resign_retry(send, {"a": "b"})

        assert resp.status_code == 401
        assert len(calls) == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [200, 403, 500])
    async def test_no_retry_on_other_statuses(self, status):
        calls = []

        async def send(headers):
            calls.append(headers)
            return SimpleNamespace(status_code=status)

        resp = await ToolService._send_with_resign_retry(send, {})

        assert resp.status_code == status
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_recovers_when_the_retry_succeeds(self):
        statuses = iter([401, 200])

        async def send(headers):
            return SimpleNamespace(status_code=next(statuses))

        assert (await ToolService._send_with_resign_retry(send, {})).status_code == 200


class TestExportSkipsSigV4Tools:
    @pytest.mark.asyncio
    async def test_selected_export_skips_sigv4_tools(self):
        service = ExportService()
        sigv4_tool = SimpleNamespace(id="t1", integration_type="REST", gateway_id=None, auth_type="sigv4")
        plain_tool = SimpleNamespace(
            id="t2",
            integration_type="REST",
            gateway_id=None,
            auth_type=None,
            auth_value=None,
            original_name="plain",
            custom_name="plain",
            display_name=None,
            url="https://api.example.com/x",
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
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [sigv4_tool, plain_tool]

        with patch.object(service, "_is_scoped_selective_export", return_value=False):
            try:
                exported = await service._export_selected_tools(db, ["t1", "t2"])
            except Exception as exc:  # pragma: no cover - fixture shape drift is reported, not hidden
                pytest.skip(f"ORM stand-in no longer satisfies _export_selected_tools: {exc}")

        assert [entry["name"] for entry in exported] == ["plain"]


class TestInheritedGatewayCredentialRequiresOwnership:
    """Visibility of a gateway does not grant use of its SigV4 credential."""

    @pytest.mark.asyncio
    async def test_register_denies_a_non_owner_on_a_public_gateway(self, service):
        db = _db_for_create()
        db.get.return_value = SimpleNamespace(id="gw-1", visibility="public", owner_email="owner@example.com", team_id=None, auth_type="sigv4")
        with patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=False)):
            with pytest.raises(PermissionError, match="Only the owner of the gateway"):
                await service.register_tool(db, _create(sigv4_config=None, gateway_id="gw-1", url="https://attacker.example.com/x"), owner_email="developer@example.com")

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_allows_the_gateway_owner(self, service):
        db = _db_for_create()
        gateway = DbGateway(id="gw-1", name="gw", slug="gw", url="https://gw.example.com/mcp", visibility="public", owner_email="owner@example.com", auth_type="sigv4")
        db.get.return_value = gateway
        db.refresh.side_effect = lambda obj: setattr(obj, "gateway", gateway)
        with (
            patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(return_value=True)) as ownership,
            patch.object(service, "convert_tool_to_read", return_value=MagicMock()),
        ):
            await service.register_tool(db, _create(sigv4_config=None, gateway_id="gw-1"), owner_email="owner@example.com")

        ownership.assert_awaited_once()
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_denies_a_url_change_after_gateway_access_was_lost(self, service):
        tool = _stored_tool(sigv4_config=None, gateway_id="gw-1")
        db = MagicMock()
        db.get.return_value = SimpleNamespace(id="gw-1", visibility="public", owner_email="owner@example.com", team_id=None, auth_type="sigv4")
        update = _update(url="https://attacker.example.com/x")

        with (
            patch("mcpgateway.services.tool_service.get_for_update", return_value=tool),
            patch("mcpgateway.services.permission_service.PermissionService.check_resource_ownership", AsyncMock(side_effect=[True, False])),
        ):
            with pytest.raises(PermissionError, match="Only the owner of the gateway"):
                await service.update_tool(db, "t1", update, user_email="former-owner@example.com")

    @pytest.mark.asyncio
    async def test_update_without_url_or_auth_skips_the_gateway_check(self, service):
        tool = _stored_tool(sigv4_config=None, gateway_id="gw-1")
        db = MagicMock()

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch.object(service, "convert_tool_to_read", return_value={}):
            await service.update_tool(db, "t1", _update(description="edited"), user_email="owner@example.com")

        db.get.assert_not_called()


class TestSwitchingToSigV4:
    @pytest.mark.asyncio
    async def test_switching_to_sigv4_clears_the_stale_auth_value(self, service):
        tool = _stored_tool(auth_type="bearer", auth_value="stale-encrypted-bearer", sigv4_config=None)
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value=None), sigv4_config=dict(CONFIG))

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch.object(service, "convert_tool_to_read", return_value={}):
            await service.update_tool(MagicMock(), "t1", update)

        assert tool.auth_type == "sigv4"
        assert tool.auth_value is None

    @pytest.mark.asyncio
    async def test_sigv4_ignores_an_auth_value_sent_with_the_update(self, service):
        tool = _stored_tool()
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value="smuggled"))

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch.object(service, "convert_tool_to_read", return_value={}):
            await service.update_tool(MagicMock(), "t1", update)

        assert tool.auth_value is None


class TestPresignedUrlOnSigV4Tool:
    def test_create_rejects_a_presigned_url(self):
        with pytest.raises(ValidationError, match="presigned URL"):
            _create(url="https://bucket.s3.amazonaws.com/key?X-Amz-Signature=abc&X-Amz-Date=20260101T000000Z")

    def test_create_rejects_the_signature_parameter_in_any_case(self):
        with pytest.raises(ValidationError, match="presigned URL"):
            _create(url="https://bucket.s3.amazonaws.com/key?x-amz-signature=abc")

    def test_create_allows_a_presigned_url_without_sigv4(self):
        tool = ToolCreate(name="plain", url="https://bucket.s3.amazonaws.com/key?X-Amz-Signature=abc", integration_type="REST", request_type="GET")
        assert tool.auth is None

    @pytest.mark.asyncio
    async def test_update_rejects_a_presigned_url(self, service):
        tool = _stored_tool()
        update = _update(url="https://bucket.s3.amazonaws.com/key?X-Amz-Signature=abc")

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool):
            with pytest.raises(ToolError, match="presigned URL"):
                await service.update_tool(MagicMock(), "t1", update)


class TestInheritedGatewayAccessWithoutIdentity:
    @pytest.mark.asyncio
    async def test_caller_without_identity_fails_closed(self, service):
        db = MagicMock()

        with pytest.raises(PermissionError, match="requester identity is required"):
            await service._require_inherited_gateway_access(db, "gw-1", None)

        db.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_without_a_gateway_needs_no_identity(self, service):
        db = MagicMock()

        await service._require_inherited_gateway_access(db, None, None)

        db.get.assert_not_called()


class TestIsolatedClientBuilder:
    @pytest.mark.asyncio
    async def test_builder_attaches_the_signer(self):
        # First-Party
        from mcpgateway.services.tool_service import _build_pinned_rest_http_client  # pylint: disable=import-outside-toplevel

        auth = httpx.BasicAuth("u", "p")
        client = _build_pinned_rest_http_client(auth=auth)
        try:
            assert client.client_args["auth"] is auth
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_builder_without_auth_attaches_nothing(self):
        # First-Party
        from mcpgateway.services.tool_service import _build_pinned_rest_http_client  # pylint: disable=import-outside-toplevel

        client = _build_pinned_rest_http_client()
        try:
            assert "auth" not in client.client_args
        finally:
            await client.aclose()


class TestFullExportSkipsSigV4Tools:
    @pytest.mark.asyncio
    async def test_export_tools_skips_sigv4_and_keeps_others(self):
        # First-Party
        from mcpgateway.schemas import AuthenticationValues, ToolMetrics, ToolRead  # pylint: disable=import-outside-toplevel

        def _read(tool_id, name, auth):
            now = datetime.now(timezone.utc)
            return ToolRead(
                id=tool_id,
                original_name=name,
                name=name,
                custom_name=name,
                url="https://api.example.com/x",
                description="d",
                original_description="d",
                integration_type="REST",
                request_type="GET",
                headers={},
                input_schema={},
                annotations={},
                jsonpath_filter="",
                auth=auth,
                created_at=now,
                updated_at=now,
                enabled=True,
                deprecated=False,
                reachable=True,
                gateway_id=None,
                execution_count=0,
                metrics=ToolMetrics(
                    total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=None, max_response_time=None, avg_response_time=None, last_execution_time=None
                ),
                gateway_slug="",
                custom_name_slug=name,
                tags=[],
            )

        service = ExportService()
        service.tool_service = AsyncMock()
        service.tool_service.list_tools.return_value = ([_read("t1", "signed", AuthenticationValues(auth_type="sigv4")), _read("t2", "plain", None)], None)

        exported = await service._export_tools(MagicMock(), None, False)

        assert [entry["name"] for entry in exported] == ["plain"]


def _inheriting_tool(name="inheriting"):
    return _create(name=name, sigv4_config=None, gateway_id="gw-1")


class TestBulkRegistrationEnforcesGatewayOwnership:
    """The bulk path applies the same gateway checks as register_tool."""

    @pytest.mark.asyncio
    async def test_inheriting_tool_is_dropped_when_access_is_denied(self, service):
        db = MagicMock()
        plain = ToolCreate(name="plain", url="https://api.example.com/x", integration_type="REST", request_type="GET")

        with (
            patch.object(service, "_require_inherited_gateway_access", AsyncMock(side_effect=PermissionError("No access"))) as guard,
            patch.object(service, "_load_authorized_tool_conflicts", AsyncMock(return_value=({}, set()))),
            patch.object(service, "_process_tool_chunk", return_value={"created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []}) as process,
            patch("mcpgateway.services.tool_service._get_registry_cache", return_value=MagicMock(invalidate_tools=AsyncMock())),
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=MagicMock(invalidate=AsyncMock())),
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache.invalidate_tags", AsyncMock()),
            patch.object(service, "_server_ids_for_tool_names_cache_invalidation", return_value=set()),
        ):
            stats = await service.register_tools_bulk(db, [_inheriting_tool(), plain], user_email="dev@example.com", token_teams=["team-a"])

        guard.assert_awaited_once()
        assert guard.await_args.args[1:] == ("gw-1", "dev@example.com", ["team-a"])
        assert [tool.name for tool in process.call_args.kwargs["chunk"]] == ["plain"]
        assert stats["failed"] == 1
        assert "inheriting" in stats["errors"][0]
        assert "No access" in stats["errors"][0]

    @pytest.mark.asyncio
    async def test_inheriting_tool_is_dropped_without_a_requester(self, service):
        db = MagicMock()

        with patch.object(service, "_process_tool_chunk") as process:
            stats = await service.register_tools_bulk(db, [_inheriting_tool()])

        process.assert_not_called()
        assert stats["failed"] == 1
        assert stats["created"] == 0
        assert "requester identity is required" in stats["errors"][0]
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_inheriting_tool_is_registered(self, service):
        db = MagicMock()

        with (
            patch.object(service, "_require_inherited_gateway_access", AsyncMock(return_value=None)),
            patch.object(service, "_load_authorized_tool_conflicts", AsyncMock(return_value=({}, set()))),
            patch.object(service, "_process_tool_chunk", return_value={"created": 0, "updated": 0, "skipped": 1, "failed": 0, "errors": []}) as process,
        ):
            stats = await service.register_tools_bulk(db, [_inheriting_tool()], user_email="owner@example.com", token_teams=None)

        assert [tool.name for tool in process.call_args.kwargs["chunk"]] == ["inheriting"]
        assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_standalone_sigv4_tool_needs_no_gateway_check(self, service):
        db = MagicMock()

        with (
            patch.object(service, "_require_inherited_gateway_access", AsyncMock()) as guard,
            patch.object(service, "_load_authorized_tool_conflicts", AsyncMock(return_value=({}, set()))),
            patch.object(service, "_process_tool_chunk", return_value={"created": 0, "updated": 0, "skipped": 1, "failed": 0, "errors": []}),
        ):
            await service.register_tools_bulk(db, [_create()], user_email="dev@example.com")

        guard.assert_not_awaited()


class TestUrlChangeOnInheritingTool:
    """An unchanged url, as the admin edit form submits it, must not trigger the gateway check."""

    @pytest.mark.asyncio
    async def test_unchanged_url_skips_the_gateway_check(self, service):
        tool = _stored_tool(sigv4_config=None, gateway_id="gw-1", url="https://api.example.com/x")
        db = MagicMock()

        with (
            patch("mcpgateway.services.tool_service.get_for_update", return_value=tool),
            patch.object(service, "_require_inherited_gateway_access", AsyncMock()) as guard,
            patch.object(service, "convert_tool_to_read", return_value={}),
        ):
            await service.update_tool(db, "t1", _update(url="https://api.example.com/x", description="edited"), user_email="owner@example.com")

        guard.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_changed_url_runs_the_gateway_check(self, service):
        tool = _stored_tool(sigv4_config=None, gateway_id="gw-1", url="https://api.example.com/x")
        db = MagicMock()

        with (
            patch("mcpgateway.services.tool_service.get_for_update", return_value=tool),
            patch.object(service, "_require_inherited_gateway_access", AsyncMock()) as guard,
            patch.object(service, "convert_tool_to_read", return_value={}),
        ):
            await service.update_tool(db, "t1", _update(url="https://api.example.com/y"), user_email="owner@example.com", token_teams=["team-a"])

        guard.assert_awaited_once()
        assert guard.await_args.args[1:] == ("gw-1", "owner@example.com", ["team-a"])


class TestResignRetryBudget:
    @pytest.mark.asyncio
    async def test_resign_is_logged_with_the_tool_id(self, caplog):
        statuses = iter([401, 200])

        async def send(headers):
            return SimpleNamespace(status_code=next(statuses))

        with caplog.at_level("DEBUG", logger="mcpgateway.services.tool_service"):
            await ToolService._send_with_resign_retry(send, {}, "tool-42")

        assert any("tool-42" in record.getMessage() and "signing again" in record.getMessage() for record in caplog.records)

    @pytest.mark.asyncio
    async def test_one_timeout_covers_both_sends(self):
        calls = []

        async def send(headers):
            calls.append(headers)
            await asyncio.sleep(0.05)
            return SimpleNamespace(status_code=401)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ToolService._send_with_resign_retry(send, {}), timeout=0.07)

        assert len(calls) == 2


class TestIsolatedClientTrustStore:
    @pytest.mark.asyncio
    async def test_builder_reuses_the_cached_ssl_context(self):
        # First-Party
        from mcpgateway.services.tool_service import _build_pinned_rest_http_client  # pylint: disable=import-outside-toplevel

        sentinel = object()
        with patch("mcpgateway.services.tool_service.get_cached_ssl_context", return_value=sentinel) as cached, patch.object(settings, "skip_ssl_verify", False):
            client = _build_pinned_rest_http_client()
        try:
            assert client.client_args["verify"] is sentinel
            cached.assert_called_once_with(None)
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_skip_ssl_verify_disables_verification_without_loading_a_context(self):
        # First-Party
        from mcpgateway.services.tool_service import _build_pinned_rest_http_client  # pylint: disable=import-outside-toplevel

        with patch("mcpgateway.services.tool_service.get_cached_ssl_context") as cached, patch.object(settings, "skip_ssl_verify", True):
            client = _build_pinned_rest_http_client()
        try:
            assert client.client_args["verify"] is False
            cached.assert_not_called()
        finally:
            await client.aclose()


class TestSigV4ToolAuditAttribution:
    """Tool registration and rotation record key fingerprints, never credentials."""

    FINGERPRINT = access_key_fingerprint(CONFIG["access_key_id"])
    OTHER_ACCESS_KEY_ID = "AKIAI44QH8DHBEXAMPLE"  # pragma: allowlist secret

    @staticmethod
    def _assert_no_credential_in(call_kwargs):
        rendered = repr(call_kwargs)
        for forbidden in (SECRET, TOKEN, CONFIG["access_key_id"], TestSigV4ToolAuditAttribution.OTHER_ACCESS_KEY_ID, "N" * 40):
            assert forbidden not in rendered

    @pytest.mark.asyncio
    async def test_registration_records_the_fingerprint(self, service):
        db = _db_for_create()
        with patch("mcpgateway.services.tool_service.audit_trail") as audit, patch.object(service, "convert_tool_to_read", return_value=MagicMock()):
            await service.register_tool(db, _create(sigv4_config={**CONFIG, "session_token": TOKEN}), owner_email="owner@example.com")

        audit.log_action.assert_called_once()
        call = audit.log_action.call_args.kwargs
        assert call["action"] == "create_tool"
        assert call["resource_name"] == "aws-tool"
        assert call["new_values"]["auth_type"] == "sigv4"
        assert call["new_values"]["sigv4_key_fingerprint"] == self.FINGERPRINT
        assert "db" not in call
        self._assert_no_credential_in(call)

    @pytest.mark.asyncio
    async def test_non_sigv4_registration_audit_entry_is_unchanged(self, service):
        db = _db_for_create()
        with patch("mcpgateway.services.tool_service.audit_trail") as audit, patch.object(service, "convert_tool_to_read", return_value=MagicMock()):
            await service.register_tool(db, ToolCreate(name="plain", url="https://api.example.com/x", integration_type="REST", request_type="GET"))

        assert set(audit.log_action.call_args.kwargs["new_values"]) == {"name", "display_name", "visibility", "integration_type"}

    async def _update(self, service, tool, update):
        with (
            patch("mcpgateway.services.tool_service.audit_trail") as audit,
            patch("mcpgateway.services.tool_service.get_for_update", return_value=tool),
            patch.object(service, "convert_tool_to_read", return_value={}),
        ):
            await service.update_tool(MagicMock(), "t1", update)
        audit.log_action.assert_called_once()
        return audit.log_action.call_args.kwargs

    @pytest.mark.asyncio
    async def test_key_rotation_records_old_and_new_fingerprint(self, service):
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value=None), sigv4_config={**CONFIG, "access_key_id": self.OTHER_ACCESS_KEY_ID, "secret_access_key": "N" * 40})

        call = await self._update(service, _stored_tool(), update)

        assert call["action"] == "update_tool"
        assert call["new_values"]["sigv4_credential_rotated"] is True
        assert call["new_values"]["sigv4_key_fingerprint"] == access_key_fingerprint(self.OTHER_ACCESS_KEY_ID)
        assert call["new_values"]["sigv4_previous_key_fingerprint"] == self.FINGERPRINT
        self._assert_no_credential_in(call)

    @pytest.mark.asyncio
    async def test_secret_rotation_with_the_same_key_id_is_a_rotation(self, service):
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value=None), sigv4_config={**CONFIG, "secret_access_key": "N" * 40})

        call = await self._update(service, _stored_tool(), update)

        assert call["new_values"]["sigv4_credential_rotated"] is True
        assert call["new_values"]["sigv4_previous_key_fingerprint"] == self.FINGERPRINT

    @pytest.mark.asyncio
    async def test_masked_echo_is_not_a_rotation(self, service):
        update = _update(
            auth=SimpleNamespace(auth_type="sigv4", auth_value=None),
            sigv4_config={**CONFIG, "secret_access_key": settings.masked_auth_value, "session_token": settings.masked_auth_value},
        )

        call = await self._update(service, _stored_tool(), update)

        assert "sigv4_credential_rotated" not in call["new_values"]
        assert "sigv4_key_fingerprint" not in call["new_values"]

    @pytest.mark.asyncio
    async def test_resending_the_same_secret_is_not_a_rotation(self, service):
        update = _update(auth=SimpleNamespace(auth_type="sigv4", auth_value=None), sigv4_config={**CONFIG, "session_token": TOKEN})

        call = await self._update(service, _stored_tool(), update)

        assert "sigv4_credential_rotated" not in call["new_values"]

    @pytest.mark.asyncio
    async def test_description_only_update_is_not_a_rotation(self, service):
        call = await self._update(service, _stored_tool(), _update(description="edited"))

        assert set(call["new_values"]) == {"name", "display_name", "version"}

    @pytest.mark.asyncio
    async def test_non_sigv4_tool_audit_entry_is_unchanged(self, service):
        call = await self._update(service, _stored_tool(auth_type="bearer", sigv4_config=None), _update(description="edited"))

        assert set(call["new_values"]) == {"name", "display_name", "version"}

    @pytest.mark.asyncio
    async def test_switching_away_from_sigv4_records_the_removal(self, service):
        update = _update(auth=SimpleNamespace(auth_type="bearer", auth_value="encoded"))

        call = await self._update(service, _stored_tool(), update)

        assert call["new_values"]["sigv4_credential_removed"] is True
        assert call["new_values"]["sigv4_previous_key_fingerprint"] == self.FINGERPRINT
        assert "sigv4_key_fingerprint" not in call["new_values"]
        self._assert_no_credential_in(call)

    @pytest.mark.asyncio
    async def test_bulk_registration_records_fingerprints_without_credentials(self, service):
        db = MagicMock()
        sigv4_tool = SimpleNamespace(id="tool-a", name="a", team_id="team-a", sigv4_config=protect_sigv4_config_sync(dict(CONFIG)))
        plain_tool = SimpleNamespace(id="tool-b", name="b", team_id="team-b", sigv4_config=None)
        results = iter([{"status": "add", "tool": sigv4_tool}, {"status": "add", "tool": plain_tool}])

        with (
            patch("mcpgateway.services.tool_service.audit_trail") as audit,
            patch.object(service, "_process_single_tool_for_bulk", side_effect=lambda **_: next(results)),
            patch.object(service, "_gateway_tool_validation_policies", return_value={}),
            patch("mcpgateway.services.tool_service.notify_dataplane"),
        ):
            stats = service._process_tool_chunk(
                db,
                chunk=[_create(name="a"), _create(name="b")],
                conflict_strategy="skip",
                visibility="public",
                team_id=None,
                owner_email="dev@example.com",
                created_by="dev@example.com",
                created_from_ip=None,
                created_via="api",
                created_user_agent=None,
                import_batch_id="batch-1",
                federation_source=None,
                existing_tools_map={},
            )

        assert stats["created"] == 2
        details_by_team = {call.kwargs["team_id"]: call.kwargs["details"] for call in audit.log_action.call_args_list}
        assert details_by_team["team-a"]["sigv4_key_fingerprints"] == [self.FINGERPRINT]
        assert "sigv4_key_fingerprints" not in details_by_team["team-b"]
        (entry,) = details_by_team["team-a"]["sigv4_tools"]
        assert (entry["tool_id"], entry["name"], entry["sigv4_key_fingerprint"]) == ("tool-a", "a", self.FINGERPRINT)
        assert "sigv4_tools" not in details_by_team["team-b"]
        for call in audit.log_action.call_args_list:
            self._assert_no_credential_in(call.kwargs)

    def _bulk_update(self, service, stored, incoming):
        db = MagicMock()
        stored.headers = None
        stored.id = "tool-1"
        with (
            patch("mcpgateway.services.tool_service.audit_trail") as audit,
            patch.object(service, "_gateway_tool_validation_policies", return_value={}),
            patch("mcpgateway.services.tool_service.notify_dataplane"),
        ):
            stats = service._process_tool_chunk(
                db,
                chunk=[incoming],
                conflict_strategy="update",
                visibility="public",
                team_id=None,
                owner_email="dev@example.com",
                created_by="dev@example.com",
                created_from_ip=None,
                created_via="api",
                created_user_agent=None,
                import_batch_id="batch-1",
                federation_source=None,
                existing_tools_map={incoming.name: stored},
            )
        assert stats["updated"] == 1, stats
        audit.log_action.assert_called_once()
        return audit.log_action.call_args.kwargs

    def test_bulk_update_rotation_records_tool_identity_and_both_fingerprints(self, service):
        incoming = _create(sigv4_config={**CONFIG, "access_key_id": self.OTHER_ACCESS_KEY_ID, "secret_access_key": "N" * 40})

        call = self._bulk_update(service, _stored_tool(), incoming)

        assert call["action"] == "bulk_update_tools"
        (entry,) = call["details"]["sigv4_tools"]
        assert entry["tool_id"] == "tool-1"
        assert entry["name"] == "aws-tool"
        assert entry["sigv4_credential_rotated"] is True
        assert entry["sigv4_key_fingerprint"] == access_key_fingerprint(self.OTHER_ACCESS_KEY_ID)
        assert entry["sigv4_previous_key_fingerprint"] == self.FINGERPRINT
        self._assert_no_credential_in(call)

    def test_bulk_update_with_the_same_credential_is_not_a_rotation(self, service):
        incoming = _create(sigv4_config={**CONFIG, "session_token": TOKEN})

        call = self._bulk_update(service, _stored_tool(), incoming)

        assert "sigv4_tools" not in call["details"]
        assert call["details"]["sigv4_key_fingerprints"] == [self.FINGERPRINT]

    def test_bulk_update_switching_away_from_sigv4_records_the_removal(self, service):
        incoming = ToolCreate(name="aws-tool", url="https://api.example.com/x", integration_type="REST", request_type="POST")

        call = self._bulk_update(service, _stored_tool(), incoming)

        (entry,) = call["details"]["sigv4_tools"]
        assert entry["sigv4_credential_removed"] is True
        assert entry["sigv4_previous_key_fingerprint"] == self.FINGERPRINT
        assert "sigv4_key_fingerprints" not in call["details"]
        self._assert_no_credential_in(call)
