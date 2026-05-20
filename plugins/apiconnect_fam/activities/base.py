"""Location: ./plugins/apiconnect_fam/activities/base.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Base Activity Classes.

Defines abstract base classes for all activities.
"""

# Standard
from abc import ABC, abstractmethod
import logging
import time
from typing import Optional

# Local
from ..models import ActivityContext


class AbstractActivity(ABC):
    """Base class for all activities.

    Activities represent discrete operations
    that can be executed independently. Each activity has access to shared
    context.

    Attributes:
        context: Shared activity context
        logger: Logger for this activity
    """

    def __init__(self, context: ActivityContext):
        """Initialize activity.

        Args:
            context: Shared activity context
        """
        self.context = context
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    async def perform(self) -> None:
        """Execute the activity.

        This method must be implemented by subclasses to define
        the activity's behavior.

        Raises:
            Exception: If activity execution fails
        """
        pass

    async def execute(self) -> bool:
        """Execute activity with error handling.

        Wraps the perform() method with error handling.

        Returns:
            True if execution succeeded, False otherwise
        """
        success = False

        try:
            self.logger.debug(f"Executing {self.__class__.__name__}")
            await self.perform()
            success = True
            self.logger.debug(f"{self.__class__.__name__} completed successfully")

        except Exception as e:
            self.logger.error(f"{self.__class__.__name__} failed: {e}", exc_info=True)

        return success


class AbstractScheduledActivity(AbstractActivity):
    """Base class for scheduled activities.

    Scheduled activities run periodically at a fixed interval.

    Attributes:
        context: Shared activity context
        last_execution_time: Timestamp of last execution
    """

    def __init__(self, context: ActivityContext):
        """Initialize scheduled activity.

        Args:
            context: Shared activity context
        """
        super().__init__(context)
        self.last_execution_time: Optional[float] = None

    @abstractmethod
    def get_interval_seconds(self) -> int:
        """Get the scheduling interval in seconds.

        Returns:
            Interval in seconds
        """
        pass

    def should_execute(self) -> bool:
        """Check if activity should execute based on interval.

        Returns:
            True if interval has elapsed or this is first execution
        """
        if self.last_execution_time is None:
            return True

        current_time = time.time()
        elapsed = current_time - self.last_execution_time
        return elapsed >= self.get_interval_seconds()

    async def execute(self) -> bool:
        """Execute scheduled activity if interval has elapsed.

        Returns:
            True if execution succeeded, False otherwise
        """
        if not self.should_execute():
            return True  # Not time to execute yet, not an error

        # Execute the activity
        success = await super().execute()

        # Update last execution time
        self.last_execution_time = time.time()

        return success
