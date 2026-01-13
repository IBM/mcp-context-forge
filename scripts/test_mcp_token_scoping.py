#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive MCP Client Test for Token Scoping RBAC.

Current tool state (5 tools total):
- fast-time-get-system-time: visibility=team, team_id=12c794d92318414fbc6829bd455bee6d
- fast-time-convert-time: visibility=public
- fast-test-get-system-time: visibility=public
- fast-test-get-stats: visibility=public
- fast-test-echo: visibility=public

Security Model Notes:
- Users must exist in the database for non-admin token validation
- Team memberships claimed in tokens are validated against EmailTeamMember table
- Tokens claiming membership to non-existent or unauthorized teams are rejected
- admin@example.com is pre-seeded as the platform admin and member of the default team

Test Cases:
1. Admin with no teams key -> should see ALL 5 tools (unrestricted)
2. Admin with teams: null -> should see ALL 5 tools (unrestricted)
3. Admin with teams: [] -> should see only 4 PUBLIC tools (public-only scope)
4. Admin with matching team -> should see all 5 tools (team + public)
5. Admin with wrong team -> token REJECTED (team membership validation fails)
6. Non-admin with no teams -> should see only 4 PUBLIC tools (secure default)
7. Non-admin with matching team -> should see all 5 tools (team + public)
8. Non-admin with teams: [] -> should see 4 PUBLIC tools (explicit public-only)
"""

import asyncio
import jwt
import time
import sys
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

# Colors for output
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
NC = "\033[0m"


@dataclass
class TestResult:
    name: str
    expected_tools: int
    actual_tools: int
    expected_public: int
    expected_team: int
    actual_public: int
    actual_team: int
    tool_names: List[str]
    passed: bool
    error: Optional[str] = None


def generate_token(
    email: str,
    is_admin: bool,
    teams: Optional[List[str]] = "OMIT",
    secret: str = "my-test-key"
) -> str:
    """Generate a JWT token with specified claims."""
    payload = {
        "sub": email,
        "is_admin": is_admin,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "iss": "mcpgateway",
        "aud": "mcpgateway-api"
    }
    if teams != "OMIT":
        payload["teams"] = teams
    return jwt.encode(payload, secret, algorithm="HS256")


async def test_with_http_rpc(
    base_url: str,
    token: str,
    test_name: str,
    expected_public: int,
    expected_team: int
) -> TestResult:
    """Test via HTTP RPC endpoint."""
    import aiohttp

    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 1
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/rpc",
                headers=headers,
                json=payload
            ) as response:
                data = await response.json()

                if "error" in data:
                    return TestResult(
                        name=test_name,
                        expected_tools=expected_public + expected_team,
                        actual_tools=0,
                        expected_public=expected_public,
                        expected_team=expected_team,
                        actual_public=0,
                        actual_team=0,
                        tool_names=[],
                        passed=False,
                        error=data["error"].get("message", str(data["error"]))
                    )

                tools = data.get("result", {}).get("tools", [])
                tool_names = [t["name"] for t in tools]

                actual_public = sum(1 for t in tools if t.get("visibility") == "public")
                actual_team = sum(1 for t in tools if t.get("visibility") == "team")

                expected_total = expected_public + expected_team
                passed = len(tools) == expected_total

                return TestResult(
                    name=test_name,
                    expected_tools=expected_total,
                    actual_tools=len(tools),
                    expected_public=expected_public,
                    expected_team=expected_team,
                    actual_public=actual_public,
                    actual_team=actual_team,
                    tool_names=tool_names,
                    passed=passed
                )

    except Exception as e:
        return TestResult(
            name=test_name,
            expected_tools=expected_public + expected_team,
            actual_tools=0,
            expected_public=expected_public,
            expected_team=expected_team,
            actual_public=0,
            actual_team=0,
            tool_names=[],
            passed=False,
            error=str(e)
        )


def print_result(result: TestResult):
    """Print a test result."""
    status = f"{GREEN}✓ PASS{NC}" if result.passed else f"{RED}✗ FAIL{NC}"
    print(f"\n{status}: {result.name}")
    print(f"  Expected: {result.expected_tools} tools ({result.expected_public} public + {result.expected_team} team)")
    print(f"  Actual:   {result.actual_tools} tools ({result.actual_public} public + {result.actual_team} team)")

    if result.tool_names:
        print(f"  Tools: {', '.join(result.tool_names[:5])}")
        if len(result.tool_names) > 5:
            print(f"         ... and {len(result.tool_names) - 5} more")

    if result.error:
        print(f"  {RED}Error: {result.error}{NC}")


async def run_tests(base_url: str, team_id: str):
    """Run all tests."""

    print(f"{CYAN}{'='*70}{NC}")
    print(f"{CYAN}MCP Token Scoping Test Suite{NC}")
    print(f"{CYAN}{'='*70}{NC}")
    print(f"\nBase URL: {base_url}")
    print(f"Team ID: {team_id}")
    print(f"\nCurrent tool state (5 tools):")
    print(f"  - fast-time-get-system-time: visibility=TEAM")
    print(f"  - fast-time-convert-time: visibility=public")
    print(f"  - fast-test-*: 3 tools, visibility=public")

    results = []

    # Test 1: Admin with no teams key (UNRESTRICTED)
    print(f"\n{YELLOW}Test 1: Admin with NO teams key{NC}")
    token = generate_token("admin@example.com", is_admin=True, teams="OMIT")
    result = await test_with_http_rpc(base_url, token, "Admin no teams", 4, 1)
    results.append(result)
    print_result(result)

    # Test 2: Admin with teams: null (UNRESTRICTED)
    print(f"\n{YELLOW}Test 2: Admin with teams: null{NC}")
    token = generate_token("admin@example.com", is_admin=True, teams=None)
    result = await test_with_http_rpc(base_url, token, "Admin teams:null", 4, 1)
    results.append(result)
    print_result(result)

    # Test 3: Admin with teams: [] (PUBLIC-ONLY)
    print(f"\n{YELLOW}Test 3: Admin with teams: []{NC}")
    token = generate_token("admin@example.com", is_admin=True, teams=[])
    result = await test_with_http_rpc(base_url, token, "Admin teams:[]", 4, 0)
    results.append(result)
    print_result(result)

    # Test 4: Admin with matching team
    print(f"\n{YELLOW}Test 4: Admin with matching team{NC}")
    token = generate_token("admin@example.com", is_admin=True, teams=[team_id])
    result = await test_with_http_rpc(base_url, token, "Admin + team", 4, 1)
    results.append(result)
    print_result(result)

    # Test 5: Admin with wrong team - token should be rejected due to team membership validation
    print(f"\n{YELLOW}Test 5: Admin with wrong team (REJECTED){NC}")
    token = generate_token("admin@example.com", is_admin=True, teams=["wrong-team"])
    result = await test_with_http_rpc(base_url, token, "Admin wrong team", 0, 0)  # Expect rejection
    # For this test, we expect an error (0 tools), not a successful list
    if result.error and "team" in result.error.lower():
        result.passed = True  # Token correctly rejected
    results.append(result)
    print_result(result)

    # Test 6: Non-admin with no teams (secure default) - uses admin email as it exists in DB
    print(f"\n{YELLOW}Test 6: Non-admin with NO teams{NC}")
    token = generate_token("admin@example.com", is_admin=False, teams="OMIT")
    result = await test_with_http_rpc(base_url, token, "Non-admin no teams", 4, 0)
    results.append(result)
    print_result(result)

    # Test 7: Non-admin with matching team - uses admin email as it exists in DB
    print(f"\n{YELLOW}Test 7: Non-admin with matching team{NC}")
    token = generate_token("admin@example.com", is_admin=False, teams=[team_id])
    result = await test_with_http_rpc(base_url, token, "Non-admin + team", 4, 1)
    results.append(result)
    print_result(result)

    # Test 8: Non-admin with teams: [] - uses admin email as it exists in DB
    print(f"\n{YELLOW}Test 8: Non-admin with teams: []{NC}")
    token = generate_token("admin@example.com", is_admin=False, teams=[])
    result = await test_with_http_rpc(base_url, token, "Non-admin teams:[]", 4, 0)
    results.append(result)
    print_result(result)

    # Summary
    print(f"\n{CYAN}{'='*70}{NC}")
    print(f"{CYAN}SUMMARY{NC}")
    print(f"{CYAN}{'='*70}{NC}")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    print(f"\n{GREEN}Passed: {passed}{NC} | {RED}Failed: {failed}{NC}")

    print(f"""
