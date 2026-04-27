# UAID Security Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DoS protection and comprehensive security documentation for UAID cross-gateway routing before merging PR #4125.

**Architecture:** Database schema update (String(512) → String(2048)), configurable length validation in UAID parser, comprehensive security warnings in documentation and code comments, test coverage from 91% → 93%+.

**Tech Stack:** Python 3.11+, SQLAlchemy, Alembic, pytest, Pydantic

---

## File Structure

**Files to Modify:**
- `mcpgateway/db.py` - Increase uaid column to String(2048)
- `mcpgateway/alembic/versions/d3e4f5a6b7c8_add_uaid_field_to_a2a_agents.py` - Update migration
- `mcpgateway/config.py` - Add uaid_max_length configuration field
- `mcpgateway/utils/uaid.py` - Add DoS protection validation
- `mcpgateway/services/a2a_service.py` - Enhanced security comments
- `README.md` - Add Security section
- `.env.example` - Comprehensive UAID security documentation
- `UAID_APPROACH_B_IMPLEMENTATION.md` - Security considerations section
- `tests/unit/mcpgateway/utils/test_uaid.py` - Add 4 DoS protection tests
- `tests/unit/mcpgateway/services/test_a2a_service.py` - Add 3 routing/access tests
- `license-policy.toml` - Potentially add base58 allowlist

**No files created** - all modifications to existing files in PR #4125.

---

## Task 1: Database Schema Update

**Files:**
- Modify: `mcpgateway/db.py:4766`

- [ ] **Step 1: Locate uaid column definition**

Open `mcpgateway/db.py` and navigate to line 4766 in the A2AAgent class:

```python
# Current line 4766:
uaid: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, comment="Full UAID string for UAID-based agents")
```

- [ ] **Step 2: Update column length to 2048**

Replace line 4766:

```python
uaid: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, comment="Full UAID string for UAID-based agents (max 2048 chars)")
```

**Rationale:** 2048 provides 2.2x headroom over calculated max UAID length (~900 chars) and aligns with cross-gateway routing from external gateways.

- [ ] **Step 3: Verify no syntax errors**

Run:
```bash
python -c "import mcpgateway.db; print('DB schema imports successfully')"
```

Expected: `DB schema imports successfully`

- [ ] **Step 4: Commit database schema change**

```bash
git add mcpgateway/db.py
git commit -m "feat: increase uaid column to String(2048) for DoS protection

- Update a2a_agents.uaid from String(512) to String(2048)
- Provides 2.2x safety margin for long endpoint URLs
- Aligns with configurable UAID_MAX_LENGTH limit"
```

---

## Task 2: Migration Update

**Files:**
- Modify: `mcpgateway/alembic/versions/d3e4f5a6b7c8_add_uaid_field_to_a2a_agents.py:53`

- [ ] **Step 1: Locate migration add_column statement**

Open `mcpgateway/alembic/versions/d3e4f5a6b7c8_add_uaid_field_to_a2a_agents.py` and find line 53:

```python
# Current line 53:
op.add_column("a2a_agents", sa.Column("uaid", sa.String(512), nullable=True, comment="Full UAID string for UAID-based agents"))
```

- [ ] **Step 2: Update migration to String(2048)**

Replace line 53:

```python
op.add_column("a2a_agents", sa.Column("uaid", sa.String(2048), nullable=True, comment="Full UAID string for UAID-based agents (max 2048 chars)"))
```

**Note:** Since PR #4125 hasn't merged yet, we update the migration in place rather than creating a new one.

- [ ] **Step 3: Verify migration syntax**

Run:
```bash
cd mcpgateway && python -c "from alembic.versions import d3e4f5a6b7c8_add_uaid_field_to_a2a_agents; print('Migration imports successfully')"
```

Expected: `Migration imports successfully`

- [ ] **Step 4: Commit migration update**

```bash
git add mcpgateway/alembic/versions/d3e4f5a6b7c8_add_uaid_field_to_a2a_agents.py
git commit -m "feat: update UAID migration to String(2048)

- Update add_column statement for uaid field
- Matches db.py schema (String(2048))
- In-place update since PR not yet merged"
```

---

## Task 3: Configuration Field for DoS Protection

**Files:**
- Modify: `mcpgateway/config.py:539` (add after existing uaid_allowed_domains field)

- [ ] **Step 1: Locate uaid_allowed_domains field in Settings class**

Open `mcpgateway/config.py` and find the UAID section around line 534-539:

```python
# Around line 534:
uaid_allowed_domains: List[str] = Field(
    default_factory=list,
    description=(
        "Domain allowlist for UAID cross-gateway routing..."
    ),
)
```

