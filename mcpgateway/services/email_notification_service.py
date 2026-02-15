# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/email_notification_service.py
Copyright 2026
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

# Third-Party
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class AuthEmailNotificationService:
    """Send authentication-related email notifications."""

    def __init__(self) -> None:
        """Initialize template rendering for authentication emails."""
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self._jinja = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "xml"]))

    @staticmethod
    def _smtp_password() -> Optional[str]:
        raw = getattr(settings, "smtp_password", None)
        if raw is None:
            return None
        if hasattr(raw, "get_secret_value"):
            return raw.get_secret_value()
        return str(raw)

    @staticmethod
    def _smtp_ready() -> bool:
        return bool(getattr(settings, "smtp_enabled", False) and getattr(settings, "smtp_host", None) and getattr(settings, "smtp_from_email", None))

    def _render_template(self, template_name: str, context: Dict[str, Any], fallback_title: str, fallback_body: str) -> str:
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
        no_tags = re.sub(r"<[^>]+>", " ", value)
        compact = re.sub(r"\s+", " ", no_tags).strip()
        return compact

    async def _send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        if not self._smtp_ready():
            logger.info("SMTP not configured. Skipping email to %s with subject '%s'.", to_email, subject)
            return False
        return await asyncio.to_thread(self._send_email_sync, to_email, subject, html_body)

    def _send_email_sync(self, to_email: str, subject: str, html_body: str) -> bool:
        from_email = str(getattr(settings, "smtp_from_email", "") or "")
        from_name = str(getattr(settings, "smtp_from_name", "MCP Gateway") or "MCP Gateway")
        smtp_user = getattr(settings, "smtp_user", None)
        smtp_password = self._smtp_password()

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((from_name, from_email))
        message["To"] = to_email
        message.set_content(self._html_to_text(html_body))
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
            logger.warning("Failed to send auth notification email to %s: %s", to_email, exc)
            return False

    async def send_password_reset_email(self, to_email: str, full_name: Optional[str], reset_url: str, expires_minutes: int) -> bool:
        """Send password-reset email containing a one-time reset link."""
        display_name = full_name or to_email.split("@")[0]
        subject = "Reset your MCP Gateway password"
        body = self._render_template(
            template_name="password_reset_email.html",
            context={"display_name": display_name, "reset_url": reset_url, "expires_minutes": expires_minutes, "recipient_email": to_email},
            fallback_title="Password reset requested",
            fallback_body=f"Hi {display_name},\n\nUse this link to reset your password: {reset_url}\n\nThe link expires in {expires_minutes} minutes.",
        )
        return await self._send_email(to_email, subject, body)

    async def send_password_reset_confirmation_email(self, to_email: str, full_name: Optional[str]) -> bool:
        """Send post-reset confirmation email."""
        display_name = full_name or to_email.split("@")[0]
        subject = "Your MCP Gateway password was changed"
        body = self._render_template(
            template_name="password_reset_confirmation_email.html",
            context={"display_name": display_name, "recipient_email": to_email},
            fallback_title="Password changed",
            fallback_body=f"Hi {display_name},\n\nYour password was changed successfully. If this was not you, contact an administrator immediately.",
        )
        return await self._send_email(to_email, subject, body)

    async def send_account_lockout_email(self, to_email: str, full_name: Optional[str], locked_until_iso: str, reset_url: str) -> bool:
        """Notify the user that login attempts triggered a temporary lockout."""
        display_name = full_name or to_email.split("@")[0]
        subject = "Your MCP Gateway account was temporarily locked"
        body = self._render_template(
            template_name="account_lockout_email.html",
            context={"display_name": display_name, "locked_until": locked_until_iso, "reset_url": reset_url, "recipient_email": to_email},
            fallback_title="Account temporarily locked",
            fallback_body=f"Hi {display_name},\n\nYour account is locked until {locked_until_iso} due to repeated failed sign-in attempts.\n\nIf this was not you, reset your password now: {reset_url}",
        )
        return await self._send_email(to_email, subject, body)
