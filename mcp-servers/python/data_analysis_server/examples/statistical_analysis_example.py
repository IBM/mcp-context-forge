# -*- coding: utf-8 -*-
"""
Statistical Analysis Example for MCP Data Analysis Server

This example demonstrates comprehensive statistical testing capabilities including:
- T-tests (one-sample, two-sample)
- ANOVA (one-way, two-way)
- Chi-square tests
- Correlation analysis
- Distribution testing
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
    """Demonstrate statistical analysis capabilities."""
    # Third-Party
    from data_analysis_server.server import analysis_server

    client = MockMCPClient(analysis_server)

    print("📊 MCP Data Analysis Server - Statistical Analysis Example")
    print("=" * 60)

    # Step 1: Load customer data
    print("\n📈 Step 1: Loading customer behavior data...")

    customer_data_path = (
        Path(__file__).parent.parent / "sample_data" / "customer_data.json"
    )

    load_result = await client.call_tool(
        "load_dataset",
        {
            "source": str(customer_data_path),
            "format": "json",
            "sample_size": None,
            "cache_data": True,
        },
    )

    if not load_result["success"]:
        print(f"❌ Failed to load data: {load_result.get('error')}")
        return

    dataset_id = load_result["dataset_id"]
    print(f"✅ Loaded dataset: {load_result['message']}")
    print(f"   Dataset ID: {dataset_id}")

    # Step 2: Comprehensive statistical analysis
    print("\n🔬 Step 2: Performing comprehensive statistical analysis...")

    analysis_result = await client.call_tool(
        "analyze_dataset",
        {
            "dataset_id": dataset_id,
            "analysis_type": "comprehensive",
            "include_distributions": True,
            "include_correlations": True,
            "include_outliers": True,
            "confidence_level": 0.95,
        },
    )

    if analysis_result["success"]:
        analysis = analysis_result["analysis"]
        print(f"✅ Analysis completed for {analysis['dataset_shape']} dataset")

        # Show correlation insights
        if "correlations" in analysis:
            correlations = analysis["correlations"]
            print("\n🔍 Key Correlations:")
            if "strong_correlations" in correlations:
                for corr in correlations["strong_correlations"][:3]:
                    print(
                        f"   • {corr['feature_1']} ↔ {corr['feature_2']}: "
                        f"{corr['correlation']:.3f} (p={corr.get('p_value', 'N/A')})"
                    )

        # Show outliers
        if "outliers" in analysis:
            outliers = analysis["outliers"]
            print("\n⚠️  Outlier Detection:")
            for column, outlier_info in list(outliers.items())[:2]:
                if isinstance(outlier_info, dict) and "count" in outlier_info:
                    print(f"   • {column}: {outlier_info['count']} outliers detected")

    # Step 3: T-test analysis
    print("\n📊 Step 3: Performing t-test analysis...")
    print(
        "   Note: T-test requires exactly 2 groups, but dataset has 3 segments (Basic, Premium, Standard)"
    )

    ttest_result = await client.call_tool(
        "statistical_test",
        {
            "dataset_id": dataset_id,
            "test_type": "t_test",
            "columns": ["purchase_amount"],
            "groupby_column": "customer_segment",
            "hypothesis": "two_sided",
            "alpha": 0.05,
            "alternative": "two-sided",
        },
    )

    if ttest_result["success"]:
        test_result = ttest_result["test_result"]
        print("✅ T-test completed:")
        print(f"   • Test statistic: {test_result.get('statistic', 'N/A'):.4f}")
        print(f"   • P-value: {test_result.get('p_value', 'N/A'):.4f}")
        print(f"   • Effect size: {test_result.get('effect_size', 'N/A')}")
        print(f"   • Conclusion: {test_result.get('conclusion', 'N/A')}")
    else:
        print(f"❌ T-test failed: {ttest_result.get('error')}")

    # Step 4: ANOVA test
    print("\n📈 Step 4: Performing ANOVA test...")

    anova_result = await client.call_tool(
        "statistical_test",
        {
            "dataset_id": dataset_id,
            "test_type": "anova",
            "columns": ["purchase_amount"],
            "groupby_column": "customer_segment",
            "hypothesis": "different_means",
            "alpha": 0.05,
        },
    )

    if anova_result["success"]:
        test_result = anova_result["test_result"]
        print("✅ ANOVA completed:")
        print(f"   • F-statistic: {test_result.get('statistic', 'N/A'):.4f}")
        print(f"   • P-value: {test_result.get('p_value', 'N/A'):.4f}")
        if "degrees_of_freedom" in test_result:
            dof = test_result["degrees_of_freedom"]
            if isinstance(dof, dict):
                print(
                    f"   • Degrees of freedom: Between={dof.get('between', 'N/A')}, "
                    f"Within={dof.get('within', 'N/A')}"
                )
            else:
                print(f"   • Degrees of freedom: {dof}")
        print(f"   • Interpretation: {test_result.get('interpretation', 'N/A')}")
    else:
        print(f"❌ ANOVA failed: {anova_result.get('error')}")

    # Step 5: Chi-square test
    print("\n🎯 Step 5: Performing Chi-square test...")

    chi_square_result = await client.call_tool(
        "statistical_test",
        {
            "dataset_id": dataset_id,
            "test_type": "chi_square",
            "columns": ["customer_segment", "product_category"],
            "hypothesis": "independence",
            "alpha": 0.05,
        },
    )

    if chi_square_result["success"]:
        test_result = chi_square_result["test_result"]
        print("✅ Chi-square test completed:")
        print(f"   • Chi-square statistic: {test_result.get('statistic', 'N/A'):.4f}")
        print(f"   • P-value: {test_result.get('p_value', 'N/A'):.4f}")
        print(
            f"   • Degrees of freedom: {test_result.get('degrees_of_freedom', 'N/A')}"
        )
        print(f"   • Effect size (Cramér's V): {test_result.get('effect_size', 'N/A')}")
        print(f"   • Conclusion: {test_result.get('conclusion', 'N/A')}")
    else:
        print(f"❌ Chi-square test failed: {chi_square_result.get('error')}")

    # Step 6: Correlation analysis visualization
    print("\n📊 Step 6: Creating correlation heatmap...")

    correlation_viz = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "heatmap",
            "title": "Customer Data Correlation Matrix",
            "save_format": "png",
        },
    )

    if correlation_viz["success"]:
        viz_info = correlation_viz["visualization"]
        print(f"✅ Created correlation heatmap: {viz_info.get('filename', 'N/A')}")
        if "metadata" in viz_info:
            metadata = viz_info["metadata"]
            print(
                f"   • Size: {metadata.get('width', 'N/A')}x{metadata.get('height', 'N/A')}"
            )
    else:
        print(f"❌ Correlation visualization failed: {correlation_viz.get('error')}")

    # Step 7: Distribution analysis
    print("\n📈 Step 7: Creating distribution plots...")

    distribution_viz = await client.call_tool(
        "create_visualization",
        {
            "dataset_id": dataset_id,
            "plot_type": "histogram",
            "x_column": "purchase_amount",
            "color_column": "customer_segment",
            "title": "Purchase Amount Distribution by Customer Segment",
            "save_format": "png",
        },
    )

    if distribution_viz["success"]:
        viz_info = distribution_viz["visualization"]
        print(f"✅ Created distribution plot: {viz_info.get('filename', 'N/A')}")
    else:
        print(f"❌ Distribution visualization failed: {distribution_viz.get('error')}")

    # Step 8: Statistical summary query
    print("\n🔍 Step 8: Advanced statistical queries...")

    stat_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": """
            SELECT
                customer_segment,
                COUNT(*) as count,
                AVG(purchase_amount) as avg_purchase,
                MIN(age) as min_age,
                MAX(age) as max_age
            FROM table
            GROUP BY customer_segment
            ORDER BY avg_purchase DESC
            """,
            "return_format": "json",
        },
    )

    if stat_query["success"]:
        query_data = stat_query["query_result"]
        print("✅ Statistical summary by customer segment:")
        if "data" in query_data and query_data["data"]:
            for row in query_data["data"]:
                print(
                    f"   • {row.get('customer_segment', 'N/A')}: "
                    f"N={row.get('count', 0)}, "
                    f"Avg Purchase=${row.get('avg_purchase', 0):.2f} "
                    f"Age Range={row.get('min_age', 0)}-{row.get('max_age', 0)}"
                )
        else:
            print("   • No data returned from query")
            print(f"   • Query result structure: {query_data}")
    else:
        print(f"❌ Statistical query failed: {stat_query.get('error')}")

    print("\n🎉 Statistical Analysis Complete!")
    print("=" * 60)
    print("Summary of statistical tests performed:")
    print("• Comprehensive dataset analysis with correlations and outliers")
    print("• T-test for group comparisons")
    print("• ANOVA for multiple group analysis")
    print("• Chi-square test for categorical associations")
    print("• Correlation heatmap visualization")
    print("• Distribution analysis by groups")
    print("• Advanced statistical aggregation queries")


if __name__ == "__main__":
    asyncio.run(main())
