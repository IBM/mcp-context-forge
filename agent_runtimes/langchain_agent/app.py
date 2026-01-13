# -*- coding: utf-8 -*-
# Standard
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

# Third-Party
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import orjson

try:
    # Local
    from .agent_langchain import LangchainMCPAgent
    from .config import get_settings
    from .models import (
        ChatCompletionChoice,
        ChatCompletionRequest,
        ChatCompletionResponse,
        ChatMessage,
        HealthResponse,
        ReadyResponse,
        ToolListResponse,
        Usage,
    )
except ImportError:
    # Third-Party
    from agent_langchain import LangchainMCPAgent
    from config import get_settings
    from models import (
        ChatCompletionChoice,
        ChatCompletionRequest,
        ChatCompletionResponse,
        ChatMessage,
        HealthResponse,
        ReadyResponse,
        ToolListResponse,
        Usage,
    )

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="MCP Langchain Agent",
    description="A Langchain agent with OpenAI-compatible API that integrates with MCP Gateway",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize settings and agent
settings = get_settings()
agent = LangchainMCPAgent.from_config(settings)


@app.on_event("startup")
async def startup_event():
    """Initialize the agent and load tools on startup"""
    try:
        await agent.initialize()
        logger.info("Agent initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize agent: {e}")
        raise


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        # Basic health check - ensure agent is responsive
        tools_count = len(agent.get_available_tools())
        return HealthResponse(
            status="healthy",
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            details={
                "agent_initialized": agent.is_initialized(),
                "tools_loaded": tools_count,
                "gateway_url": settings.mcp_gateway_url,
            },
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")


@app.get("/ready", response_model=ReadyResponse)
async def readiness_check():
    """Readiness check endpoint"""
    try:
        # More thorough readiness check
        is_ready = await agent.check_readiness()
        if not is_ready:
            raise HTTPException(status_code=503, detail="Service not ready")

        return ReadyResponse(
            ready=True,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            details={
                "gateway_connection": await agent.test_gateway_connection(),
                "tools_available": (len(agent.tools) > 0) or (len(agent.get_available_tools()) > 0),
            },
        )
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service not ready: {str(e)}")


@app.get("/list_tools", response_model=ToolListResponse)
async def list_tools():
    """List all available tools"""
    try:
        tools = agent.get_available_tools()
        return ToolListResponse(
            tools=[
                {
                    "id": tool.id,
                    "name": tool.name or tool.id,
                    "description": tool.description or "",
                    "schema": tool.schema or {},
                    "url": tool.url,
                    "method": tool.method,
                    "integration_type": tool.integration_type,
                }
                for tool in tools
            ],
            count=len(tools),
        )
    except Exception as e:
        logger.error(f"Failed to list tools: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list tools: {str(e)}")


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions endpoint"""
    try:
        if request.stream:
            return StreamingResponse(_stream_chat_completion(request), media_type="text/plain")
        else:
            return await _complete_chat(request)
    except Exception as e:
        logger.error(f"Chat completion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Chat completion failed: {str(e)}")


async def _complete_chat(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Handle non-streaming chat completion"""
    start_time = time.time()

    # Convert messages to langchain format
    messages = [msg.dict() for msg in request.messages]

    # Run the agent
    response = await agent.run_async(
        messages=messages,
        model=request.model,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        tools_enabled=True,
    )

    # Calculate token usage (approximate)
    prompt_tokens = sum(len(msg.content.split()) for msg in request.messages if msg.content)
    completion_tokens = len(response.split()) if isinstance(response, str) else 0
    total_tokens = prompt_tokens + completion_tokens

    # Create response
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        object="chat.completion",
        created=int(start_time),
        model=request.model,
        choices=[
            ChatCompletionChoice(index=0, message=ChatMessage(role="assistant", content=response), finish_reason="stop")
        ],
        usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total_tokens),
    )


async def _stream_chat_completion(request: ChatCompletionRequest) -> AsyncGenerator[str, None]:
    """Handle streaming chat completion"""
    start_time = time.time()
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Convert messages to langchain format
    messages = [msg.dict() for msg in request.messages]

    # Stream the agent response
    async for chunk in agent.stream_async(
        messages=messages,
        model=request.model,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        tools_enabled=True,
    ):
        # Format as OpenAI streaming response
        stream_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(start_time),
            "model": request.model,
            "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
        }

        yield f"data: {orjson.dumps(stream_chunk).decode()}\n\n"

    # Send final chunk
    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(start_time),
        "model": request.model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }

    yield f"data: {orjson.dumps(final_chunk).decode()}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible models endpoint"""
    return {
        "object": "list",
        "data": [
            {
                "id": settings.default_model,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mcp-langchain-agent",
            }
        ],
    }


@app.post("/v1/tools/invoke")
async def invoke_tool(request: dict[str, Any]):
    """Direct tool invocation endpoint"""
    try:
        tool_id = request.get("tool_id")
        args = request.get("args", {})

        if not tool_id:
            raise HTTPException(status_code=400, detail="tool_id is required")

        result = await agent.invoke_tool(tool_id, args)
        return {"result": result}
    except Exception as e:
        logger.error(f"Tool invocation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Tool invocation failed: {str(e)}")


# A2A endpoint for agent-to-agent communication
@app.post("/a2a")
async def agent_to_agent(request: dict[str, Any]):
    """Agent-to-agent communication endpoint (JSON-RPC style)"""
    try:
        if request.get("method") == "invoke":
            params = request.get("params", {})
            tool_id = params.get("tool")
            args = params.get("args", {})

            result = await agent.invoke_tool(tool_id, args)

            return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        else:
            raise HTTPException(status_code=400, detail="Unsupported method")
    except Exception as e:
        logger.error(f"A2A communication failed: {e}")
        return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32603, "message": str(e)}}


if __name__ == "__main__":
    # Third-Party
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