┌────────────────────────────────────────────────────────────────────────┐
│                    Token Scoping Results                               │
├────────────────────────────────────────────────────────────────────────┤
│ Test                      │ Expected │ Actual │ Status                 │
├───────────────────────────┼──────────┼────────┼────────────────────────┤""")

    for r in results:
        status = f"{GREEN}PASS{NC}" if r.passed else f"{RED}FAIL{NC}"
        exp_str = f"{r.expected_tools} ({r.expected_public}p+{r.expected_team}t)"
        act_str = f"{r.actual_tools} ({r.actual_public}p+{r.actual_team}t)"
        print(f"│ {r.name:<25} │ {exp_str:<8} │ {act_str:<6} │ {status:<22} │")

    print("└────────────────────────────────────────────────────────────────────────┘")

    return all(r.passed for r in results)


async def test_mcp_transport(mcp_url: str, token: str, test_name: str, expected_count: int):
    """Test MCP protocol transport."""
    print(f"\n{YELLOW}MCP Transport: {test_name}{NC}")
    print(f"  URL: {mcp_url}")
    print(f"  Expected tools: {expected_count}")

    try:
        from mcp.client.streamable_http import streamablehttp_client
        from mcp.client.session import ClientSession

        headers = {"Authorization": f"Bearer {token}"}

        async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()

                actual = len(tools.tools)
                status = f"{GREEN}PASS{NC}" if actual == expected_count else f"{RED}FAIL{NC}"
                print(f"  Actual tools: {actual} [{status}]")

                for t in tools.tools[:3]:
                    print(f"    - {t.name}")
                if len(tools.tools) > 3:
                    print(f"    ... and {len(tools.tools) - 3} more")

                # Try calling a tool
                if tools.tools:
                    tool = tools.tools[0]
                    try:
                        if "time" in tool.name:
                            result = await session.call_tool(tool.name, {"timezone": "UTC"})
                        else:
                            result = await session.call_tool(tool.name, {})
                        print(f"  {GREEN}Tool call succeeded{NC}")
                    except Exception as e:
                        print(f"  {RED}Tool call failed: {e}{NC}")

                return actual == expected_count

    except Exception as e:
        print(f"  {RED}Error: {e}{NC}")
        return False


async def main():
    base_url = "http://localhost:8080"
    team_id = "12c794d92318414fbc6829bd455bee6d"  # Platform Administrator's Team

    # Run RPC tests
    all_passed = await run_tests(base_url, team_id)

    # Run MCP transport tests
    print(f"\n{CYAN}{'='*70}{NC}")
    print(f"{CYAN}MCP TRANSPORT TESTS{NC}")
    print(f"{CYAN}{'='*70}{NC}")

    # Admin unrestricted - should see 5 tools
    token = generate_token("admin@example.com", is_admin=True, teams="OMIT")
    t1 = await test_mcp_transport(f"{base_url}/mcp/", token, "Admin (unrestricted)", 5)

    # Admin public-only - should see 4 tools
    token = generate_token("admin@example.com", is_admin=True, teams=[])
    t2 = await test_mcp_transport(f"{base_url}/mcp/", token, "Admin (public-only)", 4)

    # Non-admin with team - should see 5 tools (uses admin email as it exists in DB)
    token = generate_token("admin@example.com", is_admin=False, teams=[team_id])
    t3 = await test_mcp_transport(f"{base_url}/mcp/", token, "Non-admin + team", 5)

    # Virtual server test
    server_id = "9779b6698cbd4b4995ee04a4fab38737"
    token = generate_token("admin@example.com", is_admin=True, teams="OMIT")
    t4 = await test_mcp_transport(f"{base_url}/servers/{server_id}/mcp/", token, "Virtual Server", 2)

    transport_passed = all([t1, t2, t3, t4])

    print(f"\n{CYAN}{'='*70}{NC}")
    print(f"{CYAN}FINAL RESULT{NC}")
    print(f"{CYAN}{'='*70}{NC}")

    if all_passed and transport_passed:
        print(f"\n{GREEN}ALL TESTS PASSED!{NC}")
        return 0
    else:
        print(f"\n{RED}SOME TESTS FAILED{NC}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
