# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/schemas.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway Schema Definitions.
This module provides Pydantic models for request/response validation in the MCP Gateway.
It implements schemas for:
- Tool registration and invocation
- Resource management and subscriptions
- Prompt templates and arguments
- Gateway federation
- RPC message formats
- Event messages
- Admin interface

The schemas ensure proper validation according to the MCP specification while adding
gateway-specific extensions for federation support.
"""

# Standard
import base64
from datetime import datetime, timezone
from enum import Enum
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Pattern, Self, Union
from urllib.parse import urlparse

# Third-Party
import orjson
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator, model_validator, ValidationInfo

# First-Party
from mcpgateway.common.models import Annotations, ImageContent
from mcpgateway.common.models import Prompt as MCPPrompt
from mcpgateway.common.models import Resource as MCPResource
from mcpgateway.common.models import ResourceContent, TextContent
from mcpgateway.common.models import Tool as MCPTool
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.utils.base_models import BaseModelWithConfigDict
from mcpgateway.utils.services_auth import decode_auth, encode_auth
from mcpgateway.validation.tags import validate_tags_field

logger = logging.getLogger(__name__)

# ============================================================================
# Precompiled regex patterns (compiled once at module load for performance)
# ============================================================================
# Note: Only truly static patterns are precompiled here. Settings-based patterns
# (e.g., from settings.* or SecurityValidator.*) are NOT precompiled because tests
# override class/settings attributes at runtime via monkeypatch.
_HOSTNAME_RE: Pattern[str] = re.compile(r"^(https?://)?([a-zA-Z0-9.-]+)(:[0-9]+)?$")
_SLUG_RE: Pattern[str] = re.compile(r"^[a-z0-9-]+$")


def encode_datetime(v: datetime) -> str:
    """
    Convert a datetime object to an ISO 8601 formatted string.

    Args:
        v (datetime): The datetime object to be encoded.

    Returns:
        str: The ISO 8601 formatted string representation of the datetime object.

    Examples:
        >>> from datetime import datetime, timezone
        >>> encode_datetime(datetime(2023, 5, 22, 14, 30, 0))
        '2023-05-22T14:30:00'
        >>> encode_datetime(datetime(2024, 12, 25, 9, 15, 30))
        '2024-12-25T09:15:30'
        >>> encode_datetime(datetime(2025, 1, 1, 0, 0, 0))
        '2025-01-01T00:00:00'
        >>> # Test with timezone
        >>> dt_utc = datetime(2023, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        >>> encode_datetime(dt_utc)
        '2023-06-15T12:00:00+00:00'
        >>> # Test microseconds
        >>> dt_micro = datetime(2023, 7, 20, 16, 45, 30, 123456)
        >>> encode_datetime(dt_micro)
        '2023-07-20T16:45:30.123456'
    """
    return v.isoformat()


# --- Metrics Schemas ---


class ToolMetrics(BaseModelWithConfigDict):
    """
    Represents the performance and execution statistics for a tool.

    Attributes:
        total_executions (int): Total number of tool invocations.
        successful_executions (int): Number of successful tool invocations.
        failed_executions (int): Number of failed tool invocations.
        failure_rate (float): Failure rate (failed invocations / total invocations).
        min_response_time (Optional[float]): Minimum response time in seconds.
        max_response_time (Optional[float]): Maximum response time in seconds.
        avg_response_time (Optional[float]): Average response time in seconds.
        last_execution_time (Optional[datetime]): Timestamp of the most recent invocation.

    Examples:
        >>> from datetime import datetime
        >>> metrics = ToolMetrics(
        ...     total_executions=100,
        ...     successful_executions=95,
        ...     failed_executions=5,
        ...     failure_rate=0.05,
        ...     min_response_time=0.1,
        ...     max_response_time=2.5,
        ...     avg_response_time=0.8
        ... )
        >>> metrics.total_executions
        100
        >>> metrics.failure_rate
        0.05
        >>> metrics.successful_executions + metrics.failed_executions == metrics.total_executions
        True
        >>> # Test with minimal data
        >>> minimal_metrics = ToolMetrics(
        ...     total_executions=10,
        ...     successful_executions=8,
        ...     failed_executions=2,
        ...     failure_rate=0.2
        ... )
        >>> minimal_metrics.min_response_time is None
        True
        >>> # Test model dump functionality
        >>> data = metrics.model_dump()
        >>> isinstance(data, dict)
        True
        >>> data['total_executions']
        100
    """

    total_executions: int = Field(..., description="Total number of tool invocations")
    successful_executions: int = Field(..., description="Number of successful tool invocations")
    failed_executions: int = Field(..., description="Number of failed tool invocations")
    failure_rate: float = Field(..., description="Failure rate (failed invocations / total invocations)")
    min_response_time: Optional[float] = Field(None, description="Minimum response time in seconds")
    max_response_time: Optional[float] = Field(None, description="Maximum response time in seconds")
    avg_response_time: Optional[float] = Field(None, description="Average response time in seconds")
    last_execution_time: Optional[datetime] = Field(None, description="Timestamp of the most recent invocation")


class ResourceMetrics(BaseModelWithConfigDict):
    """
    Represents the performance and execution statistics for a resource.

    Attributes:
        total_executions (int): Total number of resource invocations.
        successful_executions (int): Number of successful resource invocations.
        failed_executions (int): Number of failed resource invocations.
        failure_rate (float): Failure rate (failed invocations / total invocations).
        min_response_time (Optional[float]): Minimum response time in seconds.
        max_response_time (Optional[float]): Maximum response time in seconds.
        avg_response_time (Optional[float]): Average response time in seconds.
        last_execution_time (Optional[datetime]): Timestamp of the most recent invocation.
    """

    total_executions: int = Field(..., description="Total number of resource invocations")
    successful_executions: int = Field(..., description="Number of successful resource invocations")
    failed_executions: int = Field(..., description="Number of failed resource invocations")
    failure_rate: float = Field(..., description="Failure rate (failed invocations / total invocations)")
    min_response_time: Optional[float] = Field(None, description="Minimum response time in seconds")
    max_response_time: Optional[float] = Field(None, description="Maximum response time in seconds")
    avg_response_time: Optional[float] = Field(None, description="Average response time in seconds")
    last_execution_time: Optional[datetime] = Field(None, description="Timestamp of the most recent invocation")


class ServerMetrics(BaseModelWithConfigDict):
    """
    Represents the performance and execution statistics for a server.

    Attributes:
        total_executions (int): Total number of server invocations.
        successful_executions (int): Number of successful server invocations.
        failed_executions (int): Number of failed server invocations.
        failure_rate (float): Failure rate (failed invocations / total invocations).
        min_response_time (Optional[float]): Minimum response time in seconds.
        max_response_time (Optional[float]): Maximum response time in seconds.
        avg_response_time (Optional[float]): Average response time in seconds.
        last_execution_time (Optional[datetime]): Timestamp of the most recent invocation.
    """

    total_executions: int = Field(..., description="Total number of server invocations")
    successful_executions: int = Field(..., description="Number of successful server invocations")
    failed_executions: int = Field(..., description="Number of failed server invocations")
    failure_rate: float = Field(..., description="Failure rate (failed invocations / total invocations)")
    min_response_time: Optional[float] = Field(None, description="Minimum response time in seconds")
    max_response_time: Optional[float] = Field(None, description="Maximum response time in seconds")
    avg_response_time: Optional[float] = Field(None, description="Average response time in seconds")
    last_execution_time: Optional[datetime] = Field(None, description="Timestamp of the most recent invocation")


class PromptMetrics(BaseModelWithConfigDict):
    """
    Represents the performance and execution statistics for a prompt.

    Attributes:
        total_executions (int): Total number of prompt invocations.
        successful_executions (int): Number of successful prompt invocations.
        failed_executions (int): Number of failed prompt invocations.
        failure_rate (float): Failure rate (failed invocations / total invocations).
        min_response_time (Optional[float]): Minimum response time in seconds.
        max_response_time (Optional[float]): Maximum response time in seconds.
        avg_response_time (Optional[float]): Average response time in seconds.
        last_execution_time (Optional[datetime]): Timestamp of the most recent invocation.
    """

    total_executions: int = Field(..., description="Total number of prompt invocations")
    successful_executions: int = Field(..., description="Number of successful prompt invocations")
    failed_executions: int = Field(..., description="Number of failed prompt invocations")
    failure_rate: float = Field(..., description="Failure rate (failed invocations / total invocations)")
    min_response_time: Optional[float] = Field(None, description="Minimum response time in seconds")
    max_response_time: Optional[float] = Field(None, description="Maximum response time in seconds")
    avg_response_time: Optional[float] = Field(None, description="Average response time in seconds")
    last_execution_time: Optional[datetime] = Field(None, description="Timestamp of the most recent invocation")


class A2AAgentMetrics(BaseModelWithConfigDict):
    """
    Represents the performance and execution statistics for an A2A agent.

    Attributes:
        total_executions (int): Total number of agent interactions.
        successful_executions (int): Number of successful agent interactions.
        failed_executions (int): Number of failed agent interactions.
        failure_rate (float): Failure rate (failed interactions / total interactions).
        min_response_time (Optional[float]): Minimum response time in seconds.
        max_response_time (Optional[float]): Maximum response time in seconds.
        avg_response_time (Optional[float]): Average response time in seconds.
        last_execution_time (Optional[datetime]): Timestamp of the most recent interaction.
    """

    total_executions: int = Field(..., description="Total number of agent interactions")
    successful_executions: int = Field(..., description="Number of successful agent interactions")
    failed_executions: int = Field(..., description="Number of failed agent interactions")
    failure_rate: float = Field(..., description="Failure rate (failed interactions / total interactions)")
    min_response_time: Optional[float] = Field(None, description="Minimum response time in seconds")
    max_response_time: Optional[float] = Field(None, description="Maximum response time in seconds")
    avg_response_time: Optional[float] = Field(None, description="Average response time in seconds")
    last_execution_time: Optional[datetime] = Field(None, description="Timestamp of the most recent interaction")


# --- JSON Path API modifier Schema


class JsonPathModifier(BaseModelWithConfigDict):
    """Schema for JSONPath queries.

    Provides the structure for parsing JSONPath queries and optional mapping.
    """

    jsonpath: Optional[str] = Field(None, description="JSONPath expression for querying JSON data.")
    mapping: Optional[Dict[str, str]] = Field(None, description="Mapping of fields from original data to output.")


# --- Tool Schemas ---
# Authentication model
class AuthenticationValues(BaseModelWithConfigDict):
    """Schema for all Authentications.
    Provides the authentication values for different types of authentication.
    """

    auth_type: Optional[str] = Field(None, description="Type of authentication: basic, bearer, headers or None")
    auth_value: Optional[str] = Field(None, description="Encoded Authentication values")

    # Only For tool read and view tool
    username: Optional[str] = Field("", description="Username for basic authentication")
    password: Optional[str] = Field("", description="Password for basic authentication")
    token: Optional[str] = Field("", description="Bearer token for authentication")
    auth_header_key: Optional[str] = Field("", description="Key for custom headers authentication")
    auth_header_value: Optional[str] = Field("", description="Value for custom headers authentication")


class ToolCreate(BaseModel):
    """
    Represents the configuration for creating a tool with various attributes and settings.

    Attributes:
        model_config (ConfigDict): Configuration for the model.
        name (str): Unique name for the tool.
        url (Union[str, AnyHttpUrl]): Tool endpoint URL.
        description (Optional[str]): Tool description.
        integration_type (Literal["REST", "MCP"]): Tool integration type - REST for individual endpoints, MCP for gateway-discovered tools.
        request_type (Literal["GET", "POST", "PUT", "DELETE", "PATCH"]): HTTP method to be used for invoking the tool.
        headers (Optional[Dict[str, str]]): Additional headers to send when invoking the tool.
        input_schema (Optional[Dict[str, Any]]): JSON Schema for validating tool parameters. Alias 'inputSchema'.
        output_schema (Optional[Dict[str, Any]]): JSON Schema for validating tool output. Alias 'outputSchema'.
        annotations (Optional[Dict[str, Any]]): Tool annotations for behavior hints such as title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint.
        jsonpath_filter (Optional[str]): JSON modification filter.
        auth (Optional[AuthenticationValues]): Authentication credentials (Basic or Bearer Token or custom headers) if required.
        gateway_id (Optional[str]): ID of the gateway for the tool.
    """

    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)
    allow_auto: bool = False  # Internal flag to allow system-initiated A2A tool creation

    name: str = Field(..., description="Unique name for the tool")
    displayName: Optional[str] = Field(None, description="Display name for the tool (shown in UI)")  # noqa: N815
    url: Optional[Union[str, AnyHttpUrl]] = Field(None, description="Tool endpoint URL")
    description: Optional[str] = Field(None, description="Tool description")
    integration_type: Literal["REST", "MCP", "A2A"] = Field("REST", description="'REST' for individual endpoints, 'MCP' for gateway-discovered tools, 'A2A' for A2A agents")
    request_type: Literal["GET", "POST", "PUT", "DELETE", "PATCH", "SSE", "STDIO", "STREAMABLEHTTP"] = Field("SSE", description="HTTP method to be used for invoking the tool")
    headers: Optional[Dict[str, str]] = Field(None, description="Additional headers to send when invoking the tool")
    input_schema: Optional[Dict[str, Any]] = Field(default_factory=lambda: {"type": "object", "properties": {}}, description="JSON Schema for validating tool parameters", alias="inputSchema")
    output_schema: Optional[Dict[str, Any]] = Field(default=None, description="JSON Schema for validating tool output", alias="outputSchema")
    annotations: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Tool annotations for behavior hints (title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint)",
    )
    jsonpath_filter: Optional[str] = Field(default="", description="JSON modification filter")
    auth: Optional[AuthenticationValues] = Field(None, description="Authentication credentials (Basic or Bearer Token or custom headers) if required")
    gateway_id: Optional[str] = Field(None, description="id of gateway for the tool")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for categorizing the tool")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the tool owner")
    visibility: Optional[str] = Field(default="public", description="Visibility level (private, team, public)")

    # Passthrough REST fields
    base_url: Optional[str] = Field(None, description="Base URL for REST passthrough")
    path_template: Optional[str] = Field(None, description="Path template for REST passthrough")
    query_mapping: Optional[Dict[str, Any]] = Field(None, description="Query mapping for REST passthrough")
    header_mapping: Optional[Dict[str, Any]] = Field(None, description="Header mapping for REST passthrough")
    timeout_ms: Optional[int] = Field(default=None, description="Timeout in milliseconds for REST passthrough (20000 if integration_type='REST', else None)")
    expose_passthrough: Optional[bool] = Field(True, description="Expose passthrough endpoint for this tool")
    allowlist: Optional[List[str]] = Field(None, description="Allowed upstream hosts/schemes for passthrough")
    plugin_chain_pre: Optional[List[str]] = Field(None, description="Pre-plugin chain for passthrough")
    plugin_chain_post: Optional[List[str]] = Field(None, description="Post-plugin chain for passthrough")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings
        """
        return validate_tags_field(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure tool names follow MCP naming conventions

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When displayName contains unsafe content or exceeds length limits

        Examples:
            >>> from mcpgateway.schemas import ToolCreate
            >>> ToolCreate.validate_name('valid_tool')
            'valid_tool'
            >>> ToolCreate.validate_name('Invalid Tool!')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        return SecurityValidator.validate_tool_name(v)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate URL format and ensure safe display

        Args:
            v (Optional[str]): Value to validate

        Returns:
            Optional[str]: Value if validated as safe

        Raises:
            ValueError: When displayName contains unsafe content or exceeds length limits

        Examples:
            >>> from mcpgateway.schemas import ToolCreate
            >>> ToolCreate.validate_url('https://example.com')
            'https://example.com'
            >>> ToolCreate.validate_url('ftp://example.com')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if v is None:
            return v
        return SecurityValidator.validate_url(v, "Tool URL")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import ToolCreate
            >>> ToolCreate.validate_description('A safe description')
            'A safe description'
            >>> ToolCreate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = ToolCreate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v

        forbidden_patterns = ["&&", ";", "||", "$(", "`", "|", "> ", "< "]
        for pat in forbidden_patterns:
            if pat in v:
                raise ValueError(f"Description contains unsafe characters: '{pat}'")

        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("displayName")
    @classmethod
    def validate_display_name(cls, v: Optional[str]) -> Optional[str]:
        """Ensure display names display safely

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When displayName contains unsafe content or exceeds length limits

        Examples:
            >>> from mcpgateway.schemas import ToolCreate
            >>> ToolCreate.validate_display_name('My Custom Tool')
            'My Custom Tool'
            >>> ToolCreate.validate_display_name('<script>alert("xss")</script>')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_NAME_LENGTH:
            raise ValueError(f"Display name exceeds maximum length of {SecurityValidator.MAX_NAME_LENGTH}")
        return SecurityValidator.sanitize_display_text(v, "Display name")

    @field_validator("headers", "input_schema", "annotations")
    @classmethod
    def validate_json_fields(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate JSON structure depth

        Args:
            v (dict): Value to validate

        Returns:
            dict: Value if validated as safe

        Examples:
            >>> from mcpgateway.schemas import ToolCreate
            >>> ToolCreate.validate_json_fields({'a': 1})
            {'a': 1}
            >>> # Test depth within limit (11 levels, default limit is 30)
            >>> ToolCreate.validate_json_fields({'a': {'b': {'c': {'d': {'e': {'f': {'g': {'h': {'i': {'j': {'k': 1}}}}}}}}}}})
            {'a': {'b': {'c': {'d': {'e': {'f': {'g': {'h': {'i': {'j': {'k': 1}}}}}}}}}}}
            >>> # Test exceeding depth limit (31 levels)
            >>> deep_31 = {'1': {'2': {'3': {'4': {'5': {'6': {'7': {'8': {'9': {'10': {'11': {'12': {'13': {'14': {'15': {'16': {'17': {'18': {'19': {'20': {'21': {'22': {'23': {'24': {'25': {'26': {'27': {'28': {'29': {'30': {'31': 'too deep'}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}
            >>> ToolCreate.validate_json_fields(deep_31)
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        SecurityValidator.validate_json_depth(v)
        return v

    @field_validator("request_type")
    @classmethod
    def validate_request_type(cls, v: str, info: ValidationInfo) -> str:
        """Validate request type based on integration type (REST, MCP, A2A)

        Args:
            v (str): Value to validate
            info (ValidationInfo): Values used for validation

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from pydantic import ValidationInfo
            >>> # REST integration types with valid methods
            >>> info_rest = type('obj', (object,), {'data': {'integration_type': 'REST'}})
            >>> ToolCreate.validate_request_type('POST', info_rest)
            'POST'
            >>> ToolCreate.validate_request_type('GET', info_rest)
            'GET'
            >>> # MCP integration types with valid transports
            >>> info_mcp = type('obj', (object,), {'data': {'integration_type': 'MCP'}})
            >>> ToolCreate.validate_request_type('SSE', info_mcp)
            'SSE'
            >>> ToolCreate.validate_request_type('STDIO', info_mcp)
            'STDIO'
            >>> # A2A integration type with valid method
            >>> info_a2a = type('obj', (object,), {'data': {'integration_type': 'A2A'}})
            >>> ToolCreate.validate_request_type('POST', info_a2a)
            'POST'
            >>> # Invalid REST type
            >>> try:
            ...     ToolCreate.validate_request_type('SSE', info_rest)
            ... except ValueError as e:
            ...     "not allowed for REST" in str(e)
            True
            >>> # Invalid MCP type
            >>> try:
            ...     ToolCreate.validate_request_type('POST', info_mcp)
            ... except ValueError as e:
            ...     "not allowed for MCP" in str(e)
            True
            >>> # Invalid A2A type
            >>> try:
            ...     ToolCreate.validate_request_type('GET', info_a2a)
            ... except ValueError as e:
            ...     "not allowed for A2A" in str(e)
            True
            >>> # Invalid integration type
            >>> info_invalid = type('obj', (object,), {'data': {'integration_type': 'INVALID'}})
            >>> try:
            ...     ToolCreate.validate_request_type('GET', info_invalid)
            ... except ValueError as e:
            ...     "Unknown integration type" in str(e)
            True
        """

        integration_type = info.data.get("integration_type")

        if integration_type not in ["REST", "MCP", "A2A"]:
            raise ValueError(f"Unknown integration type: {integration_type}")

        if integration_type == "REST":
            allowed = ["GET", "POST", "PUT", "DELETE", "PATCH"]
            if v not in allowed:
                raise ValueError(f"Request type '{v}' not allowed for REST. Only {allowed} methods are accepted.")
        elif integration_type == "MCP":
            allowed = ["SSE", "STDIO", "STREAMABLEHTTP"]
            if v not in allowed:
                raise ValueError(f"Request type '{v}' not allowed for MCP. Only {allowed} transports are accepted.")
        elif integration_type == "A2A":
            allowed = ["POST"]
            if v not in allowed:
                raise ValueError(f"Request type '{v}' not allowed for A2A. Only {allowed} methods are accepted.")
        return v

    @model_validator(mode="before")
    @classmethod
    def assemble_auth(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Assemble authentication information from separate keys if provided.

        Looks for keys "auth_type", "auth_username", "auth_password", "auth_token", "auth_header_key" and "auth_header_value".
        Constructs the "auth" field as a dictionary suitable for BasicAuth or BearerTokenAuth or HeadersAuth.

        Args:
            values: Dict with authentication information

        Returns:
            Dict: Reformatedd values dict

        Examples:
            >>> # Test basic auth
            >>> values = {'auth_type': 'basic', 'auth_username': 'user', 'auth_password': 'pass'}
            >>> result = ToolCreate.assemble_auth(values)
            >>> 'auth' in result
            True
            >>> result['auth']['auth_type']
            'basic'

            >>> # Test bearer auth
            >>> values = {'auth_type': 'bearer', 'auth_token': 'mytoken'}
            >>> result = ToolCreate.assemble_auth(values)
            >>> result['auth']['auth_type']
            'bearer'

            >>> # Test authheaders
            >>> values = {'auth_type': 'authheaders', 'auth_header_key': 'X-API-Key', 'auth_header_value': 'secret'}
            >>> result = ToolCreate.assemble_auth(values)
            >>> result['auth']['auth_type']
            'authheaders'

            >>> # Test no auth type
            >>> values = {'name': 'test'}
            >>> result = ToolCreate.assemble_auth(values)
            >>> 'auth' in result
            False
        """
        logger.debug(
            "Assembling auth in ToolCreate with raw values",
            extra={
                "auth_type": values.get("auth_type"),
                "auth_username": values.get("auth_username"),
                "auth_password": values.get("auth_password"),
                "auth_token": values.get("auth_token"),
                "auth_header_key": values.get("auth_header_key"),
                "auth_header_value": values.get("auth_header_value"),
            },
        )

        auth_type = values.get("auth_type")
        if auth_type and auth_type.lower() != "one_time_auth":
            if auth_type.lower() == "basic":
                creds = base64.b64encode(f"{values.get('auth_username', '')}:{values.get('auth_password', '')}".encode("utf-8")).decode()
                encoded_auth = encode_auth({"Authorization": f"Basic {creds}"})
                values["auth"] = {"auth_type": "basic", "auth_value": encoded_auth}
            elif auth_type.lower() == "bearer":
                encoded_auth = encode_auth({"Authorization": f"Bearer {values.get('auth_token', '')}"})
                values["auth"] = {"auth_type": "bearer", "auth_value": encoded_auth}
            elif auth_type.lower() == "authheaders":
                header_key = values.get("auth_header_key", "")
                header_value = values.get("auth_header_value", "")
                if header_key and header_value:
                    encoded_auth = encode_auth({header_key: header_value})
                    values["auth"] = {"auth_type": "authheaders", "auth_value": encoded_auth}
                else:
                    # Don't encode empty headers - leave auth empty
                    values["auth"] = {"auth_type": "authheaders", "auth_value": None}
        return values

    @model_validator(mode="before")
    @classmethod
    def prevent_manual_mcp_creation(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prevent manual creation of MCP tools via API.

        MCP tools should only be created by the gateway service when discovering
        tools from MCP servers. Users should add MCP servers via the Gateways interface.

        Args:
            values: The input values

        Returns:
            Dict[str, Any]: The validated values

        Raises:
            ValueError: If attempting to manually create MCP integration type
        """
        integration_type = values.get("integration_type")
        allow_auto = values.get("allow_auto", False)
        if integration_type == "MCP":
            raise ValueError("Cannot manually create MCP tools. Add MCP servers via the Gateways interface - tools will be auto-discovered and registered with integration_type='MCP'.")
        if integration_type == "A2A" and not allow_auto:
            raise ValueError("Cannot manually create A2A tools. Add A2A agents via the A2A interface - tools will be auto-created when agents are associated with servers.")
        return values

    @model_validator(mode="before")
    @classmethod
    def enforce_passthrough_fields_for_rest(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enforce that passthrough REST fields are only set for integration_type 'REST'.
        If any passthrough field is set for non-REST, raise ValueError.

        Args:
            values (Dict[str, Any]): The input values to validate.

        Returns:
            Dict[str, Any]: The validated values.

        Raises:
            ValueError: If passthrough fields are set for non-REST integration_type.
        """
        passthrough_fields = ["base_url", "path_template", "query_mapping", "header_mapping", "timeout_ms", "expose_passthrough", "allowlist", "plugin_chain_pre", "plugin_chain_post"]
        integration_type = values.get("integration_type")
        if integration_type != "REST":
            for field in passthrough_fields:
                if field in values and values[field] not in (None, [], {}):
                    raise ValueError(f"Field '{field}' is only allowed for integration_type 'REST'.")
        return values

    @model_validator(mode="before")
    @classmethod
    def extract_base_url_and_path_template(cls, values: dict) -> dict:
        """
        Only for integration_type 'REST':
        If 'url' is provided, extract 'base_url' and 'path_template'.
        Ensures path_template starts with a single '/'.

        Args:
            values (dict): The input values to process.

        Returns:
            dict: The updated values with base_url and path_template if applicable.
        """
        integration_type = values.get("integration_type")
        if integration_type != "REST":
            # Only process for REST, skip for others
            return values
        url = values.get("url")
        if url:
            parsed = urlparse(str(url))
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            path_template = parsed.path
            # Ensure path_template starts with a single '/'
            if path_template:
                path_template = "/" + path_template.lstrip("/")
            if not values.get("base_url"):
                values["base_url"] = base_url
            if not values.get("path_template"):
                values["path_template"] = path_template
        return values

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v):
        """
        Validate that base_url is a valid URL with scheme and netloc.

        Args:
            v (str): The base_url value to validate.

        Returns:
            str: The validated base_url value.

        Raises:
            ValueError: If base_url is not a valid URL.
        """
        if v is None:
            return v
        parsed = urlparse(str(v))
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("base_url must be a valid URL with scheme and netloc")
        return v

    @field_validator("path_template")
    @classmethod
    def validate_path_template(cls, v):
        """
        Validate that path_template starts with '/'.

        Args:
            v (str): The path_template value to validate.

        Returns:
            str: The validated path_template value.

        Raises:
            ValueError: If path_template does not start with '/'.
        """
        if v and not str(v).startswith("/"):
            raise ValueError("path_template must start with '/'")
        return v

    @field_validator("timeout_ms")
    @classmethod
    def validate_timeout_ms(cls, v):
        """
        Validate that timeout_ms is a positive integer.

        Args:
            v (int): The timeout_ms value to validate.

        Returns:
            int: The validated timeout_ms value.

        Raises:
            ValueError: If timeout_ms is not a positive integer.
        """
        if v is not None and v <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        return v

    @field_validator("allowlist")
    @classmethod
    def validate_allowlist(cls, v):
        """
        Validate that allowlist is a list and each entry is a valid host or scheme string.

        Args:
            v (List[str]): The allowlist to validate.

        Returns:
            List[str]: The validated allowlist.

        Raises:
            ValueError: If allowlist is not a list or any entry is not a valid host/scheme string.
        """
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("allowlist must be a list of host/scheme strings")
        # Uses precompiled regex for hostname validation
        for host in v:
            if not isinstance(host, str):
                raise ValueError(f"Invalid type in allowlist: {host} (must be str)")
            if not _HOSTNAME_RE.match(host):
                raise ValueError(f"Invalid host/scheme in allowlist: {host}")
        return v

    @field_validator("plugin_chain_pre", "plugin_chain_post")
    @classmethod
    def validate_plugin_chain(cls, v):
        """
        Validate that each plugin in the chain is allowed.

        Args:
            v (List[str]): The plugin chain to validate.

        Returns:
            List[str]: The validated plugin chain.

        Raises:
            ValueError: If any plugin is not in the allowed set.
        """
        allowed_plugins = {"deny_filter", "rate_limit", "pii_filter", "response_shape", "regex_filter", "resource_filter"}
        if v is None:
            return v
        for plugin in v:
            if plugin not in allowed_plugins:
                raise ValueError(f"Unknown plugin: {plugin}")
        return v

    @model_validator(mode="after")
    def handle_timeout_ms_defaults(self):
        """Handle timeout_ms defaults based on integration_type and expose_passthrough.

        Returns:
            self: The validated model instance with timeout_ms potentially set to default.
        """
        # If timeout_ms is None and we have REST with passthrough, set default
        if self.timeout_ms is None and self.integration_type == "REST" and getattr(self, "expose_passthrough", True):
            self.timeout_ms = 20000
        return self


class ToolUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing tool.

    Similar to ToolCreate but all fields are optional to allow partial updates.
    """

    name: Optional[str] = Field(None, description="Unique name for the tool")
    displayName: Optional[str] = Field(None, description="Display name for the tool (shown in UI)")  # noqa: N815
    custom_name: Optional[str] = Field(None, description="Custom name for the tool")
    url: Optional[Union[str, AnyHttpUrl]] = Field(None, description="Tool endpoint URL")
    description: Optional[str] = Field(None, description="Tool description")
    integration_type: Optional[Literal["REST", "MCP", "A2A"]] = Field(None, description="Tool integration type")
    request_type: Optional[Literal["GET", "POST", "PUT", "DELETE", "PATCH"]] = Field(None, description="HTTP method to be used for invoking the tool")
    headers: Optional[Dict[str, str]] = Field(None, description="Additional headers to send when invoking the tool")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema for validating tool parameters")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema for validating tool output")
    annotations: Optional[Dict[str, Any]] = Field(None, description="Tool annotations for behavior hints")
    jsonpath_filter: Optional[str] = Field(None, description="JSON path filter for rpc tool calls")
    auth: Optional[AuthenticationValues] = Field(None, description="Authentication credentials (Basic or Bearer Token or custom headers) if required")
    gateway_id: Optional[str] = Field(None, description="id of gateway for the tool")
    tags: Optional[List[str]] = Field(None, description="Tags for categorizing the tool")
    visibility: Optional[str] = Field(default="public", description="Visibility level: private, team, or public")

    # Passthrough REST fields
    base_url: Optional[str] = Field(None, description="Base URL for REST passthrough")
    path_template: Optional[str] = Field(None, description="Path template for REST passthrough")
    query_mapping: Optional[Dict[str, Any]] = Field(None, description="Query mapping for REST passthrough")
    header_mapping: Optional[Dict[str, Any]] = Field(None, description="Header mapping for REST passthrough")
    timeout_ms: Optional[int] = Field(default=None, description="Timeout in milliseconds for REST passthrough (20000 if integration_type='REST', else None)")
    expose_passthrough: Optional[bool] = Field(True, description="Expose passthrough endpoint for this tool")
    allowlist: Optional[List[str]] = Field(None, description="Allowed upstream hosts/schemes for passthrough")
    plugin_chain_pre: Optional[List[str]] = Field(None, description="Pre-plugin chain for passthrough")
    plugin_chain_post: Optional[List[str]] = Field(None, description="Post-plugin chain for passthrough")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings or None if input is None
        """
        return validate_tags_field(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure tool names follow MCP naming conventions

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_tool_name(v)

    @field_validator("custom_name")
    @classmethod
    def validate_custom_name(cls, v: str) -> str:
        """Ensure custom tool names follow MCP naming conventions

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_tool_name(v)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate URL format and ensure safe display

        Args:
            v (Optional[str]): Value to validate

        Returns:
            Optional[str]: Value if validated as safe
        """
        if v is None:
            return v
        return SecurityValidator.validate_url(v, "Tool URL")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import ToolUpdate
            >>> ToolUpdate.validate_description('A safe description')
            'A safe description'
            >>> ToolUpdate.validate_description(None)  # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = ToolUpdate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("headers", "input_schema", "annotations")
    @classmethod
    def validate_json_fields(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate JSON structure depth

        Args:
            v (dict): Value to validate

        Returns:
            dict: Value if validated as safe
        """
        SecurityValidator.validate_json_depth(v)
        return v

    @field_validator("request_type")
    @classmethod
    def validate_request_type(cls, v: str, info: ValidationInfo) -> str:
        """Validate request type based on integration type

        Args:
            v (str): Value to validate
            info (ValidationInfo): Validation context with other field values

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """

        integration_type = info.data.get("integration_type", "REST")

        if integration_type == "REST":
            allowed = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        elif integration_type == "MCP":
            allowed = ["SSE", "STDIO", "STREAMABLEHTTP"]
        elif integration_type == "A2A":
            allowed = ["POST"]  # A2A agents typically use POST
        else:
            raise ValueError(f"Unknown integration type: {integration_type}")

        if v not in allowed:
            raise ValueError(f"Request type '{v}' not allowed for {integration_type} integration")
        return v

    @model_validator(mode="before")
    @classmethod
    def assemble_auth(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Assemble authentication information from separate keys if provided.

        Looks for keys "auth_type", "auth_username", "auth_password", "auth_token", "auth_header_key" and "auth_header_value".
        Constructs the "auth" field as a dictionary suitable for BasicAuth or BearerTokenAuth or HeadersAuth.

        Args:
            values: Dict with authentication information

        Returns:
            Dict: Reformatedd values dict
        """
        logger.debug(
            "Assembling auth in ToolCreate with raw values",
            extra={
                "auth_type": values.get("auth_type"),
                "auth_username": values.get("auth_username"),
                "auth_password": values.get("auth_password"),
                "auth_token": values.get("auth_token"),
                "auth_header_key": values.get("auth_header_key"),
                "auth_header_value": values.get("auth_header_value"),
            },
        )

        auth_type = values.get("auth_type")
        if auth_type and auth_type.lower() != "one_time_auth":
            if auth_type.lower() == "basic":
                creds = base64.b64encode(f"{values.get('auth_username', '')}:{values.get('auth_password', '')}".encode("utf-8")).decode()
                encoded_auth = encode_auth({"Authorization": f"Basic {creds}"})
                values["auth"] = {"auth_type": "basic", "auth_value": encoded_auth}
            elif auth_type.lower() == "bearer":
                encoded_auth = encode_auth({"Authorization": f"Bearer {values.get('auth_token', '')}"})
                values["auth"] = {"auth_type": "bearer", "auth_value": encoded_auth}
            elif auth_type.lower() == "authheaders":
                header_key = values.get("auth_header_key", "")
                header_value = values.get("auth_header_value", "")
                if header_key and header_value:
                    encoded_auth = encode_auth({header_key: header_value})
                    values["auth"] = {"auth_type": "authheaders", "auth_value": encoded_auth}
                else:
                    # Don't encode empty headers - leave auth empty
                    values["auth"] = {"auth_type": "authheaders", "auth_value": None}
        return values

    @field_validator("displayName")
    @classmethod
    def validate_display_name(cls, v: Optional[str]) -> Optional[str]:
        """Ensure display names display safely

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When displayName contains unsafe content or exceeds length limits

        Examples:
            >>> from mcpgateway.schemas import ToolUpdate
            >>> ToolUpdate.validate_display_name('My Custom Tool')
            'My Custom Tool'
            >>> ToolUpdate.validate_display_name('<script>alert("xss")</script>')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_NAME_LENGTH:
            raise ValueError(f"Display name exceeds maximum length of {SecurityValidator.MAX_NAME_LENGTH}")
        return SecurityValidator.sanitize_display_text(v, "Display name")

    @model_validator(mode="before")
    @classmethod
    def prevent_manual_mcp_update(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prevent updating tools to MCP integration type via API.

        MCP tools should only be managed by the gateway service. Users should not
        be able to change a REST tool to MCP type or vice versa manually.

        Args:
            values: The input values

        Returns:
            Dict[str, Any]: The validated values

        Raises:
            ValueError: If attempting to update to MCP integration type
        """
        integration_type = values.get("integration_type")
        if integration_type == "MCP":
            raise ValueError("Cannot update tools to MCP integration type. MCP tools are managed by the gateway service.")
        if integration_type == "A2A":
            raise ValueError("Cannot update tools to A2A integration type. A2A tools are managed by the A2A service.")
        return values

    @model_validator(mode="before")
    @classmethod
    def extract_base_url_and_path_template(cls, values: dict) -> dict:
        """
        If 'integration_type' is 'REST' and 'url' is provided, extract 'base_url' and 'path_template'.
        Ensures path_template starts with a single '/'.

        Args:
            values (dict): The input values to process.

        Returns:
            dict: The updated values with base_url and path_template if applicable.
        """
        integration_type = values.get("integration_type")
        url = values.get("url")
        if integration_type == "REST" and url:
            parsed = urlparse(str(url))
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            path_template = parsed.path
            # Ensure path_template starts with a single '/'
            if path_template and not path_template.startswith("/"):
                path_template = "/" + path_template.lstrip("/")
            elif path_template:
                path_template = "/" + path_template.lstrip("/")
            if not values.get("base_url"):
                values["base_url"] = base_url
            if not values.get("path_template"):
                values["path_template"] = path_template
        return values

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v):
        """
        Validate that base_url is a valid URL with scheme and netloc.

        Args:
            v (str): The base_url value to validate.

        Returns:
            str: The validated base_url value.

        Raises:
            ValueError: If base_url is not a valid URL.
        """
        if v is None:
            return v
        parsed = urlparse(str(v))
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("base_url must be a valid URL with scheme and netloc")
        return v

    @field_validator("path_template")
    @classmethod
    def validate_path_template(cls, v):
        """
        Validate that path_template starts with '/'.

        Args:
            v (str): The path_template value to validate.

        Returns:
            str: The validated path_template value.

        Raises:
            ValueError: If path_template does not start with '/'.
        """
        if v and not str(v).startswith("/"):
            raise ValueError("path_template must start with '/'")
        return v

    @field_validator("timeout_ms")
    @classmethod
    def validate_timeout_ms(cls, v):
        """
        Validate that timeout_ms is a positive integer.

        Args:
            v (int): The timeout_ms value to validate.

        Returns:
            int: The validated timeout_ms value.

        Raises:
            ValueError: If timeout_ms is not a positive integer.
        """
        if v is not None and v <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        return v

    @field_validator("allowlist")
    @classmethod
    def validate_allowlist(cls, v):
        """
        Validate that allowlist is a list and each entry is a valid host or scheme string.

        Args:
            v (List[str]): The allowlist to validate.

        Returns:
            List[str]: The validated allowlist.

        Raises:
            ValueError: If allowlist is not a list or any entry is not a valid host/scheme string.
        """
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("allowlist must be a list of host/scheme strings")
        # Uses precompiled regex for hostname validation
        for host in v:
            if not isinstance(host, str):
                raise ValueError(f"Invalid type in allowlist: {host} (must be str)")
            if not _HOSTNAME_RE.match(host):
                raise ValueError(f"Invalid host/scheme in allowlist: {host}")
        return v

    @field_validator("plugin_chain_pre", "plugin_chain_post")
    @classmethod
    def validate_plugin_chain(cls, v):
        """
        Validate that each plugin in the chain is allowed.

        Args:
            v (List[str]): The plugin chain to validate.

        Returns:
            List[str]: The validated plugin chain.

        Raises:
            ValueError: If any plugin is not in the allowed set.
        """
        allowed_plugins = {"deny_filter", "rate_limit", "pii_filter", "response_shape", "regex_filter", "resource_filter"}
        if v is None:
            return v
        for plugin in v:
            if plugin not in allowed_plugins:
                raise ValueError(f"Unknown plugin: {plugin}")
        return v


class ToolRead(BaseModelWithConfigDict):
    """Schema for reading tool information.

    Includes all tool fields plus:
    - Database ID
    - Creation/update timestamps
    - enabled: If Tool is enabled or disabled.
    - reachable: If Tool is reachable or not.
    - Gateway ID for federation
    - Execution count indicating the number of times the tool has been executed.
    - Metrics: Aggregated metrics for the tool invocations.
    - Request type and authentication settings.
    """

    id: str
    original_name: str
    url: Optional[str]
    description: Optional[str]
    request_type: str
    integration_type: str
    headers: Optional[Dict[str, str]]
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = Field(None)
    annotations: Optional[Dict[str, Any]]
    jsonpath_filter: Optional[str]
    auth: Optional[AuthenticationValues]
    created_at: datetime
    updated_at: datetime
    enabled: bool
    reachable: bool
    gateway_id: Optional[str]
    execution_count: Optional[int] = Field(None)
    metrics: Optional[ToolMetrics] = Field(None)
    name: str
    displayName: Optional[str] = Field(None, description="Display name for the tool (shown in UI)")  # noqa: N815
    gateway_slug: str
    custom_name: str
    custom_name_slug: str
    tags: List[Dict[str, str]] = Field(default_factory=list, description="Tags for categorizing the tool")

    # Comprehensive metadata for audit tracking
    created_by: Optional[str] = Field(None, description="Username who created this entity")
    created_from_ip: Optional[str] = Field(None, description="IP address of creator")
    created_via: Optional[str] = Field(None, description="Creation method: ui|api|import|federation")
    created_user_agent: Optional[str] = Field(None, description="User agent of creation request")

    modified_by: Optional[str] = Field(None, description="Username who last modified this entity")
    modified_from_ip: Optional[str] = Field(None, description="IP address of last modifier")
    modified_via: Optional[str] = Field(None, description="Modification method")
    modified_user_agent: Optional[str] = Field(None, description="User agent of modification request")

    import_batch_id: Optional[str] = Field(None, description="UUID of bulk import batch")
    federation_source: Optional[str] = Field(None, description="Source gateway for federated entities")
    version: Optional[int] = Field(1, description="Entity version for change tracking")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="ID of the team that owns this resource")
    team: Optional[str] = Field(None, description="Name of the team that owns this resource")
    owner_email: Optional[str] = Field(None, description="Email of the user who owns this resource")
    visibility: Optional[str] = Field(default="public", description="Visibility level: private, team, or public")

    # Passthrough REST fields
    base_url: Optional[str] = Field(None, description="Base URL for REST passthrough")
    path_template: Optional[str] = Field(None, description="Path template for REST passthrough")
    query_mapping: Optional[Dict[str, Any]] = Field(None, description="Query mapping for REST passthrough")
    header_mapping: Optional[Dict[str, Any]] = Field(None, description="Header mapping for REST passthrough")
    timeout_ms: Optional[int] = Field(20000, description="Timeout in milliseconds for REST passthrough")
    expose_passthrough: Optional[bool] = Field(True, description="Expose passthrough endpoint for this tool")
    allowlist: Optional[List[str]] = Field(None, description="Allowed upstream hosts/schemes for passthrough")
    plugin_chain_pre: Optional[List[str]] = Field(None, description="Pre-plugin chain for passthrough")
    plugin_chain_post: Optional[List[str]] = Field(None, description="Post-plugin chain for passthrough")

    # MCP protocol extension field
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta", description="Optional metadata for protocol extension")


class ToolInvocation(BaseModelWithConfigDict):
    """Schema for tool invocation requests.

    This schema validates tool invocation requests to ensure they follow MCP
    (Model Context Protocol) naming conventions and prevent security vulnerabilities
    such as XSS attacks or deeply nested payloads that could cause DoS.

    Captures:
    - Tool name to invoke (validated for safety and MCP compliance)
    - Arguments matching tool's input schema (validated for depth limits)

    Validation Rules:
    - Tool names must start with a letter and contain only letters, numbers,
      underscores, and hyphens
    - Tool names cannot contain HTML special characters (<, >, ", ', /)
    - Arguments are validated to prevent excessively deep nesting (default max: 10 levels)

    Attributes:
        name (str): Name of the tool to invoke. Must follow MCP naming conventions.
        arguments (Dict[str, Any]): Arguments to pass to the tool. Must match the
                                   tool's input schema and not exceed depth limits.

    Examples:
        >>> from pydantic import ValidationError
        >>> # Valid tool invocation
        >>> tool_inv = ToolInvocation(name="get_weather", arguments={"city": "London"})
        >>> tool_inv.name
        'get_weather'
        >>> tool_inv.arguments
        {'city': 'London'}

        >>> # Valid tool name with underscores and numbers
        >>> tool_inv = ToolInvocation(name="tool_v2_beta", arguments={})
        >>> tool_inv.name
        'tool_v2_beta'

        >>> # Invalid: Tool name with special characters
        >>> try:
        ...     ToolInvocation(name="tool-name!", arguments={})
        ... except ValidationError as e:
        ...     print("Validation failed: Special characters not allowed")
        Validation failed: Special characters not allowed

        >>> # Invalid: XSS attempt in tool name
        >>> try:
        ...     ToolInvocation(name="<script>alert('XSS')</script>", arguments={})
        ... except ValidationError as e:
        ...     print("Validation failed: HTML tags not allowed")
        Validation failed: HTML tags not allowed

        >>> # Invalid: Tool name starting with number
        >>> try:
        ...     ToolInvocation(name="123_tool", arguments={})
        ... except ValidationError as e:
        ...     print("Validation failed: Must start with letter")
        Validation failed: Must start with letter

        >>> # Valid: Complex but not too deep arguments
        >>> args = {"level1": {"level2": {"level3": {"data": "value"}}}}
        >>> tool_inv = ToolInvocation(name="process_data", arguments=args)
        >>> tool_inv.arguments["level1"]["level2"]["level3"]["data"]
        'value'

        >>> # Invalid: Arguments too deeply nested (>30 levels)
        >>> deep_args = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": {"l": {"m": {"n": {"o": {"p": {"q": {"r": {"s": {"t": {"u": {"v": {"w": {"x": {"y": {"z": {"aa": {"bb": {"cc": {"dd": {"ee": "too deep"}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}
        >>> try:
        ...     ToolInvocation(name="process_data", arguments=deep_args)
        ... except ValidationError as e:
        ...     print("Validation failed: Exceeds maximum depth")
        Validation failed: Exceeds maximum depth

        >>> # Edge case: Empty tool name
        >>> try:
        ...     ToolInvocation(name="", arguments={})
        ... except ValidationError as e:
        ...     print("Validation failed: Name cannot be empty")
        Validation failed: Name cannot be empty

        >>> # Valid: Tool name with hyphen (but not starting/ending)
        >>> tool_inv = ToolInvocation(name="get_user_info", arguments={"id": 123})
        >>> tool_inv.name
        'get_user_info'

        >>> # Arguments with various types
        >>> args = {
        ...     "string": "value",
        ...     "number": 42,
        ...     "boolean": True,
        ...     "array": [1, 2, 3],
        ...     "nested": {"key": "value"}
        ... }
        >>> tool_inv = ToolInvocation(name="complex_tool", arguments=args)
        >>> tool_inv.arguments["number"]
        42
    """

    name: str = Field(..., description="Name of tool to invoke")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments matching tool's input schema")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure tool names follow MCP naming conventions.

        Validates that the tool name:
        - Is not empty
        - Starts with a letter (not a number or special character)
        - Contains only letters, numbers, underscores, and hyphens
        - Does not contain HTML special characters that could cause XSS
        - Does not exceed maximum length (255 characters)

        Args:
            v (str): Tool name to validate

        Returns:
            str: The validated tool name if it passes all checks

        Raises:
            ValueError: If the tool name violates any validation rules
        """
        return SecurityValidator.validate_tool_name(v)

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate arguments structure depth to prevent DoS attacks.

        Ensures that the arguments dictionary doesn't have excessive nesting
        that could cause performance issues or stack overflow. The default
        maximum depth is 10 levels.

        Args:
            v (dict): Arguments dictionary to validate

        Returns:
            dict: The validated arguments if within depth limits

        Raises:
            ValueError: If the arguments exceed the maximum allowed depth
        """
        SecurityValidator.validate_json_depth(v)
        return v


class ToolResult(BaseModelWithConfigDict):
    """Schema for tool invocation results.

    Supports:
    - Multiple content types (text/image)
    - Error reporting
    - Optional error messages
    """

    content: List[Union[TextContent, ImageContent]]
    structured_content: Optional[Dict[str, Any]] = None
    is_error: bool = False
    error_message: Optional[str] = None


class ResourceCreate(BaseModel):
    """
    Schema for creating a new resource.

    Attributes:
        model_config (ConfigDict): Configuration for the model.
        uri (str): Unique URI for the resource.
        name (str): Human-readable name for the resource.
        description (Optional[str]): Optional description of the resource.
        mime_type (Optional[str]): Optional MIME type of the resource.
        template (Optional[str]): Optional URI template for parameterized resources.
        content (Union[str, bytes]): Content of the resource, which can be text or binary.
    """

    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    uri: str = Field(..., description="Unique URI for the resource")
    name: str = Field(..., description="Human-readable resource name")
    description: Optional[str] = Field(None, description="Resource description")
    mime_type: Optional[str] = Field(None, alias="mimeType", description="Resource MIME type")
    uri_template: Optional[str] = Field(None, description="URI template for parameterized resources")
    content: Union[str, bytes] = Field(..., description="Resource content (text or binary)")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for categorizing the resource")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the resource owner")
    visibility: Optional[str] = Field(default="public", description="Visibility level (private, team, public)")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings
        """
        return validate_tags_field(v)

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, v: str) -> str:
        """Validate URI format

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_uri(v, "Resource URI")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate resource name

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "Resource name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import ResourceCreate
            >>> ResourceCreate.validate_description('A safe description')
            'A safe description'
            >>> ResourceCreate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = ResourceCreate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate MIME type format

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        if v is None:
            return v
        return SecurityValidator.validate_mime_type(v)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: Optional[Union[str, bytes]]) -> Optional[Union[str, bytes]]:
        """Validate content size and safety

        Args:
            v (Union[str, bytes]): Value to validate

        Returns:
            Union[str, bytes]: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """
        if v is None:
            return v

        if len(v) > SecurityValidator.MAX_CONTENT_LENGTH:
            raise ValueError(f"Content exceeds maximum length of {SecurityValidator.MAX_CONTENT_LENGTH}")

        if isinstance(v, bytes):
            try:
                text = v.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("Content must be UTF-8 decodable")
        else:
            text = v
        # Runtime pattern matching (not precompiled to allow test monkeypatching)
        if re.search(SecurityValidator.DANGEROUS_HTML_PATTERN, text, re.IGNORECASE):
            raise ValueError("Content contains HTML tags that may cause display issues")

        return v


class ResourceUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing resource.

    Similar to ResourceCreate but URI is not required and all fields are optional.
    """

    uri: Optional[str] = Field(None, description="Unique URI for the resource")
    name: Optional[str] = Field(None, description="Human-readable resource name")
    description: Optional[str] = Field(None, description="Resource description")
    mime_type: Optional[str] = Field(None, description="Resource MIME type")
    uri_template: Optional[str] = Field(None, description="URI template for parameterized resources")
    content: Optional[Union[str, bytes]] = Field(None, description="Resource content (text or binary)")
    tags: Optional[List[str]] = Field(None, description="Tags for categorizing the resource")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the resource owner")
    visibility: Optional[str] = Field(None, description="Visibility level (private, team, public)")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings or None if input is None
        """
        return validate_tags_field(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate resource name

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "Resource name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import ResourceUpdate
            >>> ResourceUpdate.validate_description('A safe description')
            'A safe description'
            >>> ResourceUpdate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = ResourceUpdate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate MIME type format

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        if v is None:
            return v
        return SecurityValidator.validate_mime_type(v)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: Optional[Union[str, bytes]]) -> Optional[Union[str, bytes]]:
        """Validate content size and safety

        Args:
            v (Union[str, bytes]): Value to validate

        Returns:
            Union[str, bytes]: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """
        if v is None:
            return v

        if len(v) > SecurityValidator.MAX_CONTENT_LENGTH:
            raise ValueError(f"Content exceeds maximum length of {SecurityValidator.MAX_CONTENT_LENGTH}")

        if isinstance(v, bytes):
            try:
                text = v.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("Content must be UTF-8 decodable")
        else:
            text = v
        # Runtime pattern matching (not precompiled to allow test monkeypatching)
        if re.search(SecurityValidator.DANGEROUS_HTML_PATTERN, text, re.IGNORECASE):
            raise ValueError("Content contains HTML tags that may cause display issues")

        return v


