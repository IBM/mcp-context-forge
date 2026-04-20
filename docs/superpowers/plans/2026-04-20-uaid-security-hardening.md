# UAID Cross-Gateway Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden UAID cross-gateway routing security by implementing fail-closed domain allowlist default and bearer token forwarding for RBAC enforcement.

**Architecture:** Two-layer security - (1) fail-closed domain allowlist prevents SSRF, (2) bearer token forwarding preserves user RBAC context across gateway hops. Changes isolated to config.py, a2a_service.py, main.py, plus comprehensive test coverage.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy, pytest

---

## File Structure

### Files to Create
- `tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py` - New test file for security-specific tests
- `docs/security/uaid-cross-gateway-auth.md` - Security documentation

### Files to Modify
- `mcpgateway/config.py` - Add `uaid_allow_all_domains` and `uaid_forward_auth` fields, update descriptions
- `mcpgateway/services/a2a_service.py` - Add fail-closed gate, token forwarding, error handling
- `mcpgateway/main.py` - Add startup validation for allowlist configuration
- `.env.example` - Add new config fields with warnings
- `README.md` - Update UAID security section
- `CLAUDE.md` - Add security invariants
- `tests/unit/mcpgateway/test_config.py` - Add config default tests
- `tests/unit/mcpgateway/test_main.py` - Add startup validation test

---

## Task 1: Add Configuration Fields for Fail-Closed Allowlist

**Files:**
- Modify: `mcpgateway/config.py` (around line 580-590)
- Test: `tests/unit/mcpgateway/test_config.py`

- [ ] **Step 1: Write failing test for new config fields**

Add to `tests/unit/mcpgateway/test_config.py`:

```python
def test_uaid_allow_all_domains_defaults_false():
    """Verify UAID_ALLOW_ALL_DOMAINS defaults to False (secure default)."""
    settings = Settings()
    assert settings.uaid_allow_all_domains is False


def test_uaid_forward_auth_defaults_true():
    """Verify UAID_FORWARD_AUTH defaults to True (auth forwarding enabled)."""
    settings = Settings()
    assert settings.uaid_forward_auth is True


def test_uaid_allow_all_domains_can_be_enabled():
    """Verify UAID_ALLOW_ALL_DOMAINS can be explicitly enabled (dev mode)."""
    settings = Settings(uaid_allow_all_domains=True)
    assert settings.uaid_allow_all_domains is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/mcpgateway/test_config.py::test_uaid_allow_all_domains_defaults_false -v
pytest tests/unit/mcpgateway/test_config.py::test_uaid_forward_auth_defaults_true -v
pytest tests/unit/mcpgateway/test_config.py::test_uaid_allow_all_domains_can_be_enabled -v
```

Expected: FAIL with "AttributeError: 'Settings' object has no attribute 'uaid_allow_all_domains'"

- [ ] **Step 3: Add new configuration fields to config.py**

In `mcpgateway/config.py`, find the existing `uaid_allowed_domains` field (around line 581) and add the new fields immediately after:

```python
# Existing field - UPDATE DESCRIPTION
uaid_allowed_domains: List[str] = Field(
    default_factory=list,
    description=(
        "Domain allowlist for UAID cross-gateway routing. When not empty, only UAIDs with endpoints "
        "ending in these domains will be allowed for cross-gateway routing. "
        "Empty list = DENY all cross-gateway routing (fail-closed, secure default)."
    ),
)

# NEW FIELDS
uaid_allow_all_domains: bool = Field(
    default=False,
    description=(
        "DANGEROUS: Allow UAID cross-gateway routing to any domain. "
        "This bypasses domain allowlist validation and should NEVER be used in production. "
        "Only enable for development/testing."
    ),
)

uaid_forward_auth: bool = Field(
    default=True,
    description=(
        "Forward bearer tokens in cross-gateway UAID calls for RBAC enforcement on remote gateways. "
        "Requires both gateways to trust the same JWT issuer (shared JWT_SECRET_KEY or federated SSO)."
    ),
)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/mcpgateway/test_config.py::test_uaid_allow_all_domains_defaults_false -v
pytest tests/unit/mcpgateway/test_config.py::test_uaid_forward_auth_defaults_true -v
pytest tests/unit/mcpgateway/test_config.py::test_uaid_allow_all_domains_can_be_enabled -v
```

Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit configuration changes**

```bash
git add mcpgateway/config.py tests/unit/mcpgateway/test_config.py
git commit -s -m "feat(config): add UAID security config fields for fail-closed allowlist

Add uaid_allow_all_domains (default: false) and uaid_forward_auth (default: true).
Update uaid_allowed_domains description to reflect fail-closed behavior.

Related to #4236"
```

---

## Task 2: Implement Fail-Closed Domain Allowlist Enforcement

**Files:**
- Create: `tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py`
- Modify: `mcpgateway/services/a2a_service.py` (around line 2160-2165)

- [ ] **Step 1: Write failing tests for fail-closed behavior**

Create new test file `tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py`:

```python
"""UAID cross-gateway security tests.

Tests for fail-closed allowlist and authentication forwarding.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.services.a2a_service import A2AService


class TestUAIDFailClosedAllowlist:
    """Test fail-closed domain allowlist behavior."""

    @pytest.fixture
    def a2a_service(self):
        """Create A2AService instance for testing."""
        db = MagicMock()
        return A2AService(db)

    @pytest.mark.asyncio
    async def test_cross_gateway_routing_blocked_when_allowlist_empty_and_flag_false(
        self, a2a_service
    ):
        """Verify cross-gateway routing blocked when allowlist empty and allow_all false."""
        uaid = "uaid:aid:test123;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        parameters = {"query": "test"}

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings:
            mock_settings.uaid_allowed_domains = []
            mock_settings.uaid_allow_all_domains = False

            with pytest.raises(ValueError) as exc_info:
                await a2a_service._invoke_remote_agent(
                    uaid=uaid,
                    parameters=parameters,
                    interaction_type="query",
                    hop_count=0,
                )

            error_message = str(exc_info.value)
            assert "UAID_ALLOWED_DOMAINS not configured" in error_message
            assert "agent.example.com" in error_message

    @pytest.mark.asyncio
    async def test_cross_gateway_routing_allowed_when_flag_true(self, a2a_service):
        """Verify cross-gateway routing proceeds when allow_all flag true (dev mode)."""
        uaid = "uaid:aid:test123;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        parameters = {"query": "test"}

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings, \
             patch("mcpgateway.services.a2a_service.get_http_client") as mock_client, \
             patch("mcpgateway.services.a2a_service.logger") as mock_logger:

            mock_settings.uaid_allowed_domains = []
            mock_settings.uaid_allow_all_domains = True
            mock_settings.mcpgateway_a2a_default_timeout = 30

            # Mock HTTP response
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "success"}
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http_client

            result = await a2a_service._invoke_remote_agent(
                uaid=uaid,
                parameters=parameters,
                interaction_type="query",
                hop_count=0,
            )

            # Verify warning was logged about unsafe mode
            assert mock_logger.warning.called
            warning_message = mock_logger.warning.call_args[0][0]
            assert "UAID_ALLOW_ALL_DOMAINS=true" in warning_message
            assert "agent.example.com" in warning_message

            # Verify call proceeded
            assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_cross_gateway_routing_allowed_when_allowlist_configured(
        self, a2a_service
    ):
        """Verify existing allowlist behavior unchanged (backward compatibility)."""
        uaid = "uaid:aid:test123;registry=context-forge;proto=a2a;nativeId=agent.trusted.example.com"
        parameters = {"query": "test"}

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings, \
             patch("mcpgateway.services.a2a_service.get_http_client") as mock_client:

            mock_settings.uaid_allowed_domains = ["trusted.example.com"]
            mock_settings.uaid_allow_all_domains = False
            mock_settings.mcpgateway_a2a_default_timeout = 30

            # Mock HTTP response
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "success"}
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http_client

            result = await a2a_service._invoke_remote_agent(
                uaid=uaid,
                parameters=parameters,
                interaction_type="query",
                hop_count=0,
            )

            # Verify call proceeded (existing behavior)
            assert result == {"result": "success"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py::TestUAIDFailClosedAllowlist -v
```

