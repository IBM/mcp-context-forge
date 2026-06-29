# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/credential_storage_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Personal Credential Storage Service for ContextForge.

This module handles the storage, retrieval, and management of per-user personal
credentials (API keys, bearer tokens, basic auth) for gateways where OAuth is not
supported or not sufficient.
"""

# Standard
import base64
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import get_settings
from mcpgateway.db import UserGatewayCredential
from mcpgateway.services.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)

# Valid credential types
VALID_CREDENTIAL_TYPES = {"api_key", "bearer_token", "basic_auth"}


class CredentialStorageService:
    """Manages per-user personal credential storage and retrieval for gateways."""

    def __init__(self, db: Session):
        """Initialize the service with a database session and encryption helper."""
        self.db = db
        try:
            settings = get_settings()
            self.encryption = get_encryption_service(settings.auth_encryption_secret)
        except (ImportError, AttributeError):
            logger.warning("Encryption not available for credential storage, using plain text")
            self.encryption = None

    async def store_credential(
        self,
        gateway_id: str,
        app_user_email: str,
        credential_type: str,
        credential_value: str,
        label: Optional[str] = None,
    ) -> UserGatewayCredential:
        """Store or update a personal credential for a gateway-user combination.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email
            credential_type: Type of credential ("api_key", "bearer_token", "basic_auth")
            credential_value: The secret credential value
            label: Optional user-friendly label

        Returns:
            UserGatewayCredential record

        Raises:
            ValueError: If credential_type is invalid
            Exception: If storage fails
        """
        if credential_type not in VALID_CREDENTIAL_TYPES:
            raise ValueError(f"Invalid credential_type '{credential_type}'. Must be one of: {VALID_CREDENTIAL_TYPES}")

        try:
            encrypted_value = credential_value
            if self.encryption:
                encrypted_value = await self.encryption.encrypt_secret_async(credential_value)

            record = self.db.execute(
                select(UserGatewayCredential).where(
                    UserGatewayCredential.gateway_id == gateway_id,
                    UserGatewayCredential.app_user_email == app_user_email,
                )
            ).scalar_one_or_none()

            if record:
                record.credential_type = credential_type
                record.credential_value = encrypted_value
                record.label = label
                logger.info(
                    f"Updated credential for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, "
                    f"user {SecurityValidator.sanitize_log_message(app_user_email)}"
                )
            else:
                record = UserGatewayCredential(
                    gateway_id=gateway_id,
                    app_user_email=app_user_email,
                    credential_type=credential_type,
                    credential_value=encrypted_value,
                    label=label,
                )
                self.db.add(record)
                logger.info(
                    f"Stored new credential for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, "
                    f"user {SecurityValidator.sanitize_log_message(app_user_email)}"
                )

            self.db.commit()
            return record

        except ValueError:
            raise
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to store credential: {str(e)}")
            raise

    async def get_credential(self, gateway_id: str, app_user_email: str) -> Optional[str]:
        """Get a decrypted credential value for a specific user and gateway.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email

        Returns:
            Decrypted credential value or None if not found
        """
        try:
            record = self.db.execute(
                select(UserGatewayCredential).where(
                    UserGatewayCredential.gateway_id == gateway_id,
                    UserGatewayCredential.app_user_email == app_user_email,
                )
            ).scalar_one_or_none()

            if not record:
                return None

            if self.encryption:
                return await self.encryption.decrypt_secret_async(record.credential_value)
            return record.credential_value

        except Exception as e:
            logger.error(f"Failed to retrieve credential: {str(e)}")
            return None

    async def get_credential_record(self, gateway_id: str, app_user_email: str) -> Optional[UserGatewayCredential]:
        """Get the full credential record (without decrypting the value).

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email

        Returns:
            UserGatewayCredential record or None
        """
        try:
            return self.db.execute(
                select(UserGatewayCredential).where(
                    UserGatewayCredential.gateway_id == gateway_id,
                    UserGatewayCredential.app_user_email == app_user_email,
                )
            ).scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get credential record: {str(e)}")
            return None

    async def get_credential_info(self, gateway_id: str, app_user_email: str) -> Optional[Dict[str, Any]]:
        """Get credential metadata without the secret value.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email

        Returns:
            Dict with credential info or None
        """
        record = await self.get_credential_record(gateway_id, app_user_email)
        if not record:
            return None

        return {
            "gateway_id": record.gateway_id,
            "app_user_email": record.app_user_email,
            "credential_type": record.credential_type,
            "label": record.label,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    async def revoke_credential(self, gateway_id: str, app_user_email: str) -> bool:
        """Delete stored credential for a gateway-user combination.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email

        Returns:
            True if a credential was deleted, False if none existed
        """
        try:
            result = self.db.execute(
                delete(UserGatewayCredential).where(
                    UserGatewayCredential.gateway_id == gateway_id,
                    UserGatewayCredential.app_user_email == app_user_email,
                )
            )
            self.db.commit()
            deleted = result.rowcount > 0
            if deleted:
                logger.info(
                    f"Revoked credential for gateway {SecurityValidator.sanitize_log_message(gateway_id)}, "
                    f"user {SecurityValidator.sanitize_log_message(app_user_email)}"
                )
            return deleted
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to revoke credential: {str(e)}")
            return False

    async def list_user_credentials(self, app_user_email: str) -> List[Dict[str, Any]]:
        """List all gateway credentials for a user (metadata only, no secrets).

        Args:
            app_user_email: ContextForge user email

        Returns:
            List of credential info dicts
        """
        try:
            records = (
                self.db.execute(
                    select(UserGatewayCredential).where(
                        UserGatewayCredential.app_user_email == app_user_email,
                    )
                )
                .scalars()
                .all()
            )

            return [
                {
                    "gateway_id": r.gateway_id,
                    "credential_type": r.credential_type,
                    "label": r.label,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in records
            ]
        except Exception as e:
            logger.error(f"Failed to list credentials: {str(e)}")
            return []

    @staticmethod
    def build_auth_headers(credential_type: str, credential_value: str, gateway_auth_type: Optional[str] = None) -> Dict[str, str]:
        """Build HTTP Authorization headers from a credential.

        Args:
            credential_type: Type of credential ("api_key", "bearer_token", "basic_auth")
            credential_value: Decrypted credential value
            gateway_auth_type: Gateway's auth_type for context-aware header construction

        Returns:
            Dict of HTTP headers to use for authentication
        """
        if credential_type == "bearer_token":
            return {"Authorization": f"Bearer {credential_value}"}
        elif credential_type == "api_key":
            # API key sent as Basic auth (common pattern: api_key as username, 'X' as password)
            encoded = base64.b64encode(f"{credential_value}:X".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        elif credential_type == "basic_auth":
            # credential_value is "username:password"
            encoded = base64.b64encode(credential_value.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        else:
            logger.warning(f"Unknown credential type: {credential_type}")
            return {}
