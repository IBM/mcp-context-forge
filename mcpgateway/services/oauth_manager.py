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
import logging
import secrets
from typing import Any, Dict, Optional

# Third-Party
import aiohttp
import orjson
from requests_oauthlib import OAuth2Session

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.utils.redis_client import get_redis_client as _get_shared_redis_client

logger = logging.getLogger(__name__)

# In-memory storage for OAuth states with expiration (fallback for single-process)
# Format: {state_key: {"state": state, "gateway_id": gateway_id, "expires_at": datetime}}
_oauth_states: Dict[str, Dict[str, Any]] = {}
# Lock for thread-safe state operations
_state_lock = asyncio.Lock()

# State TTL in seconds (5 minutes)
STATE_TTL_SECONDS = 300

# Redis client for distributed state storage (uses shared factory)
_redis_client: Optional[Any] = None
_REDIS_INITIALIZED = False


async def _get_redis_client():
    """Get shared Redis client for distributed state storage.

    Uses the centralized Redis client factory for consistent configuration.

    Returns:
        Redis client instance or None if unavailable
    """
    global _redis_client, _REDIS_INITIALIZED  # pylint: disable=global-statement

    if _REDIS_INITIALIZED:
        return _redis_client

    settings = get_settings()
    if settings.cache_type == "redis" and settings.redis_url:
        try:
            _redis_client = await _get_shared_redis_client()
            if _redis_client:
                logger.info("OAuth manager connected to shared Redis client")
        except Exception as e:
            logger.warning(f"Failed to get Redis client, falling back to in-memory storage: {e}")
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

    def _generate_pkce_params(self) -> Dict[str, str]:
        """Generate PKCE parameters for OAuth Authorization Code flow (RFC 7636).

        Returns:
            Dict containing code_verifier, code_challenge, and code_challenge_method
        """
        # Generate code_verifier: 43-128 character random string
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")

        # Generate code_challenge: base64url(SHA256(code_verifier))
        code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest()).decode("utf-8").rstrip("=")

        return {"code_verifier": code_verifier, "code_challenge": code_challenge, "code_challenge_method": "S256"}

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
        if grant_type == "password":
            return await self._password_flow(credentials)
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
                encryption = get_encryption_service(settings.auth_encryption_secret)
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

    async def _password_flow(self, credentials: Dict[str, Any]) -> str:
        """Resource Owner Password Credentials flow (RFC 6749 Section 4.3).

        This flow is used when the application can directly handle the user's credentials,
        such as with trusted first-party applications or legacy integrations like Keycloak.

        Args:
            credentials: OAuth configuration with client_id, optional client_secret, token_url, username, password

        Returns:
            Access token string

        Raises:
            OAuthError: If token acquisition fails after all retries
        """
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        token_url = credentials["token_url"]
        username = credentials.get("username")
        password = credentials.get("password")
        scopes = credentials.get("scopes", [])

        if not username or not password:
            raise OAuthError("Username and password are required for password grant type")

        # Decrypt client secret if it's encrypted and present
        if client_secret and len(client_secret) > 50:  # Simple heuristic: encrypted secrets are longer
            try:
                settings = get_settings()
                encryption = get_encryption_service(settings.auth_encryption_secret)
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
            "grant_type": "password",
            "username": username,
            "password": password,
        }

        # Add client_id (required by most providers including Keycloak)
        if client_id:
            token_data["client_id"] = client_id

        # Add client_secret if present (some providers require it, others don't)
        if client_secret:
            token_data["client_secret"] = client_secret

        if scopes:
            token_data["scope"] = " ".join(scopes) if isinstance(scopes, list) else scopes

        # Fetch token with retries
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(token_url, data=token_data, timeout=aiohttp.ClientTimeout(total=self.request_timeout)) as response:
                        response.raise_for_status()

                        # Handle both JSON and form-encoded responses
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

                        logger.info("Successfully obtained access token via password grant")
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
        client_secret = credentials.get("client_secret")  # Optional for public clients (PKCE-only)
        token_url = credentials["token_url"]
        redirect_uri = credentials["redirect_uri"]

        # Decrypt client secret if it's encrypted and present
        if client_secret and len(client_secret) > 50:  # Simple heuristic: encrypted secrets are longer
            try:
                settings = get_settings()
                encryption = get_encryption_service(settings.auth_encryption_secret)
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
        }

        # Only include client_secret if present (public clients don't have secrets)
        if client_secret:
            token_data["client_secret"] = client_secret

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
        """Initiate Authorization Code flow with PKCE and return authorization URL.

        Args:
            gateway_id: ID of the gateway being configured
            credentials: OAuth configuration with client_id, authorization_url, etc.
            app_user_email: MCP Gateway user email to associate with tokens

        Returns:
            Dict containing authorization_url and state
        """

        # Generate PKCE parameters (RFC 7636)
        pkce_params = self._generate_pkce_params()

        # Generate state parameter with user context for CSRF protection
        state = self._generate_state(gateway_id, app_user_email)

        # Store state with code_verifier in session/cache for validation
        if self.token_storage:
            await self._store_authorization_state(gateway_id, state, code_verifier=pkce_params["code_verifier"])

        # Generate authorization URL with PKCE
        auth_url = self._create_authorization_url_with_pkce(credentials, state, pkce_params["code_challenge"], pkce_params["code_challenge_method"])

        logger.info(f"Generated authorization URL with PKCE for gateway {gateway_id}")

        return {"authorization_url": auth_url, "state": state, "gateway_id": gateway_id}

    async def complete_authorization_code_flow(self, gateway_id: str, code: str, state: str, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Complete Authorization Code flow with PKCE and store tokens.

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
        # Validate state and retrieve code_verifier
        state_data = await self._validate_and_retrieve_state(gateway_id, state)
        if not state_data:
            raise OAuthError("Invalid or expired state parameter - possible replay attack")

        code_verifier = state_data.get("code_verifier")

        # Decode state to extract user context and verify HMAC
        try:
            # Decode base64
            state_with_sig = base64.urlsafe_b64decode(state.encode())

            # Split state and signature (HMAC-SHA256 is 32 bytes)
            state_bytes = state_with_sig[:-32]
            received_signature = state_with_sig[-32:]

            # Verify HMAC signature
            secret_key = self.settings.auth_encryption_secret.get_secret_value().encode() if self.settings.auth_encryption_secret else b"default-secret-key"
            expected_signature = hmac.new(secret_key, state_bytes, hashlib.sha256).digest()

            if not hmac.compare_digest(received_signature, expected_signature):
                raise OAuthError("Invalid state signature - possible CSRF attack")

            # Parse state data
            state_json = state_bytes.decode()
            state_payload = orjson.loads(state_json)
            app_user_email = state_payload.get("app_user_email")
            state_gateway_id = state_payload.get("gateway_id")

            # Validate gateway ID matches
            if state_gateway_id != gateway_id:
                raise OAuthError("State parameter gateway mismatch")
        except Exception as e:
            # Fallback for legacy state format (gateway_id_random)
            logger.warning(f"Failed to decode state JSON, trying legacy format: {e}")
            app_user_email = None

        # Exchange code for tokens with PKCE code_verifier
        token_response = await self._exchange_code_for_tokens(credentials, code, code_verifier=code_verifier)

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
                expires_in=token_response.get("expires_in", self.settings.oauth_default_timeout),
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

        # Encode state as JSON (orjson produces compact output by default)
        state_bytes = orjson.dumps(state_data)

        # Create HMAC signature
        secret_key = self.settings.auth_encryption_secret.get_secret_value().encode() if self.settings.auth_encryption_secret else b"default-secret-key"
        signature = hmac.new(secret_key, state_bytes, hashlib.sha256).digest()

        # Combine state and signature, then base64 encode
        state_with_sig = state_bytes + signature
        state_encoded = base64.urlsafe_b64encode(state_with_sig).decode()

        return state_encoded

    async def _store_authorization_state(self, gateway_id: str, state: str, code_verifier: str = None) -> None:
        """Store authorization state for validation with TTL.

        Args:
            gateway_id: ID of the gateway
            state: State parameter to store
            code_verifier: Optional PKCE code verifier (RFC 7636)
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS)
        settings = get_settings()

        # Try Redis first for distributed storage
        if settings.cache_type == "redis":
            redis = await _get_redis_client()
            if redis:
                try:
                    state_key = f"oauth:state:{gateway_id}:{state}"
                    state_data = {"state": state, "gateway_id": gateway_id, "code_verifier": code_verifier, "expires_at": expires_at.isoformat(), "used": False}
                    # Store in Redis with TTL
                    await redis.setex(state_key, STATE_TTL_SECONDS, orjson.dumps(state_data))
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

                    # Store new state with code_verifier
                    oauth_state = OAuthState(gateway_id=gateway_id, state=state, code_verifier=code_verifier, expires_at=expires_at, used=False)
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
            state_data = {"state": state, "gateway_id": gateway_id, "code_verifier": code_verifier, "expires_at": expires_at.isoformat(), "used": False}
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

                    state_data = orjson.loads(state_json)

                    # Parse expires_at as timezone-aware datetime. If the stored value
                    # is naive, assume UTC for compatibility.
                    try:
                        expires_at = datetime.fromisoformat(state_data["expires_at"])
                    except Exception:
                        # Fallback: try parsing without microseconds/offsets
                        expires_at = datetime.strptime(state_data["expires_at"], "%Y-%m-%dT%H:%M:%S")

                    if expires_at.tzinfo is None:
                        # Assume UTC for naive timestamps
                        expires_at = expires_at.replace(tzinfo=timezone.utc)

                    # Check if state has expired
                    if expires_at < datetime.now(timezone.utc):
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
                    # Ensure oauth_state.expires_at is timezone-aware. If naive, assume UTC.
                    expires_at = oauth_state.expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)

                    if expires_at < datetime.now(timezone.utc):
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

            # Parse and normalize expires_at to timezone-aware datetime
            expires_at = datetime.fromisoformat(state_data["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at < datetime.now(timezone.utc):
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

    async def _validate_and_retrieve_state(self, gateway_id: str, state: str) -> Optional[Dict[str, Any]]:
        """Validate state and return full state data including code_verifier.

        Args:
            gateway_id: ID of the gateway
            state: State parameter to validate

        Returns:
            Dict with state data including code_verifier, or None if invalid/expired
        """
        settings = get_settings()

        # Try Redis first
        if settings.cache_type == "redis":
            redis = await _get_redis_client()
            if redis:
                try:
                    state_key = f"oauth:state:{gateway_id}:{state}"
                    state_json = await redis.getdel(state_key)  # Atomic get+delete
                    if not state_json:
                        return None

                    state_data = orjson.loads(state_json)

                    # Check expiration
                    try:
                        expires_at = datetime.fromisoformat(state_data["expires_at"])
                    except Exception:
                        expires_at = datetime.strptime(state_data["expires_at"], "%Y-%m-%dT%H:%M:%S")

                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)

                    if expires_at < datetime.now(timezone.utc):
                        return None

                    return state_data
                except Exception as e:
                    logger.warning(f"Failed to validate state in Redis: {e}, falling back")

        # Try database
        if settings.cache_type == "database":
            try:
                # First-Party
                from mcpgateway.db import get_db, OAuthState  # pylint: disable=import-outside-toplevel

                db_gen = get_db()
                db = next(db_gen)
                try:
                    oauth_state = db.query(OAuthState).filter(OAuthState.gateway_id == gateway_id, OAuthState.state == state).first()

                    if not oauth_state:
                        return None

                    # Check expiration
                    expires_at = oauth_state.expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)

                    if expires_at < datetime.now(timezone.utc):
                        db.delete(oauth_state)
                        db.commit()
                        return None

                    # Check if already used
                    if oauth_state.used:
                        return None

                    # Build state data
                    state_data = {"state": oauth_state.state, "gateway_id": oauth_state.gateway_id, "code_verifier": oauth_state.code_verifier, "expires_at": oauth_state.expires_at.isoformat()}

                    # Mark as used and delete
                    db.delete(oauth_state)
                    db.commit()

                    return state_data
                finally:
                    db_gen.close()
            except Exception as e:
                logger.warning(f"Failed to validate state in database: {e}")

        # Fallback to in-memory
        state_key = f"oauth:state:{gateway_id}:{state}"
        async with _state_lock:
            state_data = _oauth_states.get(state_key)
            if not state_data:
                return None

            # Check expiration
            expires_at = datetime.fromisoformat(state_data["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at < datetime.now(timezone.utc):
                del _oauth_states[state_key]
                return None

            # Remove from memory (single-use)
            del _oauth_states[state_key]
            return state_data

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

    def _create_authorization_url_with_pkce(self, credentials: Dict[str, Any], state: str, code_challenge: str, code_challenge_method: str) -> str:
        """Create authorization URL with PKCE parameters (RFC 7636).

        Args:
            credentials: OAuth configuration
            state: State parameter for CSRF protection
            code_challenge: PKCE code challenge
            code_challenge_method: PKCE method (S256)

        Returns:
            Authorization URL string with PKCE parameters
        """
        # Standard
        from urllib.parse import urlencode  # pylint: disable=import-outside-toplevel

        client_id = credentials["client_id"]
        redirect_uri = credentials["redirect_uri"]
        authorization_url = credentials["authorization_url"]
        scopes = credentials.get("scopes", [])

        # Build authorization parameters
        params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state, "code_challenge": code_challenge, "code_challenge_method": code_challenge_method}

        # Add scopes if present
        if scopes:
            params["scope"] = " ".join(scopes) if isinstance(scopes, list) else scopes

        # Build full URL
        query_string = urlencode(params)
        return f"{authorization_url}?{query_string}"

    async def _exchange_code_for_tokens(self, credentials: Dict[str, Any], code: str, code_verifier: str = None) -> Dict[str, Any]:
        """Exchange authorization code for tokens with PKCE support.

        Args:
            credentials: OAuth configuration
            code: Authorization code from callback
            code_verifier: Optional PKCE code verifier (RFC 7636)

        Returns:
            Token response dictionary

        Raises:
            OAuthError: If token exchange fails
        """
        client_id = credentials["client_id"]
        client_secret = credentials.get("client_secret")  # Optional for public clients (PKCE-only)
        token_url = credentials["token_url"]
        redirect_uri = credentials["redirect_uri"]

        # Decrypt client secret if it's encrypted and present
        if client_secret and len(client_secret) > 50:  # Simple heuristic: encrypted secrets are longer
            try:
                settings = get_settings()
                encryption = get_encryption_service(settings.auth_encryption_secret)
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
        }

        # Only include client_secret if present (public clients don't have secrets)
        if client_secret:
            token_data["client_secret"] = client_secret

        # Add PKCE code_verifier if present (RFC 7636)
        if code_verifier:
            token_data["code_verifier"] = code_verifier

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
