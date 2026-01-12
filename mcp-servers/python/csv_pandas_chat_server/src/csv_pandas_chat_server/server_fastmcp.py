#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/csv_pandas_chat_server/src/csv_pandas_chat_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

CSV Pandas Chat MCP Server - FastMCP Implementation

A secure MCP server for analyzing CSV data using natural language queries.
Integrates with OpenAI models to generate and execute safe pandas code.

Security Features:
- Input sanitization and validation
- Code execution sandboxing with timeouts
- Restricted imports and function allowlists
- File size and dataframe size limits
- Safe code generation and execution
"""

import asyncio
import logging
import os
import re
import sys
import textwrap
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import orjson
import pandas as pd
import requests
from fastmcp import FastMCP
from pydantic import Field

# Configure logging to stderr to avoid MCP protocol interference
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Configuration constants
MAX_INPUT_LENGTH = int(os.getenv("CSV_CHAT_MAX_INPUT_LENGTH", "1000"))
MAX_FILE_SIZE = int(os.getenv("CSV_CHAT_MAX_FILE_SIZE", "20971520"))  # 20MB
MAX_DATAFRAME_ROWS = int(os.getenv("CSV_CHAT_MAX_DATAFRAME_ROWS", "100000"))
MAX_DATAFRAME_COLS = int(os.getenv("CSV_CHAT_MAX_DATAFRAME_COLS", "100"))
EXECUTION_TIMEOUT = int(os.getenv("CSV_CHAT_EXECUTION_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("CSV_CHAT_MAX_RETRIES", "3"))

# Create FastMCP server instance
mcp = FastMCP("csv-pandas-chat-server")


class CSVProcessor:
    """Handles CSV data processing operations."""

    async def load_dataframe(
        self,
        csv_content: str | None = None,
        file_url: str | None = None,
        file_path: str | None = None,
    ) -> pd.DataFrame:
        """Load a dataframe from various input sources."""
        logger.debug("Loading dataframe from input source")

        # Exactly one source must be provided
        sources = [csv_content, file_url, file_path]
        provided_sources = [s for s in sources if s is not None]

        if len(provided_sources) != 1:
            raise ValueError("Exactly one of csv_content, file_url, or file_path must be provided")

        if csv_content:
            logger.debug("Loading dataframe from CSV content")
            df = pd.read_csv(StringIO(csv_content))
        elif file_url:
            logger.debug(f"Loading dataframe from URL: {file_url}")
            response = requests.get(str(file_url), stream=True, timeout=30)
            response.raise_for_status()

            content = b""
            for chunk in response.iter_content(chunk_size=8192):
                content += chunk
                if len(content) > MAX_FILE_SIZE:
                    raise ValueError(
                        f"File size exceeds maximum allowed size of {MAX_FILE_SIZE} bytes"
                    )

            if str(file_url).endswith(".csv"):
                df = pd.read_csv(BytesIO(content))
            elif str(file_url).endswith(".xlsx"):
                df = pd.read_excel(BytesIO(content))
            else:
                # Try to detect format
                try:
                    df = pd.read_csv(BytesIO(content))
                except:
                    try:
                        df = pd.read_excel(BytesIO(content))
                    except:
                        raise ValueError(
                            "Unsupported file format. Only CSV and XLSX are supported."
                        )
        elif file_path:
            logger.debug(f"Loading dataframe from file path: {file_path}")
            file_path_obj = Path(file_path)

            if not file_path_obj.exists():
                raise ValueError(f"File not found: {file_path}")

            if file_path_obj.stat().st_size > MAX_FILE_SIZE:
                raise ValueError(f"File size exceeds maximum allowed size of {MAX_FILE_SIZE} bytes")

            if file_path.endswith(".csv"):
                df = pd.read_csv(file_path)
            elif file_path.endswith(".xlsx"):
                df = pd.read_excel(file_path)
            else:
                raise ValueError("Unsupported file format. Only CSV and XLSX are supported.")

        # Validate dataframe size
        self._validate_dataframe(df)
        return df

    def _validate_dataframe(self, df: pd.DataFrame) -> None:
        """Validate dataframe against security constraints."""
        if df.shape[0] > MAX_DATAFRAME_ROWS:
            raise ValueError(
                f"Dataframe has {df.shape[0]} rows, exceeding maximum of {MAX_DATAFRAME_ROWS}"
            )

        if df.shape[1] > MAX_DATAFRAME_COLS:
            raise ValueError(
                f"Dataframe has {df.shape[1]} columns, exceeding maximum of {MAX_DATAFRAME_COLS}"
            )

        # Check memory usage
        memory_usage = df.memory_usage(deep=True).sum()
        if memory_usage > MAX_FILE_SIZE * 2:  # Allow 2x file size for memory usage
            raise ValueError(f"Dataframe memory usage ({memory_usage} bytes) is too large")

    def sanitize_user_input(self, input_str: str) -> str:
        """Sanitize user input to prevent potential security issues."""
        logger.debug(f"Sanitizing input: {input_str[:100]}...")

        # Basic blocklist - can be extended based on security requirements
        blocklist = [
            "import os",
            "import sys",
            "import subprocess",
            "__import__",
            "eval(",
            "exec(",
            "open(",
            "file(",
            "input(",
            "raw_input(",
        ]

        input_lower = input_str.lower()
        for blocked in blocklist:
            if blocked in input_lower:
                logger.warning(f"Blocked phrase '{blocked}' found in input")
                raise ValueError(f"Input contains potentially unsafe content: {blocked}")

        # Remove potentially harmful characters while preserving useful ones
        sanitized = re.sub(r'[^\w\s.,?!;:()\[\]{}+=\-*/<>%"\']', "", input_str)
        return sanitized.strip()[:MAX_INPUT_LENGTH]

    def sanitize_code(self, code: str) -> str:
        """Sanitize generated Python code to ensure safe execution."""
        logger.debug(f"Sanitizing code: {code[:200]}...")

        # Remove code block markers
        code = re.sub(r"```python\s*", "", code)
        code = re.sub(r"```\s*", "", code)
        code = code.strip()

        # Blocklist of dangerous operations
        blocklist = [
            r"\bimport\s+os\b",
            r"\bimport\s+sys\b",
            r"\bimport\s+subprocess\b",
            r"\bfrom\s+os\b",
            r"\bfrom\s+sys\b",
            r"\b__import__\b",
            r"\beval\s*\(",
            r"\bexec\s*\(",
            r"\bopen\s*\(",
            r"\bfile\s*\(",
            r"\binput\s*\(",
            r"\braw_input\s*\(",
            r"\bcompile\s*\(",
            r"\bglobals\s*\(",
            r"\blocals\s*\(",
            r"\bsetattr\s*\(",
            r"\bgetattr\s*\(",
            r"\bdelattr\s*\(",
            r"\b__.*__\b",  # Dunder methods
            r"\bwhile\s+True\b",  # Infinite loops
        ]

        for pattern in blocklist:
            if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
                raise ValueError(f"Unsafe code pattern detected: {pattern}")

        return code

    def fix_syntax_errors(self, code: str) -> str:
        """Attempt to fix common syntax errors in generated code."""
        lines = code.strip().split("\n")

        # Ensure the last line assigns to result variable
        if lines and not any("result =" in line for line in lines):
            # If the last line is an expression, assign it to result
            last_line = lines[-1].strip()
            if last_line and not last_line.startswith(("print", "result")):
                lines[-1] = f"result = {last_line}"
            else:
                lines.append("result = df.head()")  # Default fallback

        return "\n".join(lines)

    async def execute_code_with_timeout(self, code: str, df: pd.DataFrame) -> Any:
        """Execute code with timeout and restricted environment."""
        logger.debug("Executing code with timeout")

        async def run_code():
            # Create safe execution environment
            safe_globals = {
                "__builtins__": {
                    "len": len,
                    "str": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "list": list,
                    "dict": dict,
                    "set": set,
                    "tuple": tuple,
                    "sum": sum,
                    "min": min,
                    "max": max,
                    "abs": abs,
                    "round": round,
                    "sorted": sorted,
                    "any": any,
                    "all": all,
                    "zip": zip,
                    "map": map,
                    "filter": filter,
                    "range": range,
                    "enumerate": enumerate,
                    "print": print,
                },
                "pd": pd,
                "np": np,
                "df": df.copy(),  # Work with a copy to prevent modification
            }

            # Prepare code with proper indentation
            indented_code = textwrap.indent(code.strip(), "    ")
            full_func = f"""
