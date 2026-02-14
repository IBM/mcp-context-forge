# -*- coding: utf-8 -*-
"""Tests for GrpcService without requiring grpc packages."""

# Standard
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.schemas import GrpcServiceCreate, GrpcServiceUpdate
from mcpgateway.services.grpc_service import GrpcService, GrpcServiceError, GrpcServiceNameConflictError, GrpcServiceNotFoundError


@pytest.fixture
def service():
    return GrpcService()


@pytest.fixture
def db():
    return MagicMock(spec=Session)


def _mock_execute_scalar(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def test_grpc_service_name_conflict_error_message():
    err = GrpcServiceNameConflictError(name="svc", is_active=False, service_id="svc-1")
    assert "inactive" in str(err)
    assert "svc-1" in str(err)


@pytest.mark.asyncio
async def test_register_service_no_conflict(service, db):
    db.execute.return_value = _mock_execute_scalar(None)

    def refresh(obj):
        if not obj.id:
            obj.id = uuid.uuid4().hex
        if not obj.slug:
            obj.slug = obj.name
        if obj.enabled is None:
            obj.enabled = True
        if obj.reachable is None:
            obj.reachable = False
        if obj.service_count is None:
            obj.service_count = 0
        if obj.method_count is None:
            obj.method_count = 0
        if obj.discovered_services is None:
            obj.discovered_services = {}
        if obj.visibility is None:
            obj.visibility = "public"

    db.refresh = MagicMock(side_effect=refresh)

    service_data = GrpcServiceCreate(
        name="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
    )

    result = await service.register_service(db, service_data, user_email="user@example.com")

    assert result.name == "svc"
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_register_service_sets_metadata_and_handles_reflection_error(service, db):
    db.execute.return_value = _mock_execute_scalar(None)

    def refresh(obj):
        if not obj.id:
            obj.id = uuid.uuid4().hex
        if not obj.slug:
            obj.slug = obj.name
        if obj.enabled is None:
            obj.enabled = True
        if obj.reachable is None:
            obj.reachable = False
        if obj.service_count is None:
            obj.service_count = 0
        if obj.method_count is None:
            obj.method_count = 0
        if obj.discovered_services is None:
            obj.discovered_services = {}
        if obj.visibility is None:
            obj.visibility = "public"

    db.refresh = MagicMock(side_effect=refresh)

    service_data = GrpcServiceCreate(
        name="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=True,
        tls_enabled=False,
    )

    with patch.object(service, "_perform_reflection", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        result = await service.register_service(
            db,
            service_data,
            user_email="user@example.com",
            metadata={"created_from_ip": "127.0.0.1", "created_via": "tests", "created_user_agent": "pytest"},
        )

    assert result.name == "svc"
    db_service = db.add.call_args[0][0]
    assert db_service.created_by == "user@example.com"
    assert db_service.created_from_ip == "127.0.0.1"
    assert db_service.created_via == "tests"
    assert db_service.created_user_agent == "pytest"


@pytest.mark.asyncio
async def test_register_service_conflict(service, db):
    db.execute.return_value = _mock_execute_scalar(MagicMock(id="s1", enabled=True))
    service_data = GrpcServiceCreate(name="svc", target="localhost:50051", description="desc")

    with pytest.raises(GrpcServiceNameConflictError):
        await service.register_service(db, service_data)


@pytest.mark.asyncio
async def test_update_service_not_found(service, db):
    db.execute.return_value = _mock_execute_scalar(None)

    with pytest.raises(GrpcServiceNotFoundError):
        await service.update_service(db, "missing", GrpcServiceUpdate(description="x"))


@pytest.mark.asyncio
async def test_update_service_success(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.side_effect = [_mock_execute_scalar(db_service), _mock_execute_scalar(None)]
    db.commit = MagicMock()
    db.refresh = MagicMock()

    result = await service.update_service(db, "svc-1", GrpcServiceUpdate(description="updated"))
    assert result.description == "updated"
    assert db.commit.called


@pytest.mark.asyncio
async def test_update_service_sets_metadata(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.side_effect = [_mock_execute_scalar(db_service), _mock_execute_scalar(None)]
    db.commit = MagicMock()
    db.refresh = MagicMock()

    result = await service.update_service(
        db,
        "svc-1",
        GrpcServiceUpdate(description="updated"),
        user_email="user@example.com",
        metadata={"modified_from_ip": "10.0.0.1", "modified_via": "tests", "modified_user_agent": "pytest"},
    )

    assert result.description == "updated"
    assert db_service.modified_by == "user@example.com"
    assert db_service.modified_from_ip == "10.0.0.1"
    assert db_service.modified_via == "tests"
    assert db_service.modified_user_agent == "pytest"
    assert db_service.version == 2


@pytest.mark.asyncio
async def test_set_service_state_and_delete(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)
    db.commit = MagicMock()
    db.refresh = MagicMock()

    result = await service.set_service_state(db, "svc-1", activate=False)
    assert result.enabled is False

    await service.delete_service(db, "svc-1")
    db.delete.assert_called_once()


@pytest.mark.asyncio
async def test_list_services_team_filter(service, db):
    db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]

    with patch("mcpgateway.services.grpc_service.TeamManagementService") as mock_team:
        mock_team.return_value.build_team_filter_clause = AsyncMock(return_value=DbGrpcService.id == "svc-1")
        with patch("mcpgateway.services.grpc_service.GrpcServiceRead.model_validate", side_effect=lambda svc: svc):
            result = await service.list_services(db, include_inactive=False, user_email="user@example.com", team_id="team-1")

    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_services_team_id_only(service, db):
    db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]

    with patch("mcpgateway.services.grpc_service.GrpcServiceRead.model_validate", side_effect=lambda svc: svc):
        result = await service.list_services(db, include_inactive=True, user_email=None, team_id="team-1")

    assert len(result) == 1


@pytest.mark.asyncio
async def test_get_service_with_team_filter(service, db):
    db.execute.return_value.scalar_one_or_none.return_value = MagicMock()

    with patch("mcpgateway.services.grpc_service.TeamManagementService") as mock_team:
        mock_team.return_value.build_team_filter_clause = AsyncMock(return_value=DbGrpcService.id == "svc-1")
        with patch("mcpgateway.services.grpc_service.GrpcServiceRead.model_validate", side_effect=lambda svc: svc):
            result = await service.get_service(db, "svc-1", user_email="user@example.com")

    assert result is not None


@pytest.mark.asyncio
async def test_delete_service_not_found(service, db):
    db.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(GrpcServiceNotFoundError):
        await service.delete_service(db, "missing")


@pytest.mark.asyncio
async def test_reflect_service_not_found(service, db):
    db.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(GrpcServiceNotFoundError):
        await service.reflect_service(db, "missing")


@pytest.mark.asyncio
async def test_get_service_methods_not_found(service, db):
    db.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(GrpcServiceNotFoundError):
        await service.get_service_methods(db, "missing")


@pytest.mark.asyncio
async def test_reflect_service_success(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=1,
        method_count=2,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)

    service._perform_reflection = AsyncMock()
    result = await service.reflect_service(db, "svc-1")
    assert result.id == "svc-1"


@pytest.mark.asyncio
async def test_reflect_service_error(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=True,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)
    db.commit = MagicMock()
    service._perform_reflection = AsyncMock(side_effect=Exception("boom"))

    with pytest.raises(GrpcServiceError):
        await service.reflect_service(db, "svc-1")
    assert db_service.reachable is False


@pytest.mark.asyncio
async def test_get_service_methods(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=True,
        service_count=0,
        method_count=0,
        discovered_services={"pkg.Service": {"methods": [{"name": "Ping", "input_type": "PingReq", "output_type": "PingResp", "client_streaming": False, "server_streaming": False}]}},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)

    methods = await service.get_service_methods(db, "svc-1")
    assert methods[0]["full_name"] == "pkg.Service.Ping"


@pytest.mark.asyncio
async def test_invoke_method_invalid_name(service, db):
    db.execute.return_value = _mock_execute_scalar(
        DbGrpcService(
            id="svc-1",
            name="svc",
            slug="svc",
            target="localhost:50051",
            description="desc",
            reflection_enabled=False,
            tls_enabled=False,
            grpc_metadata={},
            enabled=True,
            reachable=True,
            service_count=0,
            method_count=0,
            discovered_services={},
            last_reflection=None,
            tags=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version=1,
            visibility="public",
        )
    )

    with pytest.raises(GrpcServiceError):
        await service.invoke_method(db, "svc-1", "InvalidMethod", {})


@pytest.mark.asyncio
async def test_invoke_method_disabled_service(service, db):
    db.execute.return_value = _mock_execute_scalar(
        DbGrpcService(
            id="svc-1",
            name="svc",
            slug="svc",
            target="localhost:50051",
            description="desc",
            reflection_enabled=False,
            tls_enabled=False,
            grpc_metadata={},
            enabled=False,
            reachable=True,
            service_count=0,
            method_count=0,
            discovered_services={},
            last_reflection=None,
            tags=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version=1,
            visibility="public",
        )
    )

    with pytest.raises(GrpcServiceError):
        await service.invoke_method(db, "svc-1", "pkg.Service.Ping", {})


@pytest.mark.asyncio
async def test_invoke_method_service_not_found(service, db):
    db.execute.return_value = _mock_execute_scalar(None)

    with pytest.raises(GrpcServiceNotFoundError):
        await service.invoke_method(db, "missing", "pkg.Service.Ping", {})


@pytest.mark.asyncio
async def test_invoke_method_success(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=True,
        service_count=0,
        method_count=0,
        discovered_services={"pkg.Service": {"methods": []}},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)

    class FakeEndpoint:
        def __init__(self, **_kwargs):
            self._services = None

        async def start(self):
            return None

        async def invoke(self, service_name, method, request_data):
            return {"service": service_name, "method": method, "payload": request_data}

        async def close(self):
            return None

    with patch("mcpgateway.translate_grpc.GrpcEndpoint", FakeEndpoint):
        result = await service.invoke_method(db, "svc-1", "pkg.Service.Ping", {"a": 1})

    assert result["service"] == "pkg.Service"
    assert result["method"] == "Ping"


@pytest.mark.asyncio
async def test_invoke_method_error_path(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=True,
        service_count=0,
        method_count=0,
        discovered_services={"pkg.Service": {"methods": []}},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)

    class FakeEndpoint:
        def __init__(self, **_kwargs):
            self._services = None

        async def start(self):
            return None

        async def invoke(self, _service_name, _method, _request_data):
            raise RuntimeError("boom")

        async def close(self):
            return None

    with patch("mcpgateway.translate_grpc.GrpcEndpoint", FakeEndpoint):
        with pytest.raises(GrpcServiceError):
            await service.invoke_method(db, "svc-1", "pkg.Service.Ping", {"a": 1})


@pytest.mark.asyncio
async def test_perform_reflection_builds_discovery(monkeypatch, service, db):
    from mcpgateway.services import grpc_service as module

    class FakeChannel:
        def close(self):
            return None

    module.grpc = SimpleNamespace(
        insecure_channel=lambda _target: FakeChannel(),
        secure_channel=lambda _target, _creds: FakeChannel(),
        ssl_channel_credentials=lambda **_kwargs: "creds",
    )

    class FakeRequest:
        def __init__(self, list_services=None, file_containing_symbol=None):
            self.list_services = list_services
            self.file_containing_symbol = file_containing_symbol

    class FakeResponse:
        def __init__(self, list_services=None, file_descriptor_bytes=None):
            self._list_services = list_services
            self._file_descriptor_bytes = file_descriptor_bytes
            if list_services is not None:
                self.list_services_response = SimpleNamespace(service=[SimpleNamespace(name=n) for n in list_services])
            if file_descriptor_bytes is not None:
                self.file_descriptor_response = SimpleNamespace(file_descriptor_proto=file_descriptor_bytes)

        def HasField(self, name):
            if name == "list_services_response":
                return self._list_services is not None
            if name == "file_descriptor_response":
                return self._file_descriptor_bytes is not None
            return False

    class FakeStub:
        def __init__(self, _channel):
            return None

        def ServerReflectionInfo(self, request_iter):
            req = next(iter(request_iter))
            if req.list_services is not None:
                return iter([FakeResponse(list_services=["MyService", "BadService", "grpc.reflection.v1alpha.ServerReflection"])])
            if req.file_containing_symbol == "MyService":
                return iter([FakeResponse(file_descriptor_bytes=[b"dummy"])])
            if req.file_containing_symbol == "BadService":
                raise RuntimeError("boom")
            return iter([])

    module.reflection_pb2 = SimpleNamespace(ServerReflectionRequest=FakeRequest)
    module.reflection_pb2_grpc = SimpleNamespace(ServerReflectionStub=FakeStub)

    class FakeMethod:
        name = "Ping"
        input_type = "PingReq"
        output_type = "PingResp"
        client_streaming = False
        server_streaming = True

    class FakeServiceDesc:
        name = "MyService"
        method = [FakeMethod()]

    class FakeFileDescriptorProto:
        def __init__(self):
            self.service = []
            self.package = "pkg"

        def ParseFromString(self, _data):
            self.service = [FakeServiceDesc()]

    fake_descriptor = ModuleType("google.protobuf.descriptor_pb2")
    fake_descriptor.FileDescriptorProto = FakeFileDescriptorProto
    monkeypatch.setitem(sys.modules, "google.protobuf.descriptor_pb2", fake_descriptor)

    db.commit = MagicMock()

    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=True,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )

    await service._perform_reflection(db, db_service)

    assert "pkg.MyService" in db_service.discovered_services
    assert "BadService" in db_service.discovered_services
    assert db_service.service_count == 2
    assert db_service.method_count == 1
    assert db_service.reachable is True


@pytest.mark.asyncio
async def test_perform_reflection_tls_cert_missing(monkeypatch, service, db):
    from mcpgateway.services import grpc_service as module

    module.grpc = SimpleNamespace(ssl_channel_credentials=lambda **_kwargs: "creds", secure_channel=lambda _t, _c: MagicMock())

    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=True,
        tls_enabled=True,
        tls_cert_path="/missing.crt",
        tls_key_path="/missing.key",
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )

    with patch("pathlib.Path.read_bytes", side_effect=FileNotFoundError("missing")):
        with pytest.raises(GrpcServiceError):
            await service._perform_reflection(db, db_service)