class ResourceRead(BaseModelWithConfigDict):
    """Schema for reading resource information.

    Includes all resource fields plus:
    - Database ID
    - Content size
    - Creation/update timestamps
    - Active status
    - Metrics: Aggregated metrics for the resource invocations.
    """

    id: str = Field(description="Unique ID of the resource")
    uri: str
    name: str
    description: Optional[str]
    mime_type: Optional[str]
    uri_template: Optional[str] = Field(None, description="URI template for parameterized resources")
    size: Optional[int]
    created_at: datetime
    updated_at: datetime
    enabled: bool
    metrics: Optional[ResourceMetrics] = Field(None, description="Resource metrics (may be None in list operations)")
    tags: List[Dict[str, str]] = Field(default_factory=list, description="Tags for categorizing the resource")

    # Comprehensive metadata for audit tracking
    created_by: Optional[str] = Field(None, description="Username who created this entity")
    created_from_ip: Optional[str] = Field(None, description="IP address of creator")
    created_via: Optional[str] = Field(None, description="Creation method: ui|api|import|federation")
    created_user_agent: Optional[str] = Field(None, description="User agent of creation request")

    modified_by: Optional[str] = Field(None, description="Username who last modified this entity")
    modified_from_ip: Optional[str] = Field(None, description="IP address of last modifier")
    modified_via: Optional[str] = Field(None, description="Modification method")
    modified_user_agent: Optional[str] = Field(None, description="User agent of modification request")

    import_batch_id: Optional[str] = Field(None, description="UUID of bulk import batch")
    federation_source: Optional[str] = Field(None, description="Source gateway for federated entities")
    version: Optional[int] = Field(1, description="Entity version for change tracking")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="ID of the team that owns this resource")
    team: Optional[str] = Field(None, description="Name of the team that owns this resource")
    owner_email: Optional[str] = Field(None, description="Email of the user who owns this resource")
    visibility: Optional[str] = Field(default="public", description="Visibility level: private, team, or public")

    # MCP protocol fields
    title: Optional[str] = Field(None, description="Human-readable title for the resource")
    annotations: Optional[Annotations] = Field(None, description="Optional annotations for client rendering hints")
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta", description="Optional metadata for protocol extension")


class ResourceSubscription(BaseModelWithConfigDict):
    """Schema for resource subscriptions.

    This schema validates resource subscription requests to ensure URIs are safe
    and subscriber IDs follow proper formatting rules. It prevents various
    injection attacks and ensures data consistency.

    Tracks:
    - Resource URI being subscribed to (validated for safety)
    - Unique subscriber identifier (validated for proper format)

    Validation Rules:
    - URIs cannot contain HTML special characters (<, >, ", ', backslash)
    - URIs cannot contain directory traversal sequences (..)
    - URIs must contain only safe characters (alphanumeric, _, -, :, /, ?, =, &, %)
    - Subscriber IDs must contain only alphanumeric characters, underscores, hyphens, and dots
    - Both fields have maximum length limits (255 characters)

    Attributes:
        uri (str): URI of the resource to subscribe to. Must be a safe, valid URI.
        subscriber_id (str): Unique identifier for the subscriber. Must follow
                            identifier naming conventions.

    Examples:
        >>> from pydantic import ValidationError
        >>> # Valid subscription
        >>> sub = ResourceSubscription(uri="/api/v1/users/123", subscriber_id="client_001")
        >>> sub.uri
        '/api/v1/users/123'
        >>> sub.subscriber_id
        'client_001'

        >>> # Valid URI with query parameters
        >>> sub = ResourceSubscription(uri="/data?type=json&limit=10", subscriber_id="app.service.1")
        >>> sub.uri
        '/data?type=json&limit=10'

        >>> # Valid subscriber ID with dots (common for service names)
        >>> sub = ResourceSubscription(uri="/events", subscriber_id="com.example.service")
        >>> sub.subscriber_id
        'com.example.service'

        >>> # Invalid: XSS attempt in URI
        >>> try:
        ...     ResourceSubscription(uri="<script>alert('XSS')</script>", subscriber_id="sub1")
        ... except ValidationError as e:
        ...     print("Validation failed: HTML characters not allowed")
        Validation failed: HTML characters not allowed

        >>> # Invalid: Directory traversal in URI
        >>> try:
        ...     ResourceSubscription(uri="/api/../../../etc/passwd", subscriber_id="sub1")
        ... except ValidationError as e:
        ...     print("Validation failed: Directory traversal detected")
        Validation failed: Directory traversal detected

        >>> # Invalid: SQL injection attempt in URI
        >>> try:
        ...     ResourceSubscription(uri="/users'; DROP TABLE users;--", subscriber_id="sub1")
        ... except ValidationError as e:
        ...     print("Validation failed: Invalid characters in URI")
        Validation failed: Invalid characters in URI

        >>> # Invalid: Special characters in subscriber ID
        >>> try:
        ...     ResourceSubscription(uri="/api/data", subscriber_id="sub@123!")
        ... except ValidationError as e:
        ...     print("Validation failed: Invalid subscriber ID format")
        Validation failed: Invalid subscriber ID format

        >>> # Invalid: Empty URI
        >>> try:
        ...     ResourceSubscription(uri="", subscriber_id="sub1")
        ... except ValidationError as e:
        ...     print("Validation failed: URI cannot be empty")
        Validation failed: URI cannot be empty

        >>> # Invalid: Empty subscriber ID
        >>> try:
        ...     ResourceSubscription(uri="/api/data", subscriber_id="")
        ... except ValidationError as e:
        ...     print("Validation failed: Subscriber ID cannot be empty")
        Validation failed: Subscriber ID cannot be empty

        >>> # Valid: Complex but safe URI
        >>> sub = ResourceSubscription(
        ...     uri="/api/v2/resources/category:items/filter?status=active&limit=50",
        ...     subscriber_id="monitor-service-01"
        ... )
        >>> sub.uri
        '/api/v2/resources/category:items/filter?status=active&limit=50'

        >>> # Edge case: Maximum length validation (simulated)
        >>> long_uri = "/" + "a" * 254  # Just under limit
        >>> sub = ResourceSubscription(uri=long_uri, subscriber_id="sub1")
        >>> len(sub.uri)
        255

        >>> # Invalid: Quotes in URI (could break out of attributes)
        >>> try:
        ...     ResourceSubscription(uri='/api/data"onclick="alert(1)', subscriber_id="sub1")
        ... except ValidationError as e:
        ...     print("Validation failed: Quotes not allowed in URI")
        Validation failed: Quotes not allowed in URI
    """

    uri: str = Field(..., description="URI of resource to subscribe to")
    subscriber_id: str = Field(..., description="Unique subscriber identifier")

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, v: str) -> str:
        """Validate URI format for safety and correctness.

        Ensures the URI:
        - Is not empty
        - Does not contain HTML special characters that could cause XSS
        - Does not contain directory traversal sequences (..)
        - Contains only allowed characters for URIs
        - Does not exceed maximum length (255 characters)

        This prevents various injection attacks including XSS, path traversal,
        and other URI-based vulnerabilities.

        Args:
            v (str): URI to validate

        Returns:
            str: The validated URI if it passes all security checks

        Raises:
            ValueError: If the URI contains dangerous patterns or invalid characters
        """
        return SecurityValidator.validate_uri(v, "Resource URI")

    @field_validator("subscriber_id")
    @classmethod
    def validate_subscriber_id(cls, v: str) -> str:
        """Validate subscriber ID format.

        Ensures the subscriber ID:
        - Is not empty
        - Contains only alphanumeric characters, underscores, hyphens, and dots
        - Does not contain HTML special characters
        - Follows standard identifier naming conventions
        - Does not exceed maximum length (255 characters)

        This ensures consistency and prevents injection attacks through
        subscriber identifiers.

        Args:
            v (str): Subscriber ID to validate

        Returns:
            str: The validated subscriber ID if it passes all checks

        Raises:
            ValueError: If the subscriber ID violates naming conventions
        """
        return SecurityValidator.validate_identifier(v, "Subscriber ID")


class ResourceNotification(BaseModelWithConfigDict):
    """Schema for resource update notifications.

    Contains:
    - Resource URI
    - Updated content
    - Update timestamp
    """

    uri: str
    content: ResourceContent
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_serializer("timestamp")
    def serialize_timestamp(self, dt: datetime) -> str:
        """Serialize the `timestamp` field as an ISO 8601 string with UTC timezone.

        Converts the given datetime to UTC and returns it in ISO 8601 format,
        replacing the "+00:00" suffix with "Z" to indicate UTC explicitly.

        Args:
            dt (datetime): The datetime object to serialize.

        Returns:
            str: ISO 8601 formatted string in UTC, ending with 'Z'.
        """
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# --- Prompt Schemas ---


class PromptArgument(BaseModelWithConfigDict):
    """Schema for prompt template arguments.

    Defines:
    - Argument name
    - Optional description
    - Required flag
    """

    name: str = Field(..., description="Argument name")
    description: Optional[str] = Field(None, description="Argument description")
    required: bool = Field(default=False, description="Whether argument is required")

    # Use base config; example metadata removed to avoid config merging type issues in static checks


class PromptCreate(BaseModelWithConfigDict):
    """
    Schema for creating a new prompt.

    Attributes:
        model_config (ConfigDict): Configuration for the model.
        name (str): Unique name for the prompt.
        description (Optional[str]): Optional description of the prompt.
        template (str): Template text for the prompt.
        arguments (List[PromptArgument]): List of arguments for the template.
    """

    model_config = ConfigDict(**dict(BaseModelWithConfigDict.model_config), str_strip_whitespace=True)

    name: str = Field(..., description="Unique name for the prompt")
    custom_name: Optional[str] = Field(None, description="Custom prompt name used for MCP invocation")
    display_name: Optional[str] = Field(None, description="Display name for the prompt (shown in UI)")
    description: Optional[str] = Field(None, description="Prompt description")
    template: str = Field(..., description="Prompt template text")
    arguments: List[PromptArgument] = Field(default_factory=list, description="List of arguments for the template")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for categorizing the prompt")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the prompt owner")
    visibility: Optional[str] = Field(default="public", description="Visibility level (private, team, public)")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings
        """
        return validate_tags_field(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure prompt names display correctly in UI

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "Prompt name")

    @field_validator("custom_name")
    @classmethod
    def validate_custom_name(cls, v: Optional[str]) -> Optional[str]:
        """Ensure custom prompt names follow MCP naming conventions.

        Args:
            v: Custom prompt name to validate.

        Returns:
            The validated custom name or None.
        """
        if v is None:
            return v
        return SecurityValidator.validate_name(v, "Prompt name")

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: Optional[str]) -> Optional[str]:
        """Ensure display names render safely in UI.

        Args:
            v: Display name to validate.

        Returns:
            The validated display name or None.
        """
        if v is None:
            return v
        return SecurityValidator.sanitize_display_text(v, "Prompt display name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import PromptCreate
            >>> PromptCreate.validate_description('A safe description')
            'A safe description'
            >>> PromptCreate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = PromptCreate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        """Validate template content for safe display

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_template(v)

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure JSON structure is valid and within complexity limits

        Args:
            v (dict): Value to validate

        Returns:
            dict: Value if validated as safe
        """
        SecurityValidator.validate_json_depth(v)
        return v


class PromptExecuteArgs(BaseModel):
    """
    Schema for args executing a prompt

    Attributes:
        args (Dict[str, str]): Arguments for prompt execution.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    args: Dict[str, str] = Field(default_factory=dict, description="Arguments for prompt execution")

    @field_validator("args")
    @classmethod
    def validate_args(cls, v: dict) -> dict:
        """Ensure prompt arguments pass XSS validation

        Args:
            v (dict): Value to validate

        Returns:
            dict: Value if validated as safe
        """
        for val in v.values():
            SecurityValidator.validate_no_xss(val, "Prompt execution arguments")
        return v


class PromptUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing prompt.

    Similar to PromptCreate but all fields are optional to allow partial updates.
    """

    name: Optional[str] = Field(None, description="Unique name for the prompt")
    custom_name: Optional[str] = Field(None, description="Custom prompt name used for MCP invocation")
    display_name: Optional[str] = Field(None, description="Display name for the prompt (shown in UI)")
    description: Optional[str] = Field(None, description="Prompt description")
    template: Optional[str] = Field(None, description="Prompt template text")
    arguments: Optional[List[PromptArgument]] = Field(None, description="List of arguments for the template")

    tags: Optional[List[str]] = Field(None, description="Tags for categorizing the prompt")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the prompt owner")
    visibility: Optional[str] = Field(None, description="Visibility level (private, team, public)")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings
        """
        return validate_tags_field(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure prompt names display correctly in UI

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "Prompt name")

    @field_validator("custom_name")
    @classmethod
    def validate_custom_name(cls, v: Optional[str]) -> Optional[str]:
        """Ensure custom prompt names follow MCP naming conventions.

        Args:
            v: Custom prompt name to validate.

        Returns:
            The validated custom name or None.
        """
        if v is None:
            return v
        return SecurityValidator.validate_name(v, "Prompt name")

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: Optional[str]) -> Optional[str]:
        """Ensure display names render safely in UI.

        Args:
            v: Display name to validate.

        Returns:
            The validated display name or None.
        """
        if v is None:
            return v
        return SecurityValidator.sanitize_display_text(v, "Prompt display name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import PromptUpdate
            >>> PromptUpdate.validate_description('A safe description')
            'A safe description'
            >>> PromptUpdate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = PromptUpdate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        """Validate template content for safe display

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_template(v)

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure JSON structure is valid and within complexity limits

        Args:
            v (dict): Value to validate

        Returns:
            dict: Value if validated as safe
        """
        SecurityValidator.validate_json_depth(v)
        return v


class PromptRead(BaseModelWithConfigDict):
    """Schema for reading prompt information.

    Includes all prompt fields plus:
    - Database ID
    - Creation/update timestamps
    - Active status
    - Metrics: Aggregated metrics for the prompt invocations.
    """

    id: str = Field(description="Unique ID of the prompt")
    name: str
    original_name: str
    custom_name: str
    custom_name_slug: str
    display_name: Optional[str] = Field(None, description="Display name for the prompt (shown in UI)")
    gateway_slug: Optional[str] = None
    description: Optional[str]
    template: str
    arguments: List[PromptArgument]
    created_at: datetime
    updated_at: datetime
    # is_active: bool
    enabled: bool
    tags: List[Dict[str, str]] = Field(default_factory=list, description="Tags for categorizing the prompt")
    metrics: Optional[PromptMetrics] = Field(None, description="Prompt metrics (may be None in list operations)")

    # Comprehensive metadata for audit tracking
    created_by: Optional[str] = Field(None, description="Username who created this entity")
    created_from_ip: Optional[str] = Field(None, description="IP address of creator")
    created_via: Optional[str] = Field(None, description="Creation method: ui|api|import|federation")
    created_user_agent: Optional[str] = Field(None, description="User agent of creation request")

    modified_by: Optional[str] = Field(None, description="Username who last modified this entity")
    modified_from_ip: Optional[str] = Field(None, description="IP address of last modifier")
    modified_via: Optional[str] = Field(None, description="Modification method")
    modified_user_agent: Optional[str] = Field(None, description="User agent of modification request")

    import_batch_id: Optional[str] = Field(None, description="UUID of bulk import batch")
    federation_source: Optional[str] = Field(None, description="Source gateway for federated entities")
    version: Optional[int] = Field(1, description="Entity version for change tracking")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="ID of the team that owns this resource")
    team: Optional[str] = Field(None, description="Name of the team that owns this resource")
    owner_email: Optional[str] = Field(None, description="Email of the user who owns this resource")
    visibility: Optional[str] = Field(default="public", description="Visibility level: private, team, or public")

    # MCP protocol fields
    title: Optional[str] = Field(None, description="Human-readable title for the prompt")
    meta: Optional[Dict[str, Any]] = Field(None, alias="_meta", description="Optional metadata for protocol extension")


class PromptInvocation(BaseModelWithConfigDict):
    """Schema for prompt invocation requests.

    Contains:
    - Prompt name to use
    - Arguments for template rendering
    """

    name: str = Field(..., description="Name of prompt to use")
    arguments: Dict[str, str] = Field(default_factory=dict, description="Arguments for template rendering")


# --- Global Config Schemas ---
class GlobalConfigUpdate(BaseModel):
    """Schema for updating global configuration.

    Attributes:
        passthrough_headers (Optional[List[str]]): List of headers allowed to be passed through globally
    """

    passthrough_headers: Optional[List[str]] = Field(default=None, description="List of headers allowed to be passed through globally")


class GlobalConfigRead(BaseModel):
    """Schema for reading global configuration.

    Attributes:
        passthrough_headers (Optional[List[str]]): List of headers allowed to be passed through globally
    """

    passthrough_headers: Optional[List[str]] = Field(default=None, description="List of headers allowed to be passed through globally")


# --- Gateway Schemas ---


# --- Transport Type ---
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


class GatewayCreate(BaseModel):
    """
    Schema for creating a new gateway.

    Attributes:
        model_config (ConfigDict): Configuration for the model.
        name (str): Unique name for the gateway.
        url (Union[str, AnyHttpUrl]): Gateway endpoint URL.
        description (Optional[str]): Optional description of the gateway.
        transport (str): Transport used by the MCP server, default is "SSE".
        auth_type (Optional[str]): Type of authentication (basic, bearer, headers, or none).
        auth_username (Optional[str]): Username for basic authentication.
        auth_password (Optional[str]): Password for basic authentication.
        auth_token (Optional[str]): Token for bearer authentication.
        auth_header_key (Optional[str]): Key for custom headers authentication.
        auth_header_value (Optional[str]): Value for custom headers authentication.
        auth_headers (Optional[List[Dict[str, str]]]): List of custom headers for authentication.
        auth_value (Optional[str]): Alias for authentication value, used for better access post-validation.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., description="Unique name for the gateway")
    url: Union[str, AnyHttpUrl] = Field(..., description="Gateway endpoint URL")
    description: Optional[str] = Field(None, description="Gateway description")
    transport: str = Field(default="SSE", description="Transport used by MCP server: SSE or STREAMABLEHTTP")
    passthrough_headers: Optional[List[str]] = Field(default=None, description="List of headers allowed to be passed through from client to target")

    # Authorizations
    auth_type: Optional[str] = Field(None, description="Type of authentication: basic, bearer, headers, oauth, or none")
    # Fields for various types of authentication
    auth_username: Optional[str] = Field(None, description="Username for basic authentication")
    auth_password: Optional[str] = Field(None, description="Password for basic authentication")
    auth_token: Optional[str] = Field(None, description="Token for bearer authentication")
    auth_header_key: Optional[str] = Field(None, description="Key for custom headers authentication")
    auth_header_value: Optional[str] = Field(None, description="Value for custom headers authentication")
    auth_headers: Optional[List[Dict[str, str]]] = Field(None, description="List of custom headers for authentication")

    # OAuth 2.0 configuration
    oauth_config: Optional[Dict[str, Any]] = Field(None, description="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes")

    # Adding `auth_value` as an alias for better access post-validation
    auth_value: Optional[str] = Field(None, validate_default=True)

    # One time auth - do not store the auth in gateway flag
    one_time_auth: Optional[bool] = Field(default=False, description="The authentication should be used only once and not stored in the gateway")

    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for categorizing the gateway")

    # Team scoping fields for resource organization
    team_id: Optional[str] = Field(None, description="Team ID this gateway belongs to")
    owner_email: Optional[str] = Field(None, description="Email of the gateway owner")
    visibility: Optional[str] = Field(default="public", description="Gateway visibility: private, team, or public")

    # CA certificate
    ca_certificate: Optional[str] = Field(None, description="Custom CA certificate for TLS verification")
    ca_certificate_sig: Optional[str] = Field(None, description="Signature of the custom CA certificate for integrity verification")
    signing_algorithm: Optional[str] = Field("ed25519", description="Algorithm used for signing the CA certificate")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings
        """
        return validate_tags_field(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate gateway name

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "Gateway name")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate gateway URL

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_url(v, "Gateway URL")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import GatewayCreate
            >>> GatewayCreate.validate_description('A safe description')
            'A safe description'
            >>> GatewayCreate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = ToolCreate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("auth_value", mode="before")
    @classmethod
    def create_auth_value(cls, v, info):
        """
        This validator will run before the model is fully instantiated (mode="before")
        It will process the auth fields based on auth_type and generate auth_value.

        Args:
            v: Input url
            info: ValidationInfo containing auth_type

        Returns:
            str: Auth value
        """
        data = info.data
        auth_type = data.get("auth_type")

        if (auth_type is None) or (auth_type == ""):
            return v  # If no auth_type is provided, no need to create auth_value

        # Process the auth fields and generate auth_value based on auth_type
        auth_value = cls._process_auth_fields(info)
        return auth_value

    @field_validator("transport")
    @classmethod
    def validate_transport(cls, v: str) -> str:
        """
        Validates that the given transport value is one of the supported TransportType values.

        Args:
            v (str): The transport value to validate.

        Returns:
            str: The validated transport value if it is valid.

        Raises:
            ValueError: If the provided value is not a valid transport type.

        Valid transport types are defined in the TransportType enum:
            - SSE
            - HTTP
            - STDIO
            - STREAMABLEHTTP
        """
        allowed = [t.value for t in TransportType.__members__.values()]
        if v not in allowed:
            raise ValueError(f"Invalid transport type: {v}. Must be one of: {', '.join(allowed)}")
        return v

    @staticmethod
    def _process_auth_fields(info: ValidationInfo) -> Optional[str]:
        """
        Processes the input authentication fields and returns the correct auth_value.
        This method is called based on the selected auth_type.

        Args:
            info: ValidationInfo containing auth fields

        Returns:
            Encoded auth string or None

        Raises:
            ValueError: If auth_type is invalid
        """
        data = info.data
        auth_type = data.get("auth_type")

        if auth_type == "basic":
            # For basic authentication, both username and password must be present
            username = data.get("auth_username")
            password = data.get("auth_password")

            if not username or not password:
                raise ValueError("For 'basic' auth, both 'auth_username' and 'auth_password' must be provided.")

            creds = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode()
            return encode_auth({"Authorization": f"Basic {creds}"})

        if auth_type == "bearer":
            # For bearer authentication, only token is required
            token = data.get("auth_token")

            if not token:
                raise ValueError("For 'bearer' auth, 'auth_token' must be provided.")

            return encode_auth({"Authorization": f"Bearer {token}"})

        if auth_type == "oauth":
            # For OAuth authentication, we don't encode anything here
            # The OAuth configuration is handled separately in the oauth_config field
            # This method is only called for traditional auth types
            return None

        if auth_type == "authheaders":
            # Support both new multi-headers format and legacy single header format
            auth_headers = data.get("auth_headers")
            if auth_headers and isinstance(auth_headers, list):
                # New multi-headers format with enhanced validation
                header_dict = {}
                duplicate_keys = set()

                for header in auth_headers:
                    if not isinstance(header, dict):
                        continue

                    key = header.get("key")
                    value = header.get("value", "")

                    # Skip headers without keys
                    if not key:
                        continue

                    # Track duplicate keys (last value wins)
                    if key in header_dict:
                        duplicate_keys.add(key)

                    # Validate header key format (basic HTTP header validation)
                    if not all(c.isalnum() or c in "-_" for c in key.replace(" ", "")):
                        raise ValueError(f"Invalid header key format: '{key}'. Header keys should contain only alphanumeric characters, hyphens, and underscores.")

                    # Store header (empty values are allowed)
                    header_dict[key] = value

                # Ensure at least one valid header
                if not header_dict:
                    raise ValueError("For 'headers' auth, at least one valid header with a key must be provided.")

                # Warn about duplicate keys (optional - could log this instead)
                if duplicate_keys:
                    logging.warning(f"Duplicate header keys detected (last value used): {', '.join(duplicate_keys)}")

                # Check for excessive headers (prevent abuse)
                if len(header_dict) > 100:
                    raise ValueError("Maximum of 100 headers allowed per gateway.")

                return encode_auth(header_dict)

            # Legacy single header format (backward compatibility)
            header_key = data.get("auth_header_key")
            header_value = data.get("auth_header_value")

            if not header_key or not header_value:
                raise ValueError("For 'headers' auth, either 'auth_headers' list or both 'auth_header_key' and 'auth_header_value' must be provided.")

            return encode_auth({header_key: header_value})

        if auth_type == "one_time_auth":
            return None  # No auth_value needed for one-time auth

        raise ValueError("Invalid 'auth_type'. Must be one of: basic, bearer, oauth, or headers.")


class GatewayUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing federation gateway.

    Similar to GatewayCreate but all fields are optional to allow partial updates.
    """

    name: Optional[str] = Field(None, description="Unique name for the gateway")
    url: Optional[Union[str, AnyHttpUrl]] = Field(None, description="Gateway endpoint URL")
    description: Optional[str] = Field(None, description="Gateway description")
    transport: str = Field(default="SSE", description="Transport used by MCP server: SSE or STREAMABLEHTTP")

    passthrough_headers: Optional[List[str]] = Field(default=None, description="List of headers allowed to be passed through from client to target")

    # Authorizations
    auth_type: Optional[str] = Field(None, description="auth_type: basic, bearer, headers or None")
    auth_username: Optional[str] = Field(None, description="username for basic authentication")
    auth_password: Optional[str] = Field(None, description="password for basic authentication")
    auth_token: Optional[str] = Field(None, description="token for bearer authentication")
    auth_header_key: Optional[str] = Field(None, description="key for custom headers authentication")
    auth_header_value: Optional[str] = Field(None, description="value for custom headers authentication")
    auth_headers: Optional[List[Dict[str, str]]] = Field(None, description="List of custom headers for authentication")

    # Adding `auth_value` as an alias for better access post-validation
    auth_value: Optional[str] = Field(None, validate_default=True)

    # OAuth 2.0 configuration
    oauth_config: Optional[Dict[str, Any]] = Field(None, description="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes")

    # One time auth - do not store the auth in gateway flag
    one_time_auth: Optional[bool] = Field(default=False, description="The authentication should be used only once and not stored in the gateway")

    tags: Optional[List[str]] = Field(None, description="Tags for categorizing the gateway")

    # Team scoping fields for resource organization
    team_id: Optional[str] = Field(None, description="Team ID this gateway belongs to")
    owner_email: Optional[str] = Field(None, description="Email of the gateway owner")
    visibility: Optional[str] = Field(None, description="Gateway visibility: private, team, or public")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings
        """
        return validate_tags_field(v)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate gateway name

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "Gateway name")

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate gateway URL

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_url(v, "Gateway URL")

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import GatewayUpdate
            >>> GatewayUpdate.validate_description('A safe description')
            'A safe description'
            >>> GatewayUpdate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = ToolCreate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("auth_value", mode="before")
    @classmethod
    def create_auth_value(cls, v, info):
        """
        This validator will run before the model is fully instantiated (mode="before")
        It will process the auth fields based on auth_type and generate auth_value.

        Args:
            v: Input URL
            info: ValidationInfo containing auth_type

        Returns:
            str: Auth value or URL
        """
        data = info.data
        auth_type = data.get("auth_type")

        if (auth_type is None) or (auth_type == ""):
            return v  # If no auth_type is provided, no need to create auth_value

        # Process the auth fields and generate auth_value based on auth_type
        auth_value = cls._process_auth_fields(info)
        return auth_value

    @staticmethod
    def _process_auth_fields(info: ValidationInfo) -> Optional[str]:
        """
        Processes the input authentication fields and returns the correct auth_value.
        This method is called based on the selected auth_type.

        Args:
            info: ValidationInfo containing auth fields

        Returns:
            Encoded auth string or None

        Raises:
            ValueError: If auth type is invalid
        """

        data = info.data
        auth_type = data.get("auth_type")

        if auth_type == "basic":
            # For basic authentication, both username and password must be present
            username = data.get("auth_username")
            password = data.get("auth_password")
            if not username or not password:
                raise ValueError("For 'basic' auth, both 'auth_username' and 'auth_password' must be provided.")

            creds = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode()
            return encode_auth({"Authorization": f"Basic {creds}"})

        if auth_type == "bearer":
            # For bearer authentication, only token is required
            token = data.get("auth_token")

            if not token:
                raise ValueError("For 'bearer' auth, 'auth_token' must be provided.")

            return encode_auth({"Authorization": f"Bearer {token}"})

        if auth_type == "oauth":
            # For OAuth authentication, we don't encode anything here
            # The OAuth configuration is handled separately in the oauth_config field
            # This method is only called for traditional auth types
            return None

        if auth_type == "authheaders":
            # Support both new multi-headers format and legacy single header format
            auth_headers = data.get("auth_headers")
            if auth_headers and isinstance(auth_headers, list):
                # New multi-headers format with enhanced validation
                header_dict = {}
                duplicate_keys = set()

                for header in auth_headers:
                    if not isinstance(header, dict):
                        continue

                    key = header.get("key")
                    value = header.get("value", "")

                    # Skip headers without keys
                    if not key:
                        continue

                    # Track duplicate keys (last value wins)
                    if key in header_dict:
                        duplicate_keys.add(key)

                    # Validate header key format (basic HTTP header validation)
                    if not all(c.isalnum() or c in "-_" for c in key.replace(" ", "")):
                        raise ValueError(f"Invalid header key format: '{key}'. Header keys should contain only alphanumeric characters, hyphens, and underscores.")

                    # Store header (empty values are allowed)
                    header_dict[key] = value

                # Ensure at least one valid header
                if not header_dict:
                    raise ValueError("For 'headers' auth, at least one valid header with a key must be provided.")

                # Warn about duplicate keys (optional - could log this instead)
                if duplicate_keys:
                    logging.warning(f"Duplicate header keys detected (last value used): {', '.join(duplicate_keys)}")

                # Check for excessive headers (prevent abuse)
                if len(header_dict) > 100:
                    raise ValueError("Maximum of 100 headers allowed per gateway.")

                return encode_auth(header_dict)

            # Legacy single header format (backward compatibility)
            header_key = data.get("auth_header_key")
            header_value = data.get("auth_header_value")

            if not header_key or not header_value:
                raise ValueError("For 'headers' auth, either 'auth_headers' list or both 'auth_header_key' and 'auth_header_value' must be provided.")

            return encode_auth({header_key: header_value})

        if auth_type == "one_time_auth":
            return None  # No auth_value needed for one-time auth

        raise ValueError("Invalid 'auth_type'. Must be one of: basic, bearer, oauth, or headers.")


class GatewayRead(BaseModelWithConfigDict):
    """Schema for reading gateway information.

    Includes all gateway fields plus:
    - Database ID
    - Capabilities dictionary
    - Creation/update timestamps
    - enabled status
    - reachable status
    - Last seen timestamp
    - Authentication type: basic, bearer, headers, oauth
    - Authentication value: username/password or token or custom headers
    - OAuth configuration for OAuth 2.0 authentication

    Auto Populated fields:
    - Authentication username: for basic auth
    - Authentication password: for basic auth
    - Authentication token: for bearer auth
    - Authentication header key: for headers auth
    - Authentication header value: for headers auth
    """

    id: Optional[str] = Field(None, description="Unique ID of the gateway")
    name: str = Field(..., description="Unique name for the gateway")
    url: str = Field(..., description="Gateway endpoint URL")
    description: Optional[str] = Field(None, description="Gateway description")
    transport: str = Field(default="SSE", description="Transport used by MCP server: SSE or STREAMABLEHTTP")
    capabilities: Dict[str, Any] = Field(default_factory=dict, description="Gateway capabilities")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Last update timestamp")
    enabled: bool = Field(default=True, description="Is the gateway enabled?")
    reachable: bool = Field(default=True, description="Is the gateway reachable/online?")

    last_seen: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc), description="Last seen timestamp")

    passthrough_headers: Optional[List[str]] = Field(default=None, description="List of headers allowed to be passed through from client to target")
    # Authorizations
    auth_type: Optional[str] = Field(None, description="auth_type: basic, bearer, headers, oauth, or None")
    auth_value: Optional[str] = Field(None, description="auth value: username/password or token or custom headers")
    auth_headers: Optional[List[Dict[str, str]]] = Field(default=None, description="List of custom headers for authentication")
    auth_headers_unmasked: Optional[List[Dict[str, str]]] = Field(default=None, description="Unmasked custom headers for administrative views")

    # OAuth 2.0 configuration
    oauth_config: Optional[Dict[str, Any]] = Field(None, description="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes")

    # auth_value will populate the following fields
    auth_username: Optional[str] = Field(None, description="username for basic authentication")
    auth_password: Optional[str] = Field(None, description="password for basic authentication")
    auth_token: Optional[str] = Field(None, description="token for bearer authentication")
    auth_header_key: Optional[str] = Field(None, description="key for custom headers authentication")
    auth_header_value: Optional[str] = Field(None, description="vallue for custom headers authentication")
    tags: List[Dict[str, str]] = Field(default_factory=list, description="Tags for categorizing the gateway")

    auth_password_unmasked: Optional[str] = Field(default=None, description="Unmasked password for basic authentication")
    auth_token_unmasked: Optional[str] = Field(default=None, description="Unmasked bearer token for authentication")
    auth_header_value_unmasked: Optional[str] = Field(default=None, description="Unmasked single custom header value")

    # Team scoping fields for resource organization
    team_id: Optional[str] = Field(None, description="Team ID this gateway belongs to")
    team: Optional[str] = Field(None, description="Name of the team that owns this resource")
    owner_email: Optional[str] = Field(None, description="Email of the gateway owner")
    visibility: Optional[str] = Field(default="public", description="Gateway visibility: private, team, or public")

    # Comprehensive metadata for audit tracking
    created_by: Optional[str] = Field(None, description="Username who created this entity")
    created_from_ip: Optional[str] = Field(None, description="IP address of creator")
    created_via: Optional[str] = Field(None, description="Creation method: ui|api|import|federation")
    created_user_agent: Optional[str] = Field(None, description="User agent of creation request")

    modified_by: Optional[str] = Field(None, description="Username who last modified this entity")
    modified_from_ip: Optional[str] = Field(None, description="IP address of last modifier")
    modified_via: Optional[str] = Field(None, description="Modification method")
    modified_user_agent: Optional[str] = Field(None, description="User agent of modification request")

    import_batch_id: Optional[str] = Field(None, description="UUID of bulk import batch")
    federation_source: Optional[str] = Field(None, description="Source gateway for federated entities")
    version: Optional[int] = Field(1, description="Entity version for change tracking")

    slug: Optional[str] = Field(None, description="Slug for gateway endpoint URL")

    # This will be the main method to automatically populate fields
    @model_validator(mode="after")
    def _populate_auth(self) -> Self:
        """Populate authentication fields based on auth_type and encoded auth_value.

        This post-validation method decodes the stored authentication value and
        populates the appropriate authentication fields (username/password, token,
        or custom headers) based on the authentication type. It ensures the
        authentication data is properly formatted and accessible through individual
        fields for display purposes.

        The method handles three authentication types:
        - basic: Extracts username and password from Authorization header
        - bearer: Extracts token from Bearer Authorization header
        - authheaders: Extracts custom header key/value pair

        Returns:
            Self: The instance with populated authentication fields:
                - For basic: auth_username and auth_password
                - For bearer: auth_token
                - For authheaders: auth_header_key and auth_header_value

        Raises:
            ValueError: If the authentication data is malformed:
                    - Basic auth missing username or password
                    - Bearer auth missing or improperly formatted Authorization header
                    - Custom headers not exactly one key/value pair

        Examples:
            >>> # Basic auth example
            >>> string_bytes = "admin:secret".encode("utf-8")
            >>> encoded_auth = base64.urlsafe_b64encode(string_bytes).decode("utf-8")
            >>> values = GatewayRead.model_construct(
            ...     auth_type="basic",
            ...     auth_value=encode_auth({"Authorization": f"Basic {encoded_auth}"})
            ... )
            >>> values = GatewayRead._populate_auth(values)
            >>> values.auth_username
            'admin'
            >>> values.auth_password
            'secret'

            >>> # Bearer auth example
            >>> values = GatewayRead.model_construct(
            ...     auth_type="bearer",
            ...     auth_value=encode_auth({"Authorization": "Bearer mytoken123"})
            ... )
            >>> values = GatewayRead._populate_auth(values)
            >>> values.auth_token
            'mytoken123'

            >>> # Custom headers example
            >>> values = GatewayRead.model_construct(
            ...     auth_type='authheaders',
            ...     auth_value=encode_auth({"X-API-Key": "abc123"})
            ... )
            >>> values = GatewayRead._populate_auth(values)
            >>> values.auth_header_key
            'X-API-Key'
            >>> values.auth_header_value
            'abc123'
        """
        auth_type = self.auth_type
        auth_value_encoded = self.auth_value

        # Skip validation logic if masked value
        if auth_value_encoded == settings.masked_auth_value:
            return self

        # Handle OAuth authentication (no auth_value to decode)
        if auth_type == "oauth":
            # OAuth gateways don't have traditional auth_value to decode
            # They use oauth_config instead
            return self

        if auth_type == "one_time_auth":
            # One-time auth gateways don't store auth_value
            return self

        # If no encoded value is present, nothing to populate
        if not auth_value_encoded:
            return self

        auth_value = decode_auth(auth_value_encoded)
        if auth_type == "basic":
            auth = auth_value.get("Authorization")
            if not (isinstance(auth, str) and auth.startswith("Basic ")):
                raise ValueError("basic auth requires an Authorization header of the form 'Basic <base64>'")
            auth = auth.removeprefix("Basic ")
            u, p = base64.urlsafe_b64decode(auth).decode("utf-8").split(":")
            if not u or not p:
                raise ValueError("basic auth requires both username and password")
            self.auth_username, self.auth_password = u, p
            self.auth_password_unmasked = p

        elif auth_type == "bearer":
            auth = auth_value.get("Authorization")
            if not (isinstance(auth, str) and auth.startswith("Bearer ")):
                raise ValueError("bearer auth requires an Authorization header of the form 'Bearer <token>'")
            self.auth_token = auth.removeprefix("Bearer ")
            self.auth_token_unmasked = self.auth_token

        elif auth_type == "authheaders":
            # For backward compatibility, populate first header in key/value fields
            if not isinstance(auth_value, dict) or len(auth_value) == 0:
                raise ValueError("authheaders requires at least one key/value pair")
            self.auth_headers = [{"key": str(key), "value": "" if value is None else str(value)} for key, value in auth_value.items()]
            self.auth_headers_unmasked = [{"key": str(key), "value": "" if value is None else str(value)} for key, value in auth_value.items()]
            k, v = next(iter(auth_value.items()))
            self.auth_header_key, self.auth_header_value = k, v
            self.auth_header_value_unmasked = v

        return self

    def masked(self) -> "GatewayRead":
        """
        Return a masked version of the model instance with sensitive authentication fields hidden.

        This method creates a dictionary representation of the model data and replaces sensitive fields
        such as `auth_value`, `auth_password`, `auth_token`, and `auth_header_value` with a masked
        placeholder value defined in `settings.masked_auth_value`. Masking is only applied if the fields
        are present and not already masked.

        Args:
            None

        Returns:
            GatewayRead: A new instance of the GatewayRead model with sensitive authentication-related fields
            masked to prevent exposure of sensitive information.

        Notes:
            - The `auth_value` field is only masked if it exists and its value is different from the masking
            placeholder.
            - Other sensitive fields (`auth_password`, `auth_token`, `auth_header_value`) are masked if present.
            - Fields not related to authentication remain unmodified.
        """
        masked_data = self.model_dump()

        # Only mask if auth_value is present and not already masked
        if masked_data.get("auth_value") and masked_data["auth_value"] != settings.masked_auth_value:
            masked_data["auth_value"] = settings.masked_auth_value

        masked_data["auth_password"] = settings.masked_auth_value if masked_data.get("auth_password") else None
        masked_data["auth_token"] = settings.masked_auth_value if masked_data.get("auth_token") else None
        masked_data["auth_header_value"] = settings.masked_auth_value if masked_data.get("auth_header_value") else None
        if masked_data.get("auth_headers"):
            masked_data["auth_headers"] = [
                {
                    "key": header.get("key"),
                    "value": settings.masked_auth_value if header.get("value") else header.get("value"),
                }
                for header in masked_data["auth_headers"]
            ]

        masked_data["auth_password_unmasked"] = self.auth_password_unmasked
        masked_data["auth_token_unmasked"] = self.auth_token_unmasked
        masked_data["auth_header_value_unmasked"] = self.auth_header_value_unmasked
        masked_data["auth_headers_unmasked"] = [header.copy() for header in self.auth_headers_unmasked] if self.auth_headers_unmasked else None
        return GatewayRead.model_validate(masked_data)


class FederatedTool(BaseModelWithConfigDict):
    """Schema for tools provided by federated gateways.

    Contains:
    - Tool definition
    - Source gateway information
    """

    tool: MCPTool
    gateway_id: str
    gateway_name: str
    gateway_url: str


class FederatedResource(BaseModelWithConfigDict):
    """Schema for resources from federated gateways.

    Contains:
    - Resource definition
    - Source gateway information
    """

    resource: MCPResource
    gateway_id: str
    gateway_name: str
    gateway_url: str


class FederatedPrompt(BaseModelWithConfigDict):
    """Schema for prompts from federated gateways.

    Contains:
    - Prompt definition
    - Source gateway information
    """

    prompt: MCPPrompt
    gateway_id: str
    gateway_name: str
    gateway_url: str


# --- RPC Schemas ---
class RPCRequest(BaseModel):
    """MCP-compliant RPC request validation"""

    jsonrpc: Literal["2.0"]
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Union[int, str]] = None

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        """Ensure method names follow MCP format

        Args:
            v (str): Value to validate

        Returns:
            str: Value if determined as safe

        Raises:
            ValueError: When value is not safe
        """
        SecurityValidator.validate_no_xss(v, "RPC method name")
        # Runtime pattern matching (not precompiled to allow test monkeypatching)
        if not re.match(settings.validation_tool_method_pattern, v):
            raise ValueError("Invalid method name format")
        if len(v) > settings.validation_max_method_length:
            raise ValueError("Method name too long")
        return v

    @field_validator("params")
    @classmethod
    def validate_params(cls, v: Optional[Union[Dict, List]]) -> Optional[Union[Dict, List]]:
        """Validate RPC parameters

        Args:
            v (Union[dict, list]): Value to validate

        Returns:
            Union[dict, list]: Value if determined as safe

        Raises:
            ValueError: When value is not safe
        """
        if v is None:
            return v

        # Check size limits (MCP recommends max 256KB for params)
        param_size = len(orjson.dumps(v))
        if param_size > settings.validation_max_rpc_param_size:
            raise ValueError(f"Parameters exceed maximum size of {settings.validation_max_rpc_param_size} bytes")

        # Check depth
        SecurityValidator.validate_json_depth(v)
        return v


class RPCResponse(BaseModelWithConfigDict):
    """Schema for JSON-RPC 2.0 responses.

    Contains:
    - Protocol version
    - Result or error
    - Request ID
    """

    jsonrpc: Literal["2.0"]
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    id: Optional[Union[int, str]] = None


# --- Event and Admin Schemas ---


class EventMessage(BaseModelWithConfigDict):
    """Schema for SSE event messages.

    Includes:
    - Event type
    - Event data payload
    - Event timestamp
    """

    type: str = Field(..., description="Event type (tool_added, resource_updated, etc)")
    data: Dict[str, Any] = Field(..., description="Event payload")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_serializer("timestamp")
    def serialize_timestamp(self, dt: datetime) -> str:
        """
        Serialize the `timestamp` field as an ISO 8601 string with UTC timezone.

        Converts the given datetime to UTC and returns it in ISO 8601 format,
        replacing the "+00:00" suffix with "Z" to indicate UTC explicitly.

        Args:
            dt (datetime): The datetime object to serialize.

        Returns:
            str: ISO 8601 formatted string in UTC, ending with 'Z'.
        """
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class AdminToolCreate(BaseModelWithConfigDict):
    """Schema for creating tools via admin UI.

    Handles:
    - Basic tool information
    - JSON string inputs for headers/schema
    """

    name: str
    url: str
    description: Optional[str] = None
    integration_type: str = "MCP"
    headers: Optional[str] = None  # JSON string
    input_schema: Optional[str] = None  # JSON string

    @field_validator("headers", "input_schema")
    @classmethod
    def validate_json(cls, v: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Validate and parse JSON string inputs.

        Args:
            v: Input string

        Returns:
            dict: Output JSON version of v

        Raises:
            ValueError: When unable to convert to JSON
        """
        if not v:
            return None
        try:
            return orjson.loads(v)
        except orjson.JSONDecodeError:
            raise ValueError("Invalid JSON")


class AdminGatewayCreate(BaseModelWithConfigDict):
    """Schema for creating gateways via admin UI.

    Captures:
    - Gateway name
    - Endpoint URL
    - Optional description
    """

    name: str
    url: str
    description: Optional[str] = None


# --- New Schemas for Status Toggle Operations ---


class StatusToggleRequest(BaseModelWithConfigDict):
    """Request schema for toggling active status."""

    activate: bool = Field(..., description="Whether to activate (true) or deactivate (false) the item")


class StatusToggleResponse(BaseModelWithConfigDict):
    """Response schema for status toggle operations."""

    id: int
    name: str
    is_active: bool
    message: str = Field(..., description="Success message")


# --- Optional Filter Parameters for Listing Operations ---


class ListFilters(BaseModelWithConfigDict):
    """Filtering options for list operations."""

    include_inactive: bool = Field(False, description="Whether to include inactive items in the results")


# --- Server Schemas ---


class ServerCreate(BaseModel):
    """
    Schema for creating a new server.

    Attributes:
        model_config (ConfigDict): Configuration for the model, such as stripping whitespace from strings.
        name (str): The server's name.
        description (Optional[str]): Optional description of the server.
        icon (Optional[str]): Optional URL for the server's icon.
        associated_tools (Optional[List[str]]): Optional list of associated tool IDs.
        associated_resources (Optional[List[str]]): Optional list of associated resource IDs.
        associated_prompts (Optional[List[str]]): Optional list of associated prompt IDs.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Optional[str] = Field(None, description="Custom UUID for the server (if not provided, one will be generated)")
    name: str = Field(..., description="The server's name")
    description: Optional[str] = Field(None, description="Server description")
    icon: Optional[str] = Field(None, description="URL for the server's icon")
    tags: Optional[List[str]] = Field(default_factory=list, description="Tags for categorizing the server")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings
        """
        return validate_tags_field(v)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate server ID/UUID format

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When displayName contains unsafe content or exceeds length limits

        Examples:
            >>> from mcpgateway.schemas import ServerCreate
            >>> ServerCreate.validate_id('550e8400-e29b-41d4-a716-446655440000')
            '550e8400e29b41d4a716446655440000'
            >>> ServerCreate.validate_id('invalid-uuid')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if v is None:
            return v
        return SecurityValidator.validate_uuid(v, "Server ID")

    associated_tools: Optional[List[str]] = Field(None, description="Comma-separated tool IDs")
    associated_resources: Optional[List[str]] = Field(None, description="Comma-separated resource IDs")
    associated_prompts: Optional[List[str]] = Field(None, description="Comma-separated prompt IDs")
    associated_a2a_agents: Optional[List[str]] = Field(None, description="Comma-separated A2A agent IDs")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the server owner")
    visibility: Optional[str] = Field(default="public", description="Visibility level (private, team, public)")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate server name

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "Server name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import ServerCreate
            >>> ServerCreate.validate_description('A safe description')
            'A safe description'
            >>> ServerCreate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = ServerCreate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, v: Optional[str]) -> Optional[str]:
        """Validate icon URL

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        if v is None or v == "":
            return v
        return SecurityValidator.validate_url(v, "Icon URL")

    @field_validator("associated_tools", "associated_resources", "associated_prompts", "associated_a2a_agents", mode="before")
    @classmethod
    def split_comma_separated(cls, v):
        """
        Splits a comma-separated string into a list of strings if needed.

        Args:
            v: Input string

        Returns:
            list: Comma separated array of input string
        """
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        """Validate visibility level.

        Args:
            v: Visibility value to validate

        Returns:
            Validated visibility value

        Raises:
            ValueError: If visibility is invalid
        """
        if v not in ["private", "team", "public"]:
            raise ValueError("Visibility must be one of: private, team, public")
        return v

    @field_validator("team_id")
    @classmethod
    def validate_team_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate team ID format.

        Args:
            v: Team ID to validate

        Returns:
            Validated team ID
        """
        if v is not None:
            return SecurityValidator.validate_uuid(v, "team_id")
        return v


class ServerUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing server.

    All fields are optional to allow partial updates.
    """

    id: Optional[str] = Field(None, description="Custom UUID for the server")
    name: Optional[str] = Field(None, description="The server's name")
    description: Optional[str] = Field(None, description="Server description")
    icon: Optional[str] = Field(None, description="URL for the server's icon")
    tags: Optional[List[str]] = Field(None, description="Tags for categorizing the server")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the server owner")
    visibility: Optional[str] = Field(None, description="Visibility level (private, team, public)")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings
        """
        return validate_tags_field(v)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate server ID/UUID format

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When displayName contains unsafe content or exceeds length limits

        Examples:
            >>> from mcpgateway.schemas import ServerUpdate
            >>> ServerUpdate.validate_id('550e8400-e29b-41d4-a716-446655440000')
            '550e8400e29b41d4a716446655440000'
            >>> ServerUpdate.validate_id('invalid-uuid')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if v is None:
            return v
        return SecurityValidator.validate_uuid(v, "Server ID")

    associated_tools: Optional[List[str]] = Field(None, description="Comma-separated tool IDs")
    associated_resources: Optional[List[str]] = Field(None, description="Comma-separated resource IDs")
    associated_prompts: Optional[List[str]] = Field(None, description="Comma-separated prompt IDs")
    associated_a2a_agents: Optional[List[str]] = Field(None, description="Comma-separated A2A agent IDs")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate server name

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "Server name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import ServerUpdate
            >>> ServerUpdate.validate_description('A safe description')
            'A safe description'
            >>> ServerUpdate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = ServerUpdate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("icon")
    @classmethod
    def validate_icon(cls, v: Optional[str]) -> Optional[str]:
        """Validate icon URL

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        if v is None or v == "":
            return v
        return SecurityValidator.validate_url(v, "Icon URL")

    @field_validator("associated_tools", "associated_resources", "associated_prompts", "associated_a2a_agents", mode="before")
    @classmethod
    def split_comma_separated(cls, v):
        """
        Splits a comma-separated string into a list of strings if needed.

        Args:
            v: Input string

        Returns:
            list: Comma separated array of input string
        """
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


class ServerRead(BaseModelWithConfigDict):
    """Schema for reading server information.

    Includes all server fields plus:
    - Database ID
    - Associated tool, resource, and prompt IDs
    - Creation/update timestamps
    - Active status
    - Metrics: Aggregated metrics for the server invocations.
    """

    id: str
    name: str
    description: Optional[str]
    icon: Optional[str]
    created_at: datetime
    updated_at: datetime
    # is_active: bool
    enabled: bool
    associated_tools: List[str] = []
    associated_resources: List[str] = []
    associated_prompts: List[str] = []
    associated_a2a_agents: List[str] = []
    metrics: Optional[ServerMetrics] = Field(None, description="Server metrics (may be None in list operations)")
    tags: List[Dict[str, str]] = Field(default_factory=list, description="Tags for categorizing the server")

    # Comprehensive metadata for audit tracking
    created_by: Optional[str] = Field(None, description="Username who created this entity")
    created_from_ip: Optional[str] = Field(None, description="IP address of creator")
    created_via: Optional[str] = Field(None, description="Creation method: ui|api|import|federation")
    created_user_agent: Optional[str] = Field(None, description="User agent of creation request")

    modified_by: Optional[str] = Field(None, description="Username who last modified this entity")
    modified_from_ip: Optional[str] = Field(None, description="IP address of last modifier")
    modified_via: Optional[str] = Field(None, description="Modification method")
    modified_user_agent: Optional[str] = Field(None, description="User agent of modification request")

    import_batch_id: Optional[str] = Field(None, description="UUID of bulk import batch")
    federation_source: Optional[str] = Field(None, description="Source gateway for federated entities")
    version: Optional[int] = Field(1, description="Entity version for change tracking")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="ID of the team that owns this resource")
    team: Optional[str] = Field(None, description="Name of the team that owns this resource")
    owner_email: Optional[str] = Field(None, description="Email of the user who owns this resource")
    visibility: Optional[str] = Field(default="public", description="Visibility level: private, team, or public")

    @model_validator(mode="before")
    @classmethod
    def populate_associated_ids(cls, values):
        """
        Pre-validation method that converts associated objects to their 'id'.

        This method checks 'associated_tools', 'associated_resources', and
        'associated_prompts' in the input and replaces each object with its `id`
        if present.

        Args:
            values (dict): The input values.

        Returns:
            dict: Updated values with object ids, or the original values if no
            changes are made.
        """
        # Normalize to a mutable dict
        if isinstance(values, dict):
            data = dict(values)
        else:
            try:
                data = dict(vars(values))
            except Exception:
                return values

        if data.get("associated_tools"):
            data["associated_tools"] = [getattr(tool, "id", tool) for tool in data["associated_tools"]]
        if data.get("associated_resources"):
            data["associated_resources"] = [getattr(res, "id", res) for res in data["associated_resources"]]
        if data.get("associated_prompts"):
            data["associated_prompts"] = [getattr(prompt, "id", prompt) for prompt in data["associated_prompts"]]
        if data.get("associated_a2a_agents"):
            data["associated_a2a_agents"] = [getattr(agent, "id", agent) for agent in data["associated_a2a_agents"]]
        return data


