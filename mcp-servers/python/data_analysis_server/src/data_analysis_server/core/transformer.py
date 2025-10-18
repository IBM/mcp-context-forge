"""
Data transformation and cleaning functionality.
"""

# Standard
import logging
from typing import Any

# Third-Party
import numpy as np
import pandas as pd
from sklearn.preprocessing import (
    LabelEncoder,
    MinMaxScaler,
    StandardScaler,
)

logger = logging.getLogger(__name__)


class DataTransformer:
    """Provides data transformation and cleaning capabilities."""

    def __init__(self):
        """Initialize the data transformer."""
        self.scalers = {}
        self.encoders = {}

    def transform_data(
        self, df: pd.DataFrame, operations: list[dict[str, Any]], inplace: bool = False
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """
        Apply a series of transformations to the DataFrame.

        Args:
            df: DataFrame to transform
            operations: List of transformation operations
            inplace: Whether to modify the original DataFrame

        Returns:
            Tuple of (transformed DataFrame, transformation summary)
        """
        logger.info(f"Applying {len(operations)} transformation operations")

        if not inplace:
            df = df.copy()

        original_shape = df.shape
        transformation_log = []

        for i, operation in enumerate(operations):
            try:
                operation_type = operation.get("type") or operation.get("operation")
                operation_result = self._apply_single_operation(df, operation)

                transformation_log.append(
                    {
                        "operation_index": i,
                        "operation_type": operation_type,
                        "operation_params": operation,
                        "result": operation_result,
                        "shape_after": df.shape,
                    }
                )

                logger.info(
                    f"Applied {operation_type} operation: {operation_result.get('message', 'Success')}"
                )

            except Exception as e:
                error_msg = f"Error in operation {i} ({operation_type}): {str(e)}"
                logger.error(error_msg)
                transformation_log.append(
                    {
                        "operation_index": i,
                        "operation_type": operation_type,
                        "operation_params": operation,
                        "error": error_msg,
                        "shape_after": df.shape,
                    }
                )

        summary = {
            "original_shape": original_shape,
            "final_shape": df.shape,
            "operations_applied": len(
                [op for op in transformation_log if "error" not in op]
            ),
            "operations_failed": len(
                [op for op in transformation_log if "error" in op]
            ),
            "transformation_log": transformation_log,
        }

        return df, summary

    def _apply_single_operation(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply a single transformation operation."""
        operation_type = operation.get("type") or operation.get("operation")

        operation_methods = {
            "drop_na": self._drop_na,
            "fill_na": self._fill_na,
            "drop_duplicates": self._drop_duplicates,
            "drop_columns": self._drop_columns,
            "rename_columns": self._rename_columns,
            "filter_rows": self._filter_rows,
            "scale": self._scale_features,
            "normalize": self._normalize_features,
            "encode_categorical": self._encode_categorical,
            "create_dummy": self._create_dummy_variables,
            "bin_numeric": self._bin_numeric_variable,
            "transform_datetime": self._transform_datetime,
            "outlier_removal": self._remove_outliers,
            "feature_engineering": self._feature_engineering,
        }

        if operation_type not in operation_methods:
            raise ValueError(f"Unsupported operation type: {operation_type}")

        return operation_methods[operation_type](df, operation)

    def _drop_na(self, df: pd.DataFrame, operation: dict[str, Any]) -> dict[str, Any]:
        """Drop rows or columns with missing values."""
        columns = operation.get("columns")
        axis = operation.get("axis", 0)  # 0 for rows, 1 for columns
        how = operation.get("how", "any")  # 'any' or 'all'

        original_shape = df.shape

        if columns:
            if axis == 0:  # Drop rows
                df.dropna(subset=columns, how=how, inplace=True)
            else:  # Drop columns
                for col in columns:
                    if col in df.columns and df[col].isna().all():
                        df.drop(columns=[col], inplace=True)
        else:
            df.dropna(axis=axis, how=how, inplace=True)

        return {
            "message": "Dropped NA values",
            "rows_removed": original_shape[0] - df.shape[0],
            "columns_removed": original_shape[1] - df.shape[1],
        }

    def _fill_na(self, df: pd.DataFrame, operation: dict[str, Any]) -> dict[str, Any]:
        """Fill missing values with specified strategy."""
        columns = operation.get("columns", df.columns.tolist())
        method = operation.get("method", "mean")
        value = operation.get("value")

        filled_columns = []

        for col in columns:
            if col not in df.columns:
                continue

            na_count = df[col].isna().sum()
            if na_count == 0:
                continue

            if value is not None:
                df[col].fillna(value, inplace=True)
            elif method == "mean" and df[col].dtype in ["float64", "int64"]:
                df[col].fillna(df[col].mean(), inplace=True)
            elif method == "median" and df[col].dtype in ["float64", "int64"]:
                df[col].fillna(df[col].median(), inplace=True)
            elif method == "mode":
                df[col].fillna(
                    df[col].mode()[0] if not df[col].mode().empty else None,
                    inplace=True,
                )
            elif method == "forward_fill":
                df[col].fillna(method="ffill", inplace=True)
            elif method == "backward_fill":
                df[col].fillna(method="bfill", inplace=True)
            else:
                # Default to mode for categorical, mean for numeric
                if df[col].dtype == "object":
                    mode_val = (
                        df[col].mode()[0] if not df[col].mode().empty else "Unknown"
                    )
                    df[col].fillna(mode_val, inplace=True)
                else:
                    df[col].fillna(df[col].mean(), inplace=True)

            filled_columns.append({"column": col, "na_count": na_count})

        return {
            "message": f"Filled NA values using {method}",
            "columns_processed": filled_columns,
        }

    def _drop_duplicates(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Drop duplicate rows."""
        columns = operation.get("columns")
        keep = operation.get("keep", "first")

        original_count = len(df)
        df.drop_duplicates(subset=columns, keep=keep, inplace=True)

        return {
            "message": "Dropped duplicate rows",
            "duplicates_removed": original_count - len(df),
        }

    def _drop_columns(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Drop specified columns."""
        columns = operation.get("columns", [])

        existing_columns = [col for col in columns if col in df.columns]
        df.drop(columns=existing_columns, inplace=True)

        return {"message": "Dropped columns", "columns_dropped": existing_columns}

    def _rename_columns(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Rename columns."""
        mapping = operation.get("mapping", {})

        df.rename(columns=mapping, inplace=True)

        return {"message": "Renamed columns", "mappings": mapping}

    def _filter_rows(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Filter rows based on conditions."""
        condition = operation.get("condition")
        column = operation.get("column")
        operator = operation.get("operator", "==")
        value = operation.get("value")

        original_count = len(df)

        if condition:
            # Custom condition (string that can be evaluated)
            df_filtered = df.query(condition)
            df.drop(df.index, inplace=True)
            df = pd.concat([df, df_filtered])
        elif column and column in df.columns:
            if operator == "==":
                mask = df[column] == value
            elif operator == "!=":
                mask = df[column] != value
            elif operator == ">":
                mask = df[column] > value
            elif operator == ">=":
                mask = df[column] >= value
            elif operator == "<":
                mask = df[column] < value
            elif operator == "<=":
                mask = df[column] <= value
            elif operator == "in":
                mask = df[column].isin(value if isinstance(value, list) else [value])
            elif operator == "not_in":
                mask = ~df[column].isin(value if isinstance(value, list) else [value])
            else:
                raise ValueError(f"Unsupported operator: {operator}")

            df.drop(df[~mask].index, inplace=True)

        return {
            "message": "Filtered rows",
            "rows_removed": original_count - len(df),
            "rows_remaining": len(df),
        }

    def _scale_features(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Scale numeric features."""
        columns = operation.get("columns", [])
        method = operation.get("method", "standard")

        numeric_columns = [
            col
            for col in columns
            if col in df.columns and df[col].dtype in ["float64", "int64"]
        ]

        if not numeric_columns:
            return {"message": "No numeric columns found for scaling"}

        if method == "standard":
            scaler = StandardScaler()
        elif method == "minmax":
            scaler = MinMaxScaler()
        else:
            raise ValueError(f"Unsupported scaling method: {method}")

        df[numeric_columns] = scaler.fit_transform(df[numeric_columns])

        # Store scaler for potential inverse transform
        scaler_id = f"scaler_{len(self.scalers)}"
        self.scalers[scaler_id] = {
            "scaler": scaler,
            "columns": numeric_columns,
            "method": method,
        }

        return {
            "message": f"Scaled features using {method} scaling",
            "columns_scaled": numeric_columns,
            "scaler_id": scaler_id,
        }

    def _normalize_features(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Normalize numeric features to [0, 1] range."""
        columns = operation.get("columns", [])

        numeric_columns = [
            col
            for col in columns
            if col in df.columns and df[col].dtype in ["float64", "int64"]
        ]

        for col in numeric_columns:
            min_val = df[col].min()
            max_val = df[col].max()
            if max_val > min_val:
                df[col] = (df[col] - min_val) / (max_val - min_val)

        return {
            "message": "Normalized features to [0, 1] range",
            "columns_normalized": numeric_columns,
        }

    def _encode_categorical(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Encode categorical variables."""
        columns = operation.get("columns", [])
        method = operation.get("method", "label")

        categorical_columns = [col for col in columns if col in df.columns]
        encoded_info = []

        for col in categorical_columns:
            if method == "label":
                encoder = LabelEncoder()
                df[col] = encoder.fit_transform(df[col].astype(str))

                encoder_id = f"encoder_{len(self.encoders)}"
                self.encoders[encoder_id] = {
                    "encoder": encoder,
                    "column": col,
                    "method": method,
                }

                encoded_info.append(
                    {
                        "column": col,
                        "method": method,
                        "unique_values": len(encoder.classes_),
                        "encoder_id": encoder_id,
                    }
                )

            elif method == "one_hot":
                dummies = pd.get_dummies(df[col], prefix=col)
                df = pd.concat([df, dummies], axis=1)
                df.drop(columns=[col], inplace=True)

                encoded_info.append(
                    {
                        "column": col,
                        "method": method,
                        "new_columns": list(dummies.columns),
                    }
                )

        return {
            "message": f"Encoded categorical variables using {method} encoding",
            "encoded_columns": encoded_info,
        }

    def _create_dummy_variables(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Create dummy variables for categorical columns."""
        columns = operation.get("columns", [])
        prefix = operation.get("prefix")
        drop_first = operation.get("drop_first", False)

        dummy_info = []

        for col in columns:
            if col in df.columns:
                col_prefix = prefix or col
                dummies = pd.get_dummies(
                    df[col], prefix=col_prefix, drop_first=drop_first
                )
                df = pd.concat([df, dummies], axis=1)
                df.drop(columns=[col], inplace=True)

                dummy_info.append(
                    {"original_column": col, "dummy_columns": list(dummies.columns)}
                )

        return {"message": "Created dummy variables", "dummy_info": dummy_info}

    def _bin_numeric_variable(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Bin a numeric variable into categories."""
        column = operation.get("column")
        bins = operation.get("bins", 5)
        labels = operation.get("labels")
        new_column = operation.get("new_column", f"{column}_binned")

        if column not in df.columns:
            raise ValueError(f"Column {column} not found")

        if isinstance(bins, int):
            df[new_column] = pd.cut(df[column], bins=bins, labels=labels)
        else:
            df[new_column] = pd.cut(df[column], bins=bins, labels=labels)

        return {
            "message": f"Binned numeric variable {column}",
            "new_column": new_column,
            "bin_count": (
                len(df[new_column].cat.categories)
                if hasattr(df[new_column], "cat")
                else bins
            ),
        }

    def _transform_datetime(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Transform datetime columns to extract features."""
        column = operation.get("column")
        features = operation.get("features", ["year", "month", "day"])

        if column not in df.columns:
            raise ValueError(f"Column {column} not found")

        # Convert to datetime if not already
        df[column] = pd.to_datetime(df[column])

        new_columns = []

        if "year" in features:
            df[f"{column}_year"] = df[column].dt.year
            new_columns.append(f"{column}_year")
        if "month" in features:
            df[f"{column}_month"] = df[column].dt.month
            new_columns.append(f"{column}_month")
        if "day" in features:
            df[f"{column}_day"] = df[column].dt.day
            new_columns.append(f"{column}_day")
        if "dayofweek" in features:
            df[f"{column}_dayofweek"] = df[column].dt.dayofweek
            new_columns.append(f"{column}_dayofweek")
        if "quarter" in features:
            df[f"{column}_quarter"] = df[column].dt.quarter
            new_columns.append(f"{column}_quarter")

        return {
            "message": f"Extracted datetime features from {column}",
            "new_columns": new_columns,
        }

    def _remove_outliers(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Remove outliers using specified method."""
        columns = operation.get("columns", [])
        method = operation.get("method", "iqr")
        threshold = operation.get("threshold", 1.5)

        len(df)
        outliers_removed = 0

        for col in columns:
            if col not in df.columns or df[col].dtype not in ["float64", "int64"]:
                continue

            if method == "iqr":
                Q1 = df[col].quantile(0.25)
                Q3 = df[col].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - threshold * IQR
                upper_bound = Q3 + threshold * IQR

                outlier_mask = (df[col] < lower_bound) | (df[col] > upper_bound)

            elif method == "zscore":
                z_scores = np.abs((df[col] - df[col].mean()) / df[col].std())
                outlier_mask = z_scores > threshold

            else:
                raise ValueError(f"Unsupported outlier removal method: {method}")

            outliers_in_col = outlier_mask.sum()
            outliers_removed += outliers_in_col
            df.drop(df[outlier_mask].index, inplace=True)

        return {
            "message": f"Removed outliers using {method} method",
            "outliers_removed": outliers_removed,
            "rows_remaining": len(df),
        }

    def _feature_engineering(
        self, df: pd.DataFrame, operation: dict[str, Any]
    ) -> dict[str, Any]:
        """Create new features through engineering."""
        feature_type = operation.get("feature_type", "interaction")
        columns = operation.get("columns", [])

        if feature_type == "interaction" and len(columns) >= 2:
            # Create interaction features
            new_columns = []
            for i in range(len(columns)):
                for j in range(i + 1, len(columns)):
                    col1, col2 = columns[i], columns[j]
                    if col1 in df.columns and col2 in df.columns:
                        if df[col1].dtype in ["float64", "int64"] and df[
                            col2
                        ].dtype in ["float64", "int64"]:
                            new_col = f"{col1}_x_{col2}"
                            df[new_col] = df[col1] * df[col2]
                            new_columns.append(new_col)

            return {
                "message": "Created interaction features",
                "new_columns": new_columns,
            }

        elif feature_type == "polynomial" and len(columns) >= 1:
            # Create polynomial features
            degree = operation.get("degree", 2)
            new_columns = []

            for col in columns:
                if col in df.columns and df[col].dtype in ["float64", "int64"]:
                    for d in range(2, degree + 1):
                        new_col = f"{col}_power_{d}"
                        df[new_col] = df[col] ** d
                        new_columns.append(new_col)

            return {
                "message": f"Created polynomial features up to degree {degree}",
                "new_columns": new_columns,
            }

        elif feature_type == "ratio" and len(columns) >= 2:
            # Create ratio features
            new_column = operation.get("new_column")
            if not new_column:
                new_column = f"{columns[0]}_per_{columns[1]}"

            col1, col2 = columns[0], columns[1]
            if col1 in df.columns and col2 in df.columns:
                if df[col1].dtype in ["float64", "int64"] and df[col2].dtype in [
                    "float64",
                    "int64",
                ]:
                    # Avoid division by zero
                    df[new_column] = df[col1] / df[col2].replace(0, pd.NA)
                    return {
                        "message": f"Created ratio feature: {new_column}",
                        "new_columns": [new_column],
                    }
                else:
                    raise ValueError(
                        "Ratio feature engineering requires numeric columns"
                    )
            else:
                missing = [col for col in columns[:2] if col not in df.columns]
                raise ValueError(f"Columns not found: {missing}")

        else:
            raise ValueError(f"Unsupported feature engineering type: {feature_type}")

    def get_transformation_info(
        self, scaler_id: str | None = None, encoder_id: str | None = None
    ) -> dict[str, Any]:
        """Get information about stored transformations."""
        info = {}

        if scaler_id and scaler_id in self.scalers:
            info["scaler"] = self.scalers[scaler_id]
        elif not scaler_id:
            info["scalers"] = self.scalers

        if encoder_id and encoder_id in self.encoders:
            info["encoder"] = self.encoders[encoder_id]
        elif not encoder_id:
            info["encoders"] = self.encoders

        return info
