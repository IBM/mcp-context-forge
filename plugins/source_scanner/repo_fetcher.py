#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repository fetching and workspace management.

Location: ./plugins/source_scanner/repo_fetcher.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo, Agnetha

Handles git clone, checkout and workspace cleanup.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Optional, Tuple

# Local
from .errors import CloneTimeoutError, RepoFetchError, RepoSizeLimitError
from .utils.exec import run_command

logger = logging.getLogger(__name__)


@dataclass
class Workspace:
    """Cloned repository workspace.

    Attributes:
        path: Temporary directory path containing the repository.
        commit_sha: Git commit SHA of the checked-out code.
    """

    path: str
    commit_sha: str


class RepoFetcher:
    """Fetch and manage repository workspaces."""

    async def fetch(
        self,
        repo_url: str,
        ref: Optional[str] = None,
        clone_timeout: int = 120,
        max_size_mb: Optional[int] = 500,
        github_token: Optional[str] = None,
    ) -> Tuple[Workspace, Callable[[], None]]:
        """Clone repository and checkout ref.

        Args:
            repo_url: Git repository URL
            ref: Branch/tag/commit to checkout (default: default branch)
            clone_timeout: Timeout for clone operation in seconds
            max_size_mb: Maximum repo size in MB (None = no limit)
            github_token: GitHub personal access token for private repos

        Returns:
            Tuple of (Workspace, cleanup_function)

        Raises:
            CloneTimeoutError: If clone exceeds timeout
            RepoSizeLimitError: If repo exceeds size limit
            RepoFetchError: For other fetch failures
        """
        temp_dir = tempfile.mkdtemp(prefix="source_scanner_")

        try:
            # Inject GitHub token if provided
            clone_url = self._inject_token(repo_url, github_token)

            logger.info(f"Cloning {repo_url} to {temp_dir}")

            # Build clone command
            cmd = ["git", "clone"]

            # Use shallow clone for branches/tags, full clone for commit SHAs
            if ref and self._looks_like_commit_sha(ref):
                # Full clone needed for specific commit
                logger.debug(f"Full clone (commit SHA: {ref})")
                cmd.extend(["--", clone_url, temp_dir])
            else:
                # Shallow clone for branch/tag
                logger.debug("Shallow clone (branch/tag)")
                cmd.extend(["--depth", "1"])
                if ref:
                    cmd.extend(["--branch", ref])
                cmd.extend(["--", clone_url, temp_dir])

            result = await run_command(cmd, timeout_seconds=clone_timeout)

            if result.timed_out:
                raise CloneTimeoutError(f"Clone exceeded {clone_timeout}s timeout")

            if result.returncode != 0:
                raise RepoFetchError(f"Clone failed: {result.stderr}")

            # If full clone for commit, checkout the commit
            if ref and self._looks_like_commit_sha(ref):
                logger.debug(f"Checking out commit {ref}")
                checkout_result = await run_command(["git", "checkout", ref], cwd=temp_dir, timeout_seconds=10)
                if checkout_result.returncode != 0:
                    raise RepoFetchError(f"Checkout {ref} failed: {checkout_result.stderr}")

            # Check size limit
            if max_size_mb:
                size_mb = self._get_dir_size_mb(temp_dir)
                logger.debug(f"Repository size: {size_mb:.2f}MB (limit: {max_size_mb}MB)")
                if size_mb > max_size_mb:
                    raise RepoSizeLimitError(f"Repository size {size_mb:.2f}MB exceeds limit {max_size_mb}MB")

            commit_sha = await self._get_commit_sha(temp_dir)

            workspace = Workspace(path=temp_dir, commit_sha=commit_sha)

            def cleanup_fn() -> None:
                self._cleanup(temp_dir)

            logger.info(f"Repository cloned successfully: {commit_sha}")
            return workspace, cleanup_fn

        except Exception:
            # Cleanup on failure
            self._cleanup(temp_dir)
            raise

    def _inject_token(self, repo_url: str, token: Optional[str]) -> str:
        """Inject GitHub token into repository URL if provided."""
        if not token or "github.com" not in repo_url:
            return repo_url

        # https://github.com/org/repo → https://TOKEN@github.com/org/repo
        return repo_url.replace("https://github.com/", f"https://{token}@github.com/")

    def _looks_like_commit_sha(self, ref: str) -> bool:
        """Check if ref looks like a commit SHA (40 hex characters)."""
        return len(ref) == 40 and all(c in "0123456789abcdef" for c in ref.lower())

    async def _get_commit_sha(self, repo_path: str) -> str:
        """Get current commit SHA."""
        result = await run_command(["git", "rev-parse", "HEAD"], cwd=repo_path, timeout_seconds=5)

        if result.returncode != 0:
            logger.warning("Failed to get commit SHA, using 'unknown'")
            return "unknown"

        return result.stdout.strip()

    def _get_dir_size_mb(self, path: str) -> float:
        """Calculate directory size in MB."""
        total = 0
        for entry in Path(path).rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except (OSError, PermissionError):
                    # Skip files we can't read
                    pass
        return total / (1024 * 1024)

    def _cleanup(self, path: str) -> None:
        """Remove temporary directory."""
        try:
            shutil.rmtree(path, ignore_errors=True)
            logger.debug(f"Cleaned up {path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {path}: {e}")
