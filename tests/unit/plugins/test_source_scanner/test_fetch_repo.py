#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for RepoFetcher.

Location: tests/unit/plugins/test_source_scanner/test_fetch_repo.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from pathlib import Path
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.errors import CloneTimeoutError, RepoFetchError, RepoSizeLimitError
from plugins.source_scanner.repo_fetcher import RepoFetcher
from plugins.source_scanner.utils.exec import ExecResult


class TestRepoFetcherFetch:
    """Test RepoFetcher.fetch() method."""

    @pytest.mark.asyncio
    async def test_fetch_successful_branch(self) -> None:
        """Test successful clone with branch ref."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
            with patch("plugins.source_scanner.repo_fetcher.tempfile.mkdtemp") as mock_mkdtemp:
                mock_mkdtemp.return_value = "/tmp/test_repo"

                # Mock successful clone
                mock_run.side_effect = [
                    ExecResult(returncode=0, stdout="", stderr=""),  # clone
                    ExecResult(returncode=0, stdout="abc123def456\n", stderr=""),  # get commit sha
                ]

                workspace, cleanup = await fetcher.fetch("https://github.com/org/repo", ref="main")

                assert workspace.path == "/tmp/test_repo"
                assert workspace.commit_sha == "abc123def456"
                assert callable(cleanup)

    @pytest.mark.asyncio
    async def test_fetch_successful_commit_sha(self) -> None:
        """Test successful clone with commit SHA ref."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
            with patch("plugins.source_scanner.repo_fetcher.tempfile.mkdtemp") as mock_mkdtemp:
                mock_mkdtemp.return_value = "/tmp/test_repo"

                # Mock full clone + checkout + get commit sha
                # Order: clone, checkout, rev-parse (get commit sha)
                async def mock_run_async(*args, **kwargs):
                    if "checkout" in args[0]:
                        return ExecResult(returncode=0, stdout="", stderr="")
                    elif "rev-parse" in args[0]:
                        return ExecResult(returncode=0, stdout="abc123def456789abc123def456789abc1234\n", stderr="")
                    else:  # clone
                        return ExecResult(returncode=0, stdout="", stderr="")

                mock_run.side_effect = mock_run_async

                commit = "abc123def456789abc123def456789abc1234"
                workspace, cleanup = await fetcher.fetch(
                    "https://github.com/org/repo",
                    ref=commit,
                )

                assert workspace.commit_sha == "abc123def456789abc123def456789abc1234"
                assert callable(cleanup)

    @pytest.mark.asyncio
    async def test_fetch_clone_timeout(self) -> None:
        """Test clone timeout error."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
            with patch("plugins.source_scanner.repo_fetcher.tempfile.mkdtemp") as mock_mkdtemp:
                with patch("plugins.source_scanner.repo_fetcher.shutil.rmtree") as mock_rmtree:
                    mock_mkdtemp.return_value = "/tmp/test_repo"
                    mock_run.return_value = ExecResult(
                        returncode=124,
                        stdout="",
                        stderr="timeout",
                        timed_out=True,
                    )

                    with pytest.raises(CloneTimeoutError):
                        await fetcher.fetch("https://github.com/org/repo", clone_timeout=5)

                    mock_rmtree.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_clone_failure(self) -> None:
        """Test clone command failure."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
            with patch("plugins.source_scanner.repo_fetcher.tempfile.mkdtemp") as mock_mkdtemp:
                with patch("plugins.source_scanner.repo_fetcher.shutil.rmtree") as mock_rmtree:
                    mock_mkdtemp.return_value = "/tmp/test_repo"
                    mock_run.return_value = ExecResult(
                        returncode=1,
                        stdout="",
                        stderr="Repository not found",
                    )

                    with pytest.raises(RepoFetchError):
                        await fetcher.fetch("https://github.com/org/nonexistent")

                    mock_rmtree.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_checkout_with_failure_logs_warning(self) -> None:
        """Test checkout command failure logs warning but doesn't raise."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
            with patch("plugins.source_scanner.repo_fetcher.tempfile.mkdtemp") as mock_mkdtemp:
                mock_mkdtemp.return_value = "/tmp/test_repo"

                # Clone succeeds, checkout fails, get_commit_sha fails
                async def mock_run_async(*args, **kwargs):
                    if "checkout" in args[0]:
                        return ExecResult(returncode=1, stdout="", stderr="fatal: reference not found")
                    elif "rev-parse" in args[0]:
                        return ExecResult(returncode=1, stdout="", stderr="fatal: not a git repository")
                    else:  # clone
                        return ExecResult(returncode=0, stdout="", stderr="")

                mock_run.side_effect = mock_run_async

                commit = "abc123def456789abc123def456789abc1234"
                # Should not raise - code logs warning and continues with "unknown" commit sha
                workspace, cleanup = await fetcher.fetch(
                    "https://github.com/org/repo",
                    ref=commit,
                )

                assert workspace.commit_sha == "unknown"  # Fallback when commit SHA fetch fails

    @pytest.mark.asyncio
    async def test_fetch_size_limit_exceeded(self) -> None:
        """Test repository size limit exceeded."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
            with patch("plugins.source_scanner.repo_fetcher.tempfile.mkdtemp") as mock_mkdtemp:
                with patch("plugins.source_scanner.repo_fetcher.shutil.rmtree") as mock_rmtree:
                    with patch.object(fetcher, "_get_dir_size_mb") as mock_size:
                        mock_mkdtemp.return_value = "/tmp/test_repo"
                        mock_run.return_value = ExecResult(returncode=0, stdout="", stderr="")
                        mock_size.return_value = 750.0  # Exceeds 500MB limit

                        with pytest.raises(RepoSizeLimitError):
                            await fetcher.fetch(
                                "https://github.com/org/repo",
                                max_size_mb=500,
                            )

                        mock_rmtree.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_with_github_token(self) -> None:
        """Test fetch with GitHub token injection."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
            with patch("plugins.source_scanner.repo_fetcher.tempfile.mkdtemp") as mock_mkdtemp:
                mock_mkdtemp.return_value = "/tmp/test_repo"

                async def mock_run_async(*args, **kwargs):
                    if "rev-parse" in args[0]:
                        return ExecResult(returncode=0, stdout="sha123\n", stderr="")
                    else:
                        return ExecResult(returncode=0, stdout="", stderr="")

                mock_run.side_effect = mock_run_async

                await fetcher.fetch(
                    "https://github.com/org/repo",
                    github_token="ghp_token123",
                )

                # Verify token was injected in first call
                call_args = mock_run.call_args_list[0]
                cmd = call_args[0][0]
                # Token is in one of the command args
                cmd_str = str(cmd)
                assert "ghp_token123@github.com" in cmd_str

    @pytest.mark.asyncio
    async def test_fetch_cleanup_on_exception(self) -> None:
        """Test cleanup is called when fetch raises exception."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.tempfile.mkdtemp") as mock_mkdtemp:
            with patch("plugins.source_scanner.repo_fetcher.shutil.rmtree") as _:
                with patch.object(fetcher, "_cleanup") as mock_cleanup:
                    mock_mkdtemp.return_value = "/tmp/test_repo"

                    with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
                        mock_run.side_effect = Exception("Unexpected error")

                        with pytest.raises(Exception):
                            await fetcher.fetch("https://github.com/org/repo")

                        mock_cleanup.assert_called_once_with("/tmp/test_repo")


