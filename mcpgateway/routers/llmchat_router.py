# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/llmchat_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import os
import json

from typing import Optional, Dict, Any
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse

from pydantic import BaseModel
from dotenv import load_dotenv
import asyncio

from mcpgateway.services.mcp_client_chat_service import (
    MCPChatService,
    MCPClientConfig,
    MCPServerConfig,
    LLMConfig,
    AzureOpenAIConfig,
    OllamaConfig,
)

# Load environment variables
load_dotenv()

# Initialize router
llmchat_router = APIRouter(prefix="/llmchat", tags=["llmchat"])

# Store active chat sessions per user
active_sessions: Dict[str, MCPChatService] = {}

# Store configuration per user
user_configs: Dict[str, MCPClientConfig] = {}

# ---------- Utility ----------

def fallback(value, env_var_name: str, default: Optional[Any] = None):
    return value if value is not None else os.getenv(env_var_name, default)


# ---------- MODELS ----------

class LLMInput(BaseModel):
    provider: str
    config: Dict[str, Any] = {}


class ServerInput(BaseModel):
    url: Optional[str] = None
    transport: Optional[str] = "streamable_http"
    auth_token: Optional[str] = None


class ConnectInput(BaseModel):
    user_id: str
    server: Optional[ServerInput] = None
    llm: Optional[LLMInput] = None
    streaming: bool = False


class ChatInput(BaseModel):
    user_id: str
    message: str
    streaming: bool = False


class DisconnectInput(BaseModel):
    user_id: str


# ---------- HELPERS ----------

