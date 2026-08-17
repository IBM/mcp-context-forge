# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_email_notification_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for auth email notification service.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from jinja2 import TemplateNotFound
import pytest

# First-Party
from mcpgateway.services.email_notification_service import AuthEmailNotificationService, build_frontend_url
from mcpgateway.schemas import EmailDeliveryStatus


class TestAuthEmailNotificationService:
    """Test cases for AuthEmailNotificationService."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return AuthEmailNotificationService()

    def test_smtp_password_none(self, service):
        """_smtp_password returns None when not configured."""
        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_password = None
            assert service._smtp_password() is None

    def test_smtp_password_secret_object(self, service):
        """_smtp_password reads SecretStr-like values."""

        class SecretLike:
            def get_secret_value(self):
                return "secret-value"

        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_password = SecretLike()
            assert service._smtp_password() == "secret-value"

    def test_smtp_password_plain_value(self, service):
        """_smtp_password stringifies plain values."""
        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_password = 123
            assert service._smtp_password() == "123"

    def test_smtp_ready_true_and_false(self, service):
        """_smtp_ready reflects required SMTP configuration."""
        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_enabled = False
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_from_email = "noreply@example.com"
            assert service._smtp_ready() is False

        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_enabled = True
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_from_email = "noreply@example.com"
            assert service._smtp_ready() is True

    def test_build_frontend_url_prefers_ui_base_and_encodes_token(self):
        """Frontend links use configured React base and encode token as one segment."""
        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.ui_base_url = "https://ui.example.com/contextforge/"
            result = build_frontend_url("/accept-invitation", "tok/en ?")

        assert result == "https://ui.example.com/contextforge/accept-invitation/tok%2Fen%20%3F"

    @pytest.mark.parametrize(
        ("admin_api_enabled", "expected_url"),
        [
            (True, "https://gateway.example.com/root/admin/forgot-password"),
            (False, "https://gateway.example.com/root/forgot-password"),
        ],
    )
    def test_build_frontend_url_falls_back_to_domain_and_root_path(self, admin_api_enabled, expected_url):
        """Password fallback uses Admin UI only when its routes are mounted."""
        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.ui_base_url = None
            mock_settings.app_domain = "https://gateway.example.com/"
            mock_settings.app_root_path = "/root/"
            mock_settings.mcpgateway_admin_api_enabled = admin_api_enabled
            result = build_frontend_url("/forgot-password")

        assert result == expected_url

    def test_build_frontend_url_invitation_fallback_remains_frontend_route(self):
        """Invitation fallback does not inherit legacy Admin UI prefix."""
        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.ui_base_url = None
            mock_settings.app_domain = "https://gateway.example.com/"
            mock_settings.app_root_path = "/root/"
            result = build_frontend_url("/accept-invitation", "tok/en")

        assert result == "https://gateway.example.com/root/accept-invitation/tok%2Fen"

    def test_build_frontend_url_rejects_untrusted_path_shape(self):
        """Frontend helper rejects relative and scheme-relative paths."""
        with pytest.raises(ValueError):
            build_frontend_url("reset-password")
        with pytest.raises(ValueError):
            build_frontend_url("//attacker.example/path")

    def test_render_template_success(self, service):
        """_render_template returns rendered template when available."""
        result = service._render_template(
            template_name="password_reset_email.html",
            context={"display_name": "User", "reset_url": "https://example/reset", "expires_minutes": 60, "recipient_email": "user@example.com"},
            fallback_title="Fallback",
            fallback_body="Fallback body",
        )
        assert "Password Reset Request" in result

    def test_render_template_template_not_found_fallback(self, service):
        """_render_template falls back when template is missing."""
        with patch.object(service._jinja, "get_template", side_effect=TemplateNotFound("missing.html")):
            result = service._render_template(
                template_name="missing.html",
                context={},
                fallback_title="Fallback Title",
                fallback_body="Fallback\nBody",
            )
        assert "Fallback Title" in result
        assert "Fallback<br/>Body" in result

    def test_render_template_generic_exception_fallback(self, service):
        """_render_template falls back on rendering exceptions."""
        with patch.object(service._jinja, "get_template", side_effect=RuntimeError("boom")):
            result = service._render_template(
                template_name="bad.html",
                context={},
                fallback_title="Fallback",
                fallback_body="Body",
            )
        assert "Fallback" in result
        assert "Body" in result

    def test_html_to_text(self, service):
        """_html_to_text strips tags and normalizes whitespace."""
        assert service._html_to_text("<p>Hello</p>   <b>World</b>") == "Hello World"

    @pytest.mark.asyncio
    async def test_send_email_returns_false_when_smtp_not_ready(self, service):
        """_send_email exits early when SMTP is not ready."""
        with patch.object(service, "_smtp_ready", return_value=False):
            result = await service._send_email("user@example.com", "Subject", "<p>Body</p>")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_email_delegates_to_thread(self, service):
        """_send_email delegates sync send to thread when SMTP is ready."""
        with patch.object(service, "_smtp_ready", return_value=True):
            with patch("mcpgateway.services.email_notification_service.asyncio.to_thread", new=AsyncMock(return_value=True)) as to_thread:
                result = await service._send_email("user@example.com", "Subject", "<p>Body</p>")
        assert result is True
        to_thread.assert_awaited_once()

    def test_send_email_sync_ssl_success(self, service):
        """_send_email_sync sends via SMTP_SSL when configured."""
        smtp_context = MagicMock()
        smtp_server = MagicMock()
        smtp_context.__enter__.return_value = smtp_server

        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_from_email = "noreply@example.com"
            mock_settings.smtp_from_name = "ContextForge"
            mock_settings.smtp_user = "smtp-user"
            mock_settings.smtp_password = "smtp-pass"  # pragma: allowlist secret
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 465
            mock_settings.smtp_timeout_seconds = 5
            mock_settings.smtp_use_ssl = True
            mock_settings.smtp_use_tls = False

            with patch.object(service, "_smtp_password", return_value="smtp-pass"):
                with patch("mcpgateway.services.email_notification_service.smtplib.SMTP_SSL", return_value=smtp_context):
                    result = service._send_email_sync("to@example.com", "Subject", "<p>Body</p>")

        assert result is True
        smtp_server.login.assert_called_once_with("smtp-user", "smtp-pass")
        smtp_server.send_message.assert_called_once()

    def test_send_email_sync_starttls_success(self, service):
        """_send_email_sync sends via SMTP + STARTTLS when configured."""
        smtp_context = MagicMock()
        smtp_server = MagicMock()
        smtp_context.__enter__.return_value = smtp_server

        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_from_email = "noreply@example.com"
            mock_settings.smtp_from_name = "ContextForge"
            mock_settings.smtp_user = "smtp-user"
            mock_settings.smtp_password = "smtp-pass"  # pragma: allowlist secret
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_timeout_seconds = 5
            mock_settings.smtp_use_ssl = False
            mock_settings.smtp_use_tls = True

            with patch.object(service, "_smtp_password", return_value="smtp-pass"):
                with patch("mcpgateway.services.email_notification_service.smtplib.SMTP", return_value=smtp_context):
                    with patch("mcpgateway.services.email_notification_service.ssl.create_default_context", return_value=object()):
                        result = service._send_email_sync("to@example.com", "Subject", "<p>Body</p>")

        assert result is True
        assert smtp_server.ehlo.call_count >= 2
        smtp_server.starttls.assert_called_once()
        smtp_server.login.assert_called_once_with("smtp-user", "smtp-pass")
        smtp_server.send_message.assert_called_once()

    def test_send_email_sync_returns_false_on_exception(self, service):
        """_send_email_sync returns False on SMTP exception."""
        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_from_email = "noreply@example.com"
            mock_settings.smtp_from_name = "ContextForge"
            mock_settings.smtp_user = None
            mock_settings.smtp_password = None
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_timeout_seconds = 5
            mock_settings.smtp_use_ssl = False
            mock_settings.smtp_use_tls = True

            with patch("mcpgateway.services.email_notification_service.smtplib.SMTP", side_effect=RuntimeError("smtp down")):
                result = service._send_email_sync("to@example.com", "Subject", "<p>Body</p>")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_password_reset_email_uses_fallback_name(self, service):
        """send_password_reset_email uses local-part when full_name is missing."""
        with patch.object(service, "_send_email", new=AsyncMock(return_value=True)) as send_mock:
            result = await service.send_password_reset_email("alice@example.com", None, "https://example/reset", 30)

        assert result is True
        call_args = send_mock.await_args[0]
        assert call_args[0] == "alice@example.com"
        assert "Reset your ContextForge password" == call_args[1]
        assert "alice" in call_args[2]

    @pytest.mark.asyncio
    async def test_send_password_reset_confirmation_email(self, service):
        """send_password_reset_confirmation_email composes confirmation email."""
        with patch.object(service, "_send_email", new=AsyncMock(return_value=True)) as send_mock:
            result = await service.send_password_reset_confirmation_email("bob@example.com", "Bob")

        assert result is True
        call_args = send_mock.await_args[0]
        assert call_args[0] == "bob@example.com"
        assert "password was changed" in call_args[1].lower()
        assert "Bob" in call_args[2]

    @pytest.mark.asyncio
    async def test_send_account_lockout_email(self, service):
        """send_account_lockout_email composes lockout email."""
        with patch.object(service, "_send_email", new=AsyncMock(return_value=True)) as send_mock:
            result = await service.send_account_lockout_email(
                "eve@example.com",
                None,
                "2026-02-15T12:00:00+00:00",
                "https://example/forgot",
            )

        assert result is True
        call_args = send_mock.await_args[0]
        assert call_args[0] == "eve@example.com"
        assert "temporarily locked" in call_args[1].lower()
        assert "eve" in call_args[2]

    @pytest.mark.asyncio
    async def test_send_team_invitation_email_has_html_and_plaintext(self, service):
        """Invitation email includes trusted link and raw-token fallback in both parts."""
        with patch.object(service, "_send_email", new=AsyncMock(return_value=True)) as send_mock:
            result = await service.send_team_invitation_email(
                to_email="invitee@example.com",
                team_name="Engineering",
                inviter_name="Alice",
                role="member",
                invitation_url="https://ui.example/accept-invitation/token",
                expires_at="2026-08-20T12:00:00+00:00",
                token="token",
            )

        assert result is True
        args = send_mock.await_args.args
        assert "Engineering" in args[1]
        assert "https://ui.example/accept-invitation/token" in args[2]
        assert "Fallback invitation token: token" in args[3]

    @pytest.mark.asyncio
    async def test_send_team_invitation_email_autoescapes_user_values(self, service):
        """Invitation HTML escapes team and inviter values."""
        with patch.object(service, "_send_email", new=AsyncMock(return_value=True)) as send_mock:
            await service.send_team_invitation_email(
                to_email="invitee@example.com",
                team_name="<script>alert(1)</script>",
                inviter_name="<b>Alice</b>",
                role="member",
                invitation_url="https://ui.example/accept-invitation/token",
                expires_at="2026-08-20T12:00:00+00:00",
                token="token",
            )

        html_body = send_mock.await_args.args[2]
        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body
        assert "<b>Alice</b>" not in html_body

    @pytest.mark.asyncio
    async def test_deliver_team_invitation_email_statuses(self, service):
        """Delivery distinguishes disabled, successful, and failed SMTP."""
        kwargs = {
            "invitation_id": "invite-id",
            "to_email": "invitee@example.com",
            "team_name": "Engineering",
            "inviter_name": "Alice",
            "role": "member",
            "invitation_url": "https://ui.example/accept-invitation/token",
            "expires_at": "2026-08-20T12:00:00+00:00",
            "token": "token",
        }
        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_enabled = False
            with patch.object(service, "send_team_invitation_email", new=AsyncMock()) as send_mock:
                assert await service.deliver_team_invitation_email(**kwargs) == EmailDeliveryStatus.DISABLED
                send_mock.assert_not_awaited()

            mock_settings.smtp_enabled = True
            with patch.object(service, "send_team_invitation_email", new=AsyncMock(return_value=True)):
                assert await service.deliver_team_invitation_email(**kwargs) == EmailDeliveryStatus.SENT
            with patch.object(service, "send_team_invitation_email", new=AsyncMock(return_value=False)):
                assert await service.deliver_team_invitation_email(**kwargs) == EmailDeliveryStatus.FAILED

    @pytest.mark.asyncio
    async def test_delivery_logs_do_not_expose_tokens_or_smtp_error(self, service, caplog):
        """Failed delivery logs invitation ID without token or transport details."""
        secret_token = "invitation-token-canary"  # pragma: allowlist secret
        smtp_detail = "smtp-password-canary"  # pragma: allowlist secret
        with (
            patch("mcpgateway.services.email_notification_service.settings") as mock_settings,
            patch.object(service, "send_team_invitation_email", new=AsyncMock(side_effect=RuntimeError(smtp_detail))),
        ):
            mock_settings.smtp_enabled = True
            status = await service.deliver_team_invitation_email(
                invitation_id="invite-id",
                to_email="invitee@example.com",
                team_name="Engineering",
                inviter_name="Alice",
                role="member",
                invitation_url=f"https://ui.example/accept-invitation/{secret_token}",
                expires_at="2026-08-20T12:00:00+00:00",
                token=secret_token,
            )

        assert status == EmailDeliveryStatus.FAILED
        assert "invite-id" in caplog.text
        assert secret_token not in caplog.text
        assert smtp_detail not in caplog.text

    @pytest.mark.asyncio
    async def test_enabled_but_incomplete_smtp_is_failed_without_connection(self, service):
        """Enabled SMTP missing required settings reports failed, not disabled."""
        with patch("mcpgateway.services.email_notification_service.settings") as mock_settings:
            mock_settings.smtp_enabled = True
            mock_settings.smtp_host = None
            mock_settings.smtp_from_email = None
            with patch.object(service, "_send_email_sync") as sync_send:
                status = await service.deliver_team_invitation_email(
                    invitation_id="invite-id",
                    to_email="invitee@example.com",
                    team_name="Engineering",
                    inviter_name="Alice",
                    role="member",
                    invitation_url="https://ui.example/accept-invitation/token",
                    expires_at="2026-08-20T12:00:00+00:00",
                    token="token",
                )

        assert status == EmailDeliveryStatus.FAILED
        sync_send.assert_not_called()
