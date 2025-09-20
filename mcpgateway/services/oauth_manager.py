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
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
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

# In-memory storage for OAuth states with expiration (fallback for single-process)
# Format: {state_key: {"state": state, "gateway_id": gateway_id, "expires_at": datetime}}
_oauth_states: Dict[str, Dict[str, Any]] = {}
# Lock for thread-safe state operations
_state_lock = asyncio.Lock()

# State TTL in seconds (5 minutes)
STATE_TTL_SECONDS = 300

# Redis client for distributed state storage (initialized lazily)
_redis_client: Optional[Any] = None
_REDIS_INITIALIZED = False


async def _get_redis_client():
    """Get or create Redis client for distributed state storage.

    Returns:
        Redis client instance or None if unavailable
    """
    global _redis_client, _REDIS_INITIALIZED  # pylint: disable=global-statement

    if _REDIS_INITIALIZED:
        return _redis_client

    settings = get_settings()
    if settings.cache_type == "redis" and settings.redis_url:
        try:
            # Third-Party
            import aioredis  # pylint: disable=import-outside-toplevel

            _redis_client = await aioredis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
            # Test connection
            await _redis_client.ping()
            logger.info("Connected to Redis for OAuth state storage")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis, falling back to in-memory storage: {e}")
            _redis_client = None
    else:
        _redis_client = None

    _REDIS_INITIALIZED = True
    return _redis_client


