# -*- coding: utf-8 -*-
"""A schema file for OPA plugin.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module defines schema for OPA plugin.
"""

# Standard
from typing import Any, Optional

# Third-Party
from pydantic import BaseModel, Field


class BaseOPAInputKeys(BaseModel):
    """BaseOPAInputKeys

    Attributes:
        kind (Optional[str]) : specifying if it is a tool/call, or prompt, or resource request.
        user (Optional[str]): specifies user information like admin etc.
        request_ip (Optional[str]): specifies the IP of the request.
        headers (Optional[dict[str, str]]): specifies the headers for the request.
        response (Optional[dict[str, str]]) : specifies the response for the request.
        payload (dict[str, Any]) : required payload for the request.
        context (Optional[dict[str, Any]]) : context provided for policy evaluation.

    Examples:
        >>> opa_input = BaseOPAInputKeys(payload={"input" : {"repo_path" : "/path/file"}}, context = {"opa_policy_context" : {"context1" : "value1"}})
        >>> opa_input.payload
        '{"input" : {"repo_path" : "/path/file"}'
        >>> opa_input.context
        '{"opa_policy_context" : {"context1" : "value1"}}'

    """

    kind: Optional[str] = None
    user: Optional[str] = None
    request_ip: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    payload: dict[str, Any]
    context: Optional[dict[str, Any]] = None
    mode: str = None


class OPAInput(BaseModel):
    """OPAInput

    Attributes:
        input (BaseOPAInputKeys) : specifies the input to be passed to opa server for policy evaluation

    Examples:
        >>> opa_input = OPAInput(input=BaseOPAInputKeys(payload={"input" : {"repo_path" : "/path/file"}}, context = {"opa_policy_context" : {"context1" : "value1"}}))
        >>> opa_input.input.payload
        '{"input" : {"repo_path" : "/path/file"}'
        >>> opa_input.input.context
        '{"opa_policy_context" : {"context1" : "value1"}}'

    """

    input: BaseOPAInputKeys


class OPAConfig(BaseModel):
    """Configuration for the OPA plugin.

    Attributes:
        opa_base_url: The url of opa server
        opa_client_retries: Maximum no of retry attempt made while connecting to opa server
        opa_client_timeout: Timeout seconds for client connection to opa server
        opa_client_max_keepalive: Maximum number of connections to keep alive
        opa_client_max_connections: Maximum number of client connections
        opa_client_keepalive_expiry: Time for idle keep alive connections
    """

    opa_base_url: str = "http://127.0.0.1:8181/v1/data/"
    opa_client_retries: int = Field(default=3, ge=1, description="Maximum attempts (1=single attempt, no retries; 3=up to 3 attempts)")
    opa_client_timeout: str = "30s"
    opa_client_max_keepalive: int = Field(default=20, ge=1, description="Maximum keepalive connections")
    opa_client_max_connections: int = Field(default=100, ge=1, description="Maximum total connections")
    opa_client_keepalive_expiry: str = "5s"
