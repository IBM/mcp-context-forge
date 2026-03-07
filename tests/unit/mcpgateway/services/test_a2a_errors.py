# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for A2A error hierarchy (mcpgateway/services/a2a_errors.py)."""

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_errors import (
    A2AAgentError,
    A2AAgentNameConflictError,
    A2AAgentNotFoundError,
    A2AAgentUpstreamError,
)


class TestA2AAgentError:
    """Tests for the base A2AAgentError exception."""

    def test_basic_message(self):
        err = A2AAgentError("something failed")
        assert str(err) == "something failed"

    def test_is_exception(self):
        assert issubclass(A2AAgentError, Exception)

    def test_catch_as_exception(self):
        with pytest.raises(Exception):
            raise A2AAgentError("fail")


class TestA2AAgentNotFoundError:
    """Tests for A2AAgentNotFoundError."""

    def test_inherits_from_base(self):
        assert issubclass(A2AAgentNotFoundError, A2AAgentError)

    def test_message(self):
        err = A2AAgentNotFoundError("Agent 'test-agent' not found")
        assert "test-agent" in str(err)

    def test_catch_as_base(self):
        with pytest.raises(A2AAgentError):
            raise A2AAgentNotFoundError("not found")


class TestA2AAgentNameConflictError:
    """Tests for A2AAgentNameConflictError."""

    def test_inherits_from_base(self):
        assert issubclass(A2AAgentNameConflictError, A2AAgentError)

    def test_active_agent_defaults(self):
        err = A2AAgentNameConflictError("my-agent")
        assert err.name == "my-agent"
        assert err.is_active is True
        assert err.agent_id is None
        assert "my-agent" in str(err)
        assert "Public" in str(err)

    def test_inactive_agent_with_id(self):
        err = A2AAgentNameConflictError("old-agent", is_active=False, agent_id="abc-123")
        assert err.name == "old-agent"
        assert err.is_active is False
        assert err.agent_id == "abc-123"
        assert "inactive" in str(err)
        assert "abc-123" in str(err)

    def test_custom_visibility(self):
        err = A2AAgentNameConflictError("my-agent", visibility="team")
        assert "Team" in str(err)

    def test_private_visibility(self):
        err = A2AAgentNameConflictError("my-agent", visibility="private")
        assert "Private" in str(err)

    def test_catch_as_base(self):
        with pytest.raises(A2AAgentError):
            raise A2AAgentNameConflictError("conflict")


class TestA2AAgentUpstreamError:
    """Tests for A2AAgentUpstreamError."""

    def test_inherits_from_base(self):
        assert issubclass(A2AAgentUpstreamError, A2AAgentError)

    def test_message(self):
        err = A2AAgentUpstreamError("HTTP 500: Internal Server Error")
        assert "500" in str(err)

    def test_catch_as_base(self):
        with pytest.raises(A2AAgentError):
            raise A2AAgentUpstreamError("upstream fail")


class TestReExportsFromA2AService:
    """Verify that a2a_service.py re-exports the errors for backward compat."""

    def test_reexport_a2a_agent_error(self):
        from mcpgateway.services.a2a_service import A2AAgentError as ReExported

        assert ReExported is A2AAgentError

    def test_reexport_not_found_error(self):
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError as ReExported

        assert ReExported is A2AAgentNotFoundError

    def test_reexport_name_conflict_error(self):
        from mcpgateway.services.a2a_service import A2AAgentNameConflictError as ReExported

        assert ReExported is A2AAgentNameConflictError

    def test_reexport_upstream_error(self):
        from mcpgateway.services.a2a_service import A2AAgentUpstreamError as ReExported

        assert ReExported is A2AAgentUpstreamError
