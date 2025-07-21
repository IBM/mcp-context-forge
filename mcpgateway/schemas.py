# -*- coding: utf-8 -*-
"""MCP Gateway Schema Definitions.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Self, Union

# Third-Party
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator, ValidationInfo

# First-Party
from mcpgateway.config import settings
from mcpgateway.models import ImageContent
from mcpgateway.models import Prompt as MCPPrompt
from mcpgateway.models import Resource as MCPResource
from mcpgateway.models import ResourceContent, TextContent
from mcpgateway.models import Tool as MCPTool
from mcpgateway.utils.services_auth import decode_auth, encode_auth
from mcpgateway.validators import SecurityValidator

logger = logging.getLogger(__name__)


def to_camel_case(s: str) -> str:
    """
    Convert a string from snake_case to camelCase.

    Args:
        s (str): The string to be converted, which is assumed to be in snake_case.

    Returns:
        str: The string converted to camelCase.

    Examples:
        >>> to_camel_case("hello_world_example")
        'helloWorldExample'
        >>> to_camel_case("alreadyCamel")
        'alreadyCamel'
        >>> to_camel_case("")
        ''
        >>> to_camel_case("single")
        'single'
        >>> to_camel_case("_leading_underscore")
        'LeadingUnderscore'
        >>> to_camel_case("trailing_underscore_")
        'trailingUnderscore'
    """
    return "".join(word.capitalize() if i else word for i, word in enumerate(s.split("_")))


def encode_datetime(v: datetime) -> str:
    """
    Convert a datetime object to an ISO 8601 formatted string.

    Args:
        v (datetime): The datetime object to be encoded.

    Returns:
        str: The ISO 8601 formatted string representation of the datetime object.

    Examples:
        >>> from datetime import datetime
        >>> encode_datetime(datetime(2023, 5, 22, 14, 30, 0))
        '2023-05-22T14:30:00'
    """
    return v.isoformat()


# --- Base Model ---
class BaseModelWithConfigDict(BaseModel):
    """Base model with common configuration.

    Provides:
    - ORM mode for SQLAlchemy integration
    - JSON encoders for datetime handling
    - Automatic conversion from snake_case to camelCase for output
    """

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,
        populate_by_name=True,
        use_enum_values=True,
        extra="ignore",
        json_schema_extra={"nullable": True},
    )

    def to_dict(self, use_alias: bool = False) -> Dict[str, Any]:
        """
        Converts the model instance into a dictionary representation.

        Args:
            use_alias (bool): Whether to use aliases for field names (default is False). If True,
                               field names will be converted using the alias generator function.

        Returns:
            Dict[str, Any]: A dictionary where keys are field names and values are corresponding field values,
                             with any nested models recursively converted to dictionaries.

        Examples:
            >>> class ExampleModel(BaseModelWithConfigDict):
            ...     foo: int
            ...     bar: str
            >>> m = ExampleModel(foo=1, bar='baz')
            >>> m.to_dict()
            {'foo': 1, 'bar': 'baz'}

            >>> # Test with alias
            >>> m.to_dict(use_alias=True)
            {'foo': 1, 'bar': 'baz'}

            >>> # Test with nested model
            >>> class NestedModel(BaseModelWithConfigDict):
            ...     nested_field: int
            >>> class ParentModel(BaseModelWithConfigDict):
            ...     parent_field: str
            ...     child: NestedModel
            >>> nested = NestedModel(nested_field=42)
            >>> parent = ParentModel(parent_field="test", child=nested)
            >>> result = parent.to_dict()
            >>> result['child']
            {'nested_field': 42}
        """
        output = {}
        for key, value in self.model_dump(by_alias=use_alias).items():
            output[key] = value if not isinstance(value, BaseModel) else value.to_dict(use_alias)
        return output


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
    username: str = Field("", description="Username for basic authentication")
    password: str = Field("", description="Password for basic authentication")
    token: str = Field("", description="Bearer token for authentication")
    auth_header_key: str = Field("", description="Key for custom headers authentication")
    auth_header_value: str = Field("", description="Value for custom headers authentication")


class ToolCreate(BaseModel):
    """
    Represents the configuration for creating a tool with various attributes and settings.

    Attributes:
        model_config (ConfigDict): Configuration for the model.
        name (str): Unique name for the tool.
        url (Union[str, AnyHttpUrl]): Tool endpoint URL.
        description (Optional[str]): Tool description.
        integration_type (Literal["MCP", "REST"]): Tool integration type. 'MCP' for MCP-compliant tools, 'REST' for REST integrations.
        request_type (Literal["GET", "POST", "PUT", "DELETE", "SSE", "STDIO", "STREAMABLEHTTP"]): HTTP method to be used for invoking the tool.
        headers (Optional[Dict[str, str]]): Additional headers to send when invoking the tool.
        input_schema (Optional[Dict[str, Any]]): JSON Schema for validating tool parameters. Alias 'inputSchema'.
        annotations (Optional[Dict[str, Any]]): Tool annotations for behavior hints such as title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint.
        jsonpath_filter (Optional[str]): JSON modification filter.
        auth (Optional[AuthenticationValues]): Authentication credentials (Basic or Bearer Token or custom headers) if required.
        gateway_id (Optional[str]): ID of the gateway for the tool.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., description="Unique name for the tool")
    url: Union[str, AnyHttpUrl] = Field(None, description="Tool endpoint URL")
    description: Optional[str] = Field(None, description="Tool description")
    integration_type: Literal["MCP", "REST"] = Field("MCP", description="Tool integration type: 'MCP' for MCP-compliant tools, 'REST' for REST integrations")
    request_type: Literal["GET", "POST", "PUT", "DELETE", "PATCH", "SSE", "STDIO", "STREAMABLEHTTP"] = Field("SSE", description="HTTP method to be used for invoking the tool")
    headers: Optional[Dict[str, str]] = Field(None, description="Additional headers to send when invoking the tool")
    input_schema: Optional[Dict[str, Any]] = Field(default_factory=lambda: {"type": "object", "properties": {}}, description="JSON Schema for validating tool parameters", alias="inputSchema")
    annotations: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Tool annotations for behavior hints (title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint)",
    )
    jsonpath_filter: Optional[str] = Field(default="", description="JSON modification filter")
    auth: Optional[AuthenticationValues] = Field(None, description="Authentication credentials (Basic or Bearer Token or custom headers) if required")
    gateway_id: Optional[str] = Field(None, description="id of gateway for the tool")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure tool names follow MCP naming conventions

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

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
    def validate_url(cls, v: str) -> str:
        """Validate URL format and ensure safe display

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Examples:
            >>> from mcpgateway.schemas import ToolCreate
            >>> ToolCreate.validate_url('https://example.com')
            'https://example.com'
            >>> ToolCreate.validate_url('ftp://example.com')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
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
            >>> from mcpgateway.schemas import ToolCreate
            >>> ToolCreate.validate_description('A safe description')
            'A safe description'
            >>> ToolCreate.validate_description('x' * 5000)
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
        return SecurityValidator.sanitize_display_text(v, "Description")

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
            >>> ToolCreate.validate_json_fields({'a': {'b': {'c': {'d': {'e': {'f': {'g': {'h': {'i': {'j': {'k': 1}}}}}}}}}}})
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        SecurityValidator.validate_json_depth(v)
        return v

    @field_validator("request_type")
    @classmethod
    def validate_request_type(cls, v: str, info: ValidationInfo) -> str:
        """Validate request type based on integration type

        Args:
            v (str): Value to validate
            info (ValidationInfo): Values used for validation

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe

        Examples:
            >>> # Test MCP integration types
            >>> from pydantic import ValidationInfo
            >>> info = type('obj', (object,), {'data': {'integration_type': 'MCP'}})
            >>> ToolCreate.validate_request_type('SSE', info)
            'SSE'

            >>> # Test REST integration types
            >>> info = type('obj', (object,), {'data': {'integration_type': 'REST'}})
            >>> ToolCreate.validate_request_type('GET', info)
            'GET'
            >>> ToolCreate.validate_request_type('POST', info)
            'POST'

            >>> # Test invalid REST type
            >>> try:
            ...     ToolCreate.validate_request_type('SSE', info)
            ... except ValueError as e:
            ...     "not allowed for REST" in str(e)
            True

            >>> # Test invalid MCP type
            >>> info = type('obj', (object,), {'data': {'integration_type': 'MCP'}})
            >>> try:
            ...     ToolCreate.validate_request_type('GET', info)
            ... except ValueError as e:
            ...     "not allowed for MCP" in str(e)
            True
        """
        data = info.data
        integration_type = data.get("integration_type")

        if integration_type == "MCP":
            allowed = ["SSE", "STREAMABLEHTTP", "STDIO"]
        else:  # REST
            allowed = ["GET", "POST", "PUT", "DELETE", "PATCH"]

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
        if auth_type:
            if auth_type.lower() == "basic":
                creds = base64.b64encode(f"{values.get('auth_username', '')}:{values.get('auth_password', '')}".encode("utf-8")).decode()
                encoded_auth = encode_auth({"Authorization": f"Basic {creds}"})
                values["auth"] = {"auth_type": "basic", "auth_value": encoded_auth}
            elif auth_type.lower() == "bearer":
                encoded_auth = encode_auth({"Authorization": f"Bearer {values.get('auth_token', '')}"})
                values["auth"] = {"auth_type": "bearer", "auth_value": encoded_auth}
            elif auth_type.lower() == "authheaders":
                encoded_auth = encode_auth({values.get("auth_header_key", ""): values.get("auth_header_value", "")})
                values["auth"] = {"auth_type": "authheaders", "auth_value": encoded_auth}
        return values


class ToolUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing tool.

    Similar to ToolCreate but all fields are optional to allow partial updates.
    """

    name: Optional[str] = Field(None, description="Unique name for the tool")
    url: Optional[Union[str, AnyHttpUrl]] = Field(None, description="Tool endpoint URL")
    description: Optional[str] = Field(None, description="Tool description")
    request_type: Optional[Literal["GET", "POST", "PUT", "DELETE", "PATCH", "SSE", "STDIO", "STREAMABLEHTTP"]] = Field(None, description="HTTP method to be used for invoking the tool")
    integration_type: Optional[Literal["MCP", "REST"]] = Field(None, description="Tool integration type")
    headers: Optional[Dict[str, str]] = Field(None, description="Additional headers to send when invoking the tool")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema for validating tool parameters")
    annotations: Optional[Dict[str, Any]] = Field(None, description="Tool annotations for behavior hints")
    jsonpath_filter: Optional[str] = Field(None, description="JSON path filter for rpc tool calls")
    auth: Optional[AuthenticationValues] = Field(None, description="Authentication credentials (Basic or Bearer Token or custom headers) if required")
    gateway_id: Optional[str] = Field(None, description="id of gateway for the tool")

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

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format and ensure safe display

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe
        """
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
            >>> from mcpgateway.schemas import ResourceCreate
            >>> ResourceCreate.validate_description('A safe description')
            'A safe description'
            >>> ResourceCreate.validate_description(None)  # Test None case

            >>> ResourceCreate.validate_description('x' * 5000)
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
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
    def validate_request_type(cls, v: str, values: Dict[str, Any]) -> str:
        """Validate request type based on integration type

        Args:
            v (str): Value to validate
            values (str): Values used for validation

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """
        integration_type = values.config.get("integration_type", "MCP")

        if integration_type == "MCP":
            allowed = ["SSE", "STREAMABLEHTTP", "STDIO"]
        else:  # REST
            allowed = ["GET", "POST", "PUT", "DELETE", "PATCH"]

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
        if auth_type:
            if auth_type.lower() == "basic":
                creds = base64.b64encode(f"{values.get('auth_username', '')}:{values.get('auth_password', '')}".encode("utf-8")).decode()
                encoded_auth = encode_auth({"Authorization": f"Basic {creds}"})
                values["auth"] = {"auth_type": "basic", "auth_value": encoded_auth}
            elif auth_type.lower() == "bearer":
                encoded_auth = encode_auth({"Authorization": f"Bearer {values.get('auth_token', '')}"})
                values["auth"] = {"auth_type": "bearer", "auth_value": encoded_auth}
            elif auth_type.lower() == "authheaders":
                encoded_auth = encode_auth({values.get("auth_header_key", ""): values.get("auth_header_value", "")})
                values["auth"] = {"auth_type": "authheaders", "auth_value": encoded_auth}
        return values


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
    annotations: Optional[Dict[str, Any]]
    jsonpath_filter: Optional[str]
    auth: Optional[AuthenticationValues]
    created_at: datetime
    updated_at: datetime
    enabled: bool
    reachable: bool
    gateway_id: Optional[str]
    execution_count: int
    metrics: ToolMetrics
    name: str
    gateway_slug: str
    original_name_slug: str


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

        >>> # Invalid: Arguments too deeply nested (>10 levels)
        >>> deep_args = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": "too deep"}}}}}}}}}}}
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

    model_config = ConfigDict(str_strip_whitespace=True)

    uri: str = Field(..., description="Unique URI for the resource")
    name: str = Field(..., description="Human-readable resource name")
    description: Optional[str] = Field(None, description="Resource description")
    mime_type: Optional[str] = Field(None, description="Resource MIME type")
    template: Optional[str] = Field(None, description="URI template for parameterized resources")
    content: Union[str, bytes] = Field(..., description="Resource content (text or binary)")

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
        """Ensure descriptions display safely

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
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
                v_str = v.decode("utf-8")

                if re.search(SecurityValidator.DANGEROUS_HTML_PATTERN, v_str if isinstance(v, bytes) else v, re.IGNORECASE):
                    raise ValueError("Content contains HTML tags that may cause display issues")
            except UnicodeDecodeError:
                raise ValueError("Content must be UTF-8 decodable")
        else:
            if re.search(SecurityValidator.DANGEROUS_HTML_PATTERN, v if isinstance(v, bytes) else v, re.IGNORECASE):
                raise ValueError("Content contains HTML tags that may cause display issues")

        return v


class ResourceUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing resource.

    Similar to ResourceCreate but URI is not required and all fields are optional.
    """

    name: Optional[str] = Field(None, description="Human-readable resource name")
    description: Optional[str] = Field(None, description="Resource description")
    mime_type: Optional[str] = Field(None, description="Resource MIME type")
    template: Optional[str] = Field(None, description="URI template for parameterized resources")
    content: Optional[Union[str, bytes]] = Field(None, description="Resource content (text or binary)")

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
        """Ensure descriptions display safely

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
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
                v_str = v.decode("utf-8")

                if re.search(SecurityValidator.DANGEROUS_HTML_PATTERN, v_str if isinstance(v, bytes) else v, re.IGNORECASE):
                    raise ValueError("Content contains HTML tags that may cause display issues")
            except UnicodeDecodeError:
                raise ValueError("Content must be UTF-8 decodable")
        else:
            if re.search(SecurityValidator.DANGEROUS_HTML_PATTERN, v if isinstance(v, bytes) else v, re.IGNORECASE):
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

    id: int
    uri: str
    name: str
    description: Optional[str]
    mime_type: Optional[str]
    size: Optional[int]
    created_at: datetime
    updated_at: datetime
    is_active: bool
    metrics: ResourceMetrics


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

    model_config: ConfigDict = ConfigDict(
        **{
            # start with every key from the base
            **BaseModelWithConfigDict.model_config,
            # override only json_schema_extra by merging the two dicts:
            "json_schema_extra": {
                **BaseModelWithConfigDict.model_config.get("json_schema_extra", {}),
                "example": {
                    "name": "language",
                    "description": "Programming language",
                    "required": True,
                },
            },
        }
    )