- [ ] **Step 2: Add uaid_max_length field after uaid_allowed_domains**

Insert after the uaid_allowed_domains field (around line 540):

```python
uaid_max_length: int = Field(
    default=2048,
    ge=512,   # Minimum: accommodate shortest valid UAID
    le=2048,  # Maximum: MUST match database column length (a2a_agents.uaid String(2048))
    description=(
        "Maximum allowed length for UAID strings. Used to prevent DoS attacks via "
        "excessively long UAID parsing. Must not exceed database column limit (2048). "
        "Default 2048 matches database capacity. Operators can reduce for stricter DoS "
        "protection but cannot exceed database schema limit."
    ),
)
```

- [ ] **Step 3: Verify configuration loads**

Run:
```bash
python -c "from mcpgateway.config import settings; print(f'UAID_MAX_LENGTH: {settings.uaid_max_length}'); assert settings.uaid_max_length == 2048"
```

Expected: `UAID_MAX_LENGTH: 2048`

- [ ] **Step 4: Test constraint validation**

Run:
```bash
python -c "from mcpgateway.config import Settings; Settings(uaid_max_length=3000)" 2>&1 | grep "less than or equal to 2048"
```

Expected: Validation error containing "less than or equal to 2048"

- [ ] **Step 5: Commit configuration change**

```bash
git add mcpgateway/config.py
git commit -m "feat: add UAID_MAX_LENGTH configuration field

- Add uaid_max_length Field with default 2048
- Constrained ge=512 (min), le=2048 (database limit)
- Configurable DoS protection for UAID parsing"
```

---

## Task 4: DoS Protection in UAID Parser

**Files:**
- Modify: `mcpgateway/utils/uaid.py:78` (beginning of parse_uaid function)
- Test: `tests/unit/mcpgateway/utils/test_uaid.py`

- [ ] **Step 1: Write failing test for excessive length**

Add to `tests/unit/mcpgateway/utils/test_uaid.py`:

```python
def test_parse_uaid_exceeds_max_length(monkeypatch):
    """Test UAID parsing rejects strings exceeding UAID_MAX_LENGTH."""
    from mcpgateway.config import settings
    from mcpgateway.utils.uaid import parse_uaid

    monkeypatch.setattr(settings, "uaid_max_length", 2048)

    # Create UAID exceeding limit (3000 chars)
    long_uaid = "uaid:aid:" + "x" * 3000

    with pytest.raises(ValueError, match="exceeds maximum length of 2048"):
        parse_uaid(long_uaid)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/unit/mcpgateway/utils/test_uaid.py::test_parse_uaid_exceeds_max_length -v
```

Expected: FAIL with "test_parse_uaid_exceeds_max_length FAILED" (no length check yet)

- [ ] **Step 3: Implement DoS protection at start of parse_uaid**

Open `mcpgateway/utils/uaid.py` and add at line 78 (beginning of parse_uaid function, after docstring):

```python
def parse_uaid(uaid: str) -> UaidComponents:
    """Parse UAID string into components.

    Parses both aid-based and did-based UAIDs:
        - aid: uaid:aid:{hash};uid={uid};registry={registry};proto={proto};nativeId={endpoint}
        - did: uaid:did:{did};uid={uid};proto={proto};nativeId={endpoint}

    Args:
        uaid: UAID string to parse

    Returns:
        UaidComponents with parsed values

    Raises:
        ValueError: If UAID format is invalid or required components are missing
    """
    # DoS Protection: Reject excessively long UAIDs before parsing
    # First-Party
    from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

    # Database column hard limit (source of truth)
    DB_UAID_COLUMN_LENGTH = 2048

    max_length = min(settings.uaid_max_length, DB_UAID_COLUMN_LENGTH)

    # Safety check: catch misconfigurations where config exceeds database limit
    if settings.uaid_max_length > DB_UAID_COLUMN_LENGTH:
        logger.warning(
            f"UAID_MAX_LENGTH ({settings.uaid_max_length}) exceeds database column limit "
            f"({DB_UAID_COLUMN_LENGTH}). Using database limit for safety."
        )

    if len(uaid) > max_length:
        raise ValueError(
            f"UAID exceeds maximum length of {max_length} characters. "
            f"Received {len(uaid)} characters. This may indicate a malformed or malicious UAID."
        )

    # Existing validation continues...
    if not is_uaid(uaid):
        raise ValueError(f"Invalid UAID format: must start with 'uaid:aid:' or 'uaid:did:', got: {uaid}")

    # ... rest of existing function unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/unit/mcpgateway/utils/test_uaid.py::test_parse_uaid_exceeds_max_length -v
```

