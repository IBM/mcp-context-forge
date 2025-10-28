# -*- coding: utf-8 -*-
"""Statistical distribution utilities for realistic data generation."""

import random
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np


def power_law_distribution(
    n_samples: int,
    min_value: int,
    max_value: int,
    alpha: float = 2.5
) -> List[int]:
    """Generate values following a power law distribution.

    Power law creates a distribution where few items have high values
    and many items have low values (80/20 rule).

    Args:
        n_samples: Number of samples to generate
        min_value: Minimum value
        max_value: Maximum value
        alpha: Power law exponent (higher = more skewed)

    Returns:
        List of integers following power law distribution
    """
    # Generate power law samples
    samples = np.random.pareto(alpha, n_samples) + 1

    # Scale to desired range
    samples = samples / samples.max() * (max_value - min_value) + min_value

    # Convert to integers and clip
    samples = np.clip(samples.astype(int), min_value, max_value)

    return samples.tolist()


def zipf_distribution(
    n_samples: int,
    n_items: int,
    alpha: float = 1.5
) -> List[int]:
    """Generate item indices following Zipf's law.

    Zipf's law creates access patterns where some items are accessed
    much more frequently than others (80/20 rule for resource access).

    Args:
        n_samples: Number of samples to generate
        n_items: Total number of items
        alpha: Zipf exponent (higher = more skewed)

    Returns:
        List of item indices (0-based)
    """
    # Generate Zipf distribution
    samples = np.random.zipf(alpha, n_samples)

    # Clip to valid item range
    samples = np.clip(samples, 1, n_items) - 1

    return samples.tolist()


def exponential_decay_temporal(
    n_samples: int,
    start_date: datetime,
    end_date: datetime,
    recent_percent: float = 0.8
) -> List[datetime]:
    """Generate timestamps with exponential decay (more recent data).

    Creates a temporal distribution where most data is recent,
    with exponentially fewer records as you go back in time.

    Args:
        n_samples: Number of timestamps to generate
        start_date: Earliest possible date
        end_date: Latest possible date (typically today)
        recent_percent: Percentage of data in recent period (last 30 days)

    Returns:
        List of datetime objects
    """
    # Calculate days span
    total_days = (end_date - start_date).days
    recent_days = 30  # Last 30 days considered "recent"

    # Calculate lambda for exponential distribution
    # We want recent_percent of data in last recent_days
    lambda_param = -np.log(1 - recent_percent) / recent_days

    timestamps = []
    for _ in range(n_samples):
        # Generate exponential decay value (0 = most recent, higher = older)
        decay = np.random.exponential(1 / lambda_param)

        # Clip to valid range
        days_ago = min(decay, total_days)

        # Calculate timestamp
        timestamp = end_date - timedelta(days=days_ago)

        # Add random time within the day
        random_seconds = random.randint(0, 86400 - 1)
        timestamp = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        timestamp += timedelta(seconds=random_seconds)

        timestamps.append(timestamp)

    # Sort by date (oldest first) for realistic data insertion
    timestamps.sort()

    return timestamps


def normal_distribution(
    n_samples: int,
    min_value: int,
    max_value: int,
    mean: Optional[float] = None,
    std_dev: Optional[float] = None
) -> List[int]:
    """Generate values following normal (Gaussian) distribution.

    Args:
        n_samples: Number of samples to generate
        min_value: Minimum value
        max_value: Maximum value
        mean: Mean value (default: midpoint)
        std_dev: Standard deviation (default: range/6)

    Returns:
        List of integers following normal distribution
    """
    if mean is None:
        mean = (min_value + max_value) / 2

    if std_dev is None:
        std_dev = (max_value - min_value) / 6

    # Generate normal samples
    samples = np.random.normal(mean, std_dev, n_samples)

    # Clip to valid range
    samples = np.clip(samples, min_value, max_value)

    return samples.astype(int).tolist()


def uniform_distribution(
    n_samples: int,
    min_value: int,
    max_value: int
) -> List[int]:
    """Generate values following uniform distribution.

    Args:
        n_samples: Number of samples to generate
        min_value: Minimum value
        max_value: Maximum value

    Returns:
        List of integers following uniform distribution
    """
    return [random.randint(min_value, max_value) for _ in range(n_samples)]


def get_distribution(
    distribution_type: str,
    n_samples: int,
    min_value: int,
    max_value: int,
    **kwargs
) -> List[int]:
    """Get samples from specified distribution type.

    Args:
        distribution_type: Type of distribution ('power_law', 'normal', 'uniform')
        n_samples: Number of samples
        min_value: Minimum value
        max_value: Maximum value
        **kwargs: Additional distribution-specific parameters

    Returns:
        List of samples
    """
    if distribution_type == "power_law":
        return power_law_distribution(n_samples, min_value, max_value, **kwargs)
    elif distribution_type == "normal":
        return normal_distribution(n_samples, min_value, max_value, **kwargs)
    elif distribution_type == "uniform":
        return uniform_distribution(n_samples, min_value, max_value)
    else:
        raise ValueError(f"Unknown distribution type: {distribution_type}")
