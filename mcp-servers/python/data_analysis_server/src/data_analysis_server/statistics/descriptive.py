# -*- coding: utf-8 -*-
"""
Descriptive statistics functionality for data analysis.

This module provides comprehensive descriptive statistics calculations
including measures of central tendency, dispersion, shape, and data quality.
"""

# Standard
import logging
from typing import Any

# Third-Party
import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


class DescriptiveStatistics:
    """Provides comprehensive descriptive statistics functionality."""

    def __init__(self):
        """Initialize the descriptive statistics analyzer."""

    def get_basic_info(self, df: pd.DataFrame) -> dict[str, Any]:
        """
        Get basic dataset information.

        Args:
            df: DataFrame to analyze

        Returns:
            Dictionary containing basic dataset information
        """
        return {
            "shape": df.shape,
            "columns": df.columns.tolist(),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "memory_usage": f"{df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB",
            "missing_values": df.isnull().sum().to_dict(),
            "missing_percentage": (df.isnull().sum() / len(df) * 100).to_dict(),
            "duplicate_rows": df.duplicated().sum(),
            "unique_values": {col: df[col].nunique() for col in df.columns},
        }

    def get_descriptive_stats(
        self,
        df: pd.DataFrame,
        confidence_level: float = 0.95,
        columns: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Get comprehensive descriptive statistics for all columns.

        Args:
            df: DataFrame to analyze
            confidence_level: Confidence level for confidence intervals
            columns: Specific columns to analyze (None for all)

        Returns:
            Dictionary containing descriptive statistics
        """
        if columns:
            df = df[columns]

        numeric_cols = df.select_dtypes(include=[np.number]).columns
        categorical_cols = df.select_dtypes(include=["object", "category"]).columns

        result = {"numeric_columns": {}, "categorical_columns": {}}

        # Numeric columns descriptive statistics
        for col in numeric_cols:
            result["numeric_columns"][col] = self._get_numeric_stats(
                df[col], confidence_level
            )

        # Categorical columns descriptive statistics
        for col in categorical_cols:
            result["categorical_columns"][col] = self._get_categorical_stats(df[col])

        return result

    def _get_numeric_stats(
        self, series: pd.Series, confidence_level: float = 0.95
    ) -> dict[str, Any]:
        """
        Get descriptive statistics for a numeric series.

        Args:
            series: Numeric pandas Series
            confidence_level: Confidence level for intervals

        Returns:
            Dictionary containing numeric statistics
        """
        series = series.dropna()

        if len(series) == 0:
            return {"count": 0, "error": "No valid numeric values"}

        # Basic descriptive statistics
        stats_dict = {
            "count": len(series),
            "mean": float(series.mean()),
            "std": float(series.std()),
            "min": float(series.min()),
            "25%": float(series.quantile(0.25)),
            "50%": float(series.median()),  # median
            "75%": float(series.quantile(0.75)),
            "max": float(series.max()),
            "variance": float(series.var()),
            "skewness": float(series.skew()),
            "kurtosis": float(series.kurtosis()),
            "range": float(series.max() - series.min()),
            "iqr": float(series.quantile(0.75) - series.quantile(0.25)),
        }

        # Additional percentiles
        percentiles = [0.01, 0.05, 0.10, 0.90, 0.95, 0.99]
        for p in percentiles:
            stats_dict[f"{int(p * 100)}%"] = float(series.quantile(p))

        # Mode (most frequent value)
        try:
            mode_result = series.mode()
            if not mode_result.empty:
                stats_dict["mode"] = float(mode_result.iloc[0])
        except Exception:
            stats_dict["mode"] = None

        # Coefficient of variation
        if stats_dict["mean"] != 0:
            stats_dict["cv"] = stats_dict["std"] / abs(stats_dict["mean"])
        else:
            stats_dict["cv"] = None

        # Standard error of mean
        stats_dict["sem"] = float(stats.sem(series))

        # Confidence intervals for mean
        if confidence_level and len(series) > 1:
            1 - confidence_level
            ci = stats.t.interval(
                confidence_level,
                len(series) - 1,
                loc=series.mean(),
                scale=stats.sem(series),
            )
            stats_dict["confidence_interval"] = {
                "lower": float(ci[0]),
                "upper": float(ci[1]),
                "confidence_level": confidence_level,
            }

        # Data quality indicators
        stats_dict["zeros"] = int((series == 0).sum())
        stats_dict["negatives"] = int((series < 0).sum())
        stats_dict["positives"] = int((series > 0).sum())

        return stats_dict

    def _get_categorical_stats(self, series: pd.Series) -> dict[str, Any]:
        """
        Get descriptive statistics for a categorical series.

        Args:
            series: Categorical pandas Series

        Returns:
            Dictionary containing categorical statistics
        """
        series = series.dropna()

        if len(series) == 0:
            return {"count": 0, "error": "No valid categorical values"}

        value_counts = series.value_counts()

        stats_dict = {
            "count": len(series),
            "unique": series.nunique(),
            "top": str(value_counts.index[0]) if not value_counts.empty else None,
            "freq": int(value_counts.iloc[0]) if not value_counts.empty else 0,
            "value_counts": value_counts.head(10).to_dict(),
            "proportion": (value_counts / len(series)).head(10).to_dict(),
        }

        # Entropy (measure of diversity)
        proportions = value_counts / len(series)
        stats_dict["entropy"] = float(-np.sum(proportions * np.log2(proportions)))

        # Gini coefficient (measure of inequality)
        sorted_values = np.sort(value_counts.values)[::-1]  # Descending order
        n = len(sorted_values)
        index = np.arange(1, n + 1)
        stats_dict["gini"] = float(
            (np.sum((2 * index - n - 1) * sorted_values)) / (n * np.sum(sorted_values))
        )

        # Simpson's diversity index
        n_total = len(series)
        simpson = np.sum(
            [
                (count * (count - 1)) / (n_total * (n_total - 1))
                for count in value_counts.values
                if n_total > 1
            ]
        )
        stats_dict["simpson_diversity"] = float(simpson if n_total > 1 else 0)

        return stats_dict

    def get_percentiles(
        self, series: pd.Series, percentiles: list[float] | None = None
    ) -> dict[str, float]:
        """
        Calculate percentiles for a numeric series.

        Args:
            series: Numeric pandas Series
            percentiles: List of percentile values (0-1 scale)

        Returns:
            Dictionary mapping percentile labels to values
        """
        if percentiles is None:
            percentiles = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]

        series = series.dropna()

        if len(series) == 0:
            return {}

        result = {}
        for p in percentiles:
            label = f"{int(p * 100)}%"
            result[label] = float(series.quantile(p))

        return result

    def get_summary_stats(
        self, df: pd.DataFrame, columns: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Get a summary of key statistics for quick overview.

        Args:
            df: DataFrame to analyze
            columns: Specific columns to analyze

        Returns:
            Dictionary containing summary statistics
        """
        if columns:
            df = df[columns]

        numeric_cols = df.select_dtypes(include=[np.number]).columns
        categorical_cols = df.select_dtypes(include=["object", "category"]).columns

        summary = {
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "numeric_columns": len(numeric_cols),
            "categorical_columns": len(categorical_cols),
            "missing_values_total": df.isnull().sum().sum(),
            "duplicate_rows": df.duplicated().sum(),
            "memory_usage_mb": df.memory_usage(deep=True).sum() / 1024 / 1024,
        }

        # Quick stats for numeric columns
        if len(numeric_cols) > 0:
            numeric_df = df[numeric_cols]
            summary["numeric_summary"] = {
                "mean_values": numeric_df.mean().to_dict(),
                "std_values": numeric_df.std().to_dict(),
                "min_values": numeric_df.min().to_dict(),
                "max_values": numeric_df.max().to_dict(),
            }

        # Quick stats for categorical columns
        if len(categorical_cols) > 0:
            summary["categorical_summary"] = {}
            for col in categorical_cols:
                series = df[col].dropna()
                if len(series) > 0:
                    value_counts = series.value_counts()
                    summary["categorical_summary"][col] = {
                        "unique_values": series.nunique(),
                        "most_frequent": (
                            str(value_counts.index[0])
                            if not value_counts.empty
                            else None
                        ),
                        "frequency": (
                            int(value_counts.iloc[0]) if not value_counts.empty else 0
                        ),
                    }

        return summary

    def compare_distributions(
        self,
        series1: pd.Series,
        series2: pd.Series,
        name1: str = "Series 1",
        name2: str = "Series 2",
    ) -> dict[str, Any]:
        """
        Compare descriptive statistics between two numeric series.

        Args:
            series1: First numeric series
            series2: Second numeric series
            name1: Name for first series
            name2: Name for second series

        Returns:
            Dictionary containing comparison statistics
        """
        stats1 = self._get_numeric_stats(series1)
        stats2 = self._get_numeric_stats(series2)

        comparison = {name1: stats1, name2: stats2, "differences": {}}

        # Calculate differences for key metrics
        key_metrics = ["mean", "std", "median", "min", "max", "skewness", "kurtosis"]
        for metric in key_metrics:
            if metric in stats1 and metric in stats2:
                diff = stats2[metric] - stats1[metric]
                pct_change = (
                    (diff / stats1[metric] * 100) if stats1[metric] != 0 else None
                )
                comparison["differences"][metric] = {
                    "absolute_difference": diff,
                    "percent_change": pct_change,
                }

        return comparison
