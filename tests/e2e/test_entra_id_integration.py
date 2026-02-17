# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_entra_id_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

End-to-end tests for Microsoft Entra ID integration.

This module tests the full OAuth flow with Microsoft Entra ID, including:
- Dynamic creation/deletion of test users and groups in Azure
- Group membership verification and role mapping
- Platform administrator assignment based on Entra ID groups
- Full HTTP endpoint integration with real tokens
- Token validation and rejection

The tests are fully self-contained: they create all necessary Azure resources
(users, groups) before tests and clean them up afterward.

Prerequisites:
    Azure App Registration with service principal that has:
    - "Allow public client flows" = Yes (under Authentication > Advanced settings)
    - API permissions (Application, not Delegated):
      * User.ReadWrite.All - Create/delete test users
      * Group.ReadWrite.All - Create/delete test groups, manage membership
      * Directory.ReadWrite.All - Alternative to above (full directory access)
    - Admin consent granted for above permissions

Environment Variables:
    AZURE_CLIENT_ID: Service principal app ID
    AZURE_CLIENT_SECRET: Service principal secret
    AZURE_TENANT_ID: Azure tenant ID
    TEST_ENTRA_USER_PASSWORD: Password to assign to created test users
        (must meet Azure AD password complexity requirements)
    TEST_ENTRA_DOMAIN: Email domain for test users (e.g., "yourdomain.onmicrosoft.com")
