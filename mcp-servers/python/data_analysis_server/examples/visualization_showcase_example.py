# -*- coding: utf-8 -*-
"""
Visualization Showcase Example for MCP Data Analysis Server

This example demonstrates comprehensive visualization capabilities including:
- Static plots (matplotlib/seaborn): scatter, bar, histogram, box, heatmap
- Interactive plots (plotly): 3D scatter, interactive time series, choropleth
- Multiple chart types for different data scenarios
- Advanced plotting features (faceting, color mapping, styling)
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
    """Demonstrate comprehensive visualization capabilities."""
    # Third-Party
    from data_analysis_server.server import analysis_server

    client = MockMCPClient(analysis_server)

    print("🎨 MCP Data Analysis Server - Visualization Showcase")
    print("=" * 55)

    # Step 1: Load marketing campaign data
    print("\n📊 Step 1: Loading marketing campaign data...")

    campaign_data_path = Path(__file__).parent.parent / "sample_data" / "marketing_data.csv"

    load_result = await client.call_tool(
        "load_dataset",
        {
            "source": str(campaign_data_path),
            "format": "csv",
            "sample_size": 1000,  # Sample for faster visualization
            "cache_data": True,
        },
    )

    if not load_result["success"]:
        print(f"❌ Failed to load data: {load_result.get('error')}")
        return

    dataset_id = load_result["dataset_id"]
    print(f"✅ Loaded marketing dataset: {load_result['message']}")
    print(f"   Dataset ID: {dataset_id}")

    # Step 2: Scatter Plot - Campaign Performance
    print("\n📈 Step 2: Creating scatter plot - Campaign Performance...")

    scatter_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "scatter",
            "x_column": "ad_spend",
            "y_column": "revenue",
            "color_column": "campaign_type",
            "title": "Ad Spend vs Revenue by Campaign Type",
            "save_format": "png",
            "interactive": False,
        },
    )

    if scatter_result["success"]:
        viz_info = scatter_result["visualization"]
        print(f"✅ Created scatter plot: {viz_info.get('filename', 'N/A')}")
        metadata = viz_info.get("metadata", {})
        print(f"   • Dimensions: {metadata.get('width', 800)}x{metadata.get('height', 600)}")
    else:
        print(f"❌ Scatter plot failed: {scatter_result.get('error')}")

    # Step 3: Bar Chart - Campaign Comparison
    print("\n📊 Step 3: Creating bar chart - Campaign ROI by Type...")

    bar_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "bar",
            "x_column": "campaign_type",
            "y_column": "roi",
            "color_column": "campaign_type",
            "title": "Return on Investment by Campaign Type",
            "save_format": "png",
            "interactive": False,
        },
    )

    if bar_result["success"]:
        viz_info = bar_result["visualization"]
        print(f"✅ Created bar chart: {viz_info.get('filename', 'N/A')}")
    else:
        print(f"❌ Bar chart failed: {bar_result.get('error')}")

    # Step 4: Histogram - Distribution Analysis
    print("\n📈 Step 4: Creating histogram - Revenue Distribution...")

    hist_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "histogram",
            "x_column": "revenue",
            "color_column": "campaign_type",
            "facet_column": "target_audience",
            "title": "Revenue Distribution by Campaign Type and Audience",
            "save_format": "png",
            "interactive": False,
        },
    )

    if hist_result["success"]:
        viz_info = hist_result["visualization"]
        print(f"✅ Created histogram: {viz_info.get('filename', 'N/A')}")
    else:
        print(f"❌ Histogram failed: {hist_result.get('error')}")

    # Step 5: Box Plot - Performance Variance
    print("\n📦 Step 5: Creating box plot - Campaign Performance Variance...")

    box_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "box",
            "x_column": "campaign_type",
            "y_column": "click_rate",
            "color_column": "target_audience",
            "title": "Click Rate Distribution by Campaign Type and Audience",
            "save_format": "png",
            "interactive": False,
        },
    )

    if box_result["success"]:
        viz_info = box_result["visualization"]
        print(f"✅ Created box plot: {viz_info.get('filename', 'N/A')}")
    else:
        print(f"❌ Box plot failed: {box_result.get('error')}")

    # Step 6: Heatmap - Correlation Matrix
    print("\n🔥 Step 6: Creating heatmap - Marketing Metrics Correlation...")

    heatmap_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "heatmap",
            "title": "Marketing Metrics Correlation Heatmap",
            "save_format": "png",
            "interactive": False,
        },
    )

    if heatmap_result["success"]:
        viz_info = heatmap_result["visualization"]
        print(f"✅ Created correlation heatmap: {viz_info.get('filename', 'N/A')}")
    else:
        print(f"❌ Heatmap failed: {heatmap_result.get('error')}")

    # Step 7: Interactive Scatter Plot (Plotly)
    print("\n🎯 Step 7: Creating interactive scatter plot...")

    interactive_scatter = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "scatter",
            "x_column": "impressions",
            "y_column": "conversions",
            "color_column": "campaign_type",
            "title": "Interactive: Impressions vs Conversions",
            "save_format": "html",
            "interactive": True,
        },
    )

    if interactive_scatter["success"]:
        viz_info = interactive_scatter["visualization"]
        print(f"✅ Created interactive scatter plot: {viz_info.get('filename', 'N/A')}")
        print("   • Interactive features: zoom, pan, hover tooltips")
    else:
        print(f"❌ Interactive scatter plot failed: {interactive_scatter.get('error')}")

    # Step 8: Line Chart - Time Series (if time data available)
    print("\n📈 Step 8: Creating line chart - Campaign Performance Over Time...")

    line_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "line",
            "x_column": "campaign_id",  # Using campaign_id as proxy for time
            "y_column": "revenue",
            "color_column": "campaign_type",
            "title": "Revenue Trend by Campaign",
            "save_format": "png",
            "interactive": False,
        },
    )

    if line_result["success"]:
        viz_info = line_result["visualization"]
        print(f"✅ Created line chart: {viz_info.get('filename', 'N/A')}")
    else:
        print(f"❌ Line chart failed: {line_result.get('error')}")

    # Step 9: Interactive Bar Chart (Plotly)
    print("\n📊 Step 9: Creating interactive bar chart...")

    interactive_bar = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "bar",
            "x_column": "target_audience",
            "y_column": "engagement_rate",
            "color_column": "campaign_type",
            "title": "Interactive: Engagement Rate by Audience and Campaign",
            "save_format": "html",
            "interactive": True,
        },
    )

    if interactive_bar["success"]:
        viz_info = interactive_bar["visualization"]
        print(f"✅ Created interactive bar chart: {viz_info.get('filename', 'N/A')}")
    else:
        print(f"❌ Interactive bar chart failed: {interactive_bar.get('error')}")

    # Step 10: Faceted Visualization
    print("\n🔄 Step 10: Creating faceted visualization - Multi-panel Analysis...")

    faceted_result = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "scatter",
            "x_column": "cost_per_click",
            "y_column": "conversion_rate",
            "color_column": "campaign_type",
            "facet_column": "target_audience",
            "title": "CPC vs Conversion Rate by Audience (Faceted View)",
            "save_format": "png",
            "interactive": False,
        },
    )

    if faceted_result["success"]:
        viz_info = faceted_result["visualization"]
        print(f"✅ Created faceted visualization: {viz_info.get('filename', 'N/A')}")
        print("   • Multiple panels showing data by target audience")
    else:
        print(f"❌ Faceted visualization failed: {faceted_result.get('error')}")

    # Step 11: Advanced Query for Visualization Data
    print("\n🔍 Step 11: Preparing summary data for final visualization...")

    summary_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": """
            SELECT
                campaign_type,
                target_audience,
                COUNT(*) as campaign_count,
                AVG(roi) as avg_roi,
                AVG(engagement_rate) as avg_engagement,
                SUM(revenue) as total_revenue,
                AVG(cost_per_click) as avg_cpc
            FROM table
            GROUP BY campaign_type, target_audience
            ORDER BY avg_roi DESC
            """,
            "limit": 20,
            "return_format": "json",
        },
    )

    if summary_query["success"]:
        query_data = summary_query["query_result"]
        if "data" in query_data:
            print("✅ Campaign performance summary:")
            for i, row in enumerate(query_data["data"][:5]):  # Show top 5
                print(
                    f"   {i+1}. {row['campaign_type']} → {row['target_audience']}: " f"ROI={row['avg_roi']:.2f}, " f"Engagement={row['avg_engagement']:.1%}, " f"Revenue=${row['total_revenue']:,.0f}"
                )

    # Step 12: Create final dashboard-style visualization
    print("\n📋 Step 12: Creating dashboard summary visualization...")

    # Create a comprehensive multi-metric visualization
    dashboard_viz = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "scatter",
            "x_column": "ad_spend",
            "y_column": "roi",
            "color_column": "campaign_type",
            "title": "Marketing Dashboard: Ad Spend vs ROI by Campaign Type",
            "save_format": "png",
            "interactive": False,
        },
    )

    if dashboard_viz["success"]:
        viz_info = dashboard_viz["visualization"]
        print(f"✅ Created dashboard visualization: {viz_info.get('filename', 'N/A')}")

    # Final summary
    print("\n🎉 Visualization Showcase Complete!")
    print("=" * 55)
    print("Visualization types created:")
    print("📈 Static Visualizations (PNG):")
    print("  • Scatter Plot - Ad Spend vs Revenue")
    print("  • Bar Chart - ROI by Campaign Type")
    print("  • Histogram - Revenue Distribution (Faceted)")
    print("  • Box Plot - Click Rate Distribution")
    print("  • Heatmap - Correlation Matrix")
    print("  • Line Chart - Revenue Trends")
    print("  • Faceted Scatter - Multi-panel Analysis")
    print()
    print("🎯 Interactive Visualizations (HTML):")
    print("  • Interactive Scatter - Impressions vs Conversions")
    print("  • Interactive Bar Chart - Engagement by Audience")
    print()
    print("Key Features Demonstrated:")
    print("  ✅ Multiple plot types (scatter, bar, histogram, box, heatmap, line)")
    print("  ✅ Color coding by categorical variables")
    print("  ✅ Faceted/multi-panel visualizations")
    print("  ✅ Interactive plots with hover and zoom")
    print("  ✅ Both static (PNG) and interactive (HTML) outputs")
    print("  ✅ Integration with SQL queries for data prep")
    print("  ✅ Professional styling and titles")
    print()
    print("All visualizations have been saved to the plots/ directory!")


if __name__ == "__main__":
    asyncio.run(main())
