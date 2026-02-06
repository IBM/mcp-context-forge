# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/cdm/models.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unified LLM Message Format - Common Data Model.

A format-agnostic data model that abstracts over ChatML, Harmony, Google Gemini,
and Anthropic Claude message formats. Provides a unified representation for
security policy evaluation across different LLM providers and agentic frameworks.
"""

from enum import Enum
from typing import Any, Iterator, List, Literal, Optional, Union, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .view import MessageView


class Role(str, Enum):
    """Message role - who is speaking.

    Attributes:
        SYSTEM: System-level instructions or context.
        DEVELOPER: Developer-provided instructions (Harmony-specific, maps to system in others).
        USER: Human user input.
        ASSISTANT: LLM/agent response.
        TOOL: Tool execution result.

    Examples:
        >>> Role.USER.value
        'user'
        >>> Role.ASSISTANT == "assistant"
        True
    """

    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Channel(str, Enum):
    """Message channel - what kind of output (Harmony concept, inferred for others).

    Attributes:
        ANALYSIS: Internal reasoning/thinking (not shown to user).
        COMMENTARY: Tool call preambles, explanations.
        FINAL: User-facing output.

    Examples:
        >>> Channel.FINAL.value
        'final'
    """

    ANALYSIS = "analysis"
    COMMENTARY = "commentary"
    FINAL = "final"


class StopReason(str, Enum):
    """Why the model stopped generating.

    Attributes:
        END: Natural end of message.
        RETURN: Complete response (Harmony).
        CALL: Tool invocation.
        MAX_TOKENS: Hit token limit.
        STOP_SEQUENCE: Hit custom stop sequence.
    """

    END = "end"
    RETURN = "return"
    CALL = "call"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"


class ContentType(str, Enum):
    """Type of content part.

    Attributes:
        TEXT: Plain text content.
        IMAGE: Image content (URL or base64).
        THINKING: Normalized reasoning/chain-of-thought.
        TOOL_CALL: Tool/function invocation.
        TOOL_RESULT: Result from tool execution.
        RESOURCE: Embedded or referenced resource (MCP).
        PROMPT: Prompt template invocation (MCP).
        VIDEO: Video content.
        AUDIO: Audio content.
        DOCUMENT: Document content.
    """

    TEXT = "text"
    IMAGE = "image"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    RESOURCE = "resource"
    PROMPT = "prompt"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


class ResourceType(str, Enum):
    """Type of resource being referenced.

    Attributes:
        FILE: File on filesystem.
        BLOB: Binary blob (embedded).
        URI: Generic URI reference.
        DATABASE: Database record/query result.
        API: API response.
        MEMORY: Agent memory/context.
        ARTIFACT: Generated artifact (code, document, etc.).
    """

    FILE = "file"
    BLOB = "blob"
    URI = "uri"
    DATABASE = "database"
    API = "api"
    MEMORY = "memory"
    ARTIFACT = "artifact"


# =============================================================================
# Supporting Models
# =============================================================================


class ImageSource(BaseModel):
    """Source of an image.

    Attributes:
        type: Source type ("url" or "base64").
        data: URL or base64-encoded string.
        media_type: MIME type (e.g., "image/jpeg").

    Examples:
        >>> img = ImageSource(type="url", data="https://example.com/img.png")
        >>> img.type
        'url'
    """

    type: Literal["url", "base64"]
    data: str
    media_type: Optional[str] = None


class ToolCall(BaseModel):
    """Normalized tool/function call.

    Attributes:
        name: Tool name.
        arguments: Arguments as a JSON-serializable dict.
        id: Optional unique identifier for correlation with results.
        namespace: Optional namespace for namespaced tools (e.g., "functions").

    Examples:
        >>> tc = ToolCall(name="search", arguments={"query": "python"})
        >>> tc.name
        'search'
        >>> tc.arguments["query"]
        'python'
    """

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None
    namespace: Optional[str] = None


class ToolResult(BaseModel):
    """Result from a tool execution.

    Attributes:
        tool_call_id: ID of the corresponding ToolCall.
        tool_name: Name of the tool that was executed.
        content: Result content (typically string).
        is_error: Whether the result represents an error.

    Examples:
        >>> tr = ToolResult(tool_name="search", content="Found 10 results")
        >>> tr.is_error
        False
    """

    tool_call_id: Optional[str] = None
    tool_name: str = ""
    content: str = ""
    is_error: bool = False


class Resource(BaseModel):
    """A data resource that can be attached to or referenced by messages.

    Resources represent external data that provides context to a message,
    such as files being discussed, API responses, database records, or
    artifacts generated by the agent.

    In MCP terms, this maps to the Resource primitive.

    Attributes:
        uri: Unique identifier (URI format).
        name: Human-readable name.
        description: What this resource contains.
        resource_type: Type of resource.
        content: Text content (if embedded).
        blob: Binary content (if embedded).
        mime_type: MIME type of content.
        size_bytes: Size information.
        annotations: Metadata dict.
        version: For tracking changes.
        last_modified: ISO timestamp.

    Examples:
        >>> r = Resource(uri="file:///data.txt", name="Data File")
        >>> r.is_embedded()
        False
        >>> r2 = Resource(uri="file:///data.txt", content="Hello")
        >>> r2.is_embedded()
        True
    """

    uri: str
    name: Optional[str] = None
    description: Optional[str] = None
    resource_type: ResourceType = ResourceType.URI
    content: Optional[str] = None
    blob: Optional[bytes] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    annotations: dict[str, Any] = Field(default_factory=dict)
    version: Optional[str] = None
    last_modified: Optional[str] = None

    def is_embedded(self) -> bool:
        """Check if resource content is embedded vs referenced."""
        return self.content is not None or self.blob is not None

    def get_text_content(self) -> Optional[str]:
        """Get text content if available."""
        if self.content:
            return self.content
        if self.blob and self.mime_type and self.mime_type.startswith("text/"):
            return self.blob.decode("utf-8", errors="replace")
        return None


class ResourceReference(BaseModel):
    """A lightweight reference to a resource (without embedded content).

    Used when a message references a resource but doesn't need to
    include the full content inline.

    Attributes:
        uri: Resource URI.
        name: Human-readable name.
        resource_type: Type of resource.
        range_start: Line number or byte offset (for partial references).
        range_end: End of range.
        selector: CSS/XPath/JSONPath selector.

    Examples:
        >>> ref = ResourceReference(uri="file:///code.py", range_start=10, range_end=20)
        >>> ref.uri
        'file:///code.py'
    """

    uri: str
    name: Optional[str] = None
    resource_type: ResourceType = ResourceType.URI
    range_start: Optional[int] = None
    range_end: Optional[int] = None
    selector: Optional[str] = None


class PromptArgument(BaseModel):
    """Definition of a prompt template argument.

    Attributes:
        name: Argument name.
        description: What this argument is for.
        required: Whether the argument is required.
        default: Default value if not provided.
    """

    name: str
    description: Optional[str] = None
    required: bool = False
    default: Optional[Any] = None


class PromptRequest(BaseModel):
    """A request to invoke a prompt template.

    Similar to ToolCall, but produces messages rather than executing code.
    In MCP terms, this maps to prompts/get.

    Attributes:
        name: Prompt template name.
        arguments: Arguments to pass to the template.
        id: Request ID for correlation.
        server_id: Source of the prompt (for multi-server scenarios).

    Examples:
        >>> pr = PromptRequest(name="code_review", arguments={"code": "def foo(): pass"})
        >>> pr.name
        'code_review'
    """

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None
    server_id: Optional[str] = None


class PromptResult(BaseModel):
    """Result of rendering a prompt template.

    Contains the messages produced by the prompt, which can then
    be incorporated into the conversation.

    Attributes:
        prompt_request_id: ID of the corresponding PromptRequest.
        prompt_name: Name of the prompt that was rendered.
        messages: The rendered messages (prompts produce messages).
        content: Single text result for simple prompts.
        description: Description of what was rendered.
        is_error: Whether rendering succeeded.
        error_message: Error details if rendering failed.
    """

    prompt_request_id: Optional[str] = None
    prompt_name: str = ""
    messages: List["Message"] = Field(default_factory=list)
    content: Optional[str] = None
    description: Optional[str] = None
    is_error: bool = False
    error_message: Optional[str] = None


class TokenUsage(BaseModel):
    """Token usage information.

    Attributes:
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        thinking_tokens: Reasoning tokens (if separated).
        cached_tokens: Cached input tokens.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None