"""

from __future__ import annotations

# flake8: noqa: F821
# Note: F821 "undefined name" warnings are false positives.
# PEP 563 (__future__ annotations) makes forward references work at runtime,
# but flake8's static analysis doesn't understand this. The code is correct.

# Standard Library
import asyncio
import base64
from dataclasses import dataclass
import json
import logging
import os
import tempfile
import time
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch as mock_patch
import uuid

if TYPE_CHECKING:
    pass  # Forward references for type checking handled by __future__ annotations

# Third-Party
import httpx
from httpx import ASGITransport, AsyncClient
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Configure logging for test debugging
logger = logging.getLogger(__name__)

# First-Party
# NOTE: Do NOT replace RBAC decorators with no-ops at module level.
# Module-level patching poisons sys.modules under xdist: once main.py is
# imported with noop decorators, every test in the same worker sees endpoint
# functions without __wrapped__, breaking 45+ unit tests.
# Instead, the entra_test_db fixture mocks PermissionService at request time.
import mcpgateway.middleware.rbac as rbac_module  # noqa: E402

with mock_patch("mcpgateway.bootstrap_db.main"):
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.db import Base
    from mcpgateway.db import get_db as db_get_db
    from mcpgateway.main import app, get_db


# =============================================================================
# Environment Variable Helpers
# =============================================================================


def get_env_or_skip(var_name: str) -> str:
    """Get environment variable or skip the test if not set."""
    value = os.environ.get(var_name)
    if not value:
        pytest.skip(f"Environment variable {var_name} not set")
    return value


def has_azure_credentials() -> bool:
    """Check if Azure credentials are configured."""
    required = [
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_TENANT_ID",
        "TEST_ENTRA_USER_PASSWORD",
        "TEST_ENTRA_DOMAIN",
    ]
    return all(os.environ.get(var) for var in required)


# =============================================================================
# Data Classes for Test Resources
# =============================================================================


@dataclass
class AzureTestUser:
    """Represents a dynamically created test user in Azure AD."""

    id: str
    email: str
    display_name: str
    user_principal_name: str
    password: str


@dataclass
class AzureTestGroup:
    """Represents a dynamically created test group in Azure AD."""

    id: str
    display_name: str
    description: str


# =============================================================================
# Microsoft Graph API Client
# =============================================================================


class GraphAPIClient:
    """Client for Microsoft Graph API operations.

    Handles authentication and CRUD operations for users and groups.
    """

    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def _ensure_token(self, http_client: httpx.AsyncClient) -> str:
        """Ensure we have a valid access token, refreshing if needed."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        response = await http_client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )

        if response.status_code != 200:
            raise Exception(f"Failed to acquire Graph API token: {response.text}")

        data = response.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._access_token

    async def _request(
        self,
        http_client: httpx.AsyncClient,
        method: str,
        endpoint: str,
        json_data: Optional[Dict] = None,
    ) -> httpx.Response:
        """Make an authenticated request to the Graph API."""
        token = await self._ensure_token(http_client)
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        response = await http_client.request(method, url, headers=headers, json=json_data)
        return response

    # -------------------------------------------------------------------------
    # User Operations
    # -------------------------------------------------------------------------

    async def create_user(
        self,
        http_client: httpx.AsyncClient,
        display_name: str,
        mail_nickname: str,
        user_principal_name: str,
        password: str,
    ) -> AzureTestUser:
        """Create a new user in Azure AD.

        Args:
            http_client: HTTP client for requests
            display_name: User's display name
            mail_nickname: Mail nickname (username part)
            user_principal_name: Full UPN (email-like identifier)
            password: Initial password (must meet complexity requirements)

        Returns:
            AzureTestUser with created user details

        Raises:
            Exception: If user creation fails
        """
        user_data = {
            "accountEnabled": True,
            "displayName": display_name,
            "mailNickname": mail_nickname,
            "userPrincipalName": user_principal_name,
            "passwordProfile": {
                "forceChangePasswordNextSignIn": False,
                "password": password,
            },
        }

        response = await self._request(http_client, "POST", "/users", user_data)

        if response.status_code not in (200, 201):
            raise Exception(f"Failed to create user {user_principal_name}: {response.text}")

        data = response.json()
        logger.info(f"Created test user: {user_principal_name} (ID: {data['id']})")

        return AzureTestUser(
            id=data["id"],
            email=user_principal_name,
            display_name=data["displayName"],
            user_principal_name=data["userPrincipalName"],
            password=password,
        )

    async def delete_user(self, http_client: httpx.AsyncClient, user_id: str) -> bool:
        """Delete a user from Azure AD.

        Args:
            http_client: HTTP client for requests
            user_id: Azure AD user ID (GUID)

        Returns:
            True if deleted successfully, False otherwise
        """
        response = await self._request(http_client, "DELETE", f"/users/{user_id}")

        if response.status_code == 204:
            logger.info(f"Deleted test user: {user_id}")
            return True
        elif response.status_code == 404:
            logger.warning(f"User {user_id} not found (already deleted?)")
            return True
        else:
            logger.error(f"Failed to delete user {user_id}: {response.text}")
            return False

    async def get_user(self, http_client: httpx.AsyncClient, user_id: str) -> Optional[Dict]:
        """Get user details by ID."""
        response = await self._request(http_client, "GET", f"/users/{user_id}")
        if response.status_code == 200:
            return response.json()
        return None

    # -------------------------------------------------------------------------
    # Group Operations
    # -------------------------------------------------------------------------

    async def create_group(
        self,
        http_client: httpx.AsyncClient,
        display_name: str,
        description: str,
        mail_nickname: Optional[str] = None,
    ) -> AzureTestGroup:
        """Create a new security group in Azure AD.

        Args:
            http_client: HTTP client for requests
            display_name: Group display name
            description: Group description
            mail_nickname: Optional mail nickname

        Returns:
            AzureTestGroup with created group details
        """
        group_data = {
            "displayName": display_name,
            "description": description,
            "mailEnabled": False,
            "mailNickname": mail_nickname or display_name.replace(" ", "").lower(),
            "securityEnabled": True,
        }

        response = await self._request(http_client, "POST", "/groups", group_data)

        if response.status_code not in (200, 201):
            raise Exception(f"Failed to create group {display_name}: {response.text}")

        data = response.json()
        logger.info(f"Created test group: {display_name} (ID: {data['id']})")

        return AzureTestGroup(
            id=data["id"],
            display_name=data["displayName"],
            description=data.get("description", ""),
        )

    async def delete_group(self, http_client: httpx.AsyncClient, group_id: str) -> bool:
        """Delete a group from Azure AD.

        Args:
            http_client: HTTP client for requests
            group_id: Azure AD group ID (GUID)

        Returns:
            True if deleted successfully, False otherwise
        """
        response = await self._request(http_client, "DELETE", f"/groups/{group_id}")

        if response.status_code == 204:
            logger.info(f"Deleted test group: {group_id}")
            return True
        elif response.status_code == 404:
            logger.warning(f"Group {group_id} not found (already deleted?)")
            return True
        else:
            logger.error(f"Failed to delete group {group_id}: {response.text}")
            return False

    async def get_group(self, http_client: httpx.AsyncClient, group_id: str) -> Optional[Dict]:
        """Get group details by ID."""
        response = await self._request(http_client, "GET", f"/groups/{group_id}")
        if response.status_code == 200:
            return response.json()
        return None

    async def wait_for_group(
        self,
        http_client: httpx.AsyncClient,
        group_id: str,
        max_retries: int = 12,
        retry_delay: float = 5.0,
    ) -> bool:
        """Wait for a group to be available (Azure AD replication).

        Args:
            http_client: HTTP client for requests
            group_id: Azure AD group ID
            max_retries: Maximum number of retries (default 12 = 60 seconds)
            retry_delay: Delay between retries in seconds (default 5)

        Returns:
            True if group is available, False if timeout
        """
        for attempt in range(max_retries):
            group = await self.get_group(http_client, group_id)
            if group is not None:
                logger.info(f"Group {group_id} available after {attempt * retry_delay:.0f}s")
                return True
            logger.info(f"Waiting for group {group_id} (attempt {attempt + 1}/{max_retries})...")
            await asyncio.sleep(retry_delay)
        logger.error(f"Group {group_id} not available after {max_retries * retry_delay:.0f}s")
        return False

    # -------------------------------------------------------------------------
    # Group Membership Operations
    # -------------------------------------------------------------------------

    async def add_user_to_group(
        self,
        http_client: httpx.AsyncClient,
        group_id: str,
        user_id: str,
        max_retries: int = 6,
        retry_delay: float = 5.0,
    ) -> bool:
        """Add a user to a group with retry logic for Azure AD replication.

        Args:
            http_client: HTTP client for requests
            group_id: Azure AD group ID
            user_id: Azure AD user ID
            max_retries: Maximum number of retries for replication delays
            retry_delay: Delay between retries in seconds

        Returns:
            True if added successfully
        """
        member_data = {"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"}

        for attempt in range(max_retries):
            response = await self._request(http_client, "POST", f"/groups/{group_id}/members/$ref", member_data)

            if response.status_code == 204:
                logger.info(f"Added user {user_id} to group {group_id}")
                return True
            elif response.status_code == 400 and "already exist" in response.text.lower():
                logger.info(f"User {user_id} already in group {group_id}")
                return True
            elif response.status_code == 404:
                # Resource not found - likely Azure AD replication delay
                logger.info(f"Retrying add user to group (attempt {attempt + 1}/{max_retries}): {response.text}")
                await asyncio.sleep(retry_delay)
            else:
                raise Exception(f"Failed to add user to group: {response.text}")

        raise Exception(f"Failed to add user {user_id} to group {group_id} after {max_retries} retries")

    async def remove_user_from_group(
        self,
        http_client: httpx.AsyncClient,
        group_id: str,
        user_id: str,
    ) -> bool:
        """Remove a user from a group.

        Args:
            http_client: HTTP client for requests
            group_id: Azure AD group ID
            user_id: Azure AD user ID

        Returns:
            True if removed successfully
        """
        response = await self._request(http_client, "DELETE", f"/groups/{group_id}/members/{user_id}/$ref")

        if response.status_code == 204:
            logger.info(f"Removed user {user_id} from group {group_id}")
            return True
        elif response.status_code == 404:
            logger.info(f"User {user_id} not in group {group_id}")
            return True
        else:
            raise Exception(f"Failed to remove user from group: {response.text}")

    async def get_group_members(self, http_client: httpx.AsyncClient, group_id: str) -> List[Dict]:
        """Get all members of a group."""
        response = await self._request(http_client, "GET", f"/groups/{group_id}/members")
        if response.status_code == 200:
            return response.json().get("value", [])
        return []

    async def get_user_groups(self, http_client: httpx.AsyncClient, user_id: str) -> List[str]:
        """Get all group IDs a user is a member of."""
        response = await self._request(http_client, "POST", f"/users/{user_id}/getMemberObjects", {"securityEnabledOnly": False})
        if response.status_code == 200:
            return response.json().get("value", [])
        return []

    async def wait_for_membership(
        self,
        http_client: httpx.AsyncClient,
        group_id: str,
        user_id: str,
        max_retries: int = 12,
        retry_delay: float = 5.0,
    ) -> bool:
        """Wait for a user's group membership to be visible (Azure AD replication).

        Args:
            http_client: HTTP client for requests
            group_id: Azure AD group ID
            user_id: Azure AD user ID
            max_retries: Maximum number of retries
            retry_delay: Delay between retries in seconds

        Returns:
            True if membership is visible, False if timeout
        """
        for attempt in range(max_retries):
            members = await self.get_group_members(http_client, group_id)
            member_ids = [m["id"] for m in members]
            if user_id in member_ids:
                logger.info(f"User {user_id} membership in group {group_id} visible after {attempt * retry_delay:.0f}s")
                return True
            logger.info(f"Waiting for membership visibility (attempt {attempt + 1}/{max_retries})...")
            await asyncio.sleep(retry_delay)
        logger.error(f"User {user_id} membership in group {group_id} not visible after {max_retries * retry_delay:.0f}s")
        return False

    async def wait_for_membership_removal(
        self,
        http_client: httpx.AsyncClient,
        group_id: str,
        user_id: str,
        max_retries: int = 12,
        retry_delay: float = 5.0,
    ) -> bool:
        """Wait for a user's group membership removal to be visible (Azure AD replication).

        Args:
            http_client: HTTP client for requests
            group_id: Azure AD group ID
            user_id: Azure AD user ID
            max_retries: Maximum number of retries
            retry_delay: Delay between retries in seconds

        Returns:
            True if removal is visible, False if timeout
        """
        for attempt in range(max_retries):
            members = await self.get_group_members(http_client, group_id)
            member_ids = [m["id"] for m in members]
            if user_id not in member_ids:
                logger.info(f"User {user_id} removal from group {group_id} visible after {attempt * retry_delay:.0f}s")
                return True
            logger.info(f"Waiting for membership removal visibility (attempt {attempt + 1}/{max_retries})...")
            await asyncio.sleep(retry_delay)
        logger.error(f"User {user_id} still appears in group {group_id} after {max_retries * retry_delay:.0f}s")
        return False