class GatewayTestRequest(BaseModelWithConfigDict):
    """Schema for testing gateway connectivity.

    Includes the HTTP method, base URL, path, optional headers, body, and content type.
    """

    method: str = Field(..., description="HTTP method to test (GET, POST, etc.)")
    base_url: AnyHttpUrl = Field(..., description="Base URL of the gateway to test")
    path: str = Field(..., description="Path to append to the base URL")
    headers: Optional[Dict[str, str]] = Field(None, description="Optional headers for the request")
    body: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Optional body for the request, can be a string or JSON object")
    content_type: Optional[str] = Field("application/json", description="Content type for the request body")


class GatewayTestResponse(BaseModelWithConfigDict):
    """Schema for the response from a gateway test request.

    Contains:
    - HTTP status code
    - Latency in milliseconds
    - Optional response body, which can be a string or JSON object
    """

    status_code: int = Field(..., description="HTTP status code returned by the gateway")
    latency_ms: int = Field(..., description="Latency of the request in milliseconds")
    body: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Response body, can be a string or JSON object")


class TaggedEntity(BaseModelWithConfigDict):
    """A simplified representation of an entity that has a tag."""

    id: str = Field(..., description="The entity's ID")
    name: str = Field(..., description="The entity's name")
    type: str = Field(..., description="The entity type (tool, resource, prompt, server, gateway)")
    description: Optional[str] = Field(None, description="The entity's description")


class TagStats(BaseModelWithConfigDict):
    """Statistics for a single tag across all entity types."""

    tools: int = Field(default=0, description="Number of tools with this tag")
    resources: int = Field(default=0, description="Number of resources with this tag")
    prompts: int = Field(default=0, description="Number of prompts with this tag")
    servers: int = Field(default=0, description="Number of servers with this tag")
    gateways: int = Field(default=0, description="Number of gateways with this tag")
    total: int = Field(default=0, description="Total occurrences of this tag")


class TagInfo(BaseModelWithConfigDict):
    """Information about a single tag."""

    name: str = Field(..., description="The tag name")
    stats: TagStats = Field(..., description="Statistics for this tag")
    entities: Optional[List[TaggedEntity]] = Field(default_factory=list, description="Entities that have this tag")


class TopPerformer(BaseModelWithConfigDict):
    """Schema for representing top-performing entities with performance metrics.

    Used to encapsulate metrics for entities such as prompts, resources, servers, or tools,
    including execution count, average response time, success rate, and last execution timestamp.

    Attributes:
        id (Union[str, int]): Unique identifier for the entity.
        name (str): Name of the entity (e.g., prompt name, resource URI, server name, or tool name).
        execution_count (int): Total number of executions for the entity.
        avg_response_time (Optional[float]): Average response time in seconds, or None if no metrics.
        success_rate (Optional[float]): Success rate percentage, or None if no metrics.
        last_execution (Optional[datetime]): Timestamp of the last execution, or None if no metrics.
    """

    id: Union[str, int] = Field(..., description="Entity ID")
    name: str = Field(..., description="Entity name")
    execution_count: int = Field(..., description="Number of executions")
    avg_response_time: Optional[float] = Field(None, description="Average response time in seconds")
    success_rate: Optional[float] = Field(None, description="Success rate percentage")
    last_execution: Optional[datetime] = Field(None, description="Timestamp of last execution")


# --- A2A Agent Schemas ---


class A2AAgentCreate(BaseModel):
    """
    Schema for creating a new A2A (Agent-to-Agent) compatible agent.

    Attributes:
        model_config (ConfigDict): Configuration for the model.
        name (str): Unique name for the agent.
        description (Optional[str]): Optional description of the agent.
        endpoint_url (str): URL endpoint for the agent.
        agent_type (str): Type of agent (e.g., "openai", "anthropic", "custom").
        protocol_version (str): A2A protocol version supported.
        capabilities (Dict[str, Any]): Agent capabilities and features.
        config (Dict[str, Any]): Agent-specific configuration parameters.
        auth_type (Optional[str]): Type of authentication ("api_key", "oauth", "bearer", etc.).
        auth_username (Optional[str]): Username for basic authentication.
        auth_password (Optional[str]): Password for basic authentication.
        auth_token (Optional[str]): Token for bearer authentication.
        auth_header_key (Optional[str]): Key for custom headers authentication.
        auth_header_value (Optional[str]): Value for custom headers authentication.
        auth_headers (Optional[List[Dict[str, str]]]): List of custom headers for authentication.
        auth_value (Optional[str]): Alias for authentication value, used for better access post-validation.
        tags (List[str]): Tags for categorizing the agent.
        team_id (Optional[str]): Team ID for resource organization.
        visibility (str): Visibility level ("private", "team", "public").
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., description="Unique name for the agent")
    slug: Optional[str] = Field(None, description="Optional slug for the agent (auto-generated if not provided)")
    description: Optional[str] = Field(None, description="Agent description")
    endpoint_url: str = Field(..., description="URL endpoint for the agent")
    agent_type: str = Field(default="generic", description="Type of agent (e.g., 'openai', 'anthropic', 'custom')")
    protocol_version: str = Field(default="1.0", description="A2A protocol version supported")
    capabilities: Dict[str, Any] = Field(default_factory=dict, description="Agent capabilities and features")
    config: Dict[str, Any] = Field(default_factory=dict, description="Agent-specific configuration parameters")
    passthrough_headers: Optional[List[str]] = Field(default=None, description="List of headers allowed to be passed through from client to target")
    # Authorizations
    auth_type: Optional[str] = Field(None, description="Type of authentication: basic, bearer, headers, oauth, or none")
    # Fields for various types of authentication
    auth_username: Optional[str] = Field(None, description="Username for basic authentication")
    auth_password: Optional[str] = Field(None, description="Password for basic authentication")
    auth_token: Optional[str] = Field(None, description="Token for bearer authentication")
    auth_header_key: Optional[str] = Field(None, description="Key for custom headers authentication")
    auth_header_value: Optional[str] = Field(None, description="Value for custom headers authentication")
    auth_headers: Optional[List[Dict[str, str]]] = Field(None, description="List of custom headers for authentication")

    # OAuth 2.0 configuration
    oauth_config: Optional[Dict[str, Any]] = Field(None, description="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes")

    # Adding `auth_value` as an alias for better access post-validation
    auth_value: Optional[str] = Field(None, validate_default=True)
    tags: List[str] = Field(default_factory=list, description="Tags for categorizing the agent")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the agent owner")
    visibility: Optional[str] = Field(default="public", description="Visibility level (private, team, public)")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings
        """
        return validate_tags_field(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate agent name

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "A2A Agent name")

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, v: str) -> str:
        """Validate agent endpoint URL

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_url(v, "Agent endpoint URL")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import A2AAgentCreate
            >>> A2AAgentCreate.validate_description('A safe description')
            'A safe description'
            >>> A2AAgentCreate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = A2AAgentCreate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("capabilities", "config")
    @classmethod
    def validate_json_fields(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate JSON structure depth

        Args:
            v (dict): Value to validate

        Returns:
            dict: Value if validated as safe
        """
        SecurityValidator.validate_json_depth(v)
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        """Validate visibility level.

        Args:
            v: Visibility value to validate

        Returns:
            Validated visibility value

        Raises:
            ValueError: If visibility is invalid
        """
        if v not in ["private", "team", "public"]:
            raise ValueError("Visibility must be one of: private, team, public")
        return v

    @field_validator("team_id")
    @classmethod
    def validate_team_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate team ID format.

        Args:
            v: Team ID to validate

        Returns:
            Validated team ID
        """
        if v is not None:
            return SecurityValidator.validate_uuid(v, "team_id")
        return v

    @field_validator("auth_value", mode="before")
    @classmethod
    def create_auth_value(cls, v, info):
        """
        This validator will run before the model is fully instantiated (mode="before")
        It will process the auth fields based on auth_type and generate auth_value.

        Args:
            v: Input url
            info: ValidationInfo containing auth_type

        Returns:
            str: Auth value
        """
        data = info.data
        auth_type = data.get("auth_type")

        if (auth_type is None) or (auth_type == ""):
            return v  # If no auth_type is provided, no need to create auth_value

        # Process the auth fields and generate auth_value based on auth_type
        auth_value = cls._process_auth_fields(info)
        return auth_value

    @staticmethod
    def _process_auth_fields(info: ValidationInfo) -> Optional[str]:
        """
        Processes the input authentication fields and returns the correct auth_value.
        This method is called based on the selected auth_type.

        Args:
            info: ValidationInfo containing auth fields

        Returns:
            Encoded auth string or None

        Raises:
            ValueError: If auth_type is invalid
        """
        data = info.data
        auth_type = data.get("auth_type")

        if auth_type == "basic":
            # For basic authentication, both username and password must be present
            username = data.get("auth_username")
            password = data.get("auth_password")

            if not username or not password:
                raise ValueError("For 'basic' auth, both 'auth_username' and 'auth_password' must be provided.")

            creds = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode()
            return encode_auth({"Authorization": f"Basic {creds}"})

        if auth_type == "bearer":
            # For bearer authentication, only token is required
            token = data.get("auth_token")

            if not token:
                raise ValueError("For 'bearer' auth, 'auth_token' must be provided.")

            return encode_auth({"Authorization": f"Bearer {token}"})

        if auth_type == "oauth":
            # For OAuth authentication, we don't encode anything here
            # The OAuth configuration is handled separately in the oauth_config field
            # This method is only called for traditional auth types
            return None

        if auth_type == "authheaders":
            # Support both new multi-headers format and legacy single header format
            auth_headers = data.get("auth_headers")
            if auth_headers and isinstance(auth_headers, list):
                # New multi-headers format with enhanced validation
                header_dict = {}
                duplicate_keys = set()

                for header in auth_headers:
                    if not isinstance(header, dict):
                        continue

                    key = header.get("key")
                    value = header.get("value", "")

                    # Skip headers without keys
                    if not key:
                        continue

                    # Track duplicate keys (last value wins)
                    if key in header_dict:
                        duplicate_keys.add(key)

                    # Validate header key format (basic HTTP header validation)
                    if not all(c.isalnum() or c in "-_" for c in key.replace(" ", "")):
                        raise ValueError(f"Invalid header key format: '{key}'. Header keys should contain only alphanumeric characters, hyphens, and underscores.")

                    # Store header (empty values are allowed)
                    header_dict[key] = value

                # Ensure at least one valid header
                if not header_dict:
                    raise ValueError("For 'headers' auth, at least one valid header with a key must be provided.")

                # Warn about duplicate keys (optional - could log this instead)
                if duplicate_keys:
                    logging.warning(f"Duplicate header keys detected (last value used): {', '.join(duplicate_keys)}")

                # Check for excessive headers (prevent abuse)
                if len(header_dict) > 100:
                    raise ValueError("Maximum of 100 headers allowed per gateway.")

                return encode_auth(header_dict)

            # Legacy single header format (backward compatibility)
            header_key = data.get("auth_header_key")
            header_value = data.get("auth_header_value")

            if not header_key or not header_value:
                raise ValueError("For 'headers' auth, either 'auth_headers' list or both 'auth_header_key' and 'auth_header_value' must be provided.")

            return encode_auth({header_key: header_value})

        if auth_type == "one_time_auth":
            # One-time auth does not require encoding here
            return None

        raise ValueError("Invalid 'auth_type'. Must be one of: basic, bearer, oauth, or headers.")


class A2AAgentUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing A2A agent.

    Similar to A2AAgentCreate but all fields are optional to allow partial updates.
    """

    name: Optional[str] = Field(None, description="Unique name for the agent")
    description: Optional[str] = Field(None, description="Agent description")
    endpoint_url: Optional[str] = Field(None, description="URL endpoint for the agent")
    agent_type: Optional[str] = Field(None, description="Type of agent")
    protocol_version: Optional[str] = Field(None, description="A2A protocol version supported")
    capabilities: Optional[Dict[str, Any]] = Field(None, description="Agent capabilities and features")
    config: Optional[Dict[str, Any]] = Field(None, description="Agent-specific configuration parameters")
    passthrough_headers: Optional[List[str]] = Field(default=None, description="List of headers allowed to be passed through from client to target")
    auth_type: Optional[str] = Field(None, description="Type of authentication")
    auth_username: Optional[str] = Field(None, description="username for basic authentication")
    auth_password: Optional[str] = Field(None, description="password for basic authentication")
    auth_token: Optional[str] = Field(None, description="token for bearer authentication")
    auth_header_key: Optional[str] = Field(None, description="key for custom headers authentication")
    auth_header_value: Optional[str] = Field(None, description="value for custom headers authentication")
    auth_headers: Optional[List[Dict[str, str]]] = Field(None, description="List of custom headers for authentication")

    # Adding `auth_value` as an alias for better access post-validation
    auth_value: Optional[str] = Field(None, validate_default=True)

    # OAuth 2.0 configuration
    oauth_config: Optional[Dict[str, Any]] = Field(None, description="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes")

    tags: Optional[List[str]] = Field(None, description="Tags for categorizing the agent")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="Team ID for resource organization")
    owner_email: Optional[str] = Field(None, description="Email of the agent owner")
    visibility: Optional[str] = Field(None, description="Visibility level (private, team, public)")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate and normalize tags.

        Args:
            v: Optional list of tag strings to validate

        Returns:
            List of validated tag strings or None if input is None
        """
        if v is None:
            return None
        return validate_tags_field(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate agent name

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "A2A Agent name")

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, v: str) -> str:
        """Validate agent endpoint URL

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_url(v, "Agent endpoint URL")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely, truncate if too long

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe and truncated if too long

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> from mcpgateway.schemas import A2AAgentUpdate
            >>> A2AAgentUpdate.validate_description('A safe description')
            'A safe description'
            >>> A2AAgentUpdate.validate_description(None) # Test None case
            >>> long_desc = 'x' * SecurityValidator.MAX_DESCRIPTION_LENGTH
            >>> truncated = A2AAgentUpdate.validate_description(long_desc)
            >>> len(truncated) - SecurityValidator.MAX_DESCRIPTION_LENGTH
            0
            >>> truncated == long_desc[:SecurityValidator.MAX_DESCRIPTION_LENGTH]
            True
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            # Truncate the description to the maximum allowed length
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("capabilities", "config")
    @classmethod
    def validate_json_fields(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Validate JSON structure depth

        Args:
            v (dict): Value to validate

        Returns:
            dict: Value if validated as safe
        """
        if v is None:
            return v
        SecurityValidator.validate_json_depth(v)
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: Optional[str]) -> Optional[str]:
        """Validate visibility level.

        Args:
            v: Visibility value to validate

        Returns:
            Validated visibility value

        Raises:
            ValueError: If visibility is invalid
        """
        if v is not None and v not in ["private", "team", "public"]:
            raise ValueError("Visibility must be one of: private, team, public")
        return v

    @field_validator("team_id")
    @classmethod
    def validate_team_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate team ID format.

        Args:
            v: Team ID to validate

        Returns:
            Validated team ID
        """
        if v is not None:
            return SecurityValidator.validate_uuid(v, "team_id")
        return v

    @field_validator("auth_value", mode="before")
    @classmethod
    def create_auth_value(cls, v, info):
        """
        This validator will run before the model is fully instantiated (mode="before")
        It will process the auth fields based on auth_type and generate auth_value.

        Args:
            v: Input URL
            info: ValidationInfo containing auth_type

        Returns:
            str: Auth value or URL
        """
        data = info.data
        auth_type = data.get("auth_type")

        if (auth_type is None) or (auth_type == ""):
            return v  # If no auth_type is provided, no need to create auth_value

        # Process the auth fields and generate auth_value based on auth_type
        auth_value = cls._process_auth_fields(info)
        return auth_value

    @staticmethod
    def _process_auth_fields(info: ValidationInfo) -> Optional[str]:
        """
        Processes the input authentication fields and returns the correct auth_value.
        This method is called based on the selected auth_type.

        Args:
            info: ValidationInfo containing auth fields

        Returns:
            Encoded auth string or None

        Raises:
            ValueError: If auth type is invalid
        """

        data = info.data
        auth_type = data.get("auth_type")

        if auth_type == "basic":
            # For basic authentication, both username and password must be present
            username = data.get("auth_username")
            password = data.get("auth_password")
            if not username or not password:
                raise ValueError("For 'basic' auth, both 'auth_username' and 'auth_password' must be provided.")

            creds = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode()
            return encode_auth({"Authorization": f"Basic {creds}"})

        if auth_type == "bearer":
            # For bearer authentication, only token is required
            token = data.get("auth_token")

            if not token:
                raise ValueError("For 'bearer' auth, 'auth_token' must be provided.")

            return encode_auth({"Authorization": f"Bearer {token}"})

        if auth_type == "oauth":
            # For OAuth authentication, we don't encode anything here
            # The OAuth configuration is handled separately in the oauth_config field
            # This method is only called for traditional auth types
            return None

        if auth_type == "authheaders":
            # Support both new multi-headers format and legacy single header format
            auth_headers = data.get("auth_headers")
            if auth_headers and isinstance(auth_headers, list):
                # New multi-headers format with enhanced validation
                header_dict = {}
                duplicate_keys = set()

                for header in auth_headers:
                    if not isinstance(header, dict):
                        continue

                    key = header.get("key")
                    value = header.get("value", "")

                    # Skip headers without keys
                    if not key:
                        continue

                    # Track duplicate keys (last value wins)
                    if key in header_dict:
                        duplicate_keys.add(key)

                    # Validate header key format (basic HTTP header validation)
                    if not all(c.isalnum() or c in "-_" for c in key.replace(" ", "")):
                        raise ValueError(f"Invalid header key format: '{key}'. Header keys should contain only alphanumeric characters, hyphens, and underscores.")

                    # Store header (empty values are allowed)
                    header_dict[key] = value

                # Ensure at least one valid header
                if not header_dict:
                    raise ValueError("For 'headers' auth, at least one valid header with a key must be provided.")

                # Warn about duplicate keys (optional - could log this instead)
                if duplicate_keys:
                    logging.warning(f"Duplicate header keys detected (last value used): {', '.join(duplicate_keys)}")

                # Check for excessive headers (prevent abuse)
                if len(header_dict) > 100:
                    raise ValueError("Maximum of 100 headers allowed per gateway.")

                return encode_auth(header_dict)

            # Legacy single header format (backward compatibility)
            header_key = data.get("auth_header_key")
            header_value = data.get("auth_header_value")

            if not header_key or not header_value:
                raise ValueError("For 'headers' auth, either 'auth_headers' list or both 'auth_header_key' and 'auth_header_value' must be provided.")

            return encode_auth({header_key: header_value})

        if auth_type == "one_time_auth":
            # One-time auth does not require encoding here
            return None

        raise ValueError("Invalid 'auth_type'. Must be one of: basic, bearer, oauth, or headers.")


class A2AAgentRead(BaseModelWithConfigDict):
    """Schema for reading A2A agent information.

    Includes all agent fields plus:
    - Database ID
    - Slug
    - Creation/update timestamps
    - Enabled/reachable status
    - Metrics
    - Authentication type: basic, bearer, headers, oauth
    - Authentication value: username/password or token or custom headers
    - OAuth configuration for OAuth 2.0 authentication

    Auto Populated fields:
    - Authentication username: for basic auth
    - Authentication password: for basic auth
    - Authentication token: for bearer auth
    - Authentication header key: for headers auth
    - Authentication header value: for headers auth
    """

    id: Optional[str] = Field(None, description="Unique ID of the a2a agent")
    name: str = Field(..., description="Unique name for the a2a agent")
    slug: Optional[str] = Field(None, description="Slug for a2a agent endpoint URL")
    description: Optional[str] = Field(None, description="a2a agent description")
    endpoint_url: str = Field(..., description="a2a agent endpoint URL")
    agent_type: str
    protocol_version: str
    capabilities: Dict[str, Any]
    config: Dict[str, Any]
    enabled: bool
    reachable: bool
    created_at: datetime
    updated_at: datetime
    last_interaction: Optional[datetime]
    tags: List[Dict[str, str]] = Field(default_factory=list, description="Tags for categorizing the agent")
    metrics: Optional[A2AAgentMetrics] = Field(None, description="Agent metrics (may be None in list operations)")
    passthrough_headers: Optional[List[str]] = Field(default=None, description="List of headers allowed to be passed through from client to target")
    # Authorizations
    auth_type: Optional[str] = Field(None, description="auth_type: basic, bearer, headers, oauth, or None")
    auth_value: Optional[str] = Field(None, description="auth value: username/password or token or custom headers")

    # OAuth 2.0 configuration
    oauth_config: Optional[Dict[str, Any]] = Field(None, description="OAuth 2.0 configuration including grant_type, client_id, encrypted client_secret, URLs, and scopes")

    # auth_value will populate the following fields
    auth_username: Optional[str] = Field(None, description="username for basic authentication")
    auth_password: Optional[str] = Field(None, description="password for basic authentication")
    auth_token: Optional[str] = Field(None, description="token for bearer authentication")
    auth_header_key: Optional[str] = Field(None, description="key for custom headers authentication")
    auth_header_value: Optional[str] = Field(None, description="vallue for custom headers authentication")

    # Comprehensive metadata for audit tracking
    created_by: Optional[str] = Field(None, description="Username who created this entity")
    created_from_ip: Optional[str] = Field(None, description="IP address of creator")
    created_via: Optional[str] = Field(None, description="Creation method: ui|api|import|federation")
    created_user_agent: Optional[str] = Field(None, description="User agent of creation request")

    modified_by: Optional[str] = Field(None, description="Username who last modified this entity")
    modified_from_ip: Optional[str] = Field(None, description="IP address of last modifier")
    modified_via: Optional[str] = Field(None, description="Modification method")
    modified_user_agent: Optional[str] = Field(None, description="User agent of modification request")

    import_batch_id: Optional[str] = Field(None, description="UUID of bulk import batch")
    federation_source: Optional[str] = Field(None, description="Source gateway for federated entities")
    version: Optional[int] = Field(1, description="Entity version for change tracking")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="ID of the team that owns this resource")
    team: Optional[str] = Field(None, description="Name of the team that owns this resource")
    owner_email: Optional[str] = Field(None, description="Email of the user who owns this resource")
    visibility: Optional[str] = Field(default="public", description="Visibility level: private, team, or public")

    # This will be the main method to automatically populate fields
    @model_validator(mode="after")
    def _populate_auth(self) -> Self:
        """Populate authentication fields based on auth_type and encoded auth_value.

        This post-validation method decodes the stored authentication value and
        populates the appropriate authentication fields (username/password, token,
        or custom headers) based on the authentication type. It ensures the
        authentication data is properly formatted and accessible through individual
        fields for display purposes.

        The method handles three authentication types:
        - basic: Extracts username and password from Authorization header
        - bearer: Extracts token from Bearer Authorization header
        - authheaders: Extracts custom header key/value pair

        Returns:
            Self: The instance with populated authentication fields:
                - For basic: auth_username and auth_password
                - For bearer: auth_token
                - For authheaders: auth_header_key and auth_header_value

        Raises:
            ValueError: If the authentication data is malformed:
                    - Basic auth missing username or password
                    - Bearer auth missing or improperly formatted Authorization header
                    - Custom headers not exactly one key/value pair

        Examples:
            >>> # Basic auth example
            >>> string_bytes = "admin:secret".encode("utf-8")
            >>> encoded_auth = base64.urlsafe_b64encode(string_bytes).decode("utf-8")
            >>> values = GatewayRead.model_construct(
            ...     auth_type="basic",
            ...     auth_value=encode_auth({"Authorization": f"Basic {encoded_auth}"})
            ... )
            >>> values = A2AAgentRead._populate_auth(values)
            >>> values.auth_username
            'admin'
            >>> values.auth_password
            'secret'

            >>> # Bearer auth example
            >>> values = A2AAgentRead.model_construct(
            ...     auth_type="bearer",
            ...     auth_value=encode_auth({"Authorization": "Bearer mytoken123"})
            ... )
            >>> values = A2AAgentRead._populate_auth(values)
            >>> values.auth_token
            'mytoken123'

            >>> # Custom headers example
            >>> values = A2AAgentRead.model_construct(
            ...     auth_type='authheaders',
            ...     auth_value=encode_auth({"X-API-Key": "abc123"})
            ... )
            >>> values = A2AAgentRead._populate_auth(values)
            >>> values.auth_header_key
            'X-API-Key'
            >>> values.auth_header_value
            'abc123'
        """
        auth_type = self.auth_type
        auth_value_encoded = self.auth_value
        # Skip validation logic if masked value
        if auth_value_encoded == settings.masked_auth_value:
            return self

        # Handle OAuth authentication (no auth_value to decode)
        if auth_type == "oauth":
            # OAuth gateways don't have traditional auth_value to decode
            # They use oauth_config instead
            return self

        if auth_type == "one_time_auth":
            return self

        # If no encoded value is present, nothing to populate
        if not auth_value_encoded:
            return self

        auth_value = decode_auth(auth_value_encoded)
        if auth_type == "basic":
            auth = auth_value.get("Authorization")
            if not (isinstance(auth, str) and auth.startswith("Basic ")):
                raise ValueError("basic auth requires an Authorization header of the form 'Basic <base64>'")
            auth = auth.removeprefix("Basic ")
            u, p = base64.urlsafe_b64decode(auth).decode("utf-8").split(":")
            if not u or not p:
                raise ValueError("basic auth requires both username and password")
            self.auth_username, self.auth_password = u, p

        elif auth_type == "bearer":
            auth = auth_value.get("Authorization")
            if not (isinstance(auth, str) and auth.startswith("Bearer ")):
                raise ValueError("bearer auth requires an Authorization header of the form 'Bearer <token>'")
            self.auth_token = auth.removeprefix("Bearer ")

        elif auth_type == "authheaders":
            # For backward compatibility, populate first header in key/value fields
            if len(auth_value) == 0:
                raise ValueError("authheaders requires at least one key/value pair")
            k, v = next(iter(auth_value.items()))
            self.auth_header_key, self.auth_header_value = k, v
        return self

    def masked(self) -> "A2AAgentRead":
        """
        Return a masked version of the model instance with sensitive authentication fields hidden.

        This method creates a dictionary representation of the model data and replaces sensitive fields
        such as `auth_value`, `auth_password`, `auth_token`, and `auth_header_value` with a masked
        placeholder value defined in `settings.masked_auth_value`. Masking is only applied if the fields
        are present and not already masked.

        Args:
            None

        Returns:
            A2AAgentRead: A new instance of the A2AAgentRead model with sensitive authentication-related fields
            masked to prevent exposure of sensitive information.

        Notes:
            - The `auth_value` field is only masked if it exists and its value is different from the masking
            placeholder.
            - Other sensitive fields (`auth_password`, `auth_token`, `auth_header_value`) are masked if present.
            - Fields not related to authentication remain unmodified.
        """
        masked_data = self.model_dump()

        # Only mask if auth_value is present and not already masked
        if masked_data.get("auth_value") and masked_data["auth_value"] != settings.masked_auth_value:
            masked_data["auth_value"] = settings.masked_auth_value

        masked_data["auth_password"] = settings.masked_auth_value if masked_data.get("auth_password") else None
        masked_data["auth_token"] = settings.masked_auth_value if masked_data.get("auth_token") else None
        masked_data["auth_header_value"] = settings.masked_auth_value if masked_data.get("auth_header_value") else None

        return A2AAgentRead.model_validate(masked_data)