Expected: FAIL - tests execute but assertions fail because fail-closed logic not implemented yet

- [ ] **Step 3: Implement fail-closed enforcement in _invoke_remote_agent**

In `mcpgateway/services/a2a_service.py`, find the `_invoke_remote_agent` method (around line 2160). Add fail-closed gate BEFORE the existing domain allowlist check:

```python
# Around line 2163, BEFORE the existing "Security: Validate endpoint against domain allowlist" comment

# ═══════════════════════════════════════════════════════════════════════════
# SECURITY: Fail-closed domain allowlist - deny if not configured
# ═══════════════════════════════════════════════════════════════════════════
allowed_domains = getattr(settings, "uaid_allowed_domains", [])
allow_all = getattr(settings, "uaid_allow_all_domains", False)

if not allowed_domains and not allow_all:
    raise ValueError(
        f"Cross-gateway routing to {endpoint!r} blocked: UAID_ALLOWED_DOMAINS not configured. "
        "Configure UAID_ALLOWED_DOMAINS with trusted domains or set UAID_ALLOW_ALL_DOMAINS=true (unsafe for production)."
    )

# If allow_all flag is true, skip domain validation entirely (dev mode)
if allow_all:
    logger.warning(
        f"⚠️  SECURITY: Cross-gateway routing to {endpoint!r} allowed via UAID_ALLOW_ALL_DOMAINS=true. "
        "This bypasses domain allowlist validation and should NEVER be used in production."
    )
    # Skip the existing domain validation block - set allowed_domains to empty
    # so the "if allowed_domains:" check below will be false
    allowed_domains = []

# Security: Validate endpoint against domain allowlist
# (Existing code continues here - the "if allowed_domains:" block around line 2164)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py::TestUAIDFailClosedAllowlist -v
```

Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit fail-closed enforcement**

```bash
git add mcpgateway/services/a2a_service.py tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py
git commit -s -m "feat(a2a): implement fail-closed domain allowlist for UAID routing

Block cross-gateway routing when allowlist empty unless UAID_ALLOW_ALL_DOMAINS=true.
Prevents SSRF by requiring explicit domain configuration.

Tests:
- Blocked when allowlist empty and flag false
- Allowed when flag true (with warning)
- Existing allowlist behavior unchanged

Related to #4236"
```

---

## Task 3: Implement Bearer Token Forwarding

**Files:**
- Modify: `tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py`
- Modify: `mcpgateway/services/a2a_service.py` (lines ~1715 and ~2069)

- [ ] **Step 1: Write failing tests for token forwarding**

Add to `tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py`:

```python
class TestUAIDBearerTokenForwarding:
    """Test bearer token forwarding for cross-gateway authentication."""

    @pytest.fixture
    def a2a_service(self):
        """Create A2AService instance for testing."""
        db = MagicMock()
        return A2AService(db)

    @pytest.mark.asyncio
    async def test_cross_gateway_call_forwards_bearer_token(self, a2a_service):
        """Verify Authorization header forwarded in outbound request."""
        uaid = "uaid:aid:test123;registry=context-forge;proto=a2a;nativeId=agent.trusted.example.com"
        parameters = {"query": "test"}
        test_token = "test-bearer-token-abc123"

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings, \
             patch("mcpgateway.services.a2a_service.get_http_client") as mock_client:

            mock_settings.uaid_allowed_domains = ["trusted.example.com"]
            mock_settings.uaid_allow_all_domains = False
            mock_settings.uaid_forward_auth = True
            mock_settings.mcpgateway_a2a_default_timeout = 30
            mock_settings.app_name = "gateway-test"

            # Mock HTTP response
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "success"}
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http_client

            await a2a_service._invoke_remote_agent(
                uaid=uaid,
                parameters=parameters,
                interaction_type="query",
                bearer_token=test_token,
                hop_count=0,
            )

            # Verify Authorization header was included
            call_kwargs = mock_http_client.post.call_args[1]
            headers = call_kwargs["headers"]
            assert "Authorization" in headers
            assert headers["Authorization"] == f"Bearer {test_token}"

    @pytest.mark.asyncio
    async def test_cross_gateway_call_with_no_token_logs_warning(self, a2a_service):
        """Verify backward compat: proceeds without token but logs warning."""
        uaid = "uaid:aid:test123;registry=context-forge;proto=a2a;nativeId=agent.trusted.example.com"
        parameters = {"query": "test"}

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings, \
             patch("mcpgateway.services.a2a_service.get_http_client") as mock_client, \
             patch("mcpgateway.services.a2a_service.logger") as mock_logger:

            mock_settings.uaid_allowed_domains = ["trusted.example.com"]
            mock_settings.uaid_allow_all_domains = False
            mock_settings.uaid_forward_auth = True
            mock_settings.mcpgateway_a2a_default_timeout = 30

            # Mock HTTP response
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "success"}
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http_client

            await a2a_service._invoke_remote_agent(
                uaid=uaid,
                parameters=parameters,
                interaction_type="query",
                bearer_token=None,  # No token
                hop_count=0,
            )

            # Verify warning logged
            assert mock_logger.warning.called
            warning_message = mock_logger.warning.call_args[0][0]
            assert "proceeding without authentication token" in warning_message.lower()

            # Verify no Authorization header
            call_kwargs = mock_http_client.post.call_args[1]
            headers = call_kwargs["headers"]
            assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_cross_gateway_call_includes_source_gateway_header(self, a2a_service):
        """Verify X-Contextforge-Source-Gateway header for audit trail."""
        uaid = "uaid:aid:test123;registry=context-forge;proto=a2a;nativeId=agent.trusted.example.com"
        parameters = {"query": "test"}

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings, \
             patch("mcpgateway.services.a2a_service.get_http_client") as mock_client:

            mock_settings.uaid_allowed_domains = ["trusted.example.com"]
            mock_settings.uaid_allow_all_domains = False
            mock_settings.mcpgateway_a2a_default_timeout = 30
            mock_settings.app_name = "gateway-primary"

            # Mock HTTP response
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "success"}
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http_client

            await a2a_service._invoke_remote_agent(
                uaid=uaid,
                parameters=parameters,
                interaction_type="query",
                user_email="user@example.com",
                hop_count=0,
            )

            # Verify audit headers
            call_kwargs = mock_http_client.post.call_args[1]
            headers = call_kwargs["headers"]
            assert "X-Contextforge-Source-Gateway" in headers
            assert headers["X-Contextforge-Source-Gateway"] == "gateway-primary"
            assert "X-Contextforge-Source-User" in headers
            assert headers["X-Contextforge-Source-User"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_cross_gateway_call_preserves_correlation_id(self, a2a_service):
        """Verify correlation ID forwarded for distributed tracing."""
        uaid = "uaid:aid:test123;registry=context-forge;proto=a2a;nativeId=agent.trusted.example.com"
        parameters = {"query": "test"}
        test_correlation_id = "corr-id-xyz789"

        with patch("mcpgateway.services.a2a_service.settings") as mock_settings, \
             patch("mcpgateway.services.a2a_service.get_http_client") as mock_client:

            mock_settings.uaid_allowed_domains = ["trusted.example.com"]
            mock_settings.uaid_allow_all_domains = False
            mock_settings.mcpgateway_a2a_default_timeout = 30

            # Mock HTTP response
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "success"}
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http_client

            # Pass correlation_id via span context (existing pattern)
            with patch("mcpgateway.services.a2a_service.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value.hex = test_correlation_id

                await a2a_service._invoke_remote_agent(
                    uaid=uaid,
                    parameters=parameters,
                    interaction_type="query",
                    hop_count=0,
                )

            # Verify correlation ID in headers (existing behavior - just verify not broken)
            call_kwargs = mock_http_client.post.call_args[1]
            headers = call_kwargs["headers"]
            assert "X-Contextforge-Correlation-ID" in headers
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py::TestUAIDBearerTokenForwarding -v
```

