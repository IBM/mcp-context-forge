# -*- coding: utf-8 -*-
"""Progress tracking utilities."""

import sys
import time
from typing import Optional

from tqdm import tqdm


class ProgressTracker:
    """Track progress of data generation with ETA and statistics."""

    def __init__(self, total: int, desc: str, unit: str = "records"):
        """Initialize progress tracker.

        Args:
            total: Total number of items to process
            desc: Description of the operation
            unit: Unit name for progress display
        """
        self.total = total
        self.desc = desc
        self.unit = unit
        self.pbar: Optional[tqdm] = None
        self.start_time = time.time()
        self.current = 0

    def __enter__(self):
        """Context manager entry."""
        self.pbar = tqdm(
            total=self.total,
            desc=self.desc,
            unit=self.unit,
            unit_scale=True,
            dynamic_ncols=True,
            file=sys.stdout,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.pbar:
            self.pbar.close()

    def update(self, n: int = 1):
        """Update progress by n items.

        Args:
            n: Number of items to add to progress
        """
        if self.pbar:
            self.pbar.update(n)
        self.current += n

    def set_postfix(self, **kwargs):
        """Set postfix statistics.

        Args:
            **kwargs: Key-value pairs to display
        """
        if self.pbar:
            self.pbar.set_postfix(**kwargs)

    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds.

        Returns:
            Elapsed time
        """
        return time.time() - self.start_time

    def get_rate(self) -> float:
        """Get processing rate (items per second).

        Returns:
            Items per second
        """
        elapsed = self.get_elapsed_time()
        if elapsed > 0:
            return self.current / elapsed
        return 0.0

    def get_eta(self) -> float:
        """Get estimated time remaining in seconds.

        Returns:
            Estimated seconds remaining
        """
        rate = self.get_rate()
        if rate > 0:
            remaining = self.total - self.current
            return remaining / rate
        return 0.0


class MultiProgressTracker:
    """Track multiple progress bars simultaneously."""

    def __init__(self):
        """Initialize multi-progress tracker."""
        self.trackers = {}

    def add_tracker(self, name: str, total: int, desc: str):
        """Add a new progress tracker.

        Args:
            name: Unique name for the tracker
            total: Total items
            desc: Description
        """
        self.trackers[name] = ProgressTracker(total, desc)

    def update(self, name: str, n: int = 1):
        """Update a specific tracker.

        Args:
            name: Tracker name
            n: Number of items
        """
        if name in self.trackers:
            self.trackers[name].update(n)

    def close_all(self):
        """Close all progress trackers."""
        for tracker in self.trackers.values():
            if tracker.pbar:
                tracker.pbar.close()
