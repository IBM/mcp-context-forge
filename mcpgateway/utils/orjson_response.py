# -*- coding: utf-8 -*-
"""Custom JSON response class using orjson for high-performance JSON serialization.

This module provides ORJSONResponse, a drop-in replacement for FastAPI's default
JSONResponse that uses orjson for 2-3x faster JSON serialization/deserialization.

orjson is a fast, correct JSON library for Python implemented in Rust. It provides
significant performance improvements over the standard library's json module, especially
for large payloads (tool lists, server lists, bulk exports).

Performance improvements:
- 2-3x faster serialization than stdlib json
- 1.5-2x faster deserialization than stdlib json
- 30-40% less memory usage
- Smaller output size (more compact)

References:
- orjson: https://github.com/ijl/orjson
- FastAPI Custom Response: https://fastapi.tiangolo.com/advanced/custom-response/
"""

# Standard
from typing import Any

# Third-Party
from fastapi.responses import JSONResponse
import orjson


class ORJSONResponse(JSONResponse):
    """Custom JSON response class using orjson for faster serialization.

    orjson is 2-3x faster than stdlib json and produces more compact output.
    It handles datetime, UUID, and numpy types natively.

    This response class is designed to be a drop-in replacement for FastAPI's
    default JSONResponse with no breaking changes to API behavior.

    Features:
    - Fast: 2-3x faster than stdlib json, uses Rust implementation
    - Strict: RFC 8259 compliant, catches serialization errors early
    - Compact: Produces smaller output than stdlib json
    - Type Support: datetime, UUID, numpy arrays, dataclasses, Pydantic models
    - Binary Output: Returns bytes directly (no string→bytes conversion overhead)

    Example:
        >>> from mcpgateway.utils.orjson_response import ORJSONResponse
        >>> response = ORJSONResponse(content={"message": "Hello World"})
        >>> response.media_type
        'application/json'

    Options used:
    - OPT_NON_STR_KEYS: Allow non-string dict keys (ints, etc.)
    - OPT_SERIALIZE_NUMPY: Support numpy arrays if present

    For datetime serialization, orjson uses RFC 3339 format (ISO 8601 with timezone).
    Naive datetimes are treated as UTC by default.
    """

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        """Render content to JSON bytes using orjson.

        Args:
            content: The content to serialize to JSON. Can be dict, list, str,
                     int, float, bool, None, datetime, UUID, Pydantic models, etc.

        Returns:
            JSON bytes ready for HTTP response (no additional encoding needed).

        Options:
            - OPT_NON_STR_KEYS: Allow non-string dict keys (ints, UUID, etc.)
            - OPT_SERIALIZE_NUMPY: Support numpy arrays if numpy is installed

        Note:
            orjson returns bytes directly, unlike stdlib json.dumps() which returns str.
            This eliminates the string→bytes encoding step, improving performance.

        Raises:
            orjson.JSONEncodeError: If content cannot be serialized to JSON.
        """
        return orjson.dumps(
            content,
            option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY,
        )