def execute_user_code():
    df = df.fillna('')
    result = None
{indented_code}
    return result
"""

            logger.debug(f"Executing function: {full_func}")

            # Execute the code
            local_vars = {}
            exec(full_func, safe_globals, local_vars)
            return local_vars["execute_user_code"]()

        try:
            result = await asyncio.wait_for(run_code(), timeout=EXECUTION_TIMEOUT)
            logger.debug("Code execution completed successfully")
            return result
        except TimeoutError:
            raise TimeoutError(f"Code execution timed out after {EXECUTION_TIMEOUT} seconds")
        except Exception as e:
            logger.error(f"Error executing code: {str(e)}")
            raise ValueError(f"Error executing generated code: {str(e)}")

    def extract_column_info(self, df: pd.DataFrame, max_unique_values: int = 10) -> str:
        """Extract column information including unique values."""
        column_info = []

        for column in df.columns:
            dtype = str(df[column].dtype)
            unique_values = df[column].dropna().unique()

            if len(unique_values) > max_unique_values:
                sample_values = unique_values[:max_unique_values]
                values_str = f"{', '.join(map(str, sample_values))} (and {len(unique_values) - max_unique_values} more)"
            else:
                values_str = ", ".join(map(str, unique_values))

            column_info.append(f"{column} ({dtype}): {values_str}")

        return "\n".join(column_info)

    async def _generate_code_with_openai(
        self, df_head: str, column_info: str, query: str, api_key: str | None, model: str
    ) -> dict[str, Any]:
        """Generate code using OpenAI API."""
        if not api_key:
            # Fallback to environment variable
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError(
                    "OpenAI API key is required. Provide it in the request or set OPENAI_API_KEY environment variable."
                )

        prompt = self._create_prompt(df_head, column_info, query)

        # Use OpenAI API
        try:
            import openai

            client = openai.AsyncOpenAI(api_key=api_key)

            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that generates safe Python pandas code to analyze CSV data. Always respond with valid JSON containing 'code' and 'explanation' fields.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=1000,
            )

            content = response.choices[0].message.content
            logger.debug(f"OpenAI response: {content}")

            # Clean up and parse response
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]

            return orjson.loads(content)

        except ImportError:
            raise ValueError("OpenAI package not installed. Install with: pip install openai")
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {str(e)}")
            raise ValueError(f"Error generating code: {str(e)}")

    def _create_prompt(self, df_head: str, column_info: str, query: str) -> str:
        """Create prompt for code generation."""
        return f"""
