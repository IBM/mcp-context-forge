#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/container_scanner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

ContainerScannerPlugin — orchestrates the full scan pipeline:
  cache lookup → auth resolution → scanner execution →
  policy evaluation → result construction → cache store.

Plugin hooks (server_pre_register, runtime_pre_deploy) are not yet wired;
use scan() directly for now.
"""

# Future
from __future__ import annotations

# Standard
import datetime
import logging
from typing import List
from collections import Counter

# First-Party
from mcpgateway.plugins.framework import Plugin, PluginConfig

# Local
from plugins.container_scanner.auth.auth_resolver import AuthResolver
from plugins.container_scanner.cache.cache_manager import CacheManager
from plugins.container_scanner.config import ScannerConfig
from plugins.container_scanner.policy.policy_evaluator import PolicyEvaluator
from plugins.container_scanner.scanners.grype_runner import GrypeRunner
from plugins.container_scanner.scanners.trivy_runner import TrivyRunner
from plugins.container_scanner.types import ScanResult, Summary, Vulnerability
from plugins.container_scanner.storage.repository import ScanResultRepository

logger = logging.getLogger(__name__)


class ContainerScannerPlugin(Plugin):
    """Gateway plugin that scans container images for CVEs before deployment.

    Orchestrates: cache → auth → scanner CLI → policy → result.
    Hooks (server_pre_register, runtime_pre_deploy) are added separately.

    Args:
        config: Framework-level plugin configuration.  Scanner-specific
            settings are read from ``config.config`` and validated into
            a :class:`ScannerConfig`.
    """
    _scanner_config : ScannerConfig
    _cache : CacheManager
    _auth : AuthResolver
    _runner : TrivyRunner | GrypeRunner
    _policy : PolicyEvaluator
    _repo : ScanResultRepository

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._scanner_config = ScannerConfig(**(config.config or {}))
        self._cache = CacheManager(ttl_hours=self._scanner_config.cache_ttl_hours, enabled=self._scanner_config.cache_enabled)
        self._auth = AuthResolver(self._scanner_config)
        if self._scanner_config.scanner == "trivy":
            self._runner = TrivyRunner(self._scanner_config)
        else:
            self._runner = GrypeRunner(self._scanner_config)
        self._policy = PolicyEvaluator()
        self._repo = ScanResultRepository()

    # ------------------------------------------------------------------
    # Core scan pipeline
    # ------------------------------------------------------------------

    async def scan(self, image_ref: str, image_digest: str) -> ScanResult:
        """Run the full scan pipeline for *image_digest*.

        Args:
            image_digest: Full image reference (e.g., ``"ghcr.io/org/app:v1"``).

        Returns:
            :class:`ScanResult` with vulnerabilities, policy decision, and
            timing metadata.  Never raises — scanner errors are captured into
            ``scan_error`` and resolved via ``on_scan_error`` policy.
        """
        cfg = self._scanner_config
        start = datetime.datetime.now(datetime.timezone.utc)

        if cfg.mode == "disabled":
            return self._build_result(image_ref=image_ref, image_digest=image_digest, vulnerabilities=[], blocked=False, reason = "scan skipped", start=start)

        cached_vulns = self._cache.lookup(image_digest)
        if cached_vulns is not None:
            logger.info("Cache hit for %s — re-evaluating policy against current config", image_digest)
            decision = self._policy.evaluate(cached_vulns, cfg)
            return self._build_result(image_ref, image_digest, cached_vulns, blocked=decision.blocked, reason=decision.reason, start=start)

        auth_env = self._auth.resolve(image_ref)
        logger.debug("Auth resolved for %s: %d env vars", image_ref, len(auth_env))

        vulnerabilities: List[Vulnerability] = []
        scan_error = None
        try:
            vulnerabilities = await self._runner.run(image_ref, auth_env)
        except Exception as exc:
            scan_error = str(exc)
            logger.warning("Scan failed with error: %s", scan_error)
            if cfg.on_scan_error == "fail_closed":
                return self._build_result(image_ref=image_ref, image_digest=image_digest, vulnerabilities=vulnerabilities, blocked=True, scan_error=scan_error, start=start)
            else:
                logger.info("Scan error for %s (fail_open): allowing deployment, error recorded", image_digest)
                return self._build_result(image_ref=image_ref, image_digest=image_digest, vulnerabilities=vulnerabilities, blocked=False, scan_error=scan_error, start=start)

        decision = self._policy.evaluate(vulnerabilities, cfg)
        result = self._build_result(image_ref=image_ref, image_digest=image_digest, vulnerabilities=vulnerabilities, blocked=decision.blocked, reason=decision.reason, scan_error=scan_error, start=start)
        self._cache.store(image_digest, vulnerabilities)
        self._repo.save(result)
        return result



    def _build_result(
        self,
        image_ref:str,
        image_digest: str,
        vulnerabilities: List[Vulnerability],
        *,
        blocked: bool,
        reason: str | None = None,
        scan_error: str | None = None,
        start: datetime.datetime | None = None,
    ) -> ScanResult:
        """Construct a ScanResult from raw findings and a policy decision.

        Args:
            image_ref: Image reference that was scanned.
            vulnerabilities: Normalized vulnerability list from the scanner.
            blocked: Whether the policy decision blocks deployment.
            reason: Human-readable policy violation summary, if any.
            scan_error: Error message if the scanner subprocess failed.
            start: Scan start timestamp; defaults to now if omitted.

        Returns:
            Fully populated :class:`ScanResult`.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        if start is None:
            start = now
        duration_ms = int((now - start).total_seconds() * 1000)

        counts: Counter[str] = Counter(v.severity for v in vulnerabilities)
        summary = Summary(
            critical_count=counts["CRITICAL"],
            high_count=counts["HIGH"],
            medium_count=counts["MEDIUM"],
            low_count=counts["LOW"],
        )

        return ScanResult(
            image_ref=image_ref,
            image_digest=image_digest,
            scanners=self._scanner_config.scanner,
            scan_time=start,
            duration_ms=duration_ms,
            vulnerabilities=vulnerabilities,
            summary=summary,
            blocked=blocked,
            reason=reason,
            scan_error=scan_error,
        )