@pytest.mark.asyncio
async def test_perform_reflection_tls_default_creds(monkeypatch, service, db):
    from mcpgateway.services import grpc_service as module

    class FakeChannel:
        def close(self):
            return None

    module.grpc = SimpleNamespace(
        insecure_channel=lambda _target: FakeChannel(),
        secure_channel=lambda _target, _creds: FakeChannel(),
        ssl_channel_credentials=lambda **_kwargs: "creds",
    )

    class FakeRequest:
        def __init__(self, list_services=None, file_containing_symbol=None):
            self.list_services = list_services
            self.file_containing_symbol = file_containing_symbol

    class FakeStub:
        def __init__(self, _channel):
            return None

        def ServerReflectionInfo(self, _requests):
            return iter([])

    monkeypatch.setattr(module, "reflection_pb2", SimpleNamespace(ServerReflectionRequest=FakeRequest))
    monkeypatch.setattr(module, "reflection_pb2_grpc", SimpleNamespace(ServerReflectionStub=FakeStub))

    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=True,
        tls_enabled=True,
        tls_cert_path=None,
        tls_key_path=None,
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )

    await service._perform_reflection(db, db_service)
    assert db_service.reachable is True


@pytest.mark.asyncio
async def test_perform_reflection_tls_missing_cert(monkeypatch, service, db):
    from mcpgateway.services import grpc_service as module

    module.grpc = SimpleNamespace(ssl_channel_credentials=lambda **_kwargs: "creds", secure_channel=lambda _t, _c: MagicMock())

    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=True,
        tls_enabled=True,
        tls_cert_path="/missing/cert.pem",
        tls_key_path="/missing/key.pem",
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )

    with patch("mcpgateway.services.grpc_service.Path.read_bytes", side_effect=FileNotFoundError("missing")):
        with pytest.raises(GrpcServiceError):
            await service._perform_reflection(db, db_service)


@pytest.mark.asyncio
async def test_perform_reflection_sets_reachable_false_on_error(monkeypatch, service, db):
    from mcpgateway.services import grpc_service as module

    class FakeChannel:
        def close(self):
            return None

    module.grpc = SimpleNamespace(
        insecure_channel=lambda _target: FakeChannel(),
        secure_channel=lambda _target, _creds: FakeChannel(),
        ssl_channel_credentials=lambda **_kwargs: "creds",
    )

    def _raise_stub(_channel):
        raise RuntimeError("boom")

    module.reflection_pb2_grpc = SimpleNamespace(ServerReflectionStub=_raise_stub)
    module.reflection_pb2 = SimpleNamespace(ServerReflectionRequest=lambda **_kwargs: object())

    db.commit = MagicMock()

    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=True,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=True,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )

    with pytest.raises(RuntimeError):
        await service._perform_reflection(db, db_service)

    assert db_service.reachable is False
    db.commit.assert_called()