You are an AI assistant that generates safe Python pandas code to analyze CSV data.

SAFETY GUIDELINES:
1. Use only pandas (pd) and numpy (np) operations
2. Do not use import statements - pandas and numpy are already available as pd and np
3. Do not use eval(), exec(), or similar functions
4. Do not access file system, network, or system resources
5. Assign final output to variable named 'result'
6. Do not use return statements
7. Keep code safe and focused on data analysis only

CSV Data Preview:
{df_head}

Column Information:
{column_info}

User Query: {query}

Respond with valid JSON in this exact format:
{{
    "code": "your pandas code here",
    "explanation": "brief explanation of what the code does"
}}

Ensure the code is safe, efficient, and directly addresses the query.
The dataframe is available as 'df' - do not recreate it.
"""


# Initialize the processor
processor = CSVProcessor()


@mcp.tool(description="Chat with CSV data using natural language queries")
async def chat_with_csv(
    query: str = Field(
        ..., description="Natural language query about the data", max_length=MAX_INPUT_LENGTH
    ),
    csv_content: str | None = Field(None, description="CSV content as string"),
    file_url: str | None = Field(None, description="URL to CSV or XLSX file"),
    file_path: str | None = Field(None, description="Path to local CSV file"),
    openai_api_key: str | None = Field(None, description="OpenAI API key"),
    model: str = Field("gpt-3.5-turbo", description="OpenAI model to use"),
) -> dict[str, Any]:
    """Process a chat query against CSV data using AI-generated pandas code."""
    invocation_id = str(uuid4())
    logger.info(f"Processing chat request {invocation_id}")

    try:
        # Sanitize input
        sanitized_query = processor.sanitize_user_input(query)
        logger.debug(f"Sanitized query: {sanitized_query}")

        # Load and validate dataframe
        df = await processor.load_dataframe(csv_content, file_url, file_path)
        logger.info(f"Loaded dataframe with shape: {df.shape}")

        # Prepare data for LLM
        df_head = df.head(5).to_markdown()
        column_info = processor.extract_column_info(df)

        # Generate code using OpenAI
        llm_response = await processor._generate_code_with_openai(
            df_head, column_info, sanitized_query, openai_api_key, model
        )

        # Execute the generated code
        if "code" in llm_response and llm_response["code"]:
            code = processor.sanitize_code(llm_response["code"])
            code = processor.fix_syntax_errors(code)

            result = await processor.execute_code_with_timeout(code, df)

            # Format result for display
            if isinstance(result, (pd.DataFrame, pd.Series)):
                if len(result) > 100:  # Limit output size
                    display_result = f"{result.head(50).to_string()}\n... (showing first 50 of {len(result)} rows)"
                else:
                    display_result = result.to_string()
            elif isinstance(result, (list, np.ndarray)):
                display_result = ", ".join(map(str, result[:100]))
                if len(result) > 100:
                    display_result += f" ... (showing first 100 of {len(result)} items)"
            else:
                display_result = str(result)

            return {
                "success": True,
                "invocation_id": invocation_id,
                "query": sanitized_query,
                "explanation": llm_response.get("explanation", "No explanation provided"),
                "generated_code": code,
                "result": display_result,
                "dataframe_shape": df.shape,
            }
        else:
            return {
                "success": False,
                "invocation_id": invocation_id,
                "error": "No executable code was generated by the AI model",
            }

    except Exception as e:
        logger.error(f"Error in chat_with_csv: {str(e)}")
        return {"success": False, "invocation_id": invocation_id, "error": str(e)}


@mcp.tool(description="Get comprehensive information about CSV data structure")
async def get_csv_info(
    csv_content: str | None = Field(None, description="CSV content as string"),
    file_url: str | None = Field(None, description="URL to CSV or XLSX file"),
    file_path: str | None = Field(None, description="Path to local CSV file"),
) -> dict[str, Any]:
    """Get comprehensive information about CSV data."""
    try:
        df = await processor.load_dataframe(csv_content, file_url, file_path)

        # Basic info
        info = {
            "success": True,
            "shape": df.shape,
            "columns": df.columns.tolist(),
            "dtypes": df.dtypes.astype(str).to_dict(),
            "memory_usage": df.memory_usage(deep=True).sum(),
            "missing_values": df.isnull().sum().to_dict(),
            "sample_data": df.head(5).to_dict(orient="records"),
        }

        # Add basic statistics for numeric columns
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            info["numeric_summary"] = df[numeric_cols].describe().to_dict()

        # Add unique value counts for categorical columns
        categorical_cols = df.select_dtypes(include=["object"]).columns
        unique_counts = {}
        for col in categorical_cols:
            unique_counts[col] = df[col].nunique()
        info["unique_value_counts"] = unique_counts

        return info

    except Exception as e:
        logger.error(f"Error getting CSV info: {str(e)}")
        return {"success": False, "error": str(e)}


@mcp.tool(description="Perform automated analysis of CSV data")
async def analyze_csv(
    csv_content: str | None = Field(None, description="CSV content as string"),
    file_url: str | None = Field(None, description="URL to CSV or XLSX file"),
    file_path: str | None = Field(None, description="Path to local CSV file"),
    analysis_type: str = Field(
        "basic",
        pattern="^(basic|detailed|statistical)$",
        description="Type of analysis (basic, detailed, statistical)",
    ),
) -> dict[str, Any]:
    """Perform automated analysis of CSV data."""
    try:
        df = await processor.load_dataframe(csv_content, file_url, file_path)

        analysis = {
            "success": True,
            "analysis_type": analysis_type,
            "shape": df.shape,
            "columns": df.columns.tolist(),
        }

        if analysis_type in ["basic", "detailed", "statistical"]:
            # Data quality analysis
            analysis["data_quality"] = {
                "missing_values": df.isnull().sum().to_dict(),
                "duplicate_rows": df.duplicated().sum(),
                "memory_usage_mb": df.memory_usage(deep=True).sum() / 1024 / 1024,
            }

            # Column type analysis
            analysis["column_types"] = {
                "numeric": df.select_dtypes(include=[np.number]).columns.tolist(),
                "categorical": df.select_dtypes(include=["object"]).columns.tolist(),
                "datetime": df.select_dtypes(include=["datetime"]).columns.tolist(),
            }

        if analysis_type in ["detailed", "statistical"]:
            # Statistical summary
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                analysis["statistical_summary"] = df[numeric_cols].describe().to_dict()

            # Correlation matrix for numeric columns
            if len(numeric_cols) > 1:
                correlation_matrix = df[numeric_cols].corr()
                analysis["correlations"] = correlation_matrix.to_dict()

        if analysis_type == "statistical":
            # Advanced statistical analysis
            analysis["advanced_stats"] = {}

            for col in df.select_dtypes(include=[np.number]).columns:
                col_stats = {
                    "skewness": float(df[col].skew()),
                    "kurtosis": float(df[col].kurtosis()),
                    "variance": float(df[col].var()),
                    "std_dev": float(df[col].std()),
                }
                analysis["advanced_stats"][col] = col_stats

        return analysis

    except Exception as e:
        logger.error(f"Error analyzing CSV: {str(e)}")
        return {"success": False, "error": str(e)}


def main():
    """Main entry point for the FastMCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="CSV Pandas Chat FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9003, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting CSV Pandas Chat FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting CSV Pandas Chat FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
