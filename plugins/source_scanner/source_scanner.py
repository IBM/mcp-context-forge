#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/source_scanner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi, Ayo

Source Scanner Plugin.
Performs static analysis on MCP server source code using Semgrep and Bandit
to detect security vulnerabilities before deployment.
"""

# Future
from __future__ import annotations

# Standard
import logging
import os
from typing import Optional

# First-Party
from mcpgateway.plugins.framework import (  # PluginContext,
    Plugin,
    PluginConfig,
)

# Local
from .config import SourceScannerConfig
from .errors import SourceScannerError
from .language_detector import LanguageDetector
from .models import Finding, ScanResult, ScanSummary
from .parsing.normalizer import FindingNormalizer
from .policy import PolicyChecker

# Components
from .repo_fetcher import RepoFetcher
from .scanners.bandit_runner import BanditRunner
from .scanners.semgrep_runner import SemgrepRunner
from .storage.repository import ScanRepository

logger = logging.getLogger(__name__)


class SourceScannerPlugin(Plugin):
    """Scan MCP server source code for security vulnerabilities.

    Workflow:
        1. Extract repo_url and ref from payload
        2. Check cache (if enabled)
        3. Clone repository (RepoFetcher)
        4. Detect languages (LanguageDetector)
        5. Run scanners (Semgrep, Bandit)
        6. Normalize findings (FindingNormalizer)
        7. Calculate summary
        8. Evaluate policy (PolicyChecker)
        9. Store results (if enabled)
        10. Cleanup temporary files
        11. Return decision (block/allow)
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the source scanner plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = SourceScannerConfig(**(config.config or {}))

        # Initialize components
        self._repo_fetcher = RepoFetcher()
        self._language_detector = LanguageDetector()
        self._semgrep_runner = SemgrepRunner(self._cfg.semgrep)
        self._bandit_runner = BanditRunner(self._cfg.bandit)
        self._normalizer = FindingNormalizer()
        self._policy_checker = PolicyChecker()
        self._storage: Optional[ScanRepository] = None
        self._db_session = None
        try:
            # First-Party
            from mcpgateway.db import SessionLocal

            self._db_session = SessionLocal()
            self._storage = ScanRepository(self._db_session)
            logger.info("Storage initialized successfully")
        except ImportError as e:
            logger.warning(f"Database integration not available: {e}. Storage disabled.")
        except Exception as e:
            logger.error(f"Failed to initialize storage: {e}. Storage disabled.")

        logger.info(
            "SourceScannerPlugin initialized",
            extra={
                "semgrep_enabled": self._cfg.semgrep.enabled,
                "bandit_enabled": self._cfg.bandit.enabled,
                "severity_threshold": self._cfg.severity_threshold,
                "fail_on_critical": self._cfg.fail_on_critical,
                "storage_enabled": self._storage is not None,
            },
        )

    async def scan(
        self,
        repo_url: str,
        ref: Optional[str] = None,
    ) -> ScanResult:
        """Public method to scan a repository directly.

        Use this for testing/standalone operation until gateway hooks are implemented.

        Args:
            repo_url: Repository URL to scan.
            ref: Branch/tag/commit reference.

        Returns:
            Complete scan results.
        """
        return await self._scan_workflow(repo_url, ref)

    def __del__(self):
        """Cleanup database session on plugin destruction."""
        if self._db_session:
            try:
                self._db_session.close()
                logger.info("Database session closed")
            except Exception as e:
                logger.warning(f"Error closing database session: {e}")

    async def _scan_workflow(
        self,
        repo_url: str,
        ref: Optional[str] = None,
    ) -> ScanResult:
        """Execute complete scan workflow.

        Args:
            repo_url: Repository URL to scan.
            ref: Branch/tag/commit reference.

        Returns:
            Complete scan results with findings and policy decision.

        Raises:
            SourceScannerError: If scan workflow fails.
        """
        logger.info(f"Starting scan for {repo_url} (ref={ref})")

        cleanup_fn = None

        try:
            # Step 1: Clone & Checkout
            github_token = os.environ.get(self._cfg.github_token_env)
            workspace, cleanup_fn = await self._repo_fetcher.fetch(
                repo_url=repo_url,
                ref=ref,
                clone_timeout=self._cfg.clone_timeout_seconds,
                max_size_mb=self._cfg.max_repo_size_mb,
                github_token=github_token,
            )
            commit_sha = workspace.commit_sha

            # Step 2: Detect languages
            languages = self._language_detector.detect(workspace.path)
            logger.info(f"Detected languages: {languages}")

            # Step 3: Run scanners
            findings_by_scanner: list[list[Finding]] = []

            # Run Semgrep (if enabled)
            if self._cfg.semgrep.enabled:
                logger.info("Running Semgrep scanner")
                semgrep_findings = await self._semgrep_runner.run(
                    repo_path=workspace.path,
                    timeout_s=self._cfg.scan_timeout_seconds,
                )
                findings_by_scanner.append(semgrep_findings)
                logger.info(f"Semgrep found {len(semgrep_findings)} issues")

            # Run Bandit (if Python detected and enabled)
            if "python" in languages and self._cfg.bandit.enabled:
                logger.info("Running Bandit scanner")
                bandit_findings = await self._bandit_runner.run(
                    repo_path=workspace.path,
                    timeout_s=self._cfg.scan_timeout_seconds,
                )
                findings_by_scanner.append(bandit_findings)
                logger.info(f"Bandit found {len(bandit_findings)} issues")

            # Step 4: Merge & Deduplicate
            merged_findings = self._normalizer.merge_dedup(findings_by_scanner)
            logger.info(f"Total unique findings after deduplication: {len(merged_findings)}")

            # Step 5: Calculate summary
            summary = ScanSummary(
                error_count=sum(1 for f in merged_findings if f.severity == "ERROR"),
                warning_count=sum(1 for f in merged_findings if f.severity == "WARNING"),
                info_count=sum(1 for f in merged_findings if f.severity == "INFO"),
            )

            logger.info(
                "Scan summary",
                extra={
                    "errors": summary.error_count,
                    "warnings": summary.warning_count,
                    "info": summary.info_count,
                },
            )

            # Step 6: Evaluate policy
            decision = self._policy_checker.evaluate(
                findings=merged_findings,
                threshold=self._cfg.severity_threshold,
                fail_on_critical=self._cfg.fail_on_critical,
            )

            # Step 7: Build result
            result = ScanResult(
                repo_url=repo_url,
                ref=ref,
                commit_sha=commit_sha,
                languages=languages,
                findings=merged_findings,
                summary=summary,
                blocked=decision.blocked,
                block_reason=decision.reason,
            )

            if self._storage:
                try:
                    # Standard
                    import asyncio
                    from functools import partial

                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        partial(
                            self._storage.create_scan,
                            repo_url=repo_url,
                            ref=ref,
                            commit_sha=commit_sha,
                            languages=languages,
                            findings=merged_findings,
                            blocked=result.blocked,
                            block_reason=result.block_reason,
                        ),
                    )
                    logger.info(f"Scan results saved to database (commit: {commit_sha})")
                except Exception as e:
                    logger.error(f"Failed to save scan results to database: {e}", exc_info=True)

            logger.info(
                "Scan complete",
                extra={
                    "blocked": result.blocked,
                    "findings_count": len(result.findings),
                    "commit_sha": commit_sha,
                },
            )

            return result

        except SourceScannerError as e:
            logger.error(f"Scan failed: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error during scan: {e}", exc_info=True)
            raise SourceScannerError(f"Scan failed: {e}") from e
        finally:
            # Step 10: Cleanup
            if cleanup_fn:
                try:
                    cleanup_fn()
                    logger.debug("Cleanup completed")
                except Exception as e:
                    logger.warning(f"Cleanup failed: {e}")
