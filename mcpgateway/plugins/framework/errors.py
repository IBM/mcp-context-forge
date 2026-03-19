# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/errors.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Pydantic models for plugins.
This module implements the pydantic models associated with
the base plugin layer including configurations, and contexts.
"""

# First-Party
from mcpgateway.plugins.framework.models import PluginErrorModel, PluginViolation


class PluginViolationError(Exception):
    """A plugin violation error.

    Attributes:
        violation (PluginViolation): the plugin violation.
        message (str): the plugin violation reason.
    """

    def __init__(self, message: str, violation: PluginViolation | None = None):
        """Initialize a plugin violation error.

        Args:
            message: the reason for the violation error.
            violation: the plugin violation object details.

        Examples:
            >>> from mcpgateway.plugins.framework.errors import PluginViolationError
            >>> from mcpgateway.plugins.framework.models import PluginViolation
            >>> v = PluginViolation(reason="r", description="d", code="c")
            >>> err = PluginViolationError("blocked", violation=v)
            >>> (str(err), err.violation.code)
            ('blocked', 'c')
        """
        self.message = message
        self.violation = violation
        super().__init__(self.message)


class PluginError(Exception):
    """A plugin error object for errors internal to the plugin.

    Attributes:
        error (PluginErrorModel): the plugin error object.
    """

    def __init__(self, error: PluginErrorModel):
        """Initialize a plugin violation error.

        Args:
            error: the plugin error details.

        Examples:
            >>> from mcpgateway.plugins.framework.errors import PluginError
            >>> from mcpgateway.plugins.framework.models import PluginErrorModel
            >>> pe = PluginError(PluginErrorModel(message="boom", plugin_name="p1"))
            >>> (str(pe), pe.error.plugin_name)
            ('boom', 'p1')
        """
        self.error = error
        super().__init__(self.error.message)


def convert_exception_to_error(exception: Exception, plugin_name: str) -> PluginErrorModel:
    """Converts an exception object into a PluginErrorModel. Primarily used for external plugin error handling.

    Args:
        exception: The exception to be converted.
        plugin_name: The name of the plugin on which the exception occurred.

    Returns:
        A plugin error pydantic object that can be sent over HTTP.

    Examples:
        >>> from mcpgateway.plugins.framework.errors import convert_exception_to_error
        >>> err = convert_exception_to_error(ValueError("nope"), plugin_name="p1")
        >>> (err.plugin_name, "ValueError('nope')" in err.message)
        ('p1', True)
    """
    return PluginErrorModel(message=repr(exception), plugin_name=plugin_name)
