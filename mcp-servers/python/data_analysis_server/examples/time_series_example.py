#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Time Series Analysis Example

This example demonstrates time series analysis capabilities
including trend detection, seasonality analysis, and forecasting.
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

        result = await handle_call_tool(tool_name, arguments)
        return json.loads(result[0].text)


async def main():
    """Main time series analysis workflow."""
    # Third-Party
    from data_analysis_server.server import analysis_server

    client = MockMCPClient(analysis_server)

    print("📈 MCP Data Analysis Server - Time Series Analysis Example")
    print("=" * 62)

    # Step 1: Load stock price data
    print("\n📊 Step 1: Loading stock price time series data...")

    stock_data_path = Path(__file__).parent.parent / "sample_data" / "stock_prices.csv"

    load_result = await client.call_tool(
        "load_dataset",
        {
            "source": str(stock_data_path),
            "format": "csv",
            "dataset_id": "stock_prices",
            "cache_data": True,
        },
    )

    if load_result["success"]:
        print(f"✅ Loaded dataset: {load_result['message']}")
        dataset_id = load_result["dataset_id"]
    else:
        print(f"❌ Failed to load data: {load_result.get('error')}")
        return

    # Step 2: Basic analysis of the time series data
    print("\n🔍 Step 2: Basic dataset analysis...")

    analysis_result = await client.call_tool(
        "analyze_dataset",
        {
            "dataset_id": dataset_id,
            "analysis_type": "descriptive",
            "columns": ["close", "volume", "high", "low"],
            "include_distributions": True,
            "include_correlations": True,
        },
    )

    if analysis_result["success"]:
        analysis = analysis_result["analysis"]
        print("✅ Basic analysis completed")

        # Show key statistics for closing prices
        close_stats = analysis["descriptive_stats"]["numeric_columns"].get("close", {})
        if close_stats:
            print("   • Close price statistics:")
            print(f"     - Mean: ${close_stats['mean']:.2f}")
            print(f"     - Std Dev: ${close_stats['std']:.2f}")
            print(f"     - Range: ${close_stats['min']:.2f} - ${close_stats['max']:.2f}")

    # Step 3: Time series visualization
    print("\n📊 Step 3: Creating time series visualizations...")

    # Time series plot for Apple stock
    viz_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "time_series",
            "x_column": "date",
            "y_column": "close",
            "color_column": "symbol",
            "title": "Stock Prices Over Time",
            "save_format": "png",
        },
    )

    if viz_result["success"]:
        print(f"✅ Created time series plot: {viz_result['visualization']['filename']}")

    # Volume analysis
    volume_viz_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "line",
            "x_column": "date",
            "y_column": "volume",
            "color_column": "symbol",
            "title": "Trading Volume Over Time",
            "save_format": "png",
        },
    )

    if volume_viz_result["success"]:
        print(f"✅ Created volume plot: {volume_viz_result['visualization']['filename']}")

    # Step 4: Time series analysis
    print("\n📈 Step 4: Performing comprehensive time series analysis...")

    ts_result = await client.call_tool(
        "time_series_analysis",
        {
            "dataset_id": dataset_id,
            "time_column": "date",
            "value_columns": ["close", "volume"],
            "operations": ["trend", "seasonal", "forecast"],
            "forecast_periods": 5,
            "confidence_intervals": True,
        },
    )

    if ts_result["success"]:
        ts_analysis = ts_result["time_series_analysis"]
        print("✅ Time series analysis completed")

        # Show results for each analyzed column
        for column, results in ts_analysis["results"].items():
            print(f"\n   📊 Analysis for {column}:")
            print(f"   • Data points: {results['data_points']}")
            print(f"   • Time range: {results['time_range']['start']} to {results['time_range']['end']}")
            print(f"   • Frequency: {results['frequency']}")

            # Trend analysis
            if "trend_analysis" in results:
                trend = results["trend_analysis"]
                if "error" not in trend:
                    print(f"   • Trend: {trend['direction']} ({trend['strength']} strength)")
                    print(f"   • R-squared: {trend['r_squared']:.3f}")
                    print(f"   • Significant: {'Yes' if trend['significant'] else 'No'}")

            # Stationarity test
            if "stationarity" in results:
                stationarity = results["stationarity"]
                if "rolling_stats" in stationarity:
                    rs = stationarity["rolling_stats"]
                    print(f"   • Appears stationary: {'Yes' if rs['appears_stationary'] else 'No'}")

            # Forecast results
            if "forecast" in results:
                forecast = results["forecast"]
                if "error" not in forecast:
                    print(f"   • Forecast: {forecast['periods']} periods ahead")
                    print(f"   • Method: {forecast['method']}")
                    print(f"   • Forecast values: {forecast['forecast'][:3]}... (showing first 3)")

    # Step 5: Statistical tests on time series data
    print("\n🧮 Step 5: Statistical analysis of price movements...")

    # First, let's create a filtered dataset for Apple only
    apple_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT * FROM table WHERE symbol = 'AAPL'",
            "limit": 100,
        },
    )

    if apple_query["success"]:
        print("✅ Filtered Apple stock data for detailed analysis")

    # Test correlation between volume and price changes
    correlation_viz = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "scatter",
            "x_column": "volume",
            "y_column": "close",
            "color_column": "symbol",
            "title": "Volume vs Closing Price Relationship",
            "save_format": "png",
        },
    )

    if correlation_viz["success"]:
        print(f"✅ Created correlation plot: {correlation_viz['visualization']['filename']}")

    # Step 6: Sector analysis
    print("\n🏢 Step 6: Sector-based analysis...")

    # Compare performance by sector
    sector_test = await client.call_tool(
        "statistical_test",
        {
            "dataset_id": dataset_id,
            "test_type": "anova",
            "columns": ["close"],
            "groupby_column": "sector",
            "hypothesis": "Stock prices differ by sector",
            "alpha": 0.05,
        },
    )

    if sector_test["success"]:
        test = sector_test["test_result"]
        print("✅ Sector analysis completed:")
        print(f"   • Test: {test['test_type']}")
        print(f"   • F-statistic: {test['statistic']:.3f}")
        print(f"   • P-value: {test['p_value']:.6f}")
        print(f"   • Conclusion: {test['conclusion']}")

    # Step 7: Advanced queries
    print("\n🔍 Step 7: Advanced data queries...")

    # Find highest volume trading days
    high_volume_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT date, symbol, close, volume FROM table WHERE volume > 2000000 ORDER BY volume DESC",
            "limit": 5,
            "return_format": "json",
        },
    )

    if high_volume_query["success"]:
        print("✅ High volume trading days:")
        query_data = high_volume_query["query_result"]
        if "data" in query_data:
            for row in query_data["data"]:
                print(f"   • {row['date']}: {row['symbol']} - Volume: {row['volume']:,}, Price: ${row['close']:.2f}")

    print("\n🎉 Time series analysis example completed!")
    print("\nThis example demonstrated:")
    print("• Loading time series data")
    print("• Time series visualization")
    print("• Trend and seasonality analysis")
    print("• Forecasting with confidence intervals")
    print("• Stationarity testing")
    print("• Cross-sectional analysis (sector comparison)")
    print("• Advanced querying for insights")


if __name__ == "__main__":
    asyncio.run(main())
