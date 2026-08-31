# -*- coding: utf-8 -*-
"""
MCP Data Analysis Server

A comprehensive MCP server providing data analysis, statistical testing,
visualization, and transformation capabilities.
"""

# Standard
import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import yaml

# Third-Party
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

# Local
from .core.analyzer import DataAnalyzer

# Import our modules
from .core.data_loader import DataLoader
from .core.transformer import DataTransformer
from .models import (
    AnalysisResult,
    DataAnalysisRequest,
    DataLoadRequest,
    DataQueryRequest,
    StatTestRequest,
    TestResult,
    TimeSeriesRequest,
    TransformRequest,
    TransformResult,
    VisualizationRequest,
    VisualizationResult,
)
from .statistics.hypothesis_tests import HypothesisTests
from .statistics.time_series import TimeSeriesAnalyzer
from .storage.dataset_manager import DatasetManager
from .utils.query_parser import DataQueryParser
from .visualization.plots import DataVisualizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr)
    ],  # Log to stderr so it doesn't interfere with MCP
)
logger = logging.getLogger(__name__)

# Create server instance
server = Server("data-analysis-server")


def _orjson_default(obj: Any) -> Any:
    """Serialize NumPy/Pandas objects for orjson."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if hasattr(obj, "item"):  # pandas scalars
        return obj.item()
    if hasattr(obj, "isoformat"):  # datetime-like objects
        return obj.isoformat()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    raise TypeError


class DataAnalysisServer:
    """Main MCP Data Analysis Server class."""

    def __init__(self, config_path: str | None = None):
        """Initialize the data analysis server."""
        self.config = self._load_config(config_path)

        # Initialize components
        self.dataset_manager = DatasetManager(
            max_datasets=self.config.get("max_datasets", 100),
            max_memory_mb=self.config.get("max_memory_mb", 1024),
        )

        self.data_loader = DataLoader(
            max_download_size_mb=self.config.get("max_download_size_mb", 500),
            timeout_seconds=self.config.get("timeout_seconds", 30),
        )

        self.analyzer = DataAnalyzer()
        self.transformer = DataTransformer()
        self.hypothesis_tests = HypothesisTests()
        self.time_series_analyzer = TimeSeriesAnalyzer()

        self.visualizer = DataVisualizer(
            output_dir=self.config.get("plot_output_dir", "./plots"),
            default_style=self.config.get("plot_style", "seaborn-v0_8"),
        )

        self.query_parser = DataQueryParser(
            max_result_size=self.config.get("max_query_results", 10000)
        )

    def _load_config(self, config_path: str | None) -> dict[str, Any]:
        """Load configuration from file."""
        default_config = {
            "max_datasets": 100,
            "max_memory_mb": 1024,
            "max_download_size_mb": 500,
            "timeout_seconds": 30,
            "plot_output_dir": "./plots",
            "plot_style": "seaborn-v0_8",
            "max_query_results": 10000,
        }

        if config_path and Path(config_path).exists():
            try:
                with open(config_path) as f:
                    file_config = yaml.safe_load(f)
                default_config.update(file_config)
            except Exception as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")

        return default_config


# Initialize server instance
analysis_server = DataAnalysisServer()


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="load_dataset",
            description="Load data from various sources and formats (CSV, JSON, Parquet, SQL, Excel)",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "File path, URL, or SQL connection string",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["csv", "json", "parquet", "sql", "excel"],
                        "description": "Data format",
                    },
                    "options": {
                        "type": "object",
                        "description": "Format-specific loading options",
                        "additionalProperties": True,
                    },
                    "sample_size": {
                        "type": "integer",
                        "description": "Number of rows to sample (optional)",
                    },
                    "cache_data": {
                        "type": "boolean",
                        "description": "Whether to cache the dataset",
                        "default": True,
                    },
                    "dataset_id": {
                        "type": "string",
                        "description": "Custom dataset identifier (optional)",
                    },
                },
                "required": ["source", "format"],
            },
        ),
        Tool(
            name="analyze_dataset",
            description="Perform comprehensive dataset analysis and profiling",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "Dataset identifier",
                    },
                    "analysis_type": {
                        "type": "string",
                        "enum": ["descriptive", "exploratory", "correlation"],
                        "description": "Type of analysis to perform",
                        "default": "exploratory",
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific columns to analyze (optional)",
                    },
                    "include_distributions": {
                        "type": "boolean",
                        "description": "Include distribution analysis",
                        "default": True,
                    },
                    "include_correlations": {
                        "type": "boolean",
                        "description": "Include correlation analysis",
                        "default": True,
                    },
                    "include_outliers": {
                        "type": "boolean",
                        "description": "Include outlier detection",
                        "default": True,
                    },
                    "confidence_level": {
                        "type": "number",
                        "description": "Confidence level for statistics",
                        "default": 0.95,
                    },
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="statistical_test",
            description="Perform statistical hypothesis testing",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "Dataset identifier",
                    },
                    "test_type": {
                        "type": "string",
                        "enum": [
                            "t_test",
                            "chi_square",
                            "anova",
                            "regression",
                            "mann_whitney",
                            "wilcoxon",
                            "kruskal_wallis",
                        ],
                        "description": "Type of statistical test",
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Columns to test",
                    },
                    "groupby_column": {
                        "type": "string",
                        "description": "Column for grouping (optional)",
                    },
                    "hypothesis": {
                        "type": "string",
                        "description": "Hypothesis statement (optional)",
                    },
                    "alpha": {
                        "type": "number",
                        "description": "Significance level",
                        "default": 0.05,
                    },
                    "alternative": {
                        "type": "string",
                        "enum": ["two-sided", "less", "greater"],
                        "description": "Alternative hypothesis direction",
                        "default": "two-sided",
                    },
                },
                "required": ["dataset_id", "test_type", "columns"],
            },
        ),
        Tool(
            name="create_visualization",
            description="Generate statistical plots and charts",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "Dataset identifier",
                    },
                    "plot_type": {
                        "type": "string",
                        "enum": [
                            "histogram",
                            "scatter",
                            "box",
                            "heatmap",
                            "line",
                            "bar",
                            "violin",
                            "pair",
                            "time_series",
                            "distribution",
                        ],
                        "description": "Type of plot to create",
                    },
                    "x_column": {"type": "string", "description": "X-axis column"},
                    "y_column": {
                        "type": "string",
                        "description": "Y-axis column (optional)",
                    },
                    "color_column": {
                        "type": "string",
                        "description": "Color grouping column (optional)",
                    },
                    "facet_column": {
                        "type": "string",
                        "description": "Faceting column (optional)",
                    },
                    "title": {"type": "string", "description": "Plot title (optional)"},
                    "save_format": {
                        "type": "string",
                        "enum": ["png", "svg", "pdf", "html", "jpeg"],
                        "description": "Save format",
                        "default": "png",
                    },
                    "interactive": {
                        "type": "boolean",
                        "description": "Create interactive plot",
                        "default": False,
                    },
                },
                "required": ["dataset_id", "plot_type", "x_column"],
            },
        ),
        Tool(
            name="transform_data",
            description="Apply data transformations and cleaning operations",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "Dataset identifier",
                    },
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "drop_na",
                                        "fill_na",
                                        "drop_duplicates",
                                        "drop_columns",
                                        "rename_columns",
                                        "filter_rows",
                                        "scale",
                                        "normalize",
                                        "encode_categorical",
                                        "create_dummy",
                                        "bin_numeric",
                                        "transform_datetime",
                                        "outlier_removal",
                                        "feature_engineering",
                                    ],
                                    "description": "Type of transformation",
                                }
                            },
                            "additionalProperties": True,
                            "required": ["type"],
                        },
                        "description": "List of transformation operations",
                    },
                    "create_new_dataset": {
                        "type": "boolean",
                        "description": "Create new dataset or modify existing",
                        "default": False,
                    },
                    "new_dataset_id": {
                        "type": "string",
                        "description": "New dataset identifier (optional)",
                    },
                },
                "required": ["dataset_id", "operations"],
            },
        ),
        Tool(
            name="time_series_analysis",
            description="Analyze time series data patterns, trends, and forecasting",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "Dataset identifier",
                    },
                    "time_column": {
                        "type": "string",
                        "description": "Time/date column name",
                    },
                    "value_columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Value columns to analyze",
                    },
                    "frequency": {
                        "type": "string",
                        "enum": ["D", "W", "M", "Q", "Y"],
                        "description": "Time frequency (optional)",
                    },
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["trend", "seasonal", "forecast"],
                        },
                        "description": "Operations to perform",
                        "default": ["trend", "seasonal"],
                    },
                    "forecast_periods": {
                        "type": "integer",
                        "description": "Number of periods to forecast",
                        "default": 12,
                    },
                    "confidence_intervals": {
                        "type": "boolean",
                        "description": "Include confidence intervals",
                        "default": True,
                    },
                },
                "required": ["dataset_id", "time_column", "value_columns"],
            },
        ),
        Tool(
            name="query_data",
            description="Execute SQL-like queries on loaded datasets",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "Dataset identifier",
                    },
                    "query": {"type": "string", "description": "SQL-like query string"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of rows to return",
                        "default": 1000,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Number of rows to skip",
                        "default": 0,
                    },
                    "return_format": {
                        "type": "string",
                        "enum": ["json", "csv", "html"],
                        "description": "Return format",
                        "default": "json",
                    },
                },
                "required": ["dataset_id", "query"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Handle tool calls."""
    try:
        if name == "load_dataset":
            request = DataLoadRequest(**arguments)

            # Load the data
            df = analysis_server.data_loader.load_data(
                source=request.source,
                format=request.format,
                options=request.options,
                sample_size=request.sample_size,
            )

            # Store in dataset manager
            dataset_id = analysis_server.dataset_manager.store_dataset(
                dataset=df, dataset_id=request.dataset_id, source=request.source
            )

            # Get dataset info
            dataset_info = analysis_server.dataset_manager.get_dataset_info(dataset_id)

            result = {
                "success": True,
                "dataset_id": dataset_id,
                "dataset_info": dataset_info.model_dump(),
                "message": f"Successfully loaded dataset with {df.shape[0]} rows and {df.shape[1]} columns",
            }

        elif name == "analyze_dataset":
            analysis_request = DataAnalysisRequest(**arguments)

            # Get dataset
            df = analysis_server.dataset_manager.get_dataset(
                analysis_request.dataset_id
            )

            # Perform analysis
            analysis_result = analysis_server.analyzer.analyze_dataset(
                df=df,
                analysis_type=analysis_request.analysis_type,
                columns=analysis_request.columns,
                include_distributions=analysis_request.include_distributions,
                include_correlations=analysis_request.include_correlations,
                include_outliers=analysis_request.include_outliers,
                confidence_level=analysis_request.confidence_level,
            )

            # For backward compatibility, return the original structure
            # but validate it using the Pydantic model first
            comprehensive_summary = {
                "dataset_shape": analysis_result.get("dataset_shape"),
                "confidence_level": analysis_result.get("confidence_level"),
                "basic_info": analysis_result.get("basic_info"),
                "descriptive_stats": analysis_result.get("descriptive_stats"),
            }

            # Validate with Pydantic model (for type safety)
            analysis_response = AnalysisResult(
                dataset_id=analysis_request.dataset_id,
                analysis_type=analysis_request.analysis_type,
                summary=comprehensive_summary,
                distributions=analysis_result.get("distributions"),
                correlations=analysis_result.get("correlations"),
                outliers=analysis_result.get("outliers"),
            )

            # Return in the original format for backward compatibility
            result = {
                "success": True,
                "dataset_id": analysis_request.dataset_id,
                "analysis": analysis_result,  # Original format
            }

        elif name == "statistical_test":
            stat_request = StatTestRequest(**arguments)

            # Get dataset
            df = analysis_server.dataset_manager.get_dataset(stat_request.dataset_id)

            # Perform statistical test
            test_result_raw = analysis_server.hypothesis_tests.perform_test(
                df=df,
                test_type=stat_request.test_type,
                columns=stat_request.columns,
                groupby_column=stat_request.groupby_column,
                hypothesis=stat_request.hypothesis,
                alpha=stat_request.alpha,
                alternative=stat_request.alternative,
            )

            # Validate with Pydantic model (for type safety)
            # Handle degrees_of_freedom which might be a dict or int
            dof = test_result_raw.get("degrees_of_freedom")
            if isinstance(dof, dict):
                # For ANOVA, use total degrees of freedom
                dof_int = dof.get("between", 0) + dof.get("within", 0)
            else:
                dof_int = dof

            test_response = TestResult(
                test_type=stat_request.test_type,
                statistic=test_result_raw.get("statistic", 0.0),
                p_value=test_result_raw.get("p_value", 1.0),
                degrees_of_freedom=dof_int,
                effect_size=test_result_raw.get("effect_size"),
                conclusion=test_result_raw.get("conclusion", ""),
                interpretation=test_result_raw.get("interpretation", ""),
            )

            # Return in the original format for backward compatibility
            result = {
                "success": True,
                "dataset_id": stat_request.dataset_id,
                "test_result": test_result_raw,  # Original format
            }

        elif name == "create_visualization":
            viz_request = VisualizationRequest(**arguments)

            # Get dataset
            df = analysis_server.dataset_manager.get_dataset(viz_request.dataset_id)

            # Create visualization
            viz_result_raw = analysis_server.visualizer.create_visualization(
                df=df,
                plot_type=viz_request.plot_type,
                x_column=viz_request.x_column,
                y_column=viz_request.y_column,
                color_column=viz_request.color_column,
                facet_column=viz_request.facet_column,
                title=viz_request.title,
                save_format=viz_request.save_format,
                interactive=getattr(viz_request, "interactive", False),
            )

            # Validate with Pydantic model (for type safety)
            viz_response = VisualizationResult(
                plot_type=viz_request.plot_type,
                file_path=viz_result_raw.get("file_path", ""),
                format=viz_request.save_format,
                title=viz_request.title,
                metadata=viz_result_raw.get("metadata", {}),
            )

            # Return in the original format for backward compatibility
            result = {
                "success": viz_result_raw.get("success", True),
                "dataset_id": viz_request.dataset_id,
                "visualization": viz_result_raw,  # Original format
            }

        elif name == "transform_data":
            transform_request = TransformRequest(**arguments)

            # Get dataset
            df = analysis_server.dataset_manager.get_dataset(
                transform_request.dataset_id
            )

            # Apply transformations
            transformed_df, summary = analysis_server.transformer.transform_data(
                df=df,
                operations=transform_request.operations,
                inplace=not transform_request.create_new_dataset,
            )

            if transform_request.create_new_dataset:
                # Store as new dataset
                new_id = (
                    transform_request.new_dataset_id
                    or f"{transform_request.dataset_id}_transformed"
                )
                new_dataset_id = analysis_server.dataset_manager.store_dataset(
                    dataset=transformed_df, dataset_id=new_id
                )

                # Get original dataset shape for comparison
                original_df = analysis_server.dataset_manager.get_dataset(
                    transform_request.dataset_id
                )

                # Use the proper response model for type safety
                # Extract operation names from transformation log
                operations_list = [
                    op.get("operation", "unknown")
                    for op in summary.get("transformation_log", [])
                ]

                transform_response = TransformResult(
                    dataset_id=new_dataset_id,
                    operations_applied=operations_list,
                    shape_before=original_df.shape,
                    shape_after=transformed_df.shape,
                    summary=summary.get("summary", "Data transformation completed"),
                )

                result = {
                    "success": True,
                    "original_dataset_id": transform_request.dataset_id,
                    "new_dataset_id": new_dataset_id,
                    "transformation_summary": summary,  # Original format
                }
            else:
                # Update existing dataset
                original_shape = analysis_server.dataset_manager.get_dataset(
                    transform_request.dataset_id
                ).shape
                analysis_server.dataset_manager.store_dataset(
                    dataset=transformed_df, dataset_id=transform_request.dataset_id
                )

                # Use the proper response model for type safety
                # Extract operation names from transformation log
                operations_list = [
                    op.get("operation", "unknown")
                    for op in summary.get("transformation_log", [])
                ]

                transform_response = TransformResult(
                    dataset_id=transform_request.dataset_id,
                    operations_applied=operations_list,
                    shape_before=original_shape,
                    shape_after=transformed_df.shape,
                    summary=summary.get("summary", "Data transformation completed"),
                )

                result = {
                    "success": True,
                    "dataset_id": transform_request.dataset_id,
                    "transformation_summary": summary,  # Original format
                }

        elif name == "time_series_analysis":
            ts_request = TimeSeriesRequest(**arguments)

            # Get dataset
            df = analysis_server.dataset_manager.get_dataset(ts_request.dataset_id)

            # Perform time series analysis
            ts_result = analysis_server.time_series_analyzer.analyze_time_series(
                df=df,
                time_column=ts_request.time_column,
                value_columns=ts_request.value_columns,
                frequency=ts_request.frequency,
                operations=ts_request.operations,
                forecast_periods=ts_request.forecast_periods,
                confidence_intervals=ts_request.confidence_intervals,
            )

            result = {
                "success": True,
                "dataset_id": ts_request.dataset_id,
                "time_series_analysis": ts_result,
            }

        elif name == "query_data":
            query_request = DataQueryRequest(**arguments)

            # Get dataset
            df = analysis_server.dataset_manager.get_dataset(query_request.dataset_id)

            # Execute query
            query_result = analysis_server.query_parser.execute_query(
                df=df,
                query=query_request.query,
                limit=query_request.limit,
                offset=query_request.offset,
            )

            # Format result
            formatted_result = analysis_server.query_parser.format_result(
                query_result, query_request.return_format
            )

            result = {
                "success": query_result.get("success", True),
                "dataset_id": query_request.dataset_id,
                "query_result": formatted_result,
            }

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

    except KeyError as e:
        result = {"success": False, "error": f"Dataset not found: {str(e)}"}
    except Exception as e:
        logger.error(f"Error in {name}: {str(e)}")
        result = {"success": False, "error": str(e)}

    return [
        TextContent(
            type="text",
            text=orjson.dumps(
                result,
                default=_orjson_default,
                option=orjson.OPT_INDENT_2 | orjson.OPT_SERIALIZE_NUMPY,
            ).decode(),
        )
    ]


async def main():
    """Main server entry point."""
    logger.info("Starting MCP Data Analysis Server...")

    # Initialize the server
    # Third-Party
    from mcp.server.stdio import stdio_server

    logger.info("Waiting for MCP client connection...")
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP client connected, starting server...")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="data-analysis-server",
                server_version="0.1.0",
                capabilities={
                    "tools": {},
                    "logging": {},
                },
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