class MessageMetadata(BaseModel):
    """Additional metadata about a message.

    Attributes:
        stop_reason: Why the model stopped generating.
        tokens: Token usage information.
        raw_format: Original format ('chatml', 'harmony', 'gemini', 'anthropic').
        raw_data: Format-specific raw data (for debugging/lossless conversion).
    """

    stop_reason: Optional[StopReason] = None
    tokens: Optional[TokenUsage] = None
    raw_format: Optional[str] = None
    raw_data: Optional[dict[str, Any]] = None


# =============================================================================
# Content Part - The building block of multimodal messages
# =============================================================================


class ContentPart(BaseModel):
    """A single part of multimodal content.

    ContentPart is the fundamental unit for representing different types
    of content within a message. Each part has a type and the corresponding
    data for that type.

    Attributes:
        type: The type of content this part contains.
        text: Text content (for TEXT and THINKING types).
        image: Image source (for IMAGE type).
        tool_call: Tool invocation (for TOOL_CALL type).
        tool_result: Tool result (for TOOL_RESULT type).
        resource: Embedded resource (for RESOURCE type).
        resource_ref: Resource reference (for RESOURCE type).
        prompt_request: Prompt request (for PROMPT type).
        prompt_result: Prompt result (for PROMPT type).
        video: Video content data (for VIDEO type).
        audio: Audio content data (for AUDIO type).
        document: Document content data (for DOCUMENT type).

    Examples:
        >>> text_part = ContentPart(type=ContentType.TEXT, text="Hello")
        >>> text_part.text
        'Hello'
        >>> tool_part = ContentPart(
        ...     type=ContentType.TOOL_CALL,
        ...     tool_call=ToolCall(name="search", arguments={"q": "test"})
        ... )
        >>> tool_part.tool_call.name
        'search'
    """

    type: ContentType
    text: Optional[str] = None
    image: Optional[ImageSource] = None
    tool_call: Optional[ToolCall] = None
    tool_result: Optional[ToolResult] = None
    resource: Optional[Resource] = None
    resource_ref: Optional[ResourceReference] = None
    prompt_request: Optional[PromptRequest] = None
    prompt_result: Optional[PromptResult] = None
    video: Optional[dict[str, Any]] = None
    audio: Optional[dict[str, Any]] = None
    document: Optional[dict[str, Any]] = None


