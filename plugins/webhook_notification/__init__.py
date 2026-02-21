# -*- coding: utf-8 -*-
"""Webhook Notification Plugin for ContextForge.

This package provides webhook notification capabilities for ContextForge,
allowing administrators to receive HTTP notifications on various events,
violations, and state changes.
"""

from .webhook_notification import WebhookNotificationPlugin

__all__ = ["WebhookNotificationPlugin"]