class A2AAgentInvocation(BaseModelWithConfigDict):
    """Schema for A2A agent invocation requests.

    Contains:
    - Agent name or ID to invoke
    - Parameters for the agent interaction
    - Interaction type (query, execute, etc.)
    """

    agent_name: str = Field(..., description="Name of the A2A agent to invoke")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameters for agent interaction")
    interaction_type: str = Field(default="query", description="Type of interaction (query, execute, etc.)")

    @field_validator("agent_name")
    @classmethod
    def validate_agent_name(cls, v: str) -> str:
        """Ensure agent names follow naming conventions

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
        return SecurityValidator.validate_name(v, "Agent name")

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate parameters structure depth to prevent DoS attacks.

        Args:
            v (dict): Parameters dictionary to validate

        Returns:
            dict: The validated parameters if within depth limits

        Raises:
            ValueError: If the parameters exceed the maximum allowed depth
        """
        SecurityValidator.validate_json_depth(v)
        return v


# ---------------------------------------------------------------------------
# Email-Based Authentication Schemas
# ---------------------------------------------------------------------------


class EmailLoginRequest(BaseModel):
    """Request schema for email login.

    Attributes:
        email: User's email address
        password: User's password

    Examples:
        >>> request = EmailLoginRequest(email="user@example.com", password="secret123")
        >>> request.email
        'user@example.com'
        >>> request.password
        'secret123'
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=1, description="User's password")


class EmailRegistrationRequest(BaseModel):
    """Request schema for user registration.

    Attributes:
        email: User's email address
        password: User's password
        full_name: Optional full name for display
        is_admin: Whether user should have admin privileges (default: False)

    Examples:
        >>> request = EmailRegistrationRequest(
        ...     email="new@example.com",
        ...     password="secure123",
        ...     full_name="New User"
        ... )
        >>> request.email
        'new@example.com'
        >>> request.full_name
        'New User'
        >>> request.is_admin
        False
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=8, description="User's password")
    full_name: Optional[str] = Field(None, max_length=255, description="User's full name")
    is_admin: bool = Field(False, description="Grant admin privileges to user")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password meets minimum requirements.

        Args:
            v: Password string to validate

        Returns:
            str: Validated password

        Raises:
            ValueError: If password doesn't meet requirements
        """
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v


class ChangePasswordRequest(BaseModel):
    """Request schema for password change.

    Attributes:
        old_password: Current password for verification
        new_password: New password to set

    Examples:
        >>> request = ChangePasswordRequest(
        ...     old_password="old_secret",
        ...     new_password="new_secure_password"
        ... )
        >>> request.old_password
        'old_secret'
        >>> request.new_password
        'new_secure_password'
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    old_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(..., min_length=8, description="New password")

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        """Validate new password meets minimum requirements.

        Args:
            v: New password string to validate

        Returns:
            str: Validated new password

        Raises:
            ValueError: If new password doesn't meet requirements
        """
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters long")
        return v


class EmailUserResponse(BaseModel):
    """Response schema for user information.

    Attributes:
        email: User's email address
        full_name: User's full name
        is_admin: Whether user has admin privileges
        is_active: Whether account is active
        auth_provider: Authentication provider used
        created_at: Account creation timestamp
        last_login: Last successful login timestamp
        email_verified: Whether email is verified

    Examples:
        >>> user = EmailUserResponse(
        ...     email="user@example.com",
        ...     full_name="Test User",
        ...     is_admin=False,
        ...     is_active=True,
        ...     auth_provider="local",
        ...     created_at=datetime.now(),
        ...     last_login=None,
        ...     email_verified=False
        ... )
        >>> user.email
        'user@example.com'
        >>> user.is_admin
        False
    """

    model_config = ConfigDict(from_attributes=True)

    email: str = Field(..., description="User's email address")
    full_name: Optional[str] = Field(None, description="User's full name")
    is_admin: bool = Field(..., description="Whether user has admin privileges")
    is_active: bool = Field(..., description="Whether account is active")
    auth_provider: str = Field(..., description="Authentication provider")
    created_at: datetime = Field(..., description="Account creation timestamp")
    last_login: Optional[datetime] = Field(None, description="Last successful login")
    email_verified: bool = Field(False, description="Whether email is verified")
    password_change_required: bool = Field(False, description="Whether user must change password on next login")

    @classmethod
    def from_email_user(cls, user) -> "EmailUserResponse":
        """Create response from EmailUser model.

        Args:
            user: EmailUser model instance

        Returns:
            EmailUserResponse: Response schema instance
        """
        return cls(
            email=user.email,
            full_name=user.full_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            auth_provider=user.auth_provider,
            created_at=user.created_at,
            last_login=user.last_login,
            email_verified=user.is_email_verified(),
            password_change_required=user.password_change_required,
        )


class AuthenticationResponse(BaseModel):
    """Response schema for successful authentication.

    Attributes:
        access_token: JWT token for API access
        token_type: Type of token (always 'bearer')
        expires_in: Token expiration time in seconds
        user: User information

    Examples:
        >>> from datetime import datetime
        >>> response = AuthenticationResponse(
        ...     access_token="jwt.token.here",
        ...     token_type="bearer",
        ...     expires_in=3600,
        ...     user=EmailUserResponse(
        ...         email="user@example.com",
        ...         full_name="Test User",
        ...         is_admin=False,
        ...         is_active=True,
        ...         auth_provider="local",
        ...         created_at=datetime.now(),
        ...         last_login=None,
        ...         email_verified=False
        ...     )
        ... )
        >>> response.token_type
        'bearer'
        >>> response.user.email
        'user@example.com'
    """

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration in seconds")
    user: EmailUserResponse = Field(..., description="User information")


class AuthEventResponse(BaseModel):
    """Response schema for authentication events.

    Attributes:
        id: Event ID
        timestamp: Event timestamp
        user_email: User's email address
        event_type: Type of authentication event
        success: Whether the event was successful
        ip_address: Client IP address
        failure_reason: Reason for failure (if applicable)

    Examples:
        >>> from datetime import datetime
        >>> event = AuthEventResponse(
        ...     id=1,
        ...     timestamp=datetime.now(),
        ...     user_email="user@example.com",
        ...     event_type="login",
        ...     success=True,
        ...     ip_address="192.168.1.1",
        ...     failure_reason=None
        ... )
        >>> event.event_type
        'login'
        >>> event.success
        True
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Event ID")
    timestamp: datetime = Field(..., description="Event timestamp")
    user_email: Optional[str] = Field(None, description="User's email address")
    event_type: str = Field(..., description="Type of authentication event")
    success: bool = Field(..., description="Whether the event was successful")
    ip_address: Optional[str] = Field(None, description="Client IP address")
    failure_reason: Optional[str] = Field(None, description="Reason for failure")


class UserListResponse(BaseModel):
    """Response schema for user list.

    Attributes:
        users: List of users
        total_count: Total number of users
        limit: Request limit
        offset: Request offset

    Examples:
        >>> user_list = UserListResponse(
        ...     users=[],
        ...     total_count=0,
        ...     limit=10,
        ...     offset=0
        ... )
        >>> user_list.total_count
        0
        >>> len(user_list.users)
        0
    """

    users: list[EmailUserResponse] = Field(..., description="List of users")
    total_count: int = Field(..., description="Total number of users")
    limit: int = Field(..., description="Request limit")
    offset: int = Field(..., description="Request offset")


class AdminUserCreateRequest(BaseModel):
    """Request schema for admin user creation.

    Attributes:
        email: User's email address
        password: User's password
        full_name: Optional full name
        is_admin: Whether user should have admin privileges

    Examples:
        >>> request = AdminUserCreateRequest(
        ...     email="admin@example.com",
        ...     password="admin_password",
        ...     full_name="Admin User",
        ...     is_admin=True
        ... )
        >>> request.email
        'admin@example.com'
        >>> request.is_admin
        True
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=8, description="User's password")
    full_name: Optional[str] = Field(None, max_length=255, description="User's full name")
    is_admin: bool = Field(default=False, description="Whether user has admin privileges")


class AdminUserUpdateRequest(BaseModel):
    """Request schema for admin user updates.

    Attributes:
        full_name: User's full name
        is_admin: Whether user has admin privileges
        is_active: Whether account is active

    Examples:
        >>> request = AdminUserUpdateRequest(
        ...     full_name="Updated Name",
        ...     is_admin=True,
        ...     is_active=True
        ... )
        >>> request.full_name
        'Updated Name'
        >>> request.is_admin
        True
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: Optional[str] = Field(None, max_length=255, description="User's full name")
    is_admin: Optional[bool] = Field(None, description="Whether user has admin privileges")
    is_active: Optional[bool] = Field(None, description="Whether account is active")


class ErrorResponse(BaseModel):
    """Standard error response schema.

    Attributes:
        error: Error type
        message: Human-readable error message
        details: Additional error details

    Examples:
        >>> error = ErrorResponse(
        ...     error="authentication_failed",
        ...     message="Invalid email or password",
        ...     details=None
        ... )
        >>> error.error
        'authentication_failed'
        >>> error.message
        'Invalid email or password'
    """

    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[dict] = Field(None, description="Additional error details")


class SuccessResponse(BaseModel):
    """Standard success response schema.

    Attributes:
        success: Whether operation was successful
        message: Human-readable success message

    Examples:
        >>> response = SuccessResponse(
        ...     success=True,
        ...     message="Password changed successfully"
        ... )
        >>> response.success
        True
        >>> response.message
        'Password changed successfully'
    """

    success: bool = Field(True, description="Operation success status")
    message: str = Field(..., description="Human-readable success message")


# ---------------------------------------------------------------------------
# Team Management Schemas
# ---------------------------------------------------------------------------


class TeamCreateRequest(BaseModel):
    """Schema for creating a new team.

    Attributes:
        name: Team display name
        slug: URL-friendly team identifier (optional, auto-generated if not provided)
        description: Team description
        visibility: Team visibility level
        max_members: Maximum number of members allowed

    Examples:
        >>> request = TeamCreateRequest(
        ...     name="Engineering Team",
        ...     description="Software development team"
        ... )
        >>> request.name
        'Engineering Team'
        >>> request.visibility
        'private'
        >>> request.slug is None
        True
        >>>
        >>> # Test with all fields
        >>> full_request = TeamCreateRequest(
        ...     name="DevOps Team",
        ...     slug="devops-team",
        ...     description="Infrastructure and deployment team",
        ...     visibility="public",
        ...     max_members=50
        ... )
        >>> full_request.slug
        'devops-team'
        >>> full_request.max_members
        50
        >>> full_request.visibility
        'public'
        >>>
        >>> # Test validation
        >>> try:
        ...     TeamCreateRequest(name="   ", description="test")
        ... except ValueError as e:
        ...     "empty" in str(e).lower()
        True
        >>>
        >>> # Test slug validation
        >>> try:
        ...     TeamCreateRequest(name="Test", slug="Invalid_Slug")
        ... except ValueError:
        ...     True
        True
        >>>
        >>> # Test valid slug patterns
        >>> valid_slug = TeamCreateRequest(name="Test", slug="valid-slug-123")
        >>> valid_slug.slug
        'valid-slug-123'
    """

    name: str = Field(..., min_length=1, max_length=255, description="Team display name")
    slug: Optional[str] = Field(None, min_length=2, max_length=255, pattern="^[a-z0-9-]+$", description="URL-friendly team identifier")
    description: Optional[str] = Field(None, max_length=1000, description="Team description")
    visibility: Literal["private", "public"] = Field("private", description="Team visibility level")
    max_members: Optional[int] = Field(default=None, description="Maximum number of team members")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate team name.

        Args:
            v: Team name to validate

        Returns:
            str: Validated and stripped team name

        Raises:
            ValueError: If team name is empty
        """
        if not v.strip():
            raise ValueError("Team name cannot be empty")
        return v.strip()

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: Optional[str]) -> Optional[str]:
        """Validate team slug.

        Args:
            v: Team slug to validate

        Returns:
            Optional[str]: Validated and formatted slug or None

        Raises:
            ValueError: If slug format is invalid
        """
        if v is None:
            return v
        v = v.strip().lower()
        # Uses precompiled regex for slug validation
        if not _SLUG_RE.match(v):
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens")
        if v.startswith("-") or v.endswith("-"):
            raise ValueError("Slug cannot start or end with hyphens")
        return v