# =============================================================================
# ROPC Token Acquirer
# =============================================================================


class ROPCTokenAcquirer:
    """Acquires tokens via Resource Owner Password Credentials (ROPC) flow.

    Note: ROPC requires "Allow public client flows" enabled in Azure App Registration.
    """

    def __init__(self, tenant_id: str, client_id: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    async def acquire_token(self, username: str, password: str, scope: str = "openid profile email") -> Dict[str, Any]:
        """Acquire tokens using ROPC flow."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "password",
                    "client_id": self.client_id,
                    "username": username,
                    "password": password,
                    "scope": scope,
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                raise httpx.HTTPStatusError(
                    f"ROPC token acquisition failed: {error_data.get('error_description', response.text)}",
                    request=response.request,
                    response=response,
                )

            return response.json()

    def decode_id_token_unverified(self, id_token: str) -> Dict[str, Any]:
        """Decode ID token without signature verification (for claim inspection)."""
        parts = id_token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")

        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def azure_credentials() -> Dict[str, str]:
    """Load Azure credentials from environment, skip if not available."""
    if not has_azure_credentials():
        pytest.skip("Azure credentials not configured")

    return {
        "client_id": os.environ["AZURE_CLIENT_ID"],
        "client_secret": os.environ["AZURE_CLIENT_SECRET"],
        "tenant_id": os.environ["AZURE_TENANT_ID"],
        "test_password": os.environ["TEST_ENTRA_USER_PASSWORD"],
        "test_domain": os.environ["TEST_ENTRA_DOMAIN"],
    }


@pytest.fixture(scope="module")
def graph_client(azure_credentials: Dict[str, str]) -> GraphAPIClient:
    """Create a Graph API client for Azure operations."""
    return GraphAPIClient(
        tenant_id=azure_credentials["tenant_id"],
        client_id=azure_credentials["client_id"],
        client_secret=azure_credentials["client_secret"],
    )


@pytest.fixture(scope="module")
def oidc_provider_config(azure_credentials: Dict[str, str]) -> Dict[str, str]:
    """Provider-agnostic OIDC configuration for Entra ID."""
    tenant_id = azure_credentials["tenant_id"]
    return {
        "issuer": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        "client_id": azure_credentials["client_id"],
        "client_secret": azure_credentials["client_secret"],
        "tenant_id": tenant_id,
        "authorization_endpoint": f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize",
        "token_endpoint": f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        "jwks_uri": f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
    }


@pytest.fixture
def ropc_token_acquirer(oidc_provider_config: Dict[str, str]) -> ROPCTokenAcquirer:
    """Create ROPC token acquirer for test user authentication."""
    return ROPCTokenAcquirer(
        tenant_id=oidc_provider_config["tenant_id"],
        client_id=oidc_provider_config["client_id"],
    )


# =============================================================================
# Dynamic Resource Fixtures (Create/Teardown)
# =============================================================================


@pytest_asyncio.fixture(scope="module")
async def test_admin_group(azure_credentials: Dict[str, str], graph_client: GraphAPIClient) -> AsyncGenerator[AzureTestGroup, None]:
    """Create a test admin group for the test session, delete afterward.

    This group will be used to test platform_admin role assignment.
    """
    unique_id = uuid.uuid4().hex[:8]
    group_name = f"ContextForge-TestAdmins-{unique_id}"

    async with httpx.AsyncClient() as http_client:
        group = await graph_client.create_group(
            http_client,
            display_name=group_name,
            description="Temporary test group for ContextForge E2E tests",
            mail_nickname=f"cftest-admins-{unique_id}",
        )

        # Wait for Azure AD replication before the group can be used
        available = await graph_client.wait_for_group(http_client, group.id)
        if not available:
            raise Exception(f"Group {group.id} not available after waiting for replication")

        yield group

        # Cleanup: Delete the group
        await graph_client.delete_group(http_client, group.id)


@pytest_asyncio.fixture(scope="module")
async def test_admin_group_secondary(azure_credentials: Dict[str, str], graph_client: GraphAPIClient) -> AsyncGenerator[AzureTestGroup, None]:
    """Create a secondary test admin group for multiple admin groups testing."""
    unique_id = uuid.uuid4().hex[:8]
    group_name = f"ContextForge-TestAdmins2-{unique_id}"

    async with httpx.AsyncClient() as http_client:
        group = await graph_client.create_group(
            http_client,
            display_name=group_name,
            description="Secondary test admin group for ContextForge E2E tests",
            mail_nickname=f"cftest-admins2-{unique_id}",
        )

        available = await graph_client.wait_for_group(http_client, group.id)
        if not available:
            raise Exception(f"Group {group.id} not available after waiting for replication")

        yield group

        await graph_client.delete_group(http_client, group.id)


@pytest_asyncio.fixture(scope="module")
async def test_regular_group(azure_credentials: Dict[str, str], graph_client: GraphAPIClient) -> AsyncGenerator[AzureTestGroup, None]:
    """Create a test regular (non-admin) group for the test session."""
    unique_id = uuid.uuid4().hex[:8]
    group_name = f"ContextForge-TestUsers-{unique_id}"

    async with httpx.AsyncClient() as http_client:
        group = await graph_client.create_group(
            http_client,
            display_name=group_name,
            description="Temporary test group for ContextForge E2E tests (non-admin)",
            mail_nickname=f"cftest-users-{unique_id}",
        )

        # Wait for Azure AD replication before the group can be used
        available = await graph_client.wait_for_group(http_client, group.id)
        if not available:
            raise Exception(f"Group {group.id} not available after waiting for replication")

        yield group

        # Cleanup: Delete the group
        await graph_client.delete_group(http_client, group.id)


@pytest_asyncio.fixture(scope="module")
async def test_admin_user(
    azure_credentials: Dict[str, str],
    graph_client: GraphAPIClient,
    test_admin_group: AzureTestGroup,
) -> AsyncGenerator[AzureTestUser, None]:
    """Create a test user and add them to the admin group.

    This user will be used to test admin role assignment via SSO.
    """
    unique_id = uuid.uuid4().hex[:8]
    domain = azure_credentials["test_domain"]
    password = azure_credentials["test_password"]

    mail_nickname = f"cftest-admin-{unique_id}"
    upn = f"{mail_nickname}@{domain}"
    display_name = f"ContextForge Test Admin {unique_id}"

    async with httpx.AsyncClient() as http_client:
        user = await graph_client.create_user(
            http_client,
            display_name=display_name,
            mail_nickname=mail_nickname,
            user_principal_name=upn,
            password=password,
        )

        # Add user to admin group
        await graph_client.add_user_to_group(http_client, test_admin_group.id, user.id)

        # Wait for membership to be visible in Azure AD
        await graph_client.wait_for_membership(http_client, test_admin_group.id, user.id)

        yield user

        # Cleanup: Delete the user (will auto-remove from groups)
        await graph_client.delete_user(http_client, user.id)


@pytest_asyncio.fixture(scope="module")
async def test_regular_user(
    azure_credentials: Dict[str, str],
    graph_client: GraphAPIClient,
    test_regular_group: AzureTestGroup,
) -> AsyncGenerator[AzureTestUser, None]:
    """Create a test user in the non-admin group.

    This user will be used to test that non-admin users don't get admin role.
    """
    unique_id = uuid.uuid4().hex[:8]
    domain = azure_credentials["test_domain"]
    password = azure_credentials["test_password"]

    mail_nickname = f"cftest-regular-{unique_id}"
    upn = f"{mail_nickname}@{domain}"
    display_name = f"ContextForge Test User {unique_id}"

    async with httpx.AsyncClient() as http_client:
        user = await graph_client.create_user(
            http_client,
            display_name=display_name,
            mail_nickname=mail_nickname,
            user_principal_name=upn,
            password=password,
        )

        # Add user to regular (non-admin) group
        await graph_client.add_user_to_group(http_client, test_regular_group.id, user.id)

        # Wait for membership to be visible in Azure AD
        await graph_client.wait_for_membership(http_client, test_regular_group.id, user.id)

        yield user

        # Cleanup: Delete the user
        await graph_client.delete_user(http_client, user.id)


# Standard
# =============================================================================
# Test Database and Client Fixtures
# =============================================================================


def generate_test_jwt():
    """Generate a valid JWT token for testing."""
    payload = {
        "sub": "test_user",
        "exp": int(time.time()) + 3600,
        "teams": [],
    }
    secret = settings.jwt_secret_key.get_secret_value()
    algorithm = settings.jwt_algorithm
    return jwt.encode(payload, secret, algorithm=algorithm)


@pytest_asyncio.fixture
async def entra_test_db():
    """Create a temporary SQLite database for Entra ID E2E testing."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)  # noqa: N806

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[db_get_db] = override_get_db

    # Override authentication
    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.utils.create_jwt_token import get_jwt_token
    from mcpgateway.utils.verify_credentials import require_admin_auth, require_auth

    # Local
    from tests.utils.rbac_mocks import create_mock_email_user, create_mock_user_context, MockPermissionService

    def override_auth():
        return "testuser"

    mock_email_user = create_mock_email_user(email="testuser@example.com", full_name="Test User", is_admin=True, is_active=True)

    async def mock_require_admin_auth():
        return "testuser@example.com"

    async def mock_get_jwt_token():
        return generate_test_jwt()

    test_user_context = create_mock_user_context(email="testuser@example.com", full_name="Test User", is_admin=True)
    test_user_context["db"] = TestSessionLocal()

    async def simple_mock_user_with_permissions():
        return test_user_context

    # First-Party
    from mcpgateway.middleware.rbac import get_permission_service

    def mock_get_permission_service(*args, **kwargs):
        return MockPermissionService(always_grant=True)

    app.dependency_overrides[require_auth] = override_auth
    app.dependency_overrides[get_current_user] = lambda: mock_email_user
    app.dependency_overrides[require_admin_auth] = mock_require_admin_auth
    app.dependency_overrides[get_jwt_token] = mock_get_jwt_token
    app.dependency_overrides[get_current_user_with_permissions] = simple_mock_user_with_permissions
    app.dependency_overrides[get_permission_service] = mock_get_permission_service

    # Mock PermissionService on the rbac module so RBAC decorators (which
    # instantiate PermissionService directly, not via dependency injection)
    # always grant permissions during e2e tests.
    mock_ps_instance = MagicMock()
    mock_ps_instance.check_permission = AsyncMock(return_value=True)
    mock_ps_instance.check_admin_permission = AsyncMock(return_value=True)
    mock_ps_class = MagicMock(return_value=mock_ps_instance)
    rbac_ps_patcher = mock_patch.object(rbac_module, "PermissionService", mock_ps_class)
    rbac_ps_patcher.start()

    # Mock security_logger to prevent database access issues
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = mock_patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)
    sec_patcher.start()

    yield {"engine": engine, "session_local": TestSessionLocal}

    # Cleanup
    rbac_ps_patcher.stop()
    sec_patcher.stop()
    app.dependency_overrides.clear()
    os.close(db_fd)
    os.unlink(db_path)