# =============================================================================
# Message - The core unified message format
# =============================================================================


class Message(BaseModel):
    """Universal message format that works across all LLM providers.

    Key design principles:
    1. Role identifies WHO is speaking
    2. Channel identifies WHAT KIND of output (explicit or inferred)
    3. Content can be simple string or multimodal parts
    4. All structured content (tools, resources, prompts) accessed via ContentPart
       with helper methods on Message for convenience

    Attributes:
        role: Who is speaking (user, assistant, system, etc.).
        content: Message content - either a string or list of ContentParts.
        channel: Type of output (analysis, commentary, final).
        headers: HTTP headers to send with this message (mutable by plugins).
        metadata: Additional message metadata.

    Examples:
        >>> msg = Message(role=Role.USER, content="Hello")
        >>> msg.get_text_content()
        'Hello'
        >>> msg.is_tool_call()
        False
        >>> msg.headers["Authorization"] = "Bearer token123"
    """

    role: Role
    content: Union[str, List[ContentPart]]
    channel: Optional[Channel] = None
    headers: dict[str, str] = Field(default_factory=dict)
    metadata: Optional[MessageMetadata] = None

    # =========================================================================
    # Text Content Extraction
    # =========================================================================

    def get_text_content(self) -> str:
        """Extract all text content from the message.

        Returns:
            Concatenated text content from all TEXT parts.
        """
        if isinstance(self.content, str):
            return self.content

        text_parts = []
        for part in self.content:
            if part.type == ContentType.TEXT and part.text:
                text_parts.append(part.text)
            elif part.type == ContentType.THINKING and part.text:
                text_parts.append(f"[THINKING: {part.text}]")

        return "\n".join(text_parts)

    def get_thinking_content(self) -> Optional[str]:
        """Extract thinking/reasoning content if present.

        Returns:
            Concatenated thinking content, or None if not present.
        """
        if isinstance(self.content, str):
            return None

        thinking_parts = [part.text for part in self.content if part.type == ContentType.THINKING and part.text]

        return "\n".join(thinking_parts) if thinking_parts else None

    # =========================================================================
    # Tool Helpers
    # =========================================================================

    def get_tool_calls(self) -> List[ToolCall]:
        """Extract all tool calls from content parts.

        Returns:
            List of ToolCall objects.
        """
        if isinstance(self.content, str):
            return []
        return [p.tool_call for p in self.content if p.type == ContentType.TOOL_CALL and p.tool_call is not None]

    def get_tool_results(self) -> List[ToolResult]:
        """Extract all tool results from content parts.

        Returns:
            List of ToolResult objects.
        """
        if isinstance(self.content, str):
            return []
        return [p.tool_result for p in self.content if p.type == ContentType.TOOL_RESULT and p.tool_result is not None]

    def is_tool_call(self) -> bool:
        """Check if this message contains tool calls.

        Returns:
            True if message contains at least one tool call.
        """
        return len(self.get_tool_calls()) > 0

    def is_tool_result(self) -> bool:
        """Check if this message contains tool results.

        Returns:
            True if message contains at least one tool result.
        """
        return len(self.get_tool_results()) > 0

    def get_tool_call_by_id(self, tool_id: str) -> Optional[ToolCall]:
        """Get a tool call by its ID.

        Args:
            tool_id: The tool call ID to find.

        Returns:
            The matching ToolCall, or None if not found.
        """
        for tc in self.get_tool_calls():
            if tc.id == tool_id:
                return tc
        return None

    # =========================================================================
    # Resource Helpers
    # =========================================================================

    def get_resources(self) -> List[Resource]:
        """Extract all embedded resources from content parts.

        Returns:
            List of Resource objects.
        """
        if isinstance(self.content, str):
            return []
        return [p.resource for p in self.content if p.type == ContentType.RESOURCE and p.resource is not None]

    def get_resource_refs(self) -> List[ResourceReference]:
        """Extract all resource references from content parts.

        Returns:
            List of ResourceReference objects.
        """
        if isinstance(self.content, str):
            return []
        return [p.resource_ref for p in self.content if p.type == ContentType.RESOURCE and p.resource_ref is not None]

    def get_all_resource_uris(self) -> List[str]:
        """Get all resource URIs (both embedded and referenced).

        Returns:
            List of URI strings.
        """
        uris = [r.uri for r in self.get_resources()]
        uris.extend(r.uri for r in self.get_resource_refs())
        return uris

    def get_resource_by_uri(self, uri: str) -> Optional[Resource]:
        """Get an embedded resource by URI.

        Args:
            uri: The resource URI to find.

        Returns:
            The matching Resource, or None if not found.
        """
        for resource in self.get_resources():
            if resource.uri == uri:
                return resource
        return None

    def has_resources(self) -> bool:
        """Check if this message has any attached resources.

        Returns:
            True if message contains resources.
        """
        if isinstance(self.content, str):
            return False
        return any(p.type == ContentType.RESOURCE for p in self.content)

    # =========================================================================
    # Prompt Helpers
    # =========================================================================

    def get_prompt_requests(self) -> List[PromptRequest]:
        """Extract all prompt requests from content parts.

        Returns:
            List of PromptRequest objects.
        """
        if isinstance(self.content, str):
            return []
        return [p.prompt_request for p in self.content if p.type == ContentType.PROMPT and p.prompt_request is not None]

    def get_prompt_results(self) -> List[PromptResult]:
        """Extract all prompt results from content parts.

        Returns:
            List of PromptResult objects.
        """
        if isinstance(self.content, str):
            return []
        return [p.prompt_result for p in self.content if p.type == ContentType.PROMPT and p.prompt_result is not None]

    def is_prompt_request(self) -> bool:
        """Check if this message contains prompt requests.

        Returns:
            True if message contains at least one prompt request.
        """
        return len(self.get_prompt_requests()) > 0

    def is_prompt_result(self) -> bool:
        """Check if this message contains prompt results.

        Returns:
            True if message contains at least one prompt result.
        """
        return len(self.get_prompt_results()) > 0

    # =========================================================================
    # Policy/Security Evaluation
    # =========================================================================

    def iter_message_views(self, ctx: Optional[Any] = None) -> "Iterator[MessageView]":
        """Iterate over message components as MessageViews.

        Memory-efficient: yields one view at a time without copying data.
        Each view provides a uniform interface for policy evaluation.

        Args:
            ctx: Optional EvaluationContext passed to each view.

        Yields:
            MessageView for each component in the message.

        Example:
            >>> for view in message.iter_message_views():
            ...     if view.kind == ViewKind.TOOL_CALL:
            ...         if "dangerous" in view.uri:
            ...             deny()
        """
        from .view import iter_message_views

        return iter_message_views(self, ctx)

    def view(self, ctx: Optional[Any] = None) -> "List[MessageView]":
        """Get all message components as MessageViews.

        Convenience method that returns a list of all MessageViews
        for this message. Useful for policy evaluation when you need
        to inspect all components.

        Args:
            ctx: Optional EvaluationContext passed to each view.

        Returns:
            List of MessageView objects for each component.

        Example:
            >>> views = message.view()
            >>> tool_calls = [v for v in views if v.kind == ViewKind.TOOL_CALL]
            >>> for tc in tool_calls:
            ...     print(f"Tool: {tc.name}")
        """
        return list(self.iter_message_views(ctx))

    def to_opa_input(
        self,
        ctx: Optional[Any] = None,
        include_content: bool = True,
    ) -> dict[str, Any]:
        """Serialize message to OPA-compatible input format.

        Converts the message and all its views to a JSON structure
        suitable for sending to an OPA policy server.

        Args:
            ctx: Optional context for principal/environment info.
            include_content: Include text content in output.

        Returns:
            Dict in format: {"input": {"message": {...}, "views": [...]}}

        Example:
            >>> opa_input = message.to_opa_input(context)
            >>> response = httpx.post(
            ...     "http://localhost:8181/v1/data/policy/allow",
            ...     json=opa_input
            ... )
        """
        views = self.view(ctx)
        return {
            "input": {
                "message": {
                    "role": self.role.value,
                    "channel": self.channel.value if self.channel else None,
                    "has_tool_calls": self.is_tool_call(),
                    "has_resources": self.has_resources(),
                    "text_content": self.get_text_content() if include_content else None,
                },
                "views": [v.to_dict(include_content=include_content) for v in views],
            }
        }


