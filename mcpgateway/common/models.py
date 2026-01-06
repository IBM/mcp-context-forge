# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/models.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Protocol Type Definitions.
This module defines all core MCP protocol types according to the specification.
It includes:
  - Message content types (text, image, resource)
  - Tool definitions and schemas
  - Resource types and templates
  - Prompt structures
  - Protocol initialization types
  - Sampling message types
  - Capability definitions

Examples:
    >>> from mcpgateway.common.models import Role, LogLevel, TextContent
    >>> Role.USER.value
    'user'
    >>> Role.ASSISTANT.value
    'assistant'
    >>> LogLevel.ERROR.value
    'error'
    >>> LogLevel.INFO.value
    'info'
    >>> content = TextContent(type='text', text='Hello')
    >>> content.text
    'Hello'
    >>> content.type
    'text'
"""

# Standard
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

# Third-Party
from pydantic import AnyHttpUrl, AnyUrl, BaseModel, ConfigDict, Field

# First-Party
from mcpgateway.utils.base_models import BaseModelWithConfigDict, to_camel_case


class Role(str, Enum):
    """Message role in conversations.

    Attributes:
        ASSISTANT (str): Indicates the assistant's role.
        USER (str): Indicates the user's role.

    Examples:
        >>> Role.USER.value
        'user'
        >>> Role.ASSISTANT.value
        'assistant'
        >>> Role.USER == 'user'
        True
        >>> list(Role)
        [<Role.ASSISTANT: 'assistant'>, <Role.USER: 'user'>]
    """

    ASSISTANT = "assistant"
    USER = "user"


class LogLevel(str, Enum):
    """Standard syslog severity levels as defined in RFC 5424.

    Attributes:
        DEBUG (str): Debug level.
        INFO (str): Informational level.
        NOTICE (str): Notice level.
        WARNING (str): Warning level.
        ERROR (str): Error level.
        CRITICAL (str): Critical level.
        ALERT (str): Alert level.
        EMERGENCY (str): Emergency level.
    """

    DEBUG = "debug"
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    ALERT = "alert"
    EMERGENCY = "emergency"


# MCP Protocol Annotations
class Annotations(BaseModel):
    """Optional annotations for client rendering hints (MCP spec-compliant).

    Attributes:
        audience (Optional[List[Role]]): Describes who the intended customer of this
                                        object or data is. Can include multiple entries
                                        (e.g., ["user", "assistant"]).
        priority (Optional[float]): Describes how important this data is for operating
                                   the server. 1 = most important (effectively required),
                                   0 = least important (entirely optional).
        last_modified (Optional[str]): ISO 8601 timestamp of last modification.
                                      Serialized as 'lastModified' in JSON.
    """

    audience: Optional[List[Role]] = None
    priority: Optional[float] = Field(None, ge=0, le=1)
    last_modified: Optional[str] = Field(None, alias="lastModified")

    model_config = ConfigDict(populate_by_name=True)


class ToolAnnotations(BaseModel):
    """Tool behavior hints for clients (MCP spec-compliant).

    Attributes:
        title (Optional[str]): Human-readable display name for the tool.
        read_only_hint (Optional[bool]): If true, tool does not modify its environment.
        destructive_hint (Optional[bool]): If true, tool may perform destructive updates.
                                          Only meaningful when read_only_hint == false.
        idempotent_hint (Optional[bool]): If true, calling repeatedly with same arguments
                                         has no additional effect. Only meaningful when
                                         read_only_hint == false.
        open_world_hint (Optional[bool]): If true, tool may interact with an "open world"
                                         of external entities (e.g., web search).
    """

    title: Optional[str] = None
    read_only_hint: Optional[bool] = Field(None, alias="readOnlyHint")
    destructive_hint: Optional[bool] = Field(None, alias="destructiveHint")
    idempotent_hint: Optional[bool] = Field(None, alias="idempotentHint")
    open_world_hint: Optional[bool] = Field(None, alias="openWorldHint")

    model_config = ConfigDict(populate_by_name=True)


# Base content types
class TextContent(BaseModelWithConfigDict):
    """Text content for messages (MCP spec-compliant).

    Attributes:
        type (Literal["text"]): The fixed content type identifier for text.
        text (str): The actual text message.
        annotations (Optional[Annotations]): Optional annotations for the client.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.

    Examples:
        >>> content = TextContent(type='text', text='Hello World')
        >>> content.text
        'Hello World'
        >>> content.type
        'text'
        >>> content.model_dump(exclude_none=True)
        {'type': 'text', 'text': 'Hello World'}
    """

    type: Literal["text"]
    text: str
    annotations: Optional[Annotations] = None
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


class ImageContent(BaseModelWithConfigDict):
    """Image content for messages (MCP spec-compliant).

    Attributes:
        type (Literal["image"]): The fixed content type identifier for images.
        data (str): Base64-encoded image data for JSON compatibility.
        mime_type (str): The MIME type (e.g. "image/png") of the image.
                        Will be serialized as 'mimeType' in JSON.
        annotations (Optional[Annotations]): Optional annotations for the client.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.
    """

    type: Literal["image"]
    data: str  # Base64-encoded string for JSON compatibility
    mime_type: str  # Will be converted to mimeType by alias_generator
    annotations: Optional[Annotations] = None
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


class AudioContent(BaseModelWithConfigDict):
    """Audio content for messages (MCP spec-compliant).

    Attributes:
        type (Literal["audio"]): The fixed content type identifier for audio.
        data (str): Base64-encoded audio data for JSON compatibility.
        mime_type (str): The MIME type of the audio (e.g., "audio/wav", "audio/mp3").
                        Different providers may support different audio types.
                        Will be serialized as 'mimeType' in JSON.
        annotations (Optional[Annotations]): Optional annotations for the client.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.
    """

    type: Literal["audio"]
    data: str  # Base64-encoded string for JSON compatibility
    mime_type: str  # Will be converted to mimeType by alias_generator
    annotations: Optional[Annotations] = None
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


class ResourceContents(BaseModelWithConfigDict):
    """Base class for resource contents (MCP spec-compliant).

    Attributes:
        uri (str): The URI of the resource.
        mime_type (Optional[str]): The MIME type of the resource, if known.
                                   Will be serialized as 'mimeType' in JSON.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.
    """

    uri: str
    mime_type: Optional[str] = Field(None, alias="mimeType")
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


class TextResourceContents(ResourceContents):
    """Text contents of a resource (MCP spec-compliant).

    Attributes:
        text (str): The textual content of the resource.
    """

    text: str


class BlobResourceContents(ResourceContents):
    """Binary contents of a resource (MCP spec-compliant).

    Attributes:
        blob (str): Base64-encoded binary data of the resource.
    """

    blob: str  # Base64-encoded binary data


# Legacy ResourceContent for backwards compatibility
class ResourceContent(BaseModel):
    """Resource content that can be embedded (LEGACY - use TextResourceContents or BlobResourceContents).

    This class is maintained for backwards compatibility but does not fully comply
    with the MCP spec. New code should use TextResourceContents or BlobResourceContents.

    Attributes:
        type (Literal["resource"]): The fixed content type identifier for resources.
        id (str): The ID identifying the resource.
        uri (str): The URI of the resource.
        mime_type (Optional[str]): The MIME type of the resource, if known.
        text (Optional[str]): A textual representation of the resource, if applicable.
        blob (Optional[bytes]): Binary data of the resource, if applicable.
    """

    type: Literal["resource"]
    id: str
    uri: str
    mime_type: Optional[str] = None
    text: Optional[str] = None
    blob: Optional[bytes] = None


ContentType = Union[TextContent, ImageContent, ResourceContent]


# Reference types - needed early for completion
class PromptReference(BaseModel):
    """Reference to a prompt or prompt template.

    Attributes:
        type (Literal["ref/prompt"]): The fixed reference type identifier for prompts.
        name (str): The unique name of the prompt.
    """

    type: Literal["ref/prompt"]
    name: str


class ResourceReference(BaseModel):
    """Reference to a resource or resource template.

    Attributes:
        type (Literal["ref/resource"]): The fixed reference type identifier for resources.
        uri (str): The URI of the resource.
    """

    type: Literal["ref/resource"]
    uri: str


# Completion types
class CompleteRequest(BaseModel):
    """Request for completion suggestions.

    Attributes:
        ref (Union[PromptReference, ResourceReference]): A reference to a prompt or resource.
        argument (Dict[str, str]): A dictionary containing arguments for the completion.
    """

    ref: Union[PromptReference, ResourceReference]
    argument: Dict[str, str]


class CompleteResult(BaseModel):
    """Result for a completion request.

    Attributes:
        completion (Dict[str, Any]): A dictionary containing the completion results.
    """

    completion: Dict[str, Any] = Field(..., description="Completion results")


# Implementation info
class Implementation(BaseModel):
    """MCP implementation information.

    Attributes:
        name (str): The name of the implementation.
        version (str): The version of the implementation.
    """

    name: str
    version: str


# Model preferences
class ModelHint(BaseModel):
    """Hint for model selection.

    Attributes:
        name (Optional[str]): An optional hint for the model name.
    """

    name: Optional[str] = None


class ModelPreferences(BaseModelWithConfigDict):
    """Server preferences for model selection.

    Uses BaseModelWithConfigDict for automatic snake_case → camelCase conversion.
    Fields serialize as: costPriority, speedPriority, intelligencePriority.

    Attributes:
        cost_priority (float): Priority for cost efficiency (0 to 1).
        speed_priority (float): Priority for speed (0 to 1).
        intelligence_priority (float): Priority for intelligence (0 to 1).
        hints (List[ModelHint]): A list of model hints.
    """

    cost_priority: float = Field(ge=0, le=1)
    speed_priority: float = Field(ge=0, le=1)
    intelligence_priority: float = Field(ge=0, le=1)
    hints: List[ModelHint] = []


# Capability types
class ClientCapabilities(BaseModel):
    """Capabilities that a client may support.

    Attributes:
        roots (Optional[Dict[str, bool]]): Capabilities related to root management.
        sampling (Optional[Dict[str, Any]]): Capabilities related to LLM sampling.
        elicitation (Optional[Dict[str, Any]]): Capabilities related to elicitation (MCP 2025-06-18).
        experimental (Optional[Dict[str, Dict[str, Any]]]): Experimental capabilities.
    """

    roots: Optional[Dict[str, bool]] = None
    sampling: Optional[Dict[str, Any]] = None
    elicitation: Optional[Dict[str, Any]] = None
    experimental: Optional[Dict[str, Dict[str, Any]]] = None


class ServerCapabilities(BaseModel):
    """Capabilities that a server may support.

    Attributes:
        prompts (Optional[Dict[str, bool]]): Capability for prompt support.
        resources (Optional[Dict[str, bool]]): Capability for resource support.
        tools (Optional[Dict[str, bool]]): Capability for tool support.
        logging (Optional[Dict[str, Any]]): Capability for logging support.
        completions (Optional[Dict[str, Any]]): Capability for completion support.
        experimental (Optional[Dict[str, Dict[str, Any]]]): Experimental capabilities.
    """

    prompts: Optional[Dict[str, bool]] = None
    resources: Optional[Dict[str, bool]] = None
    tools: Optional[Dict[str, bool]] = None
    logging: Optional[Dict[str, Any]] = None
    completions: Optional[Dict[str, Any]] = None
    experimental: Optional[Dict[str, Dict[str, Any]]] = None


# Initialization types
class InitializeRequest(BaseModel):
    """Initial request sent from the client to the server.

    Attributes:
        protocol_version (str): The protocol version (alias: protocolVersion).
        capabilities (ClientCapabilities): The client's capabilities.
        client_info (Implementation): The client's implementation information (alias: clientInfo).

    Note:
        The alias settings allow backward compatibility with older Pydantic versions.
    """

    protocol_version: str = Field(..., alias="protocolVersion")
    capabilities: ClientCapabilities
    client_info: Implementation = Field(..., alias="clientInfo")

    model_config = ConfigDict(
        populate_by_name=True,
    )


class InitializeResult(BaseModel):
    """Server's response to the initialization request.

    Attributes:
        protocol_version (str): The protocol version used.
        capabilities (ServerCapabilities): The server's capabilities.
        server_info (Implementation): The server's implementation information.
        instructions (Optional[str]): Optional instructions for the client.
    """

    protocol_version: str = Field(..., alias="protocolVersion")
    capabilities: ServerCapabilities = Field(..., alias="capabilities")
    server_info: Implementation = Field(..., alias="serverInfo")
    instructions: Optional[str] = Field(None, alias="instructions")

    model_config = ConfigDict(
        populate_by_name=True,
    )


# Message types
class Message(BaseModel):
    """A message in a conversation.

    Attributes:
        role (Role): The role of the message sender.
        content (ContentType): The content of the message.
    """

    role: Role
    content: ContentType


class SamplingMessage(BaseModel):
    """A message used in LLM sampling requests.

    Attributes:
        role (Role): The role of the sender.
        content (ContentType): The content of the sampling message.
    """

    role: Role
    content: ContentType


class PromptMessage(BaseModelWithConfigDict):
    """Message in a prompt (MCP spec-compliant).

    A PromptMessage is similar to SamplingMessage but can include additional
    content types like ResourceLink and EmbeddedResource.

    Attributes:
        role (Role): The role of the sender (user or assistant).
        content (ContentBlock): The content of the prompt message.
                                Supports text, images, audio, resource links, and embedded resources.

    Note:
        Per MCP spec, PromptMessage differs from SamplingMessage in that it can
        include ResourceLink and EmbeddedResource content types.
    """

    role: Role
    content: "ContentBlock"  # Uses ContentBlock union (includes ResourceLink and EmbeddedResource)


# Sampling types for the client features
class CreateMessageResult(BaseModelWithConfigDict):
    """Result from a sampling/createMessage request.

    Uses BaseModelWithConfigDict for automatic snake_case → camelCase conversion.
    The stop_reason field serializes as stopReason per MCP spec.

    Attributes:
        content (Union[TextContent, ImageContent]): The generated content.
        model (str): The model used for generating the content.
        role (Role): The role associated with the content.
        stop_reason (Optional[str]): An optional reason for why sampling stopped.
    """

    content: Union[TextContent, ImageContent]
    model: str
    role: Role
    stop_reason: Optional[str] = None


# Prompt types
class PromptArgument(BaseModelWithConfigDict):
    """An argument that can be passed to a prompt (MCP spec-compliant, extends BaseMetadata).

    Attributes:
        name (str): The name of the argument.
        title (Optional[str]): Human-readable title for the argument.
        description (Optional[str]): An optional description of the argument.
        required (bool): Whether the argument is required. Defaults to False.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.
    """

    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    required: bool = False
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


class Prompt(BaseModelWithConfigDict):
    """A prompt template offered by the server (MCP spec-compliant).

    Attributes:
        name (str): The unique name of the prompt.
        description (Optional[str]): A description of the prompt.
        arguments (List[PromptArgument]): A list of expected prompt arguments.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.
    """

    name: str
    description: Optional[str] = None
    arguments: List[PromptArgument] = []
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


class PromptResult(BaseModel):
    """Result of rendering a prompt template.

    Attributes:
        messages (List[Message]): The list of messages produced by rendering the prompt.
        description (Optional[str]): An optional description of the rendered result.
    """

    messages: List[Message]
    description: Optional[str] = None


class CommonAttributes(BaseModel):
    """Common attributes for tools and gateways.

    Attributes:
        name (str): The unique name of the tool.
        url (AnyHttpUrl): The URL of the tool.
        description (Optional[str]): A description of the tool.
        created_at (Optional[datetime]): The time at which the tool was created.
        update_at (Optional[datetime]): The time at which the tool was updated.
        enabled (Optional[bool]): If the tool is enabled.
        reachable (Optional[bool]): If the tool is currently reachable.
        tags (Optional[list[Dict[str,str]]]): A list of meta data tags describing the tool.
        created_by (Optional[str]): The person that created the tool.
        created_from_ip (Optional[str]): The client IP that created the tool.
        created_via (Optional[str]): How the tool was created (e.g., ui).
        created_user_agent (Optioanl[str]): The client user agent.
        modified_by (Optional[str]): The person that modified the tool.
        modified_from_ip (Optional[str]): The client IP that modified the tool.
        modified_via (Optional[str]): How the tool was modified (e.g., ui).
        modified_user_agent (Optioanl[str]): The client user agent.
        import_batch_id (Optional[str]): The id of the batch file that imported the tool.
        federation_source (Optional[str]): The federation source of the tool
        version (Optional[int]): The version of the tool.
        team_id (Optional[str]): The id of the team that created the tool.
        owner_email (Optional[str]): Tool owner's email.
        visibility (Optional[str]): Visibility of the tool (e.g., public, private).
    """

    name: str
    url: AnyHttpUrl
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    enabled: Optional[bool] = None
    reachable: Optional[bool] = None
    auth_type: Optional[str] = None
    tags: Optional[list[Dict[str, str]]] = None
    # Comprehensive metadata for audit tracking
    created_by: Optional[str] = None
    created_from_ip: Optional[str] = None
    created_via: Optional[str] = None
    created_user_agent: Optional[str] = None

    modified_by: Optional[str] = None
    modified_from_ip: Optional[str] = None
    modified_via: Optional[str] = None
    modified_user_agent: Optional[str] = None

    import_batch_id: Optional[str] = None
    federation_source: Optional[str] = None
    version: Optional[int] = None
    # Team scoping fields for resource organization
    team_id: Optional[str] = None
    owner_email: Optional[str] = None
    visibility: Optional[str] = None


# Tool types
class Tool(CommonAttributes):
    """A tool that can be invoked.

    Attributes:
        original_name (str): The original supplied name of the tool before imported by the gateway.
        integrationType (str): The integration type of the tool (e.g. MCP or REST).
        requestType (str): The HTTP method used to invoke the tool (GET, POST, PUT, DELETE, SSE, STDIO).
        headers (Dict[str, Any]): A JSON object representing HTTP headers.
        input_schema (Dict[str, Any]): A JSON Schema for validating the tool's input.
        output_schema (Optional[Dict[str, Any]]): A JSON Schema for validating the tool's output.
        annotations (Optional[Dict[str, Any]]): Tool annotations for behavior hints.
        auth_username (Optional[str]): The username for basic authentication.
        auth_password (Optional[str]): The password for basic authentication.
        auth_token (Optional[str]): The token for bearer authentication.
        jsonpath_filter (Optional[str]):  Filter the tool based on a JSON path expression.
        custom_name (Optional[str]): Custom tool name.
        custom_name_slug (Optional[str]): Alternative custom tool name.
        display_name (Optional[str]): Display name.
        gateway_id (Optional[str]): The gateway id on which the tool is hosted.
    """

    model_config = ConfigDict(from_attributes=True)
    original_name: Optional[str] = None
    integration_type: str = "MCP"
    request_type: str = "SSE"
    headers: Optional[Dict[str, Any]] = Field(default_factory=dict)
    input_schema: Dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    output_schema: Optional[Dict[str, Any]] = Field(default=None, description="JSON Schema for validating the tool's output")
    annotations: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Tool annotations for behavior hints")
    auth_username: Optional[str] = None
    auth_password: Optional[str] = None
    auth_token: Optional[str] = None
    jsonpath_filter: Optional[str] = None

    # custom_name,custom_name_slug, display_name
    custom_name: Optional[str] = None
    custom_name_slug: Optional[str] = None
    display_name: Optional[str] = None

    # Federation relationship with a local gateway
    gateway_id: Optional[str] = None


class CallToolResult(BaseModelWithConfigDict):
    """Result of a tool invocation (MCP spec-compliant).

    Attributes:
        content (List[ContentType]): A list of content items returned by the tool.
        is_error (bool): Flag indicating if the tool call resulted in an error.
                        Will be serialized as 'isError' in JSON.
        structured_content (Optional[Dict[str, Any]]): Optional structured JSON output.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.

    Note:
        This class uses BaseModelWithConfigDict which automatically converts
        is_error to isError in JSON output via the alias_generator.
    """

    content: List["ContentBlock"]  # Uses ContentBlock union for full MCP spec support
    is_error: Optional[bool] = Field(default=False, alias="isError")
    structured_content: Optional[Dict[str, Any]] = Field(None, alias="structuredContent")
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


# Legacy alias for backwards compatibility
ToolResult = CallToolResult


# Resource types
class Resource(BaseModelWithConfigDict):
    """A resource available from the server (MCP spec-compliant).

    Attributes:
        uri (str): The unique URI of the resource.
        name (str): The human-readable name of the resource.
        description (Optional[str]): A description of the resource.
        mime_type (Optional[str]): The MIME type of the resource.
                                   Will be serialized as 'mimeType' in JSON.
        size (Optional[int]): The size of the resource.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.
    """

    uri: str
    name: str
    description: Optional[str] = None
    mime_type: Optional[str] = None
    size: Optional[int] = None
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


class ResourceTemplate(BaseModelWithConfigDict):
    """A template for constructing resource URIs (MCP spec-compliant).

    Attributes:
        id (Optional[str]): Unique identifier for resource
        uri_template (str): The URI template string.
        name (str): The unique name of the template.
        description (Optional[str]): A description of the template.
        mime_type (Optional[str]): The MIME type associated with the template.
                                   Will be serialized as 'mimeType' in JSON.
        annotations (Optional[Annotations]): Optional annotations for client rendering hints.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.
    """

    # ✅ DB field name: uri_template
    # ✅ API (JSON) alias:
    id: Optional[str] = None
    uri_template: str = Field(..., alias="uriTemplate")
    name: str
    description: Optional[str] = None
    mime_type: Optional[str] = None
    annotations: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


class ResourceLink(Resource):
    """A resource link included in prompts or tool results (MCP spec-compliant).

    Note: Inherits uri, name, description, mime_type, size, meta from Resource.
          Per MCP spec, this extends Resource and adds a type discriminator.

    Attributes:
        type (Literal["resource_link"]): The fixed type identifier for resource links.
    """

    type: Literal["resource_link"] = "resource_link"


class EmbeddedResource(BaseModelWithConfigDict):
    """The contents of a resource, embedded into a prompt or tool call result (MCP spec-compliant).

    It is up to the client how best to render embedded resources for the benefit
    of the LLM and/or the user.

    Attributes:
        type (Literal["resource"]): The fixed type identifier for embedded resources.
        resource (Union[TextResourceContents, BlobResourceContents]): The resource contents.
        annotations (Optional[Annotations]): Optional annotations for the client.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.
    """

    type: Literal["resource"] = "resource"
    resource: Union[TextResourceContents, BlobResourceContents]
    annotations: Optional[Annotations] = None
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


# MCP spec-compliant ContentBlock union for prompts and tool results
# Per spec: ContentBlock can include ResourceLink and EmbeddedResource
ContentBlock = Union[TextContent, ImageContent, AudioContent, ResourceLink, EmbeddedResource]


class ListResourceTemplatesResult(BaseModel):
    """The server's response to a resources/templates/list request from the client.

    Attributes:
        meta (Optional[Dict[str, Any]]): Reserved property for metadata.
        next_cursor (Optional[str]): Pagination cursor for the next page of results.
        resource_templates (List[ResourceTemplate]): List of resource templates.
    """

    meta: Optional[Dict[str, Any]] = Field(
        None, alias="_meta", description="This result property is reserved by the protocol to allow clients and servers to attach additional metadata to their responses."
    )
    next_cursor: Optional[str] = Field(None, description="An opaque token representing the pagination position after the last returned result.\nIf present, there may be more results available.")
    resource_templates: List[ResourceTemplate] = Field(default_factory=list, description="List of resource templates available on the server")

    model_config = ConfigDict(
        populate_by_name=True,
    )


# Elicitation types (MCP 2025-06-18)
class ElicitationCapability(BaseModelWithConfigDict):
    """Client capability for elicitation operations (MCP 2025-06-18).

    Per MCP spec: Clients that support elicitation MUST declare this capability
    during initialization. Elicitation allows servers to request structured
    information from users through the client during interactive workflows.

    Example:
        {"capabilities": {"elicitation": {}}}
    """

    # Empty object per MCP spec, follows MCP SDK pattern
    model_config = ConfigDict(extra="allow")


class ElicitRequestParams(BaseModelWithConfigDict):
    """Parameters for elicitation/create requests (MCP spec-compliant).

    Elicitation requests allow servers to ask for user input with a structured
    schema. The schema is restricted to flat objects with primitive types only.

    Attributes:
        message: Human-readable message to present to user
        requestedSchema: JSON Schema defining expected response structure.
                        Per MCP spec, must be type 'object' with primitive properties only:
                        - string (optional format: email, uri, date, date-time)
                        - number/integer (optional min/max)
                        - boolean
                        - enum (string values)
                        No nested objects or arrays allowed.

    Example:
        {
            "message": "Please provide your contact information",
            "requestedSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Your full name"},
                    "email": {"type": "string", "format": "email"}
                },
                "required": ["name", "email"]
            }
        }
    """

    message: str
    requestedSchema: Dict[str, Any]  # JSON Schema (validated by ElicitationService)  # noqa: N815 (MCP spec requires camelCase)
    model_config = ConfigDict(extra="allow")


class ElicitResult(BaseModelWithConfigDict):
    """Client response to elicitation request (MCP spec three-action model).

    The MCP specification defines three distinct user actions to differentiate
    between explicit approval, explicit rejection, and dismissal without choice.

    Attributes:
        action: User's response action:
                - "accept": User explicitly approved and submitted data
                             (content field MUST be populated)
                - "decline": User explicitly declined the request
                             (content typically None/omitted)
                - "cancel": User dismissed without making an explicit choice
                            (content typically None/omitted)
        content: Submitted form data matching requestedSchema.
                Only present when action is "accept".
                Contains primitive values: str, int, float, bool, or None.

    Examples:
        Accept response:
            {"action": "accept", "content": {"name": "John", "email": "john@example.com"}}

        Decline response:
            {"action": "decline"}

        Cancel response:
            {"action": "cancel"}
    """

    action: Literal["accept", "decline", "cancel"]
    content: Optional[Dict[str, Union[str, int, float, bool, None]]] = None
    model_config = ConfigDict(extra="allow")


# Root types
class FileUrl(AnyUrl):
    """A specialized URL type for local file-scheme resources.

    Key characteristics
    -------------------
    * Scheme restricted - only the "file" scheme is permitted
      (e.g. file:///path/to/file.txt).
    * No host required - "file" URLs typically omit a network host;
      therefore, the host component is not mandatory.
    * String-friendly equality - developers naturally expect
      FileUrl("file:///data") == "file:///data" to evaluate True.
      AnyUrl (Pydantic) does not implement that, so we override
      __eq__ to compare against plain strings transparently.
      Hash semantics are kept consistent by delegating to the parent class.

    Examples
    --------
    >>> url = FileUrl("file:///etc/hosts")
    >>> url.scheme
    'file'
    >>> url == "file:///etc/hosts"
    True
    >>> {"path": url}  # hashable
    {'path': FileUrl('file:///etc/hosts')}

    Notes
    -----
    The override does not interfere with comparisons to other
    AnyUrl/FileUrl instances; those still use the superclass
    implementation.
    """

    # Restrict to the "file" scheme and omit host requirement
    allowed_schemes = {"file"}
    host_required = False

    def __eq__(self, other):  # type: ignore[override]
        """Return True when other is an equivalent URL or string.

        If other is a str it is coerced with str(self) for comparison;
        otherwise defer to AnyUrl's comparison.

        Args:
            other (Any): The object to compare against. May be a str, FileUrl, or AnyUrl.

        Returns:
            bool: True if the other value is equal to this URL, either as a string
            or as another URL object. False otherwise.
        """
        if isinstance(other, str):
            return str(self) == other
        return super().__eq__(other)

    # Keep hashing behaviour aligned with equality
    __hash__ = AnyUrl.__hash__


class Root(BaseModelWithConfigDict):
    """A root directory or file (MCP spec-compliant).

    Attributes:
        uri (Union[FileUrl, AnyUrl]): The unique identifier for the root.
        name (Optional[str]): An optional human-readable name.
        meta (Optional[Dict[str, Any]]): Optional metadata for protocol extension.
                                        Serialized as '_meta' in JSON.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
        use_enum_values=True,
        extra="ignore",
        json_schema_extra={"nullable": True},
    )

    uri: Union[FileUrl, AnyUrl] = Field(..., description="Unique identifier for the root")
    name: Optional[str] = Field(None, description="Optional human-readable name")
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta")


