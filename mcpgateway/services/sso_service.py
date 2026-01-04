# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/sso_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Single Sign-On (SSO) authentication service for OAuth2 and OIDC providers.
Handles provider management, OAuth flows, and user authentication.
"""

# Future
from __future__ import annotations

# Standard
import base64
from datetime import timedelta
import hashlib
import logging
import secrets
import string
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

# Third-Party
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import PendingUserApproval, SSOAuthSession, SSOProvider, utc_now
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.utils.create_jwt_token import create_jwt_token

# Logger
logger = logging.getLogger(__name__)


class SSOService:
    """Service for managing SSO authentication flows and providers.

    Handles OAuth2/OIDC authentication flows, provider configuration,
    and integration with the local user system.

    Examples:
        Basic construction and helper checks:
        >>> from unittest.mock import Mock
        >>> service = SSOService(Mock())
        >>> isinstance(service, SSOService)
        True
        >>> callable(service.list_enabled_providers)
        True
    """

    def __init__(self, db: Session):
        """Initialize SSO service with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.auth_service = EmailAuthService(db)
        self._encryption = get_encryption_service(settings.auth_encryption_secret)

    def _encrypt_secret(self, secret: str) -> str:
        """Encrypt a client secret for secure storage.

        Args:
            secret: Plain text client secret

        Returns:
            Encrypted secret string
        """
        return self._encryption.encrypt_secret(secret)

    def _decrypt_secret(self, encrypted_secret: str) -> Optional[str]:
        """Decrypt a client secret for use.

        Args:
            encrypted_secret: Encrypted secret string

        Returns:
            Plain text client secret
        """
        decrypted: str | None = self._encryption.decrypt_secret(encrypted_secret)
        if decrypted:
            return decrypted

        return None

    def list_enabled_providers(self) -> List[SSOProvider]:
        """Get list of enabled SSO providers.

        Returns:
            List of enabled SSO providers

        Examples:
            Returns empty list when DB has no providers:
            >>> from unittest.mock import MagicMock
            >>> service = SSOService(MagicMock())
            >>> service.db.execute.return_value.scalars.return_value.all.return_value = []
            >>> service.list_enabled_providers()
            []
        """
        stmt = select(SSOProvider).where(SSOProvider.is_enabled.is_(True))
        result = self.db.execute(stmt)
        return list(result.scalars().all())

    def get_provider(self, provider_id: str) -> Optional[SSOProvider]:
        """Get SSO provider by ID.

        Args:
            provider_id: Provider identifier (e.g., 'github', 'google')

        Returns:
            SSO provider or None if not found

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = SSOService(MagicMock())
            >>> service.db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service.get_provider('x') is None
            True
        """
        stmt = select(SSOProvider).where(SSOProvider.id == provider_id)
        result = self.db.execute(stmt)
        return result.scalar_one_or_none()

    def get_provider_by_name(self, provider_name: str) -> Optional[SSOProvider]:
        """Get SSO provider by name.

        Args:
            provider_name: Provider name (e.g., 'github', 'google')

        Returns:
            SSO provider or None if not found

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = SSOService(MagicMock())
            >>> service.db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service.get_provider_by_name('github') is None
            True
        """
        stmt = select(SSOProvider).where(SSOProvider.name == provider_name)
        result = self.db.execute(stmt)
        return result.scalar_one_or_none()

    def create_provider(self, provider_data: Dict[str, Any]) -> SSOProvider:
        """Create new SSO provider configuration.

        Args:
            provider_data: Provider configuration data

        Returns:
            Created SSO provider

        Examples:
            >>> from unittest.mock import MagicMock
            >>> service = SSOService(MagicMock())
            >>> service._encrypt_secret = lambda s: 'ENC(' + s + ')'
            >>> data = {
            ...     'id': 'github', 'name': 'github', 'display_name': 'GitHub', 'provider_type': 'oauth2',
            ...     'client_id': 'cid', 'client_secret': 'sec',
            ...     'authorization_url': 'https://example/auth', 'token_url': 'https://example/token',
            ...     'userinfo_url': 'https://example/user', 'scope': 'user:email'
            ... }
            >>> provider = service.create_provider(data)
            >>> hasattr(provider, 'id') and provider.id == 'github'
            True
            >>> provider.client_secret_encrypted.startswith('ENC(')
            True
        """
        # Encrypt client secret
        client_secret = provider_data.pop("client_secret")
        provider_data["client_secret_encrypted"] = self._encrypt_secret(client_secret)

        provider = SSOProvider(**provider_data)
        self.db.add(provider)
        self.db.commit()
        self.db.refresh(provider)
        return provider

    def update_provider(self, provider_id: str, provider_data: Dict[str, Any]) -> Optional[SSOProvider]:
        """Update existing SSO provider configuration.

        Args:
            provider_id: Provider identifier
            provider_data: Updated provider data

        Returns:
            Updated SSO provider or None if not found

        Examples:
            >>> from types import SimpleNamespace
            >>> from unittest.mock import MagicMock
            >>> svc = SSOService(MagicMock())
            >>> # Existing provider object
            >>> existing = SimpleNamespace(id='github', name='github', client_id='old', client_secret_encrypted='X', is_enabled=True)
            >>> svc.get_provider = lambda _id: existing
            >>> svc._encrypt_secret = lambda s: 'ENC-' + s
            >>> svc.db.commit = lambda: None
            >>> svc.db.refresh = lambda obj: None
            >>> updated = svc.update_provider('github', {'client_id': 'new', 'client_secret': 'sec'})
            >>> updated.client_id
            'new'
            >>> updated.client_secret_encrypted
            'ENC-sec'
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return None

        # Handle client secret encryption if provided
        if "client_secret" in provider_data:
            client_secret = provider_data.pop("client_secret")
            provider_data["client_secret_encrypted"] = self._encrypt_secret(client_secret)

        for key, value in provider_data.items():
            if hasattr(provider, key):
                setattr(provider, key, value)

        provider.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(provider)
        return provider

    def delete_provider(self, provider_id: str) -> bool:
        """Delete SSO provider configuration.

        Args:
            provider_id: Provider identifier

        Returns:
            True if deleted, False if not found

        Examples:
            >>> from types import SimpleNamespace
            >>> from unittest.mock import MagicMock
            >>> svc = SSOService(MagicMock())
            >>> svc.db.delete = lambda obj: None
            >>> svc.db.commit = lambda: None
            >>> svc.get_provider = lambda _id: SimpleNamespace(id='github')
            >>> svc.delete_provider('github')
            True
            >>> svc.get_provider = lambda _id: None
            >>> svc.delete_provider('missing')
            False
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return False

        self.db.delete(provider)
        self.db.commit()
        return True

    def generate_pkce_challenge(self) -> Tuple[str, str]:
        """Generate PKCE code verifier and challenge for OAuth 2.1.

        Returns:
            Tuple of (code_verifier, code_challenge)

        Examples:
            Generate verifier and challenge:
            >>> from unittest.mock import Mock
            >>> service = SSOService(Mock())
            >>> verifier, challenge = service.generate_pkce_challenge()
            >>> isinstance(verifier, str) and isinstance(challenge, str)
            True
            >>> len(verifier) >= 43
            True
            >>> len(challenge) >= 43
            True
        """
        # Generate cryptographically random code verifier
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")

        # Generate code challenge using SHA256
        code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest()).decode("utf-8").rstrip("=")

        return code_verifier, code_challenge

    def get_authorization_url(self, provider_id: str, redirect_uri: str, scopes: Optional[List[str]] = None) -> Optional[str]:
        """Generate OAuth authorization URL for provider.

        Args:
            provider_id: Provider identifier
            redirect_uri: Callback URI after authorization
            scopes: Optional custom scopes (uses provider default if None)

        Returns:
            Authorization URL or None if provider not found

        Examples:
            >>> from types import SimpleNamespace
            >>> from unittest.mock import MagicMock
            >>> service = SSOService(MagicMock())
            >>> provider = SimpleNamespace(id='github', is_enabled=True, provider_type='oauth2', client_id='cid', authorization_url='https://example/auth', scope='user:email')
            >>> service.get_provider = lambda _pid: provider
            >>> service.db.add = lambda x: None
            >>> service.db.commit = lambda: None
            >>> url = service.get_authorization_url('github', 'https://app/callback', ['email'])
            >>> isinstance(url, str) and 'client_id=cid' in url and 'state=' in url
            True

            Missing provider returns None:
            >>> service.get_provider = lambda _pid: None
            >>> service.get_authorization_url('missing', 'https://app/callback') is None
            True
        """
        provider = self.get_provider(provider_id)
        if not provider or not provider.is_enabled:
            return None

        # Generate PKCE parameters
        code_verifier, code_challenge = self.generate_pkce_challenge()

        # Generate CSRF state
        state = secrets.token_urlsafe(32)

        # Generate OIDC nonce if applicable
        nonce = secrets.token_urlsafe(16) if provider.provider_type == "oidc" else None

        # Create auth session
        auth_session = SSOAuthSession(provider_id=provider_id, state=state, code_verifier=code_verifier, nonce=nonce, redirect_uri=redirect_uri)
        self.db.add(auth_session)
        self.db.commit()

        # Build authorization URL
        params = {
            "client_id": provider.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(scopes) if scopes else provider.scope,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        if nonce:
            params["nonce"] = nonce

        return f"{provider.authorization_url}?{urllib.parse.urlencode(params)}"

    async def handle_oauth_callback(self, provider_id: str, code: str, state: str) -> Optional[Dict[str, Any]]:
        """Handle OAuth callback and exchange code for tokens.

        Args:
            provider_id: Provider identifier
            code: Authorization code from callback
            state: CSRF state parameter

        Returns:
            User info dict or None if authentication failed

        Examples:
            Happy-path with patched exchanges and user info:
            >>> import asyncio
            >>> from types import SimpleNamespace
            >>> from unittest.mock import MagicMock
            >>> svc = SSOService(MagicMock())
            >>> # Mock DB auth session lookup
            >>> provider = SimpleNamespace(id='github', is_enabled=True, provider_type='oauth2')
            >>> auth_session = SimpleNamespace(provider_id='github', state='st', provider=provider, is_expired=False)
            >>> svc.db.execute.return_value.scalar_one_or_none.return_value = auth_session
            >>> # Patch token exchange and user info retrieval
            >>> async def _ex(p, sess, c):
            ...     return {'access_token': 'tok'}
            >>> async def _ui(p, access):
            ...     return {'email': 'user@example.com'}
            >>> svc._exchange_code_for_tokens = _ex
            >>> svc._get_user_info = _ui
            >>> svc.db.delete = lambda obj: None
            >>> svc.db.commit = lambda: None
            >>> out = asyncio.run(svc.handle_oauth_callback('github', 'code', 'st'))
            >>> out['email']
            'user@example.com'

            Early return cases:
            >>> # No session
            >>> svc2 = SSOService(MagicMock())
            >>> svc2.db.execute.return_value.scalar_one_or_none.return_value = None
            >>> asyncio.run(svc2.handle_oauth_callback('github', 'c', 's')) is None
            True
            >>> # Expired session
            >>> expired = SimpleNamespace(provider_id='github', state='st', provider=SimpleNamespace(is_enabled=True), is_expired=True)
            >>> svc3 = SSOService(MagicMock())
            >>> svc3.db.execute.return_value.scalar_one_or_none.return_value = expired
            >>> asyncio.run(svc3.handle_oauth_callback('github', 'c', 'st')) is None
            True
            >>> # Disabled provider
            >>> disabled = SimpleNamespace(provider_id='github', state='st', provider=SimpleNamespace(is_enabled=False), is_expired=False)
            >>> svc4 = SSOService(MagicMock())
            >>> svc4.db.execute.return_value.scalar_one_or_none.return_value = disabled
            >>> asyncio.run(svc4.handle_oauth_callback('github', 'c', 'st')) is None
            True
        """
        # Validate auth session
        stmt = select(SSOAuthSession).where(SSOAuthSession.state == state, SSOAuthSession.provider_id == provider_id)
        auth_session = self.db.execute(stmt).scalar_one_or_none()

        if not auth_session or auth_session.is_expired:
            return None

        provider = auth_session.provider
        if not provider or not provider.is_enabled:
            return None

        try:
            # Exchange authorization code for tokens
            logger.info(f"Starting token exchange for provider {provider_id}")
            token_data = await self._exchange_code_for_tokens(provider, auth_session, code)
            if not token_data:
                logger.error(f"Failed to exchange code for tokens for provider {provider_id}")
                return None
            logger.info(f"Token exchange successful for provider {provider_id}")

            # Get user info from provider
            user_info = await self._get_user_info(provider, token_data["access_token"])
            if not user_info:
                logger.error(f"Failed to get user info for provider {provider_id}")
                return None

            # Clean up auth session
            self.db.delete(auth_session)
            self.db.commit()

            return user_info

        except Exception as e:
            # Clean up auth session on error
            logger.error(f"OAuth callback failed for provider {provider_id}: {type(e).__name__}: {str(e)}")
            logger.exception("Full traceback for OAuth callback failure:")
            self.db.delete(auth_session)
            self.db.commit()
            return None

    async def _exchange_code_for_tokens(self, provider: SSOProvider, auth_session: SSOAuthSession, code: str) -> Optional[Dict[str, Any]]:
        """Exchange authorization code for access tokens.

        Args:
            provider: SSO provider configuration
            auth_session: Auth session with PKCE parameters
            code: Authorization code

        Returns:
            Token response dict or None if failed
        """
        token_params = {
            "client_id": provider.client_id,
            "client_secret": self._decrypt_secret(provider.client_secret_encrypted),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": auth_session.redirect_uri,
            "code_verifier": auth_session.code_verifier,
        }

        # First-Party
        from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

        client = await get_http_client()
        response = await client.post(provider.token_url, data=token_params, headers={"Accept": "application/json"})

        if response.status_code == 200:
            return response.json()
        logger.error(f"Token exchange failed for {provider.name}: HTTP {response.status_code} - {response.text}")

        return None

    async def _get_user_info(self, provider: SSOProvider, access_token: str) -> Optional[Dict[str, Any]]:
        """Get user information from provider using access token.

        Args:
            provider: SSO provider configuration
            access_token: OAuth access token

        Returns:
            User info dict or None if failed
        """
        # First-Party
        from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

        client = await get_http_client()
        response = await client.get(provider.userinfo_url, headers={"Authorization": f"Bearer {access_token}"})

        if response.status_code == 200:
            user_data = response.json()

            # For GitHub, also fetch organizations if admin assignment is configured
            if provider.id == "github" and settings.sso_github_admin_orgs:
                try:
                    orgs_response = await client.get("https://api.github.com/user/orgs", headers={"Authorization": f"Bearer {access_token}"})
                    if orgs_response.status_code == 200:
                        orgs_data = orgs_response.json()
                        user_data["organizations"] = [org["login"] for org in orgs_data]
                    else:
                        logger.warning(f"Failed to fetch GitHub organizations: HTTP {orgs_response.status_code}")
                        user_data["organizations"] = []
                except Exception as e:
                    logger.warning(f"Error fetching GitHub organizations: {e}")
                    user_data["organizations"] = []

            # Normalize user info across providers
            return self._normalize_user_info(provider, user_data)
        logger.error(f"User info request failed for {provider.name}: HTTP {response.status_code} - {response.text}")

        return None

    def _normalize_user_info(self, provider: SSOProvider, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize user info from different providers to common format.

        Args:
            provider: SSO provider configuration
            user_data: Raw user data from provider

        Returns:
            Normalized user info dict
        """
        # Handle GitHub provider
        if provider.id == "github":
            return {
                "email": user_data.get("email"),
                "full_name": user_data.get("name") or user_data.get("login"),
                "avatar_url": user_data.get("avatar_url"),
                "provider_id": user_data.get("id"),
                "username": user_data.get("login"),
                "provider": "github",
                "organizations": user_data.get("organizations", []),
            }

        # Handle Google provider
        if provider.id == "google":
            return {
                "email": user_data.get("email"),
                "full_name": user_data.get("name"),
                "avatar_url": user_data.get("picture"),
                "provider_id": user_data.get("sub"),
                "username": user_data.get("email", "").split("@")[0],
                "provider": "google",
            }

        # Handle IBM Verify provider
        if provider.id == "ibm_verify":
            return {
                "email": user_data.get("email"),
                "full_name": user_data.get("name"),
                "avatar_url": user_data.get("picture"),
                "provider_id": user_data.get("sub"),
                "username": user_data.get("preferred_username") or user_data.get("email", "").split("@")[0],
                "provider": "ibm_verify",
            }

        # Handle Okta provider
        if provider.id == "okta":
            return {
                "email": user_data.get("email"),
                "full_name": user_data.get("name"),
                "avatar_url": user_data.get("picture"),
                "provider_id": user_data.get("sub"),
                "username": user_data.get("preferred_username") or user_data.get("email", "").split("@")[0],
                "provider": "okta",
            }

        # Handle Keycloak provider with role mapping
        if provider.id == "keycloak":
            metadata = provider.metadata or {}
            username_claim = metadata.get("username_claim", "preferred_username")
            email_claim = metadata.get("email_claim", "email")
            groups_claim = metadata.get("groups_claim", "groups")

            groups = []

            # Extract realm roles
            if metadata.get("map_realm_roles"):
                realm_access = user_data.get("realm_access", {})
                realm_roles = realm_access.get("roles", [])
                groups.extend(realm_roles)

            # Extract client roles
            if metadata.get("map_client_roles"):
                resource_access = user_data.get("resource_access", {})
                for client, access in resource_access.items():
                    client_roles = access.get("roles", [])
                    # Prefix with client name to avoid conflicts
                    groups.extend([f"{client}:{role}" for role in client_roles])

            # Extract groups from custom claim
            if groups_claim in user_data:
                custom_groups = user_data.get(groups_claim, [])
                if isinstance(custom_groups, list):
                    groups.extend(custom_groups)

            return {
                "email": user_data.get(email_claim),
                "full_name": user_data.get("name"),
                "avatar_url": user_data.get("picture"),
                "provider_id": user_data.get("sub"),
                "username": user_data.get(username_claim) or user_data.get(email_claim, "").split("@")[0],
                "provider": "keycloak",
                "groups": list(set(groups)),  # Deduplicate
            }

        # Handle Microsoft Entra ID provider
        if provider.id == "entra":
            # Microsoft's userinfo endpoint often omits the email claim
            # Fallback: preferred_username (UPN) or upn claim
            email = user_data.get("email") or user_data.get("preferred_username") or user_data.get("upn")

            # Extract username from email/UPN
            username = None
            if user_data.get("preferred_username"):
                username = user_data.get("preferred_username")
            elif email:
                username = email.split("@")[0]

            return {
                "email": email,
                "full_name": user_data.get("name") or email,  # Fallback to email if name missing
                "avatar_url": user_data.get("picture"),
                "provider_id": user_data.get("sub") or user_data.get("oid"),
                "username": username,
                "provider": "entra",
            }

        # Generic OIDC format for all other providers
        return {
            "email": user_data.get("email"),
            "full_name": user_data.get("name"),
            "avatar_url": user_data.get("picture"),
            "provider_id": user_data.get("sub"),
            "username": user_data.get("preferred_username") or user_data.get("email", "").split("@")[0],
            "provider": provider.id,
        }

    async def authenticate_or_create_user(self, user_info: Dict[str, Any]) -> Optional[str]:
        """Authenticate existing user or create new user from SSO info.

        Args:
            user_info: Normalized user info from SSO provider

        Returns:
            JWT token for authenticated user or None if failed
        """
        email = user_info.get("email")
        if not email:
            return None

        # Check if user exists
        user = await self.auth_service.get_user_by_email(email)

        if user:
            # Update user info from SSO
            if user_info.get("full_name") and user_info["full_name"] != user.full_name:
                user.full_name = user_info["full_name"]

            # Update auth provider if changed
            if user.auth_provider == "local" or user.auth_provider != user_info.get("provider"):
                user.auth_provider = user_info.get("provider", "sso")

            # Mark email as verified for SSO users
            user.email_verified = True
            user.last_login = utc_now()

            self.db.commit()
        else:
            # Auto-create user if enabled
            provider = self.get_provider(user_info.get("provider"))
            if not provider or not provider.auto_create_users:
                return None

            # Check trusted domains if configured
            if provider.trusted_domains:
                domain = email.split("@")[1].lower()
                if domain not in [d.lower() for d in provider.trusted_domains]:
                    return None

            # Check if admin approval is required
            if settings.sso_require_admin_approval:
                # Check if user is already pending approval

                pending = self.db.execute(select(PendingUserApproval).where(PendingUserApproval.email == email)).scalar_one_or_none()

                if pending:
                    if pending.status == "pending" and not pending.is_expired():
                        return None  # Still waiting for approval
                    if pending.status == "rejected":
                        return None  # User was rejected
                    if pending.status == "approved":
                        # User was approved, create account now
                        pass  # Continue with user creation below
                else:
                    # Create pending approval request

                    pending = PendingUserApproval(
                        email=email,
                        full_name=user_info.get("full_name", email),
                        auth_provider=user_info.get("provider", "sso"),
                        sso_metadata=user_info,
                        expires_at=utc_now() + timedelta(days=30),  # 30-day approval window
                    )
                    self.db.add(pending)
                    self.db.commit()
                    logger.info(f"Created pending approval request for SSO user: {email}")
                    return None  # No token until approved

            # Create new user (either no approval required, or approval already granted)
            # Generate a secure random password for SSO users (they won't use it)

            random_password = "".join(secrets.choice(string.ascii_letters + string.digits + string.punctuation) for _ in range(32))

            # Determine if user should be admin based on domain/organization
            is_admin = self._should_user_be_admin(email, user_info, provider)

            user = await self.auth_service.create_user(
                email=email,
                password=random_password,  # Random password for SSO users (not used)
                full_name=user_info.get("full_name", email),
                is_admin=is_admin,
                auth_provider=user_info.get("provider", "sso"),
            )
            if not user:
                return None

            # If user was created from approved request, mark request as used
            if settings.sso_require_admin_approval:
                pending = self.db.execute(select(PendingUserApproval).where(and_(PendingUserApproval.email == email, PendingUserApproval.status == "approved"))).scalar_one_or_none()
                if pending:
                    # Mark as used (we could delete or keep for audit trail)
                    pending.status = "completed"
                    self.db.commit()

        # Generate JWT token for user
        token_data = {
            "sub": user.email,
            "email": user.email,
            "full_name": user.full_name,
            "auth_provider": user.auth_provider,
            "iat": int(utc_now().timestamp()),
            "user": {"email": user.email, "full_name": user.full_name, "is_admin": user.is_admin, "auth_provider": user.auth_provider},
        }

        # Add user teams to token
        teams = user.get_teams()
        token_data["teams"] = [{"id": team.id, "name": team.name, "slug": team.slug, "is_personal": team.is_personal, "role": user.get_team_role(team.id)} for team in teams]

        # Add namespaces for RBAC
        namespaces = [f"user:{user.email}"]
        namespaces.extend([f"team:{team['slug']}" for team in token_data["teams"]])
        namespaces.append("public")
        token_data["namespaces"] = namespaces

        # Add scopes
        token_data["scopes"] = {"server_id": None, "permissions": ["*"] if user.is_admin else [], "ip_restrictions": [], "time_restrictions": {}}

        # Create JWT token
        token = await create_jwt_token(token_data)
        return token

    def _should_user_be_admin(self, email: str, user_info: Dict[str, Any], provider: SSOProvider) -> bool:
        """Determine if SSO user should be granted admin privileges.

        Args:
            email: User's email address
            user_info: Normalized user info from SSO provider
            provider: SSO provider configuration

        Returns:
            True if user should be admin, False otherwise
        """
        # Check domain-based admin assignment
        domain = email.split("@")[1].lower()
        if domain in [d.lower() for d in settings.sso_auto_admin_domains]:
            return True

        # Check provider-specific admin assignment
        if provider.id == "github" and settings.sso_github_admin_orgs:
            # For GitHub, we'd need to fetch user's organizations
            # This is a placeholder - in production, you'd make API calls to get orgs
            github_orgs = user_info.get("organizations", [])
            if any(org.lower() in [o.lower() for o in settings.sso_github_admin_orgs] for org in github_orgs):
                return True

        if provider.id == "google" and settings.sso_google_admin_domains:
            # Check if user's domain is in admin domains
            if domain in [d.lower() for d in settings.sso_google_admin_domains]:
                return True

        return False
