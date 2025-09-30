#!/bin/bash
# Test DCR Implementation (After Changes)
# This script validates the DCR implementation
# and confirms all features are working

# Don't exit on errors - we want to count passes/failures
# set -e

echo "================================================"
echo "Testing DCR Implementation (After Changes)"
echo "================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS_COUNT=0
FAIL_COUNT=0

function test_passed() {
    echo -e "${GREEN}✓ $1${NC}"
    ((PASS_COUNT++))
}

function test_failed() {
    echo -e "${RED}✗ $1${NC}"
    ((FAIL_COUNT++))
}

function test_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Test 1: Check if PKCE methods exist
echo "Test 1: Checking for PKCE support..."
if python3 -c "from mcpgateway.services.oauth_manager import OAuthManager; m = OAuthManager(); assert hasattr(m, '_generate_pkce_params')" 2>/dev/null; then
    test_passed "PKCE methods found"
    
    # Test PKCE generation
    echo "  Testing PKCE generation..."
    if python3 -c "from mcpgateway.services.oauth_manager import OAuthManager; m = OAuthManager(); pkce = m._generate_pkce_params(); assert 'code_verifier' in pkce and 'code_challenge' in pkce and pkce['code_challenge_method'] == 'S256' and 43 <= len(pkce['code_verifier']) <= 128" 2>/dev/null; then
        echo "    ✓ PKCE parameters valid"
    else
        echo "    ✗ PKCE parameter validation failed"
    fi
else
    test_failed "PKCE methods NOT found"
fi
echo ""

# Test 2: Check if DCR service exists
echo "Test 2: Checking for DCR service..."
if python3 -c "from mcpgateway.services.dcr_service import DcrService" 2>/dev/null; then
    test_passed "DcrService exists"
    
    # Check for required methods
    echo "  Checking DcrService methods..."
    python3 -c "from mcpgateway.services.dcr_service import DcrService; import inspect; dcr = DcrService(); methods = ['discover_as_metadata', 'register_client', 'get_or_register_client', 'update_client_registration', 'delete_client_registration']; [print(f'  ✓ {m}') if hasattr(dcr, m) else print(f'  ✗ Missing: {m}') for m in methods]" 2>/dev/null
else
    test_failed "DcrService NOT found"
fi
echo ""

# Test 3: Check database for DCR tables
echo "Test 3: Checking database for DCR tables..."
if [ -f "mcp.db" ]; then
    if sqlite3 mcp.db ".tables" | grep -q "registered_oauth_clients"; then
        test_passed "registered_oauth_clients table exists"
        
        # Check table schema
        echo "  Checking table schema..."
        REQUIRED_COLUMNS=("id" "gateway_id" "issuer" "client_id" "client_secret_encrypted" "redirect_uris" "grant_types" "scope" "token_endpoint_auth_method" "registration_client_uri" "registration_access_token_encrypted" "created_at" "expires_at" "is_active")
        
        for col in "${REQUIRED_COLUMNS[@]}"; do
            if sqlite3 mcp.db "PRAGMA table_info(registered_oauth_clients)" | grep -q "$col"; then
                echo "    ✓ Column: $col"
            else
                echo "    ✗ Missing column: $col"
            fi
        done
        
        # Check for unique constraint
        if sqlite3 mcp.db ".schema registered_oauth_clients" | grep -q "UNIQUE.*gateway_id.*issuer"; then
            echo "    ✓ Unique constraint on (gateway_id, issuer)"
        else
            test_warning "Missing unique constraint on (gateway_id, issuer)"
        fi
    else
        test_failed "registered_oauth_clients table NOT found"
    fi
    
    # Check for code_verifier column in oauth_states
    if sqlite3 mcp.db "PRAGMA table_info(oauth_states)" | grep -q "code_verifier"; then
        test_passed "code_verifier column exists in oauth_states"
    else
        test_failed "code_verifier column NOT found in oauth_states"
    fi
else
    test_warning "Database file mcp.db not found - run 'make dev' first"
fi
echo ""

# Test 4: Check config for DCR settings
echo "Test 4: Checking configuration for DCR settings..."
if python3 -c "from mcpgateway.config import get_settings; s = get_settings(); settings = ['dcr_enabled', 'dcr_auto_register_on_missing_credentials', 'dcr_default_scopes', 'dcr_allowed_issuers', 'dcr_token_endpoint_auth_method', 'dcr_metadata_cache_ttl', 'dcr_client_name_template', 'oauth_discovery_enabled', 'oauth_preferred_code_challenge_method']; missing = [x for x in settings if not hasattr(s, x)]; print('DCR Configuration Settings:'); [print(f'  ✓ {x}: {getattr(s, x)}') for x in settings if hasattr(s, x)]; [print(f'  ✗ Missing: {x}') for x in missing]; exit(0 if len(missing) == 0 else 1)" 2>/dev/null; then
    test_passed "DCR config settings found"
else
    test_failed "DCR config settings incomplete"
fi
echo ""

# Test 5: Check OAuth manager for discovery and PKCE integration
echo "Test 5: Checking OAuth manager integration..."
echo "  OAuth Manager Methods:"
python3 -c "from mcpgateway.services.oauth_manager import OAuthManager; import inspect; m = OAuthManager(); methods = ['_generate_pkce_params', '_create_authorization_url_with_pkce', '_validate_and_retrieve_state']; [print(f'    ✓ {name}') if hasattr(m, name) else print(f'    ✗ Missing: {name}') for name in methods]" 2>/dev/null