Expected: PASS

- [ ] **Step 5: Write test for config exceeds database limit warning**

Add to `tests/unit/mcpgateway/utils/test_uaid.py`:

```python
def test_parse_uaid_config_exceeds_db_limit(monkeypatch, caplog):
    """Test parsing warns when UAID_MAX_LENGTH exceeds database limit."""
    from mcpgateway.config import settings
    from mcpgateway.utils.uaid import parse_uaid

    monkeypatch.setattr(settings, "uaid_max_length", 5000)  # Exceeds DB limit of 2048

    valid_uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=example.com"

    result = parse_uaid(valid_uaid)  # Should succeed but warn

    assert "exceeds database column limit" in caplog.text
    assert result.method == "aid"
```

- [ ] **Step 6: Run warning test to verify it passes**

Run:
```bash
pytest tests/unit/mcpgateway/utils/test_uaid.py::test_parse_uaid_config_exceeds_db_limit -v
```

Expected: PASS

- [ ] **Step 7: Commit DoS protection implementation**

```bash
git add mcpgateway/utils/uaid.py tests/unit/mcpgateway/utils/test_uaid.py
git commit -m "feat: add DoS protection to UAID parser

- Validate UAID length before parsing (prevent memory exhaustion)
- Use min(config, DB_LIMIT) for defense in depth
- Log warning if config exceeds database column limit
- Test coverage for length validation and config warnings"
```

---

## Task 5: Additional UAID Parser Test Coverage

**Files:**
- Test: `tests/unit/mcpgateway/utils/test_uaid.py`

- [ ] **Step 1: Write test for invalid UAID method**

Add to `tests/unit/mcpgateway/utils/test_uaid.py`:

```python
def test_parse_uaid_invalid_method():
    """Test UAID parsing rejects invalid methods (not 'aid' or 'did')."""
    from mcpgateway.utils.uaid import parse_uaid

    # Covers line 88: method not in ("aid", "did")
    invalid_uaid = "uaid:invalid:hash123;uid=0;registry=test;proto=a2a;nativeId=example.com"

    with pytest.raises(ValueError, match="Invalid UAID method"):
        parse_uaid(invalid_uaid)
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```bash
pytest tests/unit/mcpgateway/utils/test_uaid.py::test_parse_uaid_invalid_method -v
```

Expected: PASS (covers line 88 in uaid.py)

- [ ] **Step 3: Write test for UAID too short**

Add to `tests/unit/mcpgateway/utils/test_uaid.py`:

```python
def test_parse_uaid_too_short():
    """Test UAID parsing rejects strings without sufficient parts."""
    from mcpgateway.utils.uaid import parse_uaid

    # Covers line 84: len(parts) < 3
    short_uaid = "uaid:aid"  # Missing hash and parameters

    with pytest.raises(ValueError, match="expected 'uaid:METHOD:...' format"):
        parse_uaid(short_uaid)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/unit/mcpgateway/utils/test_uaid.py::test_parse_uaid_too_short -v
```

Expected: PASS (covers line 84 in uaid.py)

- [ ] **Step 5: Run all UAID tests to ensure no regressions**

Run:
```bash
pytest tests/unit/mcpgateway/utils/test_uaid.py -v
```

Expected: All tests PASS

- [ ] **Step 6: Commit additional test coverage**

```bash
git add tests/unit/mcpgateway/utils/test_uaid.py
git commit -m "test: add coverage for UAID parser edge cases

- Test invalid method rejection (covers line 88)
- Test too-short UAID rejection (covers line 84)
- Increases uaid.py coverage to 100%"
```

---

## Task 6: A2A Service Test Coverage

**Files:**
- Test: `tests/unit/mcpgateway/services/test_a2a_service.py`

- [ ] **Step 1: Write test for cross-gateway HTTP error handling**

Add to `tests/unit/mcpgateway/services/test_a2a_service.py`:

```python
async def test_invoke_agent_cross_gateway_routing_http_error(service, mock_db, monkeypatch):
    """Test cross-gateway routing handles HTTP errors gracefully."""
    from mcpgateway.services.a2a_service import A2AAgentError

    # Covers lines 1839, 1861: error handling in _invoke_remote_agent

    def mock_extract_routing(*args, **kwargs):
        return {"protocol": "a2a", "endpoint": "remote.example.com", "registry": "test"}

    monkeypatch.setattr("mcpgateway.utils.uaid.extract_routing_info", mock_extract_routing)

    # Mock HTTP client to return 500 error
    async def mock_post(*args, **kwargs):
        class MockResponse:
            status_code = 500
            def json(self):
                return {"error": "Internal server error"}
        return MockResponse()

    mock_client = type('obj', (object,), {'post': mock_post})()
    async def mock_get_client():
        return mock_client

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_client)

    uaid = "uaid:aid:hash;uid=0;registry=test;proto=a2a;nativeId=remote.example.com"

    with pytest.raises(A2AAgentError, match="Cross-gateway routing failed"):
        await service.invoke_agent(
            db=mock_db,
            agent_name="test",
            agent_id=uaid,
            parameters={"query": "test"}
        )
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```bash
pytest tests/unit/mcpgateway/services/test_a2a_service.py::test_invoke_agent_cross_gateway_routing_http_error -v
```

