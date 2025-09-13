# -*- coding: utf-8 -*-
"""
Time series analysis functionality.
"""

# Standard
import logging
from typing import Any
import warnings

# Third-Party
import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=FutureWarning)


class TimeSeriesAnalyzer:
    """Provides time series analysis and forecasting capabilities."""

    def __init__(self):
        """Initialize the time series analyzer."""

    def analyze_time_series(
        self,
        df: pd.DataFrame,
        time_column: str,
        value_columns: list[str],
        frequency: str | None = None,
        operations: list[str] | None = None,
        forecast_periods: int = 12,
        confidence_intervals: bool = True,
    ) -> dict[str, Any]:
        """
        Perform comprehensive time series analysis.

        Args:
            df: DataFrame containing time series data
            time_column: Name of the time/date column
            value_columns: Names of value columns to analyze
            frequency: Time frequency (D, W, M, Q, Y)
            operations: List of operations (trend, seasonal, forecast)
            forecast_periods: Number of periods to forecast
            confidence_intervals: Include confidence intervals

        Returns:
            Dictionary containing analysis results
        """
        logger.info(f"Analyzing time series for columns {value_columns}")

        # Prepare data
        ts_df = self._prepare_time_series_data(df, time_column, value_columns, frequency)

        operations = operations or ["trend", "seasonal"]
        results = {}

        for column in value_columns:
            if column not in ts_df.columns:
                continue

            series = ts_df[column].dropna()
            if len(series) < 4:
                logger.warning(f"Insufficient data for time series analysis of {column}")
                continue

            column_results = {
                "column": column,
                "data_points": len(series),
                "time_range": {
                    "start": str(series.index.min()),
                    "end": str(series.index.max()),
                },
                "frequency": frequency or self._infer_frequency(series.index),
            }

            # Basic statistics
            column_results["basic_stats"] = self._get_basic_time_series_stats(series)

            # Trend analysis
            if "trend" in operations:
                column_results["trend_analysis"] = self._analyze_trend(series)

            # Seasonal analysis
            if "seasonal" in operations:
                column_results["seasonal_analysis"] = self._analyze_seasonality(series)

            # Stationarity tests
            column_results["stationarity"] = self._test_stationarity(series)

            # Autocorrelation analysis
            column_results["autocorrelation"] = self._analyze_autocorrelation(series)

            # Forecasting
            if "forecast" in operations:
                column_results["forecast"] = self._forecast_series(series, forecast_periods, confidence_intervals)

            results[column] = column_results

        return {
            "analysis_type": "time_series",
            "time_column": time_column,
            "frequency": frequency,
            "operations": operations,
            "results": results,
        }

    def _prepare_time_series_data(
        self,
        df: pd.DataFrame,
        time_column: str,
        value_columns: list[str],
        frequency: str | None,
    ) -> pd.DataFrame:
        """Prepare data for time series analysis."""
        # Copy and prepare dataframe
        ts_df = df[[time_column] + value_columns].copy()

        # Convert time column to datetime
        ts_df[time_column] = pd.to_datetime(ts_df[time_column])

        # Set time column as index
        ts_df.set_index(time_column, inplace=True)

        # Sort by time
        ts_df.sort_index(inplace=True)

        # Resample if frequency is specified
        if frequency:
            ts_df = ts_df.resample(frequency).mean()

        return ts_df

    def _infer_frequency(self, index: pd.DatetimeIndex) -> str:
        """Infer the frequency of a datetime index."""
        try:
            freq = pd.infer_freq(index)
            return freq or "irregular"
        except Exception:
            return "unknown"

    def _get_basic_time_series_stats(self, series: pd.Series) -> dict[str, Any]:
        """Get basic time series statistics."""
        return {
            "mean": float(series.mean()),
            "median": float(series.median()),
            "std": float(series.std()),
            "min": float(series.min()),
            "max": float(series.max()),
            "first_value": float(series.iloc[0]),
            "last_value": float(series.iloc[-1]),
            "total_change": float(series.iloc[-1] - series.iloc[0]),
            "percentage_change": (float((series.iloc[-1] - series.iloc[0]) / series.iloc[0] * 100) if series.iloc[0] != 0 else 0),
            "missing_values": int(series.isnull().sum()),
        }

    def _analyze_trend(self, series: pd.Series) -> dict[str, Any]:
        """Analyze trend in time series."""
        try:
            # Linear trend using least squares
            x = np.arange(len(series))
            y = series.values

            # Remove NaN values
            mask = ~np.isnan(y)
            x_clean = x[mask]
            y_clean = y[mask]

            if len(x_clean) < 2:
                return {"error": "Insufficient data for trend analysis"}

            slope, intercept, r_value, p_value, std_err = stats.linregress(x_clean, y_clean)

            # Trend direction
            if abs(slope) < std_err:
                trend_direction = "no trend"
            elif slope > 0:
                trend_direction = "increasing"
            else:
                trend_direction = "decreasing"

            # Trend strength
            r_squared = r_value**2
            if r_squared < 0.1:
                trend_strength = "very weak"
            elif r_squared < 0.3:
                trend_strength = "weak"
            elif r_squared < 0.6:
                trend_strength = "moderate"
            else:
                trend_strength = "strong"

            return {
                "slope": float(slope),
                "intercept": float(intercept),
                "r_squared": float(r_squared),
                "p_value": float(p_value),
                "standard_error": float(std_err),
                "direction": trend_direction,
                "strength": trend_strength,
                "significant": p_value < 0.05,
            }
        except Exception as e:
            return {"error": str(e)}

    def _analyze_seasonality(self, series: pd.Series) -> dict[str, Any]:
        """Analyze seasonality in time series."""
        try:
            # Simple seasonal analysis using autocorrelation
            if len(series) < 24:  # Need at least 2 years of monthly data or equivalent
                return {"error": "Insufficient data for seasonal analysis"}

            # Check for different seasonal periods
            seasonal_periods = []

            # Common seasonal periods
            periods_to_check = [7, 12, 24, 52]  # Weekly, monthly, bi-annual, yearly

            for period in periods_to_check:
                if len(series) >= 2 * period:
                    try:
                        # Calculate autocorrelation at seasonal lag
                        autocorr = series.autocorr(lag=period)
                        if abs(autocorr) > 0.3:  # Threshold for significant seasonality
                            seasonal_periods.append(
                                {
                                    "period": period,
                                    "autocorrelation": float(autocorr),
                                    "strength": ("strong" if abs(autocorr) > 0.6 else "moderate"),
                                }
                            )
                    except Exception:
                        continue

            # Seasonal decomposition (simple moving average)
            decomposition = self._simple_seasonal_decomposition(series)

            return {
                "seasonal_periods": seasonal_periods,
                "has_seasonality": len(seasonal_periods) > 0,
                "decomposition": decomposition,
            }
        except Exception as e:
            return {"error": str(e)}

    def _simple_seasonal_decomposition(self, series: pd.Series) -> dict[str, Any]:
        """Simple seasonal decomposition using moving averages."""
        try:
            # Use a 12-period moving average as a simple trend estimate
            period = min(12, len(series) // 4)
            if period < 2:
                return {"error": "Insufficient data for decomposition"}

            # Trend component (centered moving average)
            trend = series.rolling(window=period, center=True).mean()

            # Detrended series
            detrended = series - trend

            # Seasonal component (average for each period)
            seasonal = detrended.groupby(detrended.index.dayofyear % period).transform("mean")

            # Residual component
            residual = series - trend - seasonal

            return {
                "trend_variance": float(trend.var()) if not trend.isna().all() else 0,
                "seasonal_variance": (float(seasonal.var()) if not seasonal.isna().all() else 0),
                "residual_variance": (float(residual.var()) if not residual.isna().all() else 0),
                "seasonal_strength": (float(seasonal.var() / series.var()) if series.var() > 0 else 0),
            }
        except Exception as e:
            return {"error": str(e)}

    def _test_stationarity(self, series: pd.Series) -> dict[str, Any]:
        """Test for stationarity using simple statistical tests."""
        try:
            results = {}

            # Rolling statistics test
            window_size = min(len(series) // 4, 12)
            if window_size >= 2:
                rolling_mean = series.rolling(window=window_size).mean()
                rolling_std = series.rolling(window=window_size).std()

                # Check if rolling statistics are roughly constant
                mean_stability = rolling_mean.std() / series.std() if series.std() > 0 else 0
                std_stability = rolling_std.std() / series.std() if series.std() > 0 else 0

                results["rolling_stats"] = {
                    "mean_stability": float(mean_stability),
                    "std_stability": float(std_stability),
                    "appears_stationary": mean_stability < 0.1 and std_stability < 0.1,
                }

            # First difference test
            if len(series) > 1:
                diff_series = series.diff().dropna()
                results["first_difference"] = {
                    "variance_reduction": (float((series.var() - diff_series.var()) / series.var()) if series.var() > 0 else 0),
                    "mean_diff": float(diff_series.mean()),
                    "std_diff": float(diff_series.std()),
                }

            return results
        except Exception as e:
            return {"error": str(e)}

    def _analyze_autocorrelation(self, series: pd.Series) -> dict[str, Any]:
        """Analyze autocorrelation structure."""
        try:
            max_lags = min(len(series) // 4, 20)
            autocorrelations = []

            for lag in range(1, max_lags + 1):
                try:
                    autocorr = series.autocorr(lag=lag)
                    if not np.isnan(autocorr):
                        autocorrelations.append({"lag": lag, "autocorrelation": float(autocorr)})
                except Exception:
                    continue

            # Find significant autocorrelations
            significant_lags = [item for item in autocorrelations if abs(item["autocorrelation"]) > 0.2]

            return {
                "autocorrelations": autocorrelations,
                "significant_lags": significant_lags,
                "max_autocorr": (max([abs(item["autocorrelation"]) for item in autocorrelations]) if autocorrelations else 0),
            }
        except Exception as e:
            return {"error": str(e)}

    def _forecast_series(self, series: pd.Series, forecast_periods: int, confidence_intervals: bool) -> dict[str, Any]:
        """Simple forecasting using trend and seasonal components."""
        try:
            if len(series) < 4:
                return {"error": "Insufficient data for forecasting"}

            # Simple linear trend forecast
            x = np.arange(len(series))
            y = series.values

            # Remove NaN values
            mask = ~np.isnan(y)
            x_clean = x[mask]
            y_clean = y[mask]

            if len(x_clean) < 2:
                return {"error": "Insufficient clean data for forecasting"}

            # Fit linear trend
            slope, intercept, r_value, p_value, std_err = stats.linregress(x_clean, y_clean)

            # Generate future time points
            future_x = np.arange(len(series), len(series) + forecast_periods)

            # Trend forecast
            trend_forecast = slope * future_x + intercept

            # Add seasonal component if detected
            try:
                seasonal_pattern = self._extract_seasonal_pattern(series)
                if seasonal_pattern is not None:
                    seasonal_component = np.tile(seasonal_pattern, forecast_periods // len(seasonal_pattern) + 1)[:forecast_periods]
                    forecast = trend_forecast + seasonal_component
                else:
                    forecast = trend_forecast
            except Exception:
                forecast = trend_forecast

            # Create forecast index
            freq = self._infer_frequency(series.index)
            if freq and freq != "irregular":
                forecast_index = pd.date_range(start=series.index[-1], periods=forecast_periods + 1, freq=freq)[1:]  # Exclude the last historical point
            else:
                # Create a simple numeric index
                forecast_index = range(len(series), len(series) + forecast_periods)

            # Confidence intervals (simple approach using trend standard error)
            if confidence_intervals and std_err > 0:
                confidence_level = 0.95
                t_val = stats.t.ppf((1 + confidence_level) / 2, len(x_clean) - 2)
                margin_of_error = t_val * std_err * np.sqrt(1 + 1 / len(x_clean))

                upper_bound = forecast + margin_of_error
                lower_bound = forecast - margin_of_error
            else:
                upper_bound = lower_bound = None

            result = {
                "forecast": forecast.tolist(),
                "forecast_index": [str(idx) for idx in forecast_index],
                "method": "linear_trend_with_seasonal",
                "trend_slope": float(slope),
                "trend_r_squared": float(r_value**2),
                "periods": forecast_periods,
            }

            if confidence_intervals and upper_bound is not None:
                result["confidence_intervals"] = {
                    "upper_bound": upper_bound.tolist(),
                    "lower_bound": lower_bound.tolist(),
                    "confidence_level": 0.95,
                }

            return result
        except Exception as e:
            return {"error": str(e)}

    def _extract_seasonal_pattern(self, series: pd.Series, period: int = 12) -> np.ndarray | None:
        """Extract a simple seasonal pattern from the series."""
        try:
            if len(series) < 2 * period:
                return None

            # Group by seasonal period and take mean
            seasonal_groups = [series.iloc[i::period].mean() for i in range(period)]

            # Check if there's actual seasonal variation
            seasonal_array = np.array(seasonal_groups)
            if np.std(seasonal_array) < 0.1 * np.std(series):
                return None  # No significant seasonal pattern

            # Normalize to have mean of 0
            return seasonal_array - np.mean(seasonal_array)
        except Exception:
            return None