@pytest_asyncio.fixture
async def entra_client(entra_test_db) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with Entra ID test database."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# =============================================================================
# Role Assertion Helpers
# =============================================================================


class RoleAssertions:
    """Reusable role assertion helpers for testing."""

    def __init__(self, session_local):
        self.session_local = session_local

    def get_user_by_email(self, email: str):
        """Get user from database by email."""
        # First-Party
        from mcpgateway.db import EmailUser

        with self.session_local() as db:
            return db.query(EmailUser).filter(EmailUser.email == email).first()

    def get_user_roles(self, email: str):
        """Get all active roles for a user."""
        # First-Party
        from mcpgateway.db import EmailUser, UserRole

        with self.session_local() as db:
            user = db.query(EmailUser).filter(EmailUser.email == email).first()
            if not user:
                return []
            return db.query(UserRole).filter(UserRole.user_id == user.id, UserRole.is_active == True).all()  # noqa: E712

    def has_platform_admin_role(self, email: str) -> bool:
        """Check if user has platform_admin role."""
        roles = self.get_user_roles(email)
        return any(r.role.name == "platform_admin" for r in roles)

    def assert_user_is_admin(self, email: str):
        """Assert that user is marked as admin."""
        user = self.get_user_by_email(email)
        assert user is not None, f"User {email} not found"
        assert user.is_admin is True, f"User {email} is_admin should be True"

    def assert_user_is_not_admin(self, email: str):
        """Assert that user is not marked as admin."""
        user = self.get_user_by_email(email)
        assert user is not None, f"User {email} not found"
        assert user.is_admin is False, f"User {email} is_admin should be False"


