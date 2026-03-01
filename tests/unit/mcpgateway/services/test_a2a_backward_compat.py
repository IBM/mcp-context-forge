# -*- coding: utf-8 -*-
"""Tests for A2A v1.0 ↔ v0.3 backward compatibility layer.

Covers:
- Inbound part normalization (v0.3 kind-based → v1.0 flat)
- Outbound part de-normalization (v1.0 flat → v0.3 kind-based)
- Method name version mapping (PascalCase ↔ slash-style)
- Compat mode gating (reject v0.3 when disabled)
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_errors import A2AAgentError
from mcpgateway.services.a2a_service import A2AAgentService


@pytest.fixture(autouse=True)
def _mock_structured_logger():
    with patch("mcpgateway.services.a2a_service.structured_logger"):
        yield


@pytest.fixture
def service():
    return A2AAgentService()


# ======================================================================
# Inbound normalization: v0.3 → v1.0
# ======================================================================


class TestNormalizeMessagePartsInbound:
    """Test _normalize_message_parts_to_kind (v0.3 → v1.0 conversion)."""

    def test_passthrough_non_dict(self, service):
        assert service._normalize_message_parts_to_kind("hello") == "hello"

    def test_passthrough_no_message(self, service):
        params = {"foo": "bar"}
        assert service._normalize_message_parts_to_kind(params) == params

    def test_passthrough_no_parts(self, service):
        params = {"message": {"role": "user"}}
        result = service._normalize_message_parts_to_kind(params)
        assert result == params

    def test_v10_parts_unchanged(self, service):
        """v1.0 flat parts (no kind) pass through unchanged."""
        params = {"message": {"parts": [{"text": "hello"}]}}
        result = service._normalize_message_parts_to_kind(params)
        assert result["message"]["parts"] == [{"text": "hello"}]

    def test_v03_content_field_to_parts(self, service):
        """v0.3 'content' field is renamed to 'parts'."""
        params = {"message": {"content": [{"text": "hello"}]}}
        result = service._normalize_message_parts_to_kind(params)
        assert "parts" in result["message"]
        assert "content" not in result["message"]
        assert result["message"]["parts"] == [{"text": "hello"}]

    def test_v03_text_kind(self, service):
        """v0.3 kind='text' is stripped, text key preserved."""
        params = {"message": {"parts": [{"kind": "text", "text": "hello"}]}}
        result = service._normalize_message_parts_to_kind(params)
        assert result["message"]["parts"] == [{"text": "hello"}]

    def test_v03_file_kind_with_uri(self, service):
        """v0.3 kind='file' with nested file.fileWithUri flattens to url."""
        params = {"message": {"parts": [
            {"kind": "file", "file": {"fileWithUri": "https://example.com/doc.pdf", "mimeType": "application/pdf", "name": "doc.pdf"}}
        ]}}
        result = service._normalize_message_parts_to_kind(params)
        part = result["message"]["parts"][0]
        assert part["url"] == "https://example.com/doc.pdf"
        assert part["media_type"] == "application/pdf"
        assert part["filename"] == "doc.pdf"
        assert "kind" not in part
        assert "file" not in part

    def test_v03_file_kind_with_bytes(self, service):
        """v0.3 kind='file' with nested file.fileWithBytes flattens to raw."""
        params = {"message": {"parts": [
            {"kind": "file", "file": {"fileWithBytes": "base64data==", "mimeType": "image/png"}}
        ]}}
        result = service._normalize_message_parts_to_kind(params)
        part = result["message"]["parts"][0]
        assert part["raw"] == "base64data=="
        assert part["media_type"] == "image/png"

    def test_v03_file_kind_snake_case(self, service):
        """v0.3 file fields with snake_case accepted."""
        params = {"message": {"parts": [
            {"kind": "file", "file": {"file_with_uri": "s3://bucket/key", "mime_type": "text/plain"}}
        ]}}
        result = service._normalize_message_parts_to_kind(params)
        part = result["message"]["parts"][0]
        assert part["url"] == "s3://bucket/key"
        assert part["media_type"] == "text/plain"

    def test_v03_file_kind_string_shorthand(self, service):
        """v0.3 file as plain string → url."""
        params = {"message": {"parts": [
            {"kind": "file", "file": "https://example.com/file.txt"}
        ]}}
        result = service._normalize_message_parts_to_kind(params)
        assert result["message"]["parts"][0]["url"] == "https://example.com/file.txt"

    def test_v03_data_kind(self, service):
        """v0.3 kind='data' with nested data.data flattens."""
        params = {"message": {"parts": [
            {"kind": "data", "data": {"data": {"key": "value"}}}
        ]}}
        result = service._normalize_message_parts_to_kind(params)
        part = result["message"]["parts"][0]
        assert part["data"] == {"key": "value"}
        assert "kind" not in part

    def test_v03_data_kind_direct_value(self, service):
        """v0.3 kind='data' where data is not a dict wrapping."""
        params = {"message": {"parts": [
            {"kind": "data", "data": [1, 2, 3]}
        ]}}
        result = service._normalize_message_parts_to_kind(params)
        assert result["message"]["parts"][0]["data"] == [1, 2, 3]

    def test_v03_type_discriminator_fallback(self, service):
        """Legacy 'type' discriminator accepted as fallback."""
        params = {"message": {"parts": [{"type": "text", "text": "hi"}]}}
        result = service._normalize_message_parts_to_kind(params)
        part = result["message"]["parts"][0]
        assert part == {"text": "hi"}

    def test_mixed_v03_v10_parts(self, service):
        """Mix of v0.3 and v1.0 parts normalizes correctly."""
        params = {"message": {"parts": [
            {"kind": "text", "text": "hello"},
            {"text": "world"},
            {"kind": "file", "file": {"uri": "https://x.com/f"}},
        ]}}
        result = service._normalize_message_parts_to_kind(params)
        parts = result["message"]["parts"]
        assert parts[0] == {"text": "hello"}
        assert parts[1] == {"text": "world"}
        assert parts[2] == {"url": "https://x.com/f"}

    def test_does_not_mutate_original(self, service):
        """Normalization creates a deep copy, not mutating the original."""
        original = {"message": {"content": [{"kind": "text", "text": "hi"}]}}
        service._normalize_message_parts_to_kind(original)
        assert "content" in original["message"]
        assert original["message"]["content"][0]["kind"] == "text"


# ======================================================================
# Outbound de-normalization: v1.0 → v0.3
# ======================================================================


class TestNormalizeOutboundForV03:
    """Test _normalize_outbound_for_v03 (v1.0 → v0.3 conversion)."""

    def test_passthrough_non_dict(self):
        assert A2AAgentService._normalize_outbound_for_v03("hello") == "hello"

    def test_passthrough_no_message(self):
        params = {"foo": "bar"}
        assert A2AAgentService._normalize_outbound_for_v03(params) == params

    def test_passthrough_no_parts(self):
        params = {"message": {"role": "user"}}
        result = A2AAgentService._normalize_outbound_for_v03(params)
        assert result == params

    def test_text_part(self):
        """v1.0 flat text → v0.3 kind='text'."""
        params = {"message": {"parts": [{"text": "hello"}]}}
        result = A2AAgentService._normalize_outbound_for_v03(params)
        assert result["message"]["content"] == [{"kind": "text", "text": "hello"}]
        assert "parts" not in result["message"]

    def test_url_file_part(self):
        """v1.0 url + media_type + filename → v0.3 kind='file' with nested file object."""
        params = {"message": {"parts": [
            {"url": "https://example.com/doc.pdf", "media_type": "application/pdf", "filename": "doc.pdf"}
        ]}}
        result = A2AAgentService._normalize_outbound_for_v03(params)
        part = result["message"]["content"][0]
        assert part["kind"] == "file"
        assert part["file"]["uri"] == "https://example.com/doc.pdf"
        assert part["file"]["mimeType"] == "application/pdf"
        assert part["file"]["name"] == "doc.pdf"

    def test_raw_bytes_file_part(self):
        """v1.0 raw → v0.3 kind='file' with file.bytes."""
        params = {"message": {"parts": [
            {"raw": "base64data==", "media_type": "image/png"}
        ]}}
        result = A2AAgentService._normalize_outbound_for_v03(params)
        part = result["message"]["content"][0]
        assert part["kind"] == "file"
        assert part["file"]["bytes"] == "base64data=="
        assert part["file"]["mimeType"] == "image/png"

    def test_data_part(self):
        """v1.0 data → v0.3 kind='data' with nested data.data."""
        params = {"message": {"parts": [{"data": {"key": "value"}}]}}
        result = A2AAgentService._normalize_outbound_for_v03(params)
        part = result["message"]["content"][0]
        assert part["kind"] == "data"
        assert part["data"] == {"data": {"key": "value"}}

    def test_mixed_parts(self):
        """Multiple part types convert correctly."""
        params = {"message": {"parts": [
            {"text": "hello"},
            {"url": "https://x.com/f"},
            {"data": [1, 2]},
        ]}}
        result = A2AAgentService._normalize_outbound_for_v03(params)
        content = result["message"]["content"]
        assert content[0] == {"kind": "text", "text": "hello"}
        assert content[1]["kind"] == "file"
        assert content[1]["file"]["uri"] == "https://x.com/f"
        assert content[2]["kind"] == "data"

    def test_unknown_part_passes_through(self):
        """Parts without recognized keys pass through unchanged."""
        params = {"message": {"parts": [{"custom_key": "custom_value"}]}}
        result = A2AAgentService._normalize_outbound_for_v03(params)
        assert result["message"]["content"] == [{"custom_key": "custom_value"}]

    def test_does_not_mutate_original(self):
        """De-normalization creates a deep copy."""
        original = {"message": {"parts": [{"text": "hi"}]}}
        A2AAgentService._normalize_outbound_for_v03(original)
        assert "parts" in original["message"]

    def test_roundtrip_text(self, service):
        """v0.3 → v1.0 → v0.3 roundtrip for text parts."""
        v03 = {"message": {"content": [{"kind": "text", "text": "hello"}]}}
        v10 = service._normalize_message_parts_to_kind(v03)
        back_to_v03 = A2AAgentService._normalize_outbound_for_v03(v10)
        assert back_to_v03["message"]["content"] == [{"kind": "text", "text": "hello"}]

    def test_roundtrip_file(self, service):
        """v0.3 → v1.0 → v0.3 roundtrip for file parts."""
        v03 = {"message": {"content": [
            {"kind": "file", "file": {"uri": "https://example.com/f", "mimeType": "text/plain", "name": "f.txt"}}
        ]}}
        v10 = service._normalize_message_parts_to_kind(v03)
        back_to_v03 = A2AAgentService._normalize_outbound_for_v03(v10)
        file_obj = back_to_v03["message"]["content"][0]["file"]
        assert file_obj["uri"] == "https://example.com/f"
        assert file_obj["mimeType"] == "text/plain"
        assert file_obj["name"] == "f.txt"


# ======================================================================
# Method name mapping
# ======================================================================


class TestOutboundMethodForVersion:
    """Test _outbound_method_for_version mapping."""

    def test_v10_passthrough(self):
        """v1.0 agents keep PascalCase method names."""
        assert A2AAgentService._outbound_method_for_version("SendMessage", "1.0") == "SendMessage"
        assert A2AAgentService._outbound_method_for_version("GetTask", "1.0") == "GetTask"

    def test_v10_prefix_passthrough(self):
        """Versions starting with '1.' are treated as v1.0."""
        assert A2AAgentService._outbound_method_for_version("SendMessage", "1.1") == "SendMessage"

    def test_v1_bare_passthrough(self):
        """Version '1' (no dot) is treated as v1.0."""
        assert A2AAgentService._outbound_method_for_version("SendMessage", "1") == "SendMessage"

    def test_v03_maps_send_message(self):
        assert A2AAgentService._outbound_method_for_version("SendMessage", "0.3") == "message/send"

    def test_v03_maps_send_stream_message(self):
        assert A2AAgentService._outbound_method_for_version("SendStreamMessage", "0.3") == "message/stream"

    def test_v03_maps_get_task(self):
        assert A2AAgentService._outbound_method_for_version("GetTask", "0.3") == "tasks/get"

    def test_v03_maps_list_tasks(self):
        assert A2AAgentService._outbound_method_for_version("ListTasks", "0.3") == "tasks/list"

    def test_v03_maps_cancel_task(self):
        assert A2AAgentService._outbound_method_for_version("CancelTask", "0.3") == "tasks/cancel"

    def test_v03_maps_subscribe_task(self):
        assert A2AAgentService._outbound_method_for_version("SubscribeTask", "0.3") == "tasks/subscribe"

    def test_v03_maps_agent_card(self):
        assert A2AAgentService._outbound_method_for_version("GetAgentCard", "0.3") == "agent/card"

    def test_v03_maps_extended_agent_card(self):
        assert A2AAgentService._outbound_method_for_version("GetExtendedAgentCard", "0.3") == "agent/extendedcard"

    def test_v03_unknown_method_passthrough(self):
        """Unknown method names pass through for v0.3 agents."""
        assert A2AAgentService._outbound_method_for_version("CustomMethod", "0.3") == "CustomMethod"

    def test_all_push_notification_methods(self):
        """All push notification config methods map correctly."""
        assert A2AAgentService._outbound_method_for_version("SetPushNotificationConfig", "0.3") == "tasks/pushNotificationConfig/set"
        assert A2AAgentService._outbound_method_for_version("GetPushNotificationConfig", "0.3") == "tasks/pushNotificationConfig/get"
        assert A2AAgentService._outbound_method_for_version("ListPushNotificationConfigs", "0.3") == "tasks/pushNotificationConfig/list"
        assert A2AAgentService._outbound_method_for_version("DeletePushNotificationConfig", "0.3") == "tasks/pushNotificationConfig/delete"


# ======================================================================
# Compat mode gating
# ======================================================================


class TestCompatModeGating:
    """Test rejection of v0.3 formats when compat mode is disabled."""

    def test_v03_content_field_rejected_when_compat_off(self, service):
        """v0.3 'content' field raises when compat mode is off."""
        params = {"message": {"content": [{"text": "hello"}]}}
        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.mcpgateway_a2a_v1_compat_mode = False
            with pytest.raises(A2AAgentError, match="'content' field is deprecated"):
                service._normalize_message_parts_to_kind(params)

    def test_v03_kind_rejected_when_compat_off(self, service):
        """v0.3 kind discriminator raises when compat mode is off."""
        params = {"message": {"parts": [{"kind": "text", "text": "hello"}]}}
        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.mcpgateway_a2a_v1_compat_mode = False
            with pytest.raises(A2AAgentError, match="'kind' discriminator is deprecated"):
                service._normalize_message_parts_to_kind(params)

    def test_v10_parts_accepted_when_compat_off(self, service):
        """v1.0 flat parts still work when compat mode is off."""
        params = {"message": {"parts": [{"text": "hello"}]}}
        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.mcpgateway_a2a_v1_compat_mode = False
            result = service._normalize_message_parts_to_kind(params)
            assert result["message"]["parts"] == [{"text": "hello"}]

    def test_v03_content_accepted_when_compat_on(self, service):
        """v0.3 'content' field normalizes when compat mode is on (default)."""
        params = {"message": {"content": [{"text": "hello"}]}}
        result = service._normalize_message_parts_to_kind(params)
        assert result["message"]["parts"] == [{"text": "hello"}]

    def test_v03_method_rejected_when_compat_off(self):
        """v0.3 slash-style method names rejected by prepare_rpc_params."""
        from mcpgateway.services.a2a_dispatcher import prepare_rpc_params

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.mcpgateway_a2a_v1_compat_mode = False
            with pytest.raises(A2AAgentError, match="v0.3 method name"):
                prepare_rpc_params(
                    {"method": "message/send", "params": {}},
                    "a2a-jsonrpc",
                )

    def test_v10_method_accepted_when_compat_off(self):
        """v1.0 PascalCase method names work when compat mode is off."""
        from mcpgateway.services.a2a_dispatcher import prepare_rpc_params

        with patch("mcpgateway.config.settings") as mock_settings:
            mock_settings.mcpgateway_a2a_v1_compat_mode = False
            method, params = prepare_rpc_params(
                {"method": "SendMessage", "params": {"message": {"parts": []}}},
                "a2a-jsonrpc",
            )
            assert method == "SendMessage"