class OAuthManager:
    """Manages OAuth 2.0 authentication flows.

    Examples:
        >>> manager = OAuthManager(request_timeout=30, max_retries=3)
        >>> manager.request_timeout
        30
        >>> manager.max_retries
        3
        >>> manager.token_storage is None
        True
        >>>
        >>> # Test grant type validation
        >>> grant_type = "client_credentials"
        >>> grant_type in ["client_credentials", "authorization_code"]
        True
        >>> grant_type = "invalid_grant"
        >>> grant_type in ["client_credentials", "authorization_code"]
        False
        >>>
        >>> # Test encrypted secret detection heuristic
        >>> short_secret = "secret123"
        >>> len(short_secret) > 50
        False
        >>> encrypted_secret = "gAAAAABh" + "x" * 60  # Simulated encrypted secret
        >>> len(encrypted_secret) > 50
        True
        >>>
        >>> # Test scope list handling
        >>> scopes = ["read", "write"]
        >>> " ".join(scopes)
        'read write'
        >>> empty_scopes = []
        >>> " ".join(empty_scopes)
        ''
    """

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
        self.settings = get_settings()

    async def get_access_token(self, credentials: Dict[str, Any]) -> str:
        """Get access token based on grant type.

        Args:
            credentials: OAuth configuration containing grant_type and other params

        Returns:
            Access token string

        Raises:
            ValueError: If grant type is unsupported
            OAuthError: If token acquisition fails

        Examples:
            Client credentials flow:
            >>> import asyncio
            >>> class TestMgr(OAuthManager):
            ...     async def _client_credentials_flow(self, credentials):
            ...         return 'tok'
            >>> mgr = TestMgr()
            >>> asyncio.run(mgr.get_access_token({'grant_type': 'client_credentials'}))
            'tok'

            Authorization code fallback to client credentials:
            >>> asyncio.run(mgr.get_access_token({'grant_type': 'authorization_code'}))
            'tok'

            Unsupported grant type raises ValueError:
            >>> def _unsupported():
            ...     try:
            ...         asyncio.run(mgr.get_access_token({'grant_type': 'bad'}))
            ...     except ValueError:
            ...         return True
            >>> _unsupported()
            True
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

    async def initiate_authorization_code_flow(self, gateway_id: str, credentials: Dict[str, Any], app_user_email: str = None) -> Dict[str, str]:
        """Initiate Authorization Code flow and return authorization URL.

        Args:
            gateway_id: ID of the gateway being configured
            credentials: OAuth configuration with client_id, authorization_url, etc.
            app_user_email: MCP Gateway user email to associate with tokens

        Returns:
            Dict containing authorization_url and state
        """

        # Generate state parameter with user context for CSRF protection
        state = self._generate_state(gateway_id, app_user_email)

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
        # First, validate state to prevent replay attacks
        if not await self._validate_authorization_state(gateway_id, state):
            raise OAuthError("Invalid or expired state parameter - possible replay attack")

        # Decode state to extract user context and verify HMAC
        try:
            # Decode base64
            state_with_sig = base64.urlsafe_b64decode(state.encode())

            # Split state and signature (HMAC-SHA256 is 32 bytes)
            state_bytes = state_with_sig[:-32]
            received_signature = state_with_sig[-32:]

            # Verify HMAC signature
            secret_key = self.settings.auth_encryption_secret.encode() if self.settings.auth_encryption_secret else b"default-secret-key"
            expected_signature = hmac.new(secret_key, state_bytes, hashlib.sha256).digest()

            if not hmac.compare_digest(received_signature, expected_signature):
                raise OAuthError("Invalid state signature - possible CSRF attack")

            # Parse state data
            state_json = state_bytes.decode()
            state_data = json.loads(state_json)
            app_user_email = state_data.get("app_user_email")
            state_gateway_id = state_data.get("gateway_id")

            # Validate gateway ID matches
            if state_gateway_id != gateway_id:
                raise OAuthError("State parameter gateway mismatch")
        except Exception as e:
            # Fallback for legacy state format (gateway_id_random)
            logger.warning(f"Failed to decode state JSON, trying legacy format: {e}")
            app_user_email = None

        # Exchange code for tokens
        token_response = await self._exchange_code_for_tokens(credentials, code)

        # Extract user information from token response
        user_id = self._extract_user_id(token_response, credentials)

        # Store tokens if storage service is available
        if self.token_storage:
            if not app_user_email:
                raise OAuthError("User context required for OAuth token storage")

            token_record = await self.token_storage.store_tokens(
                gateway_id=gateway_id,
                user_id=user_id,
                app_user_email=app_user_email,  # User from state
                access_token=token_response["access_token"],
                refresh_token=token_response.get("refresh_token"),
                expires_in=token_response.get("expires_in", 3600),
                scopes=token_response.get("scope", "").split(),
            )

            return {"success": True, "user_id": user_id, "expires_at": token_record.expires_at.isoformat() if token_record.expires_at else None}
        return {"success": True, "user_id": user_id, "expires_at": None}

    async def get_access_token_for_user(self, gateway_id: str, app_user_email: str) -> Optional[str]:
        """Get valid access token for a specific user.

        Args:
            gateway_id: ID of the gateway
            app_user_email: MCP Gateway user email

        Returns:
            Valid access token or None if not available
        """
        if self.token_storage:
            return await self.token_storage.get_user_token(gateway_id, app_user_email)
        return None

    def _generate_state(self, gateway_id: str, app_user_email: str = None) -> str:
        """Generate a unique state parameter with user context for CSRF protection.

        Args:
            gateway_id: ID of the gateway
            app_user_email: MCP Gateway user email (optional but recommended)

        Returns:
            Unique state string with embedded user context and HMAC signature
        """
        # Include user email in state for secure user association
        state_data = {"gateway_id": gateway_id, "app_user_email": app_user_email, "nonce": secrets.token_urlsafe(16), "timestamp": datetime.now(timezone.utc).isoformat()}

        # Encode state as JSON
        state_json = json.dumps(state_data, separators=(",", ":"))
        state_bytes = state_json.encode()

        # Create HMAC signature
        secret_key = self.settings.auth_encryption_secret.encode() if self.settings.auth_encryption_secret else b"default-secret-key"
        signature = hmac.new(secret_key, state_bytes, hashlib.sha256).digest()

        # Combine state and signature, then base64 encode
        state_with_sig = state_bytes + signature
        state_encoded = base64.urlsafe_b64encode(state_with_sig).decode()

        return state_encoded

    async def _store_authorization_state(self, gateway_id: str, state: str) -> None:
        """Store authorization state for validation with TTL.

        Args:
            gateway_id: ID of the gateway
            state: State parameter to store
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS)
        settings = get_settings()

        # Try Redis first for distributed storage
        if settings.cache_type == "redis":
            redis = await _get_redis_client()
            if redis:
                try:
                    state_key = f"oauth:state:{gateway_id}:{state}"
                    state_data = {"state": state, "gateway_id": gateway_id, "expires_at": expires_at.isoformat(), "used": False}
                    # Store in Redis with TTL
                    await redis.setex(state_key, STATE_TTL_SECONDS, json.dumps(state_data))
                    logger.debug(f"Stored OAuth state in Redis for gateway {gateway_id}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to store state in Redis: {e}, falling back")

        # Try database storage for multi-worker deployments
        if settings.cache_type == "database":
            try:
                # First-Party
                from mcpgateway.db import get_db, OAuthState  # pylint: disable=import-outside-toplevel

                db_gen = get_db()
                db = next(db_gen)
                try:
                    # Clean up expired states first
                    db.query(OAuthState).filter(OAuthState.expires_at < datetime.now(timezone.utc)).delete()

                    # Store new state
                    oauth_state = OAuthState(gateway_id=gateway_id, state=state, expires_at=expires_at, used=False)
                    db.add(oauth_state)
                    db.commit()
                    logger.debug(f"Stored OAuth state in database for gateway {gateway_id}")
                    return
                finally:
                    db_gen.close()
            except Exception as e:
                logger.warning(f"Failed to store state in database: {e}, falling back to memory")

        # Fallback to in-memory storage for development
        async with _state_lock:
            # Clean up expired states first
            now = datetime.now(timezone.utc)
            state_key = f"oauth:state:{gateway_id}:{state}"
            state_data = {"state": state, "gateway_id": gateway_id, "expires_at": expires_at.isoformat(), "used": False}
            expired_states = [key for key, data in _oauth_states.items() if datetime.fromisoformat(data["expires_at"]) < now]
            for key in expired_states:
                del _oauth_states[key]
                logger.debug(f"Cleaned up expired state: {key[:20]}...")

            # Store the new state with expiration
            _oauth_states[state_key] = state_data
            logger.debug(f"Stored OAuth state in memory for gateway {gateway_id}")

    async def _validate_authorization_state(self, gateway_id: str, state: str) -> bool:
        """Validate authorization state parameter and mark as used.

        Args:
            gateway_id: ID of the gateway
            state: State parameter to validate

        Returns:
            True if state is valid and not yet used, False otherwise
        """
        settings = get_settings()

        # Try Redis first for distributed storage
        if settings.cache_type == "redis":
            redis = await _get_redis_client()
            if redis:
                try:
                    state_key = f"oauth:state:{gateway_id}:{state}"
                    # Get and delete state atomically (single-use)
                    state_json = await redis.getdel(state_key)
                    if not state_json:
                        logger.warning(f"State not found in Redis for gateway {gateway_id}")
                        return False

                    state_data = json.loads(state_json)

                    # Check if state has expired
                    if datetime.fromisoformat(state_data["expires_at"]) < datetime.now(timezone.utc):
                        logger.warning(f"State has expired for gateway {gateway_id}")
                        return False

                    # Check if state was already used (should not happen with getdel)
                    if state_data.get("used", False):
                        logger.warning(f"State was already used for gateway {gateway_id} - possible replay attack")
                        return False

                    logger.debug(f"Successfully validated OAuth state from Redis for gateway {gateway_id}")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to validate state in Redis: {e}, falling back")

        # Try database storage for multi-worker deployments
        if settings.cache_type == "database":
            try:
                # First-Party
                from mcpgateway.db import get_db, OAuthState  # pylint: disable=import-outside-toplevel

                db_gen = get_db()
                db = next(db_gen)
                try:
                    # Find the state
                    oauth_state = db.query(OAuthState).filter(OAuthState.gateway_id == gateway_id, OAuthState.state == state).first()

                    if not oauth_state:
                        logger.warning(f"State not found in database for gateway {gateway_id}")
                        return False

                    # Check if state has expired
                    if oauth_state.expires_at < datetime.now(timezone.utc):
                        logger.warning(f"State has expired for gateway {gateway_id}")
                        db.delete(oauth_state)
                        db.commit()
                        return False

                    # Check if state was already used
                    if oauth_state.used:
                        logger.warning(f"State has already been used for gateway {gateway_id} - possible replay attack")
                        return False

                    # Mark as used and delete (single-use)
                    db.delete(oauth_state)
                    db.commit()
                    logger.debug(f"Successfully validated OAuth state from database for gateway {gateway_id}")
                    return True
                finally:
                    db_gen.close()
            except Exception as e:
                logger.warning(f"Failed to validate state in database: {e}, falling back to memory")

        # Fallback to in-memory storage for development
        state_key = f"oauth:state:{gateway_id}:{state}"
        async with _state_lock:
            state_data = _oauth_states.get(state_key)

            # Check if state exists
            if not state_data:
                logger.warning(f"State not found in memory for gateway {gateway_id}")
                return False

            # Check if state has expired
            if datetime.fromisoformat(state_data["expires_at"]) < datetime.now(timezone.utc):
                logger.warning(f"State has expired for gateway {gateway_id}")
                del _oauth_states[state_key]  # Clean up expired state
                return False

            # Check if state has already been used (prevent replay)
            if state_data.get("used", False):
                logger.warning(f"State has already been used for gateway {gateway_id} - possible replay attack")
                return False

            # Mark state as used and remove it (single-use)
            del _oauth_states[state_key]
            logger.debug(f"Successfully validated OAuth state from memory for gateway {gateway_id}")
            return True

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

    async def refresh_token(self, refresh_token: str, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh an expired access token using a refresh token.

        Args:
            refresh_token: The refresh token to use
            credentials: OAuth configuration including client_id, client_secret, token_url

        Returns:
            Dict containing new access_token, optional refresh_token, and expires_in

        Raises:
            OAuthError: If token refresh fails
        """
        if not refresh_token:
            raise OAuthError("No refresh token available")

        token_url = credentials.get("token_url")
        if not token_url:
            raise OAuthError("No token URL configured for OAuth provider")

        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")

        if not client_id:
            raise OAuthError("No client_id configured for OAuth provider")

        # Prepare token refresh request
        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }

        # Add client_secret if available (some providers require it)
        if client_secret:
            token_data["client_secret"] = client_secret

        # Attempt token refresh with retries
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(token_url, data=token_data, timeout=aiohttp.ClientTimeout(total=self.request_timeout)) as response:
                        if response.status == 200:
                            token_response = await response.json()

                            # Validate required fields
                            if "access_token" not in token_response:
                                raise OAuthError("No access_token in refresh response")

                            logger.info("Successfully refreshed OAuth token")
                            return token_response

                        error_text = await response.text()
                        # If we get a 400/401, the refresh token is likely invalid
                        if response.status in [400, 401]:
                            raise OAuthError(f"Refresh token invalid or expired: {error_text}")
                        logger.warning(f"Token refresh failed with status {response.status}: {error_text}")

            except aiohttp.ClientError as e:
                logger.warning(f"Token refresh attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise OAuthError(f"Failed to refresh token after {self.max_retries} attempts: {str(e)}")
                await asyncio.sleep(2**attempt)  # Exponential backoff

        raise OAuthError("Failed to refresh token after all retry attempts")

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
    """OAuth-related errors.

    Examples:
        >>> try:
        ...     raise OAuthError("Token acquisition failed")
        ... except OAuthError as e:
        ...     str(e)
        'Token acquisition failed'
        >>> try:
        ...     raise OAuthError("Invalid grant type")
        ... except Exception as e:
        ...     isinstance(e, OAuthError)
        True
    """
