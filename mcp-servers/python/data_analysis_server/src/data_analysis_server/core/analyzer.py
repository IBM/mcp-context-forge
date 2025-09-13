"""
Data analysis and profiling functionality.
"""

# Standard
import logging
from typing import Any

# Third-Party
import numpy as np
import pandas as pd
from scipy import stats

# Local
from ..statistics.descriptive import DescriptiveStatistics

logger = logging.getLogger(__name__)


class DataAnalyzer:
    """Provides comprehensive data analysis capabilities."""

    def __init__(self):
        """Initialize the data analyzer."""
        self.descriptive_stats = DescriptiveStatistics()

    def analyze_dataset(
        self,
        df: pd.DataFrame,
        analysis_type: str = "exploratory",
        columns: list[str] | None = None,
        include_distributions: bool = True,
        include_correlations: bool = True,
        include_outliers: bool = True,
        confidence_level: float = 0.95,
    ) -> dict[str, Any]:
        """
        Perform comprehensive dataset analysis.

        Args:
            df: DataFrame to analyze
            analysis_type: Type of analysis (descriptive, exploratory, correlation)
            columns: Specific columns to analyze (None for all)
            include_distributions: Include distribution analysis
            include_correlations: Include correlation analysis
            include_outliers: Include outlier detection
            confidence_level: Confidence level for statistics

        Returns:
            Dictionary containing analysis results
        """
        logger.info(f"Performing {analysis_type} analysis on dataset")

        if columns:
            df = df[columns]

        result = {
            "analysis_type": analysis_type,
            "dataset_shape": df.shape,
            "confidence_level": confidence_level,
            "basic_info": self.descriptive_stats.get_basic_info(df),
            "descriptive_stats": self.descriptive_stats.get_descriptive_stats(
                df, confidence_level, columns
            ),
        }

        if analysis_type in ["exploratory", "correlation"]:
            if include_distributions:
                result["distributions"] = self._analyze_distributions(df)
            if include_correlations:
                result["correlations"] = self._analyze_correlations(df)
            if include_outliers:
                result["outliers"] = self._detect_outliers(df)

        return result

    def _analyze_distributions(self, df: pd.DataFrame) -> dict[str, Any]:
        """Analyze distributions of numeric columns."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        distributions = {}

        for col in numeric_cols:
            series = df[col].dropna()
            if len(series) < 3:
                continue

            dist_info = {
                "normality_test": self._test_normality(series),
                "histogram_bins": self._get_histogram_bins(series),
                "percentiles": self._get_percentiles(series),
            }

            distributions[col] = dist_info

        return distributions

    def _analyze_correlations(self, df: pd.DataFrame) -> dict[str, Any]:
        """Analyze correlations between numeric columns."""
        numeric_df = df.select_dtypes(include=[np.number])

        if numeric_df.shape[1] < 2:
            return {"error": "Need at least 2 numeric columns for correlation analysis"}

        correlations = {
            "pearson": numeric_df.corr(method="pearson").to_dict(),
            "spearman": numeric_df.corr(method="spearman").to_dict(),
            "kendall": numeric_df.corr(method="kendall").to_dict(),
        }

        # Find strong correlations
        pearson_corr = numeric_df.corr(method="pearson")
        strong_correlations = []

        for i in range(len(pearson_corr.columns)):
            for j in range(i + 1, len(pearson_corr.columns)):
                col1 = pearson_corr.columns[i]
                col2 = pearson_corr.columns[j]
                corr_value = pearson_corr.iloc[i, j]

                if abs(corr_value) > 0.7:  # Strong correlation threshold
                    strong_correlations.append(
                        {
                            "variable1": col1,
                            "variable2": col2,
                            "correlation": float(corr_value),
                            "strength": (
                                "strong" if abs(corr_value) > 0.8 else "moderate"
                            ),
                        }
                    )

        correlations["strong_correlations"] = strong_correlations
        return correlations

    def _detect_outliers(self, df: pd.DataFrame) -> dict[str, Any]:
        """Detect outliers in numeric columns."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        outliers = {}

        for col in numeric_cols:
            series = df[col].dropna()
            if len(series) < 4:
                continue

            outlier_info = {
                "iqr_method": self._detect_iqr_outliers(series),
                "zscore_method": self._detect_zscore_outliers(series),
                "isolation_forest": self._detect_isolation_forest_outliers(series),
            }

            outliers[col] = outlier_info

        return outliers

    def _test_normality(self, series: pd.Series) -> dict[str, Any]:
        """Test normality of a numeric series."""
        try:
            # Shapiro-Wilk test (for n < 5000)
            if len(series) < 5000:
                shapiro_stat, shapiro_p = stats.shapiro(series)
                shapiro_result = {
                    "statistic": float(shapiro_stat),
                    "p_value": float(shapiro_p),
                    "is_normal": shapiro_p > 0.05,
                }
            else:
                shapiro_result = {"error": "Sample too large for Shapiro-Wilk test"}

            # Kolmogorov-Smirnov test
            ks_stat, ks_p = stats.kstest(series, "norm")
            ks_result = {
                "statistic": float(ks_stat),
                "p_value": float(ks_p),
                "is_normal": ks_p > 0.05,
            }

            return {"shapiro_wilk": shapiro_result, "kolmogorov_smirnov": ks_result}
        except Exception as e:
            return {"error": str(e)}

    def _get_histogram_bins(self, series: pd.Series) -> dict[str, Any]:
        """Calculate optimal histogram bins."""
        try:
            # Sturges' rule
            sturges_bins = int(np.ceil(np.log2(len(series)) + 1))

            # Freedman-Diaconis rule
            iqr = series.quantile(0.75) - series.quantile(0.25)
            if iqr > 0:
                bin_width = 2 * iqr / (len(series) ** (1 / 3))
                fd_bins = int(np.ceil((series.max() - series.min()) / bin_width))
            else:
                fd_bins = sturges_bins

            return {
                "sturges": sturges_bins,
                "freedman_diaconis": fd_bins,
                "recommended": min(max(sturges_bins, 10), 50),
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_percentiles(self, series: pd.Series) -> dict[str, float]:
        """Get percentile values for a series."""
        percentiles = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
        return {f"p{int(p*100)}": float(series.quantile(p)) for p in percentiles}

    def _detect_iqr_outliers(self, series: pd.Series) -> dict[str, Any]:
        """Detect outliers using IQR method."""
        Q1 = series.quantile(0.25)
        Q3 = series.quantile(0.75)
        IQR = Q3 - Q1

        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR

        outliers = series[(series < lower_bound) | (series > upper_bound)]

        return {
            "method": "IQR",
            "lower_bound": float(lower_bound),
            "upper_bound": float(upper_bound),
            "outlier_count": len(outliers),
            "outlier_percentage": float(len(outliers) / len(series) * 100),
            "outliers": outliers.tolist()[:50],  # Limit to first 50
        }

    def _detect_zscore_outliers(
        self, series: pd.Series, threshold: float = 3.0
    ) -> dict[str, Any]:
        """Detect outliers using Z-score method."""
        z_scores = np.abs(stats.zscore(series))
        outliers = series[z_scores > threshold]

        return {
            "method": "Z-Score",
            "threshold": threshold,
            "outlier_count": len(outliers),
            "outlier_percentage": float(len(outliers) / len(series) * 100),
            "outliers": outliers.tolist()[:50],  # Limit to first 50
        }

    def _detect_isolation_forest_outliers(self, series: pd.Series) -> dict[str, Any]:
        """Detect outliers using Isolation Forest."""
        try:
            # Third-Party
            from sklearn.ensemble import IsolationForest

            X = series.values.reshape(-1, 1)
            iso_forest = IsolationForest(contamination=0.1, random_state=42)
            outlier_labels = iso_forest.fit_predict(X)

            outliers = series[outlier_labels == -1]

            return {
                "method": "Isolation Forest",
                "outlier_count": len(outliers),
                "outlier_percentage": float(len(outliers) / len(series) * 100),
                "outliers": outliers.tolist()[:50],  # Limit to first 50
            }
        except ImportError:
            return {"error": "sklearn not available"}
        except Exception as e:
            return {"error": str(e)}
