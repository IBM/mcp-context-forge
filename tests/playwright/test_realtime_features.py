# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/playwright/test_realtime_features.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

# Third-Party
from playwright.sync_api import expect, Page
import pytest


class TestRealtimeFeatures:
    """Real-time WebSocket and SSE feature tests for MCP Gateway Admin UI.

    Examples:
        pytest tests/playwright/test_realtime_features.py
    """

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_websocket_connection_lifecycle(self, page: Page, admin_page):
        """Test complete WebSocket connection lifecycle."""
        ws_events = []
        connection_count = 0

        def handle_websocket(ws):
            nonlocal connection_count
            connection_count += 1

            def on_frame_sent(frame):
                ws_events.append(("sent", frame.payload))

            def on_frame_received(frame):
                ws_events.append(("received", frame.payload))

            def on_close():
                ws_events.append(("close", None))

            ws.on("framesent", on_frame_sent)
            ws.on("framereceived", on_frame_received)
            ws.on("close", on_close)

        page.on("websocket", handle_websocket)
        page.click("#tab-monitoring")
        page.click('button:has-text("Start Monitoring")')
        page.wait_for_selector(".connection-status:has-text('Connected')")
        assert connection_count > 0
        page.click('button:has-text("Send Test Message")')
        page.wait_for_function(lambda: len(ws_events) > 0)
        assert len(ws_events) > 0
        page.click('button:has-text("Stop Monitoring")')
        page.wait_for_selector(".connection-status:has-text('Disconnected')")

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_server_sent_events(self, page: Page, admin_page):
        """Test Server-Sent Events (SSE) functionality."""
        sse_messages = []

        def handle_response(response):
            if "text/event-stream" in response.headers.get("content-type", ""):
                sse_messages.append(response.url)

        page.on("response", handle_response)
        page.click("#tab-monitoring")
        page.click('button:has-text("Enable SSE Updates")')
        page.wait_for_function(lambda: len(sse_messages) > 0)
        assert any("sse" in url for url in sse_messages)
        page.wait_for_selector(".sse-indicator.active")
        expect(page.locator(".live-updates")).to_be_visible()
