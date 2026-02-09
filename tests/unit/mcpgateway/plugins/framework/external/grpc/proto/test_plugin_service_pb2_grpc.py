# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/grpc/proto/test_plugin_service_pb2_grpc.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for generated gRPC plugin service stubs.
Covers base servicer unimplemented methods, stubs, and experimental API.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

try:
    import grpc
    from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2, plugin_service_pb2_grpc

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

pytestmark = pytest.mark.skipif(not HAS_GRPC, reason="grpc not installed")


class TestPluginServiceServicerBase:
    """Tests for the base PluginServiceServicer (unimplemented stubs)."""

    def test_get_plugin_config_raises_not_implemented(self):
        servicer = plugin_service_pb2_grpc.PluginServiceServicer()
        ctx = MagicMock()
        with pytest.raises(NotImplementedError, match="Method not implemented!"):
            servicer.GetPluginConfig(MagicMock(), ctx)
        ctx.set_code.assert_called_once_with(grpc.StatusCode.UNIMPLEMENTED)
        ctx.set_details.assert_called_once_with("Method not implemented!")

    def test_get_plugin_configs_raises_not_implemented(self):
        servicer = plugin_service_pb2_grpc.PluginServiceServicer()
        ctx = MagicMock()
        with pytest.raises(NotImplementedError, match="Method not implemented!"):
            servicer.GetPluginConfigs(MagicMock(), ctx)
        ctx.set_code.assert_called_once_with(grpc.StatusCode.UNIMPLEMENTED)
        ctx.set_details.assert_called_once_with("Method not implemented!")

    def test_invoke_hook_raises_not_implemented(self):
        servicer = plugin_service_pb2_grpc.PluginServiceServicer()
        ctx = MagicMock()
        with pytest.raises(NotImplementedError, match="Method not implemented!"):
            servicer.InvokeHook(MagicMock(), ctx)
        ctx.set_code.assert_called_once_with(grpc.StatusCode.UNIMPLEMENTED)
        ctx.set_details.assert_called_once_with("Method not implemented!")


class TestHealthServicerBase:
    """Tests for the base HealthServicer (unimplemented stub)."""

    def test_check_raises_not_implemented(self):
        servicer = plugin_service_pb2_grpc.HealthServicer()
        ctx = MagicMock()
        with pytest.raises(NotImplementedError, match="Method not implemented!"):
            servicer.Check(MagicMock(), ctx)
        ctx.set_code.assert_called_once_with(grpc.StatusCode.UNIMPLEMENTED)
        ctx.set_details.assert_called_once_with("Method not implemented!")


class TestHealthStub:
    """Tests for HealthStub initialization."""

    def test_health_stub_init(self):
        channel = MagicMock()
        stub = plugin_service_pb2_grpc.HealthStub(channel)
        assert stub.Check is not None
        channel.unary_unary.assert_called_once_with(
            "/mcpgateway.plugins.Health/Check",
            request_serializer=plugin_service_pb2.HealthCheckRequest.SerializeToString,
            response_deserializer=plugin_service_pb2.HealthCheckResponse.FromString,
            _registered_method=True,
        )


class TestPluginServiceExperimentalAPI:
    """Tests for the experimental PluginService static methods."""

    @patch("grpc.experimental.unary_unary")
    def test_get_plugin_config(self, mock_unary):
        mock_unary.return_value = MagicMock()
        request = MagicMock()
        result = plugin_service_pb2_grpc.PluginService.GetPluginConfig(request, "target:50051")
        mock_unary.assert_called_once()
        args = mock_unary.call_args
        assert args[0][0] is request
        assert args[0][1] == "target:50051"
        assert args[0][2] == "/mcpgateway.plugins.PluginService/GetPluginConfig"
        assert result is mock_unary.return_value

    @patch("grpc.experimental.unary_unary")
    def test_get_plugin_configs(self, mock_unary):
        mock_unary.return_value = MagicMock()
        request = MagicMock()
        result = plugin_service_pb2_grpc.PluginService.GetPluginConfigs(request, "target:50051")
        mock_unary.assert_called_once()
        args = mock_unary.call_args
        assert args[0][2] == "/mcpgateway.plugins.PluginService/GetPluginConfigs"
        assert result is mock_unary.return_value

    @patch("grpc.experimental.unary_unary")
    def test_invoke_hook(self, mock_unary):
        mock_unary.return_value = MagicMock()
        request = MagicMock()
        result = plugin_service_pb2_grpc.PluginService.InvokeHook(request, "target:50051")
        mock_unary.assert_called_once()
        args = mock_unary.call_args
        assert args[0][2] == "/mcpgateway.plugins.PluginService/InvokeHook"
        assert result is mock_unary.return_value


class TestHealthExperimentalAPI:
    """Tests for the experimental Health static method."""

    @patch("grpc.experimental.unary_unary")
    def test_check(self, mock_unary):
        mock_unary.return_value = MagicMock()
        request = MagicMock()
        result = plugin_service_pb2_grpc.Health.Check(request, "target:50051")
        mock_unary.assert_called_once()
        args = mock_unary.call_args
        assert args[0][0] is request
        assert args[0][1] == "target:50051"
        assert args[0][2] == "/mcpgateway.plugins.Health/Check"
        assert result is mock_unary.return_value
