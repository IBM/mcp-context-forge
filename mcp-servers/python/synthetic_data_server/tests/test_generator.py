# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/synthetic_data_server/tests/test_generator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the synthetic data server utilities.
"""

from __future__ import annotations

from datetime import date

import pytest

from synthetic_data_server.generators import SyntheticDataGenerator, build_presets
from synthetic_data_server import schemas
from synthetic_data_server.storage import DatasetStorage


@pytest.fixture(scope="module")
def generator() -> SyntheticDataGenerator:
    return SyntheticDataGenerator(build_presets())


def test_generate_dataset_with_preset_is_deterministic(generator: SyntheticDataGenerator) -> None:
    request = schemas.DatasetRequest(
        name="customers",
        rows=10,
        preset="customer_profiles",
        seed=123,
        include_summary=True,
        preview_rows=3,
    )

    first_id, first_rows, _, first_summary = generator.generate(request)
    second_id, second_rows, _, second_summary = generator.generate(request)

    assert len(first_rows) == 10
    assert len(second_rows) == 10
    assert first_rows == second_rows
    assert first_summary == second_summary
    assert first_id != second_id  # Identifier is random per request


def test_generate_dataset_with_custom_columns(generator: SyntheticDataGenerator) -> None:
    request = schemas.DatasetRequest(
        name="custom",
        rows=5,
        columns=[
            schemas.IntegerColumn(name="age", minimum=18, maximum=30),
            schemas.BooleanColumn(name="subscribed", true_probability=0.25),
            schemas.TextColumn(name="notes", min_sentences=1, max_sentences=1),
            schemas.DateColumn(
                name="signup_date",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 2),
            ),
        ],
        seed=7,
        include_summary=False,
        output_formats=["csv", "jsonl"],
    )

    dataset_id, rows, columns, summary = generator.generate(request)

    assert dataset_id
    assert len(rows) == 5
    assert len(columns) == 4
    assert summary is None
    assert {"age", "subscribed", "notes", "signup_date"} == set(rows[0].keys())


def test_storage_persists_resources(generator: SyntheticDataGenerator) -> None:
    request = schemas.DatasetRequest(
        name="transactions",
        rows=3,
        preset="transactions",
        seed=99,
        include_summary=True,
        output_formats=["csv", "jsonl"],
    )
    dataset_id, rows, columns, summary = generator.generate(request)

    storage = DatasetStorage(max_items=2)
    stored = storage.store(dataset_id, rows, columns, summary, request, generator)

    assert stored.metadata.dataset_id == dataset_id
    assert set(stored.resources.keys()) == {"csv", "jsonl"}

    csv_content, csv_type = stored.get_content("csv")
    jsonl_content, jsonl_type = stored.get_content("jsonl")

    assert csv_type == "text/csv"
    assert jsonl_type == "application/jsonl"
    assert csv_content.count("\n") == 4  # header + 3 rows
    assert len(jsonl_content.splitlines()) == 3
