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

    This base class provides automatic snake_case → camelCase field name conversion
    to comply with the MCP specification's JSON naming conventions.

    Key Features:
    - **Automatic camelCase conversion**: Field names like `stop_reason` automatically
      serialize as `stopReason` when FastAPI returns the response (via jsonable_encoder).
    - **ORM mode**: Can be constructed from SQLAlchemy models (from_attributes=True).
    - **Flexible input**: Accepts both snake_case and camelCase in input (populate_by_name=True).
    - **Enum values**: Enums serialize as their values, not names (use_enum_values=True).

    Usage:
        Models extending this class will automatically serialize field names to camelCase:

        >>> class MyModel(BaseModelWithConfigDict):
        ...     my_field: str = "value"
        ...     another_field: int = 42
        >>>
        >>> obj = MyModel()
        >>> obj.model_dump(by_alias=True)
        {'myField': 'value', 'anotherField': 42}

    Important:
        FastAPI's default response serialization uses `by_alias=True`, so models extending
        this class will automatically use camelCase in JSON responses without any additional
        code changes. This is critical for MCP spec compliance.

    Examples:
        >>> from mcpgateway.utils.base_models import BaseModelWithConfigDict
        >>> class CreateMessageResult(BaseModelWithConfigDict):
        ...     stop_reason: str = "endTurn"
        >>>
        >>> result = CreateMessageResult()
        >>> # Without by_alias (internal Python usage):
        >>> result.model_dump()
        {'stop_reason': 'endTurn'}
        >>>
        >>> # With by_alias (FastAPI automatic serialization):
        >>> result.model_dump(by_alias=True)
        {'stopReason': 'endTurn'}
    """

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel_case,  # Automatic snake_case → camelCase conversion
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
