# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_endpoint_url_length.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for issue #7606: the a2a_agents endpoint_url column must fit every URL the validator accepts.

PostgreSQL enforces the column length and SQLite does not, so the column length and
settings.validation_max_url_length are compared directly rather than inferred from an insert.
"""

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent
from mcpgateway.schemas import A2AAgentCreate

URL_PREFIX = "https://example.com/"


def url_of_length(total: int) -> str:
    """Return a valid http URL of exactly ``total`` characters."""
    return URL_PREFIX + "a" * (total - len(URL_PREFIX))


def test_column_length_matches_url_validator():
    """The column and the validator agree, so a validated URL can always be stored."""
    assert A2AAgent.__table__.c.endpoint_url.type.length == settings.validation_max_url_length


def test_url_at_limit_is_accepted_and_stored(test_db):
    """A URL at the limit passes the schema and round trips through SQLite."""
    url = url_of_length(settings.validation_max_url_length)
    payload = A2AAgentCreate(name="agent-at-limit", endpoint_url=url)

    test_db.add(A2AAgent(name="agent-at-limit", slug="agent-at-limit", endpoint_url=payload.endpoint_url))
    test_db.commit()

    assert test_db.query(A2AAgent).one().endpoint_url == url


def test_url_above_limit_is_rejected_by_schema():
    """A URL above the limit fails validation, which the API renders as 422 before any insert."""
    with pytest.raises(ValidationError) as excinfo:
        A2AAgentCreate(name="agent-over-limit", endpoint_url=url_of_length(settings.validation_max_url_length + 1))

    assert excinfo.value.errors()[0]["loc"] == ("endpoint_url",)
