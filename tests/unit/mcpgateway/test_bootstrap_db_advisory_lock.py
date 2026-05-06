# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_bootstrap_db_advisory_lock.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for advisory_lock retry logic in bootstrap_db.py.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.bootstrap_db import advisory_lock


class TestAdvisoryLockRetry:
    """Test advisory lock retry and backoff logic."""

    def test_advisory_lock_retry_with_backoff(self):
        """Test advisory lock retries with exponential backoff when lock is held."""
        mock_conn = MagicMock()
        mock_conn.dialect.name = "postgresql"

        # Create mock result objects
        mock_result_false = MagicMock()
        mock_result_false.scalar.return_value = False
        mock_result_true = MagicMock()
        mock_result_true.scalar.return_value = True

        # Simulate lock held for first 2 attempts, then acquired on 3rd
        # The unlock will be called in finally block, so we need one more result
        mock_conn.execute.side_effect = [
            mock_result_false,  # First lock attempt fails
            mock_result_false,  # Second lock attempt fails
            mock_result_true,  # Third lock attempt succeeds
            MagicMock(),  # Unlock call in finally block
        ]

        with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
            with patch("time.sleep") as mock_sleep:
                with advisory_lock(mock_conn):
                    pass

                # Verify retries happened (3 lock attempts + 1 unlock)
                assert mock_conn.execute.call_count == 4
                # Verify sleep was called for the 2 failed attempts
                assert mock_sleep.call_count == 2
                # Verify backoff messages were logged
                assert any("Lock held by another instance" in str(call) for call in mock_logger.info.call_args_list)

    def test_advisory_lock_timeout_after_max_retries(self):
        """Test advisory lock raises TimeoutError after max retries."""
        mock_conn = MagicMock()
        mock_conn.dialect.name = "postgresql"

        # Create mock result that always returns False
        mock_result = MagicMock()
        mock_result.scalar.return_value = False
        mock_conn.execute.return_value = mock_result

        with patch("mcpgateway.bootstrap_db.logger"):
            with patch("time.sleep"):
                with pytest.raises(TimeoutError, match="Failed to acquire advisory lock after 60 attempts"):
                    with advisory_lock(mock_conn):
                        pass

                # Verify all 60 retries were attempted
                assert mock_conn.execute.call_count == 60
