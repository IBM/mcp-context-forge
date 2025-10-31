# -*- coding: utf-8 -*-
"""A schema file for OPA plugin.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module defines schema for Cedar plugin.
"""

# Standard
from typing import Any, Optional, Union

# Third-Party
from pydantic import BaseModel


class CedarInput(BaseModel):
    """BaseOPAInputKeys

    Attributes:
        user (str) : specifying the user
        action (str): specifies the action
        resource (str): specifies the resource
        context (Optional[dict[str, Any]]) : context provided for policy evaluation.
    """
    principal: str = ""
    action: str = ""
    resource: str = ""
    context: Optional[dict[Any,Any]] = None


class CedarConfig(BaseModel):
    """Configuration for the OPA plugin."""

    # Base url on which opa server is running
    policy_lang: str  = "None"
    policy: Union[list,str] = None
