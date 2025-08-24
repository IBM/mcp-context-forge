# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/oauth_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OAuth 2.0 Manager for MCP Gateway.

This module handles OAuth 2.0 authentication flows including:
- Client Credentials (Machine-to-Machine)
- Authorization Code (User Delegation)
"""

# Standard
import asyncio
import logging
import secrets
from typing import Any, Dict, Optional

# Third-Party
import aiohttp
from requests_oauthlib import OAuth2Session

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.utils.oauth_encryption import get_oauth_encryption

logger = logging.getLogger(__name__)


class OAuthManager:
    """Manages OAuth 2.0 authentication flows."""

    def __init__(self, request_timeout: int = 30, max_retries: int = 3, token_storage: Optional[Any] = None):
        """Initialize OAuth Manager.

        Args:
            request_timeout: Timeout for OAuth requests in seconds
            max_retries: Maximum number of retry attempts for token requests
            token_storage: Optional TokenStorageService for storing tokens
        """
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.token_storage = token_storage

    async def get_access_token(self, credentials: Dict[str, Any]) -> str:
        """Get access token based on grant type.

        Args:
            credentials: OAuth configuration containing grant_type and other params

        Returns:
            Access token string

        Raises:
            ValueError: If grant type is unsupported
            OAuthError: If token acquisition fails
        """
        grant_type = credentials.get("grant_type")
        logger.debug(f"Getting access token for grant type: {grant_type}")

        if grant_type == "client_credentials":
            return await self._client_credentials_flow(credentials)
        if grant_type == "authorization_code":
            # For authorization code flow in gateway initialization, we need to handle this differently
            # Since this is called during gateway setup, we'll try to use client credentials as fallback
            # or provide a more helpful error message
            logger.warning("Authorization code flow requires user interaction. " + "For gateway initialization, consider using 'client_credentials' grant type instead.")
            # Try to use client credentials flow if possible (some OAuth providers support this)
            try:
                return await self._client_credentials_flow(credentials)
            except Exception as e:
                raise OAuthError(
                    f"Authorization code flow cannot be used for automatic gateway initialization. "
                    f"Please use 'client_credentials' grant type or complete the OAuth flow manually first. "
                    f"Error: {str(e)}"
                )
        else:
            raise ValueError(f"Unsupported grant type: {grant_type}")

    async def _client_credentials_flow(self, credentials: Dict[str, Any]) -> str:
        """Machine-to-machine authentication using client credentials.

        Args:
            credentials: OAuth configuration with client_id, client_secret, token_url

        Returns:
            Access token string

        Raises:
            OAuthError: If token acquisition fails after all retries
        """
        client_id = credentials["client_id"]
        client_secret = credentials["client_secret"]
        token_url = credentials["token_url"]
        scopes = credentials.get("scopes", [])

        # Decrypt client secret if it's encrypted
        if len(client_secret) > 50:  # Simple heuristic: encrypted secrets are longer
            try:
                settings = get_settings()
                encryption = get_oauth_encryption(settings.auth_encryption_secret)
                decrypted_secret = encryption.decrypt_secret(client_secret)
                if decrypted_secret:
                    client_secret = decrypted_secret
                    logger.debug("Successfully decrypted client secret")
                else:
                    logger.warning("Failed to decrypt client secret, using encrypted version")
            except Exception as e:
                logger.warning(f"Failed to decrypt client secret: {e}, using encrypted version")

        # Prepare token request data
        token_data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }

        if scopes:
            token_data["scope"] = " ".join(scopes) if isinstance(scopes, list) else scopes

        # Fetch token with retries
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(token_url, data=token_data, timeout=aiohttp.ClientTimeout(total=self.request_timeout)) as response:
                        response.raise_for_status()

                        # GitHub returns form-encoded responses, not JSON
                        content_type = response.headers.get("content-type", "")
                        if "application/x-www-form-urlencoded" in content_type:
                            # Parse form-encoded response
                            text_response = await response.text()
                            token_response = {}
                            for pair in text_response.split("&"):
                                if "=" in pair:
                                    key, value = pair.split("=", 1)
                                    token_response[key] = value
                        else:
                            # Try JSON response
                            try:
                                token_response = await response.json()
                            except Exception as e:
                                logger.warning(f"Failed to parse JSON response: {e}")
                                # Fallback to text parsing
                                text_response = await response.text()
                                token_response = {"raw_response": text_response}

                        if "access_token" not in token_response:
                            raise OAuthError(f"No access_token in response: {token_response}")

                        logger.info("""Successfully obtained access token via client credentials""")
                        return token_response["access_token"]

            except aiohttp.ClientError as e:
                logger.warning(f"Token request attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise OAuthError(f"Failed to obtain access token after {self.max_retries} attempts: {str(e)}")
                await asyncio.sleep(2**attempt)  # Exponential backoff

        # This should never be reached due to the exception above, but needed for type safety
        raise OAuthError("Failed to obtain access token after all retry attempts")

    async def get_authorization_url(self, credentials: Dict[str, Any]) -> Dict[str, str]:
        """Get authorization URL for user delegation flow.

        Args:
            credentials: OAuth configuration with client_id, authorization_url, etc.

        Returns:
            Dict containing authorization_url and state
        """
        client_id = credentials["client_id"]
        redirect_uri = credentials["redirect_uri"]
        authorization_url = credentials["authorization_url"]
        scopes = credentials.get("scopes", [])

        # Create OAuth2 session
        oauth = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scopes)

        # Generate authorization URL with state for CSRF protection
        auth_url, state = oauth.authorization_url(authorization_url)

        logger.info(f"Generated authorization URL for client {client_id}")

        return {"authorization_url": auth_url, "state": state}

    async def exchange_code_for_token(self, credentials: Dict[str, Any], code: str, state: str) -> str:  # pylint: disable=unused-argument
        """Exchange authorization code for access token.

        Args:
            credentials: OAuth configuration
            code: Authorization code from callback
            state: State parameter for CSRF validation

        Returns:
            Access token string

        Raises:
            OAuthError: If token exchange fails
        """
        client_id = credentials["client_id"]
        client_secret = credentials["client_secret"]
        token_url = credentials["token_url"]
        redirect_uri = credentials["redirect_uri"]

        # Decrypt client secret if it's encrypted
        if len(client_secret) > 50:  # Simple heuristic: encrypted secrets are longer
            try:
                settings = get_settings()
                encryption = get_oauth_encryption(settings.auth_encryption_secret)
                decrypted_secret = encryption.decrypt_secret(client_secret)
                if decrypted_secret:
                    client_secret = decrypted_secret
                    logger.debug("Successfully decrypted client secret")
                else:
                    logger.warning("Failed to decrypt client secret, using encrypted version")
            except Exception as e:
                logger.warning(f"Failed to decrypt client secret: {e}, using encrypted version")

        # Prepare token exchange data
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }

        # Exchange code for token with retries
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(token_url, data=token_data, timeout=aiohttp.ClientTimeout(total=self.request_timeout)) as response:
                        response.raise_for_status()

                        # GitHub returns form-encoded responses, not JSON
                        content_type = response.headers.get("content-type", "")
                        if "application/x-www-form-urlencoded" in content_type:
                            # Parse form-encoded response
                            text_response = await response.text()
                            token_response = {}
                            for pair in text_response.split("&"):
                                if "=" in pair:
                                    key, value = pair.split("=", 1)
                                    token_response[key] = value
                        else:
                            # Try JSON response
                            try:
                                token_response = await response.json()
                            except Exception as e:
                                logger.warning(f"Failed to parse JSON response: {e}")
                                # Fallback to text parsing
                                text_response = await response.text()
                                token_response = {"raw_response": text_response}

                        if "access_token" not in token_response:
                            raise OAuthError(f"No access_token in response: {token_response}")

                        logger.info("""Successfully exchanged authorization code for access token""")
                        return token_response["access_token"]

            except aiohttp.ClientError as e:
                logger.warning(f"Token exchange attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise OAuthError(f"Failed to exchange code for token after {self.max_retries} attempts: {str(e)}")
                await asyncio.sleep(2**attempt)  # Exponential backoff

        # This should never be reached due to the exception above, but needed for type safety
        raise OAuthError("Failed to exchange code for token after all retry attempts")

    async def initiate_authorization_code_flow(self, gateway_id: str, credentials: Dict[str, Any]) -> Dict[str, str]:
        """Initiate Authorization Code flow and return authorization URL.

        Args:
            gateway_id: ID of the gateway being configured
            credentials: OAuth configuration with client_id, authorization_url, etc.

        Returns:
            Dict containing authorization_url and state
        """

        # Generate state parameter for CSRF protection
        state = self._generate_state(gateway_id)

        # Store state in session/cache for validation
        if self.token_storage:
            await self._store_authorization_state(gateway_id, state)

        # Generate authorization URL
        auth_url, _ = self._create_authorization_url(credentials, state)

        logger.info(f"Generated authorization URL for gateway {gateway_id}")

        return {"authorization_url": auth_url, "state": state, "gateway_id": gateway_id}

    async def complete_authorization_code_flow(self, gateway_id: str, code: str, state: str, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Complete Authorization Code flow and store tokens.

        Args:
            gateway_id: ID of the gateway
            code: Authorization code from callback
            state: State parameter for CSRF validation
            credentials: OAuth configuration

        Returns:
            Dict containing success status, user_id, and expiration info

        Raises:
            OAuthError: If state validation fails or token exchange fails
        """
        # Validate state parameter
        if self.token_storage and not await self._validate_authorization_state(gateway_id, state):
            raise OAuthError("Invalid state parameter")

        # Exchange code for tokens
        token_response = await self._exchange_code_for_tokens(credentials, code)

        # Extract user information from token response
        user_id = self._extract_user_id(token_response, credentials)

        # Store tokens if storage service is available
        if self.token_storage:
            token_record = await self.token_storage.store_tokens(
                gateway_id=gateway_id,
                user_id=user_id,
                access_token=token_response["access_token"],
                refresh_token=token_response.get("refresh_token"),
                expires_in=token_response.get("expires_in", 3600),
                scopes=token_response.get("scope", "").split(),
            )

            return {"success": True, "user_id": user_id, "expires_at": token_record.expires_at.isoformat() if token_record.expires_at else None}
        return {"success": True, "user_id": user_id, "expires_at": None}

    async def get_access_token_for_user(self, gateway_id: str, user_id: str) -> Optional[str]:
        """Get valid access token for a specific user.

        Args:
            gateway_id: ID of the gateway
            user_id: OAuth provider user ID

        Returns:
            Valid access token or None if not available
        """
        if self.token_storage:
            return await self.token_storage.get_valid_token(gateway_id, user_id)
        return None

    def _generate_state(self, gateway_id: str) -> str:
        """Generate a unique state parameter for CSRF protection.

        Args:
            gateway_id: ID of the gateway

        Returns:
            Unique state string
        """
        return f"{gateway_id}_{secrets.token_urlsafe(32)}"

    async def _store_authorization_state(self, gateway_id: str, state: str) -> None:  # pylint: disable=unused-argument
        """Store authorization state for validation.

        Args:
            gateway_id: ID of the gateway
            state: State parameter to store
        """
        # This is a placeholder implementation
        # In a real implementation, you would store the state in a cache or database
        # with an expiration time for security
        logger.debug(f"Stored authorization state for gateway {gateway_id}")

    async def _validate_authorization_state(self, gateway_id: str, state: str) -> bool:  # pylint: disable=unused-argument
        """Validate authorization state parameter.

        Args:
            gateway_id: ID of the gateway
            state: State parameter to validate

        Returns:
            True if state is valid
        """
        # This is a placeholder implementation
        # In a real implementation, you would retrieve and validate the stored state
        logger.debug(f"Validating authorization state for gateway {gateway_id}")
        return True  # Placeholder: always return True for now

    def _create_authorization_url(self, credentials: Dict[str, Any], state: str) -> tuple[str, str]:
        """Create authorization URL with state parameter.

        Args:
            credentials: OAuth configuration
            state: State parameter for CSRF protection

        Returns:
            Tuple of (authorization_url, state)
        """
        client_id = credentials["client_id"]
        redirect_uri = credentials["redirect_uri"]
        authorization_url = credentials["authorization_url"]
        scopes = credentials.get("scopes", [])

        # Create OAuth2 session
        oauth = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scopes)

        # Generate authorization URL with state for CSRF protection
        auth_url, state = oauth.authorization_url(authorization_url, state=state)

        return auth_url, state

    async def _exchange_code_for_tokens(self, credentials: Dict[str, Any], code: str) -> Dict[str, Any]:
        """Exchange authorization code for tokens.

        Args:
            credentials: OAuth configuration
            code: Authorization code from callback

        Returns:
            Token response dictionary

        Raises:
            OAuthError: If token exchange fails
        """
        client_id = credentials["client_id"]
        client_secret = credentials["client_secret"]
        token_url = credentials["token_url"]
        redirect_uri = credentials["redirect_uri"]

        # Decrypt client secret if it's encrypted
        if len(client_secret) > 50:  # Simple heuristic: encrypted secrets are longer
            try:
                settings = get_settings()
                encryption = get_oauth_encryption(settings.auth_encryption_secret)
                decrypted_secret = encryption.decrypt_secret(client_secret)
                if decrypted_secret:
                    client_secret = decrypted_secret
                    logger.debug("Successfully decrypted client secret")
                else:
                    logger.warning("Failed to decrypt client secret, using encrypted version")
            except Exception as e:
                logger.warning(f"Failed to decrypt client secret: {e}, using encrypted version")

        # Prepare token exchange data
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }

        # Exchange code for token with retries
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(token_url, data=token_data, timeout=aiohttp.ClientTimeout(total=self.request_timeout)) as response:
                        response.raise_for_status()

                        # GitHub returns form-encoded responses, not JSON
                        content_type = response.headers.get("content-type", "")
                        if "application/x-www-form-urlencoded" in content_type:
                            # Parse form-encoded response
                            text_response = await response.text()
                            token_response = {}
                            for pair in text_response.split("&"):
                                if "=" in pair:
                                    key, value = pair.split("=", 1)
                                    token_response[key] = value
                        else:
                            # Try JSON response
                            try:
                                token_response = await response.json()
                            except Exception as e:
                                logger.warning(f"Failed to parse JSON response: {e}")
                                # Fallback to text parsing
                                text_response = await response.text()
                                token_response = {"raw_response": text_response}

                        if "access_token" not in token_response:
                            raise OAuthError(f"No access_token in response: {token_response}")

                        logger.info("""Successfully exchanged authorization code for tokens""")
                        return token_response

            except aiohttp.ClientError as e:
                logger.warning(f"Token exchange attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise OAuthError(f"Failed to exchange code for token after {self.max_retries} attempts: {str(e)}")
                await asyncio.sleep(2**attempt)  # Exponential backoff

        # This should never be reached due to the exception above, but needed for type safety
        raise OAuthError("Failed to exchange code for token after all retry attempts")

    def _extract_user_id(self, token_response: Dict[str, Any], credentials: Dict[str, Any]) -> str:
        """Extract user ID from token response.

        Args:
            token_response: Response from token exchange
            credentials: OAuth configuration

        Returns:
            User ID string
        """
        # Try to extract user ID from various common fields in token response
        # Different OAuth providers use different field names

        # Check for 'sub' (subject) - JWT standard
        if "sub" in token_response:
            return token_response["sub"]

        # Check for 'user_id' - common in some OAuth responses
        if "user_id" in token_response:
            return token_response["user_id"]

        # Check for 'id' - also common
        if "id" in token_response:
            return token_response["id"]

        # Fallback to client_id if no user info is available
        if credentials.get("client_id"):
            return credentials["client_id"]

        # Final fallback
        return "unknown_user"


class OAuthError(Exception):
    """OAuth-related errors."""