Expected: FAIL - tests run but token not forwarded, headers missing

- [ ] **Step 3: Add bearer_token parameter to _invoke_remote_agent signature**

In `mcpgateway/services/a2a_service.py`, find `_invoke_remote_agent` method signature (line ~2069) and add parameter:

```python
async def _invoke_remote_agent(
    self,
    uaid: str,
    parameters: Dict[str, Any],
    interaction_type: str = "query",
    *,
    bearer_token: Optional[str] = None,  # NEW parameter
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    token_teams: Optional[List[str]] = None,
    hop_count: int = 0,
) -> Dict[str, Any]:
    """Invoke agent on remote gateway via UAID cross-gateway routing.

    Args:
        uaid: Universal Agent ID with embedded routing metadata
        parameters: Parameters for the interaction
        interaction_type: Type of interaction
        bearer_token: Bearer token to forward for authentication (NEW)
        user_id: Identifier of the user initiating the call
        user_email: Email of the user initiating the call
        token_teams: Teams from JWT token
        hop_count: Current federation hop depth

    Returns:
        Agent response from remote gateway

    Raises:
        A2AAgentError: If routing fails or remote invocation fails
        ValueError: If UAID parsing fails or endpoint not allowed
    """
```

- [ ] **Step 4: Add token forwarding logic in _invoke_remote_agent**

In `mcpgateway/services/a2a_service.py`, find where headers are constructed for the outbound HTTP request (around line 2200+). Add token forwarding logic:

```python
# Build headers for cross-gateway request
headers = {
    "Content-Type": "application/json",
}

# Forward authentication for RBAC enforcement on remote gateway
if bearer_token and getattr(settings, "uaid_forward_auth", True):
    headers["Authorization"] = f"Bearer {bearer_token}"
    logger.debug("Cross-gateway call: forwarding bearer token for authentication")
else:
    if not bearer_token:
        # Backward compatibility: proceed without token but log warning
        logger.warning(
            f"Cross-gateway call to {endpoint} proceeding without authentication token. "
            "Remote gateway will process request as unauthenticated (public access only). "
            "Ensure remote gateway enforces AUTH_REQUIRED=true for security."
        )

# Add audit trail headers for cross-gateway requests
headers["X-Contextforge-Source-Gateway"] = getattr(settings, "app_name", "contextforge")
if user_email:
    # Include originating user for audit purposes (non-sensitive header)
    headers["X-Contextforge-Source-User"] = user_email

# Add correlation ID (existing pattern - preserve it)
# Note: correlation_id should already be defined from span context above
headers["X-Contextforge-Correlation-ID"] = correlation_id or str(uuid.uuid4())
```

- [ ] **Step 5: Extract bearer token in invoke_agent and pass to _invoke_remote_agent**

In `mcpgateway/services/a2a_service.py`, find the `invoke_agent` method where UAID routing is handled (around line 1715). Add token extraction:

```python
# Around line 1715, where UAID routing happens
if uaid_utils.is_uaid(agent_identifier):
    # Extract bearer token from request if available
    bearer_token = None
    if hasattr(request, "state") and hasattr(request.state, "bearer_token"):
        bearer_token = request.state.bearer_token

    return await self._invoke_remote_agent(
        uaid=agent_identifier,
        parameters=parameters,
        interaction_type=interaction_type,
        bearer_token=bearer_token,  # NEW: forward token
        user_id=user_id,
        user_email=user_email,
        token_teams=token_teams,
        hop_count=hop_count,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py::TestUAIDBearerTokenForwarding -v
```

Expected: PASS (all 4 tests)

- [ ] **Step 7: Commit token forwarding implementation**

```bash
git add mcpgateway/services/a2a_service.py tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py
git commit -s -m "feat(a2a): implement bearer token forwarding for cross-gateway auth

Forward user bearer tokens in UAID cross-gateway calls for RBAC enforcement.
Add audit trail headers (source gateway, source user, correlation ID).

Features:
- Authorization header forwarded when token available
- Backward compat: proceeds without token (logs warning)
- Audit trail: X-Contextforge-Source-Gateway, X-Contextforge-Source-User
- Configurable via UAID_FORWARD_AUTH (default: true)

Tests:
- Token forwarded in Authorization header
- Warning logged when no token
- Source gateway header included
- Correlation ID preserved

Related to #4236"
```

