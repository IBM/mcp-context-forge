"""Location: ./plugins/apiconnect_fam/activities/send_heartbeat.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Send Heartbeat Activity.

Sends runtime heartbeat to FAM periodically.
"""

# Standard

# Local
from ..fam import FAMAssetCatalogClient
from ..models import ActivityContext
from ..utils import RetryConfig, SyncError, with_retry
from .base import AbstractScheduledActivity


class SendHeartbeatActivity(AbstractScheduledActivity):
    """Activity for sending runtime heartbeat to FAM.

    Attributes:
        context: Shared activity context
        fam_client: FAM API client
        heartbeat_interval: Interval in seconds
    """

    def __init__(self, context: ActivityContext, fam_client: FAMAssetCatalogClient, heartbeat_interval: int = 60):
        """Initialize send heartbeat activity.

        Args:
            context: Shared activity context
            fam_client: FAM API client
            heartbeat_interval: Heartbeat interval in seconds
        """
        super().__init__(context)
        self._fam_client = fam_client
        self._heartbeat_interval = heartbeat_interval
        self._consecutive_failures = 0
        self._total_heartbeats_sent = 0

    def get_interval_seconds(self) -> int:
        """Get the heartbeat interval.

        Returns:
            Interval in seconds
        """
        return self._heartbeat_interval

    async def perform(self) -> None:
        """Send heartbeat to FAM.

        Raises:
            SyncError: If heartbeat fails after retries
        """

        try:
            # Send heartbeat with retry logic
            await with_retry(self._send_heartbeat, retry_config=RetryConfig(max_attempts=2, initial_delay=0.5), operation_name="Send Heartbeat")

            # Track success
            self._consecutive_failures = 0
            self._total_heartbeats_sent += 1

            self.logger.debug(f"Heartbeat sent successfully (total: {self._total_heartbeats_sent})")

        except Exception as e:
            self._consecutive_failures += 1
            error_msg = f"Failed to send heartbeat (consecutive failures: {self._consecutive_failures}): {e}"
            self.logger.error(error_msg, exc_info=True)
            raise SyncError(error_msg, e)

    async def _send_heartbeat(self) -> None:
        """Send heartbeat to FAM.

        Raises:
            Exception: If heartbeat fails
        """
        self.logger.debug("Calling FAM API: POST /api/engine/v2/runtimes/heartbeat")
        self.logger.debug(f"Runtime ID: {self.context.runtime_id}")

        success = await self._fam_client.send_heartbeat(self.context.runtime_id)

        if success:
            self.logger.debug("FAM API call successful")
        else:
            raise Exception("Heartbeat failed")