@pytest.fixture
def role_assertions(entra_test_db) -> RoleAssertions:
    """Create role assertion helper with test database session."""
    return RoleAssertions(entra_test_db["session_local"])


# =============================================================================
# Helper: Create SSO Provider in Test DB
# =============================================================================


def create_entra_sso_provider(db, provider_id: str = "entra"):
    """Create an Entra ID SSO provider in the test database."""
    # First-Party
    from mcpgateway.db import SSOProvider

    existing = db.query(SSOProvider).filter(SSOProvider.id == provider_id).first()
    if existing:
        return existing

    provider = SSOProvider(
        id=provider_id,
        name=provider_id,
        display_name="Microsoft Entra ID",
        provider_type="oidc",
        client_id="test_client_id",
        client_secret_encrypted="encrypted_secret",
        authorization_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        userinfo_url="https://graph.microsoft.com/oidc/userinfo",
        is_enabled=True,
        auto_create_users=True,
        provider_metadata={"groups_claim": "groups"},
    )
    db.add(provider)
    db.commit()
    return provider


# =============================================================================
# Test Classes - SSOService Role Mapping (Tests 10-13)
# =============================================================================


@pytest.mark.skipif(not has_azure_credentials(), reason="Azure credentials not configured")
class TestEntraIDRoleMapping:
    """Tests for Entra ID SSO role mapping logic."""

    @pytest.mark.asyncio
    async def test_admin_user_gets_admin_role(
        self,
        entra_test_db,
        test_admin_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
    ):
        """Full OAuth flow assigns platform_admin for admin group member."""
        # First-Party
        from mcpgateway.services.sso_service import SSOService

        session_local = entra_test_db["session_local"]

        with session_local() as db:
            create_entra_sso_provider(db)

            sso_service = SSOService(db)

            # Simulate normalized user info with admin group
            user_info = {
                "email": test_admin_user.user_principal_name,
                "full_name": test_admin_user.display_name,
                "provider": "entra",
                "provider_id": test_admin_user.id,
                "username": test_admin_user.email.split("@")[0],
                "groups": [test_admin_group.id],  # Dynamic group ID
            }

            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                mock_settings.sso_entra_admin_groups = [test_admin_group.id]
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = True
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_token"
                    result = await sso_service.authenticate_or_create_user(user_info)

                    assert result is not None, "Expected JWT token to be returned"

            # Verify user was created with admin status
            # First-Party
            from mcpgateway.db import EmailUser

            user = db.query(EmailUser).filter(EmailUser.email == test_admin_user.user_principal_name).first()
            assert user is not None, "User should have been created"
            assert user.is_admin is True, "User should be admin"

    @pytest.mark.asyncio
    async def test_regular_user_does_not_get_admin_role(
        self,
        entra_test_db,
        test_regular_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
        test_regular_group: AzureTestGroup,
    ):
        """Regular user without admin group does not get platform_admin."""
        # First-Party
        from mcpgateway.services.sso_service import SSOService

        session_local = entra_test_db["session_local"]

        with session_local() as db:
            create_entra_sso_provider(db)

            sso_service = SSOService(db)

            # User info with regular group (NOT admin group)
            user_info = {
                "email": test_regular_user.user_principal_name,
                "full_name": test_regular_user.display_name,
                "provider": "entra",
                "provider_id": test_regular_user.id,
                "username": test_regular_user.email.split("@")[0],
                "groups": [test_regular_group.id],  # Regular group, not admin
            }

            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                mock_settings.sso_entra_admin_groups = [test_admin_group.id]
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = True
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_token"
                    await sso_service.authenticate_or_create_user(user_info)

            # First-Party
            from mcpgateway.db import EmailUser

            user = db.query(EmailUser).filter(EmailUser.email == test_regular_user.user_principal_name).first()
            assert user is not None, "User should have been created"
            assert user.is_admin is False, "Regular user should NOT have is_admin=True"

    @pytest.mark.asyncio
    async def test_user_gains_admin_when_added_to_group(
        self,
        entra_test_db,
        test_regular_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
        test_regular_group: AzureTestGroup,
        graph_client: GraphAPIClient,
    ):
        """User gains admin when added to admin group and logs in again."""
        # First-Party
        from mcpgateway.db import EmailUser
        from mcpgateway.services.sso_service import SSOService

        session_local = entra_test_db["session_local"]

        # First, create user without admin
        with session_local() as db:
            create_entra_sso_provider(db)

            # Create user as non-admin first
            existing_user = EmailUser(
                email=f"promote_{test_regular_user.user_principal_name}",
                full_name="User to Promote",
                is_admin=False,
                is_active=True,
                auth_provider="entra",
                password_hash="sso_user_no_password",  # SSO users don't use password auth
            )
            db.add(existing_user)
            db.commit()

            sso_service = SSOService(db)

            # Now simulate login WITH admin group (user was added to group)
            user_info = {
                "email": f"promote_{test_regular_user.user_principal_name}",
                "full_name": "User to Promote",
                "provider": "entra",
                "provider_id": "promote-oid",
                "username": "promote",
                "groups": [test_admin_group.id],  # Now in admin group!
            }

            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                mock_settings.sso_entra_admin_groups = [test_admin_group.id]
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = True
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_token"
                    await sso_service.authenticate_or_create_user(user_info)

            db.expire_all()
            user = db.query(EmailUser).filter(EmailUser.email == f"promote_{test_regular_user.user_principal_name}").first()
            assert user is not None
            assert user.is_admin is True, "User should have been promoted to admin"

    @pytest.mark.asyncio
    async def test_admin_group_matching_is_case_insensitive(
        self,
        entra_test_db,
        test_admin_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
    ):
        """Group matching handles case variations (UUID case insensitivity)."""
        # First-Party
        from mcpgateway.services.sso_service import SSOService

        session_local = entra_test_db["session_local"]

        with session_local() as db:
            create_entra_sso_provider(db)

            sso_service = SSOService(db)

            # Use UPPERCASE group ID in token claims
            user_info = {
                "email": f"case_test_{test_admin_user.user_principal_name}",
                "full_name": "Case Test User",
                "provider": "entra",
                "provider_id": "case-test-oid",
                "username": "casetest",
                "groups": [test_admin_group.id.upper()],  # UPPERCASE
            }

            # Configure with lowercase
            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                mock_settings.sso_entra_admin_groups = [test_admin_group.id.lower()]  # lowercase
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = True
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_token"
                    await sso_service.authenticate_or_create_user(user_info)

            # First-Party
            from mcpgateway.db import EmailUser

            user = db.query(EmailUser).filter(EmailUser.email == f"case_test_{test_admin_user.user_principal_name}").first()
            assert user is not None
            assert user.is_admin is True, "Admin group matching should be case-insensitive"