Expected: PASS (covers lines 1839, 1861 in a2a_service.py)

- [ ] **Step 3: Write test for disallowed domain rejection**

Add to `tests/unit/mcpgateway/services/test_a2a_service.py`:

```python
async def test_invoke_agent_uaid_disallowed_domain(service, mock_db, monkeypatch):
    """Test cross-gateway routing rejects disallowed domains."""
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "uaid_allowed_domains", ["trusted.com"])

    def mock_extract_routing(*args, **kwargs):
        return {"protocol": "a2a", "endpoint": "untrusted.example.com", "registry": "test"}

    monkeypatch.setattr("mcpgateway.utils.uaid.extract_routing_info", mock_extract_routing)

    uaid = "uaid:aid:hash;uid=0;registry=test;proto=a2a;nativeId=untrusted.example.com"

    with pytest.raises(ValueError, match="not allowed.*not in UAID_ALLOWED_DOMAINS"):
        await service.invoke_agent(
            db=mock_db,
            agent_name="test",
            agent_id=uaid,
            parameters={"query": "test"}
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/unit/mcpgateway/services/test_a2a_service.py::test_invoke_agent_uaid_disallowed_domain -v
```

Expected: PASS

- [ ] **Step 5: Write test for team access control**

Add to `tests/unit/mcpgateway/services/test_a2a_service.py`:

```python
async def test_invoke_agent_access_denied_by_team(service, mock_db):
    """Test agent invocation respects team visibility."""
    from mcpgateway.db import A2AAgent as DbA2AAgent
    from mcpgateway.services.a2a_service import A2AAgentNotFoundError

    # Covers lines 1566, 1578: access check edge cases

    # Create team-scoped agent
    agent = DbA2AAgent(
        id="test-agent-id",
        name="team-agent",
        endpoint_url="https://example.com",
        visibility="team",
        team_id="team-123",
        enabled=True
    )
    mock_db.add(agent)
    mock_db.commit()

    # Invoke with different team (should fail with 404, not 403)
    with pytest.raises(A2AAgentNotFoundError):
        await service.invoke_agent(
            db=mock_db,
            agent_name="team-agent",
            parameters={"query": "test"},
            token_teams=["different-team"]  # Wrong team
        )
```

- [ ] **Step 6: Run test to verify it passes**

Run:
```bash
pytest tests/unit/mcpgateway/services/test_a2a_service.py::test_invoke_agent_access_denied_by_team -v
```

Expected: PASS (covers lines 1566, 1578 in a2a_service.py)

- [ ] **Step 7: Run all A2A service tests to ensure no regressions**

Run:
```bash
pytest tests/unit/mcpgateway/services/test_a2a_service.py -v
```

Expected: All tests PASS

- [ ] **Step 8: Commit A2A service test coverage**

```bash
git add tests/unit/mcpgateway/services/test_a2a_service.py
git commit -m "test: add A2A service cross-gateway and access control coverage

- Test cross-gateway HTTP error handling (covers lines 1839, 1861)
- Test disallowed domain rejection
- Test team access control edge case (covers lines 1566, 1578)
- Increases a2a_service.py coverage toward 93% target"
```

---

## Task 7: Verify Test Coverage Target

**Files:**
- Run coverage report

- [ ] **Step 1: Run coverage report for changed files**

Run:
```bash
pytest tests/unit/mcpgateway/utils/test_uaid.py tests/unit/mcpgateway/services/test_a2a_service.py --cov=mcpgateway/utils/uaid.py --cov=mcpgateway/services/a2a_service.py --cov-report=term-missing
```

Expected:
- `uaid.py`: 100% coverage (all lines covered)
- `a2a_service.py`: Coverage increased from 84.1% (specific lines 1566, 1578, 1839, 1861 now covered)

- [ ] **Step 2: Run full test suite with coverage**

Run:
```bash
pytest --cov=mcpgateway --cov-report=term-missing --cov-report=html
```

