# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/input_validator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Centralized input validation utility for all services.
"""

# Standard
from typing import Optional

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings


class InputValidator:
    """Centralized validation for all service inputs."""

    @staticmethod
    def validate_resource_input(
        name: Optional[str] = None,
        description: Optional[str] = None,
        uri: Optional[str] = None,
        url: Optional[str] = None,
        path: Optional[str] = None,
    ) -> None:
        """Validate common resource input fields.

        Args:
            name: Resource name
            description: Resource description
            uri: Resource URI
            url: Resource URL
            path: File path

        Raises:
            ValueError: If validation fails
        """
        if not settings.experimental_validate_io:
            return

        if name:
            SecurityValidator.validate_no_xss(name, "Name")

        if description:
            SecurityValidator.validate_shell_parameter(description)
            SecurityValidator.validate_no_xss(description, "Description")

        if uri:
            SecurityValidator.validate_uri(uri, "URI")

        if url:
            SecurityValidator.validate_url(url, "URL")

        if path:
            SecurityValidator.validate_path(path)
