# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_plugins_utils.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for mcpgateway.plugins.utils.build_request_extensions() (Task B1 / G0).

Covers the helper in isolation (no HTTP request or PluginManager involved):
    - Returns a populated Extensions(request=RequestExtension(...)) when a trace_id
      is active in the observability ContextVars.
    - Returns None when no trace_id is active (the common case: observability
      disabled, or code running outside of a traced request).
    - Returns None (never raises) when span_id is unset but trace_id is present.
    - Is best-effort: any unexpected exception while reading the ContextVars or
      constructing the CPEX Extensions object is swallowed and None is returned,
      so this helper can never break the request path it's called from.
"""

# Standard
from unittest.mock import patch

# First-Party
from mcpgateway.plugins.utils import build_request_extensions
from mcpgateway.services.observability_service import current_span_id, current_trace_id


class TestBuildRequestExtensions:
    """Tests for build_request_extensions()."""

    def test_returns_none_when_no_trace_active(self):
        """With no trace_id set in the ContextVar, the helper returns None."""
        token = current_trace_id.set(None)
        try:
            assert build_request_extensions() is None
        finally:
            current_trace_id.reset(token)

    def test_returns_extensions_with_trace_and_span_id(self):
        """When both trace_id and span_id are active, both are carried through."""
        trace_token = current_trace_id.set("trace-abc")
        span_token = current_span_id.set("span-xyz")
        try:
            extensions = build_request_extensions()
        finally:
            current_trace_id.reset(trace_token)
            current_span_id.reset(span_token)

        assert extensions is not None
        assert extensions.request.trace_id == "trace-abc"
        assert extensions.request.span_id == "span-xyz"

    def test_returns_extensions_with_trace_id_only_when_span_id_unset(self):
        """A trace_id without a span_id still produces Extensions (span_id=None)."""
        trace_token = current_trace_id.set("trace-only")
        try:
            extensions = build_request_extensions()
        finally:
            current_trace_id.reset(trace_token)

        assert extensions is not None
        assert extensions.request.trace_id == "trace-only"
        assert extensions.request.span_id is None

    def test_never_raises_when_contextvar_read_fails(self):
        """If reading the ContextVar unexpectedly raises, the helper swallows it and
        returns None rather than propagating into the request path.
        """
        with patch("mcpgateway.services.observability_service.current_trace_id") as mock_trace_id:
            mock_trace_id.get.side_effect = RuntimeError("boom")
            assert build_request_extensions() is None

    def test_never_raises_when_extensions_construction_fails(self):
        """If building the CPEX Extensions/RequestExtension object unexpectedly raises,
        the helper swallows it and returns None rather than propagating.
        """
        trace_token = current_trace_id.set("trace-abc")
        try:
            with patch("mcpgateway.plugins.utils.RequestExtension", side_effect=RuntimeError("boom")):
                assert build_request_extensions() is None
        finally:
            current_trace_id.reset(trace_token)