class PromptCreate(BaseModel):
    """
    Schema for creating a new prompt.

    Attributes:
        model_config (ConfigDict): Configuration for the model.
        name (str): Unique name for the prompt.
        description (Optional[str]): Optional description of the prompt.
        template (str): Template text for the prompt.
        arguments (List[PromptArgument]): List of arguments for the template.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., description="Unique name for the prompt")
    description: Optional[str] = Field(None, description="Prompt description")
    template: str = Field(..., description="Prompt template text")
    arguments: List[PromptArgument] = Field(default_factory=list, description="List of arguments for the template")

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

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely without breaking UI layout

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
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


class PromptUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing prompt.

    Similar to PromptCreate but all fields are optional to allow partial updates.
    """

    name: Optional[str] = Field(None, description="Unique name for the prompt")
    description: Optional[str] = Field(None, description="Prompt description")
    template: Optional[str] = Field(None, description="Prompt template text")
    arguments: Optional[List[PromptArgument]] = Field(None, description="List of arguments for the template")

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

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Ensure descriptions display safely without breaking UI layout

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
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

    id: int
    name: str
    description: Optional[str]
    template: str
    arguments: List[PromptArgument]
    created_at: datetime
    updated_at: datetime
    is_active: bool
    metrics: PromptMetrics