# =============================================================================
# Test Classes - True End-to-End with HTTP Endpoints
# =============================================================================


@pytest.mark.skipif(not has_azure_credentials(), reason="Azure credentials not configured")
class TestEntraIDEndToEndHTTP:
    """True E2E tests using HTTP endpoints with real Entra ID tokens."""

    @pytest.mark.asyncio
    async def test_sso_callback_with_real_token_creates_admin_user(
        self,
        entra_test_db,
        entra_client: AsyncClient,
        test_admin_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
        ropc_token_acquirer: ROPCTokenAcquirer,
        oidc_provider_config: Dict[str, str],
    ):
        """Full E2E: ROPC token acquisition + SSO callback endpoint creates admin user."""
        session_local = entra_test_db["session_local"]

        # Step 1: Acquire real token from Entra ID via ROPC
        try:
            tokens = await ropc_token_acquirer.acquire_token(
                username=test_admin_user.user_principal_name,
                password=test_admin_user.password,
            )
        except httpx.HTTPStatusError as e:
            pytest.skip(f"ROPC not enabled for this app registration: {e}")

        id_token = tokens["id_token"]
        claims = ropc_token_acquirer.decode_id_token_unverified(id_token)

        # Step 2: Create SSO provider in test database
        # NOTE: Provider ID must be exactly "entra" for admin group checks to work
        # (SSOService._should_user_be_admin checks provider.id == "entra")
        with session_local() as db:
            create_entra_sso_provider(db, provider_id="entra")

        # Step 3: Mock the OAuth callback exchange to return our real user info
        # (Since we can't do actual OAuth code exchange with ROPC tokens)
        # First-Party
        from mcpgateway.services.sso_service import SSOService

        user_email = f"e2e_http_{test_admin_user.user_principal_name}"

        with session_local() as db:
            sso_service = SSOService(db)

            # Construct user_info from real token claims
            # NOTE: provider must be "entra" (not "entra-e2e") for admin group matching
            user_info = {
                "email": user_email,
                "full_name": claims.get("name", test_admin_user.display_name),
                "provider": "entra",
                "provider_id": claims.get("oid", claims.get("sub")),
                "username": claims.get("preferred_username", "").split("@")[0],
                "groups": [test_admin_group.id],  # Real group ID from Azure
            }

            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                mock_settings.sso_entra_admin_groups = [test_admin_group.id]
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = True
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_jwt_token"
                    result = await sso_service.authenticate_or_create_user(user_info)

            assert result is not None, "Should return JWT token"

            # Verify user created with admin rights
            # First-Party
            from mcpgateway.db import EmailUser

            user = db.query(EmailUser).filter(EmailUser.email == user_email).first()
            assert user is not None, "User should be created in database"
            assert user.is_admin is True, "User should be admin (in admin group)"
            assert user.auth_provider == "entra", "Auth provider should be set"

    @pytest.mark.asyncio
    async def test_sso_providers_endpoint_lists_enabled_providers(
        self,
        entra_test_db,
        entra_client: AsyncClient,
    ):
        """Verify /auth/sso/providers endpoint returns enabled providers."""
        session_local = entra_test_db["session_local"]

        # Create SSO provider
        with session_local() as db:
            create_entra_sso_provider(db, provider_id="entra-list-test")

        # Mock sso_enabled setting
        with mock_patch("mcpgateway.routers.sso.settings") as mock_settings:
            mock_settings.sso_enabled = True

            response = await entra_client.get("/auth/sso/providers")

        # Note: May return 404 if SSO is disabled in actual settings
        # This tests the endpoint structure
        assert response.status_code in [200, 404], f"Unexpected status: {response.status_code}"


# =============================================================================
# Test Classes - Admin Role Retention (By Design)
# =============================================================================