---

## Task 4: Add Error Handling for Authentication Failures

**Files:**
- Modify: `tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py`
- Modify: `mcpgateway/services/a2a_service.py` (around line 2250+)

- [ ] **Step 1: Write failing test for 401/403 error handling**

Add to `tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py`:

```python
@pytest.mark.asyncio
async def test_cross_gateway_call_401_raises_clear_error(self, a2a_service):
    """Verify clear error message when remote gateway returns 401."""
    uaid = "uaid:aid:test123;registry=context-forge;proto=a2a;nativeId=agent.trusted.example.com"
    parameters = {"query": "test"}

    with patch("mcpgateway.services.a2a_service.settings") as mock_settings, \
         patch("mcpgateway.services.a2a_service.get_http_client") as mock_client:

        mock_settings.uaid_allowed_domains = ["trusted.example.com"]
        mock_settings.uaid_allow_all_domains = False
        mock_settings.mcpgateway_a2a_default_timeout = 30

        # Mock 401 response
        mock_http_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_http_client.post = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_http_client

        # Import the exception class
        from mcpgateway.services.a2a_service import A2AAgentError

        with pytest.raises(A2AAgentError) as exc_info:
            await a2a_service._invoke_remote_agent(
                uaid=uaid,
                parameters=parameters,
                interaction_type="query",
                bearer_token="test-token",
                hop_count=0,
            )

        error_message = str(exc_info.value)
        assert "authentication failed" in error_message.lower()
        assert "401" in error_message
        assert "agent.trusted.example.com" in error_message or "trusted.example.com" in error_message


@pytest.mark.asyncio
async def test_cross_gateway_call_403_raises_clear_error(self, a2a_service):
    """Verify clear error message when remote gateway returns 403."""
    uaid = "uaid:aid:test123;registry=context-forge;proto=a2a;nativeId=agent.trusted.example.com"
    parameters = {"query": "test"}

    with patch("mcpgateway.services.a2a_service.settings") as mock_settings, \
         patch("mcpgateway.services.a2a_service.get_http_client") as mock_client:

        mock_settings.uaid_allowed_domains = ["trusted.example.com"]
        mock_settings.uaid_allow_all_domains = False
        mock_settings.mcpgateway_a2a_default_timeout = 30

        # Mock 403 response
        mock_http_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_http_client.post = AsyncMock(return_value=mock_response)
        mock_client.return_value = mock_http_client

        from mcpgateway.services.a2a_service import A2AAgentError

        with pytest.raises(A2AAgentError) as exc_info:
            await a2a_service._invoke_remote_agent(
                uaid=uaid,
                parameters=parameters,
                interaction_type="query",
                bearer_token="test-token",
                hop_count=0,
            )

        error_message = str(exc_info.value)
        assert "authentication failed" in error_message.lower() or "forbidden" in error_message.lower()
        assert "403" in error_message
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py::test_cross_gateway_call_401_raises_clear_error -v
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py::test_cross_gateway_call_403_raises_clear_error -v
```

Expected: FAIL - tests run but 401/403 not handled with clear error

- [ ] **Step 3: Add auth failure error handling in _invoke_remote_agent**

In `mcpgateway/services/a2a_service.py`, find the response handling code in `_invoke_remote_agent` (after the HTTP request is made, around line 2250+). Add 401/403 handling BEFORE the existing error handling:

```python
# After receiving HTTP response, before existing error handling
if status_code in (401, 403):
    error_msg = (
        f"Cross-gateway authentication failed: remote gateway returned {status_code}. "
        f"Verify both gateways trust the same JWT issuer (shared JWT_SECRET_KEY or federated SSO). "
        f"Endpoint: {endpoint}"
    )
    raise A2AAgentError(
        agent_name=uaid,
        message=error_msg,
        status_code=status_code,
    )

# Existing error handling continues here...
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py::test_cross_gateway_call_401_raises_clear_error -v
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py::test_cross_gateway_call_403_raises_clear_error -v
```

Expected: PASS (both tests)

- [ ] **Step 5: Commit error handling**

```bash
git add mcpgateway/services/a2a_service.py tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py
git commit -s -m "feat(a2a): add clear error handling for auth failures in cross-gateway calls

Raise A2AAgentError with actionable message when remote gateway returns 401/403.
Error message includes troubleshooting guidance about JWT trust configuration.

Tests:
- 401 returns clear auth failure message
- 403 returns clear forbidden message

Related to #4236"
```

---

## Task 5: Add Startup Validation for Empty Allowlist

**Files:**
- Modify: `mcpgateway/main.py` (after app initialization, around line 200+)
- Modify: `tests/unit/mcpgateway/test_main.py`

- [ ] **Step 1: Write failing test for startup validation**

Add to `tests/unit/mcpgateway/test_main.py`:

```python
def test_startup_warns_when_uaid_allowlist_empty():
    """Verify ERROR logged when A2A enabled but UAID allowlist empty."""
    from unittest.mock import patch, MagicMock

    with patch("mcpgateway.main.logger") as mock_logger, \
         patch("mcpgateway.main.settings") as mock_settings, \
         patch("mcpgateway.main.FastAPI"):

        mock_settings.a2a_enabled = True
        mock_settings.uaid_allowed_domains = []
        mock_settings.uaid_allow_all_domains = False

        # Import and trigger the validation logic
        # (This test will need to call the validation function once it exists)
        from mcpgateway.main import validate_uaid_security_config
        validate_uaid_security_config()

        # Verify ERROR was logged
        assert mock_logger.error.called
        error_message = mock_logger.error.call_args[0][0]
        assert "UAID cross-gateway routing is DISABLED" in error_message
        assert "UAID_ALLOWED_DOMAINS" in error_message


def test_startup_no_warning_when_allowlist_configured():
    """Verify no warning when allowlist properly configured."""
    from unittest.mock import patch, MagicMock

    with patch("mcpgateway.main.logger") as mock_logger, \
         patch("mcpgateway.main.settings") as mock_settings:

        mock_settings.a2a_enabled = True
        mock_settings.uaid_allowed_domains = ["trusted.example.com"]
        mock_settings.uaid_allow_all_domains = False

        from mcpgateway.main import validate_uaid_security_config
        validate_uaid_security_config()

        # Verify no ERROR logged
        assert not mock_logger.error.called


def test_startup_no_warning_when_a2a_disabled():
    """Verify no warning when A2A not enabled."""
    from unittest.mock import patch, MagicMock

    with patch("mcpgateway.main.logger") as mock_logger, \
         patch("mcpgateway.main.settings") as mock_settings:

        mock_settings.a2a_enabled = False
        mock_settings.uaid_allowed_domains = []
        mock_settings.uaid_allow_all_domains = False

        from mcpgateway.main import validate_uaid_security_config
        validate_uaid_security_config()

        # Verify no ERROR logged
        assert not mock_logger.error.called
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/mcpgateway/test_main.py::test_startup_warns_when_uaid_allowlist_empty -v
pytest tests/unit/mcpgateway/test_main.py::test_startup_no_warning_when_allowlist_configured -v
pytest tests/unit/mcpgateway/test_main.py::test_startup_no_warning_when_a2a_disabled -v
```

