"""
Data models for MCP data analysis server requests and responses.
"""

# Standard
from typing import Any

# Third-Party
from pydantic import BaseModel, Field


class DataLoadRequest(BaseModel):
    """Request model for loading datasets."""

    source: str = Field(..., description="File path, URL, or SQL connection string")
    format: str = Field(..., description="Data format: csv, json, parquet, sql, excel")
    options: dict[str, Any] | None = Field(None, description="Format-specific options")
    sample_size: int | None = Field(None, description="Number of rows to sample")
    cache_data: bool = Field(True, description="Whether to cache the dataset")
    dataset_id: str | None = Field(None, description="Custom dataset identifier")


class DataAnalysisRequest(BaseModel):
    """Request model for dataset analysis."""

    dataset_id: str = Field(..., description="Dataset identifier")
    analysis_type: str = Field(
        ..., description="Analysis type: descriptive, exploratory, correlation"
    )
    columns: list[str] | None = Field(None, description="Specific columns to analyze")
    include_distributions: bool = Field(
        True, description="Include distribution analysis"
    )
    include_correlations: bool = Field(True, description="Include correlation analysis")
    include_outliers: bool = Field(True, description="Include outlier detection")
    confidence_level: float = Field(0.95, description="Confidence level for statistics")


class StatTestRequest(BaseModel):
    """Request model for statistical hypothesis testing."""

    dataset_id: str = Field(..., description="Dataset identifier")
    test_type: str = Field(
        ..., description="Test type: t_test, chi_square, anova, regression"
    )
    columns: list[str] = Field(..., description="Columns to test")
    groupby_column: str | None = Field(None, description="Column for grouping")
    hypothesis: str | None = Field(None, description="Hypothesis statement")
    alpha: float = Field(0.05, description="Significance level")
    alternative: str = Field("two-sided", description="Alternative hypothesis")


class VisualizationRequest(BaseModel):
    """Request model for creating visualizations."""

    dataset_id: str = Field(..., description="Dataset identifier")
    plot_type: str = Field(
        ..., description="Plot type: histogram, scatter, box, heatmap, time_series"
    )
    x_column: str | None = Field(
        None, description="X-axis column (not required for heatmap)"
    )
    y_column: str | None = Field(None, description="Y-axis column")
    color_column: str | None = Field(None, description="Color grouping column")
    facet_column: str | None = Field(None, description="Faceting column")
    title: str | None = Field(None, description="Plot title")
    save_format: str = Field("png", description="Save format: png, svg, html")
    interactive: bool = Field(False, description="Create interactive visualization")


class TransformRequest(BaseModel):
    """Request model for data transformations."""

    dataset_id: str = Field(..., description="Dataset identifier")
    operations: list[dict[str, Any]] = Field(
        ..., description="List of transformation operations"
    )
    create_new_dataset: bool = Field(
        False, description="Create new dataset or modify existing"
    )
    new_dataset_id: str | None = Field(None, description="New dataset identifier")


class TimeSeriesRequest(BaseModel):
    """Request model for time series analysis."""

    dataset_id: str = Field(..., description="Dataset identifier")
    time_column: str = Field(..., description="Time/date column")
    value_columns: list[str] = Field(..., description="Value columns to analyze")
    frequency: str | None = Field(None, description="Time frequency: D, W, M, Q, Y")
    operations: list[str] | None = Field(
        None, description="Operations: trend, seasonal, forecast"
    )
    forecast_periods: int = Field(12, description="Number of periods to forecast")
    confidence_intervals: bool = Field(True, description="Include confidence intervals")


class DataQueryRequest(BaseModel):
    """Request model for querying datasets."""

    dataset_id: str = Field(..., description="Dataset identifier")
    query: str = Field(..., description="SQL-like query string")
    limit: int | None = Field(1000, description="Maximum number of rows")
    offset: int = Field(0, description="Row offset")
    return_format: str = Field("json", description="Return format: json, csv, html")


# Response models
class DatasetInfo(BaseModel):
    """Dataset information model."""

    dataset_id: str
    shape: tuple[int, int]
    columns: list[str]
    dtypes: dict[str, str]
    memory_usage: str
    created_at: str


class AnalysisResult(BaseModel):
    """Analysis result model."""

    dataset_id: str
    analysis_type: str
    summary: dict[str, Any]
    distributions: dict[str, Any] | None = None
    correlations: dict[str, Any] | None = None
    outliers: dict[str, Any] | None = None


class TestResult(BaseModel):
    """Statistical test result model."""

    test_type: str
    statistic: float
    p_value: float
    degrees_of_freedom: int | None = None
    effect_size: float | None = None
    conclusion: str
    interpretation: str


class VisualizationResult(BaseModel):
    """Visualization result model."""

    plot_type: str
    file_path: str
    format: str
    title: str | None = None
    metadata: dict[str, Any]


class TransformResult(BaseModel):
    """Data transformation result model."""

    dataset_id: str
    operations_applied: list[str]
    shape_before: tuple[int, int]
    shape_after: tuple[int, int]
    summary: str