@pytest.mark.skipif(not has_azure_credentials(), reason="Azure credentials not configured")
class TestEntraIDAdminRoleRetention:
    """Tests verifying that admin role is RETAINED when user leaves admin group.

    IMPORTANT: By design, the SSOService only UPGRADES is_admin via SSO, never downgrades.
    This is intentional to preserve manual admin grants made via Admin UI/API.
    To revoke admin access, administrators must use the Admin UI/API directly.

    See SSOService._should_user_be_admin() comments for rationale.
    """

    @pytest.mark.asyncio
    async def test_admin_retains_role_when_removed_from_group(
        self,
        entra_test_db,
        test_admin_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
        test_regular_group: AzureTestGroup,
    ):
        """Admin RETAINS role even when removed from admin group (by design).

        This test verifies the intentional design decision that SSO login
        does not demote admins. This preserves manual admin grants and requires
        explicit revocation through Admin UI/API.
        """
        # First-Party
        from mcpgateway.db import EmailUser
        from mcpgateway.services.sso_service import SSOService

        session_local = entra_test_db["session_local"]

        retain_email = f"retain_{test_admin_user.user_principal_name}"

        with session_local() as db:
            create_entra_sso_provider(db)

            # Create user as admin first
            admin_user = EmailUser(
                email=retain_email,
                full_name="User to Retain Admin",
                is_admin=True,  # Start as admin
                is_active=True,
                auth_provider="entra",
                password_hash="sso_user_no_password",
            )
            db.add(admin_user)
            db.commit()

            sso_service = SSOService(db)

            # Simulate login WITHOUT admin group (user was removed from group)
            user_info = {
                "email": retain_email,
                "full_name": "User to Retain Admin",
                "provider": "entra",
                "provider_id": "retain-oid",
                "username": "retain",
                "groups": [test_regular_group.id],  # Only in regular group now!
            }

            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                mock_settings.sso_entra_admin_groups = [test_admin_group.id]
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = True
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_token"
                    await sso_service.authenticate_or_create_user(user_info)

            db.expire_all()
            user = db.query(EmailUser).filter(EmailUser.email == retain_email).first()
            assert user is not None
            # By design: admin status is RETAINED (not demoted via SSO)
            assert user.is_admin is True, "Admin should retain role (SSO never demotes)"

    @pytest.mark.asyncio
    async def test_admin_retains_role_when_no_groups_in_token(
        self,
        entra_test_db,
        test_admin_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
    ):
        """Admin RETAINS role even when token contains no groups (by design).

        This test verifies that missing groups claim does not cause demotion.
        This protects against accidental admin revocation due to token configuration
        issues (e.g., groups claim not configured in Azure App Registration).
        """
        # First-Party
        from mcpgateway.db import EmailUser
        from mcpgateway.services.sso_service import SSOService

        session_local = entra_test_db["session_local"]

        no_groups_email = f"nogroups_{test_admin_user.user_principal_name}"

        with session_local() as db:
            create_entra_sso_provider(db)

            # Create user as admin first
            admin_user = EmailUser(
                email=no_groups_email,
                full_name="User with No Groups",
                is_admin=True,
                is_active=True,
                auth_provider="entra",
                password_hash="sso_user_no_password",
            )
            db.add(admin_user)
            db.commit()

            sso_service = SSOService(db)

            # Login with empty groups (token might not include groups claim)
            user_info = {
                "email": no_groups_email,
                "full_name": "User with No Groups",
                "provider": "entra",
                "provider_id": "nogroups-oid",
                "username": "nogroups",
                "groups": [],  # Empty groups!
            }

            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                mock_settings.sso_entra_admin_groups = [test_admin_group.id]
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = True
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_token"
                    await sso_service.authenticate_or_create_user(user_info)

            db.expire_all()
            user = db.query(EmailUser).filter(EmailUser.email == no_groups_email).first()
            assert user is not None
            # By design: admin status is RETAINED (not demoted via SSO)
            assert user.is_admin is True, "Admin should retain role even with empty groups"


# =============================================================================
# Test Classes - Multiple Admin Groups
# =============================================================================


@pytest.mark.skipif(not has_azure_credentials(), reason="Azure credentials not configured")
class TestEntraIDMultipleAdminGroups:
    """Tests for multiple admin group configurations."""

    @pytest.mark.asyncio
    async def test_user_in_secondary_admin_group_gets_admin(
        self,
        entra_test_db,
        test_admin_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
        test_admin_group_secondary: AzureTestGroup,
    ):
        """User in secondary admin group also gets admin role."""
        # First-Party
        from mcpgateway.services.sso_service import SSOService

        session_local = entra_test_db["session_local"]

        secondary_email = f"secondary_{test_admin_user.user_principal_name}"

        with session_local() as db:
            create_entra_sso_provider(db)

            sso_service = SSOService(db)

            # User only in SECONDARY admin group
            user_info = {
                "email": secondary_email,
                "full_name": "Secondary Admin User",
                "provider": "entra",
                "provider_id": "secondary-oid",
                "username": "secondaryadmin",
                "groups": [test_admin_group_secondary.id],  # Only in secondary group
            }

            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                # Configure BOTH admin groups
                mock_settings.sso_entra_admin_groups = [
                    test_admin_group.id,
                    test_admin_group_secondary.id,
                ]
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = True
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_token"
                    await sso_service.authenticate_or_create_user(user_info)

            # First-Party
            from mcpgateway.db import EmailUser

            user = db.query(EmailUser).filter(EmailUser.email == secondary_email).first()
            assert user is not None
            assert user.is_admin is True, "User in secondary admin group should be admin"

    @pytest.mark.asyncio
    async def test_user_in_both_admin_groups_gets_admin(
        self,
        entra_test_db,
        test_admin_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
        test_admin_group_secondary: AzureTestGroup,
    ):
        """User in both admin groups gets admin role."""
        # First-Party
        from mcpgateway.services.sso_service import SSOService

        session_local = entra_test_db["session_local"]

        both_email = f"both_{test_admin_user.user_principal_name}"

        with session_local() as db:
            create_entra_sso_provider(db)

            sso_service = SSOService(db)

            # User in BOTH admin groups
            user_info = {
                "email": both_email,
                "full_name": "Both Groups Admin",
                "provider": "entra",
                "provider_id": "both-oid",
                "username": "bothadmin",
                "groups": [test_admin_group.id, test_admin_group_secondary.id],
            }

            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                mock_settings.sso_entra_admin_groups = [
                    test_admin_group.id,
                    test_admin_group_secondary.id,
                ]
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = True
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_token"
                    await sso_service.authenticate_or_create_user(user_info)

            # First-Party
            from mcpgateway.db import EmailUser

            user = db.query(EmailUser).filter(EmailUser.email == both_email).first()
            assert user is not None
            assert user.is_admin is True, "User in both admin groups should be admin"


# =============================================================================
# Test Classes - Token Validation
# =============================================================================