Expected: Overall diff coverage 93%+ (target met)

- [ ] **Step 3: Review coverage report**

Open `htmlcov/index.html` and verify:
- `mcpgateway/utils/uaid.py`: 97-100% coverage
- `mcpgateway/services/a2a_service.py`: Lines 1566, 1578, 1839, 1861 covered (green)

**Note:** If coverage doesn't reach 93%, add more test cases for remaining missing lines before proceeding.

---

## Task 8: Security Documentation - Code Comments

**Files:**
- Modify: `mcpgateway/services/a2a_service.py:1855-1856`

- [ ] **Step 1: Locate existing authentication comment**

Open `mcpgateway/services/a2a_service.py` and find lines 1855-1856:

```python
# Current lines 1855-1856:
# NOTE: Authentication for cross-gateway calls is future work.
# Will support bearer token forwarding and mutual TLS in future release.
```

- [ ] **Step 2: Replace with comprehensive security comment block**

Replace lines 1855-1856 with:

```python
# ═══════════════════════════════════════════════════════════════════════════
# SECURITY: Cross-gateway authentication is NOT implemented (as of v1.0)
# ═══════════════════════════════════════════════════════════════════════════
# Current behavior: Cross-gateway UAID routing makes UNAUTHENTICATED HTTP calls
# to remote gateways. This means:
#   1. Remote gateway cannot verify the calling gateway's identity
#   2. User identity/authorization is NOT propagated to remote gateway
#   3. Relies solely on UAID_ALLOWED_DOMAINS for endpoint filtering
#
# Future work (tracked in follow-up PR):
#   - Bearer token forwarding (propagate user JWT to remote gateway)
#   - Mutual TLS authentication (gateway-to-gateway certificate validation)
#   - Trusted gateway registry (pre-register peer gateways with shared secrets)
#
# Security mitigation:
#   - UAID_ALLOWED_DOMAINS acts as endpoint allowlist (see config.py)
#   - Cross-gateway calls are logged with correlation IDs for audit trails
#   - Operators should set strict domain allowlists in production
# ═══════════════════════════════════════════════════════════════════════════
```

- [ ] **Step 3: Verify no syntax errors**

Run:
```bash
python -c "import mcpgateway.services.a2a_service; print('a2a_service imports successfully')"
```

Expected: `a2a_service imports successfully`

- [ ] **Step 4: Commit security comment enhancement**

```bash
git add mcpgateway/services/a2a_service.py
git commit -m "docs: enhance cross-gateway auth security comments

- Replace brief TODO with comprehensive security warning
- Document specific risks and mitigations
- Reference UAID_ALLOWED_DOMAINS as primary control
- Track future authentication work"
```

---

## Task 9: Security Documentation - .env.example

**Files:**
- Modify: `.env.example:85-90` (UAID section)

- [ ] **Step 1: Locate existing UAID configuration section**

Open `.env.example` and find the UAID section around lines 85-90:

```bash
# Current (around line 89):
# UAID_ALLOWED_DOMAINS=["example.com","trusted.org"]
```

- [ ] **Step 2: Replace UAID section with comprehensive documentation**

Replace the UAID section (around lines 82-90) with:

```bash
# UAID Cross-Gateway Routing Security
# =====================================
# ⚠️  SECURITY WARNING: Cross-gateway UAID routing is currently UNAUTHENTICATED
#
# When a UAID agent is not found locally, the gateway will route requests to
# remote gateways based on the endpoint embedded in the UAID. However, these
# cross-gateway calls do NOT currently include authentication (bearer token
# forwarding or mutual TLS will be added in a future release).
#
# RECOMMENDED CONFIGURATION:
# - Set UAID_ALLOWED_DOMAINS to a strict allowlist of trusted domains
# - Only include domains you control or have explicit trust relationships with
# - Empty list = allow all domains (NOT RECOMMENDED for production)
#
# Example: Only allow cross-gateway routing to your own infrastructure
# UAID_ALLOWED_DOMAINS=["mycompany.com","partner.trusted.com"]
#
# Domain allowlist for UAID cross-gateway routing (JSON array of domain suffixes)
# When not empty, only UAIDs with endpoints ending in these domains will be allowed
# Empty list = allow all domains (default)
UAID_ALLOWED_DOMAINS=[]

# UAID DoS Protection
# Maximum allowed UAID string length (default: 2048)
# Prevents memory exhaustion attacks from parsing excessively long UAIDs
# Valid range: 512-2048 characters
# - 512: Minimum to accommodate valid UAIDs
# - 2048: Maximum (database column limit - cannot be increased without migration)
# Operators can set lower values for stricter DoS protection
UAID_MAX_LENGTH=2048
```