class PromptInvocation(BaseModelWithConfigDict):
    """Schema for prompt invocation requests.

    Contains:
    - Prompt name to use
    - Arguments for template rendering
    """

    name: str = Field(..., description="Name of prompt to use")
    arguments: Dict[str, str] = Field(default_factory=dict, description="Arguments for template rendering")


# --- Gateway Schemas ---


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
        auth_value (Optional[str]): Alias for authentication value, used for better access post-validation.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., description="Unique name for the gateway")
    url: Union[str, AnyHttpUrl] = Field(..., description="Gateway endpoint URL")
    description: Optional[str] = Field(None, description="Gateway description")
    transport: str = Field(default="SSE", description="Transport used by MCP server: SSE or STREAMABLEHTTP")

    # Authorizations
    auth_type: Optional[str] = Field(None, description="Type of authentication: basic, bearer, headers, or none")
    # Fields for various types of authentication
    auth_username: Optional[str] = Field(None, description="Username for basic authentication")
    auth_password: Optional[str] = Field(None, description="Password for basic authentication")
    auth_token: Optional[str] = Field(None, description="Token for bearer authentication")
    auth_header_key: Optional[str] = Field(None, description="Key for custom headers authentication")
    auth_header_value: Optional[str] = Field(None, description="Value for custom headers authentication")

    # Adding `auth_value` as an alias for better access post-validation
    auth_value: Optional[str] = Field(None, validate_default=True)

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
        """Ensure descriptions display safely

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
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

    @staticmethod
    def _process_auth_fields(info: ValidationInfo) -> Optional[Dict[str, Any]]:
        """
        Processes the input authentication fields and returns the correct auth_value.
        This method is called based on the selected auth_type.

        Args:
            info: ValidationInfo containing auth fields

        Returns:
            Dict with encoded auth

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

        if auth_type == "authheaders":
            # For headers authentication, both key and value must be present
            header_key = data.get("auth_header_key")
            header_value = data.get("auth_header_value")

            if not header_key or not header_value:
                raise ValueError("For 'headers' auth, both 'auth_header_key' and 'auth_header_value' must be provided.")

            return encode_auth({header_key: header_value})

        raise ValueError("Invalid 'auth_type'. Must be one of: basic, bearer, or headers.")


class GatewayUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing federation gateway.

    Similar to GatewayCreate but all fields are optional to allow partial updates.
    """

    name: Optional[str] = Field(None, description="Unique name for the gateway")
    url: Optional[Union[str, AnyHttpUrl]] = Field(None, description="Gateway endpoint URL")
    description: Optional[str] = Field(None, description="Gateway description")
    transport: str = Field(default="SSE", description="Transport used by MCP server: SSE or STREAMABLEHTTP")

    name: Optional[str] = Field(None, description="Unique name for the prompt")
    # Authorizations
    auth_type: Optional[str] = Field(None, description="auth_type: basic, bearer, headers or None")
    auth_username: Optional[str] = Field(None, description="username for basic authentication")
    auth_password: Optional[str] = Field(None, description="password for basic authentication")
    auth_token: Optional[str] = Field(None, description="token for bearer authentication")
    auth_header_key: Optional[str] = Field(None, description="key for custom headers authentication")
    auth_header_value: Optional[str] = Field(None, description="vallue for custom headers authentication")

    # Adding `auth_value` as an alias for better access post-validation
    auth_value: Optional[str] = Field(None, validate_default=True)

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
        """Ensure descriptions display safely

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is unsafe
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
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
    def _process_auth_fields(values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Processes the input authentication fields and returns the correct auth_value.
        This method is called based on the selected auth_type.

        Args:
            values: Dict container auth information auth_type, auth_username, auth_password, auth_token, auth_header_key and auth_header_value

        Returns:
            dict: Encoded auth information

        Raises:
            ValueError: If auth type is invalid
        """
        auth_type = values.get("auth_type")

        if auth_type == "basic":
            # For basic authentication, both username and password must be present
            username = values.get("auth_username")
            password = values.get("auth_password")

            if not username or not password:
                raise ValueError("For 'basic' auth, both 'auth_username' and 'auth_password' must be provided.")

            creds = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode()
            return encode_auth({"Authorization": f"Basic {creds}"})

        if auth_type == "bearer":
            # For bearer authentication, only token is required
            token = values.get("auth_token")

            if not token:
                raise ValueError("For 'bearer' auth, 'auth_token' must be provided.")

            return encode_auth({"Authorization": f"Bearer {token}"})

        if auth_type == "authheaders":
            # For headers authentication, both key and value must be present
            header_key = values.get("auth_header_key")
            header_value = values.get("auth_header_value")

            if not header_key or not header_value:
                raise ValueError("For 'headers' auth, both 'auth_header_key' and 'auth_header_value' must be provided.")

            return encode_auth({header_key: header_value})

        raise ValueError("Invalid 'auth_type'. Must be one of: basic, bearer, or headers.")


class GatewayRead(BaseModelWithConfigDict):
    """Schema for reading gateway information.

    Includes all gateway fields plus:
    - Database ID
    - Capabilities dictionary
    - Creation/update timestamps
    - enabled status
    - reachable status
    - Last seen timestamp
    - Authentication type: basic, bearer, headers
    - Authentication value: username/password or token or custom headers

    Auto Populated fields:
    - Authentication username: for basic auth
    - Authentication password: for basic auth
    - Authentication token: for bearer auth
    - Authentication header key: for headers auth
    - Authentication header value: for headers auth
    """

    id: str = Field(None, description="Unique ID of the gateway")
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

    # Authorizations
    auth_type: Optional[str] = Field(None, description="auth_type: basic, bearer, headers or None")
    auth_value: Optional[str] = Field(None, description="auth value: username/password or token or custom headers")

    # auth_value will populate the following fields
    auth_username: Optional[str] = Field(None, description="username for basic authentication")
    auth_password: Optional[str] = Field(None, description="password for basic authentication")
    auth_token: Optional[str] = Field(None, description="token for bearer authentication")
    auth_header_key: Optional[str] = Field(None, description="key for custom headers authentication")
    auth_header_value: Optional[str] = Field(None, description="vallue for custom headers authentication")

    slug: str = Field(None, description="Slug for gateway endpoint URL")

    # This will be the main method to automatically populate fields
    @model_validator(mode="after")
    @classmethod
    def _populate_auth(cls, values: Self) -> Dict[str, Any]:
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

        Args:
            values: The validated model data containing auth_type and auth_value.
                Expected to have 'auth_type' and 'auth_value' fields.

        Returns:
            Dict[str, Any]: The updated values dict with populated auth fields:
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
        auth_type = values.auth_type
        auth_value_encoded = values.auth_value
        auth_value = decode_auth(auth_value_encoded)
        if auth_type == "basic":
            auth = auth_value.get("Authorization")
            auth = auth.removeprefix("Basic ")
            u, p = base64.urlsafe_b64decode(auth).decode("utf-8").split(":")
            if not u or not p:
                raise ValueError("basic auth requires both username and password")
            values.auth_username, values.auth_password = u, p

        elif auth_type == "bearer":
            auth = auth_value.get("Authorization")
            if not (isinstance(auth, str) and auth.startswith("Bearer ")):
                raise ValueError("bearer auth requires an Authorization header of the form 'Bearer <token>'")
            values.auth_token = auth.removeprefix("Bearer ")

        elif auth_type == "authheaders":
            # must be exactly one header
            if len(auth_value) != 1:
                raise ValueError("authheaders requires exactly one key/value pair")
            k, v = next(iter(auth_value.items()))
            values.auth_header_key, values.auth_header_value = k, v

        return values


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
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_\.]*$", v):
            raise ValueError("Invalid method name format")
        if len(v) > 128:  # MCP method name limit
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
        param_size = len(json.dumps(v))
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
            return json.loads(v)
        except json.JSONDecodeError:
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

    name: str = Field(..., description="The server's name")
    description: Optional[str] = Field(None, description="Server description")
    icon: Optional[str] = Field(None, description="URL for the server's icon")
    associated_tools: Optional[List[str]] = Field(None, description="Comma-separated tool IDs")
    associated_resources: Optional[List[str]] = Field(None, description="Comma-separated resource IDs")
    associated_prompts: Optional[List[str]] = Field(None, description="Comma-separated prompt IDs")

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
        """Ensure descriptions display safely

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is not safe
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
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

    @field_validator("associated_tools", "associated_resources", "associated_prompts", mode="before")
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


class ServerUpdate(BaseModelWithConfigDict):
    """Schema for updating an existing server.

    All fields are optional to allow partial updates.
    """

    name: Optional[str] = Field(None, description="The server's name")
    description: Optional[str] = Field(None, description="Server description")
    icon: Optional[str] = Field(None, description="URL for the server's icon")
    associated_tools: Optional[List[str]] = Field(None, description="Comma-separated tool IDs")
    associated_resources: Optional[List[str]] = Field(None, description="Comma-separated resource IDs")
    associated_prompts: Optional[List[str]] = Field(None, description="Comma-separated prompt IDs")

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
        """Ensure descriptions display safely

        Args:
            v (str): Value to validate

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is not safe
        """
        if v is None:
            return v
        if len(v) > SecurityValidator.MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description exceeds maximum length of {SecurityValidator.MAX_DESCRIPTION_LENGTH}")
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

    @field_validator("associated_tools", "associated_resources", "associated_prompts", mode="before")
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
    is_active: bool
    associated_tools: List[str] = []
    associated_resources: List[int] = []
    associated_prompts: List[int] = []
    metrics: ServerMetrics

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
        # If values is not a dict (e.g. it's a Server instance), convert it
        if not isinstance(values, dict):
            try:
                values = vars(values)
            except Exception:
                return values
        if "associated_tools" in values and values["associated_tools"]:
            values["associated_tools"] = [tool.id if hasattr(tool, "id") else tool for tool in values["associated_tools"]]
        if "associated_resources" in values and values["associated_resources"]:
            values["associated_resources"] = [res.id if hasattr(res, "id") else res for res in values["associated_resources"]]
        if "associated_prompts" in values and values["associated_prompts"]:
            values["associated_prompts"] = [prompt.id if hasattr(prompt, "id") else prompt for prompt in values["associated_prompts"]]
        return values


class GatewayTestRequest(BaseModelWithConfigDict):
    """Schema for testing gateway connectivity.

    Includes the HTTP method, base URL, path, optional headers, and body.
    """

    method: str = Field(..., description="HTTP method to test (GET, POST, etc.)")
    base_url: AnyHttpUrl = Field(..., description="Base URL of the gateway to test")
    path: str = Field(..., description="Path to append to the base URL")
    headers: Optional[Dict[str, str]] = Field(None, description="Optional headers for the request")
    body: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Optional body for the request, can be a string or JSON object")


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
