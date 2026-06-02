"""Location: ./plugins/apiconnect_fam/fam/client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

IBM API Connect Federated API Management Asset Catalog Client.
"""

# Standard
import base64
import logging
from typing import Any, Callable, Dict, List, Optional

# Third-Party
import httpx

# Local
from ..circuit_breaker import CircuitBreaker, CircuitBreakerError
from ..models import ReregistrationReport
from .endpoints import FAMEndpoints
from .payloads import FAMRuntimePayload, FAMServerPayload, FAMToolPayload

logger = logging.getLogger(__name__)


class FAMAssetCatalogClient:
    """Client for IBM API Connect Federated API Management Asset Catalog API v1.

    Handles MCP Server lifecycle operations (create, update, delete) with
    proper error handling and logging.

    Attributes:
        base_url: IBM API Connect Federated API Management API base URL
        runtime_id: Runtime identifier for API requests
        http_client: Async HTTP client for API calls
    """

    def __init__(
        self,
        base_url: str,
        runtime_id: str,
        auth_type: str = "basic",
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        timeout: int = 30,
        verify_ssl: bool = True,
        circuit_breaker_enabled: bool = True,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_timeout: float = 60.0,
    ):
        """Initialize IBM API Connect Federated API Management client.

        Args:
            base_url: IBM API Connect Federated API Management API base URL (e.g., https://fam.example.com)
            runtime_id: Runtime identifier
            auth_type: Authentication type - 'basic' or 'apikey' (default: 'basic')
            username: IBM API Connect Federated API Management username for Basic Authentication
            password: IBM API Connect Federated API Management password for Basic Authentication
            api_key: IBM API Connect Federated API Management API key for API Key Authentication
            client_id: IBM API Connect Federated API Management client ID for API Key Authentication
            timeout: HTTP request timeout in seconds
            verify_ssl: Whether to verify SSL certificates (default: True, set False for self-signed certs)
            circuit_breaker_enabled: Enable circuit breaker pattern (default: True)
            circuit_breaker_failure_threshold: Failures before opening circuit (default: 5)
            circuit_breaker_recovery_timeout: Seconds before attempting recovery (default: 60.0)
        """
        self.base_url = base_url.rstrip("/")
        self.runtime_id = runtime_id
        self._auth_type = auth_type.lower()
        self._timeout = timeout
        self._verify_ssl = verify_ssl

        # Store auth credentials for token refresh
        self._api_key = api_key
        self._client_id = client_id
        self._bearer_token: Optional[str] = None
        self._token_expires_at: Optional[float] = None

        # Build initial headers based on auth type
        headers = {"Content-Type": "application/json"}
        
        if self._auth_type == "basic":
            if not username or not password:
                raise ValueError("Username and password required for basic authentication")
            # Create Basic Auth header
            credentials = f"{username}:{password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded_credentials}"
        elif self._auth_type == "apikey":
            if not api_key or not client_id:
                raise ValueError("API key and client ID required for API key authentication")
            # For API key auth, we'll fetch bearer token before first request
            # Don't set Authorization header yet - will be set after token fetch
            pass
        else:
            raise ValueError(f"Invalid auth_type '{auth_type}'. Must be 'basic' or 'apikey'")

        self._http_client = httpx.AsyncClient(timeout=timeout, headers=headers, verify=verify_ssl)
        self._endpoint = f"{self.base_url}{FAMEndpoints.SERVERS_BASE.format(runtime_id=self.runtime_id)}"

        # Initialize circuit breaker
        self._circuit_breaker_enabled = circuit_breaker_enabled
        if circuit_breaker_enabled:
            self._circuit_breaker = CircuitBreaker(failure_threshold=circuit_breaker_failure_threshold, recovery_timeout=circuit_breaker_recovery_timeout, success_threshold=2, timeout=float(timeout))
            logger.info(f"Circuit breaker enabled: failure_threshold={circuit_breaker_failure_threshold}, " f"recovery_timeout={circuit_breaker_recovery_timeout}s")
        else:
            self._circuit_breaker = None
            logger.info("Circuit breaker disabled")

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._http_client:
            await self._http_client.aclose()

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get current authentication headers.
        
        Returns:
            Dictionary with Authorization header (and Content-Type)
        """
        headers = {"Content-Type": "application/json"}
        
        if self._auth_type == "apikey" and self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        # For basic auth, headers are already set in the client
        
        return headers

    async def _fetch_bearer_token(self) -> bool:
        """Fetch bearer token for API key authentication.
        
        Returns:
            True if token was successfully fetched, False otherwise
        """
        if self._auth_type != "apikey":
            return True  # Not needed for basic auth
            
        try:
            token_url = f"{self.base_url}{FAMEndpoints.TOKEN}"
            
            # Ensure api_key and client_id are not None (validated in __init__)
            assert self._api_key is not None
            assert self._client_id is not None
            
            headers = {
                "X-APIKEY": self._api_key,
                "X-ClientID": self._client_id,
                "Content-Type": "application/json"
            }
            
            logger.debug(f"Fetching bearer token from {token_url}")
            
            # Use a temporary client for token fetch to avoid circular dependency
            # (main client needs token, but we need to fetch token first)
            async with httpx.AsyncClient(timeout=self._timeout, verify=self._verify_ssl) as temp_client:
                response = await temp_client.post(token_url, headers=headers, json={})
                response.raise_for_status()
                
                token_data = response.json()
                self._bearer_token = token_data.get("token")
                
                # expires_in is an epoch timestamp in milliseconds, convert to seconds
                expires_in_ms = token_data.get("expires_in")
                if expires_in_ms:
                    self._token_expires_at = expires_in_ms / 1000.0  # Convert ms to seconds
                else:
                    self._token_expires_at = None
            
            # Standard
            import time
            current_time = time.time()
            time_until_expiry = self._token_expires_at - current_time if self._token_expires_at else 0
            logger.info(f"Bearer token fetched successfully for API key authentication (expires_at={self._token_expires_at}, current_time={current_time}, valid_for={time_until_expiry:.0f}s)")
            return True
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch bearer token: status={e.response.status_code}, body={e.response.text}")
            return False
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching bearer token: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error fetching bearer token: {e}", exc_info=True)
            return False

    async def _ensure_valid_token(self) -> bool:
        """Ensure we have a valid bearer token for API key auth.
        
        Returns:
            True if token is valid or successfully refreshed, False otherwise
        """
        if self._auth_type != "apikey":
            return True  # Not needed for basic auth
            
        # Standard
        import time
        
        # Check if token exists and is not expired (refresh 5 minutes before expiry)
        # expires_at is an epoch timestamp in seconds
        if self._bearer_token and self._token_expires_at:
            current_time = time.time()
            time_until_expiry = self._token_expires_at - current_time
            
            # Add 5 minutes (300 seconds) buffer before expiry
            if time_until_expiry > 300:
                logger.debug(f"Bearer token still valid (time_left={time_until_expiry:.0f}s)")
                return True
            
            # Token expiring soon, refresh it
            logger.info(f"Bearer token expiring soon (current={current_time:.0f}, expires={self._token_expires_at:.0f}, time_left={time_until_expiry:.0f}s), refreshing")
        else:
            # Token missing or expired, fetch new one
            logger.info("Bearer token missing or not set, fetching new token")
        
        return await self._fetch_bearer_token()

    async def _call_with_circuit_breaker(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute function with circuit breaker protection if enabled.

        Args:
            func: Async function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function result

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: Original exception if circuit breaker disabled
        """
        if self._circuit_breaker_enabled and self._circuit_breaker:
            return await self._circuit_breaker.call(func, *args, **kwargs)
        else:
            # Circuit breaker disabled, call directly
            result = func(*args, **kwargs)
            # If result is awaitable, await it
            if hasattr(result, "__await__"):
                return await result
            return result

    async def _execute_with_error_handling(self, func: Callable[..., Any], operation_name: str, *args: Any, default_return: Any = None, **kwargs: Any) -> Any:
        """Execute function with standardized error handling and circuit breaker protection.

        This method provides a centralized error handling pattern for all IBM API Connect Federated API Management API calls:
        - Token validity check (for API key auth)
        - Circuit breaker protection (if enabled)
        - HTTP status error handling with detailed logging
        - HTTP error handling (connection, timeout, etc.)
        - Generic exception handling with stack trace

        Args:
            func: Async function to execute
            operation_name: Human-readable operation name for logging (e.g., "creating server", "sending heartbeat")
            default_return: Value to return on error (default: None)
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function result on success, default_return on error
        """
        try:
            # Ensure valid token for API key auth
            if not await self._ensure_valid_token():
                logger.error(f"Failed to obtain valid bearer token for {operation_name}")
                return default_return

            # Execute with circuit breaker protection
            return await self._call_with_circuit_breaker(func, *args, **kwargs)

        except httpx.HTTPStatusError as e:
            logger.error(f"IBM API Connect Federated API Management API error {operation_name}: " f"status={e.response.status_code}, body={e.response.text}")
            return default_return

        except httpx.HTTPError as e:
            logger.error(f"HTTP error {operation_name}: {e}")
            return default_return

        except CircuitBreakerError as e:
            logger.error(f"Circuit breaker open {operation_name}: {e}")
            return default_return

        except Exception as e:
            logger.error(f"Unexpected error {operation_name}: {e}", exc_info=True)
            return default_return

    def get_circuit_breaker_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics.

        Returns:
            Dictionary with circuit breaker state and statistics:
            - enabled: Whether circuit breaker is enabled
            - state: Current state (CLOSED, OPEN, HALF_OPEN)
            - failure_count: Current failure count
            - success_count: Current success count in half-open state
            - last_failure_time: Timestamp of last failure (None if no failures)
            - failure_threshold: Configured failure threshold
            - recovery_timeout: Configured recovery timeout in seconds
            - success_threshold: Configured success threshold for recovery
        """
        if not self._circuit_breaker_enabled or not self._circuit_breaker:
            return {
                "enabled": False,
                "state": "N/A",
                "failure_count": 0,
                "success_count": 0,
                "last_failure_time": None,
                "failure_threshold": 0,
                "recovery_timeout": 0.0,
                "success_threshold": 0,
            }

        return {
            "enabled": True,
            "state": self._circuit_breaker.state.value,
            "failure_count": self._circuit_breaker.failure_count,
            "success_count": self._circuit_breaker.success_count,
            "last_failure_time": self._circuit_breaker.last_failure_time,
            "failure_threshold": self._circuit_breaker.failure_threshold,
            "recovery_timeout": self._circuit_breaker.recovery_timeout,
            "success_threshold": self._circuit_breaker.success_threshold,
        }

    async def create_runtime_type(self, runtime_type_id: str, runtime_type_name: str) -> bool:
        """Create a new runtime type in FAM.

        POST /api/assetcatalog/v1/runtimes/types

        Args:
            runtime_type_id: Runtime type ID (e.g., "MCP_CONTEXT_FORGE")
            runtime_type_name: Runtime type display name (e.g., "MCP Context Forge")

        Returns:
            True if creation succeeded, False otherwise
        """
        try:
            # Ensure valid token for API key auth
            if not await self._ensure_valid_token():
                logger.error(f"Failed to obtain valid bearer token for creating runtime type '{runtime_type_id}'")
                return False

            endpoint = f"{self.base_url}{FAMEndpoints.RUNTIME_TYPES}"
            payload = {"id": runtime_type_id, "name": runtime_type_name, "capabilities": ["AI"]}

            logger.info(f"Creating runtime type '{runtime_type_name}' (ID: {runtime_type_id}) at {endpoint}")
            response = await self._http_client.post(endpoint, json=payload, headers=self._get_auth_headers())

            if response.status_code in (200, 201):
                logger.info(f"Successfully created runtime type '{runtime_type_name}' (ID: {runtime_type_id})")
                return True
            else:
                logger.error(f"Failed to create runtime type: status={response.status_code}, body={response.text}")
                return False

        except httpx.HTTPError as e:
            logger.error(f"HTTP error creating runtime type '{runtime_type_id}': {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error creating runtime type '{runtime_type_id}': {e}", exc_info=True)
            return False

    async def register_runtime(
        self,
        name: str,
        description: str,
        runtime_type: str,
        deployment_type: str = FAMRuntimePayload.DEPLOYMENT_ON_PREMISE,
        region: Optional[str] = None,
        location: Optional[str] = None,
        host: Optional[str] = None,
        tags: Optional[List[str]] = None,
        capacity_value: Optional[str] = None,
        capacity_unit: Optional[str] = None,
        heartbeat_interval: int = 6000,
        publish_assets: bool = True,
        sync_assets: bool = True,
        send_metrics: bool = True,
    ) -> Optional[ReregistrationReport]:
        """Register or update runtime in IBM API Connect Federated API Management Asset Catalog API v2.

        POST /api/assetcatalog/v2/runtimes

        Args:
            name: Runtime display name
            description: Runtime description
            runtime_type: Runtime type
            deployment_type: Deployment type (default: ON_PREMISE)
            region: Region identifier (e.g., "us-east-1")
            location: Location description (e.g., "US East")
            host: Host identifier
            tags: List of tags for the runtime
            capacity_value: Capacity value (e.g., "50")
            capacity_unit: Capacity unit (e.g., "per minute")
            heartbeat_interval: Heartbeat sync interval in seconds
            publish_assets: Whether to publish assets to IBM API Connect Federated API Management (default: True)
            sync_assets: Whether to sync assets from IBM API Connect Federated API Management (default: True)
            send_metrics: Whether to send metrics to IBM API Connect Federated API Management (default: True)

        Returns:
            ReregistrationReport with runtime ID and last sync timestamps if successful, None otherwise
        """

        async def _do_register() -> httpx.Response:
            """Internal method to perform registration HTTP call."""
            # Build runtime registration payload with runtime ID
            payload = FAMRuntimePayload.build_payload(
                runtime_id=self.runtime_id,
                name=name,
                description=description,
                runtime_type=runtime_type,
                deployment_type=deployment_type,
                region=region,
                location=location,
                host=host,
                tags=tags,
                capacity_value=capacity_value,
                capacity_unit=capacity_unit,
                heartbeat_interval=heartbeat_interval,
                publish_assets=publish_assets,
                sync_assets=sync_assets,
                send_metrics=send_metrics,
            )

            # POST to API v2 runtime endpoint
            endpoint = f"{self.base_url}{FAMEndpoints.RUNTIMES}"
            logger.info(f"Registering runtime '{name}' at {endpoint}")
            return await self._http_client.post(endpoint, json=payload, headers=self._get_auth_headers())

        try:
            # Ensure valid token for API key auth
            if not await self._ensure_valid_token():
                logger.error(f"Failed to obtain valid bearer token for registering runtime '{name}'")
                return None

            # Execute with circuit breaker protection
            response = await self._call_with_circuit_breaker(_do_register)

            # Handle status codes:
            # 201 = Created (first-time registration) - returns Runtime object
            # 200 = OK (re-registration) - returns ReregistrationReport
            # 409 = Conflict (runtime already exists) - returns ReregistrationReport
            status_code = response.status_code

            if status_code not in (200, 201, 409):
                response.raise_for_status()

            response_data = response.json()

            if status_code == 201:
                # 201 Created: Response is a Runtime object
                # Extract runtime ID from the Runtime object
                runtime_id_from_response = response_data.get("id")
                if runtime_id_from_response:
                    self.runtime_id = runtime_id_from_response
                    logger.debug(f"Runtime ID from 201 response: {runtime_id_from_response}")

                # Create ReregistrationReport with no timestamps (first registration)
                report = ReregistrationReport(
                    runtime_id=self.runtime_id,
                    status_code=status_code,
                    last_registration_time=None,
                    last_heartbeat_time=None,
                    last_metrics_time=None,
                    last_asset_sync_time=None,
                )
                logger.info(f"Successfully created runtime '{name}' with ID: {self.runtime_id}, " f"status: 201 (Created - first-time registration)")
            else:
                # 200/409: Response is a ReregistrationReport
                # Extract runtime ID from the report's runtime object
                runtime_obj = response_data.get("runtime", {})
                runtime_id_from_response = runtime_obj.get("id")

                if runtime_id_from_response:
                    self.runtime_id = runtime_id_from_response
                    logger.debug(f"Runtime ID from {status_code} response: {runtime_id_from_response}")

                # Parse re-registration report (timestamps of last sync operations)
                report = ReregistrationReport(
                    runtime_id=self.runtime_id,
                    status_code=status_code,
                    last_registration_time=response_data.get("lastRegistrationTime"),
                    last_heartbeat_time=response_data.get("lastHeartbeatTime"),
                    last_metrics_time=response_data.get("lastMetricsTime"),
                    last_asset_sync_time=response_data.get("lastAssetSyncTime"),
                )

                status_msg = "OK (re-registration)" if status_code == 200 else "Conflict (runtime already exists - treated as re-registration)"
                logger.info(f"Successfully re-registered runtime '{name}' with ID: {self.runtime_id}, " f"status: {status_code} ({status_msg}), report: {report.model_dump()}")

            return report

        except CircuitBreakerError as e:
            logger.error(f"Circuit breaker open, cannot register runtime '{name}': {e}")
            return None
        except httpx.HTTPStatusError as e:
            # Check if error is "Runtime type does not exists"
            error_body = e.response.text
            if e.response.status_code == 400 and "Runtime type does not exists" in error_body:
                logger.warning(f"Runtime type '{runtime_type}' does not exist in FAM, attempting to create it...")

                # Attempt to create the runtime type
                type_created = await self.create_runtime_type(runtime_type_id=runtime_type, runtime_type_name="MCP Context Forge")

                if type_created:
                    logger.info(f"Successfully created runtime type '{runtime_type}', retrying registration...")
                    # Retry registration after creating the runtime type
                    return await self.register_runtime(
                        name=name,
                        description=description,
                        runtime_type=runtime_type,
                        deployment_type=deployment_type,
                        region=region,
                        location=location,
                        host=host,
                        tags=tags,
                        capacity_value=capacity_value,
                        capacity_unit=capacity_unit,
                        heartbeat_interval=heartbeat_interval,
                        publish_assets=publish_assets,
                        sync_assets=sync_assets,
                        send_metrics=send_metrics,
                    )
                else:
                    logger.error(f"Failed to create runtime type '{runtime_type}', cannot register runtime")
                    return None

            logger.error(f"IBM API Connect Federated API Management API error registering runtime '{name}': " f"status={e.response.status_code}, body={error_body}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"HTTP error registering runtime '{name}': {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error registering runtime '{name}': {e}")
            return None

    async def send_heartbeat(self, runtime_id: str) -> bool:
        """Send heartbeat for runtime to IBM API Connect Federated API Management Asset Catalog API v2.

        POST /api/engine/v2/runtimes/heartbeat

        Args:
            runtime_id: Runtime ID to send heartbeat for

        Returns:
            True if successful, False otherwise
        """

        async def _do_heartbeat() -> bool:
            # Standard
            import time

            payload = {"created": int(time.time() * 1000), "runtimeId": runtime_id}
            endpoint = f"{self.base_url}{FAMEndpoints.HEARTBEAT}"
            response = await self._http_client.post(endpoint, json=payload, headers=self._get_auth_headers())
            response.raise_for_status()
            logger.debug(f"Heartbeat sent successfully for runtime {runtime_id}")
            return True

        return await self._execute_with_error_handling(_do_heartbeat, f"sending heartbeat for runtime {runtime_id}", default_return=False)

    async def create_server(self, server: Any) -> bool:
        """Create MCP Server in IBM API Connect Federated API Management.

        POST /api/assetcatalog/v1/runtimes/{runtimeId}/mcp-servers

        Args:
            server: ContextForge Server ORM object

        Returns:
            True if successful (including 409 Conflict - server already exists), False otherwise
        """

        async def _do_create() -> bool:
            payload = FAMServerPayload.build_create_payload(server)
            response = await self._http_client.post(self._endpoint, json=payload, headers=self._get_auth_headers())

            # Handle 409 Conflict as success (server already exists in IBM API Connect Federated API Management)
            if response.status_code == 409:
                logger.info(f"Server {server.id} already exists in IBM API Connect Federated API Management (409 Conflict - treated as success)")
                return True

            response.raise_for_status()
            logger.info(f"Created MCP Server {server.id} in IBM API Connect Federated API Management")
            return True

        return await self._execute_with_error_handling(_do_create, f"creating server {server.id}", default_return=False)

    async def update_server(self, server: Any) -> bool:
        """Update MCP Server in IBM API Connect Federated API Management.

        PUT /api/assetcatalog/v1/runtimes/{runtimeId}/mcp-servers/{id}

        Args:
            server: ContextForge Server ORM object

        Returns:
            True if successful, False otherwise
        """

        async def _do_update() -> bool:
            url = f"{self._endpoint}/{server.id}"
            payload = FAMServerPayload.build_update_payload(server)
            response = await self._http_client.put(url, json=payload, headers=self._get_auth_headers())
            response.raise_for_status()
            logger.info(f"Updated MCP Server {server.id} in IBM API Connect Federated API Management")
            return True

        return await self._execute_with_error_handling(_do_update, f"updating server {server.id}", default_return=False)

    async def delete_server(self, server_id: str) -> bool:
        """Delete MCP Server from IBM API Connect Federated API Management.

        DELETE /api/assetcatalog/v1/runtimes/{runtimeId}/mcp-servers/{id}

        Args:
            server_id: Server identifier

        Returns:
            True if successful, False otherwise
        """

        async def _do_delete() -> bool:
            url = f"{self._endpoint}/{server_id}"
            response = await self._http_client.delete(url, headers=self._get_auth_headers())

            # 404 is acceptable for delete (already deleted)
            if response.status_code == 404:
                logger.info(f"Server {server_id} not found in IBM API Connect Federated API Management (already deleted)")
                return True

            response.raise_for_status()
            logger.info(f"Deleted MCP Server {server_id} from IBM API Connect Federated API Management")
            return True

        return await self._execute_with_error_handling(_do_delete, f"deleting server {server_id}", default_return=False)

    async def bulk_create_tools(self, tools: List[Any], server_id: str) -> Optional[str]:
        """Bulk create MCP Tools in IBM API Connect Federated API Management.

        POST /api/assetcatalog/v1/runtimes/{runtimeId}/mcp-servers/{mcpServerId}/mcp-tools/bulk/create

        Args:
            tools: List of ContextForge Tool ORM objects
            server_id: Parent MCP Server ID

        Returns:
            Job ID if successful, None otherwise
        """

        async def _do_bulk_create() -> Optional[str]:
            url = f"{self._endpoint}/{server_id}/mcp-tools/bulk/create"
            payloads = [FAMToolPayload.build_create_payload(tool, server_id) for tool in tools]
            response = await self._http_client.post(url, json=payloads, headers=self._get_auth_headers())
            response.raise_for_status()

            if response.status_code == 202:
                job_data = response.json()
                job_id = job_data.get("jobId")
                logger.info(f"Bulk create job submitted for {len(tools)} tools (server: {server_id}, job: {job_id})")
                return job_id
            else:
                logger.warning(f"Unexpected status code {response.status_code} for bulk create")
                return None

        return await self._execute_with_error_handling(_do_bulk_create, f"bulk creating {len(tools)} tools", default_return=None)

    async def bulk_update_tools(self, tools: List[Any], server_id: str) -> Optional[str]:
        """Bulk update MCP Tools in IBM API Connect Federated API Management.

        POST /api/assetcatalog/v1/runtimes/{runtimeId}/mcp-servers/{mcpServerId}/mcp-tools/bulk/update

        Args:
            tools: List of ContextForge Tool ORM objects
            server_id: Parent MCP Server ID

        Returns:
            Job ID if successful, None otherwise
        """

        async def _do_bulk_update() -> Optional[str]:
            url = f"{self._endpoint}/{server_id}/mcp-tools/bulk/update"
            payloads = [FAMToolPayload.build_update_payload(tool) for tool in tools]
            response = await self._http_client.post(url, json=payloads, headers=self._get_auth_headers())
            response.raise_for_status()

            if response.status_code == 202:
                job_data = response.json()
                job_id = job_data.get("jobId")
                logger.info(f"Bulk update job submitted for {len(tools)} tools (server: {server_id}, job: {job_id})")
                return job_id
            else:
                logger.warning(f"Unexpected status code {response.status_code} for bulk update")
                return None

        return await self._execute_with_error_handling(_do_bulk_update, f"bulk updating {len(tools)} tools", default_return=None)

    async def bulk_delete_tools(self, tool_ids: List[str], server_id: str) -> Optional[str]:
        """Bulk delete MCP Tools from IBM API Connect Federated API Management.

        POST /api/assetcatalog/v1/runtimes/{runtimeId}/mcp-servers/{mcpServerId}/mcp-tools/bulk/delete

        Args:
            tool_ids: List of tool identifiers
            server_id: Parent MCP Server ID

        Returns:
            Job ID if successful, None otherwise
        """

        async def _do_bulk_delete() -> Optional[str]:
            url = f"{self._endpoint}/{server_id}/mcp-tools/bulk/delete"
            response = await self._http_client.post(url, json=tool_ids, headers=self._get_auth_headers())
            response.raise_for_status()

            if response.status_code == 202:
                job_data = response.json()
                job_id = job_data.get("jobId")
                logger.info(f"Bulk delete job submitted for {len(tool_ids)} tools (server: {server_id}, job: {job_id})")
                return job_id
            else:
                logger.warning(f"Unexpected status code {response.status_code} for bulk delete")
                return None

        return await self._execute_with_error_handling(_do_bulk_delete, f"bulk deleting {len(tool_ids)} tools", default_return=None)

    async def submit_metrics(self, metrics_payload: Dict[str, Any]) -> bool:
        """Submit metrics to IBM API Connect Federated API Management.

        POST /api/engine/v3/runtimes/{runtimeId}/metrics

        Args:
            metrics_payload: AgentMetricsModel payload dict

        Returns:
            True if successful (202 Accepted), False otherwise
        """

        async def _do_submit_metrics() -> bool:
            metrics_url = f"{self.base_url}{FAMEndpoints.METRICS.format(runtime_id=self.runtime_id)}"
            response = await self._http_client.post(metrics_url, json=metrics_payload, headers=self._get_auth_headers())
            response.raise_for_status()

            # Metrics endpoint returns 202 Accepted
            if response.status_code == 202:
                logger.info(f"Successfully submitted metrics to IBM API Connect Federated API Management for runtime {self.runtime_id}")
                return True
            else:
                logger.warning(f"Unexpected status code {response.status_code} when submitting metrics")
                return False

        return await self._execute_with_error_handling(_do_submit_metrics, "submitting metrics", default_return=False)
