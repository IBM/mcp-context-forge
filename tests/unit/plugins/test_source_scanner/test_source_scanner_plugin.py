#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for SourceScannerPlugin.

Location: tests/unit/plugins/test_source_scanner/test_source_scanner_plugin.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import PluginConfig
from plugins.source_scanner.errors import SourceScannerError
from plugins.source_scanner.models import Finding, ScanResult, ScanSummary
from plugins.source_scanner.repo_fetcher import Workspace
from plugins.source_scanner.source_scanner import SourceScannerPlugin


class TestSourceScannerPluginInitialization:
    """Test SourceScannerPlugin initialization."""

    def test_init_with_default_config(self) -> None:
        """Test initialization with default config."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )

        plugin = SourceScannerPlugin(config)

        assert plugin is not None
        assert plugin._cfg is not None
        assert plugin._semgrep_runner is not None
        assert plugin._bandit_runner is not None

    def test_init_with_custom_config(self) -> None:
        """Test initialization with custom configuration."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={
                "severity_threshold": "WARNING",
                "fail_on_critical": True,
                "scan_timeout_seconds": 600,
                "semgrep": {
                    "enabled": True,
                    "rulesets": ["p/security-audit"],
                },
            },
        )

        plugin = SourceScannerPlugin(config)

        assert plugin._cfg.severity_threshold == "WARNING"
        assert plugin._cfg.fail_on_critical is True

    def test_init_creates_components(self) -> None:
        """Test initialization creates all required components."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        assert plugin._repo_fetcher is not None
        assert plugin._language_detector is not None
        assert plugin._semgrep_runner is not None
        assert plugin._bandit_runner is not None
        assert plugin._normalizer is not None
        assert plugin._policy_checker is not None


class TestSourceScannerPluginScan:
    """Test SourceScannerPlugin.scan() public method."""

    @pytest.mark.asyncio
    async def test_scan_successful(self) -> None:
        """Test successful scan workflow."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        # Mock the workflow
        with patch.object(plugin, "_scan_workflow") as mock_workflow:
            mock_result = ScanResult(
                repo_url="https://github.com/org/repo",
                ref="main",
                commit_sha="abc123",
                languages=["python"],
                findings=[],
                summary=ScanSummary(error_count=0, warning_count=0, info_count=0),
                blocked=False,
                block_reason=None,
            )
            mock_workflow.return_value = mock_result

            result = await plugin.scan("https://github.com/org/repo", "main")

            assert result == mock_result
            mock_workflow.assert_called_once_with("https://github.com/org/repo", "main")

    @pytest.mark.asyncio
    async def test_scan_without_ref(self) -> None:
        """Test scan without specifying ref (uses default branch)."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        with patch.object(plugin, "_scan_workflow") as mock_workflow:
            mock_result = ScanResult(
                repo_url="https://github.com/org/repo",
                ref=None,
                commit_sha="abc123",
                languages=["python"],
                findings=[],
                summary=ScanSummary(error_count=0, warning_count=0, info_count=0),
                blocked=False,
                block_reason=None,
            )
            mock_workflow.return_value = mock_result

            result = await plugin.scan("https://github.com/org/repo")

            assert result == mock_result
            mock_workflow.assert_called_once_with("https://github.com/org/repo", None)


class TestSourceScannerPluginWorkflow:
    """Test SourceScannerPlugin._scan_workflow() method."""

    @pytest.mark.asyncio
    async def test_scan_workflow_complete_success(self) -> None:
        """Test complete successful scan workflow."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        mock_workspace = Workspace(path="/tmp/repo", commit_sha="abc123def456")
        mock_cleanup = MagicMock()

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            with patch.object(plugin._language_detector, "detect") as mock_detect:
                with patch.object(plugin._semgrep_runner, "run") as mock_semgrep:
                    with patch.object(plugin._bandit_runner, "run") as mock_bandit:
                        with patch.object(plugin._normalizer, "merge_dedup") as mock_merge:
                            with patch.object(plugin._policy_checker, "evaluate") as mock_policy:
                                mock_fetch.return_value = (mock_workspace, mock_cleanup)
                                mock_detect.return_value = ["python", "javascript"]
                                mock_semgrep.return_value = []
                                mock_bandit.return_value = []
                                mock_merge.return_value = []
                                mock_policy.return_value = MagicMock(blocked=False, reason=None)

                                result = await plugin._scan_workflow(
                                    "https://github.com/org/repo",
                                    "main",
                                )

                                assert result.repo_url == "https://github.com/org/repo"
                                assert result.commit_sha == "abc123def456"
                                assert result.languages == ["python", "javascript"]
                                assert result.blocked is False
                                mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_workflow_with_findings(self) -> None:
        """Test scan workflow with security findings."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        mock_workspace = Workspace(path="/tmp/repo", commit_sha="abc123def456")
        mock_cleanup = MagicMock()

        finding = Finding(
            scanner="semgrep",
            severity="ERROR",
            rule_id="security-001",
            message="SQL injection vulnerability",
            file_path="app.py",
            line=42,
            column=10,
            code_snippet="query = f'SELECT * FROM users WHERE id={id}'",
            help_url="https://example.com/rules/security-001",
        )

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            with patch.object(plugin._language_detector, "detect") as mock_detect:
                with patch.object(plugin._semgrep_runner, "run") as mock_semgrep:
                    with patch.object(plugin._bandit_runner, "run") as mock_bandit:
                        with patch.object(plugin._normalizer, "merge_dedup") as mock_merge:
                            with patch.object(plugin._policy_checker, "evaluate") as mock_policy:
                                mock_fetch.return_value = (mock_workspace, mock_cleanup)
                                mock_detect.return_value = ["python"]
                                mock_semgrep.return_value = [finding]
                                mock_bandit.return_value = []
                                mock_merge.return_value = [finding]
                                mock_policy.return_value = MagicMock(
                                    blocked=True,
                                    reason="Critical findings detected",
                                )

                                result = await plugin._scan_workflow(
                                    "https://github.com/org/repo",
                                    "main",
                                )

                                assert len(result.findings) == 1
                                assert result.findings[0].severity == "ERROR"
                                assert result.blocked is True
                                assert result.summary.error_count == 1

    @pytest.mark.asyncio
    async def test_scan_workflow_semgrep_disabled(self) -> None:
        """Test scan workflow with Semgrep disabled."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={"semgrep": {"enabled": False}},
        )
        plugin = SourceScannerPlugin(config)

        mock_workspace = Workspace(path="/tmp/repo", commit_sha="abc123def456")
        mock_cleanup = MagicMock()

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            with patch.object(plugin._language_detector, "detect") as mock_detect:
                with patch.object(plugin._semgrep_runner, "run") as mock_semgrep:
                    with patch.object(plugin._bandit_runner, "run") as mock_bandit:
                        with patch.object(plugin._normalizer, "merge_dedup") as mock_merge:
                            with patch.object(plugin._policy_checker, "evaluate") as mock_policy:
                                mock_fetch.return_value = (mock_workspace, mock_cleanup)
                                mock_detect.return_value = ["python"]
                                mock_bandit.return_value = []
                                mock_merge.return_value = []
                                mock_policy.return_value = MagicMock(blocked=False, reason=None)

                                await plugin._scan_workflow(
                                    "https://github.com/org/repo",
                                    "main",
                                )

                                # Semgrep should not be called
                                mock_semgrep.assert_not_called()
                                mock_bandit.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_workflow_bandit_only_for_python(self) -> None:
        """Test Bandit is only run when Python is detected."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        mock_workspace = Workspace(path="/tmp/repo", commit_sha="abc123def456")
        mock_cleanup = MagicMock()

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            with patch.object(plugin._language_detector, "detect") as mock_detect:
                with patch.object(plugin._semgrep_runner, "run") as mock_semgrep:
                    with patch.object(plugin._bandit_runner, "run") as mock_bandit:
                        with patch.object(plugin._normalizer, "merge_dedup") as mock_merge:
                            with patch.object(plugin._policy_checker, "evaluate") as mock_policy:
                                mock_fetch.return_value = (mock_workspace, mock_cleanup)
                                # Only JavaScript, no Python
                                mock_detect.return_value = ["javascript"]
                                mock_semgrep.return_value = []
                                mock_merge.return_value = []
                                mock_policy.return_value = MagicMock(blocked=False, reason=None)

                                await plugin._scan_workflow(
                                    "https://github.com/org/repo",
                                    "main",
                                )

                                # Bandit should not be called because Python not detected
                                mock_bandit.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_workflow_clone_failure(self) -> None:
        """Test scan workflow handles clone failure."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            mock_fetch.side_effect = Exception("Clone failed")

            with pytest.raises(SourceScannerError):
                await plugin._scan_workflow("https://github.com/org/repo", "main")

    @pytest.mark.asyncio
    async def test_scan_workflow_cleanup_on_error(self) -> None:
        """Test cleanup is called even if scan fails."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        mock_workspace = Workspace(path="/tmp/repo", commit_sha="abc123def456")
        mock_cleanup = MagicMock()

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            with patch.object(plugin._language_detector, "detect") as mock_detect:
                mock_fetch.return_value = (mock_workspace, mock_cleanup)
                mock_detect.side_effect = Exception("Detection failed")

                with pytest.raises(SourceScannerError):
                    await plugin._scan_workflow("https://github.com/org/repo", "main")

                # Cleanup should still be called
                mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_workflow_semgrep_timeout(self) -> None:
        """Test scan workflow handles Semgrep timeout."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        mock_workspace = Workspace(path="/tmp/repo", commit_sha="abc123def456")
        mock_cleanup = MagicMock()

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            with patch.object(plugin._language_detector, "detect") as mock_detect:
                with patch.object(plugin._semgrep_runner, "run") as mock_semgrep:
                    with patch.object(plugin._bandit_runner, "run") as mock_bandit:
                        with patch.object(plugin._normalizer, "merge_dedup") as mock_merge:
                            with patch.object(plugin._policy_checker, "evaluate") as mock_policy:
                                mock_fetch.return_value = (mock_workspace, mock_cleanup)
                                mock_detect.return_value = ["python"]
                                # Semgrep times out
                                mock_semgrep.side_effect = TimeoutError("Scan timeout")
                                mock_bandit.return_value = []
                                mock_merge.return_value = []
                                mock_policy.return_value = MagicMock(blocked=False, reason=None)

                                with pytest.raises(SourceScannerError):
                                    await plugin._scan_workflow(
                                        "https://github.com/org/repo",
                                        "main",
                                    )

                                # Cleanup should still be called
                                mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_workflow_multiple_findings_counted(self) -> None:
        """Test scan workflow correctly counts findings by severity."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        mock_workspace = Workspace(path="/tmp/repo", commit_sha="abc123def456")
        mock_cleanup = MagicMock()

        findings = [
            Finding(
                scanner="semgrep",
                severity="ERROR",
                rule_id="rule-001",
                message="Critical issue",
                file_path="app.py",
                line=10,
                column=5,
                code_snippet="bad_code()",
                help_url="https://example.com/rule-001",
            ),
            Finding(
                scanner="semgrep",
                severity="WARNING",
                rule_id="rule-002",
                message="Warning issue",
                file_path="app.py",
                line=20,
                column=5,
                code_snippet="questionable_code()",
                help_url="https://example.com/rule-002",
            ),
            Finding(
                scanner="bandit",
                severity="INFO",
                rule_id="rule-003",
                message="Info issue",
                file_path="test.py",
                line=30,
                column=5,
                code_snippet="info_code()",
                help_url="https://example.com/rule-003",
            ),
        ]

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            with patch.object(plugin._language_detector, "detect") as mock_detect:
                with patch.object(plugin._semgrep_runner, "run") as mock_semgrep:
                    with patch.object(plugin._bandit_runner, "run") as mock_bandit:
                        with patch.object(plugin._normalizer, "merge_dedup") as mock_merge:
                            with patch.object(plugin._policy_checker, "evaluate") as mock_policy:
                                mock_fetch.return_value = (mock_workspace, mock_cleanup)
                                mock_detect.return_value = ["python"]
                                mock_semgrep.return_value = findings[:2]
                                mock_bandit.return_value = findings[2:]
                                mock_merge.return_value = findings
                                mock_policy.return_value = MagicMock(blocked=False, reason=None)

                                result = await plugin._scan_workflow(
                                    "https://github.com/org/repo",
                                    "main",
                                )

                                assert result.summary.error_count == 1
                                assert result.summary.warning_count == 1
                                assert result.summary.info_count == 1

    @pytest.mark.asyncio
    async def test_scan_workflow_empty_findings(self) -> None:
        """Test scan workflow with no findings detected."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        mock_workspace = Workspace(path="/tmp/repo", commit_sha="abc123def456")
        mock_cleanup = MagicMock()

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            with patch.object(plugin._language_detector, "detect") as mock_detect:
                with patch.object(plugin._semgrep_runner, "run") as mock_semgrep:
                    with patch.object(plugin._bandit_runner, "run") as _:
                        with patch.object(plugin._normalizer, "merge_dedup") as mock_merge:
                            with patch.object(plugin._policy_checker, "evaluate") as mock_policy:
                                mock_fetch.return_value = (mock_workspace, mock_cleanup)
                                mock_detect.return_value = ["go"]
                                mock_semgrep.return_value = []
                                # Bandit not called for Go
                                mock_merge.return_value = []
                                mock_policy.return_value = MagicMock(blocked=False, reason=None)

                                result = await plugin._scan_workflow(
                                    "https://github.com/org/repo",
                                    "main",
                                )

                                assert len(result.findings) == 0
                                assert result.summary.error_count == 0
                                assert result.summary.warning_count == 0
                                assert result.summary.info_count == 0

    @pytest.mark.asyncio
    async def test_scan_workflow_policy_blocks(self) -> None:
        """Test scan workflow respects policy decision to block."""
        config = PluginConfig(
            name="test-scanner",
            kind="source_scanner",
            namespace="plugins",
            version="1.0.0",
            config={},
        )
        plugin = SourceScannerPlugin(config)

        mock_workspace = Workspace(path="/tmp/repo", commit_sha="abc123def456")
        mock_cleanup = MagicMock()

        finding = Finding(
            scanner="semgrep",
            severity="ERROR",
            rule_id="critical",
            message="Critical vulnerability",
            file_path="app.py",
            line=1,
            column=1,
            code_snippet="code",
            help_url="https://example.com",
        )

        with patch.object(plugin._repo_fetcher, "fetch") as mock_fetch:
            with patch.object(plugin._language_detector, "detect") as mock_detect:
                with patch.object(plugin._semgrep_runner, "run") as mock_semgrep:
                    with patch.object(plugin._bandit_runner, "run") as mock_bandit:
                        with patch.object(plugin._normalizer, "merge_dedup") as mock_merge:
                            with patch.object(plugin._policy_checker, "evaluate") as mock_policy:
                                mock_fetch.return_value = (mock_workspace, mock_cleanup)
                                mock_detect.return_value = ["python"]
                                mock_semgrep.return_value = [finding]
                                mock_bandit.return_value = []
                                mock_merge.return_value = [finding]
                                mock_policy.return_value = MagicMock(
                                    blocked=True,
                                    reason="ERROR threshold exceeded",
                                )

                                result = await plugin._scan_workflow(
                                    "https://github.com/org/repo",
                                    "main",
                                )

                                assert result.blocked is True
                                assert "ERROR threshold exceeded" in result.block_reason
