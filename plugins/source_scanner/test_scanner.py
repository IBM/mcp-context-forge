#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test suite for Source Scanner Plugin.

Location: ./plugins/source_scanner/test_scanner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: MCP Security Team
"""

# Standard
import argparse
import asyncio
import logging
from pathlib import Path
import sys
from typing import Optional

# First-Party
from mcpgateway.plugins.framework import PluginConfig

# Plugin components
from plugins.source_scanner.source_scanner import SourceScannerPlugin

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ============================================================
# LOGGING CONFIGURATION - Clean Output
# ============================================================


class CleanFormatter(logging.Formatter):
    """Custom formatter that removes timestamps and logger names for INFO level."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record based on level."""
        if record.levelno == logging.INFO:
            # INFO: Just the message, nothing else
            return record.getMessage()
        return f"{record.levelname}: {record.getMessage()}"


# Remove any existing handlers
logging.root.handlers = []

# Create handler with custom formatter
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(CleanFormatter())

# Configure root logger
logging.root.addHandler(handler)
logging.root.setLevel(logging.INFO)

# Get our logger (will use root handler)
logger = logging.getLogger(__name__)

# Silence noisy loggers
logging.getLogger("plugins.source_scanner").setLevel(logging.WARNING)
logging.getLogger("mcpgateway").setLevel(logging.ERROR)


# ============================================================
# TEST FUNCTION
# ============================================================


async def test_repository(repo_url: str, ref: Optional[str] = None):
    """Test scanning a repository."""

    try:
        logger.info("=" * 60)
        logger.info("SOURCE SCANNER - REPOSITORY TEST")
        logger.info("=" * 60)

        # Standard
        import time

        start_time = time.time()

        # Initialize scanner
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
        scanner = SourceScannerPlugin(config)

        # Scan
        logger.info(f"Scanning {repo_url}")
        if ref:
            logger.info(f"Reference: {ref}")
        logger.info("")

        result = await scanner.scan(repo_url, ref=ref)

        duration = time.time() - start_time

        # Display results
        logger.info("=" * 60)
        logger.info("SCAN RESULTS")
        logger.info("=" * 60)
        logger.info(f"Repository: {repo_url}")
        logger.info(f"Commit SHA: {result.commit_sha}")
        logger.info(f"Languages: {', '.join(result.languages)}")
        logger.info(f"Duration: {duration:.1f}s")
        logger.info("")
        logger.info(f"Total findings: {len(result.findings)}")
        logger.info(f"  🔴 ERROR: {result.summary.error_count}")
        logger.info(f"  🟡 WARNING: {result.summary.warning_count}")
        logger.info(f"  ℹ️  INFO: {result.summary.info_count}")
        logger.info("")
        logger.info(f"Policy Decision: {'🚫 BLOCKED' if result.blocked else '✅ ALLOWED'}")
        if result.block_reason:
            logger.info(f"Block Reason: {result.block_reason}")

        # Show findings breakdown
        if result.findings:
            logger.info("")
            logger.info("=" * 60)
            logger.info("FINDINGS BREAKDOWN")
            logger.info("=" * 60)

            errors = [f for f in result.findings if f.severity == "ERROR"]
            warnings = [f for f in result.findings if f.severity == "WARNING"]
            infos = [f for f in result.findings if f.severity == "INFO"]

            if errors:
                logger.info(f"\n🔴 ERRORS ({len(errors)}):")
                for i, finding in enumerate(errors[:10], 1):
                    logger.info(f"  {i}. {finding.rule_id}")
                    logger.info(f"     {finding.file_path}:{finding.line}")
                    logger.info(f"     {finding.message[:100]}...")
                if len(errors) > 10:
                    logger.info(f"  ... and {len(errors) - 10} more")

            if warnings:
                logger.info(f"\n🟡 WARNINGS ({len(warnings)}):")
                for i, finding in enumerate(warnings[:5], 1):
                    logger.info(f"  {i}. {finding.rule_id}")
                    logger.info(f"     {finding.file_path}:{finding.line}")
                if len(warnings) > 5:
                    logger.info(f"  ... and {len(warnings) - 5} more")

            if infos:
                logger.info(f"\nℹ️  INFO ({len(infos)}):")
                for i, finding in enumerate(infos[:3], 1):
                    logger.info(f"  {i}. {finding.rule_id}")
                if len(infos) > 3:
                    logger.info(f"  ... and {len(infos) - 3} more")

        logger.info("")
        logger.info("=" * 60)
        logger.info("✅ TEST PASSED")
        logger.info("=" * 60)

        sys.exit(0)

    except Exception as e:
        logger.error("=" * 60)
        logger.error("❌ TEST FAILED")
        logger.error("=" * 60)
        logger.error(f"Error: {e}")
        if logger.isEnabledFor(logging.DEBUG):
            # Standard
            import traceback

            logger.error(traceback.format_exc())
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test Source Scanner Plugin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m plugins.source_scanner.test_scanner --repo https://github.com/WebGoat/WebGoat
  python -m plugins.source_scanner.test_scanner --repo https://github.com/digininja/DVWA
  python -m plugins.source_scanner.test_scanner --repo https://github.com/user/repo --ref main
        """,
    )

    parser.add_argument("--repo", required=True, help="GitHub repository URL")
    parser.add_argument("--ref", help="Git reference (branch/tag/commit)")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")

    args = parser.parse_args()

    if args.verbose:
        logging.root.setLevel(logging.DEBUG)
        logging.getLogger("plugins.source_scanner").setLevel(logging.DEBUG)

    asyncio.run(test_repository(repo_url=args.repo, ref=args.ref))


if __name__ == "__main__":
    main()
