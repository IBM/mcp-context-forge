# -*- coding: utf-8 -*-
# Standard
from typing import Any

# Third-Party
from pydantic import BaseModel, Field


# OpenAI Chat API Models
class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of the message sender")
    content: str = Field(..., description="Content of the message")
    name: str | None = Field(None, description="Name of the sender")


class ChatCompletionRequest(BaseModel):
    model: str = Field(..., description="Model to use for completion")
    messages: list[ChatMessage] = Field(..., description="List of messages")
    max_tokens: int | None = Field(None, description="Maximum tokens to generate")
    temperature: float | None = Field(0.7, description="Sampling temperature")
    top_p: float | None = Field(1.0, description="Nucleus sampling parameter")
    n: int | None = Field(1, description="Number of completions to generate")
    stream: bool | None = Field(False, description="Whether to stream responses")
    stop: str | list[str] | None = Field(None, description="Stop sequences")
    presence_penalty: float | None = Field(0.0, description="Presence penalty")
    frequency_penalty: float | None = Field(0.0, description="Frequency penalty")
    logit_bias: dict[str, float] | None = Field(None, description="Logit bias")
    user: str | None = Field(None, description="User identifier")


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
    choices: list[ChatCompletionChoice] = Field(..., description="List of completion choices")
    usage: Usage = Field(..., description="Token usage information")


# Health and Status Models
class HealthResponse(BaseModel):
    status: str = Field(..., description="Health status")
    timestamp: str = Field(..., description="Timestamp of health check")
    details: dict[str, Any] | None = Field(None, description="Additional health details")


class ReadyResponse(BaseModel):
    ready: bool = Field(..., description="Readiness status")
    timestamp: str = Field(..., description="Timestamp of readiness check")
    details: dict[str, Any] | None = Field(None, description="Additional readiness details")


# Tool Models
class ToolDefinition(BaseModel):
    id: str = Field(..., description="Tool identifier")
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    input_schema: dict[str, Any] = Field(..., description="Tool input schema", alias="schema")
    url: str | None = Field(None, description="Tool URL (for REST tools)")
    method: str | None = Field(None, description="HTTP method")
    integration_type: str | None = Field(None, description="Integration type")

    class Config:
        populate_by_name = True  # Allow both 'schema' and 'input_schema'


class ToolListResponse(BaseModel):
    tools: list[ToolDefinition] = Field(..., description="List of available tools")
    count: int = Field(..., description="Number of tools")


# Agent Configuration Models
class AgentConfig(BaseModel):
    # ContextForge Configuration
    mcp_gateway_url: str = Field(..., description="ContextForge URL")
    gateway_bearer_token: str | None = Field(None, description="Gateway authentication token")
    tools_allowlist: list[str] | None = Field(None, description="List of allowed tool IDs")

    # LLM Provider Configuration
    llm_provider: str = Field("openai", description="LLM provider (openai, azure, bedrock, ollama, anthropic)")
    default_model: str = Field("gpt-4o-mini", description="Default model to use")

    # OpenAI Configuration
    openai_api_key: str | None = Field(None, description="OpenAI API key")
    openai_base_url: str | None = Field(None, description="Custom OpenAI base URL")
    openai_organization: str | None = Field(None, description="OpenAI organization")

    # Azure OpenAI Configuration
    azure_openai_api_key: str | None = Field(None, description="Azure OpenAI API key")
    azure_openai_endpoint: str | None = Field(None, description="Azure OpenAI endpoint")
    azure_openai_api_version: str = Field("2024-02-15-preview", description="Azure OpenAI API version")
    azure_deployment_name: str | None = Field(None, description="Azure deployment name")

    # AWS Bedrock Configuration
    aws_access_key_id: str | None = Field(None, description="AWS access key ID")
    aws_secret_access_key: str | None = Field(None, description="AWS secret access key")
    aws_region: str = Field("us-east-1", description="AWS region")
    bedrock_model_id: str | None = Field(None, description="Bedrock model ID")

    # OLLAMA Configuration
    ollama_base_url: str = Field("http://localhost:11434", description="OLLAMA base URL")
    ollama_model: str | None = Field(None, description="OLLAMA model name")

    # Anthropic Configuration
    anthropic_api_key: str | None = Field(None, description="Anthropic API key")

    # Agent Configuration
    max_iterations: int = Field(10, description="Maximum agent iterations")
    temperature: float = Field(0.7, description="Default temperature")
    streaming_enabled: bool = Field(True, description="Enable streaming responses")
    debug_mode: bool = Field(False, description="Enable debug logging")

    # Performance Configuration
    request_timeout: int = Field(30, description="Request timeout in seconds")
    max_tokens: int | None = Field(None, description="Maximum tokens per response")
    top_p: float | None = Field(None, description="Top-p sampling parameter")


# Tool Invocation Models
class ToolInvocationRequest(BaseModel):
    tool_id: str = Field(..., description="Tool to invoke")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class ToolInvocationResponse(BaseModel):
    tool_id: str = Field(..., description="Tool that was invoked")
    result: Any = Field(..., description="Tool execution result")
    execution_time: float | None = Field(None, description="Execution time in seconds")
    success: bool = Field(..., description="Whether execution was successful")
    error: str | None = Field(None, description="Error message if any")


# Streaming Models
class StreamChunk(BaseModel):
    id: str = Field(..., description="Stream identifier")
    object: str = Field("chat.completion.chunk", description="Object type")
    created: int = Field(..., description="Unix timestamp")
    model: str = Field(..., description="Model used")
    choices: list[dict[str, Any]] = Field(..., description="Stream choices")


# Error Models
class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error message")
    code: str | None = Field(None, description="Error code")
    details: dict[str, Any] | None = Field(None, description="Additional error details")


# JSON-RPC Models for A2A communication
class JSONRPCRequest(BaseModel):
    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    method: str = Field(..., description="Method to call")
    params: dict[str, Any] | None = Field(None, description="Method parameters")
    id: str | int | None = Field(None, description="Request identifier")


class JSONRPCResponse(BaseModel):
    jsonrpc: str = Field("2.0", description="JSON-RPC version")
    result: Any | None = Field(None, description="Method result")
    error: dict[str, Any] | None = Field(None, description="Error object")
    id: str | int | None = Field(None, description="Request identifier")
