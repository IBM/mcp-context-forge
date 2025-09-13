# -*- coding: utf-8 -*-
"""
Dataset storage and management functionality.
"""

# Standard
from datetime import datetime
import hashlib
import logging
from typing import Any

# Third-Party
import pandas as pd

# Local
from ..models import DatasetInfo

logger = logging.getLogger(__name__)


class DatasetManager:
    """Manages dataset storage, caching, and retrieval."""

    def __init__(self, max_datasets: int = 100, max_memory_mb: int = 1024):
        """
        Initialize the dataset manager.

        Args:
            max_datasets: Maximum number of datasets to keep in memory
            max_memory_mb: Maximum memory usage in MB
        """
        self._datasets: dict[str, pd.DataFrame] = {}
        self._metadata: dict[str, DatasetInfo] = {}
        self._access_times: dict[str, datetime] = {}
        self.max_datasets = max_datasets
        self.max_memory_mb = max_memory_mb

    def store_dataset(
        self,
        dataset: pd.DataFrame,
        dataset_id: str | None = None,
        source: str | None = None,
    ) -> str:
        """
        Store a dataset in memory with automatic ID generation.

        Args:
            dataset: Pandas DataFrame to store
            dataset_id: Optional custom dataset ID
            source: Source information for the dataset

        Returns:
            Dataset ID
        """
        if dataset_id is None:
            dataset_id = self._generate_dataset_id(dataset, source)

        # Check if we need to evict datasets
        self._evict_if_necessary()

        # Store dataset and metadata
        self._datasets[dataset_id] = dataset.copy()
        self._access_times[dataset_id] = datetime.now()

        # Create metadata
        memory_usage = dataset.memory_usage(deep=True).sum()
        self._metadata[dataset_id] = DatasetInfo(
            dataset_id=dataset_id,
            shape=dataset.shape,
            columns=dataset.columns.tolist(),
            dtypes={col: str(dtype) for col, dtype in dataset.dtypes.items()},
            memory_usage=f"{memory_usage / 1024 / 1024:.2f} MB",
            created_at=datetime.now().isoformat(),
        )

        logger.info(f"Stored dataset {dataset_id} with shape {dataset.shape}")
        return dataset_id

    def get_dataset(self, dataset_id: str) -> pd.DataFrame:
        """
        Retrieve a dataset by ID.

        Args:
            dataset_id: Dataset identifier

        Returns:
            Pandas DataFrame

        Raises:
            KeyError: If dataset not found
        """
        if dataset_id not in self._datasets:
            raise KeyError(f"Dataset {dataset_id} not found")

        self._access_times[dataset_id] = datetime.now()
        return self._datasets[dataset_id]

    def get_dataset_info(self, dataset_id: str) -> DatasetInfo:
        """
        Get metadata for a dataset.

        Args:
            dataset_id: Dataset identifier

        Returns:
            DatasetInfo object

        Raises:
            KeyError: If dataset not found
        """
        if dataset_id not in self._metadata:
            raise KeyError(f"Dataset {dataset_id} not found")

        return self._metadata[dataset_id]

    def list_datasets(self) -> list[DatasetInfo]:
        """
        List all stored datasets.

        Returns:
            List of DatasetInfo objects
        """
        return list(self._metadata.values())

    def remove_dataset(self, dataset_id: str) -> bool:
        """
        Remove a dataset from storage.

        Args:
            dataset_id: Dataset identifier

        Returns:
            True if removed, False if not found
        """
        if dataset_id not in self._datasets:
            return False

        del self._datasets[dataset_id]
        del self._metadata[dataset_id]
        del self._access_times[dataset_id]

        logger.info(f"Removed dataset {dataset_id}")
        return True

    def clear_all(self) -> None:
        """Clear all datasets from storage."""
        self._datasets.clear()
        self._metadata.clear()
        self._access_times.clear()
        logger.info("Cleared all datasets")

    def get_memory_usage(self) -> dict[str, Any]:
        """
        Get current memory usage statistics.

        Returns:
            Dictionary with memory usage information
        """
        total_memory = 0
        dataset_sizes = {}

        for dataset_id, dataset in self._datasets.items():
            size = dataset.memory_usage(deep=True).sum()
            dataset_sizes[dataset_id] = size
            total_memory += size

        return {
            "total_memory_mb": total_memory / 1024 / 1024,
            "dataset_count": len(self._datasets),
            "dataset_sizes_mb": {k: v / 1024 / 1024 for k, v in dataset_sizes.items()},
            "max_memory_mb": self.max_memory_mb,
            "utilization_percent": (total_memory / 1024 / 1024) / self.max_memory_mb * 100,
        }

    def _generate_dataset_id(self, dataset: pd.DataFrame, source: str | None = None) -> str:
        """
        Generate a unique dataset ID based on content hash.

        Args:
            dataset: Pandas DataFrame
            source: Optional source information

        Returns:
            Unique dataset ID
        """
        # Create a hash based on dataset shape, columns, and first few rows
        content = f"{dataset.shape}_{list(dataset.columns)}"
        if not dataset.empty:
            content += f"_{dataset.head(5).to_string()}"
        if source:
            content += f"_{source}"

        hash_obj = hashlib.md5(content.encode())
        return f"dataset_{hash_obj.hexdigest()[:8]}"

    def _evict_if_necessary(self) -> None:
        """Evict datasets if memory or count limits are exceeded."""
        # Check dataset count limit
        if len(self._datasets) >= self.max_datasets:
            self._evict_least_recently_used()

        # Check memory limit
        memory_stats = self.get_memory_usage()
        if memory_stats["total_memory_mb"] > self.max_memory_mb:
            self._evict_least_recently_used()

    def _evict_least_recently_used(self) -> None:
        """Evict the least recently used dataset."""
        if not self._access_times:
            return

        # Find least recently accessed dataset
        lru_dataset_id = min(self._access_times.keys(), key=lambda x: self._access_times[x])

        logger.info(f"Evicting least recently used dataset: {lru_dataset_id}")
        self.remove_dataset(lru_dataset_id)
