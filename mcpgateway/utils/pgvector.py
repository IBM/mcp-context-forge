"""PostgreSQL pgvector extension support detection.

This module provides a centralized location for detecting pgvector availability
to avoid circular imports when used across database models, migrations, and
application code.
"""

try:
    # Third-Party
    from pgvector.sqlalchemy import Vector  # type: ignore

    HAS_PGVECTOR = True
except ImportError:
    Vector = None
    HAS_PGVECTOR = False


class DummyVector:
    """Dummy Vector class when pgvector is not installed.

    This class is used as a placeholder when the pgvector extension is not available.
    It raises an ImportError when instantiated to inform users they need to install
    the postgres-vector extra.
    """

    def __init__(self, *args, **kwargs):
        """Raise ImportError when attempting to use Vector without pgvector installed."""
        raise ImportError("pgvector is not installed. Install with: pip install mcp-contextforge-gateway[postgres-vector]")


# Export the Vector class or dummy, depending on availability
if not HAS_PGVECTOR:
    Vector = DummyVector  # type: ignore[misc,assignment]
