# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/email_notification_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Email notification service for authentication workflows.
"""

# Standard
import asyncio
from email.message import EmailMessage
from email.utils import formataddr
import html
from pathlib import Path
import re
import smtplib
import ssl
from typing import Any, Dict, Optional
import urllib.parse

# Third-Party
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.schemas import EmailDeliveryStatus
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


def build_frontend_url(path: str, token: Optional[str] = None) -> str:
    """Build a trusted browser-facing URL for email notifications.

    Args:
        path: Frontend route beginning with ``/``.
        token: Optional secret token appended as one URL-encoded path segment.

    Returns:
        str: Absolute frontend URL.

    Raises:
        ValueError: If path is not an absolute frontend route.
    """
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Frontend path must start with exactly one slash")

    configured_ui_base = getattr(settings, "ui_base_url", None)
    if configured_ui_base:
        base_url = str(configured_ui_base).rstrip("/")
    else:
        app_domain = str(getattr(settings, "app_domain", "http://localhost:4444")).rstrip("/")
        root_path = str(getattr(settings, "app_root_path", "") or "").strip("/")
        base_url = f"{app_domain}/{root_path}" if root_path else app_domain
        # Preserve bundled Admin UI password recovery only when those routes are mounted.
        if path in {"/forgot-password", "/reset-password"} and settings.mcpgateway_admin_api_enabled:
            path = f"/admin{path}"

    url = f"{base_url}{path}"
    if token is not None:
        url = f"{url.rstrip('/')}/{urllib.parse.quote(token, safe='')}"
    return url


class AuthEmailNotificationService:
    """Send authentication-related email notifications."""

    def __init__(self) -> None:
        """Initialize template rendering for authentication emails."""
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self._jinja = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "xml"]))

    @staticmethod
    def _smtp_password() -> Optional[str]:
        """Resolve SMTP password from settings.

        Returns:
            Optional[str]: SMTP password string or None when unset.
        """
        raw = getattr(settings, "smtp_password", None)
        if raw is None:
            return None
        if hasattr(raw, "get_secret_value"):
            return raw.get_secret_value()
        return str(raw)

    @staticmethod
    def _smtp_ready() -> bool:
        """Check whether minimum SMTP settings are available.

        Returns:
            bool: True when SMTP delivery is enabled and required fields exist.
        """
        return bool(getattr(settings, "smtp_enabled", False) and getattr(settings, "smtp_host", None) and getattr(settings, "smtp_from_email", None))

    def _render_template(self, template_name: str, context: Dict[str, Any], fallback_title: str, fallback_body: str) -> str:
        """Render an email template with graceful fallback.

        Args:
            template_name: Jinja template filename.
            context: Rendering context values.
            fallback_title: Fallback HTML title when template fails.
            fallback_body: Fallback body text when template fails.

        Returns:
            str: Rendered HTML email body.
        """
        try:
            template = self._jinja.get_template(template_name)
            return template.render(**context)
        except TemplateNotFound:
            logger.warning("Email template %s not found. Using fallback template.", template_name)
        except Exception as exc:
            logger.warning("Failed to render email template %s: %s. Using fallback template.", template_name, exc)

        safe_title = html.escape(fallback_title)
        safe_body = html.escape(fallback_body).replace("\n", "<br/>")
        return f"<html><body><h2>{safe_title}</h2><p>{safe_body}</p></body></html>"

    @staticmethod
    def _html_to_text(value: str) -> str:
        """Convert simple HTML content to plain text.

        Args:
            value: HTML value.

        Returns:
            str: Text-only representation.
        """
        no_tags = re.sub(r"<[^>]+>", " ", value)
        compact = re.sub(r"\s+", " ", no_tags).strip()
        return compact

    async def _send_email(self, to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
        """Send an email asynchronously.

        Args:
            to_email: Destination email address.
            subject: Message subject.
            html_body: HTML message body.
            text_body: Optional explicit plaintext message body.

        Returns:
            bool: True when message is sent successfully.
        """
        if not self._smtp_ready():
            logger.info("SMTP not configured. Skipping email to %s with subject '%s'.", to_email, subject)
            return False
        return await asyncio.to_thread(self._send_email_sync, to_email, subject, html_body, text_body)

    def _send_email_sync(self, to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
        """Send an email synchronously over SMTP.

        Args:
            to_email: Destination email address.
            subject: Message subject.
            html_body: HTML message body.
            text_body: Optional explicit plaintext message body.

        Returns:
            bool: True when message is sent successfully.
        """
        from_email = str(getattr(settings, "smtp_from_email", "") or "")
        from_name = str(getattr(settings, "smtp_from_name", "ContextForge") or "ContextForge")
        smtp_user = getattr(settings, "smtp_user", None)
        smtp_password = self._smtp_password()

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((from_name, from_email))
        message["To"] = to_email
        message.set_content(text_body or self._html_to_text(html_body))
        message.add_alternative(html_body, subtype="html")

        smtp_host = str(getattr(settings, "smtp_host", ""))
        smtp_port = int(getattr(settings, "smtp_port", 587))
        timeout_seconds = int(getattr(settings, "smtp_timeout_seconds", 15))
        use_ssl = bool(getattr(settings, "smtp_use_ssl", False))
        use_tls = bool(getattr(settings, "smtp_use_tls", True))

        try:
            if use_ssl:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout_seconds) as server:
                    if smtp_user and smtp_password:
                        server.login(str(smtp_user), smtp_password)
                    server.send_message(message)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout_seconds) as server:
                    server.ehlo()
                    if use_tls:
                        server.starttls(context=ssl.create_default_context())
                        server.ehlo()
                    if smtp_user and smtp_password:
                        server.login(str(smtp_user), smtp_password)
                    server.send_message(message)

            logger.info("Auth notification email sent to %s", to_email)
            return True
        except Exception as exc:
            logger.warning("Failed to send auth notification email to %s (%s)", to_email, type(exc).__name__)
            return False

    async def send_team_invitation_email(
        self,
        to_email: str,
        team_name: str,
        inviter_name: str,
        role: str,
        invitation_url: str,
        expires_at: str,
        token: str,
    ) -> bool:
        """Send a team invitation email.

        Args:
            to_email: Destination email address.
            team_name: Invited team display name.
            inviter_name: Inviter display name.
            role: Role granted after acceptance.
            invitation_url: Trusted frontend acceptance URL.
            expires_at: Invitation expiry timestamp.
            token: Raw invitation token included as fallback.

        Returns:
            bool: True when message is sent successfully.
        """
        subject = f"Invitation to join {team_name} on ContextForge"
        html_body = self._render_template(
            template_name="team_invitation_email.html",
            context={
                "recipient_email": to_email,
                "team_name": team_name,
                "inviter_name": inviter_name,
                "role": role,
                "invitation_url": invitation_url,
                "expires_at": expires_at,
                "token": token,
            },
            fallback_title="Team invitation",
            fallback_body=f"{inviter_name} invited you to join {team_name} as {role}. Accept: {invitation_url}\nExpires: {expires_at}\nToken: {token}",
        )
        text_body = (
            "ContextForge team invitation\n\n"
            f"{inviter_name} invited you to join {team_name} as {role}.\n\n"
            f"Accept invitation: {invitation_url}\n"
            f"Expires: {expires_at}\n\n"
            f"Fallback invitation token: {token}\n"
        )
        return await self._send_email(to_email, subject, html_body, text_body)

    async def deliver_team_invitation_email(
        self,
        invitation_id: str,
        to_email: str,
        team_name: str,
        inviter_name: str,
        role: str,
        invitation_url: str,
        expires_at: str,
        token: str,
    ) -> EmailDeliveryStatus:
        """Deliver a persisted invitation without exposing transport failures.

        Args:
            invitation_id: Persisted invitation identifier used for safe logging.
            to_email: Destination email address.
            team_name: Invited team display name.
            inviter_name: Inviter display name.
            role: Role granted after acceptance.
            invitation_url: Trusted frontend acceptance URL.
            expires_at: Invitation expiry timestamp.
            token: Raw invitation token included in the email only.

        Returns:
            EmailDeliveryStatus: Delivery outcome.
        """
        if not getattr(settings, "smtp_enabled", False):
            return EmailDeliveryStatus.DISABLED

        try:
            sent = await self.send_team_invitation_email(
                to_email=to_email,
                team_name=team_name,
                inviter_name=inviter_name,
                role=role,
                invitation_url=invitation_url,
                expires_at=expires_at,
                token=token,
            )
        except Exception:  # pragma: no cover - defensive boundary around best-effort delivery
            sent = False

        if sent:
            return EmailDeliveryStatus.SENT
        logger.warning("Team invitation email delivery failed for invitation %s", SecurityValidator.sanitize_log_message(invitation_id))
        return EmailDeliveryStatus.FAILED

    async def send_password_reset_email(self, to_email: str, full_name: Optional[str], reset_url: str, expires_minutes: int) -> bool:
        """Send password-reset email containing a one-time reset link.

        Args:
            to_email: Destination email address.
            full_name: Optional display name for salutation.
            reset_url: Password-reset link.
            expires_minutes: Link validity duration.

        Returns:
            bool: True when message is sent successfully.
        """
        display_name = full_name or to_email.split("@", maxsplit=1)[0]
        subject = "Reset your ContextForge password"
        body = self._render_template(
            template_name="password_reset_email.html",
            context={"display_name": display_name, "reset_url": reset_url, "expires_minutes": expires_minutes, "recipient_email": to_email},
            fallback_title="Password reset requested",
            fallback_body=f"Hi {display_name},\n\nUse this link to reset your password: {reset_url}\n\nThe link expires in {expires_minutes} minutes.",
        )
        return await self._send_email(to_email, subject, body)

    async def send_password_reset_confirmation_email(self, to_email: str, full_name: Optional[str]) -> bool:
        """Send post-reset confirmation email.

        Args:
            to_email: Destination email address.
            full_name: Optional display name for salutation.

        Returns:
            bool: True when message is sent successfully.
        """
        display_name = full_name or to_email.split("@", maxsplit=1)[0]
        subject = "Your ContextForge password was changed"
        body = self._render_template(
            template_name="password_reset_confirmation_email.html",
            context={"display_name": display_name, "recipient_email": to_email},
            fallback_title="Password changed",
            fallback_body=f"Hi {display_name},\n\nYour password was changed successfully. If this was not you, contact an administrator immediately.",
        )
        return await self._send_email(to_email, subject, body)

    async def send_account_lockout_email(self, to_email: str, full_name: Optional[str], locked_until_iso: str, reset_url: str) -> bool:
        """Notify the user that login attempts triggered a temporary lockout.

        Args:
            to_email: Destination email address.
            full_name: Optional display name for salutation.
            locked_until_iso: ISO timestamp for lockout expiry.
            reset_url: Forgot-password URL for recovery.

        Returns:
            bool: True when message is sent successfully.
        """
        display_name = full_name or to_email.split("@", maxsplit=1)[0]
        subject = "Your ContextForge account was temporarily locked"
        body = self._render_template(
            template_name="account_lockout_email.html",
            context={"display_name": display_name, "locked_until": locked_until_iso, "reset_url": reset_url, "recipient_email": to_email},
            fallback_title="Account temporarily locked",
            fallback_body=f"Hi {display_name},\n\nYour account is locked until {locked_until_iso} due to repeated failed sign-in attempts.\n\nIf this was not you, reset your password now: {reset_url}",
        )
        return await self._send_email(to_email, subject, body)