class TeamUpdateRequest(BaseModel):
    """Schema for updating a team.

    Attributes:
        name: Team display name
        description: Team description
        visibility: Team visibility level
        max_members: Maximum number of members allowed

    Examples:
        >>> request = TeamUpdateRequest(
        ...     name="Updated Engineering Team",
        ...     description="Updated description"
        ... )
        >>> request.name
        'Updated Engineering Team'
    """

    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Team display name")
    description: Optional[str] = Field(None, max_length=1000, description="Team description")
    visibility: Optional[Literal["private", "public"]] = Field(None, description="Team visibility level")
    max_members: Optional[int] = Field(default=None, description="Maximum number of team members")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate team name.

        Args:
            v: Team name to validate

        Returns:
            Optional[str]: Validated and stripped team name or None

        Raises:
            ValueError: If team name is empty
        """
        if v is not None:
            if not v.strip():
                raise ValueError("Team name cannot be empty")
            return v.strip()
        return v


class TeamResponse(BaseModel):
    """Schema for team response data.

    Attributes:
        id: Team UUID
        name: Team display name
        slug: URL-friendly team identifier
        description: Team description
        created_by: Email of team creator
        is_personal: Whether this is a personal team
        visibility: Team visibility level
        max_members: Maximum number of members allowed
        member_count: Current number of team members
        created_at: Team creation timestamp
        updated_at: Last update timestamp
        is_active: Whether the team is active

    Examples:
        >>> team = TeamResponse(
        ...     id="team-123",
        ...     name="Engineering Team",
        ...     slug="engineering-team",
        ...     created_by="admin@example.com",
        ...     is_personal=False,
        ...     visibility="private",
        ...     member_count=5,
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     is_active=True
        ... )
        >>> team.name
        'Engineering Team'
    """

    id: str = Field(..., description="Team UUID")
    name: str = Field(..., description="Team display name")
    slug: str = Field(..., description="URL-friendly team identifier")
    description: Optional[str] = Field(None, description="Team description")
    created_by: str = Field(..., description="Email of team creator")
    is_personal: bool = Field(..., description="Whether this is a personal team")
    visibility: Optional[str] = Field(..., description="Team visibility level")
    max_members: Optional[int] = Field(None, description="Maximum number of members allowed")
    member_count: int = Field(..., description="Current number of team members")
    created_at: datetime = Field(..., description="Team creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    is_active: bool = Field(..., description="Whether the team is active")


class TeamMemberResponse(BaseModel):
    """Schema for team member response data.

    Attributes:
        id: Member UUID
        team_id: Team UUID
        user_email: Member email address
        role: Member role in the team
        joined_at: When the member joined
        invited_by: Email of user who invited this member
        is_active: Whether the membership is active

    Examples:
        >>> member = TeamMemberResponse(
        ...     id="member-123",
        ...     team_id="team-123",
        ...     user_email="user@example.com",
        ...     role="member",
        ...     joined_at=datetime.now(timezone.utc),
        ...     is_active=True
        ... )
        >>> member.role
        'member'
    """

    id: str = Field(..., description="Member UUID")
    team_id: str = Field(..., description="Team UUID")
    user_email: str = Field(..., description="Member email address")
    role: str = Field(..., description="Member role in the team")
    joined_at: datetime = Field(..., description="When the member joined")
    invited_by: Optional[str] = Field(None, description="Email of user who invited this member")
    is_active: bool = Field(..., description="Whether the membership is active")


class TeamInviteRequest(BaseModel):
    """Schema for inviting users to a team.

    Attributes:
        email: Email address of user to invite
        role: Role to assign to the user

    Examples:
        >>> invite = TeamInviteRequest(
        ...     email="newuser@example.com",
        ...     role="member"
        ... )
        >>> invite.email
        'newuser@example.com'
    """

    email: EmailStr = Field(..., description="Email address of user to invite")
    role: Literal["owner", "member"] = Field("member", description="Role to assign to the user")


class TeamInvitationResponse(BaseModel):
    """Schema for team invitation response data.

    Attributes:
        id: Invitation UUID
        team_id: Team UUID
        team_name: Team display name
        email: Email address of invited user
        role: Role the user will have when they accept
        invited_by: Email of user who sent the invitation
        invited_at: When the invitation was sent
        expires_at: When the invitation expires
        token: Invitation token
        is_active: Whether the invitation is active
        is_expired: Whether the invitation has expired

    Examples:
        >>> invitation = TeamInvitationResponse(
        ...     id="invite-123",
        ...     team_id="team-123",
        ...     team_name="Engineering Team",
        ...     email="newuser@example.com",
        ...     role="member",
        ...     invited_by="admin@example.com",
        ...     invited_at=datetime.now(timezone.utc),
        ...     expires_at=datetime.now(timezone.utc),
        ...     token="invitation-token",
        ...     is_active=True,
        ...     is_expired=False
        ... )
        >>> invitation.role
        'member'
    """

    id: str = Field(..., description="Invitation UUID")
    team_id: str = Field(..., description="Team UUID")
    team_name: str = Field(..., description="Team display name")
    email: str = Field(..., description="Email address of invited user")
    role: str = Field(..., description="Role the user will have when they accept")
    invited_by: str = Field(..., description="Email of user who sent the invitation")
    invited_at: datetime = Field(..., description="When the invitation was sent")
    expires_at: datetime = Field(..., description="When the invitation expires")
    token: str = Field(..., description="Invitation token")
    is_active: bool = Field(..., description="Whether the invitation is active")
    is_expired: bool = Field(..., description="Whether the invitation has expired")


class TeamMemberUpdateRequest(BaseModel):
    """Schema for updating a team member's role.

    Attributes:
        role: New role for the team member

    Examples:
        >>> update = TeamMemberUpdateRequest(role="member")
        >>> update.role
        'member'
    """

    role: Literal["owner", "member"] = Field(..., description="New role for the team member")


class TeamListResponse(BaseModel):
    """Schema for team list response.

    Attributes:
        teams: List of teams
        total: Total number of teams

    Examples:
        >>> response = TeamListResponse(teams=[], total=0)
        >>> response.total
        0
    """

    teams: List[TeamResponse] = Field(..., description="List of teams")
    total: int = Field(..., description="Total number of teams")


class TeamDiscoveryResponse(BaseModel):
    """Schema for public team discovery response.

    Provides limited metadata about public teams for discovery purposes.

    Attributes:
        id: Team ID
        name: Team name
        description: Team description
        member_count: Number of members
        created_at: Team creation timestamp
        is_joinable: Whether the current user can join this team
    """

    id: str = Field(..., description="Team ID")
    name: str = Field(..., description="Team name")
    description: Optional[str] = Field(None, description="Team description")
    member_count: int = Field(..., description="Number of team members")
    created_at: datetime = Field(..., description="Team creation timestamp")
    is_joinable: bool = Field(..., description="Whether the current user can join this team")


class TeamJoinRequest(BaseModel):
    """Schema for requesting to join a public team.

    Attributes:
        message: Optional message to team owners
    """

    message: Optional[str] = Field(None, description="Optional message to team owners", max_length=500)


class TeamJoinRequestResponse(BaseModel):
    """Schema for team join request response.

    Attributes:
        id: Join request ID
        team_id: Target team ID
        team_name: Target team name
        user_email: Requesting user email
        message: Request message
        status: Request status (pending, approved, rejected)
        requested_at: Request timestamp
        expires_at: Request expiration timestamp
    """

    id: str = Field(..., description="Join request ID")
    team_id: str = Field(..., description="Target team ID")
    team_name: str = Field(..., description="Target team name")
    user_email: str = Field(..., description="Requesting user email")
    message: Optional[str] = Field(None, description="Request message")
    status: str = Field(..., description="Request status")
    requested_at: datetime = Field(..., description="Request timestamp")
    expires_at: datetime = Field(..., description="Request expiration")


# API Token Management Schemas


class TokenScopeRequest(BaseModel):
    """Schema for token scoping configuration.

    Attributes:
        server_id: Optional server ID limitation
        permissions: List of permission scopes
        ip_restrictions: List of IP address/CIDR restrictions
        time_restrictions: Time-based access limitations
        usage_limits: Rate limiting and quota settings

    Examples:
        >>> scope = TokenScopeRequest(
        ...     server_id="server-123",
        ...     permissions=["tools.read", "resources.read"],
        ...     ip_restrictions=["192.168.1.0/24"]
        ... )
        >>> scope.server_id
        'server-123'
    """

    server_id: Optional[str] = Field(None, description="Limit token to specific server")
    permissions: List[str] = Field(default_factory=list, description="Permission scopes")
    ip_restrictions: List[str] = Field(default_factory=list, description="IP address restrictions")
    time_restrictions: Dict[str, Any] = Field(default_factory=dict, description="Time-based restrictions")
    usage_limits: Dict[str, Any] = Field(default_factory=dict, description="Usage limits and quotas")


class TokenCreateRequest(BaseModel):
    """Schema for creating a new API token.

    Attributes:
        name: Human-readable token name
        description: Optional token description
        expires_in_days: Optional expiry in days
        scope: Optional token scoping configuration
        tags: Optional organizational tags

    Examples:
        >>> request = TokenCreateRequest(
        ...     name="Production Access",
        ...     description="Read-only production access",
        ...     expires_in_days=30,
        ...     tags=["production", "readonly"]
        ... )
        >>> request.name
        'Production Access'
    """

    name: str = Field(..., description="Human-readable token name", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Token description", max_length=1000)
    expires_in_days: Optional[int] = Field(default=None, description="Expiry in days")
    scope: Optional[TokenScopeRequest] = Field(None, description="Token scoping configuration")
    tags: List[str] = Field(default_factory=list, description="Organizational tags")
    team_id: Optional[str] = Field(None, description="Team ID for team-scoped tokens")


class TokenUpdateRequest(BaseModel):
    """Schema for updating an existing API token.

    Attributes:
        name: New token name
        description: New token description
        scope: New token scoping configuration
        tags: New organizational tags

    Examples:
        >>> request = TokenUpdateRequest(
        ...     name="Updated Token Name",
        ...     description="Updated description"
        ... )
        >>> request.name
        'Updated Token Name'
    """

    name: Optional[str] = Field(None, description="New token name", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="New token description", max_length=1000)
    scope: Optional[TokenScopeRequest] = Field(None, description="New token scoping configuration")
    tags: Optional[List[str]] = Field(None, description="New organizational tags")


class TokenResponse(BaseModel):
    """Schema for API token response.

    Attributes:
        id: Token ID
        name: Token name
        description: Token description
        server_id: Server scope limitation
        resource_scopes: Permission scopes
        ip_restrictions: IP restrictions
        time_restrictions: Time-based restrictions
        usage_limits: Usage limits
        created_at: Creation timestamp
        expires_at: Expiry timestamp
        last_used: Last usage timestamp
        is_active: Active status
        tags: Organizational tags

    Examples:
        >>> from datetime import datetime
        >>> token = TokenResponse(
        ...     id="token-123",
        ...     name="Test Token",
        ...     description="Test description",
        ...     user_email="test@example.com",
        ...     server_id=None,
        ...     resource_scopes=["tools.read"],
        ...     ip_restrictions=[],
        ...     time_restrictions={},
        ...     usage_limits={},
        ...     created_at=datetime.now(),
        ...     expires_at=None,
        ...     last_used=None,
        ...     is_active=True,
        ...     tags=[]
        ... )
        >>> token.name
        'Test Token'
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Token ID")
    name: str = Field(..., description="Token name")
    description: Optional[str] = Field(None, description="Token description")
    user_email: str = Field(..., description="Token creator's email")
    team_id: Optional[str] = Field(None, description="Team ID for team-scoped tokens")
    server_id: Optional[str] = Field(None, description="Server scope limitation")
    resource_scopes: List[str] = Field(..., description="Permission scopes")
    ip_restrictions: List[str] = Field(..., description="IP restrictions")
    time_restrictions: Dict[str, Any] = Field(..., description="Time-based restrictions")
    usage_limits: Dict[str, Any] = Field(..., description="Usage limits")
    created_at: datetime = Field(..., description="Creation timestamp")
    expires_at: Optional[datetime] = Field(None, description="Expiry timestamp")
    last_used: Optional[datetime] = Field(None, description="Last usage timestamp")
    is_active: bool = Field(..., description="Active status")
    is_revoked: bool = Field(False, description="Whether token is revoked")
    revoked_at: Optional[datetime] = Field(None, description="Revocation timestamp")
    revoked_by: Optional[str] = Field(None, description="Email of user who revoked token")
    revocation_reason: Optional[str] = Field(None, description="Reason for revocation")
    tags: List[str] = Field(..., description="Organizational tags")


class TokenCreateResponse(BaseModel):
    """Schema for token creation response.

    Attributes:
        token: Token information
        access_token: The actual token string (only returned on creation)

    Examples:
        >>> from datetime import datetime
        >>> token_info = TokenResponse(
        ...     id="token-123", name="Test Token", description=None,
        ...     user_email="test@example.com", server_id=None, resource_scopes=[], ip_restrictions=[],
        ...     time_restrictions={}, usage_limits={}, created_at=datetime.now(),
        ...     expires_at=None, last_used=None, is_active=True, tags=[]
        ... )
        >>> response = TokenCreateResponse(
        ...     token=token_info,
        ...     access_token="abc123xyz"
        ... )
        >>> response.access_token
        'abc123xyz'
    """

    token: TokenResponse = Field(..., description="Token information")
    access_token: str = Field(..., description="The actual token string")


class TokenListResponse(BaseModel):
    """Schema for token list response.

    Attributes:
        tokens: List of tokens
        total: Total number of tokens
        limit: Request limit
        offset: Request offset

    Examples:
        >>> response = TokenListResponse(
        ...     tokens=[],
        ...     total=0,
        ...     limit=10,
        ...     offset=0
        ... )
        >>> response.total
        0
    """

    tokens: List[TokenResponse] = Field(..., description="List of tokens")
    total: int = Field(..., description="Total number of tokens")
    limit: int = Field(..., description="Request limit")
    offset: int = Field(..., description="Request offset")


class TokenRevokeRequest(BaseModel):
    """Schema for token revocation.

    Attributes:
        reason: Optional reason for revocation

    Examples:
        >>> request = TokenRevokeRequest(reason="Security incident")
        >>> request.reason
        'Security incident'
    """

    reason: Optional[str] = Field(None, description="Reason for revocation", max_length=255)


class TokenUsageStatsResponse(BaseModel):
    """Schema for token usage statistics.

    Attributes:
        period_days: Number of days analyzed
        total_requests: Total number of requests
        successful_requests: Number of successful requests
        blocked_requests: Number of blocked requests
        success_rate: Success rate percentage
        average_response_time_ms: Average response time
        top_endpoints: Most accessed endpoints

    Examples:
        >>> stats = TokenUsageStatsResponse(
        ...     period_days=30,
        ...     total_requests=100,
        ...     successful_requests=95,
        ...     blocked_requests=5,
        ...     success_rate=0.95,
        ...     average_response_time_ms=150.5,
        ...     top_endpoints=[("/tools", 50), ("/resources", 30)]
        ... )
        >>> stats.success_rate
        0.95
    """

    period_days: int = Field(..., description="Number of days analyzed")
    total_requests: int = Field(..., description="Total number of requests")
    successful_requests: int = Field(..., description="Number of successful requests")
    blocked_requests: int = Field(..., description="Number of blocked requests")
    success_rate: float = Field(..., description="Success rate (0-1)")
    average_response_time_ms: float = Field(..., description="Average response time in milliseconds")
    top_endpoints: List[tuple[str, int]] = Field(..., description="Most accessed endpoints with counts")


# ===== RBAC Schemas =====


class RoleCreateRequest(BaseModel):
    """Schema for creating a new role.

    Attributes:
        name: Unique role name
        description: Role description
        scope: Role scope (global, team, personal)
        permissions: List of permission strings
        inherits_from: Optional parent role ID
        is_system_role: Whether this is a system role

    Examples:
        >>> request = RoleCreateRequest(
        ...     name="team_admin",
        ...     description="Team administrator with member management",
        ...     scope="team",
        ...     permissions=["teams.manage_members", "resources.create"]
        ... )
        >>> request.name
        'team_admin'
    """

    name: str = Field(..., description="Unique role name", max_length=255)
    description: Optional[str] = Field(None, description="Role description")
    scope: str = Field(..., description="Role scope", pattern="^(global|team|personal)$")
    permissions: List[str] = Field(..., description="List of permission strings")
    inherits_from: Optional[str] = Field(None, description="Parent role ID for inheritance")
    is_system_role: Optional[bool] = Field(False, description="Whether this is a system role")


class RoleUpdateRequest(BaseModel):
    """Schema for updating an existing role.

    Attributes:
        name: Optional new name
        description: Optional new description
        permissions: Optional new permissions list
        inherits_from: Optional new parent role
        is_active: Optional active status

    Examples:
        >>> request = RoleUpdateRequest(
        ...     description="Updated role description",
        ...     permissions=["new.permission"]
        ... )
        >>> request.description
        'Updated role description'
    """

    name: Optional[str] = Field(None, description="Role name", max_length=255)
    description: Optional[str] = Field(None, description="Role description")
    permissions: Optional[List[str]] = Field(None, description="List of permission strings")
    inherits_from: Optional[str] = Field(None, description="Parent role ID for inheritance")
    is_active: Optional[bool] = Field(None, description="Whether role is active")


class RoleResponse(BaseModel):
    """Schema for role response.

    Attributes:
        id: Role identifier
        name: Role name
        description: Role description
        scope: Role scope
        permissions: List of permissions
        effective_permissions: All permissions including inherited
        inherits_from: Parent role ID
        created_by: Creator email
        is_system_role: Whether system role
        is_active: Whether role is active
        created_at: Creation timestamp
        updated_at: Update timestamp

    Examples:
        >>> role = RoleResponse(
        ...     id="role-123",
        ...     name="admin",
        ...     scope="global",
        ...     permissions=["*"],
        ...     effective_permissions=["*"],
        ...     created_by="admin@example.com",
        ...     is_system_role=True,
        ...     is_active=True,
        ...     created_at=datetime.now(),
        ...     updated_at=datetime.now()
        ... )
        >>> role.name
        'admin'
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Role identifier")
    name: str = Field(..., description="Role name")
    description: Optional[str] = Field(None, description="Role description")
    scope: str = Field(..., description="Role scope")
    permissions: List[str] = Field(..., description="Direct permissions")
    effective_permissions: Optional[List[str]] = Field(None, description="All permissions including inherited")
    inherits_from: Optional[str] = Field(None, description="Parent role ID")
    created_by: str = Field(..., description="Creator email")
    is_system_role: bool = Field(..., description="Whether system role")
    is_active: bool = Field(..., description="Whether role is active")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")


class UserRoleAssignRequest(BaseModel):
    """Schema for assigning a role to a user.

    Attributes:
        role_id: Role to assign
        scope: Assignment scope
        scope_id: Team ID if team-scoped
        expires_at: Optional expiration timestamp

    Examples:
        >>> request = UserRoleAssignRequest(
        ...     role_id="role-123",
        ...     scope="team",
        ...     scope_id="team-456"
        ... )
        >>> request.scope
        'team'
    """

    role_id: str = Field(..., description="Role ID to assign")
    scope: str = Field(..., description="Assignment scope", pattern="^(global|team|personal)$")
    scope_id: Optional[str] = Field(None, description="Team ID if team-scoped")
    expires_at: Optional[datetime] = Field(None, description="Optional expiration timestamp")


class UserRoleResponse(BaseModel):
    """Schema for user role assignment response.

    Attributes:
        id: Assignment identifier
        user_email: User email
        role_id: Role identifier
        role_name: Role name for convenience
        scope: Assignment scope
        scope_id: Team ID if applicable
        granted_by: Who granted the role
        granted_at: When role was granted
        expires_at: Optional expiration
        is_active: Whether assignment is active

    Examples:
        >>> user_role = UserRoleResponse(
        ...     id="assignment-123",
        ...     user_email="user@example.com",
        ...     role_id="role-456",
        ...     role_name="team_admin",
        ...     scope="team",
        ...     scope_id="team-789",
        ...     granted_by="admin@example.com",
        ...     granted_at=datetime.now(),
        ...     is_active=True
        ... )
        >>> user_role.scope
        'team'
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Assignment identifier")
    user_email: str = Field(..., description="User email")
    role_id: str = Field(..., description="Role identifier")
    role_name: Optional[str] = Field(None, description="Role name for convenience")
    scope: str = Field(..., description="Assignment scope")
    scope_id: Optional[str] = Field(None, description="Team ID if applicable")
    granted_by: str = Field(..., description="Who granted the role")
    granted_at: datetime = Field(..., description="When role was granted")
    expires_at: Optional[datetime] = Field(None, description="Optional expiration")
    is_active: bool = Field(..., description="Whether assignment is active")


class PermissionCheckRequest(BaseModel):
    """Schema for permission check request.

    Attributes:
        user_email: User to check
        permission: Permission to verify
        resource_type: Optional resource type
        resource_id: Optional resource ID
        team_id: Optional team context

    Examples:
        >>> request = PermissionCheckRequest(
        ...     user_email="user@example.com",
        ...     permission="tools.create",
        ...     resource_type="tools"
        ... )
        >>> request.permission
        'tools.create'
    """

    user_email: str = Field(..., description="User email to check")
    permission: str = Field(..., description="Permission to verify")
    resource_type: Optional[str] = Field(None, description="Resource type")
    resource_id: Optional[str] = Field(None, description="Resource ID")
    team_id: Optional[str] = Field(None, description="Team context")


class PermissionCheckResponse(BaseModel):
    """Schema for permission check response.

    Attributes:
        user_email: User checked
        permission: Permission checked
        granted: Whether permission was granted
        checked_at: When check was performed
        checked_by: Who performed the check

    Examples:
        >>> response = PermissionCheckResponse(
        ...     user_email="user@example.com",
        ...     permission="tools.create",
        ...     granted=True,
        ...     checked_at=datetime.now(),
        ...     checked_by="admin@example.com"
        ... )
        >>> response.granted
        True
    """

    user_email: str = Field(..., description="User email checked")
    permission: str = Field(..., description="Permission checked")
    granted: bool = Field(..., description="Whether permission was granted")
    checked_at: datetime = Field(..., description="When check was performed")
    checked_by: str = Field(..., description="Who performed the check")


class PermissionListResponse(BaseModel):
    """Schema for available permissions list.

    Attributes:
        all_permissions: List of all available permissions
        permissions_by_resource: Permissions grouped by resource type
        total_count: Total number of permissions

    Examples:
        >>> response = PermissionListResponse(
        ...     all_permissions=["users.create", "tools.read"],
        ...     permissions_by_resource={"users": ["users.create"], "tools": ["tools.read"]},
        ...     total_count=2
        ... )
        >>> response.total_count
        2
    """

    all_permissions: List[str] = Field(..., description="All available permissions")
    permissions_by_resource: Dict[str, List[str]] = Field(..., description="Permissions by resource type")
    total_count: int = Field(..., description="Total number of permissions")


# ==============================================================================
# SSO Authentication Schemas
# ==============================================================================


class SSOProviderResponse(BaseModelWithConfigDict):
    """Response schema for SSO provider information.

    Attributes:
        id: Provider identifier (e.g., 'github', 'google')
        name: Provider name
        display_name: Human-readable display name
        provider_type: Type of provider ('oauth2', 'oidc')
        is_enabled: Whether provider is currently enabled
        authorization_url: OAuth authorization URL (optional)

    Examples:
        >>> provider = SSOProviderResponse(
        ...     id="github",
        ...     name="github",
        ...     display_name="GitHub",
        ...     provider_type="oauth2",
        ...     is_enabled=True
        ... )
        >>> provider.id
        'github'
    """

    id: str = Field(..., description="Provider identifier")
    name: str = Field(..., description="Provider name")
    display_name: str = Field(..., description="Human-readable display name")
    provider_type: Optional[str] = Field(None, description="Provider type (oauth2, oidc)")
    is_enabled: Optional[bool] = Field(None, description="Whether provider is enabled")
    authorization_url: Optional[str] = Field(None, description="OAuth authorization URL")


class SSOLoginResponse(BaseModelWithConfigDict):
    """Response schema for SSO login initiation.

    Attributes:
        authorization_url: URL to redirect user for authentication
        state: CSRF state parameter for validation

    Examples:
        >>> login = SSOLoginResponse(
        ...     authorization_url="https://github.com/login/oauth/authorize?...",
        ...     state="csrf-token-123"
        ... )
        >>> "github.com" in login.authorization_url
        True
    """

    authorization_url: str = Field(..., description="OAuth authorization URL")
    state: str = Field(..., description="CSRF state parameter")


class SSOCallbackResponse(BaseModelWithConfigDict):
    """Response schema for SSO authentication callback.

    Attributes:
        access_token: JWT access token for authenticated user
        token_type: Token type (always 'bearer')
        expires_in: Token expiration time in seconds
        user: User information from SSO provider

    Examples:
        >>> callback = SSOCallbackResponse(
        ...     access_token="jwt.token.here",
        ...     token_type="bearer",
        ...     expires_in=3600,
        ...     user={"email": "user@example.com", "full_name": "User"}
        ... )
        >>> callback.token_type
        'bearer'
    """

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration in seconds")
    user: Dict[str, Any] = Field(..., description="User information")


# gRPC Service schemas


class GrpcServiceCreate(BaseModel):
    """Schema for creating a new gRPC service."""

    name: str = Field(..., min_length=1, max_length=255, description="Unique name for the gRPC service")
    target: str = Field(..., description="gRPC server target address (host:port)")
    description: Optional[str] = Field(None, description="Description of the gRPC service")
    reflection_enabled: bool = Field(default=True, description="Enable gRPC server reflection")
    tls_enabled: bool = Field(default=False, description="Enable TLS for gRPC connection")
    tls_cert_path: Optional[str] = Field(None, description="Path to TLS certificate file")
    tls_key_path: Optional[str] = Field(None, description="Path to TLS key file")
    grpc_metadata: Dict[str, str] = Field(default_factory=dict, description="gRPC metadata headers")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")

    # Team scoping fields
    team_id: Optional[str] = Field(None, description="ID of the team that owns this resource")
    owner_email: Optional[str] = Field(None, description="Email of the user who owns this resource")
    visibility: str = Field(default="public", description="Visibility level: private, team, or public")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate service name.

        Args:
            v: Service name to validate

        Returns:
            Validated service name
        """
        return SecurityValidator.validate_name(v, "gRPC service name")

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        """Validate target address format (host:port).

        Args:
            v: Target address to validate

        Returns:
            Validated target address

        Raises:
            ValueError: If target is not in host:port format
        """
        if not v or ":" not in v:
            raise ValueError("Target must be in host:port format")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Validate description.

        Args:
            v: Description to validate

        Returns:
            Validated and sanitized description
        """
        if v is None:
            return None
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")


class GrpcServiceUpdate(BaseModel):
    """Schema for updating an existing gRPC service."""

    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Service name")
    target: Optional[str] = Field(None, description="gRPC server target address")
    description: Optional[str] = Field(None, description="Service description")
    reflection_enabled: Optional[bool] = Field(None, description="Enable server reflection")
    tls_enabled: Optional[bool] = Field(None, description="Enable TLS")
    tls_cert_path: Optional[str] = Field(None, description="TLS certificate path")
    tls_key_path: Optional[str] = Field(None, description="TLS key path")
    grpc_metadata: Optional[Dict[str, str]] = Field(None, description="gRPC metadata headers")
    tags: Optional[List[str]] = Field(None, description="Service tags")
    visibility: Optional[str] = Field(None, description="Visibility level")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate service name.

        Args:
            v: Service name to validate

        Returns:
            Validated service name or None
        """
        if v is None:
            return None
        return SecurityValidator.validate_name(v, "gRPC service name")

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: Optional[str]) -> Optional[str]:
        """Validate target address.

        Args:
            v: Target address to validate

        Returns:
            Validated target address or None

        Raises:
            ValueError: If target is not in host:port format
        """
        if v is None:
            return None
        if ":" not in v:
            raise ValueError("Target must be in host:port format")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Validate description.

        Args:
            v: Description to validate

        Returns:
            Validated and sanitized description
        """
        if v is None:
            return None
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            truncated = v[: SecurityValidator.MAX_DESCRIPTION_LENGTH]
            logger.info(f"Description too long, truncated to {SecurityValidator.MAX_DESCRIPTION_LENGTH} characters.")
            return SecurityValidator.sanitize_display_text(truncated, "Description")
        return SecurityValidator.sanitize_display_text(v, "Description")


