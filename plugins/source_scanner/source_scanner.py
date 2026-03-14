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
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    # PluginContext,
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

# from .storage.repository import ScanRepository

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
        # Storage disabled until database integration is complete
        # self._scan_repo_store = ScanRepository(db) if self._cfg.cache_by_commit else None

        logger.info(
            "SourceScannerPlugin initialized",
            extra={
                "semgrep_enabled": self._cfg.semgrep.enabled,
                "bandit_enabled": self._cfg.bandit.enabled,
                "severity_threshold": self._cfg.severity_threshold,
                "fail_on_critical": self._cfg.fail_on_critical,
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
            # Step 1: Check cache (if enabled)
            # TODO: Implement when database integration is ready
            # if self._cfg.cache_by_commit and self._scan_repo_store:
            #     cached = await self._scan_repo_store.get_by_commit(repo_url, commit_sha)
            #     if cached and not expired:
            #         logger.info("Using cached scan results")
            #         return cached

            # Step 2: Clone & Checkout
            github_token = os.environ.get(self._cfg.github_token_env)
            workspace, cleanup_fn = await self._repo_fetcher.fetch(
                repo_url=repo_url,
                ref=ref,
                clone_timeout=self._cfg.clone_timeout_seconds,
                max_size_mb=self._cfg.max_repo_size_mb,
                github_token=github_token,
            )
            commit_sha = workspace.commit_sha

            # Step 3: Detect languages
            languages = self._language_detector.detect(workspace.path)
            logger.info(f"Detected languages: {languages}")

            # Step 4: Run scanners
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

            # Step 5: Merge & Deduplicate
            merged_findings = self._normalizer.merge_dedup(findings_by_scanner)
            logger.info(f"Total unique findings after deduplication: {len(merged_findings)}")

            # Step 6: Calculate summary
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

            # Step 7: Evaluate policy
            decision = self._policy_checker.evaluate(
                findings=merged_findings,
                threshold=self._cfg.severity_threshold,
                fail_on_critical=self._cfg.fail_on_critical,
            )

            # Step 8: Build result
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

            # Step 9: Store results (if cache enabled)
            # TODO: Implement when database integration is ready
            # if self._cfg.cache_by_commit and self._scan_repo_store:
            #     await self._scan_repo_store.save(result)
            #     logger.info("Scan results cached")

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

    # ============================================================
    # GATEWAY HOOKS - NOT YET IMPLEMENTED IN GATEWAY
    # ============================================================
    # These hooks are documented in the gateway but not yet called.
    # Uncomment when gateway implements server_pre_register and catalog_pre_deploy hooks.
    #
    # async def server_pre_register(self, payload, context) -> dict:
    #     """Hook for server registration (NOT YET IMPLEMENTED IN GATEWAY)."""
    #     logger.info("server_pre_register hook triggered")
    #     repo_url = payload.get("server", {}).get("source", {}).get("repo")
    #     ref = payload.get("server", {}).get("source", {}).get("ref")
    #
    #     if not repo_url:
    #         logger.warning("No repo_url in payload, allowing registration")
    #         return {"continue_processing": True}
    #
    #     result = await self.scan(repo_url, ref)
    #
    #     if result.blocked:
    #         return {
    #             "continue_processing": False,
    #             "violation": {
    #                 "reason": "Security vulnerabilities detected",
    #                 "description": result.block_reason,
    #                 "code": "SOURCE_SCAN_BLOCKED",
    #                 "details": {
    #                     "findings_count": len(result.findings),
    #                     "error_count": result.summary.error_count,
    #                 },
    #             },
    #         }
    #
    #     return {"continue_processing": True}
    #
    # async def catalog_pre_deploy(self, payload, context) -> dict:
    #     """Hook for catalog deployment (NOT YET IMPLEMENTED IN GATEWAY)."""
    #     logger.info("catalog_pre_deploy hook triggered")
    #     # Similar implementation to server_pre_register
    #     return {"continue_processing": True}

    """async def server_pre_register(
        self,
        payload: ServerPreRegisterPayload,
        context: PluginContext,
    ) -> ServerPreRegisterResult:
        Scan source code before server registration.

        Args:
            payload: Server registration payload.
            context: Plugin execution context.

        Returns:
            Result blocking if critical findings exist, or allowing.
        
        logger.info("server_pre_register hook triggered")

        try:
            # TODO: Extract repo_url and ref from payload
            # Example payload structure (to be confirmed):
            # payload.server.source = {
            #     "type": "github",
            #     "repo": "https://github.com/org/mcp-server",
            #     "ref": "main"  # or branch/tag/commit
            # }

            # TODO: repo_url = payload.server.source.get("repo")
            # TODO: ref = payload.server.source.get("ref")

            # TODO: if not repo_url:
            #           logger.warning("No repo_url in payload, allowing registration")
            #           return ServerPreRegisterResult(continue_processing=True)

            # TODO: result = await self._scan_workflow(repo_url, ref)

            # TODO: if result.blocked:
            #           return ServerPreRegisterResult(
            #               continue_processing=False,
            #               violation=PluginViolation(
            #                   reason="Security vulnerabilities detected",
            #                   description=result.block_reason or "Critical findings in source code",
            #                   code="SOURCE_SCAN_BLOCKED",
            #                   details={
            #                       "findings_count": len(result.findings),
            #                       "error_count": result.summary.error_count,
            #                       "warning_count": result.summary.warning_count,
            #                   },
            #               ),
            #           )

            # Placeholder: allow all registrations until implemented
            logger.warning("server_pre_register not fully implemented, allowing")
            # NOTE: Current implementation is fail-open.
            # Enforce-mode scan failure behavior will be configurable.
            return ServerPreRegisterResult(continue_processing=True)

        except Exception as e:
            logger.error(f"server_pre_register failed: {e}", exc_info=True)
            # Fail open: allow registration but log error
            # NOTE: Current implementation is fail-open.
            # Enforce-mode scan failure behavior will be configurable.
            return ServerPreRegisterResult(continue_processing=True)

    async def catalog_pre_deploy(
        self,
        payload: CatalogPreDeployPayload,
        context: PluginContext,
    ) -> CatalogPreDeployResult:
        Scan source code before catalog deployment.

        Args:
            payload: Catalog deployment payload.
            context: Plugin execution context.

        Returns:
            Result blocking if critical findings exist, or allowing.
        logger.info("catalog_pre_deploy hook triggered")

        try:
            # TODO: Extract repo_url and ref from payload
            # Example payload structure (to be confirmed):
            # payload.catalog.source = {
            #     "type": "github",
            #     "repo": "https://github.com/org/mcp-catalog",
            #     "ref": "main"
            # }

            # TODO: repo_url = payload.catalog.source.get("repo")
            # TODO: ref = payload.catalog.source.get("ref")

            # TODO: if not repo_url:
            #           logger.warning("No repo_url in payload, allowing deployment")
            #           return CatalogPreDeployResult(continue_processing=True)

            # TODO: result = await self._scan_workflow(repo_url, ref)

            # TODO: if result.blocked:
            #           return CatalogPreDeployResult(
            #               continue_processing=False,
            #               violation=PluginViolation(
            #                   reason="Security vulnerabilities detected",
            #                   description=result.block_reason or "Critical findings in source code",
            #                   code="SOURCE_SCAN_BLOCKED",
            #                   details={
            #                       "findings_count": len(result.findings),
            #                       "error_count": result.summary.error_count,
            #                       "warning_count": result.summary.warning_count,
            #                   },
            #               ),
            #           )

            # Placeholder: allow all deployments until implemented
            logger.warning("catalog_pre_deploy not fully implemented, allowing")
            return CatalogPreDeployResult(continue_processing=True)

        except Exception as e:
            logger.error(f"catalog_pre_deploy failed: {e}", exc_info=True)
            # Fail open: allow deployment but log error
            return CatalogPreDeployResult(continue_processing=True)"""