def build_llm_config(llm: Optional[LLMInput]) -> LLMConfig:
    provider = fallback(llm.provider if llm else None, "LLM_PROVIDER", "azure_openai")
    cfg = llm.config if llm else {}
    
    # Validate provider
    valid_providers = ["azure_openai", "ollama", "openai"]
    if provider not in valid_providers:
        raise ValueError(f"Unsupported LLM provider: {provider}. Supported providers: {', '.join(valid_providers)}")
    
    if provider == "azure_openai":
        # Validate required fields
        api_key = fallback(cfg.get("api_key"), "AZURE_OPENAI_API_KEY")
        azure_endpoint = fallback(cfg.get("azure_endpoint"), "AZURE_OPENAI_ENDPOINT")
        
        if not api_key:
            raise ValueError("Azure OpenAI API key is required but not provided")
        if not azure_endpoint:
            raise ValueError("Azure OpenAI endpoint is required but not provided")
        
        return LLMConfig(
            provider="azure_openai",
            config=AzureOpenAIConfig(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=fallback(cfg.get("api_version"), "AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
                azure_deployment=fallback(cfg.get("azure_deployment"), "AZURE_OPENAI_DEPLOYMENT", "gpt-4"),
                model=fallback(cfg.get("model"), "AZURE_OPENAI_MODEL", "gpt-4"),
                temperature=fallback(cfg.get("temperature"), "AZURE_OPENAI_TEMPERATURE", 0.7),
            ),
        )
    elif provider == "ollama":
        model = fallback(cfg.get("model"), "OLLAMA_MODEL", "llama3")
        if not model:
            raise ValueError("Ollama model name is required but not provided")
            
        return LLMConfig(
            provider="ollama",
            config=OllamaConfig(
                model=model,
                temperature=fallback(cfg.get("temperature"), "OLLAMA_TEMPERATURE", 0.7),
            ),
        )
    elif provider == "openai":
        api_key = fallback(cfg.get("api_key"), "OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API key is required but not provided")
            
        return LLMConfig(
            provider="openai",
            config={
                "api_key": api_key,
                "model": fallback(cfg.get("model"), "OPENAI_MODEL", "gpt-4o-mini"),
                "temperature": fallback(cfg.get("temperature"), "OPENAI_TEMPERATURE", 0.7),
                "base_url": fallback(cfg.get("base_url"), "OPENAI_BASE_URL"),
            },
        )



def build_config(input_data: ConnectInput) -> MCPClientConfig:
    server = input_data.server
    llm = input_data.llm

    return MCPClientConfig(
        mcp_server=MCPServerConfig(
            url=fallback(server.url if server else None, "MCP_SERVER_URL", "http://localhost:8000/mcp"),
            transport=fallback(server.transport if server else None, "MCP_SERVER_TRANSPORT", "streamable_http"),
            auth_token=fallback(server.auth_token if server else None, "MCP_SERVER_AUTH_TOKEN"),
        ),
        llm=build_llm_config(llm),
        enable_streaming=input_data.streaming,
    )


# ---------- ROUTES ----------
from fastapi import Request
@llmchat_router.post("/connect")
async def connect(input_data: ConnectInput, request: Request):
    """Create or refresh a chat session for a user."""
    user_id = input_data.user_id
    
    try:
        # Validate user_id
        if not user_id or not isinstance(user_id, str):
            raise HTTPException(status_code=400, detail="Invalid user ID provided")
        
        # Handle authentication token
        if input_data.server.auth_token is None or input_data.server.auth_token == "":
            jwt_token = request.cookies.get("jwt_token")
            if not jwt_token:
                raise HTTPException(
                    status_code=401, 
                    detail="Authentication required. Please ensure you are logged in."
                )
            input_data.server.auth_token = jwt_token
        
        # Close old session if it exists
        if user_id in active_sessions:
            try:
                await active_sessions[user_id].shutdown()
            except Exception as shutdown_error:
                logger.warning(f"Failed to cleanly shutdown existing session for {user_id}: {shutdown_error}")
                # Continue anyway to establish new connection
        
        # Build and validate configuration
        try:
            config = build_config(input_data)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=f"Invalid configuration: {str(ve)}")
        except Exception as config_error:
            raise HTTPException(status_code=400, detail=f"Configuration error: {str(config_error)}")
        
        # Store user configuration
        user_configs[user_id] = config
        
        # Initialize chat service
        try:
            chat_service = MCPChatService(config)
            await chat_service.initialize()
        except ConnectionError as ce:
            # Clean up partial state
            user_configs.pop(user_id, None)
            raise HTTPException(
                status_code=503, 
                detail=f"Failed to connect to MCP server: {str(ce)}. Please verify the server URL and authentication."
            )
        except ValueError as ve:
            # Clean up partial state
            user_configs.pop(user_id, None)
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid LLM configuration: {str(ve)}"
            )
        except Exception as init_error:
            # Clean up partial state
            user_configs.pop(user_id, None)
            raise HTTPException(
                status_code=500, 
                detail=f"Service initialization failed: {str(init_error)}"
            )
        
        active_sessions[user_id] = chat_service
        
        # Extract tool names
        tool_names = []
        try:
            if hasattr(chat_service, '_tools') and chat_service._tools:
                for tool in chat_service._tools:
                    tool_name = getattr(tool, 'name', None)
                    if tool_name:
                        tool_names.append(tool_name)
        except Exception as tool_error:
            logger.warning(f"Failed to extract tool names: {tool_error}")
            # Continue without tools list
        
        return {
            "status": "connected",
            "user_id": user_id,
            "provider": config.llm.provider,
            "tool_count": len(tool_names),
            "tools": tool_names
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error in connect endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Unexpected connection error: {str(e)}"
        )



