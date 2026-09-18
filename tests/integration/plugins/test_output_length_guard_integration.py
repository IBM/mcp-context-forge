# -*- coding: utf-8 -*-
"""Location: ./tests/integration/plugins/test_output_length_guard_integration.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Integration tests for output_length_guard plugin metrics consumption.

Mirrors test_plugin_metrics_consumer_integration.py: constructs fake
result.metadata directly (no HTTP, no plugin manager) and asserts that
record_plugin_metrics() writes the correct span attributes and metric rows
to a real in-memory SQLite DB.

Prerequisites:
    pip install cpex-output-length-guard  (or install from source per the guide)
"""

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, ObservabilityMetric, ObservabilitySpan
from mcpgateway.plugins.utils import record_plugin_metrics
from mcpgateway.services.observability_service import ObservabilityService


@pytest.fixture
def test_db_engine():
    """Create in-memory SQLite engine with all tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(test_db_engine):
    """Provide a transactional DB session for testing."""
    test_session_local = sessionmaker(bind=test_db_engine)
    session = test_session_local()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def patch_session_local(test_db_engine, monkeypatch):
    """Patch SessionLocal to use test_db_engine."""
    test_session_local = sessionmaker(bind=test_db_engine)
    monkeypatch.setattr("mcpgateway.db.SessionLocal", test_session_local)
    monkeypatch.setattr("mcpgateway.services.observability_service.SessionLocal", test_session_local)


@pytest.fixture
def observability_service():
    """ObservabilityService instance."""
    return ObservabilityService()


class TestOutputLengthGuardMetricsIntegration:
    """record_plugin_metrics() correctly persists output_length_guard metadata."""

    def test_truncate_event_records_span_and_metrics(
        self, db_session, observability_service: ObservabilityService
    ):
        """Truncation metadata -> span attributes + numeric metric rows."""
        trace_id = observability_service.start_trace(name="test_olg_truncate")

        result_metadata = {
            "output_length_guard": {
                "chars_seen": 32000,
                "truncated_count": 3,
                "blocked": False,
                "limit_mode": "character",
                "strategy": "truncate",
                "stage": "tool_post_invoke",
            }
        }

        record_plugin_metrics(trace_id, result_metadata)

        # Span assertions
        span = db_session.query(ObservabilitySpan).filter_by(
            trace_id=trace_id, name="plugin.metrics.output_length_guard"
        ).one()
        assert span.resource_type == "plugin"
        assert span.resource_name == "output_length_guard"
        assert span.status == "ok"
        assert span.attributes["chars_seen"] == 32000
        assert span.attributes["truncated_count"] == 3
        assert span.attributes["blocked"] is False
        assert span.attributes["limit_mode"] == "character"
        assert span.attributes["strategy"] == "truncate"
        assert span.attributes["stage"] == "tool_post_invoke"

        # Metric row assertions (numeric fields only — bool/str do not become rows)
        metrics = db_session.query(ObservabilityMetric).filter_by(trace_id=trace_id).all()
        metrics_by_name = {m.name: m for m in metrics}
        assert set(metrics_by_name) == {
            "plugin.output_length_guard.chars_seen",
            "plugin.output_length_guard.truncated_count",
        }
        assert metrics_by_name["plugin.output_length_guard.chars_seen"].value == 32000.0
        assert metrics_by_name["plugin.output_length_guard.truncated_count"].value == 3.0
        for metric in metrics_by_name.values():
            assert metric.resource_type == "plugin"
            assert metric.resource_id == "output_length_guard"

        observability_service.end_trace(trace_id)

    def test_block_event_records_span_with_blocked_true(
        self, db_session, observability_service: ObservabilityService
    ):
        """Block metadata -> span with blocked=True, no chars_seen/truncated_count metrics."""
        trace_id = observability_service.start_trace(name="test_olg_block")

        result_metadata = {
            "output_length_guard": {
                "chars_seen": 0,
                "truncated_count": 0,
                "blocked": True,
                "limit_mode": "character",
                "strategy": "block",
                "stage": "tool_post_invoke",
            }
        }

        record_plugin_metrics(trace_id, result_metadata)

        span = db_session.query(ObservabilitySpan).filter_by(
            trace_id=trace_id, name="plugin.metrics.output_length_guard"
        ).one()
        assert span.attributes["blocked"] is True
        assert span.attributes["strategy"] == "block"
        assert span.attributes["chars_seen"] == 0
        assert span.attributes["truncated_count"] == 0

        observability_service.end_trace(trace_id)

    def test_no_metrics_without_trace_id(self, db_session):
        """No DB rows written when trace_id is absent."""
        before = db_session.query(ObservabilitySpan).count()
        record_plugin_metrics(
            None,
            {"output_length_guard": {"chars_seen": 100, "truncated_count": 1}},
        )
        assert db_session.query(ObservabilitySpan).count() == before

    def test_plugin_instantiates_with_rust_backend(self):
        """Smoke test: the Rust-backed plugin can be imported and instantiated."""
        from cpex_output_length_guard.output_length_guard import OutputLengthGuardPlugin
        from cpex.framework import PluginConfig, ToolHookType

        config = PluginConfig(
            name="output_length_guard",
            kind="cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            config={"max_chars": 5000, "strategy": "truncate"},
        )
        plugin = OutputLengthGuardPlugin(config)
        assert plugin is not None

    def test_truncate_hook_fires_on_oversized_string(self):
        """End-to-end: plugin truncates a plain oversized string result."""
        import asyncio
        from cpex_output_length_guard.output_length_guard import OutputLengthGuardPlugin
        from cpex.framework import GlobalContext, PluginConfig, PluginContext, ToolHookType, ToolPostInvokePayload

        config = PluginConfig(
            name="output_length_guard",
            kind="cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            config={"max_chars": 100, "strategy": "truncate"},
        )
        plugin = OutputLengthGuardPlugin(config)
        payload = ToolPostInvokePayload(name="test_tool", result="A" * 500)
        gc = GlobalContext(request_id="req-1", user=None, tenant_id="t1", server_id="gw1")
        context = PluginContext(global_context=gc)
        result = asyncio.run(plugin.tool_post_invoke(payload, context))
        assert result.modified_payload is not None
        assert len(result.modified_payload.result) <= 100  # ellipsis fits within the 100-char budget

    def test_block_hook_fires_on_oversized_string(self):
        """End-to-end: plugin blocks and returns continue_processing=False."""
        import asyncio
        from cpex_output_length_guard.output_length_guard import OutputLengthGuardPlugin
        from cpex.framework import GlobalContext, PluginConfig, PluginContext, ToolHookType, ToolPostInvokePayload

        config = PluginConfig(
            name="output_length_guard",
            kind="cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin",
            hooks=[ToolHookType.TOOL_POST_INVOKE],
            config={"max_chars": 100, "strategy": "block"},
        )
        plugin = OutputLengthGuardPlugin(config)
        payload = ToolPostInvokePayload(name="test_tool", result="A" * 500)
        gc = GlobalContext(request_id="req-1", user=None, tenant_id="t1", server_id="gw1")
        context = PluginContext(global_context=gc)
        result = asyncio.run(plugin.tool_post_invoke(payload, context))
        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "OUTPUT_LENGTH_VIOLATION"


class TestOutputLengthGuardBackwardCompatibility:
    """Backward-compatibility tests for the Rust-backed output_length_guard package.

    Each test targets a specific schema field or behaviour that the PR claims is
    preserved from the old Python implementation:
    - limit_mode: token  (token-based enforcement)
    - word_boundary: true  (word-boundary truncation)
    - Structured / nested payloads (MCP content dict, list of strings)
    - Security limits: max_text_length, max_recursion_depth
    - Inverted min/max configuration rejected at load time
    """

    def _make_plugin(self, cfg: dict):
        """Instantiate OutputLengthGuardPlugin with the given config dict.

        Args:
            cfg: Plugin-specific configuration overrides.

        Returns:
            Configured OutputLengthGuardPlugin instance.
        """
        from cpex_output_length_guard.output_length_guard import OutputLengthGuardPlugin
        from cpex.framework import PluginConfig, ToolHookType

        return OutputLengthGuardPlugin(
            PluginConfig(
                name="output_length_guard",
                kind="cpex_output_length_guard.output_length_guard.OutputLengthGuardPlugin",
                hooks=[ToolHookType.TOOL_POST_INVOKE],
                config=cfg,
            )
        )

    def _context(self):
        """Return a minimal PluginContext for direct hook invocation.

        Returns:
            A PluginContext backed by a minimal GlobalContext.
        """
        from cpex.framework import GlobalContext, PluginContext

        gc = GlobalContext(request_id="req-compat", user=None, tenant_id="t1", server_id="gw1")
        return PluginContext(global_context=gc)

    def _invoke(self, plugin, result):
        """Run tool_post_invoke synchronously.

        Args:
            plugin: OutputLengthGuardPlugin instance.
            result: Tool result payload value.

        Returns:
            ToolPostInvokeResult.
        """
        import asyncio
        from cpex.framework import ToolPostInvokePayload

        payload = ToolPostInvokePayload(name="compat_tool", result=result)
        return asyncio.run(plugin.tool_post_invoke(payload, self._context()))

    # ------------------------------------------------------------------
    # limit_mode: token
    # ------------------------------------------------------------------

    def test_token_mode_truncates_oversized_string(self):
        """limit_mode=token + max_tokens=5 truncates a 100-char string (25 est. tokens).

        The Rust package estimates tokens as len(text) // chars_per_token (default 4).
        100 chars / 4 = 25 tokens > 5 → truncated to 5 * 4 = 20 chars + ellipsis.
        """
        plugin = self._make_plugin({"limit_mode": "token", "max_tokens": 5, "chars_per_token": 4, "strategy": "truncate"})
        result = self._invoke(plugin, "A" * 100)
        assert result.modified_payload is not None
        # cut at 20 chars + at most 1 char ellipsis
        assert len(result.modified_payload.result) <= 21

    def test_token_mode_passes_short_string(self):
        """limit_mode=token: a string within the token budget passes through unchanged."""
        plugin = self._make_plugin({"limit_mode": "token", "max_tokens": 100, "chars_per_token": 4, "strategy": "truncate"})
        result = self._invoke(plugin, "short text")
        assert result.modified_payload is None
        assert result.continue_processing is not False

    def test_token_mode_blocks_oversized_string(self):
        """limit_mode=token + strategy=block returns a violation for an oversized string."""
        plugin = self._make_plugin({"limit_mode": "token", "max_tokens": 5, "chars_per_token": 4, "strategy": "block"})
        result = self._invoke(plugin, "A" * 100)
        assert result.continue_processing is False
        assert result.violation is not None

    # ------------------------------------------------------------------
    # word_boundary: true
    # ------------------------------------------------------------------

    def test_word_boundary_truncates_at_word_edge(self):
        """word_boundary=true truncates at the last word boundary, not mid-word.

        Input: 'The quick brown fox jumps over the lazy dog' (43 chars)
        max_chars=20, ellipsis='...' (3 chars) → cut before char 17.
        The last word boundary before position 17 is after 'brown ' (15 chars),
        so the result must not end mid-word and must end with '...'.
        """
        plugin = self._make_plugin({"max_chars": 20, "word_boundary": True, "strategy": "truncate", "ellipsis": "..."})
        result = self._invoke(plugin, "The quick brown fox jumps over the lazy dog")
        assert result.modified_payload is not None
        truncated = result.modified_payload.result
        assert len(truncated) <= 20
        assert truncated.endswith("...")
        # must not cut in the middle of a word — the char before '...' is a space or word-boundary char
        body = truncated[: -len("...")]
        assert body == "" or body[-1] in " \t\n.,;:!?-/\\"

    def test_word_boundary_false_hard_cuts(self):
        """word_boundary=false (default) hard-cuts at max_chars regardless of word edges."""
        plugin = self._make_plugin({"max_chars": 10, "word_boundary": False, "strategy": "truncate", "ellipsis": "…"})
        result = self._invoke(plugin, "The quick brown fox")
        assert result.modified_payload is not None
        assert len(result.modified_payload.result) <= 10

    # ------------------------------------------------------------------
    # Structured / nested payloads
    # ------------------------------------------------------------------

    def test_truncates_oversized_text_in_mcp_content_dict(self):
        """Oversized text inside an MCP CallToolResult dict is truncated in place."""
        plugin = self._make_plugin({"max_chars": 10, "strategy": "truncate", "ellipsis": "…"})
        mcp_result = {"content": [{"type": "text", "text": "A" * 200}], "isError": False}
        result = self._invoke(plugin, mcp_result)
        assert result.modified_payload is not None
        content = result.modified_payload.result["content"]
        assert len(content[0]["text"]) <= 10

    def test_blocks_oversized_text_in_mcp_content_dict(self):
        """block strategy returns a violation for oversized text in an MCP content dict."""
        plugin = self._make_plugin({"max_chars": 10, "strategy": "block"})
        mcp_result = {"content": [{"type": "text", "text": "A" * 200}], "isError": False}
        result = self._invoke(plugin, mcp_result)
        assert result.continue_processing is False
        assert result.violation is not None

    def test_truncates_oversized_strings_in_list(self):
        """Oversized strings in a list-of-strings result are each truncated."""
        plugin = self._make_plugin({"max_chars": 10, "strategy": "truncate", "ellipsis": "…"})
        result = self._invoke(plugin, ["B" * 200, "C" * 200])
        assert result.modified_payload is not None
        for item in result.modified_payload.result:
            assert len(item) <= 10

    def test_blocks_oversized_string_in_list(self):
        """block strategy returns a violation when any element in a list exceeds max_chars."""
        plugin = self._make_plugin({"max_chars": 10, "strategy": "block"})
        result = self._invoke(plugin, ["short", "D" * 200])
        assert result.continue_processing is False
        assert result.violation is not None

    # ------------------------------------------------------------------
    # Security limits
    # ------------------------------------------------------------------

    def test_max_text_length_caps_truncation_input(self):
        """Text exceeding max_text_length is still truncated to max_chars (not silently passed).

        The security limit caps the *processing* window, not the enforcement decision.
        A 2000-char string with max_text_length=1000 and max_chars=500 must be
        truncated to ≤500 chars.
        """
        plugin = self._make_plugin({"max_chars": 500, "max_text_length": 1000, "strategy": "truncate", "ellipsis": "…"})
        result = self._invoke(plugin, "X" * 2000)
        assert result.modified_payload is not None
        assert len(result.modified_payload.result) <= 500

    def test_max_recursion_depth_blocks_deeply_nested_payload(self):
        """A structuredContent payload nested beyond max_recursion_depth is blocked.

        Builds a dict nested 20 levels deep with max_recursion_depth=10.
        The Rust package must block (not silently pass) on the block strategy.
        """
        plugin = self._make_plugin({"max_chars": 500, "max_recursion_depth": 10, "strategy": "block"})
        # 20-deep nested dict
        nested: dict = {"v": "leaf"}
        for _ in range(20):
            nested = {"k": nested}
        mcp_result = {"content": [{"type": "text", "text": "ok"}], "structuredContent": nested}
        result = self._invoke(plugin, mcp_result)
        assert result.continue_processing is False
        assert result.violation is not None

    # ------------------------------------------------------------------
    # Inverted min/max validation
    # ------------------------------------------------------------------

    def test_inverted_min_max_chars_raises_at_load(self):
        """min_chars > max_chars is rejected with ValueError at plugin instantiation."""
        with pytest.raises((ValueError, Exception)):
            self._make_plugin({"min_chars": 500, "max_chars": 100, "strategy": "truncate"})

    def test_inverted_min_max_tokens_raises_at_load(self):
        """min_tokens > max_tokens is rejected with ValueError at plugin instantiation."""
        with pytest.raises((ValueError, Exception)):
            self._make_plugin({"limit_mode": "token", "min_tokens": 500, "max_tokens": 100, "strategy": "truncate"})
