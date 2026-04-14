# -*- coding: utf-8 -*-
"""pgvector compatibility shim.

Provides HAS_PGVECTOR flag and Vector type for optional pgvector support.
When pgvector is not installed, falls back to JSON column storage.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]

    HAS_PGVECTOR = True
    logger.debug("pgvector extension available")
except ImportError:
    HAS_PGVECTOR = False
    Vector = None  # type: ignore[assignment,misc]
    logger.debug("pgvector not available, using JSON fallback for embeddings")