class GrpcServiceRead(BaseModel):
    """Schema for reading gRPC service information."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique service identifier")
    name: str = Field(..., description="Service name")
    slug: str = Field(..., description="URL-safe slug")
    target: str = Field(..., description="gRPC server target (host:port)")
    description: Optional[str] = Field(None, description="Service description")

    # Configuration
    reflection_enabled: bool = Field(..., description="Reflection enabled")
    tls_enabled: bool = Field(..., description="TLS enabled")
    tls_cert_path: Optional[str] = Field(None, description="TLS certificate path")
    tls_key_path: Optional[str] = Field(None, description="TLS key path")
    grpc_metadata: Dict[str, str] = Field(default_factory=dict, description="gRPC metadata")

    # Status
    enabled: bool = Field(..., description="Service enabled")
    reachable: bool = Field(..., description="Service reachable")

    # Discovery
    service_count: int = Field(default=0, description="Number of gRPC services discovered")
    method_count: int = Field(default=0, description="Number of methods discovered")
    discovered_services: Dict[str, Any] = Field(default_factory=dict, description="Discovered service descriptors")
    last_reflection: Optional[datetime] = Field(None, description="Last reflection timestamp")

    # Tags
    tags: List[Dict[str, str]] = Field(default_factory=list, description="Service tags")

    # Timestamps
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    # Team scoping
    team_id: Optional[str] = Field(None, description="Team ID")
    owner_email: Optional[str] = Field(None, description="Owner email")
    visibility: str = Field(default="public", description="Visibility level")


# Plugin-related schemas


class PluginSummary(BaseModel):
    """Summary information for a plugin in list views."""

    name: str = Field(..., description="Unique plugin name")
    description: str = Field("", description="Plugin description")
    author: str = Field("Unknown", description="Plugin author")
    version: str = Field("0.0.0", description="Plugin version")
    mode: str = Field(..., description="Plugin mode: enforce, permissive, or disabled")
    priority: int = Field(..., description="Plugin execution priority (lower = higher priority)")
    hooks: List[str] = Field(default_factory=list, description="Hook points where plugin executes")
    tags: List[str] = Field(default_factory=list, description="Plugin tags for categorization")
    status: str = Field(..., description="Plugin status: enabled or disabled")
    config_summary: Dict[str, Any] = Field(default_factory=dict, description="Summary of plugin configuration")


class PluginDetail(PluginSummary):
    """Detailed plugin information including full configuration."""

    kind: str = Field("", description="Plugin type or class")
    namespace: Optional[str] = Field(None, description="Plugin namespace")
    conditions: List[Any] = Field(default_factory=list, description="Conditions for plugin execution")
    config: Dict[str, Any] = Field(default_factory=dict, description="Full plugin configuration")
    manifest: Optional[Dict[str, Any]] = Field(None, description="Plugin manifest information")


class PluginListResponse(BaseModel):
    """Response for plugin list endpoint."""

    plugins: List[PluginSummary] = Field(..., description="List of plugins")
    total: int = Field(..., description="Total number of plugins")
    enabled_count: int = Field(0, description="Number of enabled plugins")
    disabled_count: int = Field(0, description="Number of disabled plugins")


class PluginStatsResponse(BaseModel):
    """Response for plugin statistics endpoint."""

    total_plugins: int = Field(..., description="Total number of plugins")
    enabled_plugins: int = Field(..., description="Number of enabled plugins")
    disabled_plugins: int = Field(..., description="Number of disabled plugins")
    plugins_by_hook: Dict[str, int] = Field(default_factory=dict, description="Plugin count by hook type")
    plugins_by_mode: Dict[str, int] = Field(default_factory=dict, description="Plugin count by mode")


# MCP Server Catalog Schemas


class CatalogServer(BaseModel):
    """Schema for a catalog server entry."""

    id: str = Field(..., description="Unique identifier for the catalog server")
    name: str = Field(..., description="Display name of the server")
    category: str = Field(..., description="Server category (e.g., Project Management, Software Development)")
    url: str = Field(..., description="Server endpoint URL")
    auth_type: str = Field(..., description="Authentication type (e.g., OAuth2.1, API Key, Open)")
    provider: str = Field(..., description="Provider/vendor name")
    description: str = Field(..., description="Server description")
    requires_api_key: bool = Field(default=False, description="Whether API key is required")
    secure: bool = Field(default=False, description="Whether additional security is required")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")
    transport: Optional[str] = Field(None, description="Transport type: SSE, STREAMABLEHTTP, or WEBSOCKET")
    logo_url: Optional[str] = Field(None, description="URL to server logo/icon")
    documentation_url: Optional[str] = Field(None, description="URL to server documentation")
    is_registered: bool = Field(default=False, description="Whether server is already registered")
    is_available: bool = Field(default=True, description="Whether server is currently available")


class CatalogServerRegisterRequest(BaseModel):
    """Request to register a catalog server."""

    server_id: str = Field(..., description="Catalog server ID to register")
    name: Optional[str] = Field(None, description="Optional custom name for the server")
    api_key: Optional[str] = Field(None, description="API key if required")
    oauth_credentials: Optional[Dict[str, Any]] = Field(None, description="OAuth credentials if required")


class CatalogServerRegisterResponse(BaseModel):
    """Response after registering a catalog server."""

    success: bool = Field(..., description="Whether registration was successful")
    server_id: str = Field(..., description="ID of the registered server in the system")
    message: str = Field(..., description="Status message")
    error: Optional[str] = Field(None, description="Error message if registration failed")


class CatalogServerStatusRequest(BaseModel):
    """Request to check catalog server status."""

    server_id: str = Field(..., description="Catalog server ID to check")


class CatalogServerStatusResponse(BaseModel):
    """Response for catalog server status check."""

    server_id: str = Field(..., description="Catalog server ID")
    is_available: bool = Field(..., description="Whether server is reachable")
    is_registered: bool = Field(..., description="Whether server is registered")
    last_checked: Optional[datetime] = Field(None, description="Last health check timestamp")
    response_time_ms: Optional[float] = Field(None, description="Response time in milliseconds")
    error: Optional[str] = Field(None, description="Error message if check failed")


class CatalogListRequest(BaseModel):
    """Request to list catalog servers."""

    category: Optional[str] = Field(None, description="Filter by category")
    auth_type: Optional[str] = Field(None, description="Filter by auth type")
    provider: Optional[str] = Field(None, description="Filter by provider")
    search: Optional[str] = Field(None, description="Search term for name/description")
    tags: Optional[List[str]] = Field(None, description="Filter by tags")
    show_registered_only: bool = Field(default=False, description="Show only registered servers")
    show_available_only: bool = Field(default=True, description="Show only available servers")
    limit: int = Field(default=100, description="Maximum number of results")
    offset: int = Field(default=0, description="Offset for pagination")


class CatalogListResponse(BaseModel):
    """Response containing catalog servers."""

    servers: List[CatalogServer] = Field(..., description="List of catalog servers")
    total: int = Field(..., description="Total number of matching servers")
    categories: List[str] = Field(..., description="Available categories")
    auth_types: List[str] = Field(..., description="Available auth types")
    providers: List[str] = Field(..., description="Available providers")
    all_tags: List[str] = Field(default_factory=list, description="All available tags")


class CatalogBulkRegisterRequest(BaseModel):
    """Request to register multiple catalog servers."""

    server_ids: List[str] = Field(..., description="List of catalog server IDs to register")
    skip_errors: bool = Field(default=True, description="Continue on error")


class CatalogBulkRegisterResponse(BaseModel):
    """Response after bulk registration."""

    successful: List[str] = Field(..., description="Successfully registered server IDs")
    failed: List[Dict[str, str]] = Field(..., description="Failed registrations with error messages")
    total_attempted: int = Field(..., description="Total servers attempted")
    total_successful: int = Field(..., description="Total successful registrations")


# ===================================
# Pagination Schemas
# ===================================


class PaginationMeta(BaseModel):
    """Pagination metadata.

    Attributes:
        page: Current page number (1-indexed)
        per_page: Items per page
        total_items: Total number of items across all pages
        total_pages: Total number of pages
        has_next: Whether there is a next page
        has_prev: Whether there is a previous page
        next_cursor: Cursor for next page (cursor-based only)
        prev_cursor: Cursor for previous page (cursor-based only)

    Examples:
        >>> meta = PaginationMeta(
        ...     page=2,
        ...     per_page=50,
        ...     total_items=250,
        ...     total_pages=5,
        ...     has_next=True,
        ...     has_prev=True
        ... )
        >>> meta.page
        2
        >>> meta.total_pages
        5
    """

    page: int = Field(..., description="Current page number (1-indexed)", ge=1)
    per_page: int = Field(..., description="Items per page", ge=1)
    total_items: int = Field(..., description="Total number of items", ge=0)
    total_pages: int = Field(..., description="Total number of pages", ge=0)
    has_next: bool = Field(..., description="Whether there is a next page")
    has_prev: bool = Field(..., description="Whether there is a previous page")
    next_cursor: Optional[str] = Field(None, description="Cursor for next page (cursor-based only)")
    prev_cursor: Optional[str] = Field(None, description="Cursor for previous page (cursor-based only)")


class PaginationLinks(BaseModel):
    """Pagination navigation links.

    Attributes:
        self: Current page URL
        first: First page URL
        last: Last page URL
        next: Next page URL (None if no next page)
        prev: Previous page URL (None if no previous page)

    Examples:
        >>> links = PaginationLinks(
        ...     self="/admin/tools?page=2&per_page=50",
        ...     first="/admin/tools?page=1&per_page=50",
        ...     last="/admin/tools?page=5&per_page=50",
        ...     next="/admin/tools?page=3&per_page=50",
        ...     prev="/admin/tools?page=1&per_page=50"
        ... )
        >>> links.self
        '/admin/tools?page=2&per_page=50'
    """

    self: str = Field(..., description="Current page URL")
    first: str = Field(..., description="First page URL")
    last: str = Field(..., description="Last page URL")
    next: Optional[str] = Field(None, description="Next page URL")
    prev: Optional[str] = Field(None, description="Previous page URL")


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper.

    This is a container for paginated data with metadata and navigation links.
    The actual data is stored in the 'data' field as a list of items.

    Attributes:
        data: List of items for the current page
        pagination: Pagination metadata (counts, page info)
        links: Navigation links (optional)

    Examples:
        >>> from mcpgateway.schemas import ToolRead
        >>> response = PaginatedResponse(
        ...     data=[],
        ...     pagination=PaginationMeta(
        ...         page=1, per_page=50, total_items=0,
        ...         total_pages=0, has_next=False, has_prev=False
        ...     ),
        ...     links=None
        ... )
        >>> response.pagination.page
        1
    """

    data: List[Any] = Field(..., description="List of items")
    pagination: PaginationMeta = Field(..., description="Pagination metadata")
    links: Optional[PaginationLinks] = Field(None, description="Navigation links")


class PaginationParams(BaseModel):
    """Common pagination query parameters.

    Attributes:
        page: Page number (1-indexed)
        per_page: Items per page
        cursor: Cursor for cursor-based pagination
        sort_by: Field to sort by
        sort_order: Sort order (asc/desc)

    Examples:
        >>> params = PaginationParams(page=1, per_page=50)
        >>> params.page
        1
        >>> params.sort_order
        'desc'
    """

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    per_page: int = Field(default=50, ge=1, le=500, description="Items per page (max 500)")
    cursor: Optional[str] = Field(None, description="Cursor for cursor-based pagination")
    sort_by: Optional[str] = Field("created_at", description="Sort field")
    sort_order: Optional[str] = Field("desc", pattern="^(asc|desc)$", description="Sort order")


# ============================================================================
# Cursor Pagination Response Schemas (for main API endpoints)
# ============================================================================


class CursorPaginatedToolsResponse(BaseModel):
    """Cursor-paginated response for tools list endpoint."""

    tools: List["ToolRead"] = Field(..., description="List of tools for this page")
    next_cursor: Optional[str] = Field(None, alias="nextCursor", description="Cursor for the next page, null if no more pages")


class CursorPaginatedServersResponse(BaseModel):
    """Cursor-paginated response for servers list endpoint."""

    servers: List["ServerRead"] = Field(..., description="List of servers for this page")
    next_cursor: Optional[str] = Field(None, alias="nextCursor", description="Cursor for the next page, null if no more pages")


class CursorPaginatedGatewaysResponse(BaseModel):
    """Cursor-paginated response for gateways list endpoint."""

    gateways: List["GatewayRead"] = Field(..., description="List of gateways for this page")
    next_cursor: Optional[str] = Field(None, alias="nextCursor", description="Cursor for the next page, null if no more pages")


class CursorPaginatedResourcesResponse(BaseModel):
    """Cursor-paginated response for resources list endpoint."""

    resources: List["ResourceRead"] = Field(..., description="List of resources for this page")
    next_cursor: Optional[str] = Field(None, alias="nextCursor", description="Cursor for the next page, null if no more pages")


class CursorPaginatedPromptsResponse(BaseModel):
    """Cursor-paginated response for prompts list endpoint."""

    prompts: List["PromptRead"] = Field(..., description="List of prompts for this page")
    next_cursor: Optional[str] = Field(None, alias="nextCursor", description="Cursor for the next page, null if no more pages")


class CursorPaginatedA2AAgentsResponse(BaseModel):
    """Cursor-paginated response for A2A agents list endpoint."""

    agents: List["A2AAgentRead"] = Field(..., description="List of A2A agents for this page")
    next_cursor: Optional[str] = Field(None, alias="nextCursor", description="Cursor for the next page, null if no more pages")


# ============================================================================
# Observability Schemas (OpenTelemetry-style traces, spans, events, metrics)
# ============================================================================


class ObservabilityTraceBase(BaseModel):
    """Base schema for observability traces."""

    name: str = Field(..., description="Trace name (e.g., 'POST /tools/invoke')")
    start_time: datetime = Field(..., description="Trace start timestamp")
    end_time: Optional[datetime] = Field(None, description="Trace end timestamp")
    duration_ms: Optional[float] = Field(None, description="Total duration in milliseconds")
    status: str = Field("unset", description="Trace status (unset, ok, error)")
    status_message: Optional[str] = Field(None, description="Status message or error description")
    http_method: Optional[str] = Field(None, description="HTTP method")
    http_url: Optional[str] = Field(None, description="HTTP URL")
    http_status_code: Optional[int] = Field(None, description="HTTP status code")
    user_email: Optional[str] = Field(None, description="User email")
    user_agent: Optional[str] = Field(None, description="User agent string")
    ip_address: Optional[str] = Field(None, description="Client IP address")
    attributes: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional trace attributes")
    resource_attributes: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Resource attributes")


class ObservabilityTraceCreate(ObservabilityTraceBase):
    """Schema for creating an observability trace."""

    trace_id: Optional[str] = Field(None, description="Trace ID (generated if not provided)")


class ObservabilityTraceUpdate(BaseModel):
    """Schema for updating an observability trace."""

    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    status: Optional[str] = None
    status_message: Optional[str] = None
    http_status_code: Optional[int] = None
    attributes: Optional[Dict[str, Any]] = None


class ObservabilityTraceRead(ObservabilityTraceBase):
    """Schema for reading an observability trace."""

    trace_id: str = Field(..., description="Trace ID")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {"from_attributes": True}


class ObservabilitySpanBase(BaseModel):
    """Base schema for observability spans."""

    trace_id: str = Field(..., description="Parent trace ID")
    parent_span_id: Optional[str] = Field(None, description="Parent span ID (for nested spans)")
    name: str = Field(..., description="Span name (e.g., 'database_query', 'tool_invocation')")
    kind: str = Field("internal", description="Span kind (internal, server, client, producer, consumer)")
    start_time: datetime = Field(..., description="Span start timestamp")
    end_time: Optional[datetime] = Field(None, description="Span end timestamp")
    duration_ms: Optional[float] = Field(None, description="Span duration in milliseconds")
    status: str = Field("unset", description="Span status (unset, ok, error)")
    status_message: Optional[str] = Field(None, description="Status message")
    attributes: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Span attributes")
    resource_name: Optional[str] = Field(None, description="Resource name")
    resource_type: Optional[str] = Field(None, description="Resource type (tool, resource, prompt, gateway, a2a_agent)")
    resource_id: Optional[str] = Field(None, description="Resource ID")


class ObservabilitySpanCreate(ObservabilitySpanBase):
    """Schema for creating an observability span."""

    span_id: Optional[str] = Field(None, description="Span ID (generated if not provided)")


class ObservabilitySpanUpdate(BaseModel):
    """Schema for updating an observability span."""

    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    status: Optional[str] = None
    status_message: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None


class ObservabilitySpanRead(ObservabilitySpanBase):
    """Schema for reading an observability span."""

    span_id: str = Field(..., description="Span ID")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {"from_attributes": True}


class ObservabilityEventBase(BaseModel):
    """Base schema for observability events."""

    span_id: str = Field(..., description="Parent span ID")
    name: str = Field(..., description="Event name (e.g., 'exception', 'log', 'checkpoint')")
    timestamp: datetime = Field(..., description="Event timestamp")
    attributes: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Event attributes")
    severity: Optional[str] = Field(None, description="Log severity (debug, info, warning, error, critical)")
    message: Optional[str] = Field(None, description="Event message")
    exception_type: Optional[str] = Field(None, description="Exception class name")
    exception_message: Optional[str] = Field(None, description="Exception message")
    exception_stacktrace: Optional[str] = Field(None, description="Exception stacktrace")


class ObservabilityEventCreate(ObservabilityEventBase):
    """Schema for creating an observability event."""


class ObservabilityEventRead(ObservabilityEventBase):
    """Schema for reading an observability event."""

    id: int = Field(..., description="Event ID")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {"from_attributes": True}


class ObservabilityMetricBase(BaseModel):
    """Base schema for observability metrics."""

    name: str = Field(..., description="Metric name (e.g., 'http.request.duration', 'tool.invocation.count')")
    metric_type: str = Field(..., description="Metric type (counter, gauge, histogram)")
    value: float = Field(..., description="Metric value")
    timestamp: datetime = Field(..., description="Metric timestamp")
    unit: Optional[str] = Field(None, description="Metric unit (ms, count, bytes, etc.)")
    attributes: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metric attributes/labels")
    resource_type: Optional[str] = Field(None, description="Resource type")
    resource_id: Optional[str] = Field(None, description="Resource ID")
    trace_id: Optional[str] = Field(None, description="Associated trace ID")


class ObservabilityMetricCreate(ObservabilityMetricBase):
    """Schema for creating an observability metric."""


class ObservabilityMetricRead(ObservabilityMetricBase):
    """Schema for reading an observability metric."""

    id: int = Field(..., description="Metric ID")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {"from_attributes": True}


class ObservabilityTraceWithSpans(ObservabilityTraceRead):
    """Schema for reading a trace with its spans."""

    spans: List[ObservabilitySpanRead] = Field(default_factory=list, description="List of spans in this trace")


class ObservabilitySpanWithEvents(ObservabilitySpanRead):
    """Schema for reading a span with its events."""

    events: List[ObservabilityEventRead] = Field(default_factory=list, description="List of events in this span")


class ObservabilityQueryParams(BaseModel):
    """Query parameters for filtering observability data."""

    start_time: Optional[datetime] = Field(None, description="Filter traces/spans/metrics after this time")
    end_time: Optional[datetime] = Field(None, description="Filter traces/spans/metrics before this time")
    status: Optional[str] = Field(None, description="Filter by status (ok, error, unset)")
    http_status_code: Optional[int] = Field(None, description="Filter by HTTP status code")
    user_email: Optional[str] = Field(None, description="Filter by user email")
    resource_type: Optional[str] = Field(None, description="Filter by resource type")
    resource_name: Optional[str] = Field(None, description="Filter by resource name")
    trace_id: Optional[str] = Field(None, description="Filter by trace ID")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum number of results")
    offset: int = Field(default=0, ge=0, description="Result offset for pagination")


# --- Performance Monitoring Schemas ---


class WorkerMetrics(BaseModel):
    """Metrics for a single worker process."""

    pid: int = Field(..., description="Process ID")
    cpu_percent: float = Field(..., description="CPU utilization percentage")
    memory_rss_mb: float = Field(..., description="Resident Set Size memory in MB")
    memory_vms_mb: float = Field(..., description="Virtual Memory Size in MB")
    threads: int = Field(..., description="Number of threads")
    connections: int = Field(0, description="Number of network connections")
    open_fds: Optional[int] = Field(None, description="Number of open file descriptors")
    status: str = Field("running", description="Worker status")
    create_time: Optional[datetime] = Field(None, description="Worker start time")
    uptime_seconds: Optional[int] = Field(None, description="Worker uptime in seconds")


class SystemMetricsSchema(BaseModel):
    """System-wide resource metrics."""

    # CPU metrics
    cpu_percent: float = Field(..., description="Total CPU utilization percentage")
    cpu_count: int = Field(..., description="Number of logical CPU cores")
    cpu_freq_mhz: Optional[float] = Field(None, description="Current CPU frequency in MHz")
    load_avg_1m: Optional[float] = Field(None, description="1-minute load average")
    load_avg_5m: Optional[float] = Field(None, description="5-minute load average")
    load_avg_15m: Optional[float] = Field(None, description="15-minute load average")

    # Memory metrics
    memory_total_mb: int = Field(..., description="Total physical memory in MB")
    memory_used_mb: int = Field(..., description="Used physical memory in MB")
    memory_available_mb: int = Field(..., description="Available memory in MB")
    memory_percent: float = Field(..., description="Memory utilization percentage")
    swap_total_mb: int = Field(0, description="Total swap space in MB")
    swap_used_mb: int = Field(0, description="Used swap space in MB")

    # Disk metrics
    disk_total_gb: float = Field(..., description="Total disk space in GB")
    disk_used_gb: float = Field(..., description="Used disk space in GB")
    disk_percent: float = Field(..., description="Disk utilization percentage")

    # Network metrics
    network_bytes_sent: int = Field(0, description="Total network bytes sent")
    network_bytes_recv: int = Field(0, description="Total network bytes received")
    network_connections: int = Field(0, description="Active network connections")

    # Process info
    boot_time: Optional[datetime] = Field(None, description="System boot time")


class RequestMetricsSchema(BaseModel):
    """HTTP request performance metrics."""

    requests_total: int = Field(0, description="Total HTTP requests")
    requests_per_second: float = Field(0, description="Current request rate")
    requests_1xx: int = Field(0, description="1xx informational responses")
    requests_2xx: int = Field(0, description="2xx success responses")
    requests_3xx: int = Field(0, description="3xx redirect responses")
    requests_4xx: int = Field(0, description="4xx client error responses")
    requests_5xx: int = Field(0, description="5xx server error responses")

    # Response time percentiles
    response_time_avg_ms: float = Field(0, description="Average response time in ms")
    response_time_p50_ms: float = Field(0, description="50th percentile response time")
    response_time_p95_ms: float = Field(0, description="95th percentile response time")
    response_time_p99_ms: float = Field(0, description="99th percentile response time")

    # Error rate
    error_rate: float = Field(0, description="Percentage of 4xx/5xx responses")

    # Active requests
    active_requests: int = Field(0, description="Currently processing requests")


class DatabaseMetricsSchema(BaseModel):
    """Database connection pool metrics."""

    pool_size: int = Field(0, description="Connection pool size")
    connections_in_use: int = Field(0, description="Active connections")
    connections_available: int = Field(0, description="Available connections")
    overflow: int = Field(0, description="Overflow connections")
    query_count: int = Field(0, description="Total queries executed")
    query_avg_time_ms: float = Field(0, description="Average query time in ms")


class CacheMetricsSchema(BaseModel):
    """Redis cache metrics."""

    connected: bool = Field(False, description="Redis connection status")
    version: Optional[str] = Field(None, description="Redis version")
    used_memory_mb: float = Field(0, description="Redis memory usage in MB")
    connected_clients: int = Field(0, description="Connected Redis clients")
    ops_per_second: int = Field(0, description="Redis operations per second")
    hit_rate: float = Field(0, description="Cache hit rate percentage")
    keyspace_hits: int = Field(0, description="Successful key lookups")
    keyspace_misses: int = Field(0, description="Failed key lookups")


class GunicornMetricsSchema(BaseModel):
    """Gunicorn server metrics."""

    master_pid: Optional[int] = Field(None, description="Master process PID")
    workers_total: int = Field(0, description="Total configured workers")
    workers_active: int = Field(0, description="Currently active workers")
    workers_idle: int = Field(0, description="Idle workers")
    max_requests: int = Field(0, description="Max requests before worker restart")


class PerformanceSnapshotCreate(BaseModel):
    """Schema for creating a performance snapshot."""

    host: str = Field(..., description="Hostname")
    worker_id: Optional[str] = Field(None, description="Worker identifier")
    metrics_json: Dict[str, Any] = Field(..., description="Serialized metrics data")


class PerformanceSnapshotRead(BaseModel):
    """Schema for reading a performance snapshot."""

    id: int = Field(..., description="Snapshot ID")
    timestamp: datetime = Field(..., description="Snapshot timestamp")
    host: str = Field(..., description="Hostname")
    worker_id: Optional[str] = Field(None, description="Worker identifier")
    metrics_json: Dict[str, Any] = Field(..., description="Serialized metrics data")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {"from_attributes": True}


class PerformanceAggregateBase(BaseModel):
    """Base schema for performance aggregates."""

    period_start: datetime = Field(..., description="Start of aggregation period")
    period_end: datetime = Field(..., description="End of aggregation period")
    period_type: str = Field(..., description="Aggregation type (hourly, daily)")
    host: Optional[str] = Field(None, description="Host (None for cluster-wide)")

    # Request aggregates
    requests_total: int = Field(0, description="Total requests in period")
    requests_2xx: int = Field(0, description="2xx responses in period")
    requests_4xx: int = Field(0, description="4xx responses in period")
    requests_5xx: int = Field(0, description="5xx responses in period")
    avg_response_time_ms: float = Field(0, description="Average response time")
    p95_response_time_ms: float = Field(0, description="95th percentile response time")
    peak_requests_per_second: float = Field(0, description="Peak request rate")

    # Resource aggregates
    avg_cpu_percent: float = Field(0, description="Average CPU utilization")
    avg_memory_percent: float = Field(0, description="Average memory utilization")
    peak_cpu_percent: float = Field(0, description="Peak CPU utilization")
    peak_memory_percent: float = Field(0, description="Peak memory utilization")


class PerformanceAggregateCreate(PerformanceAggregateBase):
    """Schema for creating a performance aggregate."""


class PerformanceAggregateRead(PerformanceAggregateBase):
    """Schema for reading a performance aggregate."""

    id: int = Field(..., description="Aggregate ID")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {"from_attributes": True}


class PerformanceDashboard(BaseModel):
    """Complete performance dashboard data."""

    timestamp: datetime = Field(..., description="Dashboard generation timestamp")
    uptime_seconds: int = Field(0, description="Application uptime in seconds")
    host: str = Field(..., description="Current hostname")

    # Current metrics
    system: SystemMetricsSchema = Field(..., description="Current system metrics")
    requests: RequestMetricsSchema = Field(..., description="Current request metrics")
    database: DatabaseMetricsSchema = Field(..., description="Current database metrics")
    cache: CacheMetricsSchema = Field(..., description="Current cache metrics")
    gunicorn: GunicornMetricsSchema = Field(..., description="Current Gunicorn metrics")
    workers: List[WorkerMetrics] = Field(default_factory=list, description="Per-worker metrics")

    # Cluster info (for distributed mode)
    cluster_hosts: List[str] = Field(default_factory=list, description="Known cluster hosts")
    is_distributed: bool = Field(False, description="Running in distributed mode")


class PerformanceHistoryParams(BaseModel):
    """Query parameters for historical performance data."""

    start_time: Optional[datetime] = Field(None, description="Start of time range")
    end_time: Optional[datetime] = Field(None, description="End of time range")
    period_type: str = Field("hourly", description="Aggregation period (hourly, daily)")
    host: Optional[str] = Field(None, description="Filter by host")
    limit: int = Field(default=168, ge=1, le=1000, description="Maximum results")


class PerformanceHistoryResponse(BaseModel):
    """Response for historical performance data."""

    aggregates: List[PerformanceAggregateRead] = Field(default_factory=list, description="Historical aggregates")
    period_type: str = Field(..., description="Aggregation period type")
    total_count: int = Field(0, description="Total matching records")