- [ ] **Step 3: Verify .env.example syntax**

Run:
```bash
grep -A 5 "UAID_ALLOWED_DOMAINS" .env.example | head -10
```

Expected: Shows new comprehensive documentation with ⚠️ warning

- [ ] **Step 4: Commit .env.example documentation**

```bash
git add .env.example
git commit -m "docs: add comprehensive UAID security warnings to .env.example

- Prominent ⚠️ security warning about unauthenticated cross-gateway
- Configuration recommendations with examples
- Document UAID_MAX_LENGTH DoS protection setting
- Clear guidance for production deployments"
```

---

## Task 10: Security Documentation - README.md

**Files:**
- Modify: `README.md` (add Security section)

- [ ] **Step 1: Locate insertion point in README**

Open `README.md` and find a suitable location after installation/usage sections and before Contributing section. If a Security section already exists, add a subsection. Otherwise, create new section.

- [ ] **Step 2: Add UAID Security section**

Insert the following section:

```markdown
## Security

### UAID Cross-Gateway Routing Security

⚠️ **Important Security Notice**: UAID cross-gateway routing is currently **unauthenticated**.

When a UAID-identified agent is not found locally, ContextForge will route requests to
remote gateways based on the endpoint embedded in the UAID. However, these cross-gateway
calls do NOT currently include authentication mechanisms (bearer token forwarding and
mutual TLS support are planned for a future release).

**Security Implications:**
- Remote gateways cannot verify the calling gateway's identity
- User context and authorization are not propagated to remote gateways
- Endpoints in the allowlist must be explicitly trusted

**Recommended Configuration:**

```bash
# Set strict domain allowlist - only include trusted infrastructure
UAID_ALLOWED_DOMAINS=["mycompany.com","trusted-partner.com"]

# DoS protection - limit UAID parsing length (default: 2048)
UAID_MAX_LENGTH=2048
```

**Best Practices:**
1. **Restrict `UAID_ALLOWED_DOMAINS`** to domains you control or have explicit trust with
2. **Never use empty allowlist** (`[]`) in production - this allows routing to any domain
3. **Monitor cross-gateway calls** in observability dashboards for unexpected patterns
4. **Plan for authentication** - future releases will add bearer token forwarding and mutual TLS

See [UAID Implementation Guide](./UAID_APPROACH_B_IMPLEMENTATION.md) for architecture details.
```

- [ ] **Step 3: Verify markdown syntax**

Run:
```bash
python -c "import markdown; markdown.markdown(open('README.md').read()); print('README.md markdown valid')"
```

Expected: `README.md markdown valid` (or use a markdown linter)

- [ ] **Step 4: Commit README security documentation**

```bash
git add README.md
git commit -m "docs: add UAID security section to README

- Add prominent Security section with ⚠️ warning
- Document unauthenticated cross-gateway routing risks
- Provide configuration recommendations and best practices
- Link to UAID implementation guide"
```

---

## Task 11: Security Documentation - Implementation Guide

**Files:**
- Modify: `UAID_APPROACH_B_IMPLEMENTATION.md` (add Security Considerations section)

- [ ] **Step 1: Locate insertion point**

Open `UAID_APPROACH_B_IMPLEMENTATION.md` and find the section after "Changes Made" or "Testing" (near the end of the document).

- [ ] **Step 2: Add Security Considerations section**

Insert the following section:

```markdown
## Security Considerations

### Cross-Gateway Authentication Gap

**Current Limitation:** Cross-gateway UAID routing is **unauthenticated** in this release.

When invoking a UAID agent not found locally, the gateway routes the request to the
remote endpoint embedded in the UAID. However, these cross-gateway calls do not
currently include authentication mechanisms.

**Risks:**
- Remote gateways cannot verify the calling gateway's identity
- User authorization context is not propagated
- Potential for unauthorized agent invocations if endpoint allowlist is misconfigured

**Mitigations Implemented:**
1. **Domain Allowlist** (`UAID_ALLOWED_DOMAINS`): Restricts cross-gateway routing to trusted domains
2. **Audit Logging**: All cross-gateway calls are logged with correlation IDs
3. **DoS Protection** (`UAID_MAX_LENGTH`): Prevents memory exhaustion from parsing long UAIDs
4. **Opt-in Model**: Empty allowlist provides secure default (no cross-gateway routing)

**Planned Enhancements:**
- Bearer token forwarding (propagate user JWT to remote gateways)
- Mutual TLS authentication (certificate-based gateway identity verification)
- Trusted gateway registry (pre-registered peer gateways with shared secrets)

**Deployment Recommendations:**
- Set strict `UAID_ALLOWED_DOMAINS` in production (never use empty list)
- Monitor cross-gateway call patterns in observability dashboards
- Only include domains under your operational control or explicit trust relationships
- Review audit logs regularly for unexpected cross-gateway activity
```