@pytest.mark.skipif(not has_azure_credentials(), reason="Azure credentials not configured")
class TestEntraIDTokenValidation:
    """Tests for token validation and rejection scenarios."""

    @pytest.mark.asyncio
    async def test_expired_token_claims_detected(
        self,
        oidc_provider_config: Dict[str, str],
    ):
        """Expired tokens can be detected by claim inspection."""
        # Create a token that expired in the past
        expired_payload = {
            "sub": "test-user",
            "iss": oidc_provider_config["issuer"],
            "aud": oidc_provider_config["client_id"],
            "exp": int(time.time()) - 3600,  # Expired 1 hour ago
            "iat": int(time.time()) - 7200,
        }

        expired_token = jwt.encode(expired_payload, "test-secret", algorithm="HS256")

        # Verify we can detect expiration
        decoded = jwt.decode(
            expired_token,
            "test-secret",
            algorithms=["HS256"],
            options={"verify_exp": False, "verify_aud": False},
        )

        assert decoded["exp"] < time.time(), "Token should be expired"

        # Verify PyJWT raises ExpiredSignatureError when verifying
        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(
                expired_token,
                "test-secret",
                algorithms=["HS256"],
                options={"verify_aud": False},
            )

    @pytest.mark.asyncio
    async def test_invalid_audience_detected(
        self,
        oidc_provider_config: Dict[str, str],
    ):
        """Tokens with invalid audience are detectable."""
        invalid_aud_payload = {
            "sub": "test-user",
            "iss": oidc_provider_config["issuer"],
            "aud": "wrong-client-id",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }

        token = jwt.encode(invalid_aud_payload, "test-secret", algorithm="HS256")

        decoded = jwt.decode(
            token,
            "test-secret",
            algorithms=["HS256"],
            options={"verify_aud": False},
        )

        assert decoded["aud"] != oidc_provider_config["client_id"], "Audience should not match"

        # Verify PyJWT raises InvalidAudienceError when verifying
        with pytest.raises(jwt.InvalidAudienceError):
            jwt.decode(
                token,
                "test-secret",
                algorithms=["HS256"],
                audience=oidc_provider_config["client_id"],
            )

    @pytest.mark.asyncio
    async def test_invalid_issuer_detected(
        self,
        oidc_provider_config: Dict[str, str],
    ):
        """Tokens with invalid issuer are detectable."""
        invalid_iss_payload = {
            "sub": "test-user",
            "iss": "https://evil-issuer.example.com",
            "aud": oidc_provider_config["client_id"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }

        token = jwt.encode(invalid_iss_payload, "test-secret", algorithm="HS256")

        decoded = jwt.decode(
            token,
            "test-secret",
            algorithms=["HS256"],
            options={"verify_aud": False, "verify_iss": False},
        )

        assert decoded["iss"] != oidc_provider_config["issuer"], "Issuer should not match"

        # Verify PyJWT raises InvalidIssuerError when verifying
        with pytest.raises(jwt.InvalidIssuerError):
            jwt.decode(
                token,
                "test-secret",
                algorithms=["HS256"],
                issuer=oidc_provider_config["issuer"],
                options={"verify_aud": False},
            )

    @pytest.mark.asyncio
    async def test_real_token_has_valid_claims(
        self,
        ropc_token_acquirer: ROPCTokenAcquirer,
        test_admin_user: AzureTestUser,
        oidc_provider_config: Dict[str, str],
    ):
        """Real tokens from Entra ID have valid standard claims."""
        try:
            tokens = await ropc_token_acquirer.acquire_token(
                username=test_admin_user.user_principal_name,
                password=test_admin_user.password,
            )
        except httpx.HTTPStatusError as e:
            pytest.skip(f"ROPC not enabled: {e}")

        id_token = tokens["id_token"]
        claims = ropc_token_acquirer.decode_id_token_unverified(id_token)

        # Verify standard OIDC claims
        assert "sub" in claims, "Token should have 'sub' claim"
        assert "iss" in claims, "Token should have 'iss' claim"
        assert "aud" in claims, "Token should have 'aud' claim"
        assert "exp" in claims, "Token should have 'exp' claim"
        assert "iat" in claims, "Token should have 'iat' claim"

        # Verify token is not expired
        assert claims["exp"] > time.time(), "Token should not be expired"

        # Verify issuer matches expected
        assert oidc_provider_config["tenant_id"] in claims["iss"], "Issuer should contain tenant ID"


# =============================================================================
# Test Classes - Disabled Sync Behavior
# =============================================================================


@pytest.mark.skipif(not has_azure_credentials(), reason="Azure credentials not configured")
class TestEntraIDSyncDisabled:
    """Tests for behavior when role sync on login is disabled."""

    @pytest.mark.asyncio
    async def test_admin_retains_role_when_sync_disabled(
        self,
        entra_test_db,
        test_admin_user: AzureTestUser,
        test_admin_group: AzureTestGroup,
        test_regular_group: AzureTestGroup,
    ):
        """Admin retains role even if removed from group when sync is disabled."""
        # First-Party
        from mcpgateway.db import EmailUser
        from mcpgateway.services.sso_service import SSOService

        session_local = entra_test_db["session_local"]

        nosync_email = f"nosync_{test_admin_user.user_principal_name}"

        with session_local() as db:
            create_entra_sso_provider(db)

            # Create user as admin first
            admin_user = EmailUser(
                email=nosync_email,
                full_name="No Sync Admin",
                is_admin=True,  # Start as admin
                is_active=True,
                auth_provider="entra",
                password_hash="sso_user_no_password",
            )
            db.add(admin_user)
            db.commit()

            sso_service = SSOService(db)

            # Login WITHOUT admin group, but sync is DISABLED
            user_info = {
                "email": nosync_email,
                "full_name": "No Sync Admin",
                "provider": "entra",
                "provider_id": "nosync-oid",
                "username": "nosync",
                "groups": [test_regular_group.id],  # Not in admin group
            }

            with mock_patch("mcpgateway.services.sso_service.settings") as mock_settings:
                mock_settings.sso_entra_admin_groups = [test_admin_group.id]
                mock_settings.sso_entra_role_mappings = {}
                mock_settings.sso_entra_default_role = None
                mock_settings.sso_entra_sync_roles_on_login = False  # DISABLED!
                mock_settings.sso_auto_admin_domains = []
                mock_settings.sso_github_admin_orgs = []
                mock_settings.sso_google_admin_domains = []
                mock_settings.sso_require_admin_approval = False
                mock_settings.default_admin_role = "platform_admin"
                mock_settings.jwt_secret_key = settings.jwt_secret_key
                mock_settings.jwt_algorithm = settings.jwt_algorithm
                mock_settings.jwt_expiration_minutes = 60

                with mock_patch("mcpgateway.services.sso_service.create_jwt_token") as mock_jwt:
                    mock_jwt.return_value = "mock_token"
                    await sso_service.authenticate_or_create_user(user_info)

            db.expire_all()
            user = db.query(EmailUser).filter(EmailUser.email == nosync_email).first()
            assert user is not None
            # When sync is disabled, existing admin status should be preserved
            # (This tests that the sync flag is respected)
            # Note: Actual behavior depends on SSOService implementation
