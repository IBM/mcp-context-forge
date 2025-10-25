# -*- coding: utf-8 -*-
"""Base model utilities for MCP Gateway.

This module provides shared base classes and utilities for Pydantic models
to avoid circular dependencies between models.py and schemas.py.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from typing import Any, Dict

# Third-Party
from pydantic import BaseModel, ConfigDict


def to_camel_case(s: str) -> str:
    """Convert a string from snake_case to camelCase.

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
        >>> to_camel_case("multiple_words_here")
        'multipleWordsHere'
        >>> to_camel_case("api_key_value")
        'apiKeyValue'
        >>> to_camel_case("user_id")
        'userId'
        >>> to_camel_case("created_at")
        'createdAt'
    """
    return "".join(word.capitalize() if i else word for i, word in enumerate(s.split("_")))


class BaseModelWithConfigDict(BaseModel):
    """Base model with common configuration for MCP protocol types.

    Provides:
    - ORM mode for SQLAlchemy integration
    - Automatic conversion from snake_case to camelCase for output
    - Populate by name for flexible field naming
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
        """Convert the model instance into a dictionary representation.

        Args:
            use_alias (bool): Whether to use aliases for field names (default is False).
                             If True, field names will be converted using the alias generator.

        Returns:
            Dict[str, Any]: A dictionary where keys are field names and values are
                           corresponding field values, with any nested models recursively
                           converted to dictionaries.
        """
        return self.model_dump(by_alias=use_alias)
