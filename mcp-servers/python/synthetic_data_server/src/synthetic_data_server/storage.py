# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/synthetic_data_server/src/synthetic_data_server/storage.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

In-memory persistence for generated datasets.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from . import schemas


@dataclass
class StoredDataset:
    """Container representing a generated dataset persisted in memory."""

    dataset_id: str
    rows: list[dict[str, object]]
    columns: list[schemas.ColumnDefinition]
    summary: Optional[schemas.DatasetSummary]
    metadata: schemas.DatasetMetadata
    resources: Dict[str, str] = field(default_factory=dict)
    contents: Dict[str, tuple[str, str]] = field(default_factory=dict)

    def get_content(self, fmt: str) -> tuple[str, str]:
        """Return the content string and MIME type for a format."""
        if fmt not in self.contents:
            raise KeyError(f"Format '{fmt}' not available for dataset {self.dataset_id}")
        return self.contents[fmt]


class DatasetStorage:
    """LRU-style storage keeping the most recent generated datasets."""

    def __init__(self, max_items: int = 10) -> None:
        self.max_items = max_items
        self._items: "OrderedDict[str, StoredDataset]" = OrderedDict()

    def store(
        self,
        dataset_id: str,
        rows: list[dict[str, object]],
        columns: list[schemas.ColumnDefinition],
        summary: Optional[schemas.DatasetSummary],
        request: schemas.DatasetRequest,
        generator: "SyntheticDataGenerator",
    ) -> StoredDataset:
        """Persist a dataset and return the stored representation."""
        from .generators import SyntheticDataGenerator  # Circular import guard

        if not isinstance(generator, SyntheticDataGenerator):
            raise TypeError("generator must be an instance of SyntheticDataGenerator")

        created_at = datetime.now(tz=timezone.utc)
        column_names = [column.name for column in columns]
        metadata = schemas.DatasetMetadata(
            dataset_id=dataset_id,
            name=request.name,
            rows=len(rows),
            columns=column_names,
            created_at=created_at,
            seed=request.seed,
            preset=request.preset,
            locale=request.locale,
            output_formats=request.output_formats,
        )

        resources: Dict[str, str] = {}
        contents: Dict[str, tuple[str, str]] = {}
        for fmt in request.output_formats:
            if fmt == "csv":
                content = generator.rows_to_csv(rows)
                mime = "text/csv"
            elif fmt == "jsonl":
                content = generator.rows_to_jsonl(rows)
                mime = "application/jsonl"
            else:
                raise ValueError(f"Unsupported output format: {fmt}")
            resources[fmt] = f"dataset://{dataset_id}.{fmt}"
            contents[fmt] = (content, mime)

        stored = StoredDataset(
            dataset_id=dataset_id,
            rows=rows,
            columns=columns,
            summary=summary,
            metadata=metadata,
            resources=resources,
            contents=contents,
        )

        self._items[dataset_id] = stored
        self._items.move_to_end(dataset_id)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)
        return stored

    def get(self, dataset_id: str) -> StoredDataset:
        """Retrieve a stored dataset by identifier."""
        try:
            stored = self._items[dataset_id]
        except KeyError as exc:
            raise KeyError(f"Dataset '{dataset_id}' not found") from exc
        self._items.move_to_end(dataset_id)
        return stored

    def list_datasets(self) -> list[schemas.DatasetMetadata]:
        """Return metadata for all stored datasets (most recent last)."""
        return [item.metadata for item in self._items.values()]


__all__ = ["DatasetStorage", "StoredDataset"]
