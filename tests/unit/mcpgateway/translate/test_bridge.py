# -*- coding: utf-8 -*-
"""Unit tests for MCP Gateway Transport-Translation Bridge Core.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

This module tests the core bridge functionality including transport endpoints
and message routing logic.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.translate.bridge import (
    TransportEndpoint,
    StdIOEndpoint,
    SSEEndpoint,
    WSEndpoint,
    StreamableHTTPEndpoint,
    TranslateBridge,
)


class MockTransportEndpoint(TransportEndpoint):
    """Mock transport endpoint for testing."""
    
    def __init__(self):
        self.connected = False
        self.sent_messages = []
        self.received_messages = []
    
    async def connect(self):
        self.connected = True
    
    async def disconnect(self):
        self.connected = False
    
    async def send_message(self, message):
        self.sent_messages.append(message)
    
    async def receive_message(self):
        for message in self.received_messages:
            yield message
    
    async def is_connected(self):
        return self.connected


class TestStdIOEndpoint:
    """Test StdIOEndpoint functionality."""
    
    @patch('mcpgateway.translate.bridge.subprocess.Popen')
    async def test_connect_success(self, mock_popen):
        """Test successful stdio endpoint connection."""
        # Setup mock process
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        
        endpoint = StdIOEndpoint("echo test")
        await endpoint.connect()
        
        assert endpoint._connected
        assert endpoint.process == mock_process
        mock_popen.assert_called_once()
    
    @patch('mcpgateway.translate.bridge.subprocess.Popen')
    async def test_connect_failure(self, mock_popen):
        """Test stdio endpoint connection failure."""
        mock_popen.side_effect = Exception("Command not found")
        
        endpoint = StdIOEndpoint("invalid_command")
        
        with pytest.raises(Exception, match="Command not found"):
            await endpoint.connect()
    
    @patch('mcpgateway.translate.bridge.subprocess.Popen')
    async def test_send_message(self, mock_popen):
        """Test sending message to stdio endpoint."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        
        endpoint = StdIOEndpoint("echo test")
        await endpoint.connect()
        
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        await endpoint.send_message(message)
        
        expected_output = json.dumps(message) + "\n"
        mock_process.stdin.write.assert_called_once_with(expected_output)
        mock_process.stdin.flush.assert_called_once()
    
    async def test_send_message_not_connected(self):
        """Test sending message when not connected."""
        endpoint = StdIOEndpoint("echo test")
        
        with pytest.raises(RuntimeError, match="Stdio endpoint not connected"):
            await endpoint.send_message({"test": "message"})
    
    @patch('mcpgateway.translate.bridge.subprocess.Popen')
    async def test_disconnect(self, mock_popen):
        """Test stdio endpoint disconnection."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        
        endpoint = StdIOEndpoint("echo test")
        await endpoint.connect()
        await endpoint.disconnect()
        
        assert not endpoint._connected
        mock_process.terminate.assert_called_once()


class TestSSEEndpoint:
    """Test SSEEndpoint functionality."""
    
    async def test_connect_with_transport(self):
        """Test SSE endpoint connection with existing transport."""
        mock_transport = AsyncMock()
        endpoint = SSEEndpoint(transport=mock_transport)
        
        await endpoint.connect()
        
        assert endpoint._connected
        mock_transport.connect.assert_called_once()
    
    async def test_connect_with_url(self):
        """Test SSE endpoint connection with URL."""
        endpoint = SSEEndpoint(url="https://example.com/sse")
        
        await endpoint.connect()
        
        assert endpoint._connected
        assert endpoint._client is not None
    
    async def test_connect_no_url_or_transport(self):
        """Test SSE endpoint connection failure with no URL or transport."""
        endpoint = SSEEndpoint()
        
        with pytest.raises(ValueError, match="Either URL or transport must be provided"):
            await endpoint.connect()
    
    async def test_send_message_with_transport(self):
        """Test sending message via transport."""
        mock_transport = AsyncMock()
        endpoint = SSEEndpoint(transport=mock_transport)
        await endpoint.connect()
        
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        await endpoint.send_message(message)
        
        mock_transport.send_message.assert_called_once_with(message)
    
    @patch('mcpgateway.translate.bridge.httpx.AsyncClient')
    async def test_send_message_with_url(self, mock_client_class):
        """Test sending message via HTTP client."""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        
        endpoint = SSEEndpoint(url="https://example.com/sse")
        await endpoint.connect()
        
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        await endpoint.send_message(message)
        
        mock_client.post.assert_called_once()
    
    async def test_send_message_not_connected(self):
        """Test sending message when not connected."""
        endpoint = SSEEndpoint(url="https://example.com/sse")
        
        with pytest.raises(RuntimeError, match="SSE endpoint not connected"):
            await endpoint.send_message({"test": "message"})


class TestWSEndpoint:
    """Test WSEndpoint functionality."""
    
    async def test_connect(self):
        """Test WebSocket endpoint connection."""
        mock_websocket = MagicMock()
        endpoint = WSEndpoint(mock_websocket)
        
        with patch.object(endpoint.transport, 'connect') as mock_connect:
            await endpoint.connect()
            mock_connect.assert_called_once()
    
    async def test_send_message(self):
        """Test sending message via WebSocket."""
        mock_websocket = MagicMock()
        endpoint = WSEndpoint(mock_websocket)
        
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        
        with patch.object(endpoint.transport, 'send_message') as mock_send:
            await endpoint.send_message(message)
            mock_send.assert_called_once_with(message)


class TestStreamableHTTPEndpoint:
    """Test StreamableHTTPEndpoint functionality."""
    
    async def test_connect(self):
        """Test HTTP endpoint connection."""
        endpoint = StreamableHTTPEndpoint("https://example.com/api")
        await endpoint.connect()
        
        assert endpoint._connected
        assert endpoint._client is not None
    
    @patch('mcpgateway.translate.bridge.httpx.AsyncClient')
    async def test_send_message(self, mock_client_class):
        """Test sending message via HTTP."""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client
        
        endpoint = StreamableHTTPEndpoint("https://example.com/api")
        await endpoint.connect()
        
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        await endpoint.send_message(message)
        
        mock_client.post.assert_called_once_with("https://example.com/api", json=message)
    
    async def test_send_message_not_connected(self):
        """Test sending message when not connected."""
        endpoint = StreamableHTTPEndpoint("https://example.com/api")
        
        with pytest.raises(RuntimeError, match="HTTP endpoint not connected"):
            await endpoint.send_message({"test": "message"})
    
    async def test_disconnect(self):
        """Test HTTP endpoint disconnection."""
        endpoint = StreamableHTTPEndpoint("https://example.com/api")
        await endpoint.connect()
        await endpoint.disconnect()
        
        assert not endpoint._connected


class TestTranslateBridge:
    """Test TranslateBridge functionality."""
    
    def test_init(self):
        """Test bridge initialization."""
        config = {
            "stdio_command": "echo test",
            "output_transport": "sse",
            "port": 8000,
            "headers": {},
            "cors_origins": [],
        }
        
        bridge = TranslateBridge(config)
        assert bridge.config == config
        assert bridge.input_endpoint is None
        assert bridge.output_endpoint is None
    
    async def test_create_input_endpoint_stdio(self):
        """Test creating stdio input endpoint."""
        config = {
            "stdio_command": "echo test",
            "sse_url": None,
            "streamable_http_url": None,
            "headers": {},
        }
        
        bridge = TranslateBridge(config)
        
        with patch.object(StdIOEndpoint, 'connect') as mock_connect:
            await bridge._create_input_endpoint()
            
            assert isinstance(bridge.input_endpoint, StdIOEndpoint)
            mock_connect.assert_called_once()
    
    async def test_create_input_endpoint_sse(self):
        """Test creating SSE input endpoint."""
        config = {
            "stdio_command": None,
            "sse_url": "https://example.com/sse",
            "streamable_http_url": None,
            "headers": {"Authorization": "Bearer token"},
        }
        
        bridge = TranslateBridge(config)
        
        with patch.object(SSEEndpoint, 'connect') as mock_connect:
            await bridge._create_input_endpoint()
            
            assert isinstance(bridge.input_endpoint, SSEEndpoint)
            assert bridge.input_endpoint.url == "https://example.com/sse"
            assert bridge.input_endpoint.headers == {"Authorization": "Bearer token"}
            mock_connect.assert_called_once()
    
    async def test_create_input_endpoint_http(self):
        """Test creating HTTP input endpoint."""
        config = {
            "stdio_command": None,
            "sse_url": None,
            "streamable_http_url": "https://example.com/api",
            "headers": {},
        }
        
        bridge = TranslateBridge(config)
        
        with patch.object(StreamableHTTPEndpoint, 'connect') as mock_connect:
            await bridge._create_input_endpoint()
            
            assert isinstance(bridge.input_endpoint, StreamableHTTPEndpoint)
            assert bridge.input_endpoint.url == "https://example.com/api"
            mock_connect.assert_called_once()
    
    async def test_create_input_endpoint_no_transport(self):
        """Test creating input endpoint with no transport specified."""
        config = {
            "stdio_command": None,
            "sse_url": None,
            "streamable_http_url": None,
        }
        
        bridge = TranslateBridge(config)
        
        with pytest.raises(ValueError, match="No input transport specified"):
            await bridge._create_input_endpoint()
    
    async def test_cleanup(self):
        """Test bridge cleanup."""
        config = {"output_transport": "stdio"}
        bridge = TranslateBridge(config)
        
        # Set up mock endpoints
        bridge.input_endpoint = AsyncMock()
        bridge.output_endpoint = AsyncMock()
        
        # Set up mock tasks
        mock_task = AsyncMock()
        bridge._pump_tasks = [mock_task]
        
        await bridge._cleanup()
        
        assert not bridge._running
        mock_task.cancel.assert_called_once()
        bridge.input_endpoint.disconnect.assert_called_once()
        bridge.output_endpoint.disconnect.assert_called_once()


class TestBidirectionalPumping:
    """Test bidirectional message pumping."""
    
    @pytest.mark.asyncio
    async def test_bidirectional_pump_single_message(self):
        """Test bidirectional pumping with a single message."""
        # Create mock endpoints
        input_endpoint = MockTransportEndpoint()
        output_endpoint = MockTransportEndpoint()
        
        # Set up test data
        test_message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        input_endpoint.received_messages = [test_message]
        
        # Create bridge and set endpoints
        bridge = TranslateBridge({})
        bridge.input_endpoint = input_endpoint
        bridge.output_endpoint = output_endpoint
        
        # Run pump for a short time
        pump_task = asyncio.create_task(bridge._run_bidirectional_pump())
        
        # Give it time to process one message
        await asyncio.sleep(0.1)
        pump_task.cancel()
        
        try:
            await pump_task
        except asyncio.CancelledError:
            pass
        
        # Check that message was forwarded
        assert len(output_endpoint.sent_messages) >= 1
        assert output_endpoint.sent_messages[0] == test_message
    
    async def test_bidirectional_pump_no_endpoints(self):
        """Test bidirectional pump fails with no endpoints."""
        bridge = TranslateBridge({})
        
        with pytest.raises(RuntimeError, match="Endpoints not configured"):
            await bridge._run_bidirectional_pump()
