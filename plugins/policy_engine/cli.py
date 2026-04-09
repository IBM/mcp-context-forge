#!/usr/bin/env python3
"""
Policy Engine Plugin - Unified CLI Interface

Provides simple commands to:
- Scan: Run source scanner on a server/repo
- Apply Policy: Check scan results against policies
- Ask Waiver: Request exception for policy violations
"""

# Standard
import argparse
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, Optional

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# First-Party
from mcpgateway.plugins.framework import PluginConfig
from plugins.policy_engine.models import Policy
from plugins.policy_engine.plugin import get_plugin
from plugins.source_scanner.report import Report
from plugins.source_scanner.source_scanner import SourceScannerPlugin

logger = logging.getLogger(__name__)


class PolicyEnginesCLI:
    """Unified CLI for Policy Engine + Source Scanner integration."""

    def __init__(self):
        """Initialize CLI and plugin instances."""
        self.plugin = get_plugin()
        self.scanner = self._init_scanner()

    def _init_scanner(self):
        """Initialize source scanner plugin."""
        config = PluginConfig(
            name="source_scanner",
            kind="plugins.source_scanner.source_scanner.SourceScannerPlugin",
            config={
                "scan_timeout_seconds": 600,
                "max_repo_size_mb": 1000,
                "severity_threshold": "ERROR",
                "fail_on_critical": True,
            },
        )
        return SourceScannerPlugin(config)

    def scan(self, server_name: str, repo_url: Optional[str] = None, ref: Optional[str] = None) -> Dict[str, Any]:
        """
        Scan a repository using source scanner.

        Args:
            server_name: Name/identifier of the server
            repo_url: Repository URL (if None, uses server_name as URL)
            ref: Branch/tag to scan (default: main)

        Returns:
            Scan findings and summary
        """
        if not repo_url:
            repo_url = server_name

        print(f"\n{'='*60}")
        print(f"SCANNING: {server_name}")
        print(f"Repository: {repo_url}")
        print(f"{'='*60}\n")

        try:
            # Run async scanner
            result = asyncio.run(self.scanner.scan(repo_url, ref=ref))

            # Generate report
            report = Report(result.findings)
            summary = report.summary()

            print("✓ Scan Complete!")
            print("\nFindings Summary:")
            print(f"  🔴 Critical (ERROR):  {summary['ERROR']}")
            print(f"  🟠 High (WARNING):    {summary['WARNING']}")
            print(f"  🟡 Info:              {summary['INFO']}")
            print(f"  Total Issues:         {summary['total_issues']}\n")

            # Store findings with server context
            findings_data = {
                "server_id": server_name,
                "repo_url": repo_url,
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "error_count": summary["ERROR"],  # Critical = errors
                    "warning_count": summary["WARNING"],  # High = warnings
                    "info_count": summary["INFO"],
                    "total_issues": summary["total_issues"],
                },
                "findings": [f.dict() for f in result.findings],
            }

            return findings_data

        except Exception as e:
            print(f"\n❌ Scan Failed: {str(e)}\n")
            raise

    def apply_policy(self, server_name: str, policy_name: str, scan_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply a policy to scan results.

        Args:
            server_name: Server identifier
            policy_name: Name of the policy to apply
            scan_results: Findings from scan

        Returns:
            Policy evaluation result
        """
        print(f"\n{'='*60}")
        print(f"APPLYING POLICY: {policy_name}")
        print(f"Server: {server_name}")
        print(f"{'='*60}\n")

        try:
            # Find policy by name
            policies = self.plugin.list_policies()
            policy = next((p for p in policies if p.name == policy_name), None)

            if not policy:
                print(f"❌ Policy '{policy_name}' not found")
                if policies:
                    print("\nAvailable policies:")
                    for p in policies:
                        print(f"  • {p.name} ({p.environment})")
                else:
                    print("No policies configured. Run setup_policies.py first or create policies via API.\n")
                return None

            # Evaluate assessment
            result = self.plugin.evaluate_assessment(assessment=scan_results, server_id=server_name, policy_id=policy.id)

            # Display results
            print("Policy Evaluation Results:")
            print(f"  Decision:         {result['decision'].upper()}")
            print(f"  Compliance Score: {result['score']:.1f}%")
            print(f"  Status:           {result['compliance_status']}")
            print("\nRule Results:")

            for rule_result in result["rule_results"]:
                status = "✓ PASS" if rule_result["passed"] else "✗ FAIL"
                waived = " (WAIVED)" if rule_result["waived"] else ""
                print(f"  {status}{waived}: {rule_result['rule']}")
                print(f"           {rule_result['message']}")

            if result["decision"] == "block":
                print("\n⚠️  Policy Violations Found!")
                failing_rules = [r for r in result["rule_results"] if not r["passed"] and not r["waived"]]
                print(f"   {len(failing_rules)} rule(s) need waivers to proceed\n")

            return result

        except Exception as e:
            print(f"\n❌ Policy Application Failed: {str(e)}\n")
            raise

    def ask_waiver(self, server_name: str, rule_name: str, reason: str, duration_days: int = 7) -> Dict[str, Any]:
        """
        Request a waiver for a policy violation.

        Args:
            server_name: Server identifier
            rule_name: Rule being waived
            reason: Reason for exception
            duration_days: How long waiver should last (default 7)

        Returns:
            Waiver request details
        """
        print(f"\n{'='*60}")
        print("REQUESTING WAIVER")
        print(f"{'='*60}")
        print(f"Server:   {server_name}")
        print(f"Rule:     {rule_name}")
        print(f"Reason:   {reason}")
        print(f"Duration: {duration_days} days\n")

        try:
            # Check if server has been scanned
            evaluations = self.plugin.get_evaluation_history(server_id=server_name)
            if not evaluations:
                print(f"❌ Error: Server '{server_name}' has not been scanned yet!")
                print(f"   Please scan the server first using: apply-policy --server {server_name} --policy <policy_name>")
                raise ValueError(f"Server '{server_name}' not found in evaluation history")

            waiver = self.plugin.create_waiver(server_id=server_name, rule_name=rule_name, reason=reason, requested_by="cli", duration_days=duration_days)

            print("✓ Waiver Request Created!")
            print(f"  Waiver ID:  {waiver['id']}")
            print(f"  Status:     {waiver['status']}")
            print(f"  Expires:    {waiver['expires_at'].strftime('%Y-%m-%d %H:%M:%S')}")
            print("\n⏳ Awaiting approval from security team...\n")

            return waiver

        except Exception as e:
            print(f"\n❌ Waiver Request Failed: {str(e)}\n")
            raise

    def approve_waiver(self, waiver_id: str, approved_by: str = "security-team") -> Dict[str, Any]:
        """
        Approve a pending waiver (admin use).

        Args:
            waiver_id: Waiver ID to approve
            approved_by: Approver identifier

        Returns:
            Updated waiver
        """
        print(f"\nApproving waiver {waiver_id}...\n")

        waiver = self.plugin.approve_waiver(waiver_id, approved_by=approved_by)
        if waiver:
            print("✓ Waiver Approved!")
            print(f"  Status: {waiver['status']}")
            print()
        return waiver

    def list_policies(self) -> list[Policy]:
        """List all available policies."""
        print(f"\n{'='*60}")
        print("AVAILABLE POLICIES")
        print(f"{'='*60}\n")

        policies = self.plugin.list_policies()
        if not policies:
            print("No policies configured\n")
            return policies

        for policy in policies:
            print(f"📋 {policy.name} (ID: {policy.id})")
            print(f"   Environment: {policy.environment}")
            print("   Rules:")
            for rule_name, rule_value in policy.rules.items():
                print(f"     - {rule_name}: {rule_value}")
            print()

        return policies

    def list_waivers(self, server_name: Optional[str] = None) -> list[Dict[str, Any]]:
        """List waivers, optionally filtered by server."""
        print(f"\n{'='*60}")
        print("WAIVERS")
        print(f"{'='*60}\n")

        waivers = self.plugin.list_waivers(server_name)
        if not waivers:
            print("No waivers found\n")
            return waivers

        for waiver in waivers:
            status_icon = "⏳" if waiver["status"] == "pending" else "✓" if waiver["status"] == "approved" else "✗"
            print(f"{status_icon} {waiver['rule_name']} ({waiver['status']})")
            print(f"  Server: {waiver['server_id']}")
            print(f"  Reason: {waiver['reason']}")
            print(f"  Expires: {waiver.get('expires_at', 'N/A')}")
            print()

        return waivers


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Policy Engine CLI - Scan & Compliance Checking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan a repository
  %(prog)s scan --server my-server --repo https://github.com/user/repo

  # Apply a single policy (uses cached scan)
  %(prog)s apply-policy --server my-server --policy Production

  # Auto-scan AND apply single policy (all-in-one)
  %(prog)s apply-policy --server my-server --repo https://github.com/user/repo --policy Production

  # Auto-scan AND apply multiple policies (all-in-one)
  %(prog)s apply-policy --server my-server --repo https://github.com/user/repo --policy Dev --policy Standard --policy Production

  # Request a waiver
  %(prog)s ask-waiver --server my-server --rule max_critical_vulnerabilities --reason "Fix in progress" --days 7

  # List all policies
  %(prog)s list-policies

  # List waivers
  %(prog)s list-waivers --server my-server
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # SCAN command
    scan_parser = subparsers.add_parser("scan", help="Scan a repository for vulnerabilities")
    scan_parser.add_argument("--server", required=True, help="Server/project name")
    scan_parser.add_argument("--repo", help="Repository URL (defaults to server name)")
    scan_parser.add_argument("--ref", help="Branch/tag to scan (default: main)")

    # APPLY-POLICY command
    apply_parser = subparsers.add_parser("apply-policy", help="Apply policy to scan results or auto-scan repo")
    apply_parser.add_argument("--server", required=True, help="Server name")
    apply_parser.add_argument("--repo", help="Repository URL (if provided, will auto-scan)")
    apply_parser.add_argument("--policy", action="append", help="Policy name(s) to apply (can use multiple times)")
    apply_parser.add_argument("--scan-file", help="Scan results JSON file (if not re-scanning)")

    # ASK-WAIVER command
    waiver_parser = subparsers.add_parser("ask-waiver", help="Request a waiver for policy violation")
    waiver_parser.add_argument("--server", required=True, help="Server name")
    waiver_parser.add_argument("--rule", required=True, help="Rule name")
    waiver_parser.add_argument("--reason", required=True, help="Reason for exception")
    waiver_parser.add_argument("--days", type=int, default=7, help="Duration in days (default: 7)")

    # APPROVE-WAIVER command
    approve_parser = subparsers.add_parser("approve-waiver", help="Approve a waiver (admin)")
    approve_parser.add_argument("--id", required=True, help="Waiver ID")
    approve_parser.add_argument("--by", default="security-team", help="Approver name")

    # LIST-POLICIES command
    # list_policies_parser = subparsers.add_parser('list-policies', help='List available policies')

    # LIST-WAIVERS command
    list_waivers_parser = subparsers.add_parser("list-waivers", help="List waivers")
    list_waivers_parser.add_argument("--server", help="Filter by server")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Initialize CLI
    cli = PolicyEnginesCLI()
    scan_results = None

    try:
        # Handle commands
        if args.command == "scan":
            scan_results = cli.scan(args.server, args.repo, args.ref)
            # Save for later use
            with open(f"/tmp/{args.server}_scan.json", "w") as f:
                json.dump(scan_results, f)

        elif args.command == "apply-policy":
            # Auto-scan if repo URL provided
            if args.repo:
                print("⚡ Auto-scanning repository...")
                scan_results = cli.scan(args.server, args.repo, None)
                # Save for later use
                with open(f"/tmp/{args.server}_scan.json", "w") as f:
                    json.dump(scan_results, f)
            elif args.scan_file:
                with open(args.scan_file) as f:
                    scan_results = json.load(f)
            else:
                # Try to find recent scan
                scan_file = f"/tmp/{args.server}_scan.json"
                if Path(scan_file).exists():
                    with open(scan_file) as f:
                        scan_results = json.load(f)
                else:
                    print("❌ No scan results found. Please run 'scan' command first or provide --repo.\n")
                    sys.exit(1)

            # Handle policies (can be multiple)
            if not args.policy:
                print("❌ No policies specified. Use --policy PolicyName (can use multiple times)\n")
                sys.exit(1)

            # Apply each policy
            for policy_name in args.policy:
                cli.apply_policy(args.server, policy_name, scan_results)

        elif args.command == "ask-waiver":
            cli.ask_waiver(args.server, args.rule, args.reason, args.days)

        elif args.command == "approve-waiver":
            cli.approve_waiver(args.id, args.by)

        elif args.command == "list-policies":
            cli.list_policies()

        elif args.command == "list-waivers":
            cli.list_waivers(args.server)

    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
