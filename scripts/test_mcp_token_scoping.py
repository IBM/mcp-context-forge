#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comprehensive MCP Client Test for Token Scoping RBAC.

The tool inventory and visibility counts are discovered from the running
gateway before the assertions, so the checks follow the pinned Compose image
instead of duplicating its catalog in this script.

Security Model Notes:
- Users must exist in the database for non-admin token validation
- Team memberships claimed in tokens are validated against EmailTeamMember table
- Tokens claiming membership to non-existent or unauthorized teams are rejected
- admin@example.com is pre-seeded as the platform admin and member of the default team

Test Cases:
1. Admin with no teams key -> unrestricted
2. Admin with teams: null -> unrestricted
3. Admin with teams: [] -> public-only scope
4. Admin with matching team -> unrestricted catalog
5. Admin with wrong team -> token rejected
6. Non-admin with no teams -> public-only secure default
7. Non-admin with matching team -> unrestricted catalog
8. Non-admin with teams: [] -> public-only scope
"""

import asyncio
import sys
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

import jwt

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


def generate_token(email: str, is_admin: bool, teams: Optional[List[str]] = "OMIT", secret: str = "my-test-key-but-now-longer-than-32-bytes") -> str:
    """Generate a JWT token with specified claims."""
    payload = {"sub": email, "is_admin": is_admin, "iat": int(time.time()), "exp": int(time.time()) + 3600, "iss": "mcpgateway", "aud": "mcpgateway-api", "jti": str(uuid.uuid4())}
    if teams != "OMIT":
        payload["teams"] = teams
    return jwt.encode(payload, secret, algorithm="HS256")


async def discover_tool_counts(base_url: str, token: str) -> tuple[int, int]:
    """Return public and team tool counts from the unrestricted catalog."""
    import aiohttp

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/tools?limit=0", headers=headers) as response:
            response.raise_for_status()
            tools = await response.json()

    if not isinstance(tools, list):
        raise RuntimeError(f"Unexpected tools catalog payload: {tools!r}")

    unsupported = {tool.get("visibility") for tool in tools} - {"public", "team"}
    if unsupported:
        raise RuntimeError(f"Unsupported tool visibility values in catalog: {sorted(unsupported)}")
    return (
        sum(1 for tool in tools if tool.get("visibility") == "public"),
        sum(1 for tool in tools if tool.get("visibility") == "team"),
    )


async def discover_virtual_server_tool_count(base_url: str, token: str, server_id: str) -> int:
    """Return the number of tools associated with a virtual server."""
    import aiohttp

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/servers/{server_id}", headers=headers) as response:
            response.raise_for_status()
            server = await response.json()

    associated_tools = server.get("associatedTools", server.get("associated_tools", []))
    if not isinstance(associated_tools, list):
        raise RuntimeError(f"Unexpected associated tool payload for server {server_id}: {associated_tools!r}")
    return len(associated_tools)


async def test_with_http_rpc(base_url: str, token: str, test_name: str, expected_public: int, expected_team: int) -> TestResult:
    """Test via HTTP RPC endpoint."""
    import aiohttp

    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        payload = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1}

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{base_url}/rpc", headers=headers, json=payload) as response:
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
                        error=data["error"].get("message", str(data["error"])),
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
                    passed=passed,
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
            error=str(e),
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


async def run_tests(base_url: str, team_id: str) -> tuple[bool, int, int]:
    """Run all token-scoping tests against the discovered catalog."""

    print(f"{CYAN}{'='*70}{NC}")
    print(f"{CYAN}MCP Token Scoping Test Suite{NC}")
    print(f"{CYAN}{'='*70}{NC}")
    print(f"\nBase URL: {base_url}")
    print(f"Team ID: {team_id}")

    discovery_token = generate_token("admin@example.com", is_admin=True, teams=None)
    expected_public, expected_team = await discover_tool_counts(base_url, discovery_token)
    expected_total = expected_public + expected_team
    print(f"\nDiscovered tool state ({expected_total} tools): {expected_public} public + {expected_team} team")

    results = []

    # Test 1: Admin with no teams key (UNRESTRICTED)
    print(f"\n{YELLOW}Test 1: Admin with NO teams key{NC}")
    token = generate_token("admin@example.com", is_admin=True, teams="OMIT")
    result = await test_with_http_rpc(base_url, token, "Admin no teams", expected_public, expected_team)
    results.append(result)
    print_result(result)

    # Test 2: Admin with teams: null (UNRESTRICTED)
    print(f"\n{YELLOW}Test 2: Admin with teams: null{NC}")
    token = generate_token("admin@example.com", is_admin=True, teams=None)
    result = await test_with_http_rpc(base_url, token, "Admin teams:null", expected_public, expected_team)
    results.append(result)
    print_result(result)

    # Test 3: Admin with teams: [] (PUBLIC-ONLY)
    print(f"\n{YELLOW}Test 3: Admin with teams: []{NC}")
    token = generate_token("admin@example.com", is_admin=True, teams=[])
    result = await test_with_http_rpc(base_url, token, "Admin teams:[]", expected_public, 0)
    results.append(result)
    print_result(result)

    # Test 4: Admin with matching team
    print(f"\n{YELLOW}Test 4: Admin with matching team{NC}")
    token = generate_token("admin@example.com", is_admin=True, teams=[team_id])
    result = await test_with_http_rpc(base_url, token, "Admin + team", expected_public, expected_team)
    results.append(result)
    print_result(result)

    # Test 5: Admin with wrong team - token should be rejected
    print(f"\n{YELLOW}Test 5: Admin with wrong team (REJECTED){NC}")
    token = generate_token("admin@example.com", is_admin=True, teams=["wrong-team"])
    result = await test_with_http_rpc(base_url, token, "Admin wrong team", 0, 0)
    if result.error and "team" in result.error.lower():
        result.passed = True
    results.append(result)
    print_result(result)

    # Test 6: Non-admin with no teams (secure default)
    print(f"\n{YELLOW}Test 6: Non-admin with NO teams{NC}")
    token = generate_token("admin@example.com", is_admin=False, teams="OMIT")
    result = await test_with_http_rpc(base_url, token, "Non-admin no teams", expected_public, 0)
    results.append(result)
    print_result(result)

    # Test 7: Non-admin with matching team
    print(f"\n{YELLOW}Test 7: Non-admin with matching team{NC}")
    token = generate_token("admin@example.com", is_admin=False, teams=[team_id])
    result = await test_with_http_rpc(base_url, token, "Non-admin + team", expected_public, expected_team)
    results.append(result)
    print_result(result)

    # Test 8: Non-admin with teams: []
    print(f"\n{YELLOW}Test 8: Non-admin with teams: []{NC}")
    token = generate_token("admin@example.com", is_admin=False, teams=[])
    result = await test_with_http_rpc(base_url, token, "Non-admin teams:[]", expected_public, 0)
    results.append(result)
    print_result(result)

    print(f"\n{CYAN}{'='*70}{NC}")
    print(f"{CYAN}SUMMARY{NC}")
    print(f"{CYAN}{'='*70}{NC}")
    passed = sum(1 for result in results if result.passed)
    failed = len(results) - passed
    print(f"\n{GREEN}Passed: {passed}{NC} | {RED}Failed: {failed}{NC}")

    for result in results:
        status = f"{GREEN}PASS{NC}" if result.passed else f"{RED}FAIL{NC}"
        expected = f"{result.expected_tools} ({result.expected_public}p+{result.expected_team}t)"
        actual = f"{result.actual_tools} ({result.actual_public}p+{result.actual_team}t)"
        print(f"  {result.name:<25} expected={expected:<8} actual={actual:<6} {status}")
    return all(result.passed for result in results), expected_public, expected_team


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
                            await session.call_tool(tool.name, {"timezone": "UTC"})
                        else:
                            await session.call_tool(tool.name, {})
                        print(f"  {GREEN}Tool call succeeded{NC}")
                    except Exception as e:
                        print(f"  {RED}Tool call failed: {e}{NC}")

                return actual == expected_count
    except Exception as e:
        print(f"  {RED}Error: {e}{NC}")
        return False


async def main():
    base_url = "http://localhost:8080"
    team_id = "12c794d92318414fbc6829bd455bee6d"  # Platform Administrator's Team  # pragma: allowlist secret

    all_passed, expected_public, expected_team = await run_tests(base_url, team_id)

    print(f"\n{CYAN}{'='*70}{NC}")
    print(f"{CYAN}MCP TRANSPORT TESTS{NC}")
    print(f"{CYAN}{'='*70}{NC}")

    expected_total = expected_public + expected_team

    token = generate_token("admin@example.com", is_admin=True, teams="OMIT")
    t1 = await test_mcp_transport(f"{base_url}/mcp/", token, "Admin (unrestricted)", expected_total)

    token = generate_token("admin@example.com", is_admin=True, teams=[])
    t2 = await test_mcp_transport(f"{base_url}/mcp/", token, "Admin (public-only)", expected_public)

    token = generate_token("admin@example.com", is_admin=False, teams=[team_id])
    t3 = await test_mcp_transport(f"{base_url}/mcp/", token, "Non-admin + team", expected_total)

    server_id = "9779b6698cbd4b4995ee04a4fab38737"  # pragma: allowlist secret
    token = generate_token("admin@example.com", is_admin=True, teams="OMIT")
    expected_virtual_server = await discover_virtual_server_tool_count(base_url, token, server_id)
    t4 = await test_mcp_transport(f"{base_url}/servers/{server_id}/mcp/", token, "Virtual Server", expected_virtual_server)

    transport_passed = all([t1, t2, t3, t4])

    print(f"\n{CYAN}{'='*70}{NC}")
    print(f"{CYAN}FINAL RESULT{NC}")
    print(f"{CYAN}{'='*70}{NC}")

    if all_passed and transport_passed:
        print(f"\n{GREEN}ALL TESTS PASSED!{NC}")
        return 0

    print(f"\n{RED}SOME TESTS FAILED{NC}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