# Progress types
class ProgressToken(BaseModel):
    """Token for associating progress notifications.

    Attributes:
        value (Union[str, int]): The token value.
    """

    value: Union[str, int]


class Progress(BaseModel):
    """Progress update for long-running operations.

    Attributes:
        progress_token (ProgressToken): The token associated with the progress update.
        progress (float): The current progress value.
        total (Optional[float]): The total progress value, if known.
    """

    progress_token: ProgressToken
    progress: float
    total: Optional[float] = None


# JSON-RPC types
class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request.

    Attributes:
        jsonrpc (Literal["2.0"]): The JSON-RPC version.
        id (Optional[Union[str, int]]): The request identifier.
        method (str): The method name.
        params (Optional[Dict[str, Any]]): The parameters for the request.
    """

    jsonrpc: Literal["2.0"]
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 response.

    Attributes:
        jsonrpc (Literal["2.0"]): The JSON-RPC version.
        id (Optional[Union[str, int]]): The request identifier.
        result (Optional[Any]): The result of the request.
        error (Optional[Dict[str, Any]]): The error object if an error occurred.
    """

    jsonrpc: Literal["2.0"]
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error.

    Attributes:
        code (int): The error code.
        message (str): A short description of the error.
        data (Optional[Any]): Additional data about the error.
    """

    code: int
    message: str
    data: Optional[Any] = None


# Global configuration types
class GlobalConfig(BaseModel):
    """Global server configuration.

    Attributes:
        passthrough_headers (Optional[List[str]]): List of headers allowed to be passed through globally
    """

    passthrough_headers: Optional[List[str]] = Field(default=None, description="List of headers allowed to be passed through globally")


# Transport message types
class SSEEvent(BaseModel):
    """Server-Sent Events message.

    Attributes:
        id (Optional[str]): The event identifier.
        event (Optional[str]): The event type.
        data (str): The event data.
        retry (Optional[int]): The retry timeout in milliseconds.
    """

    id: Optional[str] = None
    event: Optional[str] = None
    data: str
    retry: Optional[int] = None


class WebSocketMessage(BaseModel):
    """WebSocket protocol message.

    Attributes:
        type (str): The type of the WebSocket message.
        data (Any): The message data.
    """

    type: str
    data: Any


# Notification types
class ResourceUpdateNotification(BaseModel):
    """Notification of resource changes.

    Attributes:
        method (Literal["notifications/resources/updated"]): The notification method.
        uri (str): The URI of the updated resource.
    """

    method: Literal["notifications/resources/updated"]
    uri: str


class ResourceListChangedNotification(BaseModel):
    """Notification of resource list changes.

    Attributes:
        method (Literal["notifications/resources/list_changed"]): The notification method.
    """

    method: Literal["notifications/resources/list_changed"]


class PromptListChangedNotification(BaseModel):
    """Notification of prompt list changes.

    Attributes:
        method (Literal["notifications/prompts/list_changed"]): The notification method.
    """

    method: Literal["notifications/prompts/list_changed"]


class ToolListChangedNotification(BaseModel):
    """Notification of tool list changes.

    Attributes:
        method (Literal["notifications/tools/list_changed"]): The notification method.
    """

    method: Literal["notifications/tools/list_changed"]


class CancelledNotification(BaseModel):
    """Notification of request cancellation.

    Attributes:
        method (Literal["notifications/cancelled"]): The notification method.
        request_id (Union[str, int]): The ID of the cancelled request.
        reason (Optional[str]): An optional reason for cancellation.
    """

    method: Literal["notifications/cancelled"]
    request_id: Union[str, int]
    reason: Optional[str] = None


class ProgressNotification(BaseModel):
    """Notification of operation progress.

    Attributes:
        method (Literal["notifications/progress"]): The notification method.
        progress_token (ProgressToken): The token associated with the progress.
        progress (float): The current progress value.
        total (Optional[float]): The total progress value, if known.
    """

    method: Literal["notifications/progress"]
    progress_token: ProgressToken
    progress: float
    total: Optional[float] = None


class LoggingNotification(BaseModel):
    """Notification of log messages.

    Attributes:
        method (Literal["notifications/message"]): The notification method.
        level (LogLevel): The log level of the message.
        logger (Optional[str]): The logger name.
        data (Any): The log message data.
    """

    method: Literal["notifications/message"]
    level: LogLevel
    logger: Optional[str] = None
    data: Any


# Federation types
class FederatedTool(Tool):
    """A tool from a federated gateway.

    Attributes:
        gateway_id (str): The identifier of the gateway.
        gateway_name (str): The name of the gateway.
    """

    gateway_id: str
    gateway_name: str


class FederatedResource(Resource):
    """A resource from a federated gateway.

    Attributes:
        gateway_id (str): The identifier of the gateway.
        gateway_name (str): The name of the gateway.
    """

    gateway_id: str
    gateway_name: str


class FederatedPrompt(Prompt):
    """A prompt from a federated gateway.

    Attributes:
        gateway_id (str): The identifier of the gateway.
        gateway_name (str): The name of the gateway.
    """

    gateway_id: str
    gateway_name: str


class Gateway(CommonAttributes):
    """A federated gateway peer.

    Attributes:
        id (str): The unique identifier for the gateway.
        name (str): The name of the gateway.
        url (AnyHttpUrl): The URL of the gateway.
        capabilities (ServerCapabilities): The capabilities of the gateway.
        last_seen (Optional[datetime]): Timestamp when the gateway was last seen.
    """

    model_config = ConfigDict(from_attributes=True)
    id: str
    capabilities: ServerCapabilities
    last_seen: Optional[datetime] = None
    slug: str
    transport: str
    last_seen: Optional[datetime]
    # Header passthrough configuration
    passthrough_headers: Optional[list[str]]  # Store list of strings as JSON array
    # Request type and authentication fields
    auth_value: Optional[str | dict]


# ===== RBAC Models =====


class RBACRole(BaseModel):
    """Role model for RBAC system.

    Represents roles that can be assigned to users with specific permissions.
    Supports global, team, and personal scopes with role inheritance.

    Attributes:
        id: Unique role identifier
        name: Human-readable role name
        description: Role description and purpose
        scope: Role scope ('global', 'team', 'personal')
        permissions: List of permission strings
        inherits_from: Parent role ID for inheritance
        created_by: Email of user who created the role
        is_system_role: Whether this is a system-defined role
        is_active: Whether the role is currently active
        created_at: Role creation timestamp
        updated_at: Role last modification timestamp

    Examples:
        >>> from datetime import datetime
        >>> role = RBACRole(
        ...     id="role-123",
        ...     name="team_admin",
        ...     description="Team administrator with member management rights",
        ...     scope="team",
        ...     permissions=["teams.manage_members", "resources.create"],
        ...     created_by="admin@example.com",
        ...     created_at=datetime(2023, 1, 1),
        ...     updated_at=datetime(2023, 1, 1)
        ... )
        >>> role.name
        'team_admin'
        >>> "teams.manage_members" in role.permissions
        True
    """

    id: str = Field(..., description="Unique role identifier")
    name: str = Field(..., description="Human-readable role name")
    description: Optional[str] = Field(None, description="Role description and purpose")
    scope: str = Field(..., description="Role scope", pattern="^(global|team|personal)$")
    permissions: List[str] = Field(..., description="List of permission strings")
    inherits_from: Optional[str] = Field(None, description="Parent role ID for inheritance")
    created_by: str = Field(..., description="Email of user who created the role")
    is_system_role: bool = Field(False, description="Whether this is a system-defined role")
    is_active: bool = Field(True, description="Whether the role is currently active")
    created_at: datetime = Field(..., description="Role creation timestamp")
    updated_at: datetime = Field(..., description="Role last modification timestamp")


class UserRoleAssignment(BaseModel):
    """User role assignment model.

    Represents the assignment of roles to users in specific scopes (global, team, personal).
    Includes metadata about who granted the role and when it expires.

    Attributes:
        id: Unique assignment identifier
        user_email: Email of the user assigned the role
        role_id: ID of the assigned role
        scope: Assignment scope ('global', 'team', 'personal')
        scope_id: Team ID if team-scoped, None otherwise
        granted_by: Email of user who granted this role
        granted_at: Timestamp when role was granted
        expires_at: Optional expiration timestamp
        is_active: Whether the assignment is currently active

    Examples:
        >>> from datetime import datetime
        >>> user_role = UserRoleAssignment(
        ...     id="assignment-123",
        ...     user_email="user@example.com",
        ...     role_id="team-admin-123",
        ...     scope="team",
        ...     scope_id="team-engineering-456",
        ...     granted_by="admin@example.com",
        ...     granted_at=datetime(2023, 1, 1)
        ... )
        >>> user_role.scope
        'team'
        >>> user_role.is_active
        True
    """

    id: str = Field(..., description="Unique assignment identifier")
    user_email: str = Field(..., description="Email of the user assigned the role")
    role_id: str = Field(..., description="ID of the assigned role")
    scope: str = Field(..., description="Assignment scope", pattern="^(global|team|personal)$")
    scope_id: Optional[str] = Field(None, description="Team ID if team-scoped, None otherwise")
    granted_by: str = Field(..., description="Email of user who granted this role")
    granted_at: datetime = Field(..., description="Timestamp when role was granted")
    expires_at: Optional[datetime] = Field(None, description="Optional expiration timestamp")
    is_active: bool = Field(True, description="Whether the assignment is currently active")


class PermissionAudit(BaseModel):
    """Permission audit log model.

    Records all permission checks for security auditing and compliance.
    Includes details about the user, permission, resource, and result.

    Attributes:
        id: Unique audit log entry identifier
        timestamp: When the permission check occurred
        user_email: Email of user being checked
        permission: Permission being checked (e.g., 'tools.create')
        resource_type: Type of resource (e.g., 'tools', 'teams')
        resource_id: Specific resource ID if applicable
        team_id: Team context if applicable
        granted: Whether permission was granted
        roles_checked: JSON of roles that were checked
        ip_address: IP address of the request
        user_agent: User agent string

    Examples:
        >>> from datetime import datetime
        >>> audit_log = PermissionAudit(
        ...     id=1,
        ...     timestamp=datetime(2023, 1, 1),
        ...     user_email="user@example.com",
        ...     permission="tools.create",
        ...     resource_type="tools",
        ...     granted=True,
        ...     roles_checked={"roles": ["team_admin"]}
        ... )
        >>> audit_log.granted
        True
        >>> audit_log.permission
        'tools.create'
    """

    id: int = Field(..., description="Unique audit log entry identifier")
    timestamp: datetime = Field(..., description="When the permission check occurred")
    user_email: Optional[str] = Field(None, description="Email of user being checked")
    permission: str = Field(..., description="Permission being checked")
    resource_type: Optional[str] = Field(None, description="Type of resource")
    resource_id: Optional[str] = Field(None, description="Specific resource ID if applicable")
    team_id: Optional[str] = Field(None, description="Team context if applicable")
    granted: bool = Field(..., description="Whether permission was granted")
    roles_checked: Optional[Dict] = Field(None, description="JSON of roles that were checked")
    ip_address: Optional[str] = Field(None, description="IP address of the request")
    user_agent: Optional[str] = Field(None, description="User agent string")


# Permission constants are imported from db.py to avoid duplication
# Use Permissions class from mcpgateway.db instead of duplicate SystemPermissions


class TransportType(str, Enum):
    """
    Enumeration of supported transport mechanisms for communication between components.

    Attributes:
        SSE (str): Server-Sent Events transport.
        HTTP (str): Standard HTTP-based transport.
        STDIO (str): Standard input/output transport.
        STREAMABLEHTTP (str): HTTP transport with streaming.
    """

    SSE = "SSE"
    HTTP = "HTTP"
    STDIO = "STDIO"
    STREAMABLEHTTP = "STREAMABLEHTTP"
