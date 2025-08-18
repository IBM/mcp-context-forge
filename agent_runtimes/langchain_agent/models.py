from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime

# OpenAI Chat API Models
class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of the message sender")
    content: str = Field(..., description="Content of the message")
    name: Optional[str] = Field(None, description="Name of the sender")

class ChatCompletionRequest(BaseModel):
    model: str = Field(..., description="Model to use for completion")
    messages: List[ChatMessage] = Field(..., description="List of messages")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens to generate")
    temperature: Optional[float] = Field(0.7, description="Sampling temperature")
    top_p: Optional[float] = Field(1.0, description="Nucleus sampling parameter")
    n: Optional[int] = Field(1, description="Number of completions to generate")
    stream: Optional[bool] = Field(False, description="Whether to stream responses")
    stop: Optional[Union[str, List[str]]] = Field(None, description="Stop sequences")
    presence_penalty: Optional[float] = Field(0.0, description="Presence penalty")
    frequency_penalty: Optional[float] = Field(0.0, description="Frequency penalty")
    logit_bias: Optional[Dict[str, float]] = Field(None, description="Logit bias")
    user: Optional[str] = Field(None, description="User identifier")

class Usage(BaseModel):
    prompt_tokens: int = Field(..., description="Tokens in the prompt")
    completion_tokens: int = Field(..., description="Tokens in the completion")
    total_tokens: int = Field(..., description="Total tokens used")

class ChatCompletionChoice(BaseModel):
    index: int = Field(..., description="Choice index")
    message: ChatMessage = Field(..., description="Generated message")
    finish_reason: str = Field(..., description="Reason for finishing")

class ChatCompletionResponse(BaseModel):
    id: str = Field(..., description="Unique identifier for the completion")
    object: str = Field("chat.completion", description="Object type")
    created: int = Field(..., description="Unix timestamp of creation")
    model: str = Field(..., description="Model used for completion")
    choices: List[ChatCompletionChoice] = Field(..., description="List of completion choices")
    usage: Usage = Field(..., description="Token usage information")

# Health and Status Models
class HealthResponse(BaseModel):
    status: str = Field(..., description="Health status")
    timestamp: str = Field(..., description="Timestamp of health check")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional health details")

class ReadyResponse(BaseModel):
    ready: bool = Field(..., description="Readiness status")
    timestamp: str = Field(..., description="Timestamp of readiness check")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional readiness details")

# Tool Models
class ToolDefinition(BaseModel):
    id: str = Field(..., description="Tool identifier")
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    input_schema: Dict[str, Any] = Field(..., description="Tool input schema", alias="schema")
    url: Optional[str] = Field(None, description="Tool URL (for REST tools)")
    method: Optional[str] = Field(None, description="HTTP method")
    integration_type: Optional[str] = Field(None, description="Integration type")
    
    class Config:
        populate_by_name = True  # Allow both 'schema' and 'input_schema'

class ToolListResponse(BaseModel):
    tools: List[ToolDefinition] = Field(..., description="List of available tools")
    count: int = Field(..., description="Number of tools")

# Agent Configuration Models
class AgentConfig(BaseModel):
    mcp_gateway_url: str = Field(..., description="MCP Gateway URL")
    gateway_bearer_token: Optional[str] = Field(None, description="Gateway authentication token")
    tools_allowlist: Optional[List[str]] = Field(None, description="List of allowed tool IDs")
    default_model: str = Field("gpt-4o-mini", description="Default model to use")
    max_iterations: int = Field(10, description="Maximum agent iterations")
    temperature: float = Field(0.7, description="Default temperature")
    streaming_enabled: bool = Field(True, description="Enable streaming responses")
    debug_mode: bool = Field(False, description="Enable debug logging")

# Tool Invocation Models
class ToolInvocationRequest(BaseModel):
    tool_id: str = Field(..., description="Tool to invoke")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")

class ToolInvocationResponse(BaseModel):
    tool_id: str = Field(..., description="Tool that was invoked")
    result: Any = Field(..., description="Tool execution result")
    execution_time: Optional[float] = Field(None, description="Execution time in seconds")
    success: bool = Field(..., description="Whether execution was successful")
    error: Optional[str] = Field(None, description="Error message if any")

# Streaming Models
class StreamChunk(BaseModel):
    id: str = Field(..., description="Stream identifier")
    object: str = Field("chat.completion.chunk", description="Object type")
    created: int = Field(..., description="Unix timestamp")
    model: str = Field(..., description="Model used")
    choices: List[Dict[str, Any]] = Field(..., description="Stream choices")

# Error Models
class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error message")
    code: Optional[str] = Field(None, description="Error code")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")

# JSON-RPC Models for A2A communication
class JSONRPCRequest(BaseModel):
    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    method: str = Field(..., description="Method to call")
    params: Optional[Dict[str, Any]] = Field(None, description="Method parameters")
    id: Optional[Union[str, int]] = Field(None, description="Request identifier")

class JSONRPCResponse(BaseModel):
    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    result: Optional[Any] = Field(None, description="Method result")
    error: Optional[Dict[str, Any]] = Field(None, description="Error object")
    id: Optional[Union[str, int]] = Field(None, description="Request identifier")