async def token_streamer(chat_service, message: str):
    async def sse(event_type: str, data: Dict[str, Any]):
        # Minimal SSE framing
        yield f"event: {event_type}\n".encode("utf-8")
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
    
    try:
        async for ev in chat_service.chat_events(message):
            et = ev.get("type")
            if et == "token":
                async for part in sse("token", {"content": ev.get("content", "")}):
                    yield part
            elif et in ("tool_start", "tool_end", "tool_error"):
                async for part in sse(et, ev):
                    yield part
            elif et == "final":
                async for part in sse("final", ev):
                    yield part
    except ConnectionError as ce:
        error_event = {
            "type": "error",
            "error": f"Connection lost: {str(ce)}",
            "recoverable": False
        }
        async for part in sse("error", error_event):
            yield part
    except TimeoutError:
        error_event = {
            "type": "error",
            "error": "Request timed out waiting for LLM response",
            "recoverable": True
        }
        async for part in sse("error", error_event):
            yield part
    except RuntimeError as re:
        error_event = {
            "type": "error",
            "error": f"Service error: {str(re)}",
            "recoverable": False
        }
        async for part in sse("error", error_event):
            yield part
    except Exception as e:
        logger.error(f"Unexpected streaming error: {e}", exc_info=True)
        error_event = {
            "type": "error",
            "error": f"Unexpected error: {str(e)}",
            "recoverable": False
        }
        async for part in sse("error", error_event):
            yield part




@llmchat_router.post("/chat")
async def chat(input_data: ChatInput):
    """Send a message for a given user session."""
    user_id = input_data.user_id
    
    # Validate input
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
    
    if not input_data.message or not input_data.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # Check for active session
    chat_service = active_sessions.get(user_id)
    if not chat_service:
        raise HTTPException(
            status_code=400, 
            detail="No active session found. Please connect to a server first."
        )
    
    # Verify session is initialized
    if not chat_service.is_initialized:
        raise HTTPException(
            status_code=503, 
            detail="Session is not properly initialized. Please reconnect."
        )
    
    try:
        if input_data.streaming:
            return StreamingResponse(
                token_streamer(chat_service, input_data.message),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no"  # Disable proxy buffering
                },
            )
        else:
            try:
                result = await chat_service.chat_with_metadata(input_data.message)
                return {
                    "user_id": user_id,
                    "response": result["text"],
                    "tool_used": result["tool_used"],
                    "tools": result["tools"],
                    "tool_invocations": result["tool_invocations"],
                    "elapsed_ms": result["elapsed_ms"],
                }
            except RuntimeError as re:
                raise HTTPException(status_code=503, detail=f"Chat service error: {str(re)}")
            except ConnectionError as ce:
                raise HTTPException(
                    status_code=503, 
                    detail=f"Lost connection to MCP server: {str(ce)}. Please reconnect."
                )
            except TimeoutError:
                raise HTTPException(
                    status_code=504, 
                    detail="Request timed out. The LLM took too long to respond."
                )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"An unexpected error occurred: {str(e)}"
        )



@llmchat_router.post("/disconnect")
async def disconnect(input_data: DisconnectInput):
    """End the chat session for a user."""
    user_id = input_data.user_id
    
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
    
    # Remove and shut down chat service
    chat_service = active_sessions.pop(user_id, None)
    # Remove user config
    user_configs.pop(user_id, None)
    
    if not chat_service:
        return {"status": "no_active_session", "user_id": user_id, "message": "No active session to disconnect"}
    
    try:
        await chat_service.shutdown()
        return {"status": "disconnected", "user_id": user_id, "message": "Successfully disconnected"}
    except Exception as e:
        logger.error(f"Error during disconnect for user {user_id}: {e}", exc_info=True)
        # Session already removed, so return success with warning
        return {
            "status": "disconnected_with_errors", 
            "user_id": user_id,
            "message": "Disconnected but cleanup encountered errors",
            "warning": str(e)
        }



@llmchat_router.get("/status/{user_id}")
async def status(user_id: str):
    """Check if a user session exists."""
    return {
        "user_id": user_id,
        "connected": user_id in active_sessions
    }


@llmchat_router.get("/config/{user_id}")
async def get_config(user_id: str):
    """Retrieve the stored configuration for a user."""
    config = user_configs.get(user_id)
    if not config:
        raise HTTPException(status_code=404, detail="No config found for this user.")

    # Sanitize and return config (remove secrets)
    config_dict = config.model_dump()

    if "config" in config_dict.get("llm", {}):
        config_dict["llm"]["config"].pop("api_key", None)
        config_dict["llm"]["config"].pop("auth_token", None)

    return config_dict
