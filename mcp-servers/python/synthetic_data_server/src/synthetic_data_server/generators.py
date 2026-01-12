# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/synthetic_data_server/src/synthetic_data_server/generators.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Synthetic data generation utilities used by the FastMCP server.
"""

from __future__ import annotations

import math
import random
from collections import Counter, OrderedDict
from datetime import datetime, timedelta
from io import StringIO
from typing import Any, Callable, Dict, Optional, Sequence
from uuid import UUID, uuid4

import orjson
from faker import Faker

from . import schemas


class DatasetGenerationError(RuntimeError):
    """Raised when synthetic data generation fails."""


class SyntheticDataGenerator:
    """High level synthetic data generator supporting multiple column types."""

    def __init__(self, presets: Dict[str, schemas.DatasetPreset]) -> None:
        self.presets = presets

    def list_presets(self) -> list[schemas.DatasetPreset]:
        """Return available dataset presets."""
        return list(self.presets.values())

    def generate(self, request: schemas.DatasetRequest) -> tuple[str, list[dict[str, Any]], list[schemas.ColumnDefinition], schemas.DatasetSummary | None]:
        """Produce synthetic rows according to the provided request."""

        columns = self._resolve_columns(request)
        faker = self._build_faker(request)
        rng = random.Random(request.seed)

        rows: list[dict[str, Any]] = []
        for _ in range(request.rows):
            rows.append(self._generate_row(columns, rng, faker))

        summary = self._summarize(rows, columns) if request.include_summary else None
        dataset_id = str(uuid4())
        return dataset_id, rows, list(columns), summary

    def _resolve_columns(self, request: schemas.DatasetRequest) -> list[schemas.ColumnDefinition]:
        """Determine column definitions based on preset/explicit input."""
        if request.columns:
            return request.columns
        if request.preset and request.preset in self.presets:
            return self.presets[request.preset].columns
        raise DatasetGenerationError("Unable to resolve column definitions from request")

    def _build_faker(self, request: schemas.DatasetRequest) -> Faker:
        """Return a faker instance configured for deterministic output when seeded."""
        faker = Faker(locale=request.locale) if request.locale else Faker()
        if request.seed is not None:
            faker.seed_instance(request.seed)
        return faker

    def _generate_row(
        self,
        columns: Sequence[schemas.ColumnDefinition],
        rng: random.Random,
        faker: Faker,
    ) -> dict[str, Any]:
        """Generate a single row of synthetic data."""
        record: dict[str, Any] = {}

        for column in columns:
            generator = self._get_generator(column, rng, faker)
            value = self._maybe_null(column, generator(), rng)
            record[column.name] = value
        return record

    def _maybe_null(
        self,
        column: schemas.ColumnDefinition,
        value: Any,
        rng: random.Random,
    ) -> Any:
        """Return None based on null probability, otherwise the provided value."""
        if column.nullable and column.null_probability > 0 and rng.random() <= column.null_probability:
            return None
        return value

    def _get_generator(
        self,
        column: schemas.ColumnDefinition,
        rng: random.Random,
        faker: Faker,
    ) -> Callable[[], Any]:
        """Return the generator callable for a specific column definition."""
        if isinstance(column, schemas.IntegerColumn):
            return lambda: self._gen_integer(column, rng)
        if isinstance(column, schemas.FloatColumn):
            return lambda: self._gen_float(column, rng)
        if isinstance(column, schemas.BooleanColumn):
            return lambda: rng.random() < column.true_probability
        if isinstance(column, schemas.CategoricalColumn):
            return lambda: self._gen_categorical(column, rng)
        if isinstance(column, schemas.DateColumn):
            return lambda: self._gen_date(column, rng)
        if isinstance(column, schemas.DateTimeColumn):
            return lambda: self._gen_datetime(column, rng)
        if isinstance(column, schemas.TextColumn):
            return lambda: self._gen_text(column, rng, faker)
        if isinstance(column, schemas.PatternColumn):
            return lambda: self._gen_pattern(column, rng)
        if isinstance(column, schemas.SimpleFakerColumn):
            return lambda: self._gen_simple_faker(column, faker)
        if isinstance(column, schemas.UUIDColumn):
            return lambda: self._gen_uuid(column, rng)
        raise DatasetGenerationError(f"Unsupported column type: {column}")

    def _gen_integer(self, column: schemas.IntegerColumn, rng: random.Random) -> int:
        span = ((column.maximum - column.minimum) // column.step) + 1
        offset = rng.randrange(0, span)
        return column.minimum + (offset * column.step)

    def _gen_float(self, column: schemas.FloatColumn, rng: random.Random) -> float:
        value = rng.uniform(column.minimum, column.maximum)
        return round(value, column.precision)

    def _gen_categorical(self, column: schemas.CategoricalColumn, rng: random.Random) -> str:
        weights = column.weights if column.weights is not None else None
        return rng.choices(column.categories, weights=weights, k=1)[0]

    def _gen_date(self, column: schemas.DateColumn, rng: random.Random) -> str:
        window = (column.end_date - column.start_date).days
        delta = rng.randint(0, window)
        result = column.start_date + timedelta(days=delta)
        return result.strftime(column.date_format)

    def _gen_datetime(self, column: schemas.DateTimeColumn, rng: random.Random) -> Any:
        start = column.start_datetime
        delta_seconds = int((column.end_datetime - start).total_seconds())
        offset = rng.randint(0, max(delta_seconds, 0))
        result = start + timedelta(seconds=offset)
        if column.output_format:
            return result.strftime(column.output_format)
        return result

    def _gen_text(
        self,
        column: schemas.TextColumn,
        rng: random.Random,
        faker: Faker,
    ) -> str:
        if column.mode == "word":
            word_count = column.word_count or rng.randint(1, 10)
            words = [faker.word() for _ in range(word_count)]
            return " ".join(words)
        elif column.mode == "paragraph":
            count = rng.randint(column.min_sentences, column.max_sentences)
            paragraphs = faker.paragraphs(nb=count)
            text = "\n\n".join(paragraphs)
        else:  # sentence mode (default)
            count = rng.randint(column.min_sentences, column.max_sentences)
            sentences = [faker.sentence() for _ in range(count)]
            text = " ".join(sentences)

        if column.wrap_within:
            return self._wrap_text(text, column.wrap_within)
        return text

    def _gen_pattern(
        self,
        column: schemas.PatternColumn,
        rng: random.Random,
    ) -> str:
        import re

        # Count all format placeholders (both {} and {:format})
        pattern_regex = r"\{[^}]*\}"
        placeholders = re.findall(pattern_regex, column.pattern)
        placeholder_count = len(placeholders)

        if placeholder_count == 0:
            # No placeholders, return pattern as-is
            return column.pattern

        # Generate values for placeholders
        values = []
        for _ in range(placeholder_count):
            if column.random_choices:
                values.append(rng.choice(column.random_choices))
            elif column.sequence_start is not None:
                # Use sequence counter
                if not hasattr(self, "_pattern_counters"):
                    self._pattern_counters = {}
                key = f"{column.pattern}_{column.name}"
                if key not in self._pattern_counters:
                    self._pattern_counters[key] = column.sequence_start
                value = self._pattern_counters[key]
                self._pattern_counters[key] += column.sequence_step
                values.append(value)
            else:
                # Generate random digits
                values.append(rng.randint(0, 10**column.random_digits - 1))

        # Format the pattern with values
        try:
            return column.pattern.format(*values)
        except (IndexError, ValueError) as e:
            raise DatasetGenerationError(f"Pattern formatting error: {e}")

    def _wrap_text(self, text: str, width: int) -> str:
        lines = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            words = paragraph.split()
            current_line: list[str] = []
            current_len = 0
            for word in words:
                projected = current_len + len(word) + (1 if current_line else 0)
                if projected > width:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                    current_len = len(word)
                else:
                    current_line.append(word)
                    current_len = projected
            if current_line:
                lines.append(" ".join(current_line))
        return "\n".join(lines)

    def _gen_simple_faker(self, column: schemas.SimpleFakerColumn, faker: Faker) -> str:
        local_faker = faker
        if column.locale:
            local_faker = Faker(locale=column.locale)
        if column.type == schemas.ColumnKind.NAME.value:
            return local_faker.name()
        if column.type == schemas.ColumnKind.EMAIL.value:
            return local_faker.email()
        if column.type == schemas.ColumnKind.ADDRESS.value:
            return local_faker.address().replace("\n", ", ")
        if column.type == schemas.ColumnKind.COMPANY.value:
            return local_faker.company()
        raise DatasetGenerationError(f"Unsupported faker column type: {column.type}")

    def _gen_uuid(self, column: schemas.UUIDColumn, rng: random.Random) -> str:
        # Follow UUID4 bit layout so downstream systems recognise the variant
        random_bytes = rng.getrandbits(128).to_bytes(16, byteorder="big")
        data = bytearray(random_bytes)
        data[6] = (data[6] & 0x0F) | 0x40
        data[8] = (data[8] & 0x3F) | 0x80
        value = str(UUID(bytes=bytes(data)))
        return value.upper() if column.uppercase else value

    def _summarize(
        self,
        rows: Sequence[dict[str, Any]],
        columns: Sequence[schemas.ColumnDefinition],
    ) -> schemas.DatasetSummary:
        column_summaries: list[schemas.ColumnSummary] = []
        total_rows = len(rows)

        for column in columns:
            values = [row[column.name] for row in rows]
            non_null_values = [value for value in values if value is not None]
            null_count = total_rows - len(non_null_values)
            column_kind = schemas.ColumnKind(column.type) if isinstance(column.type, str) else column.type

            sample_values = non_null_values[:5]
            unique_values: Optional[int] = None
            stats: Optional[dict[str, float | int]] = None

            if column_kind in {schemas.ColumnKind.INTEGER, schemas.ColumnKind.FLOAT}:
                unique_values = len(set(non_null_values))
                if non_null_values:
                    numeric_values = [float(value) for value in non_null_values]
                    stats = {
                        "min": min(numeric_values),
                        "max": max(numeric_values),
                        "mean": sum(numeric_values) / len(numeric_values),
                        "stddev": self._stddev(numeric_values),
                    }
            elif column_kind == schemas.ColumnKind.BOOLEAN:
                counts = Counter(non_null_values)
                stats = {"true": counts.get(True, 0), "false": counts.get(False, 0)}
            elif column_kind == schemas.ColumnKind.CATEGORICAL:
                counter = Counter(non_null_values)
                unique_values = len(counter)
                stats = dict(counter.most_common(5))
            elif column_kind in {schemas.ColumnKind.DATE, schemas.ColumnKind.DATETIME}:
                unique_values = len(set(non_null_values))
            elif column_kind == schemas.ColumnKind.UUID:
                unique_values = len(set(non_null_values))

            column_summaries.append(
                schemas.ColumnSummary(
                    name=column.name,
                    type=column_kind,
                    null_count=null_count,
                    sample_values=sample_values,
                    unique_values=unique_values,
                    stats=stats,
                )
            )

        return schemas.DatasetSummary(
            row_count=total_rows,
            column_count=len(columns),
            columns=column_summaries,
        )

    def _stddev(self, values: Sequence[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        return math.sqrt(variance)

    def rows_to_csv(self, rows: Sequence[dict[str, Any]]) -> str:
        if not rows:
            return ""
        fieldnames = list(rows[0].keys())
        buffer = StringIO()
        import csv

        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue()

    def rows_to_jsonl(self, rows: Sequence[dict[str, Any]]) -> str:
        buffer = StringIO()
        for row in rows:
            buffer.write(orjson.dumps(row, default=str).decode())
            buffer.write("\n")
        return buffer.getvalue().rstrip("\n")


def build_presets() -> Dict[str, schemas.DatasetPreset]:
    """Return a curated collection of bundled presets."""
    return OrderedDict(
        {
            "customer_profiles": schemas.DatasetPreset(
                name="customer_profiles",
                description="Synthetic customer demographic and engagement data.",
                default_rows=500,
                tags=["customer", "marketing"],
                columns=[
                    schemas.UUIDColumn(name="customer_id", description="Unique customer identifier"),
                    schemas.SimpleFakerColumn(
                        name="full_name",
                        type=schemas.ColumnKind.NAME.value,
                        description="Full name using Faker",
                    ),
                    schemas.SimpleFakerColumn(
                        name="email",
                        type=schemas.ColumnKind.EMAIL.value,
                        description="Email address",
                    ),
                    schemas.CategoricalColumn(
                        name="segment",
                        description="Customer segmentation bucket",
                        categories=["platinum", "gold", "silver", "bronze"],
                        weights=[0.15, 0.35, 0.3, 0.2],
                    ),
                    schemas.FloatColumn(
                        name="lifetime_value",
                        description="Estimated customer lifetime value",
                        minimum=120.0,
                        maximum=25000.0,
                        precision=2,
                    ),
                    schemas.DateColumn(
                        name="signup_date",
                        description="Date the customer joined",
                        start_date=datetime(2015, 1, 1).date(),
                        end_date=datetime(2024, 12, 31).date(),
                    ),
                    schemas.BooleanColumn(
                        name="is_active",
                        description="Whether the customer engaged in the last 90 days",
                        true_probability=0.68,
                    ),
                ],
            ),
            "transactions": schemas.DatasetPreset(
                name="transactions",
                description="Point-of-sale transaction events with fraud indicators.",
                default_rows=1000,
                tags=["finance", "transactions"],
                columns=[
                    schemas.UUIDColumn(name="transaction_id"),
                    schemas.UUIDColumn(name="customer_id"),
                    schemas.DateTimeColumn(
                        name="transaction_at",
                        start_datetime=datetime(2023, 1, 1, 0, 0, 0),
                        end_datetime=datetime(2024, 12, 31, 23, 59, 59),
                        output_format="%Y-%m-%dT%H:%M:%SZ",
                    ),
                    schemas.FloatColumn(
                        name="amount",
                        minimum=-250.0,
                        maximum=5000.0,
                        precision=2,
                        description="Transaction amount in account currency",
                    ),
                    schemas.CategoricalColumn(
                        name="channel",
                        categories=["in_store", "online", "mobile", "ivr"],
                        weights=[0.45, 0.35, 0.15, 0.05],
                    ),
                    schemas.BooleanColumn(
                        name="is_fraudulent",
                        true_probability=0.02,
                        description="Flag indicating suspected fraud",
                    ),
                ],
            ),
            "iot_sensor_readings": schemas.DatasetPreset(
                name="iot_sensor_readings",
                description="Environmental sensor metrics sampled in regular intervals.",
                default_rows=1440,
                tags=["iot", "timeseries"],
                columns=[
                    schemas.UUIDColumn(name="device_id"),
                    schemas.DateTimeColumn(
                        name="recorded_at",
                        start_datetime=datetime(2024, 1, 1, 0, 0, 0),
                        end_datetime=datetime(2024, 1, 31, 23, 59, 59),
                        output_format="%Y-%m-%d %H:%M:%S",
                    ),
                    schemas.FloatColumn(
                        name="temperature_c",
                        minimum=-10.0,
                        maximum=45.0,
                        precision=2,
                    ),
                    schemas.FloatColumn(
                        name="humidity_pct",
                        minimum=10.0,
                        maximum=100.0,
                        precision=1,
                    ),
                    schemas.FloatColumn(
                        name="co2_ppm",
                        minimum=350.0,
                        maximum=1600.0,
                        precision=0,
                    ),
                    schemas.BooleanColumn(
                        name="is_alert",
                        true_probability=0.05,
                        description="Whether the reading breached configured thresholds",
                    ),
                ],
            ),
            "products": schemas.DatasetPreset(
                name="products",
                description="E-commerce product catalog with SKUs and pricing.",
                default_rows=200,
                tags=["ecommerce", "products", "inventory"],
                columns=[
                    schemas.PatternColumn(
                        name="sku",
                        pattern="SKU-{:05d}",
                        sequence_start=10000,
                        description="Product SKU identifier",
                    ),
                    schemas.PatternColumn(
                        name="product_name",
                        pattern="Product {}",
                        random_choices=["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"],
                        description="Product name",
                    ),
                    schemas.TextColumn(
                        name="description",
                        mode="sentence",
                        min_sentences=1,
                        max_sentences=2,
                        description="Product description",
                    ),
                    schemas.CategoricalColumn(
                        name="category",
                        categories=["Electronics", "Clothing", "Home", "Sports", "Books", "Toys"],
                        weights=[0.25, 0.20, 0.20, 0.15, 0.10, 0.10],
                    ),
                    schemas.FloatColumn(
                        name="price",
                        minimum=9.99,
                        maximum=999.99,
                        precision=2,
                        description="Product price in USD",
                    ),
                    schemas.IntegerColumn(
                        name="stock_quantity",
                        minimum=0,
                        maximum=500,
                        description="Current stock level",
                    ),
                    schemas.BooleanColumn(
                        name="is_featured",
                        true_probability=0.15,
                        description="Whether product is featured",
                    ),
                ],
            ),
            "employees": schemas.DatasetPreset(
                name="employees",
                description="HR employee records with departments and salaries.",
                default_rows=150,
                tags=["hr", "employees", "organization"],
                columns=[
                    schemas.PatternColumn(
                        name="employee_id",
                        pattern="EMP-{:06d}",
                        sequence_start=100001,
                        description="Employee ID",
                    ),
                    schemas.SimpleFakerColumn(
                        name="full_name",
                        type=schemas.ColumnKind.NAME.value,
                        description="Employee full name",
                    ),
                    schemas.SimpleFakerColumn(
                        name="email",
                        type=schemas.ColumnKind.EMAIL.value,
                        description="Work email address",
                    ),
                    schemas.CategoricalColumn(
                        name="department",
                        categories=["Engineering", "Sales", "Marketing", "HR", "Finance", "Operations", "Support"],
                        weights=[0.30, 0.15, 0.10, 0.08, 0.12, 0.15, 0.10],
                    ),
                    schemas.CategoricalColumn(
                        name="level",
                        categories=["Junior", "Mid", "Senior", "Lead", "Manager", "Director"],
                        weights=[0.25, 0.30, 0.20, 0.10, 0.10, 0.05],
                    ),
                    schemas.IntegerColumn(
                        name="salary",
                        minimum=40000,
                        maximum=250000,
                        step=5000,
                        description="Annual salary in USD",
                    ),
                    schemas.DateColumn(
                        name="hire_date",
                        start_date=datetime(2010, 1, 1).date(),
                        end_date=datetime(2024, 12, 31).date(),
                    ),
                    schemas.BooleanColumn(
                        name="is_remote",
                        true_probability=0.35,
                        description="Remote work status",
                    ),
                ],
            ),
        }
    )