- [ ] **Step 3: Verify markdown syntax**

Run:
```bash
grep -A 5 "Security Considerations" UAID_APPROACH_B_IMPLEMENTATION.md
```

Expected: Shows new section header and content

- [ ] **Step 4: Commit implementation guide update**

```bash
git add UAID_APPROACH_B_IMPLEMENTATION.md
git commit -m "docs: add Security Considerations to UAID implementation guide

- Document cross-gateway authentication gap
- List risks and implemented mitigations
- Outline planned security enhancements
- Provide deployment recommendations"
```

---

## Task 12: License Checker Investigation and Fix

**Files:**
- Potentially modify: `license-policy.toml`

- [ ] **Step 1: Run license checker to identify failure**

Run:
```bash
python scripts/license_checker.py --config license-policy.toml --report-json license-check-report.json
```

Expected: Either PASS or error identifying specific package (likely `base58>=2.1.1`)

- [ ] **Step 2: Check base58 license**

If license checker fails on base58:

Run:
```bash
pip show base58 | grep License
```

Expected: `License: MIT`

- [ ] **Step 3: Add base58 to allowed packages (if needed)**

If base58 is flagged, open `license-policy.toml` and add:

```toml
[[package]]
name = "base58"
allowed_licenses = ["MIT"]
reason = "Required for UAID SHA-384 hash encoding (HCS-14 standard)"
```

**Note:** Only add this if license checker actually fails on base58. If it fails on a different dependency, investigate that package instead.

- [ ] **Step 4: Re-run license checker to verify fix**

Run:
```bash
python scripts/license_checker.py --config license-policy.toml --report-json license-check-report.json
```

Expected: PASS with all dependencies approved

- [ ] **Step 5: Commit license policy update (if changed)**

If `license-policy.toml` was modified:

```bash
git add license-policy.toml
git commit -m "chore: add base58 to license allowlist

- base58 uses MIT license (compatible)
- Required for UAID SHA-384 hash encoding
- Fixes license checker CI/CD failure"
```

If license checker passed without changes, skip this commit.

---

## Task 13: Run Full Test Suite

**Files:**
- Validation step

- [ ] **Step 1: Run complete test suite**

Run:
```bash
make test
```

Expected: All tests PASS (147+ A2A tests + 31 UAID tests + 7 new tests = 185+ total)

- [ ] **Step 2: Run linting checks**

Run:
```bash
make ruff pylint
```

Expected: No new linting errors (should maintain 10.00/10 Pylint score)

- [ ] **Step 3: Run type checking**

Run:
```bash
make mypy
```

Expected: No type errors

- [ ] **Step 4: Verify coverage report**

Run:
```bash
pytest --cov=mcpgateway --cov-report=term-missing | grep -E "mcpgateway/(utils/uaid|services/a2a_service)"
```

Expected:
- `mcpgateway/utils/uaid.py`: 97-100%
- `mcpgateway/services/a2a_service.py`: 86-88% (up from 84.1%)
- Overall diff coverage: 93-94%

---

## Task 14: Manual Testing - DoS Protection

**Files:**
- Manual validation

- [ ] **Step 1: Test UAID length rejection in Python REPL**

Run:
```bash
python -c "
from mcpgateway.utils.uaid import parse_uaid
try:
    long_uaid = 'uaid:aid:' + 'x' * 3000
    parse_uaid(long_uaid)
    print('ERROR: Should have raised ValueError')
except ValueError as e:
    print(f'✓ Length validation works: {e}')
"
```

Expected: `✓ Length validation works: UAID exceeds maximum length...`

- [ ] **Step 2: Test configurable limit (UAID_MAX_LENGTH=512)**

Run:
```bash
UAID_MAX_LENGTH=512 python -c "
from mcpgateway.utils.uaid import parse_uaid
try:
    medium_uaid = 'uaid:aid:' + 'x' * 600
    parse_uaid(medium_uaid)
    print('ERROR: Should have raised ValueError')
except ValueError as e:
    print(f'✓ Configurable limit works: {e}')
"
```

Expected: `✓ Configurable limit works: UAID exceeds maximum length of 512...`

- [ ] **Step 3: Test valid UAID still works**

