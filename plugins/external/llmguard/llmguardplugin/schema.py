# -*- coding: utf-8 -*-
"""Defines Schema for Guardrails using LLMGuard

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

"""

# Standard
from typing import Optional

# Third-Party
from pydantic import BaseModel


class ModeConfig(BaseModel):
    """The config schema for both input and output modes for guardrails

    Attributes:
       sanitizers:  A set of transformers applied on input or output. Transforms the original input.
       filters: A set of filters applied on input or output. Returns true or false.
       metadata: plugin meta data.

    Examples:
        >>> config = ModeConfig(filters= {"PromptInjection" : {"threshold" : 0.5}})
        >>> config.filters
        {'PromptInjection' : {'threshold' : 0.5}
    """

    sanitizers: Optional[dict] = None
    filters: Optional[dict] = None


class LLMGuardConfig(BaseModel):
    """The config schema for guardrails

    Attributes:
       set_guardrail_context: If true, the context is set in the plugins
       cache_ttl: Time to live for cache defined in seconds
       input:  A set of sanitizers and filters applied on input
       output: A set of sanitizers and filters applied on output

    Examples:
        >>> config =LLMGuardConfig(input=ModeConfig(filters= {"PromptInjection" : {"threshold" : 0.5}}))
        >>> config.input.filters
        {'PromptInjection' : {'threshold' : 0.5}
    """

    set_guardrails_context: bool = True
    cache_ttl: int = 0
    input: Optional[ModeConfig] = None
    output: Optional[ModeConfig] = None