# =============================================================================
# Conversation - A sequence of messages
# =============================================================================


class Conversation(BaseModel):
    """A conversation consisting of multiple messages.

    Attributes:
        messages: List of messages in the conversation.
        metadata: Additional conversation metadata.

    Examples:
        >>> conv = Conversation()
        >>> conv.add_message(Message(role=Role.USER, content="Hello"))
        >>> len(conv.messages)
        1
    """

    messages: List[Message] = Field(default_factory=list)
    metadata: Optional[dict[str, Any]] = None

    def add_message(self, message: Message) -> None:
        """Add a message to the conversation.

        Args:
            message: The message to add.
        """
        self.messages.append(message)

    def get_messages_by_role(self, role: Role) -> List[Message]:
        """Get all messages with a specific role.

        Args:
            role: The role to filter by.

        Returns:
            List of messages with the specified role.
        """
        return [m for m in self.messages if m.role == role]

    def get_messages_by_channel(self, channel: Channel) -> List[Message]:
        """Get all messages with a specific channel.

        Args:
            channel: The channel to filter by.

        Returns:
            List of messages with the specified channel.
        """
        return [m for m in self.messages if m.channel == channel]

    def get_user_facing_messages(self) -> List[Message]:
        """Get only messages intended for user display.

        Returns:
            List of user-facing messages (FINAL channel or USER role).
        """
        return [m for m in self.messages if m.channel in (Channel.FINAL, None) or m.role == Role.USER]

    def get_thinking_messages(self) -> List[Message]:
        """Get only thinking/reasoning messages.

        Returns:
            List of messages with ANALYSIS channel.
        """
        return [m for m in self.messages if m.channel == Channel.ANALYSIS]


# =============================================================================
# Output Constraints
# =============================================================================


class OutputConstraint(BaseModel):
    """Constraint on model output format (e.g., JSON schema).

    Attributes:
        type: Constraint type ("json", "text", or "enum").
        json_schema: JSON schema for "json" type.
        enum_values: Allowed values for "enum" type.
        implementation_hints: Format-specific implementation hints.

    Examples:
        >>> constraint = OutputConstraint(type="json", json_schema={"type": "object"})
        >>> constraint.type
        'json'
    """

    type: Literal["json", "text", "enum"]
    json_schema: Optional[dict[str, Any]] = None
    enum_values: Optional[List[str]] = None
    implementation_hints: dict[str, Any] = Field(default_factory=dict)


# Update forward references
PromptResult.model_rebuild()
Message.model_rebuild()
