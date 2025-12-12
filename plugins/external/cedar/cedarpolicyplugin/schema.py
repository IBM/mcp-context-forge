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
    context: Optional[dict[Any, Any]] = None


class Redaction(BaseModel):
    """Configuration for Redaction

    Attributes:
        pattern (str) : pattern detected in output to redact
    """

    pattern: str = ""


class CedarConfig(BaseModel):
    """Configuration for the Cedar plugin.

    Attributes:
        policy_land (str) : cedar or custom_dsl. If policy is represented in cedar mode or custom_dsl mode
        policy (Union[list, str]): RBAC policy defined
        policy_output_keywords (dict): this is to internally check if certain type of views are allowed for outputs
        policy_redaction_spec (Redaction) : pattern or other parameters provided to redact the output
    """

    policy_lang: str = "None"
    policy: Union[list, str] = None
    policy_output_keywords: Optional[dict] = None
    policy_redaction_spec: Optional[Redaction] = None
