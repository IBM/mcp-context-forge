# -*- coding: utf-8 -*-
"""
SQL-like query parsing and execution for pandas DataFrames.
"""

# Standard
import logging
import re
from typing import Any

# Third-Party
import pandas as pd

logger = logging.getLogger(__name__)


class DataQueryParser:
    """Provides SQL-like querying capabilities for pandas DataFrames."""

    def __init__(self, max_result_size: int = 10000):
        """
        Initialize the query parser.

        Args:
            max_result_size: Maximum number of rows to return
        """
        self.max_result_size = max_result_size

    def execute_query(self, df: pd.DataFrame, query: str, limit: int | None = None, offset: int = 0) -> dict[str, Any]:
        """
        Execute a SQL-like query on a pandas DataFrame.

        Args:
            df: DataFrame to query
            query: SQL-like query string
            limit: Maximum number of rows to return
            offset: Number of rows to skip

        Returns:
            Dictionary containing query results and metadata
        """
        logger.info(f"Executing query: {query}")

        try:
            # Parse and execute the query
            result_df = self._parse_and_execute(df, query)

            # Apply offset and limit
            total_rows = len(result_df)

            if offset > 0:
                result_df = result_df.iloc[offset:]

            if limit:
                result_df = result_df.head(limit)
            elif len(result_df) > self.max_result_size:
                result_df = result_df.head(self.max_result_size)
                logger.warning(f"Result truncated to {self.max_result_size} rows")

            return {
                "success": True,
                "data": result_df,
                "metadata": {
                    "total_rows": total_rows,
                    "returned_rows": len(result_df),
                    "offset": offset,
                    "limit": limit,
                    "columns": list(result_df.columns),
                    "query": query,
                },
            }

        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}")
            return {"success": False, "error": str(e), "query": query}

    def _parse_and_execute(self, df: pd.DataFrame, query: str) -> pd.DataFrame:
        """Parse and execute the SQL-like query."""
        query = query.strip()
        query_lower = query.lower()

        # Basic SELECT query parsing
        if query_lower.startswith("select"):
            return self._execute_select_query(df, query)
        else:
            # Try to execute as a pandas query expression
            return df.query(query)

    def _execute_select_query(self, df: pd.DataFrame, query: str) -> pd.DataFrame:
        """Execute a SELECT-style query."""
        # This is a simplified SQL parser - in production you'd want a more robust solution

        query = query.strip()
        query_parts = self._parse_select_statement(query)

        result_df = df.copy()

        # Apply WHERE clause
        if query_parts.get("where"):
            result_df = self._apply_where_clause(result_df, query_parts["where"])

        # Apply GROUP BY or handle aggregates without grouping
        if query_parts.get("group_by"):
            result_df = self._apply_group_by(result_df, query_parts["group_by"], query_parts.get("aggregates"))

            # Apply HAVING clause after GROUP BY
            if query_parts.get("having"):
                result_df = self._apply_having_clause(result_df, query_parts["having"])
        elif query_parts.get("aggregates"):
            # Handle aggregates without GROUP BY (e.g., SELECT COUNT(*), SUM(revenue) FROM table)
            result_df = self._apply_global_aggregates(result_df, query_parts["aggregates"])

        # Apply ORDER BY
        if query_parts.get("order_by"):
            result_df = self._apply_order_by(result_df, query_parts["order_by"])

        # Apply column selection
        if query_parts.get("columns") and query_parts["columns"] != ["*"]:
            result_df = self._apply_column_selection(result_df, query_parts["columns"])

        # Apply LIMIT and OFFSET from query
        if query_parts.get("limit"):
            offset = query_parts.get("offset", 0)
            if offset > 0:
                result_df = result_df.iloc[offset:]
            result_df = result_df.head(query_parts["limit"])

        return result_df

    def _parse_select_statement(self, query: str) -> dict[str, Any]:
        """Parse a SELECT statement into components."""
        query_parts = {}

        # Remove extra whitespace and normalize
        query = re.sub(r"\s+", " ", query.strip())

        # Extract SELECT columns
        select_match = re.search(r"select\s+(.*?)\s+from", query, re.IGNORECASE)
        if select_match:
            columns_str = select_match.group(1).strip()
            if columns_str == "*":
                query_parts["columns"] = ["*"]
            else:
                # Parse column list (including aggregates)
                columns = []
                aggregates = {}

                for col_expr in columns_str.split(","):
                    col_expr = col_expr.strip()

                    # Check for aggregate functions
                    agg_match = re.search(
                        r"(count|sum|avg|min|max|std|var|stddev)\s*\(\s*([^)]+)\s*\)",
                        col_expr,
                        re.IGNORECASE,
                    )
                    if agg_match:
                        func = agg_match.group(1).lower()
                        column = agg_match.group(2).strip()

                        # Handle alias
                        alias_match = re.search(r"as\s+(\w+)", col_expr, re.IGNORECASE)
                        alias = alias_match.group(1) if alias_match else f"{func}_{column}"

                        aggregates[alias] = (func, column)
                        columns.append(alias)
                    else:
                        # Regular column (remove alias if present)
                        col_name = re.sub(r"\s+as\s+\w+", "", col_expr, flags=re.IGNORECASE).strip()
                        columns.append(col_name)

                query_parts["columns"] = columns
                if aggregates:
                    query_parts["aggregates"] = aggregates

        # Extract WHERE clause - improved to handle LIMIT in WHERE
        where_match = re.search(
            r"where\s+(.*?)(?:\s+group\s+by|\s+having|\s+order\s+by|\s+limit|$)",
            query,
            re.IGNORECASE,
        )
        if where_match:
            query_parts["where"] = where_match.group(1).strip()

        # Extract GROUP BY - improved to handle HAVING
        group_match = re.search(
            r"group\s+by\s+(.*?)(?:\s+having|\s+order\s+by|\s+limit|$)",
            query,
            re.IGNORECASE,
        )
        if group_match:
            group_cols = [col.strip() for col in group_match.group(1).split(",")]
            query_parts["group_by"] = group_cols

        # Extract HAVING clause
        having_match = re.search(r"having\s+(.*?)(?:\s+order\s+by|\s+limit|$)", query, re.IGNORECASE)
        if having_match:
            query_parts["having"] = having_match.group(1).strip()

        # Extract ORDER BY
        order_match = re.search(r"order\s+by\s+(.*?)(?:\s+limit|$)", query, re.IGNORECASE)
        if order_match:
            order_expr = order_match.group(1).strip()
            query_parts["order_by"] = self._parse_order_by(order_expr)

        # Extract LIMIT clause
        limit_match = re.search(r"limit\s+(\d+)(?:\s+offset\s+(\d+))?$", query, re.IGNORECASE)
        if limit_match:
            query_parts["limit"] = int(limit_match.group(1))
            if limit_match.group(2):
                query_parts["offset"] = int(limit_match.group(2))

        return query_parts

    def _apply_where_clause(self, df: pd.DataFrame, where_clause: str) -> pd.DataFrame:
        """Apply WHERE clause filtering."""
        try:
            # Simple condition parsing - convert SQL-like syntax to pandas query
            condition = where_clause

            # Fix quote handling: Convert single quotes to double quotes for pandas query
            condition = self._fix_quotes_in_condition(condition)

            # Convert SQL operators to pandas query syntax
            condition = re.sub(r"\bAND\b", "and", condition, flags=re.IGNORECASE)
            condition = re.sub(r"\bOR\b", "or", condition, flags=re.IGNORECASE)
            condition = re.sub(r"\bNOT\b", "not", condition, flags=re.IGNORECASE)
            condition = re.sub(r"\bIS NULL\b", ".isna()", condition, flags=re.IGNORECASE)
            condition = re.sub(r"\bIS NOT NULL\b", ".notna()", condition, flags=re.IGNORECASE)

            # Handle LIKE operator
            condition = self._handle_like_operator(condition)

            # Handle IN operator
            condition = self._handle_in_operator(condition)

            return df.query(condition)
        except Exception as e:
            logger.warning(f"Failed to apply WHERE clause '{where_clause}': {e}")
            return df

    def _fix_quotes_in_condition(self, condition: str) -> str:
        """Fix quote handling in WHERE conditions."""
        # Replace single quotes around string literals with double quotes
        # Pattern: word = 'value' -> word == "value"

        # Handle equals with single quotes
        pattern = r"(\w+)\s*=\s*'([^']*)'"
        condition = re.sub(pattern, r'\1 == "\2"', condition)

        # Handle not equals with single quotes
        pattern = r"(\w+)\s*!=\s*'([^']*)'"
        condition = re.sub(pattern, r'\1 != "\2"', condition)

        # Handle IN clauses with single quotes
        pattern = r"'([^']*)'"

        def replace_quotes_in_in(match):
            return f'"{match.group(1)}"'

        # Only replace quotes that aren't already handled by the above patterns
        # This handles cases like IN ('val1', 'val2')
        if " IN " in condition.upper():
            condition = re.sub(r"'([^']*)'", r'"\1"', condition)

        return condition

    def _handle_like_operator(self, condition: str) -> str:
        """Handle LIKE operator conversion."""
        # Convert SQL LIKE to pandas str.contains
        # Pattern: column LIKE 'value' -> column.str.contains("value")
        pattern = r"(\w+)\s+LIKE\s+'([^']*)'"
        condition = re.sub(pattern, r'\1.str.contains("\2")', condition, flags=re.IGNORECASE)

        # Handle LIKE with double quotes
        pattern = r"(\w+)\s+LIKE\s+\"([^\"]*)\""
        condition = re.sub(pattern, r'\1.str.contains("\2")', condition, flags=re.IGNORECASE)

        return condition

    def _handle_in_operator(self, condition: str) -> str:
        """Handle IN operator conversion."""
        # Pattern: column IN ('val1', 'val2') -> column.isin(["val1", "val2"])
        in_pattern = r"(\w+)\s+IN\s+\((.*?)\)"

        def replace_in(match):
            column = match.group(1)
            values = match.group(2)
            return f"{column}.isin([{values}])"

        condition = re.sub(in_pattern, replace_in, condition, flags=re.IGNORECASE)
        return condition

    def _apply_group_by(
        self,
        df: pd.DataFrame,
        group_cols: list[str],
        aggregates: dict[str, tuple] | None,
    ) -> pd.DataFrame:
        """Apply GROUP BY with optional aggregations."""
        try:
            # Clean group columns - remove HAVING clause if present
            cleaned_group_cols = []
            for col in group_cols:
                # Remove anything after HAVING
                clean_col = re.sub(r"\s+having\s+.*", "", col, flags=re.IGNORECASE).strip()
                if clean_col:
                    cleaned_group_cols.append(clean_col)

            # Validate group columns exist
            valid_group_cols = [col for col in cleaned_group_cols if col in df.columns]

            if not valid_group_cols:
                logger.warning(f"No valid group columns found: {cleaned_group_cols}")
                return df

            grouped = df.groupby(valid_group_cols)

            if aggregates:
                # Apply specified aggregations
                agg_dict = {}
                rename_map = {}

                for alias, (func, column) in aggregates.items():
                    # Handle special cases
                    if column == "*" and func == "count":
                        # COUNT(*) - count rows
                        agg_dict[df.columns[0]] = "count"
                        rename_map[df.columns[0]] = alias
                    elif column in df.columns or column == "*":
                        actual_column = df.columns[0] if column == "*" else column

                        if func == "count":
                            agg_dict[actual_column] = "count"
                        elif func == "sum":
                            agg_dict[actual_column] = "sum"
                        elif func == "avg":
                            agg_dict[actual_column] = "mean"
                        elif func == "min":
                            agg_dict[actual_column] = "min"
                        elif func == "max":
                            agg_dict[actual_column] = "max"
                        elif func == "std":
                            agg_dict[actual_column] = "std"
                        elif func == "var":
                            agg_dict[actual_column] = "var"
                        elif func == "stddev":
                            agg_dict[actual_column] = "std"

                        if actual_column not in rename_map:
                            rename_map[actual_column] = alias

                if agg_dict:
                    result = grouped.agg(agg_dict).reset_index()

                    # Rename columns according to aliases
                    for old_col, new_col in rename_map.items():
                        if old_col in result.columns:
                            result = result.rename(columns={old_col: new_col})

                    return result
                else:
                    # Default aggregation (count)
                    return grouped.size().reset_index(name="count")
            else:
                # Default aggregation (count)
                return grouped.size().reset_index(name="count")

        except Exception as e:
            logger.warning(f"Failed to apply GROUP BY: {e}")
            return df

    def _apply_global_aggregates(self, df: pd.DataFrame, aggregates: dict[str, tuple]) -> pd.DataFrame:
        """Apply aggregate functions without GROUP BY (global aggregates)."""
        try:
            result_data = {}

            for alias, (func, column) in aggregates.items():
                # Handle special cases
                if column == "*" and func == "count":
                    result_data[alias] = len(df)
                elif column in df.columns or column == "*":
                    actual_column = df.columns[0] if column == "*" else column

                    if func == "count":
                        result_data[alias] = len(df) if column == "*" else df[actual_column].count()
                    elif func == "sum":
                        result_data[alias] = df[actual_column].sum()
                    elif func == "avg":
                        result_data[alias] = df[actual_column].mean()
                    elif func == "min":
                        result_data[alias] = df[actual_column].min()
                    elif func == "max":
                        result_data[alias] = df[actual_column].max()
                    elif func == "std" or func == "stddev":
                        result_data[alias] = df[actual_column].std()
                    elif func == "var":
                        result_data[alias] = df[actual_column].var()

            # Create a DataFrame with a single row containing the aggregate results
            return pd.DataFrame([result_data])

        except Exception as e:
            logger.warning(f"Failed to apply global aggregates: {e}")
            return df

    def _apply_having_clause(self, df: pd.DataFrame, having_clause: str) -> pd.DataFrame:
        """Apply HAVING clause filtering after GROUP BY."""
        try:
            # HAVING works like WHERE but on aggregated results
            condition = having_clause

            # Handle COUNT(*) references - replace with appropriate column name
            if "COUNT(*)" in condition.upper():
                # Find a column that was likely created by COUNT aggregation
                count_columns = [col for col in df.columns if "count" in col.lower() or col.endswith("_count")]
                if count_columns:
                    condition = re.sub(r"COUNT\(\*\)", count_columns[0], condition, flags=re.IGNORECASE)
                else:
                    # Fallback - use the last column (often the count column)
                    condition = re.sub(r"COUNT\(\*\)", df.columns[-1], condition, flags=re.IGNORECASE)

            # Fix quote handling: Convert single quotes to double quotes
            condition = self._fix_quotes_in_condition(condition)

            # Convert SQL operators to pandas query syntax
            condition = re.sub(r"\bAND\b", "and", condition, flags=re.IGNORECASE)
            condition = re.sub(r"\bOR\b", "or", condition, flags=re.IGNORECASE)
            condition = re.sub(r"\bNOT\b", "not", condition, flags=re.IGNORECASE)

            # Handle LIKE operator
            condition = self._handle_like_operator(condition)

            # Handle IN operator
            condition = self._handle_in_operator(condition)

            return df.query(condition)
        except Exception as e:
            logger.warning(f"Failed to apply HAVING clause '{having_clause}': {e}")
            return df

    def _apply_order_by(self, df: pd.DataFrame, order_specs: list[tuple]) -> pd.DataFrame:
        """Apply ORDER BY clause."""
        try:
            columns = []
            ascending = []

            for column, direction in order_specs:
                if column in df.columns:
                    columns.append(column)
                    ascending.append(direction.lower() != "desc")

            if columns:
                return df.sort_values(by=columns, ascending=ascending)
            else:
                return df

        except Exception as e:
            logger.warning(f"Failed to apply ORDER BY: {e}")
            return df

    def _parse_order_by(self, order_expr: str) -> list[tuple]:
        """Parse ORDER BY expression."""
        order_specs = []

        for item in order_expr.split(","):
            item = item.strip()
            parts = item.split()

            column = parts[0]
            direction = parts[1] if len(parts) > 1 else "ASC"

            order_specs.append((column, direction))

        return order_specs

    def _apply_column_selection(self, df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        """Apply column selection."""
        try:
            # Filter to columns that exist in the DataFrame
            valid_columns = [col for col in columns if col in df.columns]

            if valid_columns:
                return df[valid_columns]
            else:
                logger.warning(f"No valid columns found: {columns}")
                return df

        except Exception as e:
            logger.warning(f"Failed to apply column selection: {e}")
            return df

    def validate_query(self, query: str) -> dict[str, Any]:
        """
        Validate a query without executing it.

        Args:
            query: SQL-like query string

        Returns:
            Dictionary containing validation results
        """
        try:
            query = query.strip()
            query_lower = query.lower()

            validation_result = {
                "valid": True,
                "query_type": "unknown",
                "warnings": [],
                "errors": [],
            }

            # Check if it's a SELECT query
            if query_lower.startswith("select"):
                validation_result["query_type"] = "select"

                # Basic syntax validation
                if "from" not in query_lower:
                    validation_result["warnings"].append("Query appears to be missing FROM clause")

                # Check for potentially dangerous operations
                dangerous_keywords = [
                    "drop",
                    "delete",
                    "update",
                    "insert",
                    "alter",
                    "create",
                ]
                for keyword in dangerous_keywords:
                    if keyword in query_lower:
                        validation_result["errors"].append(f"Dangerous keyword '{keyword}' found in query")
                        validation_result["valid"] = False

            else:
                validation_result["query_type"] = "pandas_expression"

            return validation_result

        except Exception as e:
            return {"valid": False, "error": str(e)}

    def get_supported_functions(self) -> dict[str, list[str]]:
        """Get list of supported query functions and operators."""
        return {
            "aggregate_functions": ["COUNT", "SUM", "AVG", "MIN", "MAX", "STD", "VAR"],
            "operators": ["=", "!=", "<", ">", "<=", ">=", "IN", "NOT IN", "LIKE"],
            "logical_operators": ["AND", "OR", "NOT"],
            "clauses": ["SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY"],
            "special_functions": ["IS NULL", "IS NOT NULL"],
            "pandas_methods": [".str.contains()", ".isna()", ".notna()", ".isin()"],
        }

    def format_result(self, result: dict[str, Any], format_type: str = "json") -> str | dict[str, Any]:
        """
        Format query results in different formats.

        Args:
            result: Query result dictionary
            format_type: Output format (json, csv, html)

        Returns:
            Formatted result
        """
        if not result.get("success", False):
            return result

        df = result["data"]

        if format_type == "csv":
            return df.to_csv(index=False)
        elif format_type == "html":
            return df.to_html(index=False, classes="table table-striped")
        else:  # json
            return {**result, "data": df.to_dict(orient="records")}