Run:
```bash
python -c "
from mcpgateway.utils.uaid import parse_uaid
valid_uaid = 'uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=example.com'
result = parse_uaid(valid_uaid)
print(f'✓ Valid UAID parsed: method={result.method}, proto={result.proto}')
"
```

Expected: `✓ Valid UAID parsed: method=aid, proto=a2a`

---

## Task 15: Manual Testing - Cross-Gateway Security Warning

**Files:**
- Manual validation

- [ ] **Step 1: Verify .env.example security warning is prominent**

Run:
```bash
grep -B 2 -A 20 "⚠️  SECURITY WARNING" .env.example
```

Expected: Shows prominent warning block with recommendations

- [ ] **Step 2: Verify README security section exists**

Run:
```bash
grep -A 10 "UAID Cross-Gateway Routing Security" README.md
```

Expected: Shows security section with warning emoji and best practices

- [ ] **Step 3: Verify code comment is comprehensive**

Run:
```bash
grep -A 15 "SECURITY: Cross-gateway authentication" mcpgateway/services/a2a_service.py
```

Expected: Shows comprehensive comment block with risks and mitigations

---

## Task 16: Final Validation Checklist

**Files:**
- Comprehensive validation

- [ ] **Step 1: Verify all files were modified**

Run:
```bash
git diff --name-only main | sort
```

Expected list:
```
.env.example
README.md
UAID_APPROACH_B_IMPLEMENTATION.md
license-policy.toml (possibly)
mcpgateway/alembic/versions/d3e4f5a6b7c8_add_uaid_field_to_a2a_agents.py
mcpgateway/config.py
mcpgateway/db.py
mcpgateway/services/a2a_service.py
mcpgateway/utils/uaid.py
tests/unit/mcpgateway/services/test_a2a_service.py
tests/unit/mcpgateway/utils/test_uaid.py
```

- [ ] **Step 2: Verify commit count**

Run:
```bash
git log --oneline main..HEAD | wc -l
```

Expected: 11-15 commits (one per task/step group)

- [ ] **Step 3: Review all commit messages**

Run:
```bash
git log --oneline main..HEAD
```

Expected: All commits follow conventional commit format (`feat:`, `docs:`, `test:`, `chore:`)

- [ ] **Step 4: Verify no uncommitted changes**

Run:
```bash
git status
```

Expected: `nothing to commit, working tree clean`

- [ ] **Step 5: Run full validation suite**

Run:
```bash
make test && make ruff pylint && make mypy
```

Expected: All checks PASS

---

## Success Criteria Checklist

Verify all goals from the spec are met:

- [ ] Database schema updated: `a2a_agents.uaid` is `String(2048)` in `db.py` and migration
- [ ] Configuration added: `uaid_max_length` Field exists in `config.py` with proper constraints
- [ ] DoS protection implemented: Length validation at start of `parse_uaid()` function
- [ ] Security documentation complete:
  - [ ] README.md has Security section with ⚠️ warning
  - [ ] .env.example has comprehensive UAID documentation
  - [ ] Code comments enhanced in `a2a_service.py`
  - [ ] Implementation guide updated with Security Considerations
- [ ] Test coverage increased:
  - [ ] 4 new tests in `test_uaid.py` (length, invalid method, too short, config warning)
  - [ ] 3 new tests in `test_a2a_service.py` (HTTP error, disallowed domain, team access)
  - [ ] Coverage reaches 93%+ (up from 91%)
- [ ] License checker passes (base58 added to allowlist if needed)
- [ ] All tests pass: `make test` ✅
- [ ] All linters pass: `make ruff pylint mypy` ✅
- [ ] Manual DoS testing validates protection works
- [ ] No commits pushed (user commits manually per requirement)

---

## Troubleshooting

**If test coverage doesn't reach 93%:**
1. Run coverage report with `--cov-report=html` to identify remaining missing lines
2. Add targeted test cases for specific uncovered branches
3. Focus on `a2a_service.py` lines 1225, 1227-1228, 1238-1241, 1243-1245 if still missing

**If license checker fails on unexpected package:**
1. Identify the failing package in error output
2. Run `pip show <package> | grep License` to check license
3. If compatible (MIT, BSD, Apache-2.0), add to `license-policy.toml`
4. If incompatible license, investigate alternative package

**If tests fail:**
1. Check test isolation: ensure `monkeypatch` is used for config changes
2. Verify mock objects have correct method signatures
3. Run individual test with `-vv` flag for detailed output

**If linting fails:**
1. Run `make black isort autoflake` to auto-fix formatting
2. Address remaining `pylint` suggestions manually
3. Ensure all imports use `# pylint: disable=import-outside-toplevel` where needed