# Check if _exchange_code_for_tokens accepts code_verifier
if python3 -c "from mcpgateway.services.oauth_manager import OAuthManager; import inspect; m = OAuthManager(); sig = inspect.signature(m._exchange_code_for_tokens); assert 'code_verifier' in sig.parameters" 2>/dev/null; then
    echo "    ✓ _exchange_code_for_tokens accepts code_verifier"
else
    echo "    ✗ _exchange_code_for_tokens missing code_verifier parameter"
fi
echo ""

# Test 6: Check admin DCR router
echo "Test 6: Checking admin DCR router..."
if [ -f "mcpgateway/routers/admin_dcr_router.py" ]; then
    test_passed "admin_dcr_router.py exists"
    
    echo "  Checking DCR admin endpoints..."
    for endpoint in list_registered_clients get_registered_client delete_registered_client refresh_registered_client; do
        if grep -q "$endpoint" mcpgateway/routers/admin_dcr_router.py 2>/dev/null; then
            echo "    ✓ Endpoint: $endpoint"
        else
            echo "    ✗ Missing endpoint: $endpoint"
        fi
    done
else
    test_failed "admin_dcr_router.py NOT found"
fi
echo ""

# Test 7: Check Alembic migration
echo "Test 7: Checking Alembic migration..."
MIGRATION_FILE=$(find mcpgateway/alembic/versions -name "*dcr*.py" 2>/dev/null | head -1)
if [ -n "$MIGRATION_FILE" ]; then
    test_passed "DCR migration file found: $(basename $MIGRATION_FILE)"
    
    echo "  Checking migration content..."
    if grep -q "registered_oauth_clients" "$MIGRATION_FILE"; then
        echo "    ✓ Creates registered_oauth_clients table"
    else
        echo "    ✗ Missing registered_oauth_clients table creation"
    fi
    
    if grep -q "code_verifier" "$MIGRATION_FILE"; then
        echo "    ✓ Adds code_verifier to oauth_states"
    else
        echo "    ✗ Missing code_verifier column addition"
    fi
else
    test_failed "DCR migration file NOT found"
fi
echo ""

# Test 8: Check documentation updates
echo "Test 8: Checking documentation updates..."
if grep -q "Dynamic Client Registration\|DCR" docs/docs/manage/oauth.md 2>/dev/null; then
    test_passed "OAuth documentation includes DCR"
else
    test_warning "DCR not documented in oauth.md"
fi

if grep -q "dcr_enabled\|DCR_ENABLED" docs/docs/manage/configuration.md 2>/dev/null; then
    test_passed "Configuration documentation includes DCR settings"
else
    test_warning "DCR not documented in configuration.md"
fi

if ls docs/docs/architecture/adr/*dcr*.md 1> /dev/null 2>&1; then
    test_passed "DCR Architecture Decision Record exists"
else
    test_warning "No ADR for DCR implementation"
fi
echo ""

# Test 9: Run unit tests
echo "Test 9: Running unit tests..."
if [ -d "tests/unit/services" ]; then
    if pytest tests/unit/services/test_dcr_service.py -v --tb=short 2>/dev/null; then
        test_passed "DCR service unit tests pass"
    else
        test_failed "DCR service unit tests fail or don't exist"
    fi
    
    if pytest tests/unit/services/test_oauth_manager_pkce.py -v --tb=short 2>/dev/null; then
        test_passed "OAuth manager PKCE tests pass"
    else
        test_failed "OAuth manager PKCE tests fail or don't exist"
    fi
else
    test_warning "Unit test directory not found"
fi
echo ""

# Test 10: Check linting
echo "Test 10: Checking code quality..."
echo "  Running black..."
if black --check mcpgateway/services/dcr_service.py 2>/dev/null; then
    echo "    ✓ Code formatted correctly"
else
    test_warning "Code needs formatting (run: black mcpgateway/services/dcr_service.py)"
fi

echo "  Running pylint..."
if pylint mcpgateway/services/dcr_service.py --disable=all --enable=E,F 2>/dev/null; then
    echo "    ✓ No critical errors"
else
    test_warning "Linting issues detected"
fi
echo ""

# Summary
echo "================================================"
echo "Summary"
echo "================================================"
echo ""
echo -e "${GREEN}Passed: $PASS_COUNT${NC}"
echo -e "${RED}Failed: $FAIL_COUNT${NC}"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed! DCR implementation looks good.${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Run full test suite: make test"
    echo "  2. Run integration tests: pytest tests/integration/test_dcr_*.py"
    echo "  3. Test manually with mock AS"
    echo "  4. Update CHANGELOG.md"
    echo "  5. Create PR"
    exit 0
else
    echo -e "${RED}✗ Some tests failed. Please review and fix.${NC}"
    echo ""
    echo "Debug steps:"
    echo "  1. Check failed tests above"
    echo "  2. Review implementation against DCR_IMPLEMENTATION_PLAN.md"
    echo "  3. Run: python3 -m pytest -v"
    echo "  4. Check logs: tail -f logs/gateway.log"
    exit 1
fi

