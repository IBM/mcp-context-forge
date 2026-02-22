# -*- coding: utf-8 -*-
"""Location: ./plugins/deny_filter/deny_violation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo, Dmitry Zakharov

Helper function for creating deny violation responses.
"""

from mcpgateway.plugins.framework import (
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
)


def deny_violation(payload: PromptPrehookPayload) -> PromptPrehookResult:
    """Create a prompt prehook result indicating a deny word violation.

    Args:
        payload: The prompt payload that triggered the violation.

    Returns:
        A PromptPrehookResult with violation details and processing halted.
    """
    return PromptPrehookResult(
        modified_payload=payload,
        violation=PluginViolation(
            reason="Prompt not allowed",
            description="A deny word was found in the prompt",
            code="deny",
            details={},
        ),
        continue_processing=False,
    )
