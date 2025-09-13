# -*- coding: utf-8 -*-
"""
Data Transformation Example for MCP Data Analysis Server

This example demonstrates comprehensive data transformation capabilities including:
- Data cleaning (handle missing values, remove duplicates)
- Feature engineering (create new features, encoding)
- Data scaling and normalization
- Column operations (drop, rename, type conversion)
- Advanced transformations (binning, aggregation)
"""

# Standard
import asyncio
import json
from pathlib import Path


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
    """Demonstrate data transformation capabilities."""
    # Third-Party
    from data_analysis_server.server import analysis_server

    client = MockMCPClient(analysis_server)

    print("🔧 MCP Data Analysis Server - Data Transformation Example")
    print("=" * 65)

    # Step 1: Load raw employee data
    print("\n📊 Step 1: Loading raw employee data...")

    employee_data_path = Path(__file__).parent.parent / "sample_data" / "employee_data.csv"

    load_result = await client.call_tool(
        "load_dataset",
        {
            "source": str(employee_data_path),
            "format": "csv",
            "sample_size": None,
            "cache_data": True,
        },
    )

    if not load_result["success"]:
        print(f"❌ Failed to load data: {load_result.get('error')}")
        return

    dataset_id = load_result["dataset_id"]
    print(f"✅ Loaded raw dataset: {load_result['message']}")
    print(f"   Dataset ID: {dataset_id}")

    # Step 2: Analyze raw data quality
    print("\n🔍 Step 2: Analyzing raw data quality...")

    raw_analysis = await client.call_tool(
        "analyze_dataset",
        {
            "dataset_id": dataset_id,
            "analysis_type": "basic",
            "include_distributions": False,
            "include_correlations": False,
            "include_outliers": True,
            "confidence_level": 0.95,
        },
    )

    if raw_analysis["success"]:
        analysis = raw_analysis["analysis"]
        basic_info = analysis["basic_info"]
        print(f"✅ Raw data analysis:")
        print(f"   • Shape: {basic_info['shape']}")
        print(f"   • Columns: {basic_info['shape'][1]}")
        print(f"   • Missing values: {sum(basic_info['missing_values'].values())}")
        print(f"   • Data types: {len(set(basic_info['dtypes'].values()))} unique")

        # Show missing values breakdown
        missing_values = basic_info["missing_values"]
        missing_cols = [k for k, v in missing_values.items() if v > 0]
        if missing_cols:
            print(f"   • Columns with missing data: {missing_cols[:3]}...")

    # Step 3: Data Cleaning Transformations
    print("\n🧹 Step 3: Performing data cleaning transformations...")

    cleaning_ops = [
        {"type": "fill_na", "columns": ["salary"], "method": "median"},
        {"type": "fill_na", "columns": ["age"], "method": "mean"},
        {"type": "fill_na", "columns": ["department"], "method": "mode"},
        {"type": "drop_duplicates"},
        {
            "type": "outlier_removal",
            "columns": ["salary"],
            "method": "iqr",
            "threshold": 1.5,
        },
    ]

    cleaning_result = await client.call_tool(
        "transform_data",
        {
            "dataset_id": dataset_id,
            "operations": cleaning_ops,
            "create_new_dataset": True,
            "new_dataset_id": f"{dataset_id}_cleaned",
        },
    )

    if cleaning_result["success"]:
        cleaned_id = cleaning_result["new_dataset_id"]
        summary = cleaning_result["transformation_summary"]
        print(f"✅ Data cleaning completed:")
        print(f"   • New dataset ID: {cleaned_id}")
        print(f"   • Operations applied: {len(summary.get('transformation_log', []))}")

        # Show transformation effects
        if "shape_changes" in summary:
            shape_changes = summary["shape_changes"]
            print(f"   • Shape change: {shape_changes.get('before')} → {shape_changes.get('after')}")
    else:
        cleaned_id = dataset_id  # Fallback to original
        print(f"❌ Cleaning failed: {cleaning_result.get('error')}")

    # Step 4: Feature Engineering
    print("\n🔬 Step 4: Performing feature engineering...")

    feature_ops = [
        {
            "type": "feature_engineering",
            "feature_type": "interaction",
            "columns": ["salary", "age"],
        },
        {
            "type": "bin_numeric",
            "column": "age",
            "bins": [20, 30, 40, 50, 65],
            "labels": ["Young", "Mid-career", "Senior", "Experienced"],
            "new_column": "age_group",
        },
        {
            "type": "encode_categorical",
            "columns": ["department"],
            "method": "onehot",
        },
    ]

    feature_result = await client.call_tool(
        "transform_data",
        {
            "dataset_id": cleaned_id,
            "operations": feature_ops,
            "create_new_dataset": True,
            "new_dataset_id": f"{cleaned_id}_featured",
        },
    )

    if feature_result["success"]:
        featured_id = feature_result["new_dataset_id"]
        summary = feature_result["transformation_summary"]
        print(f"✅ Feature engineering completed:")
        print(f"   • New dataset ID: {featured_id}")

        # Show new features created
        if "new_columns" in summary:
            new_cols = summary["new_columns"][:5]  # Show first 5
            print(f"   • New features: {new_cols}...")
    else:
        featured_id = cleaned_id  # Fallback
        print(f"❌ Feature engineering failed: {feature_result.get('error')}")

    # Step 5: Data Scaling and Normalization
    print("\n⚖️  Step 5: Applying scaling and normalization...")

    scaling_ops = [
        {
            "type": "scale",
            "columns": ["salary", "age"],
            "method": "standard",  # Z-score normalization
        },
        {
            "type": "scale",
            "columns": ["salary_x_age"],
            "method": "minmax",  # Min-max scaling
        },
    ]

    scaling_result = await client.call_tool(
        "transform_data",
        {
            "dataset_id": featured_id,
            "operations": scaling_ops,
            "create_new_dataset": True,
            "new_dataset_id": f"{featured_id}_scaled",
        },
    )

    if scaling_result["success"]:
        scaled_id = scaling_result["new_dataset_id"]
        print(f"✅ Scaling and normalization completed:")
        print(f"   • Final dataset ID: {scaled_id}")
    else:
        scaled_id = featured_id  # Fallback
        print(f"❌ Scaling failed: {scaling_result.get('error')}")

    # Step 6: Advanced Column Operations
    print("\n🔄 Step 6: Advanced column operations...")

    column_ops = [
        {
            "type": "rename_columns",
            "mapping": {"salary": "annual_salary", "age": "employee_age"},
        },
        {
            "type": "drop_columns",
            "columns": ["temporary_column"] if "temporary_column" in [] else [],
        },  # Safe drop operation
    ]

    column_result = await client.call_tool(
        "transform_data",
        {
            "dataset_id": scaled_id,
            "operations": column_ops,
            "create_new_dataset": False,  # Modify in place
        },
    )

    if column_result["success"]:
        final_id = column_result["dataset_id"]
        print(f"✅ Column operations completed:")
        print(f"   • Dataset updated in place: {final_id}")
    else:
        final_id = scaled_id
        print(f"❌ Column operations failed: {column_result.get('error')}")

    # Step 7: Analyze transformed data
    print("\n📊 Step 7: Analyzing final transformed dataset...")

    final_analysis = await client.call_tool(
        "analyze_dataset",
        {
            "dataset_id": final_id,
            "analysis_type": "comprehensive",
            "include_distributions": True,
            "include_correlations": True,
            "include_outliers": False,
            "confidence_level": 0.95,
        },
    )

    if final_analysis["success"]:
        analysis = final_analysis["analysis"]
        basic_info = analysis["basic_info"]
        print(f"✅ Final dataset analysis:")
        print(f"   • Shape: {basic_info['shape']}")
        print(f"   • Columns: {basic_info['shape'][1]}")
        print(f"   • Missing values: {sum(basic_info['missing_values'].values())}")

        # Show new feature statistics
        if "descriptive_stats" in analysis:
            desc_stats = analysis["descriptive_stats"]
            if "numeric_columns" in desc_stats and "salary_x_age" in desc_stats["numeric_columns"]:
                salary_x_age = desc_stats["numeric_columns"]["salary_x_age"]
                print(f"   • Salary*Age interaction - Mean: {salary_x_age.get('mean', 0):.2f}, " f"Std: {salary_x_age.get('std', 0):.2f}")

    # Step 8: Transformation pipeline summary
    print("\n📋 Step 8: Querying transformation results...")

    summary_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": final_id,
            "query": """
            SELECT
                department,
                annual_salary,
                salary_x_age
            FROM table
            LIMIT 10
            """,
            "return_format": "json",
        },
    )

    if summary_query["success"]:
        query_data = summary_query["query_result"]
        if "data" in query_data:
            print("✅ Sample of transformation results:")
            for i, row in enumerate(query_data["data"][:5]):
                print(f"   • Row {i+1}: {row['department']}, " f"Salary=${row['annual_salary']:.2f}, " f"Salary*Age={row['salary_x_age']:.2f}")

    # Step 9: Create visualization of transformed data
    print("\n📈 Step 9: Visualizing transformation results...")

    viz_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": final_id,
            "plot_type": "scatter",
            "x_column": "employee_age",
            "y_column": "annual_salary",
            "color_column": "age_group",
            "title": "Employee Age vs Salary (After Transformations)",
            "save_format": "png",
        },
    )

    if viz_result["success"]:
        viz_info = viz_result["visualization"]
        print(f"✅ Created transformation visualization: {viz_info.get('filename', 'N/A')}")

    # Final summary
    print("\n🎉 Data Transformation Pipeline Complete!")
    print("=" * 65)
    print("Transformation steps performed:")
    print("1. ✅ Data Quality Analysis - Identified missing values and outliers")
    print("2. ✅ Data Cleaning - Handled missing values, removed duplicates & outliers")
    print("3. ✅ Feature Engineering - Created new features and categorical binning")
    print("4. ✅ Data Scaling - Applied standard scaling and min-max normalization")
    print("5. ✅ Column Operations - Renamed columns and converted data types")
    print("6. ✅ Final Analysis - Comprehensive analysis of transformed data")
    print("7. ✅ Results Querying - Advanced SQL queries on transformed dataset")
    print("8. ✅ Visualization - Scatter plot showing transformation results")
    print(f"\nFinal dataset ID: {final_id}")


if __name__ == "__main__":
    asyncio.run(main())
