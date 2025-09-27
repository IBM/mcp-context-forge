# -*- coding: utf-8 -*-
"""Webhook Notification Plugin for MCP Gateway.

This package provides webhook notification capabilities for the MCP Gateway,
allowing administrators to receive HTTP notifications on various events,
violations, and state changes.
"""

from .webhook_notification import WebhookNotificationPlugin

__all__ = ["WebhookNotificationPlugin"]
