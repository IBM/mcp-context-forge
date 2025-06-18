# -*- coding: utf-8 -*-
"""MCP Gateway Transport-Translation Bridge Core.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

This module implements the core bridge logic for translating between different
MCP transport protocols. It provides bidirectional pumping between endpoints
and handles message routing with proper error handling and logging.
"""

import asyncio
import base64
import json
import logging
import os
import subprocess
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import Response
from starlette.routing import Route, WebSocketRoute
import uvicorn

from mcpgateway.transports.sse_transport import SSETransport
from mcpgateway.transports.websocket_transport import WebSocketTransport

logger = logging.getLogger(__name__)

# Environment variables for configuration
MCP_TRANSLATE_LOG_LEVEL = os.getenv("MCP_TRANSLATE_LOG_LEVEL", "info")
MCP_TOOL_CALL_TIMEOUT = int(os.getenv("MCP_TOOL_CALL_TIMEOUT", "90"))


class TransportEndpoint(ABC):
    """Abstract base class for transport endpoints."""
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection for this endpoint."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up connection for this endpoint."""
        pass
    
    @abstractmethod
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send a message through this endpoint.
        
        Args:
            message: JSON-RPC message to send
        """
        pass
    
    @abstractmethod
    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from this endpoint.
        
        Yields:
            JSON-RPC messages
        """
        pass
    
    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if endpoint is connected.
        
        Returns:
            True if connected
        """
        pass


class StdIOEndpoint(TransportEndpoint):
    """Endpoint for stdio-based MCP servers."""
    
    def __init__(self, command: str):
        """Initialize stdio endpoint.
        
        Args:
            command: Command to run the stdio MCP server
        """
        self.command = command
        self.process: Optional[subprocess.Popen] = None
        self._connected = False
        self._message_queue = asyncio.Queue()
        self._read_task: Optional[asyncio.Task] = None
        
    async def connect(self) -> None:
        """Start the stdio MCP server process."""
        try:
            self.process = subprocess.Popen(
                self.command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            self._connected = True
            
            # Start reading from stdout
            self._read_task = asyncio.create_task(self._read_stdout())
            
            logger.info(f"Started stdio server: {self.command}")
            
        except Exception as e:
            logger.error(f"Failed to start stdio server: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Stop the stdio MCP server process."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            
        self._connected = False
        logger.info("Stopped stdio server")
    
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send message to stdio server.
        
        Args:
            message: JSON-RPC message
        """
        if not self._connected or not self.process:
            raise RuntimeError("Stdio endpoint not connected")
        
        try:
            message_str = json.dumps(message) + "\n"
            self.process.stdin.write(message_str)
            self.process.stdin.flush()
            
            logger.debug(f"Sent to stdio: {message.get('method', '(response)')}")
            
        except Exception as e:
            logger.error(f"Failed to send message to stdio: {e}")
            raise
    
    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from stdio server.
        
        Yields:
            JSON-RPC messages
        """
        while self._connected:
            try:
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield message
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error receiving from stdio: {e}")
                break
    
    async def is_connected(self) -> bool:
        """Check if stdio endpoint is connected."""
        return self._connected and self.process and self.process.poll() is None
    
    async def _read_stdout(self) -> None:
        """Read messages from stdout in a loop."""
        try:
            while self._connected and self.process:
                line = await asyncio.to_thread(self.process.stdout.readline)
                if not line:
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                try:
                    message = json.loads(line)
                    await self._message_queue.put(message)
                    logger.debug(f"Received from stdio: {message.get('method', '(response)')}")
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON from stdio: {line[:100]}")
                    
        except Exception as e:
            logger.error(f"Error reading from stdio: {e}")
        finally:
            self._connected = False


class SSEEndpoint(TransportEndpoint):
    """Endpoint for SSE-based communication."""
    
    def __init__(self, url: Optional[str] = None, transport: Optional[SSETransport] = None, headers: Optional[Dict[str, str]] = None):
        """Initialize SSE endpoint.
        
        Args:
            url: Remote SSE URL (for client mode)
            transport: Existing SSE transport (for server mode)
            headers: HTTP headers for requests
        """
        self.url = url
        self.transport = transport
        self.headers = headers or {}
        self._connected = False
        self._client: Optional[httpx.AsyncClient] = None
        self._message_queue = asyncio.Queue()
        
    async def connect(self) -> None:
        """Connect to SSE endpoint."""
        if self.transport:
            # Server mode - use existing transport
            await self.transport.connect()
            self._connected = True
            logger.info("SSE server endpoint connected")
        elif self.url:
            # Client mode - connect to remote SSE
            self._client = httpx.AsyncClient(headers=self.headers, timeout=30.0)
            self._connected = True
            logger.info(f"SSE client endpoint connected to {self.url}")
        else:
            raise ValueError("Either URL or transport must be provided")
    
    async def disconnect(self) -> None:
        """Disconnect from SSE endpoint."""
        if self.transport:
            await self.transport.disconnect()
        if self._client:
            await self._client.aclose()
        
        self._connected = False
        logger.info("SSE endpoint disconnected")
    
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send message through SSE endpoint."""
        if not self._connected:
            raise RuntimeError("SSE endpoint not connected")
        
        if self.transport:
            # Server mode - send via transport
            await self.transport.send_message(message)
        elif self._client and self.url:
            # Client mode - POST to message endpoint
            try:
                # Extract base URL and construct message endpoint
                parsed = urlparse(self.url)
                message_url = f"{parsed.scheme}://{parsed.netloc}/message"
                
                response = await self._client.post(message_url, json=message)
                response.raise_for_status()
                
                logger.debug(f"Sent to SSE: {message.get('method', '(response)')}")
                
            except Exception as e:
                logger.error(f"Failed to send message to SSE: {e}")
                raise
    
    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from SSE endpoint."""
        if not self._connected:
            raise RuntimeError("SSE endpoint not connected")
        
        if self.transport:
            # Server mode - receive via transport
            async for message in self.transport.receive_message():
                yield message
        elif self._client and self.url:
            # Client mode - listen to SSE stream
            async with self._client.stream("GET", self.url) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = line[6:]  # Remove "data: " prefix
                            if data and data != "{}":
                                message = json.loads(data)
                                yield message
                        except json.JSONDecodeError:
                            continue
    
    async def is_connected(self) -> bool:
        """Check if SSE endpoint is connected."""
        if self.transport:
            return await self.transport.is_connected()
        return self._connected


class WSEndpoint(TransportEndpoint):
    """Endpoint for WebSocket-based communication."""
    
    def __init__(self, websocket: WebSocket):
        """Initialize WebSocket endpoint.
        
        Args:
            websocket: FastAPI WebSocket connection
        """
        self.transport = WebSocketTransport(websocket)
    
    async def connect(self) -> None:
        """Connect WebSocket endpoint."""
        await self.transport.connect()
        logger.info("WebSocket endpoint connected")
    
    async def disconnect(self) -> None:
        """Disconnect WebSocket endpoint."""
        await self.transport.disconnect()
        logger.info("WebSocket endpoint disconnected")
    
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send message through WebSocket."""
        await self.transport.send_message(message)
    
    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from WebSocket."""
        async for message in self.transport.receive_message():
            yield message
    
    async def is_connected(self) -> bool:
        """Check if WebSocket endpoint is connected."""
        return await self.transport.is_connected()


class StreamableHTTPEndpoint(TransportEndpoint):
    """Endpoint for streamable HTTP-based communication."""
    
    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        """Initialize streamable HTTP endpoint.
        
        Args:
            url: Remote HTTP endpoint URL
            headers: HTTP headers for requests
        """
        self.url = url
        self.headers = headers or {}
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False
    
    async def connect(self) -> None:
        """Connect to HTTP endpoint."""
        self._client = httpx.AsyncClient(headers=self.headers, timeout=30.0)
        self._connected = True
        logger.info(f"HTTP endpoint connected to {self.url}")
    
    async def disconnect(self) -> None:
        """Disconnect from HTTP endpoint."""
        if self._client:
            await self._client.aclose()
        self._connected = False
        logger.info("HTTP endpoint disconnected")
    
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send message through HTTP POST."""
        if not self._connected or not self._client:
            raise RuntimeError("HTTP endpoint not connected")
        
        try:
            response = await self._client.post(self.url, json=message)
            response.raise_for_status()
            logger.debug(f"Sent to HTTP: {message.get('method', '(response)')}")
            
        except Exception as e:
            logger.error(f"Failed to send message to HTTP: {e}")
            raise
    
    async def receive_message(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Receive messages from HTTP (streaming response)."""
        if not self._connected or not self._client:
            raise RuntimeError("HTTP endpoint not connected")
        
        # This is a placeholder - in practice, streamable HTTP would need
        # to implement a long-polling or chunked response mechanism
        yield {"jsonrpc": "2.0", "method": "initialize", "id": 1}
        
        # Keep connection alive but don't yield more messages
        # Real implementation would handle streaming HTTP responses
        while self._connected:
            await asyncio.sleep(1.0)
    
    async def is_connected(self) -> bool:
        """Check if HTTP endpoint is connected."""
        return self._connected


class TranslateBridge:
    """Main bridge class that coordinates transport translation."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize translate bridge.
        
        Args:
            config: Bridge configuration dictionary
        """
        self.config = config
        self.input_endpoint: Optional[TransportEndpoint] = None
        self.output_endpoint: Optional[TransportEndpoint] = None
        self.app: Optional[FastAPI] = None
        self._running = False
        self._pump_tasks: List[asyncio.Task] = []
        
    async def run(self) -> None:
        """Run the bridge."""
        try:
            self._running = True
            
            # Create input endpoint
            await self._create_input_endpoint()
            
            # Determine if we need to run a server
            if self.config["output_transport"] in ["sse", "ws"]:
                await self._run_server()
            else:
                # Direct bridging mode (e.g., SSE -> stdio)
                await self._create_output_endpoint()
                await self._run_direct_bridge()
                
        except KeyboardInterrupt:
            logger.info("Bridge interrupted")
        except Exception as e:
            logger.error(f"Bridge error: {e}")
            raise
        finally:
            await self._cleanup()
    
    async def _create_input_endpoint(self) -> None:
        """Create the input transport endpoint."""
        if self.config["stdio_command"]:
            self.input_endpoint = StdIOEndpoint(self.config["stdio_command"])
        elif self.config["sse_url"]:
            self.input_endpoint = SSEEndpoint(
                url=self.config["sse_url"],
                headers=self.config["headers"]
            )
        elif self.config["streamable_http_url"]:
            self.input_endpoint = StreamableHTTPEndpoint(
                url=self.config["streamable_http_url"],
                headers=self.config["headers"]
            )
        else:
            raise ValueError("No input transport specified")
        
        await self.input_endpoint.connect()
        logger.info("Input endpoint created and connected")
    
    async def _create_output_endpoint(self) -> None:
        """Create the output transport endpoint."""
        output_type = self.config["output_transport"]
        
        if output_type == "stdio":
            # For stdio output, we'll print to stdout
            # This is a simplified implementation
            logger.info("Output endpoint: stdio (stdout)")
        else:
            raise ValueError(f"Unsupported output transport: {output_type}")
    
    async def _run_server(self) -> None:
        """Run the embedded server for SSE/WS output."""
        self.app = FastAPI(title="MCP Transport Bridge")
        
        # Add CORS middleware if configured
        if self.config["cors_origins"]:
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=self.config["cors_origins"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        
        # Add health endpoint if configured
        if self.config["health_endpoint"]:
            @self.app.get(self.config["health_endpoint"])
            async def health():
                return Response("ok", status_code=200)
        
        # Add SSE endpoint
        if self.config["output_transport"] == "sse":
            @self.app.get(self.config["sse_path"])
            async def sse_endpoint(request: Request):
                # Create SSE transport and endpoint
                sse_transport = SSETransport()
                self.output_endpoint = SSEEndpoint(transport=sse_transport)
                await self.output_endpoint.connect()
                
                # Start bidirectional pump
                pump_task = asyncio.create_task(self._run_bidirectional_pump())
                self._pump_tasks.append(pump_task)
                
                return await sse_transport.create_sse_response(request)
            
            @self.app.post(self.config["message_path"])
            async def message_endpoint(request: Request):
                message = await request.json()
                if self.input_endpoint:
                    await self.input_endpoint.send_message(message)
                return JSONResponse({"status": "ok"})
        
        # Add WebSocket endpoint
        elif self.config["output_transport"] == "ws":
            @self.app.websocket("/ws")
            async def websocket_endpoint(websocket: WebSocket):
                self.output_endpoint = WSEndpoint(websocket)
                await self.output_endpoint.connect()
                
                try:
                    # Start bidirectional pump
                    await self._run_bidirectional_pump()
                finally:
                    await self.output_endpoint.disconnect()
        
        # Start server
        port = self.config["port"]
        logger.info(f"Starting server on port {port}")
        
        config = uvicorn.Config(
            self.app,
            host="0.0.0.0",
            port=port,
            log_level=self.config["log_level"]
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    async def _run_direct_bridge(self) -> None:
        """Run direct bridging between input and output."""
        # For stdio output, we implement a simple stdout bridge
        if self.config["output_transport"] == "stdio":
            async for message in self.input_endpoint.receive_message():
                # Print JSON message to stdout
                print(json.dumps(message), flush=True)
        else:
            # Run bidirectional pump for other output types
            await self._run_bidirectional_pump()
    
    async def _run_bidirectional_pump(self) -> None:
        """Run bidirectional message pump between endpoints."""
        if not self.input_endpoint or not self.output_endpoint:
            raise RuntimeError("Endpoints not configured")
        
        async def pump_input_to_output():
            """Pump messages from input to output."""
            try:
                async for message in self.input_endpoint.receive_message():
                    await self.output_endpoint.send_message(message)
            except Exception as e:
                logger.error(f"Input->Output pump error: {e}")
        
        async def pump_output_to_input():
            """Pump messages from output to input."""
            try:
                async for message in self.output_endpoint.receive_message():
                    await self.input_endpoint.send_message(message)
            except Exception as e:
                logger.error(f"Output->Input pump error: {e}")
        
        # Run both pumps concurrently
        logger.info("Starting bidirectional message pump")
        await asyncio.gather(
            pump_input_to_output(),
            pump_output_to_input(),
            return_exceptions=True
        )
    
    async def _cleanup(self) -> None:
        """Clean up resources."""
        self._running = False
        
        # Cancel pump tasks
        for task in self._pump_tasks:
            task.cancel()
        
        # Disconnect endpoints
        if self.input_endpoint:
            await self.input_endpoint.disconnect()
        if self.output_endpoint:
            await self.output_endpoint.disconnect()
        
        logger.info("Bridge cleanup completed")
