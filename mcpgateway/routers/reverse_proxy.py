# -*- coding: utf-8 -*-
"""
FastAPI router for handling reverse proxy connections.

This module provides WebSocket and SSE endpoints for reverse proxy clients
to connect and tunnel their local MCP servers through the gateway.
"""

# Standard
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.database import get_db
from mcpgateway.models import User
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.routers.reverse_proxy")

router = APIRouter(prefix="/reverse-proxy", tags=["reverse-proxy"])


class ReverseProxySession:
    """Manages a reverse proxy session."""
    
    def __init__(self, session_id: str, websocket: WebSocket, user: Optional[User] = None):
        """Initialize reverse proxy session.
        
        Args:
            session_id: Unique session identifier.
            websocket: WebSocket connection.
            user: Authenticated user (if any).
        """
        self.session_id = session_id
        self.websocket = websocket
        self.user = user
        self.server_info: Dict[str, Any] = {}
        self.connected_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.message_count = 0
        self.bytes_transferred = 0
        
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send message to the client.
        
        Args:
            message: Message dictionary to send.
        """
        data = json.dumps(message)
        await self.websocket.send_text(data)
        self.bytes_transferred += len(data)
        self.last_activity = datetime.utcnow()
        
    async def receive_message(self) -> Dict[str, Any]:
        """Receive message from the client.
        
        Returns:
            Parsed message dictionary.
        """
        data = await self.websocket.receive_text()
        self.bytes_transferred += len(data)
        self.message_count += 1
        self.last_activity = datetime.utcnow()
        return json.loads(data)


class ReverseProxyManager:
    """Manages all reverse proxy sessions."""
    
    def __init__(self):
        """Initialize the manager."""
        self.sessions: Dict[str, ReverseProxySession] = {}
        self._lock = asyncio.Lock()
        
    async def add_session(self, session: ReverseProxySession) -> None:
        """Add a new session.
        
        Args:
            session: Session to add.
        """
        async with self._lock:
            self.sessions[session.session_id] = session
            LOGGER.info(f"Added reverse proxy session: {session.session_id}")
            
    async def remove_session(self, session_id: str) -> None:
        """Remove a session.
        
        Args:
            session_id: Session ID to remove.
        """
        async with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
                LOGGER.info(f"Removed reverse proxy session: {session_id}")
                
    def get_session(self, session_id: str) -> Optional[ReverseProxySession]:
        """Get a session by ID.
        
        Args:
            session_id: Session ID to get.
            
        Returns:
            Session if found, None otherwise.
        """
        return self.sessions.get(session_id)
        
    def list_sessions(self) -> list[Dict[str, Any]]:
        """List all active sessions.
        
        Returns:
            List of session information dictionaries.
        """
        return [
            {
                "session_id": session.session_id,
                "server_info": session.server_info,
                "connected_at": session.connected_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
                "message_count": session.message_count,
                "bytes_transferred": session.bytes_transferred,
                "user": session.user.username if session.user else None,
            }
            for session in self.sessions.values()
        ]


# Global manager instance
manager = ReverseProxyManager()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
):
    """WebSocket endpoint for reverse proxy connections.
    
    Args:
        websocket: WebSocket connection.
        db: Database session.
    """
    await websocket.accept()
    
    # Get session ID from headers or generate new one
    session_id = websocket.headers.get("X-Session-ID", uuid.uuid4().hex)
    
    # Check authentication
    user = None
    auth_header = websocket.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            # TODO: Validate token and get user
            pass
        except Exception as e:
            LOGGER.warning(f"Authentication failed: {e}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication failed")
            return
    
    # Create session
    session = ReverseProxySession(session_id, websocket, user)
    await manager.add_session(session)
    
    try:
        LOGGER.info(f"Reverse proxy connected: {session_id}")
        
        # Main message loop
        while True:
            try:
                message = await session.receive_message()
                msg_type = message.get("type")
                
                if msg_type == "register":
                    # Register the server
                    session.server_info = message.get("server", {})
                    LOGGER.info(f"Registered server for session {session_id}: {session.server_info.get('name')}")
                    
                    # Send acknowledgment
                    await session.send_message({
                        "type": "register_ack",
                        "sessionId": session_id,
                        "status": "success"
                    })
                    
                elif msg_type == "unregister":
                    # Unregister the server
                    LOGGER.info(f"Unregistering server for session {session_id}")
                    break
                    
                elif msg_type == "heartbeat":
                    # Respond to heartbeat
                    await session.send_message({
                        "type": "heartbeat",
                        "sessionId": session_id,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
                elif msg_type in ("response", "notification"):
                    # Handle MCP response/notification from the proxied server
                    # TODO: Route to appropriate MCP client
                    LOGGER.debug(f"Received {msg_type} from session {session_id}")
                    
                else:
                    LOGGER.warning(f"Unknown message type from session {session_id}: {msg_type}")
                    
            except WebSocketDisconnect:
                LOGGER.info(f"WebSocket disconnected: {session_id}")
                break
            except json.JSONDecodeError as e:
                LOGGER.error(f"Invalid JSON from session {session_id}: {e}")
                await session.send_message({
                    "type": "error",
                    "message": "Invalid JSON format"
                })
            except Exception as e:
                LOGGER.error(f"Error handling message from session {session_id}: {e}")
                await session.send_message({
                    "type": "error",
                    "message": str(e)
                })
                
    finally:
        await manager.remove_session(session_id)
        LOGGER.info(f"Reverse proxy session ended: {session_id}")


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user),
):
    """List all active reverse proxy sessions.
    
    Args:
        current_user: Authenticated user.
        
    Returns:
        List of session information.
    """
    return {
        "sessions": manager.list_sessions(),
        "total": len(manager.sessions)
    }


@router.delete("/sessions/{session_id}")
async def disconnect_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """Disconnect a reverse proxy session.
    
    Args:
        session_id: Session ID to disconnect.
        current_user: Authenticated user.
        
    Returns:
        Disconnection status.
    """
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    # Close the WebSocket connection
    await session.websocket.close()
    await manager.remove_session(session_id)
    
    return {"status": "disconnected", "session_id": session_id}


@router.post("/sessions/{session_id}/request")
async def send_request_to_session(
    session_id: str,
    request: Dict[str, Any],
    current_user: User = Depends(get_current_user),
):
    """Send an MCP request to a reverse proxy session.
    
    Args:
        session_id: Session ID to send request to.
        request: MCP request to send.
        current_user: Authenticated user.
        
    Returns:
        Request acknowledgment.
    """
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    # Wrap the request in reverse proxy envelope
    message = {
        "type": "request",
        "sessionId": session_id,
        "payload": request
    }
    
    try:
        await session.send_message(message)
        return {"status": "sent", "session_id": session_id}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send request: {e}"
        )


@router.get("/sse/{session_id}")
async def sse_endpoint(
    session_id: str,
    request: Request,
):
    """SSE endpoint for receiving messages from a reverse proxy session.
    
    Args:
        session_id: Session ID to subscribe to.
        request: HTTP request.
        
    Returns:
        SSE stream.
    """
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    
    async def event_generator():
        """Generate SSE events."""
        try:
            # Send initial connection event
            yield {
                "event": "connected",
                "data": json.dumps({
                    "sessionId": session_id,
                    "serverInfo": session.server_info
                })
            }
            
            # TODO: Implement message queue for SSE delivery
            while not await request.is_disconnected():
                await asyncio.sleep(30)  # Keepalive
                yield {
                    "event": "keepalive",
                    "data": json.dumps({"timestamp": datetime.utcnow().isoformat()})
                }
                
        except asyncio.CancelledError:
            pass
            
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )