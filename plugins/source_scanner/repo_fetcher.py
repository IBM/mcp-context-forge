#!/usr/bin/env python3
# -- coding: utf-8 --
"""
Location: ./plugins/source_scanner/repo_fetcher.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo, Agnetha

Handles git clone, checkout and workspace cleanup
"""

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
    """Cloned repo workspace"""

    path: str
    commit_sha: str


class RepoFetcher:
    """Fetch and manage repo workspaces"""

    async def fetch(
        self,
        repo_url: str,
        ref: Optional[str] = None,
        clone_timeout: int = 120,
        max_size_mb: Optional[int] = 500,
    ) -> Tuple[Workspace, Callable[[], None]]:
        """
        Clone repository and checkout ref.

        Args:
            repo_url: Git repository URL
            ref: Branch/tag/commit to checkout (default: default branch)
            clone_timeout: Timeout for clone operation in seconds
            max_size_mb: Maximum repo size in MB (None = no limit)

        Returns:
            Tuple of (Workspace, cleanup_function)

        Raises:
            CloneTimeoutError: If clone exceeds timeout
            RepoSizeLimitError: If repo exceeds size limit
            RepoFetchError: For other fetch failures
        """
        temp_dir = tempfile.mkdtemp(prefix="source_scanner_")

        try:
            logger.info(f"Cloning {repo_url} to {temp_dir}")

            cmd = ["git", "clone", "--depth", "1"]
            if ref:
                cmd.extend(["--branch", ref])
            cmd.extend(["--", repo_url, temp_dir])

            result = await run_command(cmd, timeout_seconds=clone_timeout)

            if result.timed_out:
                raise CloneTimeoutError(f"Clone exceeded {clone_timeout}s timeout")

            if result.returncode != 0:
                raise RepoFetchError(f"Clone failed: {result.stderr}")

            if max_size_mb:
                size_mb = self._get_dir_size_mb(temp_dir)
                if size_mb > max_size_mb:
                    raise RepoSizeLimitError(f"Repository size {size_mb}MB exceeds limit {max_size_mb}MB")
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

    async def _get_commit_sha(self, repo_path: str) -> str:
        """Get current commit SHA."""
        result = await run_command(["git", "rev-parse", "HEAD"], cwd=repo_path, timeout_seconds=5)

        if result.returncode != 0:
            return "unknown"

        return result.stdout.strip()

    def _get_dir_size_mb(self, path: str) -> float:
        """Calculate directory size in MB."""
        total = 0
        for entry in Path(path).rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
        return total / (1024 * 1024)

    def _cleanup(self, path: str) -> None:
        """Remove temporary directory."""
        try:
            shutil.rmtree(path, ignore_errors=True)
            logger.debug(f"Cleaned up {path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {path}: {e}")
