# -*- coding: utf-8 -*-
"""
Comprehensive Workflow Example for MCP Data Analysis Server

This example demonstrates an end-to-end data analysis workflow combining ALL capabilities:
1. Data loading and validation
2. Exploratory data analysis
3. Data cleaning and transformation
4. Statistical testing and hypothesis validation
5. Time series analysis (if applicable)
6. Advanced querying and insights
7. Comprehensive visualizations
8. Results reporting and export

This showcases how all MCP tools work together in a real-world scenario.
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
    """Demonstrate comprehensive end-to-end workflow."""
    # Third-Party
    from data_analysis_server.server import analysis_server

    client = MockMCPClient(analysis_server)

    print("🚀 MCP Data Analysis Server - Comprehensive Workflow")
    print("=" * 65)
    print("End-to-End Data Science Pipeline Demonstration")
    print("=" * 65)

    # Phase 1: DATA LOADING AND INITIAL EXPLORATION
    print("\n📊 PHASE 1: DATA LOADING AND EXPLORATION")
    print("-" * 45)

    # Load primary dataset
    print("\n🔍 Step 1.1: Loading primary business dataset...")

    sales_data_path = Path(__file__).parent.parent / "sample_data" / "sales_data.csv"

    load_result = await client.call_tool(
        "load_dataset",
        {
            "source": str(sales_data_path),
            "format": "csv",
            "sample_size": None,
            "cache_data": True,
        },
    )

    if not load_result["success"]:
        print(f"❌ Failed to load primary dataset: {load_result.get('error')}")
        return

    primary_dataset_id = load_result["dataset_id"]
    print(f"✅ Loaded primary dataset: {load_result['message']}")
    print(f"   Dataset ID: {primary_dataset_id}")

    # Initial exploration
    print("\n🔬 Step 1.2: Initial data exploration...")

    initial_analysis = await client.call_tool(
        "analyze_dataset",
        {
            "dataset_id": primary_dataset_id,
            "analysis_type": "comprehensive",
            "include_distributions": True,
            "include_correlations": True,
            "include_outliers": True,
            "confidence_level": 0.95,
        },
    )

    if initial_analysis["success"]:
        analysis = initial_analysis["analysis"]
        basic_info = analysis["basic_info"]
        print(f"✅ Initial analysis complete:")
        print(f"   • Dataset shape: {basic_info['shape']}")
        print(f"   • Missing values: {sum(basic_info['missing_values'].values())}")
        print(f"   • Data quality: {analysis.get('data_quality_score', 'N/A')}/100")

        # Report data quality issues
        missing_columns = [k for k, v in basic_info["missing_values"].items() if v > 0]
        if missing_columns:
            print(f"   • Columns with missing data: {missing_columns[:3]}...")

    # Phase 2: DATA CLEANING AND TRANSFORMATION
    print("\n🧹 PHASE 2: DATA CLEANING AND PREPROCESSING")
    print("-" * 48)

    print("\n🔧 Step 2.1: Data cleaning operations...")

    # Define comprehensive cleaning operations
    cleaning_operations = [
        {"operation": "fill_na", "columns": ["revenue"], "method": "median"},
        {"operation": "fill_na", "columns": ["price"], "method": "median"},
        {"operation": "drop_duplicates"},
        {"operation": "outlier_removal", "columns": ["revenue"], "method": "iqr", "threshold": 2.0},
        {"operation": "drop_na", "columns": ["product_name"]},  # Convert types not directly supported
    ]

    cleaning_result = await client.call_tool(
        "transform_data",
        {
            "dataset_id": primary_dataset_id,
            "operations": cleaning_operations,
            "create_new_dataset": True,
            "new_dataset_id": f"{primary_dataset_id}_cleaned",
        },
    )

    if cleaning_result["success"]:
        cleaned_dataset_id = cleaning_result["new_dataset_id"]
        cleaning_summary = cleaning_result["transformation_summary"]
        print(f"✅ Data cleaning completed:")
        print(f"   • Cleaned dataset ID: {cleaned_dataset_id}")
        print(f"   • Operations applied: {len(cleaning_summary.get('transformation_log', []))}")

        if "shape_changes" in cleaning_summary:
            shapes = cleaning_summary["shape_changes"]
            print(f"   • Shape: {shapes.get('before')} → {shapes.get('after')}")
    else:
        cleaned_dataset_id = primary_dataset_id
        print(f"⚠️  Using original dataset due to cleaning issues")

    print("\n🔬 Step 2.2: Feature engineering...")

    # Advanced feature engineering
    feature_operations = [
        {"operation": "feature_engineering", "feature_type": "ratio", "columns": ["revenue", "quantity_sold"], "new_column": "revenue_per_unit"},
        {"operation": "bin_numeric", "column": "revenue", "bins": [0, 1000, 5000, 10000, float("inf")], "labels": ["Low", "Medium", "High", "Premium"], "new_column": "revenue_tier"},
        {"operation": "encode_categorical", "columns": ["product_category"], "method": "onehot"},
        {"operation": "scale", "columns": ["revenue", "quantity_sold"], "method": "standard"},
        {"operation": "create_dummy", "columns": ["customer_segment"]},
    ]

    feature_result = await client.call_tool(
        "transform_data",
        {
            "dataset_id": cleaned_dataset_id,
            "operations": feature_operations,
            "create_new_dataset": True,
            "new_dataset_id": f"{cleaned_dataset_id}_featured",
        },
    )

    if feature_result["success"]:
        featured_dataset_id = feature_result["new_dataset_id"]
        feature_summary = feature_result["transformation_summary"]
        print(f"✅ Feature engineering completed:")
        print(f"   • Enhanced dataset ID: {featured_dataset_id}")

        if "new_columns" in feature_summary:
            new_features = feature_summary["new_columns"][:5]
            print(f"   • New features created: {new_features}...")
    else:
        featured_dataset_id = cleaned_dataset_id
        print(f"⚠️  Feature engineering had issues, using cleaned dataset")

    # Phase 3: STATISTICAL ANALYSIS AND HYPOTHESIS TESTING
    print("\n📊 PHASE 3: STATISTICAL ANALYSIS")
    print("-" * 35)

    print("\n🧮 Step 3.1: Comprehensive statistical analysis...")

    stat_analysis = await client.call_tool(
        "analyze_dataset",
        {
            "dataset_id": featured_dataset_id,
            "analysis_type": "comprehensive",
            "include_distributions": True,
            "include_correlations": True,
            "include_outliers": True,
            "confidence_level": 0.95,
        },
    )

    if stat_analysis["success"]:
        analysis = stat_analysis["analysis"]
        print(f"✅ Statistical analysis completed:")

        # Report key statistical insights
        if "correlations" in analysis and "strong_correlations" in analysis["correlations"]:
            strong_corrs = analysis["correlations"]["strong_correlations"][:3]
            print(f"   • Strong correlations found: {len(strong_corrs)}")
            for corr in strong_corrs:
                print(f"     - {corr.get('feature_1')} ↔ {corr.get('feature_2')}: {corr.get('correlation', 0):.3f}")

    print("\n🎯 Step 3.2: Hypothesis testing - Revenue by Product Category...")

    # Test if there are significant differences in revenue across product categories
    hypothesis_test = await client.call_tool(
        "statistical_test",
        {
            "dataset_id": featured_dataset_id,
            "test_type": "anova",
            "columns": ["revenue"],
            "groupby_column": "product_category",
            "hypothesis": "different_means",
            "alpha": 0.05,
        },
    )

    if hypothesis_test["success"]:
        test_result = hypothesis_test["test_result"]
        print(f"✅ ANOVA test completed:")
        print(f"   • F-statistic: {test_result.get('statistic', 0):.4f}")
        print(f"   • P-value: {test_result.get('p_value', 1):.4f}")
        print(f"   • Conclusion: {test_result.get('conclusion', 'N/A')}")

    print("\n📈 Step 3.3: Customer segmentation analysis...")

    # Chi-square test for independence
    chi_test = await client.call_tool(
        "statistical_test",
        {
            "dataset_id": featured_dataset_id,
            "test_type": "chi_square",
            "columns": ["revenue_tier", "product_category"],
            "hypothesis": "independence",
            "alpha": 0.05,
        },
    )

    if chi_test["success"]:
        test_result = chi_test["test_result"]
        print(f"✅ Chi-square test (Revenue Tier vs Category):")
        print(f"   • Chi-square: {test_result.get('statistic', 0):.4f}")
        print(f"   • P-value: {test_result.get('p_value', 1):.4f}")
        print(f"   • Association strength: {test_result.get('effect_size', 'N/A')}")

    # Phase 4: TIME SERIES ANALYSIS (if applicable)
    print("\n⏰ PHASE 4: TIME SERIES ANALYSIS")
    print("-" * 33)

    print("\n📅 Step 4.1: Time series analysis of sales trends...")

    # Attempt time series analysis
    ts_analysis = await client.call_tool(
        "time_series_analysis",
        {
            "dataset_id": featured_dataset_id,
            "time_column": "date",  # Assuming date column exists
            "value_columns": ["revenue", "quantity"],
            "frequency": "daily",
            "operations": ["trend", "seasonality", "stationarity"],
            "forecast_periods": 30,
            "confidence_intervals": True,
        },
    )

    if ts_analysis["success"]:
        ts_result = ts_analysis["time_series_analysis"]
        print(f"✅ Time series analysis completed:")

        if "trend_analysis" in ts_result:
            trend = ts_result["trend_analysis"]
            if "direction" in trend:
                print(f"   • Trend: {trend.get('direction', 'N/A')} ({trend.get('strength', 'N/A')} strength)")

        if "forecast" in ts_result:
            forecast = ts_result["forecast"]
            print(f"   • Forecast generated: {len(forecast.get('forecast', []))} periods")
    else:
        print(f"ℹ️  Time series analysis not applicable to this dataset")

    # Phase 5: ADVANCED QUERYING AND INSIGHTS
    print("\n🔍 PHASE 5: ADVANCED ANALYTICS QUERIES")
    print("-" * 40)

    print("\n📊 Step 5.1: Business intelligence queries...")

    # Complex business analytics query
    bi_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": featured_dataset_id,
            "query": """
            SELECT
                product_category,
                revenue_tier,
                COUNT(*) as transaction_count,
                SUM(revenue) as total_revenue,
                AVG(revenue) as avg_revenue,
                AVG(quantity_sold) as avg_quantity,
                SUM(revenue) / SUM(quantity_sold) as revenue_per_unit,
                STDDEV(revenue) as revenue_std
            FROM table
            WHERE revenue > 0 AND quantity_sold > 0
            GROUP BY product_category, revenue_tier
            ORDER BY total_revenue DESC
            """,
            "limit": 20,
            "return_format": "json",
        },
    )

    if bi_query["success"]:
        query_data = bi_query["query_result"]
        print("✅ Business intelligence analysis:")
        if "data" in query_data:
            print("   Top performing category-tier combinations:")
            for i, row in enumerate(query_data["data"][:5], 1):
                print(f"   {i}. {row.get('product_category', 'N/A')} - {row.get('revenue_tier', 'N/A')}: " f"${row.get('total_revenue', 0):,.0f} " f"({row.get('transaction_count', 0)} transactions)")

    print("\n🎯 Step 5.2: Customer behavior analysis...")

    customer_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": featured_dataset_id,
            "query": """
            SELECT
                customer_segment,
                COUNT(*) as total_transactions,
                AVG(revenue) as avg_transaction_value,
                SUM(revenue) as segment_revenue,
                AVG(quantity_sold) as avg_items_per_transaction
            FROM table
            WHERE customer_segment IS NOT NULL
            GROUP BY customer_segment
            ORDER BY segment_revenue DESC
            """,
            "return_format": "json",
        },
    )

    if customer_query["success"]:
        query_data = customer_query["query_result"]
        print("✅ Customer segment analysis:")
        if "data" in query_data:
            for row in query_data["data"]:
                print(
                    f"   • {row.get('customer_segment', 'N/A')}: "
                    f"{row.get('unique_customers', 0)} customers, "
                    f"${row.get('segment_revenue', 0):,.0f} revenue, "
                    f"{row.get('transactions_per_customer', 0):.1f} transactions/customer"
                )

    # Phase 6: COMPREHENSIVE VISUALIZATIONS
    print("\n🎨 PHASE 6: VISUALIZATION DASHBOARD")
    print("-" * 36)

    print("\n📊 Step 6.1: Creating business dashboard visualizations...")

    # Revenue distribution visualization
    revenue_viz = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": featured_dataset_id,
            "plot_type": "histogram",
            "x_column": "revenue",
            "color_column": "product_category",
            "title": "Revenue Distribution by Product Category",
            "save_format": "png",
            "interactive": False,
        },
    )

    if revenue_viz["success"]:
        viz_info = revenue_viz["visualization"]
        print(f"✅ Revenue distribution plot: {viz_info.get('filename', 'N/A')}")

    # Correlation heatmap
    corr_viz = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": featured_dataset_id,
            "plot_type": "heatmap",
            "x_column": "revenue",
            "y_column": "quantity_sold",
            "title": "Feature Correlation Heatmap",
            "save_format": "png",
            "interactive": False,
        },
    )

    if corr_viz["success"]:
        viz_info = corr_viz["visualization"]
        print(f"✅ Correlation heatmap: {viz_info.get('filename', 'N/A')}")

    # Interactive business performance scatter plot
    performance_viz = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": featured_dataset_id,
            "plot_type": "scatter",
            "x_column": "quantity_sold",
            "y_column": "revenue",
            "color_column": "revenue_tier",
            "facet_column": "product_category",
            "title": "Interactive: Quantity vs Revenue Analysis",
            "save_format": "html",
            "interactive": True,
        },
    )

    if performance_viz["success"]:
        viz_info = performance_viz["visualization"]
        print(f"✅ Interactive performance analysis: {viz_info.get('filename', 'N/A')}")

    # Box plot for revenue tier analysis
    tier_viz = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": featured_dataset_id,
            "plot_type": "box",
            "x_column": "revenue_tier",
            "y_column": "quantity_sold",
            "color_column": "product_category",
            "title": "Quantity Distribution by Revenue Tier and Category",
            "save_format": "png",
            "interactive": False,
        },
    )

    if tier_viz["success"]:
        viz_info = tier_viz["visualization"]
        print(f"✅ Revenue tier analysis: {viz_info.get('filename', 'N/A')}")

    # Phase 7: RESULTS EXPORT AND REPORTING
    print("\n📋 PHASE 7: RESULTS EXPORT AND REPORTING")
    print("-" * 42)

    print("\n💾 Step 7.1: Exporting final results...")

    # Export key findings in different formats
    final_report_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": featured_dataset_id,
            "query": """
            SELECT
                product_category,
                COUNT(*) as total_transactions,
                AVG(revenue) as avg_revenue,
                SUM(revenue) as total_revenue,
                AVG(quantity_sold) as avg_quantity,
                MIN(revenue) as min_revenue,
                MAX(revenue) as max_revenue
            FROM table
            GROUP BY product_category
            ORDER BY total_revenue DESC
            """,
            "return_format": "csv",
        },
    )

    if final_report_query["success"]:
        print("✅ Final business report exported in CSV format")

    # Get summary statistics for reporting
    summary_stats = await client.call_tool(
        "query_data",
        {
            "dataset_id": featured_dataset_id,
            "query": """
            SELECT
                COUNT(*) as total_records,
                COUNT(DISTINCT customer_segment) as customer_segments,
                COUNT(DISTINCT product_category) as product_categories,
                SUM(revenue) as total_revenue,
                AVG(revenue) as avg_revenue_per_transaction,
                SUM(quantity_sold) as total_items_sold
            FROM table
            """,
            "return_format": "json",
        },
    )

    # Final Summary Report
    print("\n🎉 COMPREHENSIVE WORKFLOW COMPLETE!")
    print("=" * 65)
    print("📊 EXECUTIVE SUMMARY")
    print("-" * 20)

    if summary_stats["success"]:
        stats = summary_stats["query_result"]["data"][0]
        print(f"Dataset Overview:")
        total_records = stats.get("total_records", 0)
        customer_segments = stats.get("customer_segments", 0)
        print(f"  • Total Records: {total_records:,}" if isinstance(total_records, (int, float)) else f"  • Total Records: {total_records}")
        print(f"  • Customer Segments: {customer_segments:,}" if isinstance(customer_segments, (int, float)) else f"  • Customer Segments: {customer_segments}")
        print(f"  • Product Categories: {stats.get('product_categories', 'N/A')}")
        total_revenue = stats.get("total_revenue", 0)
        avg_revenue = stats.get("avg_revenue_per_transaction", 0)
        total_items = stats.get("total_items_sold", 0)
        print(f"  • Total Revenue: ${total_revenue:,.2f}" if isinstance(total_revenue, (int, float)) else f"  • Total Revenue: ${total_revenue}")
        print(f"  • Average Transaction: ${avg_revenue:.2f}" if isinstance(avg_revenue, (int, float)) else f"  • Average Transaction: ${avg_revenue}")
        print(f"  • Total Items Sold: {total_items:,}" if isinstance(total_items, (int, float)) else f"  • Total Items Sold: {total_items}")

    print(f"\n🔧 WORKFLOW STAGES COMPLETED:")
    print(f"  ✅ 1. Data Loading & Exploration")
    print(f"  ✅ 2. Data Cleaning & Preprocessing")
    print(f"  ✅ 3. Feature Engineering")
    print(f"  ✅ 4. Statistical Analysis & Hypothesis Testing")
    print(f"  ✅ 5. Time Series Analysis (where applicable)")
    print(f"  ✅ 6. Advanced SQL Analytics")
    print(f"  ✅ 7. Comprehensive Visualizations")
    print(f"  ✅ 8. Results Export & Reporting")

    print(f"\n📊 ANALYSIS OUTPUTS GENERATED:")
    print(f"  • Multiple dataset versions (raw → cleaned → featured)")
    print(f"  • Statistical test results (ANOVA, Chi-square)")
    print(f"  • Business intelligence queries")
    print(f"  • Customer segmentation analysis")
    print(f"  • 4+ Visualizations (static PNG + interactive HTML)")
    print(f"  • Exportable reports (CSV, JSON, HTML formats)")
    print(f"  • Executive summary with key metrics")

    print(f"\n🚀 MCP DATA ANALYSIS SERVER CAPABILITIES DEMONSTRATED:")
    print(f"  ✅ 7 MCP Tools: load_dataset, analyze_dataset, transform_data,")
    print(f"      statistical_test, time_series_analysis, query_data, create_visualization")
    print(f"  ✅ 14+ Data transformation operations")
    print(f"  ✅ 7+ Statistical tests and analyses")
    print(f"  ✅ 6+ Visualization types (static + interactive)")
    print(f"  ✅ SQL-like querying with complex analytics")
    print(f"  ✅ Multiple export formats and reporting")
    print(f"  ✅ Complete end-to-end data science pipeline")

    print(f"\nDataset IDs for reference:")
    print(f"  • Original: {primary_dataset_id}")
    print(f"  • Cleaned: {cleaned_dataset_id}")
    print(f"  • Featured: {featured_dataset_id}")

    print("\n" + "=" * 65)
    print("🎯 This comprehensive workflow demonstrates the full power")
    print("   of the MCP Data Analysis Server for end-to-end")
    print("   data science and business analytics projects!")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