Expected: FAIL with "ImportError: cannot import name 'validate_uaid_security_config'"

- [ ] **Step 3: Implement startup validation in main.py**

In `mcpgateway/main.py`, add validation function and call it during startup:

```python
# Add this function near the top of the file, after imports
def validate_uaid_security_config() -> None:
    """Validate UAID security configuration at startup.

    Logs ERROR if A2A enabled but UAID allowlist not configured,
    alerting operators to security misconfiguration.
    """
    if settings.a2a_enabled:
        if not settings.uaid_allowed_domains and not settings.uaid_allow_all_domains:
            logger.error(
                "🚨 SECURITY: UAID cross-gateway routing is DISABLED. "
                "Configure UAID_ALLOWED_DOMAINS with trusted domains or set UAID_ALLOW_ALL_DOMAINS=true (unsafe for production). "
                "Cross-gateway UAID calls will fail until allowlist is configured."
            )


# Find the app initialization section (search for "app = FastAPI" or lifespan manager)
# Add validation call after app is created but before startup completes
# This is typically in the startup event handler or after app = FastAPI(...)

# Example location (adjust to actual code structure):
@app.on_event("startup")
async def startup_event():
    """Application startup tasks."""
    # ... existing startup code ...

    # Validate UAID security configuration
    validate_uaid_security_config()

    # ... rest of startup code ...
```

**Note:** The exact placement depends on the existing startup structure in main.py. Find where other startup validations or checks are performed and add the call there.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/mcpgateway/test_main.py::test_startup_warns_when_uaid_allowlist_empty -v
pytest tests/unit/mcpgateway/test_main.py::test_startup_no_warning_when_allowlist_configured -v
pytest tests/unit/mcpgateway/test_main.py::test_startup_no_warning_when_a2a_disabled -v
```

Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit startup validation**

```bash
git add mcpgateway/main.py tests/unit/mcpgateway/test_main.py
git commit -s -m "feat(startup): add UAID security configuration validation

Log ERROR at startup if A2A enabled but UAID_ALLOWED_DOMAINS not configured.
Alerts operators to security misconfiguration before first cross-gateway call fails.

Tests:
- ERROR logged when allowlist empty and A2A enabled
- No warning when allowlist configured
- No warning when A2A disabled

Related to #4236"
```

---

## Task 6: Update Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Create: `docs/security/uaid-cross-gateway-auth.md`

- [ ] **Step 1: Update .env.example with new config fields**

Add to `.env.example` in the UAID configuration section (around line 85-125):

```bash
################################################################################
# UAID Cross-Gateway Routing Security
################################################################################

# Domain allowlist for UAID cross-gateway routing (REQUIRED for production)
# Empty list = DENY all cross-gateway routing (fail-closed, secure default)
# Example: UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]
UAID_ALLOWED_DOMAINS=[]

# DANGEROUS: Allow UAID routing to ANY domain (dev-only)
# ⚠️  WARNING: Setting this to true bypasses domain allowlist validation
# ⚠️  NEVER use in production - creates SSRF vulnerability
# Only enable for development/testing environments
UAID_ALLOW_ALL_DOMAINS=false

# Forward bearer tokens in cross-gateway UAID calls for RBAC enforcement
# When enabled, user authentication context is preserved across gateway hops
# Requires both gateways to trust the same JWT issuer (shared JWT_SECRET_KEY or federated SSO)
# Disable only if you have a different cross-gateway auth mechanism
UAID_FORWARD_AUTH=true
```

- [ ] **Step 2: Update README.md UAID section**

Find the UAID section in README.md and add security subsection:

```markdown
### UAID Security Configuration

**Production Requirements:**

Cross-gateway UAID routing requires explicit security configuration:

1. **Configure Domain Allowlist:**
   ```bash
   UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]
   ```

2. **Ensure JWT Trust:**
   - Both gateways must trust the same JWT issuer
   - Option A: Shared secret (same `JWT_SECRET_KEY` on all gateways)
   - Option B: Federated SSO (Google, GitHub, Entra ID)

3. **Enable Authentication:**
   ```bash
   AUTH_REQUIRED=true
   UAID_FORWARD_AUTH=true
   ```

**Authentication Flow:**

Cross-gateway calls forward the user's bearer token via the `Authorization` header.
Remote gateways validate tokens through existing auth middleware, preserving RBAC context.

**Security Features:**

- ✅ Fail-closed default: Empty allowlist blocks all cross-gateway routing
- ✅ Bearer token forwarding: User authentication preserved across hops
- ✅ Audit trail: Source gateway and user tracked in headers
- ✅ Clear error messages: Misconfigurations caught at startup and runtime

**Troubleshooting:**

- **"UAID_ALLOWED_DOMAINS not configured" error:** Add trusted domains to allowlist in .env
- **401/403 from remote gateway:** Verify both gateways trust same JWT issuer
- **"proceeding without authentication token" warning:** Check auth middleware extracts token to `request.state.bearer_token`

For detailed security architecture, see `docs/security/uaid-cross-gateway-auth.md`.
```

- [ ] **Step 3: Update CLAUDE.md Security Invariants**

Add to the Security Invariants section in CLAUDE.md:

```markdown
### UAID Cross-Gateway Security

- UAID cross-gateway routing requires explicit domain allowlist (fail-closed default)
- Empty `UAID_ALLOWED_DOMAINS` blocks all cross-gateway routing unless `UAID_ALLOW_ALL_DOMAINS=true`
- Cross-gateway calls forward bearer tokens for RBAC enforcement on remote gateways
- Both gateways must trust the same JWT issuer (shared `JWT_SECRET_KEY` or federated SSO)
- `UAID_ALLOW_ALL_DOMAINS=true` is unsafe for production (bypasses allowlist validation)
- Startup validation logs ERROR if A2A enabled but allowlist not configured
- Remote gateway 401/403 responses raise `A2AAgentError` with troubleshooting guidance
```

- [ ] **Step 4: Create comprehensive security documentation**

Create `docs/security/uaid-cross-gateway-auth.md`:

```markdown
# UAID Cross-Gateway Authentication & Security

This document describes the security architecture, trust model, and configuration for UAID cross-gateway routing.