class TestRepoFetcherHelpers:
    """Test RepoFetcher helper methods."""

    def test_inject_token_github_url(self) -> None:
        """Test GitHub token injection for GitHub URLs."""
        fetcher = RepoFetcher()
        result = fetcher._inject_token(
            "https://github.com/org/repo",
            "ghp_token123",
        )

        assert result == "https://ghp_token123@github.com/org/repo"

    def test_inject_token_non_github_url(self) -> None:
        """Test token injection is skipped for non-GitHub URLs."""
        fetcher = RepoFetcher()
        result = fetcher._inject_token(
            "https://gitlab.com/org/repo",
            "token123",
        )

        assert result == "https://gitlab.com/org/repo"

    def test_inject_token_no_token(self) -> None:
        """Test token injection is skipped when no token provided."""
        fetcher = RepoFetcher()
        result = fetcher._inject_token(
            "https://github.com/org/repo",
            None,
        )

        assert result == "https://github.com/org/repo"

    def test_looks_like_commit_sha_valid(self) -> None:
        """Test commit SHA validation for valid SHA."""
        fetcher = RepoFetcher()
        # Exactly 40 hex characters for a git SHA
        sha = "abc123def456789abc123def456789abc123456f"

        assert fetcher._looks_like_commit_sha(sha) is True

    def test_looks_like_commit_sha_valid_uppercase(self) -> None:
        """Test commit SHA validation with uppercase characters."""
        fetcher = RepoFetcher()
        # Exactly 40 hex characters for a git SHA
        sha = "ABC123DEF456789ABC123DEF456789ABC123456F"

        assert fetcher._looks_like_commit_sha(sha) is True

    def test_looks_like_commit_sha_invalid_length(self) -> None:
        """Test commit SHA validation rejects invalid length."""
        fetcher = RepoFetcher()

        assert fetcher._looks_like_commit_sha("abc123") is False
        assert fetcher._looks_like_commit_sha("abc123" * 10) is False

    def test_looks_like_commit_sha_invalid_characters(self) -> None:
        """Test commit SHA validation rejects non-hex characters."""
        fetcher = RepoFetcher()
        sha = "zzz123def4567890abc123def4567890abc1234"

        assert fetcher._looks_like_commit_sha(sha) is False

    @pytest.mark.asyncio
    async def test_get_commit_sha_success(self) -> None:
        """Test getting commit SHA from repository."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
            mock_run.return_value = ExecResult(
                returncode=0,
                stdout="abc123def456\n",
                stderr="",
            )

            sha = await fetcher._get_commit_sha("/tmp/test_repo")

            assert sha == "abc123def456"

    @pytest.mark.asyncio
    async def test_get_commit_sha_failure(self) -> None:
        """Test getting commit SHA handles failure gracefully."""
        fetcher = RepoFetcher()

        with patch("plugins.source_scanner.repo_fetcher.run_command") as mock_run:
            mock_run.return_value = ExecResult(
                returncode=1,
                stdout="",
                stderr="fatal: not a git repository",
            )

            sha = await fetcher._get_commit_sha("/tmp/test_repo")

            assert sha == "unknown"

    def test_get_dir_size_mb_empty(self, tmp_path: Path) -> None:
        """Test directory size calculation for empty directory."""
        fetcher = RepoFetcher()
        size = fetcher._get_dir_size_mb(str(tmp_path))

        assert size == 0.0

    def test_get_dir_size_mb_with_files(self, tmp_path: Path) -> None:
        """Test directory size calculation with files."""
        fetcher = RepoFetcher()

        # Create test files
        (tmp_path / "file1.txt").write_text("a" * 1024)  # 1KB
        (tmp_path / "file2.txt").write_text("b" * 1024)  # 1KB

        size = fetcher._get_dir_size_mb(str(tmp_path))

        # Should be approximately 2KB / (1024 * 1024) ≈ 0.0019 MB
        assert 0.001 < size < 0.01

    def test_get_dir_size_mb_recursive(self, tmp_path: Path) -> None:
        """Test directory size calculation includes subdirectories."""
        fetcher = RepoFetcher()

        # Create nested structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("x" * 2048)  # 2KB

        size = fetcher._get_dir_size_mb(str(tmp_path))

        assert 0.001 < size < 0.01

    def test_cleanup_success(self, tmp_path: Path) -> None:
        """Test cleanup removes directory."""
        fetcher = RepoFetcher()
        test_dir = str(tmp_path / "cleanup_test")
        Path(test_dir).mkdir()

        assert Path(test_dir).exists()

        fetcher._cleanup(test_dir)

        assert not Path(test_dir).exists()

    def test_cleanup_nonexistent_directory(self) -> None:
        """Test cleanup handles nonexistent directory gracefully."""
        fetcher = RepoFetcher()

        # Should not raise
        fetcher._cleanup("/nonexistent/path/that/does/not/exist")
