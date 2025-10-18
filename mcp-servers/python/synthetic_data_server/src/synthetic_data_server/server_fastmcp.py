# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/synthetic_data_server/src/synthetic_data_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Synthetic Data Generation FastMCP Server.
"""

from __future__ import annotations

import argparse
import logging
import sys

from fastmcp import FastMCP

from . import schemas
from .generators import SyntheticDataGenerator, build_presets
from .storage import DatasetStorage


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

mcp = FastMCP("synthetic-data-server", version="0.1.0")

_presets = build_presets()
_generator = SyntheticDataGenerator(_presets)
_storage = DatasetStorage(max_items=25)


@mcp.tool(description="List available dataset presets with column definitions")
def list_presets() -> schemas.PresetListResponse:
    """Return metadata about built-in dataset presets."""
    logger.info("Listing synthetic data presets")
    return schemas.PresetListResponse(presets=_generator.list_presets())


@mcp.tool(description="Generate a synthetic dataset and persist it for later retrieval")
def generate_dataset(request: schemas.DatasetRequest) -> schemas.DatasetResponse:
    """Generate synthetic data based on presets or custom column definitions."""
    logger.info(
        "Generating dataset",
        extra={
            "rows": request.rows,
            "preset": request.preset,
            "seed": request.seed,
            "formats": request.output_formats,
        },
    )

    dataset_id, rows, columns, summary = _generator.generate(request)
    stored = _storage.store(dataset_id, rows, columns, summary, request, _generator)

    preview_rows = rows[: request.preview_rows]

    return schemas.DatasetResponse(
        dataset_id=dataset_id,
        rows=stored.metadata.rows,
        preview=preview_rows,
        summary=summary,
        metadata=stored.metadata,
        resources=stored.resources,
    )


@mcp.tool(description="List metadata about previously generated datasets")
def list_generated_datasets() -> list[schemas.DatasetMetadata]:
    """Return metadata for cached datasets."""
    logger.info("Listing generated datasets")
    return _storage.list_datasets()


@mcp.tool(description="Retrieve persisted dataset content in CSV or JSONL format")
def retrieve_dataset(request: schemas.DatasetRetrievalRequest) -> schemas.DatasetRetrievalResponse:
    """Return dataset contents for a requested format."""
    logger.info(
        "Retrieving dataset",
        extra={"dataset_id": request.dataset_id, "format": request.format},
    )
    stored = _storage.get(request.dataset_id)
    content, content_type = stored.get_content(request.format)
    return schemas.DatasetRetrievalResponse(
        dataset_id=request.dataset_id,
        format=request.format,
        content=content,
        content_type=content_type,
        row_count=stored.metadata.rows,
        generated_at=stored.metadata.created_at,
    )


@mcp.tool(description="Return summary statistics for a generated dataset")
def summarize_dataset(dataset_id: str) -> schemas.DatasetSummary | None:
    """Return computed summary statistics for a stored dataset."""
    logger.info("Summarizing dataset", extra={"dataset_id": dataset_id})
    stored = _storage.get(dataset_id)
    return stored.summary


def main() -> None:
    """Entry point with flexible transport selection."""
    parser = argparse.ArgumentParser(description="Synthetic Data FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9018, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info("Starting Synthetic Data Server on HTTP", extra={"host": args.host, "port": args.port})
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting Synthetic Data Server on stdio")
        mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
