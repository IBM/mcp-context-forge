#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sales Analysis Example

This example demonstrates how to use the MCP Data Analysis Server
to analyze sales data with various statistical and visualization techniques.
"""

# Standard
import asyncio
import json
from pathlib import Path


# This would be your MCP client - for demonstration purposes
class MockMCPClient:
    """Mock MCP client for demonstration purposes."""

    def __init__(self, server_instance):
        self.server = server_instance

    async def call_tool(self, tool_name: str, arguments: dict):
        """Simulate calling an MCP tool."""
        # Third-Party
        from data_analysis_server.server import handle_call_tool

        # This simulates the MCP tool call
        result = await handle_call_tool(tool_name, arguments)
        return json.loads(result[0].text)


async def main():
    """Main sales analysis workflow."""
    # Initialize mock client (in real usage, this would be your MCP client)
    # Third-Party
    from data_analysis_server.server import analysis_server

    client = MockMCPClient(analysis_server)

    print("🔬 MCP Data Analysis Server - Sales Analysis Example")
    print("=" * 55)

    # Step 1: Load sales data
    print("\n📊 Step 1: Loading sales data...")

    sales_data_path = Path(__file__).parent.parent / "sample_data" / "sales_data.csv"

    load_result = await client.call_tool(
        "load_dataset",
        {
            "source": str(sales_data_path),
            "format": "csv",
            "dataset_id": "sales_data",
            "cache_data": True,
        },
    )

    if load_result["success"]:
        print(f"✅ Loaded dataset: {load_result['message']}")
        dataset_id = load_result["dataset_id"]
    else:
        print(f"❌ Failed to load data: {load_result.get('error')}")
        return

    # Step 2: Perform exploratory data analysis
    print("\n📈 Step 2: Performing exploratory data analysis...")

    analysis_result = await client.call_tool(
        "analyze_dataset",
        {
            "dataset_id": dataset_id,
            "analysis_type": "exploratory",
            "include_distributions": True,
            "include_correlations": True,
            "include_outliers": True,
        },
    )

    if analysis_result["success"]:
        analysis = analysis_result["analysis"]
        print(f"✅ Analysis completed for {analysis['dataset_shape']} dataset")

        # Show basic info
        basic_info = analysis["basic_info"]
        print(f"   • Dataset shape: {basic_info['shape']}")
        print(f"   • Missing values: {sum(basic_info['missing_values'].values())} total")
        print(f"   • Duplicate rows: {basic_info['duplicate_rows']}")

        # Show numeric column statistics
        numeric_stats = analysis["descriptive_stats"]["numeric_columns"]
        if numeric_stats:
            print(f"   • Numeric columns analyzed: {len(numeric_stats)}")
            for col, stats in list(numeric_stats.items())[:2]:  # Show first 2
                print(f"     - {col}: mean={stats['mean']:.2f}, std={stats['std']:.2f}")

    # Step 3: Create visualizations
    print("\n📊 Step 3: Creating visualizations...")

    # Revenue by product category
    viz1_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "bar",
            "x_column": "product_category",
            "y_column": "revenue",
            "title": "Revenue by Product Category",
            "save_format": "png",
        },
    )

    if viz1_result["success"]:
        print(f"✅ Created bar chart: {viz1_result['visualization']['filename']}")

    # Price vs Quantity scatter plot
    viz2_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "scatter",
            "x_column": "price",
            "y_column": "quantity_sold",
            "color_column": "product_category",
            "title": "Price vs Quantity Sold by Category",
            "save_format": "png",
        },
    )

    if viz2_result["success"]:
        print(f"✅ Created scatter plot: {viz2_result['visualization']['filename']}")

    # Step 4: Statistical testing
    print("\n🧮 Step 4: Statistical hypothesis testing...")

    # Test if there's a difference in revenue between regions
    test_result = await client.call_tool(
        "statistical_test",
        {
            "dataset_id": dataset_id,
            "test_type": "anova",
            "columns": ["revenue"],
            "groupby_column": "region",
            "hypothesis": "Revenue differs between regions",
            "alpha": 0.05,
        },
    )

    if test_result["success"]:
        test = test_result["test_result"]
        print("✅ ANOVA test completed:")
        print(f"   • F-statistic: {test['statistic']:.3f}")
        print(f"   • P-value: {test['p_value']:.3f}")
        print(f"   • Conclusion: {test['conclusion']}")
        print(f"   • Interpretation: {test['interpretation']}")

    # Step 5: Data transformations
    print("\n🔄 Step 5: Data transformations...")

    transform_result = await client.call_tool(
        "transform_data",
        {
            "dataset_id": dataset_id,
            "operations": [
                {
                    "type": "feature_engineering",
                    "feature_type": "interaction",
                    "columns": ["price", "quantity_sold"],
                },
                {
                    "type": "bin_numeric",
                    "column": "price",
                    "bins": 5,
                    "labels": ["Very Low", "Low", "Medium", "High", "Very High"],
                },
            ],
            "create_new_dataset": True,
            "new_dataset_id": "sales_data_enhanced",
        },
    )

    if transform_result["success"]:
        print("✅ Data transformation completed:")
        summary = transform_result["transformation_summary"]
        print(f"   • Operations applied: {summary['operations_applied']}")
        print(f"   • Final shape: {summary['final_shape']}")
        print(f"   • New dataset ID: {transform_result['new_dataset_id']}")

    # Step 6: Query the data
    print("\n🔍 Step 6: Querying data with SQL-like syntax...")

    query_result = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT product_category, AVG(revenue) as avg_revenue, COUNT(*) as count FROM table GROUP BY product_category ORDER BY avg_revenue DESC",
            "limit": 10,
            "return_format": "json",
        },
    )

    if query_result["success"]:
        print("✅ Query executed successfully:")
        query_data = query_result["query_result"]
        if "data" in query_data:
            for row in query_data["data"]:
                print(f"   • {row}")

    print("\n🎉 Sales analysis example completed!")
    print("\nThis example demonstrated:")
    print("• Data loading from CSV")
    print("• Comprehensive statistical analysis")
    print("• Data visualization creation")
    print("• Hypothesis testing (ANOVA)")
    print("• Data transformation and feature engineering")
    print("• SQL-like data querying")


if __name__ == "__main__":
    asyncio.run(main())
