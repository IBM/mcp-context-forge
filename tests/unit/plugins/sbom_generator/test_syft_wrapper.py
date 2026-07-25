#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/sbom_generator/test_syft_wrapper.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn

Unit tests for Syft subprocess wrapper.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from plugins.sbom_generator.errors import ExtractionError
from plugins.sbom_generator.extraction import syft_wrapper


class _FakeProcess:
    """Simple fake subprocess process object for wrapper tests."""

    def __init__(self, returncode=0, stdout=b"{}", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


class TestFindSyft:
    """Test syft binary discovery."""

    def test_find_syft_success(self):
        """When syft is on PATH, absolute path should be returned."""
        with patch("plugins.sbom_generator.extraction.syft_wrapper.shutil.which", return_value="/usr/local/bin/syft"):
            assert syft_wrapper._find_syft() == "/usr/local/bin/syft"

    def test_find_syft_missing(self):
        """Missing syft binary should raise ExtractionError."""
        with patch("plugins.sbom_generator.extraction.syft_wrapper.shutil.which", return_value=None):
            with pytest.raises(ExtractionError, match="not found"):
                syft_wrapper._find_syft()


class TestRunSyft:
    """Test run_syft subprocess execution and error handling."""

    @pytest.mark.asyncio
    async def test_run_syft_success(self):
        """Successful syft execution should return parsed JSON."""
        fake_process = _FakeProcess(stdout=b'{"components": []}')

        with (
            patch("plugins.sbom_generator.extraction.syft_wrapper._find_syft", return_value="/usr/local/bin/syft"),
            patch(
                "plugins.sbom_generator.extraction.syft_wrapper.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=fake_process),
            ),
        ):
            result = await syft_wrapper.run_syft("nginx:latest", fmt="cyclonedx", timeout=60)

        assert result == {"components": []}

    @pytest.mark.asyncio
    async def test_run_syft_invalid_format(self):
        """Unsupported output format should raise ExtractionError."""
        with pytest.raises(ExtractionError, match="Unsupported format"):
            await syft_wrapper.run_syft("nginx:latest", fmt="invalid", timeout=60)

    @pytest.mark.asyncio
    async def test_run_syft_non_zero_exit(self):
        """Non-zero exit code should raise ExtractionError with stderr details."""
        fake_process = _FakeProcess(returncode=2, stdout=b"", stderr=b"permission denied")

        with (
            patch("plugins.sbom_generator.extraction.syft_wrapper._find_syft", return_value="/usr/local/bin/syft"),
            patch(
                "plugins.sbom_generator.extraction.syft_wrapper.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=fake_process),
            ),
        ):
            with pytest.raises(ExtractionError) as exc_info:
                await syft_wrapper.run_syft("nginx:latest")

        assert "exited with code" in str(exc_info.value)
        assert exc_info.value.details["returncode"] == 2
        assert "permission denied" in exc_info.value.details["stderr"]

    @pytest.mark.asyncio
    async def test_run_syft_empty_output(self):
        """Empty stdout should raise ExtractionError."""
        fake_process = _FakeProcess(stdout=b"   ")

        with (
            patch("plugins.sbom_generator.extraction.syft_wrapper._find_syft", return_value="/usr/local/bin/syft"),
            patch(
                "plugins.sbom_generator.extraction.syft_wrapper.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=fake_process),
            ),
        ):
            with pytest.raises(ExtractionError, match="produced no output"):
                await syft_wrapper.run_syft("nginx:latest")

    @pytest.mark.asyncio
    async def test_run_syft_invalid_json(self):
        """Malformed JSON output should raise ExtractionError."""
        fake_process = _FakeProcess(stdout=b"not-json")

        with (
            patch("plugins.sbom_generator.extraction.syft_wrapper._find_syft", return_value="/usr/local/bin/syft"),
            patch(
                "plugins.sbom_generator.extraction.syft_wrapper.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=fake_process),
            ),
        ):
            with pytest.raises(ExtractionError, match="parse Syft JSON"):
                await syft_wrapper.run_syft("nginx:latest")

    @pytest.mark.asyncio
    async def test_run_syft_timeout(self):
        """Timeout should kill process and raise ExtractionError."""
        fake_process = _FakeProcess(stdout=b'{"components": []}')
        call_count = {"value": 0}

        async def _wait_for_with_one_timeout(awaitable, timeout):
            call_count["value"] += 1
            if call_count["value"] == 1:
                # Prevent "coroutine was never awaited" warning when simulating timeout.
                if hasattr(awaitable, "close"):
                    awaitable.close()
                raise asyncio.TimeoutError()
            return await awaitable

        with (
            patch("plugins.sbom_generator.extraction.syft_wrapper._find_syft", return_value="/usr/local/bin/syft"),
            patch(
                "plugins.sbom_generator.extraction.syft_wrapper.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=fake_process),
            ),
            patch(
                "plugins.sbom_generator.extraction.syft_wrapper.asyncio.wait_for",
                new=AsyncMock(side_effect=_wait_for_with_one_timeout),
            ),
        ):
            with pytest.raises(ExtractionError, match="timed out"):
                await syft_wrapper.run_syft("nginx:latest", timeout=1)

        assert fake_process.killed is True


class TestGetSyftVersion:
    """Test syft version retrieval behavior."""

    @pytest.mark.asyncio
    async def test_get_syft_version_success(self):
        """Wrapper should return parsed version string."""
        fake_process = _FakeProcess(stdout=b'{"version": "1.10.0"}')

        with (
            patch("plugins.sbom_generator.extraction.syft_wrapper._find_syft", return_value="/usr/local/bin/syft"),
            patch(
                "plugins.sbom_generator.extraction.syft_wrapper.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=fake_process),
            ),
        ):
            version = await syft_wrapper.get_syft_version()

        assert version == "1.10.0"

    @pytest.mark.asyncio
    async def test_get_syft_version_returns_none_on_error(self):
        """Wrapper should swallow errors and return None when version lookup fails."""
        with patch("plugins.sbom_generator.extraction.syft_wrapper._find_syft", side_effect=RuntimeError("no syft")):
            version = await syft_wrapper.get_syft_version()

        assert version is None