## Overview

UAID (Universal Agent ID) enables zero-config cross-gateway routing by embedding endpoint and protocol information in the agent identifier. This document covers the security controls that protect cross-gateway communications.

## Security Layers

### Layer 1: Fail-Closed Domain Allowlist

**Purpose:** Prevent SSRF attacks by restricting which domains can be reached via cross-gateway routing.

**Configuration:**

```bash
# Required for production
UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]

# Default behavior (empty list)
UAID_ALLOWED_DOMAINS=[]  # DENIES all cross-gateway routing (fail-closed)

# Unsafe bypass (dev/testing only)
UAID_ALLOW_ALL_DOMAINS=true  # Allows routing to ANY domain
```

**Enforcement:**

1. **Startup Validation:** Logs ERROR if allowlist empty when A2A enabled
2. **Runtime Check:** Rejects cross-gateway calls if allowlist not configured
3. **Subdomain Matching:** Supports wildcard matching (e.g., `example.com` matches `agent.example.com`)

**Error Messages:**

```
Cross-gateway routing to 'agent.untrusted.com' blocked: UAID_ALLOWED_DOMAINS not configured.
Configure UAID_ALLOWED_DOMAINS with trusted domains or set UAID_ALLOW_ALL_DOMAINS=true (unsafe for production).
```

### Layer 2: Bearer Token Forwarding

**Purpose:** Preserve user authentication and RBAC context across gateway hops.

**Configuration:**

```bash
# Enable token forwarding (default: true)
UAID_FORWARD_AUTH=true

# Disable if using alternative auth mechanism
UAID_FORWARD_AUTH=false
```

**Authentication Flow:**

```
1. User authenticates to Gateway A → receives JWT token
2. User invokes UAID agent → Gateway A extracts token from request.state.bearer_token
3. Gateway A makes cross-gateway call → includes Authorization: Bearer <token>
4. Gateway B receives request → validates token via auth middleware
5. Gateway B enforces user's RBAC permissions → invokes agent
6. Response returns through Gateway A → forwarded to user
```

**Headers:**

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
X-Contextforge-Source-Gateway: gateway-primary
X-Contextforge-Source-User: user@example.com
X-Contextforge-Correlation-ID: corr-abc-123-xyz
```

## Trust Model

### Shared JWT Secret (Simple)

Both gateways use the same `JWT_SECRET_KEY`:

```bash
# Gateway A .env
JWT_SECRET_KEY=shared-secret-value-xyz

# Gateway B .env
JWT_SECRET_KEY=shared-secret-value-xyz
```

**Pros:**
- Simple to configure
- Works immediately
- No external dependencies

**Cons:**
- Key rotation requires coordination
- Single key compromise affects all gateways
- Not suitable for untrusted gateway federation

### Federated SSO (Recommended for Production)

Both gateways validate tokens from the same identity provider:

**Google Workspace:**
```bash
# Both gateways
SSO_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=your-secret
```

**GitHub:**
```bash
# Both gateways
SSO_GITHUB_CLIENT_ID=your-github-client-id
SSO_GITHUB_CLIENT_SECRET=your-github-secret
```

**Microsoft Entra ID (Azure AD):**
```bash
# Both gateways
SSO_ENTRA_CLIENT_ID=your-app-client-id
SSO_ENTRA_TENANT_ID=your-tenant-id
SSO_ENTRA_CLIENT_SECRET=your-secret
```

**Pros:**
- Centralized identity management
- Key rotation handled by IdP
- Works across organizational boundaries
- Supports conditional access policies

**Cons:**
- Requires IdP setup
- External dependency
- Token expiration considerations

## Configuration Examples

### Single Trust Domain (Shared Secret)

```bash
# Gateway A (gateway-primary.example.com)
A2A_ENABLED=true
AUTH_REQUIRED=true
JWT_SECRET_KEY=shared-secret-xyz-789
UAID_ALLOWED_DOMAINS=["gateway-secondary.example.com"]
UAID_FORWARD_AUTH=true

# Gateway B (gateway-secondary.example.com)
A2A_ENABLED=true
AUTH_REQUIRED=true
JWT_SECRET_KEY=shared-secret-xyz-789
UAID_ALLOWED_DOMAINS=["gateway-primary.example.com"]
UAID_FORWARD_AUTH=true
```

### Federated SSO (Google)

```bash
# Gateway A
A2A_ENABLED=true
AUTH_REQUIRED=true
SSO_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=your-google-secret
UAID_ALLOWED_DOMAINS=["gateway-b.partner.com"]
UAID_FORWARD_AUTH=true

# Gateway B (partner organization)
A2A_ENABLED=true
AUTH_REQUIRED=true
SSO_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
SSO_GOOGLE_CLIENT_SECRET=your-google-secret
UAID_ALLOWED_DOMAINS=["gateway-a.yourorg.com"]
UAID_FORWARD_AUTH=true
```

### Development/Testing (Unsafe)

```bash
# ⚠️  WARNING: Never use this in production
A2A_ENABLED=true
AUTH_REQUIRED=false  # UNSAFE: Disables auth entirely
UAID_ALLOW_ALL_DOMAINS=true  # UNSAFE: Allows routing to any domain
UAID_FORWARD_AUTH=false  # Optional: Disable if no auth available
```

## Troubleshooting

### Error: "UAID_ALLOWED_DOMAINS not configured"

**Symptom:** Cross-gateway calls fail immediately with configuration error.

**Cause:** Domain allowlist not configured (fail-closed default).

**Solution:**
```bash
# Add trusted domains to .env
UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]

# OR for dev/testing ONLY (unsafe)
UAID_ALLOW_ALL_DOMAINS=true
```

### Error: "Cross-gateway authentication failed: remote gateway returned 401"

**Symptom:** Remote gateway rejects request with 401 Unauthorized.

**Possible Causes:**

1. **JWT trust mismatch:**
   - Gateway A and B use different `JWT_SECRET_KEY`
   - Gateway B not configured for federated SSO
   - IdP configuration mismatch

   **Solution:** Verify both gateways trust same JWT issuer (shared key or SSO)

2. **Token expired:**
   - User token expired before cross-gateway call completed
   - Long-running operations hit token TTL

   **Solution:** Increase JWT expiration or implement token refresh

3. **Token not forwarded:**
   - `UAID_FORWARD_AUTH=false` on source gateway
   - Auth middleware not extracting token to `request.state.bearer_token`

   **Solution:** Enable `UAID_FORWARD_AUTH=true`, verify auth middleware

4. **Remote gateway requires auth:**
   - Gateway B has `AUTH_REQUIRED=true` but token validation fails

   **Solution:** Verify remote gateway auth configuration, check logs

### Warning: "proceeding without authentication token"

**Symptom:** Logged warning on cross-gateway calls, remote gateway receives unauthenticated request.

**Cause:** Source gateway did not extract bearer token from request.

**Solution:**

1. Verify auth middleware extracts token:
   ```python
   # Auth middleware should set:
   request.state.bearer_token = extracted_token
   ```

2. Check request has authentication:
   ```bash
   # User must be authenticated when making request
   curl -H "Authorization: Bearer <token>" ...
   ```

### Error: "Cross-gateway routing blocked: endpoint not in allowlist"

**Symptom:** Call fails with allowlist rejection.

**Cause:** UAID endpoint domain not in `UAID_ALLOWED_DOMAINS`.

**Solution:**
```bash
# Add the domain to allowlist
UAID_ALLOWED_DOMAINS=["trusted.example.com", "another-gateway.example.com"]

