# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/synthetic_data_server/src/synthetic_data_server/schemas.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Pydantic models describing synthetic data generation requests and responses.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


class ColumnKind(str, Enum):
    """Supported synthetic column types."""

    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"
    DATE = "date"
    DATETIME = "datetime"
    TEXT = "text"
    PATTERN = "pattern"
    NAME = "name"
    EMAIL = "email"
    ADDRESS = "address"
    COMPANY = "company"
    UUID = "uuid"


class ColumnBase(BaseModel):
    """Common fields shared by all column definitions."""

    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(
        default=None,
        description="Optional human friendly description of the column.",
        max_length=500,
    )
    nullable: bool = Field(default=False, description="Allow null values to be generated for this column.")
    null_probability: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Probability of generating null values when nullable is true.",
    )

    @model_validator(mode="after")
    def validate_null_probability(self) -> "ColumnBase":
        """Ensure null probability aligns with the nullable flag."""
        if not self.nullable and self.null_probability not in (0.0, 0):
            raise ValueError("null_probability must be 0 when nullable is False")
        return self


class IntegerColumn(ColumnBase):
    """Integer column configuration."""

    type: Literal[ColumnKind.INTEGER.value] = ColumnKind.INTEGER.value
    minimum: int = Field(default=0)
    maximum: int = Field(default=1000)
    step: int = Field(default=1, gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "IntegerColumn":
        if self.maximum < self.minimum:
            raise ValueError("maximum must be >= minimum for integer columns")
        return self


class FloatColumn(ColumnBase):
    """Floating point column configuration."""

    type: Literal[ColumnKind.FLOAT.value] = ColumnKind.FLOAT.value
    minimum: float = Field(default=0.0)
    maximum: float = Field(default=1.0)
    precision: int = Field(default=4, ge=0, le=10)

    @model_validator(mode="after")
    def validate_bounds(self) -> "FloatColumn":
        if self.maximum < self.minimum:
            raise ValueError("maximum must be >= minimum for float columns")
        return self


class BooleanColumn(ColumnBase):
    """Boolean column configuration."""

    type: Literal[ColumnKind.BOOLEAN.value] = ColumnKind.BOOLEAN.value
    true_probability: float = Field(default=0.5, ge=0.0, le=1.0)


class CategoricalColumn(ColumnBase):
    """Categorical column with discrete values."""

    type: Literal[ColumnKind.CATEGORICAL.value] = ColumnKind.CATEGORICAL.value
    categories: list[str] = Field(..., min_length=1)
    weights: Optional[list[float]] = Field(default=None, description="Optional sampling weights matching the categories list.")

    @model_validator(mode="after")
    def validate_weights(self) -> "CategoricalColumn":
        if self.weights is not None:
            if len(self.weights) != len(self.categories):
                raise ValueError("weights must have the same length as categories")
            total = sum(self.weights)
            if not total:
                raise ValueError("weights must sum to a positive number")
            self.weights = [w / total for w in self.weights]
        return self


class DateColumn(ColumnBase):
    """Date column configuration."""

    type: Literal[ColumnKind.DATE.value] = ColumnKind.DATE.value
    start_date: date = Field(default=date(2020, 1, 1))
    end_date: date = Field(default=date(2024, 12, 31))
    date_format: str = Field(default="%Y-%m-%d")

    @model_validator(mode="after")
    def validate_bounds(self) -> "DateColumn":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class DateTimeColumn(ColumnBase):
    """Datetime column configuration."""

    type: Literal[ColumnKind.DATETIME.value] = ColumnKind.DATETIME.value
    start_datetime: datetime = Field(default=datetime(2020, 1, 1, 0, 0, 0))
    end_datetime: datetime = Field(default=datetime(2024, 12, 31, 23, 59, 59))
    output_format: Optional[str] = Field(
        default="%Y-%m-%dT%H:%M:%S",
        description="Optional strftime format. When null, naive datetime objects are returned.",
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> "DateTimeColumn":
        if self.end_datetime < self.start_datetime:
            raise ValueError("end_datetime must be >= start_datetime")
        return self


class TextColumn(ColumnBase):
    """Free-form text column configuration using Faker providers."""

    type: Literal[ColumnKind.TEXT.value] = ColumnKind.TEXT.value
    min_sentences: int = Field(default=1, ge=1, le=10)
    max_sentences: int = Field(default=3, ge=1, le=20)
    mode: Literal["sentence", "word", "paragraph"] = Field(default="sentence")
    word_count: Optional[int] = Field(default=None, ge=1, le=50, description="Number of words when mode='word'")
    wrap_within: Optional[int] = Field(
        default=None,
        description="Optional maximum number of characters per line for generated text.",
    )

    @model_validator(mode="after")
    def validate_sentence_bounds(self) -> "TextColumn":
        if self.max_sentences < self.min_sentences:
            raise ValueError("max_sentences must be >= min_sentences")
        return self


class PatternColumn(ColumnBase):
    """Pattern-based string column for formatted strings."""

    type: Literal[ColumnKind.PATTERN.value] = ColumnKind.PATTERN.value
    pattern: str = Field(..., description="Python format string e.g. 'PROD-{:04d}' or with multiple: 'USER-{}-{}'")
    sequence_start: Optional[int] = Field(default=1, description="Starting number for sequence patterns")
    sequence_step: int = Field(default=1, description="Step for sequence patterns")
    random_choices: Optional[list[str]] = Field(default=None, description="Random values to use in pattern")
    random_digits: int = Field(default=4, ge=1, le=10, description="Number of random digits if no choices provided")


class SimpleFakerColumn(ColumnBase):
    """Column backed by a simple Faker provider with no extra options."""

    type: Literal[
        ColumnKind.NAME.value,
        ColumnKind.EMAIL.value,
        ColumnKind.ADDRESS.value,
        ColumnKind.COMPANY.value,
    ]
    locale: Optional[str] = Field(
        default=None,
        description="Optional Faker locale override (e.g., 'en_US').",
    )


class UUIDColumn(ColumnBase):
    """UUID column configuration."""

    type: Literal[ColumnKind.UUID.value] = ColumnKind.UUID.value
    uppercase: bool = Field(default=False)


ColumnDefinition = Annotated[
    Union[
        IntegerColumn,
        FloatColumn,
        BooleanColumn,
        CategoricalColumn,
        DateColumn,
        DateTimeColumn,
        TextColumn,
        PatternColumn,
        SimpleFakerColumn,
        UUIDColumn,
    ],
    Field(discriminator="type"),
]


class DatasetPreset(BaseModel):
    """Preset containing a reusable collection of columns."""

    name: str
    description: str
    columns: list[ColumnDefinition]
    default_rows: int = Field(default=250, ge=1, le=50000)
    tags: list[str] = Field(default_factory=list)


class DatasetRequest(BaseModel):
    """Incoming dataset generation request."""

    name: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Optional dataset name that will be echoed in metadata and persisted resources.",
    )
    rows: int = Field(..., ge=1, le=100000, description="Number of rows to generate.")
    preset: Optional[str] = Field(
        default=None,
        description="Optional preset name. When provided, preset columns are used unless overridden.",
    )
    columns: Optional[list[ColumnDefinition]] = Field(
        default=None,
        description="Explicit column definitions. Required when preset is not provided.",
    )
    seed: Optional[int] = Field(default=None, description="Seed ensuring deterministic generation.")
    locale: Optional[str] = Field(
        default=None,
        description="Optional locale code passed to Faker providers (overrides per-column locale).",
    )
    include_summary: bool = Field(default=True)
    preview_rows: int = Field(
        default=5,
        ge=0,
        le=100,
        description="Number of preview rows to return with the response.",
    )
    output_formats: list[Literal["csv", "jsonl"]] = Field(
        default_factory=lambda: ["csv"],
        description="Formats persisted for later retrieval via resources.",
    )

    @model_validator(mode="after")
    def validate_columns(self) -> "DatasetRequest":
        if self.preset is None and not self.columns:
            raise ValueError("columns must be provided when preset is not specified")
        return self


class DatasetMetadata(BaseModel):
    """Metadata associated with a generated dataset."""

    dataset_id: str
    name: Optional[str]
    rows: int
    columns: list[str]
    created_at: datetime
    seed: Optional[int]
    preset: Optional[str]
    locale: Optional[str]
    output_formats: list[str]


class ColumnSummary(BaseModel):
    """Summary statistics for a single column."""

    name: str
    type: ColumnKind
    null_count: int
    sample_values: list[str | int | float | bool]
    unique_values: Optional[int] = None
    stats: Optional[dict[str, float | int]] = None


class DatasetSummary(BaseModel):
    """Summary statistics for the entire dataset."""

    row_count: int
    column_count: int
    columns: list[ColumnSummary]


class DatasetResponse(BaseModel):
    """Payload returned from the dataset generation tool."""

    dataset_id: str
    rows: int
    preview: list[dict[str, object]]
    summary: Optional[DatasetSummary]
    metadata: DatasetMetadata
    resources: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of format name to resource URI for later retrieval.",
    )


class PresetListResponse(BaseModel):
    """Response for the preset listing tool."""

    presets: list[DatasetPreset]

    class Config:
        json_schema_extra = {
            "example": {
                "presets": [
                    {
                        "name": "customer_profiles",
                        "description": "Synthetic customer profile records",
                        "default_rows": 250,
                        "tags": ["customer", "marketing"],
                    }
                ]
            }
        }


class DatasetRetrievalRequest(BaseModel):
    """Payload for fetching persisted dataset resources."""

    dataset_id: str
    format: Literal["csv", "jsonl"] = "csv"


class DatasetRetrievalResponse(BaseModel):
    """Response for dataset retrieval tool."""

    dataset_id: str
    format: str
    content: str
    content_type: str
    row_count: int
    generated_at: datetime
