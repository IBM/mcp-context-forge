# -*- coding: utf-8 -*-
"""A schema file for OPA plugin.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module defines schema for OPA plugin.
"""

# Standard
from typing import Optional, Any

# Third-Party
from pydantic import BaseModel

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
    kind : Optional[str] = None
    user : Optional[str] = None
    request_ip : Optional[str] = None
    headers : Optional[dict[str, str]] = None
    response : Optional[dict[str, str]] = None
    payload: dict[str, Any]
    context: Optional[dict[str, Any]] = None


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
    input : BaseOPAInputKeys

class OPAConfig(BaseModel):
    """Configuration for the OPA plugin."""

    # Base url on which opa server is running
    opa_base_url: str = "None"