# UAID format must match:
# uaid:aid:hash;registry=X;proto=Y;nativeId=agent.trusted.example.com
#                                              ^^^^^ must be in allowlist
```

## Security Best Practices

1. **Always configure allowlist in production:**
   - Never use `UAID_ALLOW_ALL_DOMAINS=true` in production
   - Use specific domain names, not wildcard/CIDR ranges

2. **Use federated SSO when possible:**
   - Preferred over shared secrets for multi-org deployments
   - Enables centralized access control and audit

3. **Set appropriate token expiration:**
   - Minimum 1 hour for cross-gateway routing
   - Consider network latency and operation duration

4. **Monitor authentication failures:**
   - Alert on 401/403 spikes from cross-gateway calls
   - Investigate token validation errors

5. **Rotate shared secrets regularly:**
   - If using shared JWT secret, rotate quarterly
   - Coordinate rotation across all gateways

6. **Enable AUTH_REQUIRED on all gateways:**
   - Never expose gateways without authentication
   - Even "internal" gateways should enforce auth

## Future Enhancements

### Mutual TLS (mTLS)

**Timeline:** Week 4+

**Features:**
- Certificate-based gateway identity
- Cryptographic trust without shared secrets
- Certificate rotation support

**Configuration (planned):**
```bash
UAID_GATEWAY_CERT_PATH=/path/to/gateway.crt
UAID_GATEWAY_KEY_PATH=/path/to/gateway.key
UAID_GATEWAY_CA_PATH=/path/to/ca.crt
```

### Gateway Trust Token

**Timeline:** Future release

**Features:**
- HMAC-signed requests for gateway-to-gateway trust
- Works with mixed auth systems
- Per-gateway secret rotation

**Configuration (planned):**
```bash
UAID_GATEWAY_TRUST_TOKEN=gateway-shared-secret
```

### Gateway Registry

**Timeline:** Long-term roadmap

**Features:**
- Trusted gateway registry with public key verification
- HCS-14 compliant discovery
- Automatic allowlist population

## Related Documentation

- UAID Implementation: PR #4125
- Security Hardening: Issue #4236
- General Authentication: `docs/docs/manage/rbac.md`
- Multi-tenancy: `docs/docs/architecture/multitenancy.md`
```

- [ ] **Step 5: Commit documentation updates**

```bash
git add .env.example README.md CLAUDE.md docs/security/uaid-cross-gateway-auth.md
git commit -s -m "docs: update UAID security configuration documentation

Add comprehensive security documentation for cross-gateway routing:
- .env.example: New config fields with warnings
- README.md: Security requirements and troubleshooting
- CLAUDE.md: Security invariants for maintainers
- New: docs/security/uaid-cross-gateway-auth.md (complete guide)

Covers:
- Fail-closed allowlist configuration
- Bearer token forwarding setup
- Trust model (shared secret vs federated SSO)
- Configuration examples for different scenarios
- Troubleshooting guide for common issues

Related to #4236"
```

---

## Task 7: Run Full Test Suite and Verify

**Files:**
- All test files

- [ ] **Step 1: Run all UAID security tests**

```bash
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py -v
```

Expected: PASS (all 10 tests)

- [ ] **Step 2: Run all config tests**

```bash
pytest tests/unit/mcpgateway/test_config.py -v
```

Expected: PASS (including 3 new config tests)

- [ ] **Step 3: Run all main.py tests**

```bash
pytest tests/unit/mcpgateway/test_main.py -v
```

Expected: PASS (including 3 new startup validation tests)

- [ ] **Step 4: Run full A2A service test suite**

```bash
pytest tests/unit/mcpgateway/services/test_a2a_service.py -v
```

Expected: PASS (all 147+ existing tests still pass)

- [ ] **Step 5: Run complete test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: PASS (all tests pass, no regressions)

- [ ] **Step 6: Verify test coverage for new code**

```bash
pytest tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py --cov=mcpgateway.services.a2a_service --cov-report=term-missing
```

Expected: High coverage (>90%) for modified sections of a2a_service.py

---

## Task 8: Code Quality and Linting

**Files:**
- All modified Python files

- [ ] **Step 1: Run autoflake, isort, black**

```bash
make autoflake isort black
```

Expected: No changes (code should already be formatted correctly)

- [ ] **Step 2: Run pre-commit hooks**

```bash
make pre-commit
```

Expected: PASS (all hooks pass)

- [ ] **Step 3: Run ruff linter**

```bash
make ruff
```

Expected: No errors or warnings

- [ ] **Step 4: Run bandit security linter**

```bash
make bandit
```

Expected: No new security warnings (existing warnings are acceptable if already in codebase)

- [ ] **Step 5: Run pylint**

```bash
make pylint
```

Expected: 10.00/10 score (or match existing baseline)

- [ ] **Step 6: Run full verification**

```bash
make verify
```

Expected: PASS (all quality checks pass)

---

## Task 9: Manual Testing (Optional but Recommended)

**Files:**
- N/A (runtime testing)

- [ ] **Step 1: Start dev server with empty allowlist**

```bash
# Set environment
export A2A_ENABLED=true
export UAID_ALLOWED_DOMAINS=[]
export UAID_ALLOW_ALL_DOMAINS=false

# Start server
make dev
```

Expected: Server starts, ERROR log appears: "UAID cross-gateway routing is DISABLED"

- [ ] **Step 2: Test cross-gateway call fails with clear error**

```bash
# Create UAID agent (if not exists)
# Then try to invoke it

curl -X POST "http://localhost:4444/a2a/uaid:aid:test;registry=context-forge;proto=a2a;nativeId=agent.example.com/invoke" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interaction_type": "query", "parameters": {"query": "test"}}'
```

Expected: 400/500 error with message about "UAID_ALLOWED_DOMAINS not configured"

- [ ] **Step 3: Test bypass with UAID_ALLOW_ALL_DOMAINS=true**

```bash
# Set environment
export UAID_ALLOW_ALL_DOMAINS=true

# Restart server
make dev
```

