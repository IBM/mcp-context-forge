# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/llmchat_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import os
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

    if provider == "azure_openai":
        return LLMConfig(
            provider="azure_openai",
            config=AzureOpenAIConfig(
                api_key=fallback(cfg.get("api_key"), "AZURE_OPENAI_API_KEY"),
                azure_endpoint=fallback(cfg.get("azure_endpoint"), "AZURE_OPENAI_ENDPOINT"),
                api_version=fallback(cfg.get("api_version"), "AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
                azure_deployment=fallback(cfg.get("azure_deployment"), "AZURE_OPENAI_DEPLOYMENT", "gpt-4"),
                model=fallback(cfg.get("model"), "AZURE_OPENAI_MODEL", "gpt-4"),
                temperature=fallback(cfg.get("temperature"), "AZURE_OPENAI_TEMPERATURE", 0.7),
            ),
        )

    elif provider == "ollama":
        return LLMConfig(
            provider="ollama",
            config=OllamaConfig(
                model=fallback(cfg.get("model"), "OLLAMA_MODEL", "llama3"),
                temperature=fallback(cfg.get("temperature"), "OLLAMA_TEMPERATURE", 0.7),
            ),
        )

    elif provider == "openai":
        return LLMConfig(
            provider="openai",
            config={
                "api_key": fallback(cfg.get("api_key"), "OPENAI_API_KEY"),
                "model": fallback(cfg.get("model"), "OPENAI_MODEL", "gpt-4o-mini"),
                "temperature": fallback(cfg.get("temperature"), "OPENAI_TEMPERATURE", 0.7),
                "base_url": fallback(cfg.get("base_url"), "OPENAI_BASE_URL"),
            },
        )

    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


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

@llmchat_router.post("/connect")
async def connect(input_data: ConnectInput):
    """Create or refresh a chat session for a user."""
    user_id = input_data.user_id

    # Close old session if it exists
    if user_id in active_sessions:
        await active_sessions[user_id].shutdown()

    try:
        config = build_config(input_data)

        # Store user configuration
        user_configs[user_id] = config

        # Initialize chat service
        chat_service = MCPChatService(config)
        await chat_service.initialize()

        active_sessions[user_id] = chat_service

        return {
            "status": "connected",
            "user_id": user_id,
            "provider": config.llm.provider
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect: {str(e)}")


async def token_streamer(chat_service, message: str):
    async for chunk in chat_service.chat_stream(message):
        yield chunk


@llmchat_router.post("/chat")
async def chat(input_data: ChatInput):
    """Send a message for a given user session."""
    user_id = input_data.user_id
    chat_service = active_sessions.get(user_id)
    
    if not chat_service:
        raise HTTPException(status_code=400, detail="No active session for this user. Please connect first.")

    try:
        if input_data.streaming:
            return StreamingResponse(
                token_streamer(chat_service, input_data.message),
                media_type="text/plain"
            )
        else:
            response = await chat_service.chat(input_data.message)
            return {"user_id": user_id, "response": response}
    except Exception as e:
        return {"error": str(e)}


@llmchat_router.post("/disconnect")
async def disconnect(input_data: DisconnectInput):
    """End the chat session for a user."""
    user_id = input_data.user_id

    # Remove and shut down chat service
    chat_service = active_sessions.pop(user_id, None)

    # Remove user config
    user_configs.pop(user_id, None)

    if not chat_service:
        return {"status": "no active session", "user_id": user_id}

    await chat_service.shutdown()
    return {"status": "disconnected", "user_id": user_id}


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
