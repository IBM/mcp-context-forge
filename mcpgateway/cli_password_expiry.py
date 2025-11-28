# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cli_password_expiry.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

CLI commands for password expiration management.

This module provides command-line utilities for managing password expiration
notifications and monitoring. Can be run as scheduled tasks.

Examples:
    >>> python -m mcpgateway.cli_password_expiry check-notifications
    >>> python -m mcpgateway.cli_password_expiry send-notifications
    >>> python -m mcpgateway.cli_password_expiry summary
"""

# Standard
import asyncio
import json
import logging
import sys

# Third-Party
import typer

# First-Party
from mcpgateway.db import SessionLocal
from mcpgateway.services.password_notification_service import PasswordNotificationService

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize CLI app
app = typer.Typer(
    name="password-expiry",
    help="Password expiration management commands"
)


@app.command()
def summary(
    notification_days: int = typer.Option(14, help="Days before expiry to consider 'expiring soon'"),
    json_output: bool = typer.Option(False, help="Output in JSON format")
):
    """Show summary of password expiration status across all users."""
    async def _run_summary():
        try:
            with SessionLocal() as db:
                service = PasswordNotificationService(db)
                summary_data = await service.get_expiry_summary(notification_days)
                
                if json_output:
                    typer.echo(json.dumps(summary_data, indent=2))
                else:
                    typer.echo("Password Expiration Summary")
                    typer.echo("=" * 40)
                    typer.echo(f"Total users: {summary_data['total_users']}")
                    typer.echo(f"Active users: {summary_data['active_users']}")
                    typer.echo(f"Users with expired passwords: {summary_data['expired_passwords']}")
                    typer.echo(f"Users with passwords expiring in {notification_days} days: {summary_data['expiring_passwords']}")
                    
                    if summary_data['expired_passwords'] > 0:
                        typer.echo("\nUsers with expired passwords:")
                        for email in summary_data['expired_user_emails']:
                            typer.echo(f"  - {email}")
                            
                    if summary_data['expiring_passwords'] > 0:
                        typer.echo(f"\nUsers with passwords expiring in {notification_days} days:")
                        for email in summary_data['expiring_user_emails']:
                            typer.echo(f"  - {email}")
                
                return summary_data
                
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    return asyncio.run(_run_summary())


@app.command()
def send_notifications(
    notification_days: int = typer.Option(14, help="Days before expiry to send notification"),
    dry_run: bool = typer.Option(False, help="Show what would be done without actually sending notifications")
):
    """Send password expiry notifications to all eligible users."""
    async def _run_notifications():
        try:
            with SessionLocal() as db:
                service = PasswordNotificationService(db)
                
                if dry_run:
                    typer.echo("DRY RUN: Would send notifications to the following users:")
                    summary = await service.get_expiry_summary(notification_days)
                    for email in summary['expiring_user_emails']:
                        typer.echo(f"  - {email}")
                    typer.echo(f"Total notifications that would be sent: {summary['expiring_passwords']}")
                else:
                    typer.echo("Sending password expiry notifications...")
                    notifications_sent = await service.send_expiry_notifications(notification_days)
                    typer.echo(f"Successfully sent {notifications_sent} notifications")
                    
                    if notifications_sent == 0:
                        typer.echo("No users require password expiry notifications at this time.")
                
        except Exception as e:
            logger.error(f"Error sending notifications: {e}")
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    return asyncio.run(_run_notifications())


@app.command()
def check_user(
    email: str = typer.Argument(..., help="Email address of user to check")
):
    """Check password expiration status for a specific user."""
    async def _check_user():
        try:
            with SessionLocal() as db:
                from mcpgateway.services.email_auth_service import EmailAuthService
                auth_service = EmailAuthService(db)
                
                user = await auth_service.get_user_by_email(email)
                if not user:
                    typer.echo(f"User {email} not found", err=True)
                    raise typer.Exit(1)
                
                typer.echo(f"Password status for {email}:")
                typer.echo("=" * 40)
                typer.echo(f"Active: {user.is_active}")
                typer.echo(f"Password created: {user.password_created_at}")
                typer.echo(f"Password expires: {user.password_expires_at}")
                
                if user.password_expires_at:
                    days_until = user.days_until_password_expires()
                    typer.echo(f"Days until expiry: {days_until}")
                    typer.echo(f"Password expired: {user.is_password_expired()}")
                    typer.echo(f"Password expiring soon: {user.is_password_expiring_soon(14)}")
                    typer.echo(f"Notification sent: {user.expiry_notification_sent}")
                else:
                    typer.echo("No password expiration set")
                
        except Exception as e:
            logger.error(f"Error checking user: {e}")
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    return asyncio.run(_check_user())


@app.command()
def reset_notification(
    email: str = typer.Argument(..., help="Email address of user to reset notification flag for")
):
    """Reset the notification flag for a specific user."""
    async def _reset_notification():
        try:
            with SessionLocal() as db:
                service = PasswordNotificationService(db)
                success = await service.reset_notification_flag(email)
                
                if success:
                    typer.echo(f"Successfully reset notification flag for {email}")
                else:
                    typer.echo(f"Failed to reset notification flag for {email}", err=True)
                    raise typer.Exit(1)
                
        except Exception as e:
            logger.error(f"Error resetting notification: {e}")
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    return asyncio.run(_reset_notification())


if __name__ == "__main__":
    app()