Expected: No ERROR log at startup, cross-gateway calls proceed (with warning logged)

- [ ] **Step 4: Test with configured allowlist**

```bash
# Set environment
export UAID_ALLOWED_DOMAINS='["example.com"]'
export UAID_ALLOW_ALL_DOMAINS=false

# Restart server
make dev
```

Expected: No ERROR log at startup, calls to `*.example.com` succeed, others fail with allowlist error

---

## Task 10: Create Pull Request

**Files:**
- All modified files

- [ ] **Step 1: Review all changes**

```bash
git status
git diff main
```

Expected: Changes limited to config, a2a_service, main, tests, docs

- [ ] **Step 2: Verify commit messages**

```bash
git log --oneline origin/main..HEAD
```

Expected: 7 commits following conventional commit format

- [ ] **Step 3: Push branch to remote**

```bash
git push -u origin feat/uaid-security-hardening
```

- [ ] **Step 4: Create pull request**

```bash
gh pr create \
  --title "[SECURITY][ENHANCEMENT]: UAID Cross-Gateway Security Hardening - Auth Forwarding & Fail-Closed Allowlist" \
  --body-file - <<'EOF'
## Summary

Implements critical security hardening for UAID cross-gateway routing (issue #4236, PR #1):

1. **Fail-Closed Domain Allowlist**: Empty `UAID_ALLOWED_DOMAINS` now DENIES all cross-gateway routing (was: allow all)
2. **Bearer Token Forwarding**: User authentication preserved across gateway hops via `Authorization` header forwarding
3. **Startup Validation**: ERROR logged if A2A enabled but allowlist not configured
4. **Clear Error Messages**: Actionable guidance when cross-gateway calls fail (config, auth, allowlist)

## Changes

### Configuration (`mcpgateway/config.py`)
- Add `uaid_allow_all_domains` (default: false) - explicit opt-in to bypass allowlist
- Add `uaid_forward_auth` (default: true) - enable/disable token forwarding
- Update `uaid_allowed_domains` description for fail-closed behavior

### Security Enforcement (`mcpgateway/services/a2a_service.py`)
- Fail-closed gate: reject cross-gateway calls if allowlist empty (unless `UAID_ALLOW_ALL_DOMAINS=true`)
- Token extraction: extract bearer token from `request.state.bearer_token`
- Token forwarding: add `Authorization: Bearer <token>` header to outbound requests
- Audit trail: add `X-Contextforge-Source-Gateway`, `X-Contextforge-Source-User` headers
- Error handling: clear messages for 401/403 auth failures with troubleshooting guidance

### Startup Validation (`mcpgateway/main.py`)
- ERROR log if A2A enabled but allowlist empty and bypass flag false
- Alerts operators to misconfiguration before first cross-gateway call fails

### Documentation
- `.env.example`: Add new config fields with prominent warnings
- `README.md`: Security requirements, authentication flow, troubleshooting
- `CLAUDE.md`: Security invariants for maintainers
- `docs/security/uaid-cross-gateway-auth.md`: Comprehensive security guide (trust models, configuration examples, troubleshooting)

### Testing
- 10 new unit tests for fail-closed allowlist and token forwarding
- 3 new config tests for defaults
- 3 new startup validation tests
- All 147 existing A2A tests still pass

## Breaking Change

⚠️ **Operators must configure `UAID_ALLOWED_DOMAINS` before upgrading** ⚠️

Cross-gateway UAID routing will **stop working by default** after this update.

### Migration Required

Add to `.env` before upgrading:

```bash
# Production: Configure allowlist with trusted domains
UAID_ALLOWED_DOMAINS=["gateway1.example.com", "gateway2.example.com"]

# Dev/Testing ONLY: Bypass allowlist (UNSAFE for production)
UAID_ALLOW_ALL_DOMAINS=true
```

### JWT Trust Requirement

Both gateways must trust the same JWT issuer:
- **Option A**: Shared secret (same `JWT_SECRET_KEY`)
- **Option B**: Federated SSO (Google, GitHub, Entra ID)

## Testing

- ✅ All 10 new security tests pass
- ✅ All 147 existing A2A tests pass
- ✅ Config defaults validated
- ✅ Startup validation tested
- ✅ Code quality: pylint 10.00/10, ruff clean, bandit clean
- ✅ Manual testing: fail-closed enforcement verified, token forwarding verified

## Security Implications

**Prevents:**
- SSRF attacks via unrestricted cross-gateway routing
- RBAC bypass via unauthenticated cross-gateway calls
- Accidental routing to internal/untrusted endpoints

**Enables:**
- User authentication preserved across gateway federation
- Audit trail for cross-gateway actions
- Clear security configuration with safe defaults

## Related Issues

- Closes #4236 (PR #1 - Critical Security Fixes)
- Introduced in #4125 (UAID initial implementation)
- Follow-up: Observability/monitoring (future PR)

## Documentation

- Migration guide: See PR description above
- Security architecture: `docs/security/uaid-cross-gateway-auth.md`
- Configuration examples: See security doc for shared secret vs federated SSO
- Troubleshooting: See security doc for common issues

## Review Focus

1. **Breaking change communication**: Clear for operators?
2. **Error messages**: Actionable guidance?
3. **Test coverage**: Security scenarios adequately covered?
4. **Documentation**: Complete for different deployment scenarios?

EOF
```

- [ ] **Step 5: Link PR to issue**

Verify PR description includes "Closes #4236" for automatic issue linking.

- [ ] **Step 6: Request review**

Tag security-conscious team members and stakeholders for review.

---

## Checklist Summary

After completing all tasks, verify:

- [ ] All 16 new tests pass (10 security + 3 config + 3 startup)
- [ ] All 147+ existing A2A tests still pass
- [ ] Code quality checks pass (pylint 10.00/10, ruff clean)
- [ ] Documentation complete (.env.example, README, CLAUDE.md, security doc)
- [ ] Commit messages follow conventional commits
- [ ] PR created with clear breaking change warning
- [ ] Migration guide included in PR description

## Success Criteria

✅ **Fail-closed allowlist implemented**
- Empty `UAID_ALLOWED_DOMAINS` blocks cross-gateway routing
- `UAID_ALLOW_ALL_DOMAINS=true` provides explicit bypass
- Startup validation alerts operators

✅ **Bearer token forwarding implemented**
- `Authorization` header forwarded to remote gateways
- Audit trail headers included
- Clear error messages for auth failures

✅ **Backward compatibility maintained**
- Existing allowlist behavior unchanged (when configured)
- UUID-based agents work as before
- Graceful degradation when token unavailable

✅ **Production ready in 1 week**
- Implementation complete
- Comprehensive test coverage
- Documentation covers all scenarios
- Ready for security review
