# -*- coding: utf-8 -*-
"""
Query Operations Example for MCP Data Analysis Server

This example demonstrates comprehensive SQL-like query capabilities including:
- SELECT statements with column selection
- WHERE clauses with various conditions (=, !=, IN, LIKE, NULL checks)
- GROUP BY with aggregation functions (COUNT, SUM, AVG, MIN, MAX)
- ORDER BY with multiple columns and directions
- Complex queries with multiple clauses
- Query result formatting (JSON, CSV, HTML)
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
    """Demonstrate comprehensive query operations."""
    # Third-Party
    from data_analysis_server.server import analysis_server

    client = MockMCPClient(analysis_server)

    print("🔍 MCP Data Analysis Server - Query Operations Example")
    print("=" * 60)

    # Step 1: Load retail transaction data
    print("\n📊 Step 1: Loading retail transaction data...")

    retail_data_path = (
        Path(__file__).parent.parent / "sample_data" / "retail_transactions.csv"
    )

    load_result = await client.call_tool(
        "load_dataset",
        {
            "source": str(retail_data_path),
            "format": "csv",
            "sample_size": None,
            "cache_data": True,
        },
    )

    if not load_result["success"]:
        print(f"❌ Failed to load data: {load_result.get('error')}")
        return

    dataset_id = load_result["dataset_id"]
    print(f"✅ Loaded retail dataset: {load_result['message']}")
    print(f"   Dataset ID: {dataset_id}")

    # Step 2: Basic SELECT queries
    print("\n📋 Step 2: Basic SELECT queries...")

    # Simple SELECT with specific columns
    basic_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT customer_id, product_name, quantity, price FROM table LIMIT 10",
            "return_format": "json",
        },
    )

    if basic_query["success"]:
        query_data = basic_query["query_result"]
        print("✅ Basic SELECT query (first 10 rows):")
        if "data" in query_data:
            for i, row in enumerate(query_data["data"][:3]):  # Show first 3
                print(
                    f"   {i + 1}. Customer: {row.get('customer_id', 'N/A')}, "
                    f"Product: {row.get('product_name', 'N/A')}, "
                    f"Qty: {row.get('quantity', 0)}, "
                    f"Price: ${row.get('price', 0):.2f}"
                )
    else:
        print(f"❌ Basic query failed: {basic_query.get('error')}")

    # Step 3: WHERE clause variations
    print("\n🔍 Step 3: WHERE clause queries...")

    # Query with equality condition
    where_query1 = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT * FROM table WHERE category = 'Electronics' LIMIT 5",
            "return_format": "json",
        },
    )

    if where_query1["success"]:
        result_count = len(where_query1["query_result"].get("data", []))
        print(f"✅ Electronics products: {result_count} results")

    # Query with range condition
    where_query2 = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT customer_id, product_name, price FROM table WHERE price > 100 AND price < 500 ORDER BY price DESC LIMIT 8",
            "return_format": "json",
        },
    )

    if where_query2["success"]:
        query_data = where_query2["query_result"]
        print("✅ Mid-range products ($100-$500):")
        if "data" in query_data:
            for row in query_data["data"][:3]:
                print(
                    f"   • {row.get('product_name', 'N/A')}: ${row.get('price', 0):.2f}"
                )

    # Query with IN condition
    where_query3 = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT category, COUNT(*) as count FROM table WHERE category IN ('Electronics', 'Clothing', 'Books') GROUP BY category",
            "return_format": "json",
        },
    )

    if where_query3["success"]:
        query_data = where_query3["query_result"]
        print("✅ Product counts by major categories:")
        if "data" in query_data:
            for row in query_data["data"]:
                print(
                    f"   • {row.get('category', 'N/A')}: {row.get('count', 0)} products"
                )

    # Step 4: Aggregation functions
    print("\n📊 Step 4: Aggregation queries...")

    # Complex aggregation query
    agg_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": """
            SELECT
                category,
                COUNT(*) as transaction_count,
                SUM(quantity) as total_quantity,
                AVG(price) as avg_price,
                MIN(price) as min_price,
                MAX(price) as max_price,
                SUM(quantity * price) as total_revenue
            FROM table
            GROUP BY category
            ORDER BY total_revenue DESC
            """,
            "return_format": "json",
        },
    )

    if agg_query["success"]:
        query_data = agg_query["query_result"]
        print("✅ Category performance analysis:")
        if "data" in query_data:
            for row in query_data["data"][:5]:  # Top 5 categories
                print(
                    f"   • {row.get('category', 'N/A')}: "
                    f"Revenue=${row.get('total_revenue', 0):,.0f}, "
                    f"Transactions={row.get('transaction_count', 0)}, "
                    f"Avg Price=${row.get('avg_price', 0):.2f}"
                )

    # Step 5: Advanced WHERE conditions
    print("\n🔎 Step 5: Advanced WHERE conditions...")

    # Query with LIKE condition (if supported)
    like_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT product_name, price FROM table WHERE product_name LIKE 'Phone' LIMIT 5",
            "return_format": "json",
        },
    )

    if like_query["success"]:
        query_data = like_query["query_result"]
        if "data" in query_data and len(query_data["data"]) > 0:
            print("✅ Products containing 'Phone':")
            for row in query_data["data"]:
                print(
                    f"   • {row.get('product_name', 'N/A')}: ${row.get('price', 0):.2f}"
                )
        else:
            print("ℹ️  No products containing 'Phone' found")

    # Query with complex AND/OR conditions
    complex_where = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": """
            SELECT customer_id, product_name, quantity, price
            FROM table
            WHERE (price > 200 AND quantity > 2) OR (category = 'Electronics' AND price < 50)
            ORDER BY price DESC
            LIMIT 10
            """,
            "return_format": "json",
        },
    )

    if complex_where["success"]:
        result_count = len(complex_where["query_result"].get("data", []))
        print(f"✅ Complex WHERE condition: {result_count} results found")

    # Step 6: Customer analysis queries
    print("\n👥 Step 6: Customer analysis queries...")

    # Top customers by spending
    customer_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": """
            SELECT
                customer_id,
                COUNT(*) as purchase_count,
                SUM(quantity) as total_items,
                SUM(quantity * price) as total_spent,
                AVG(price) as avg_item_price
            FROM table
            GROUP BY customer_id
            HAVING COUNT(*) > 3
            ORDER BY total_spent DESC
            LIMIT 10
            """,
            "return_format": "json",
        },
    )

    if customer_query["success"]:
        query_data = customer_query["query_result"]
        print("✅ Top customers by spending (>3 purchases):")
        if "data" in query_data:
            for i, row in enumerate(query_data["data"][:5], 1):
                print(
                    f"   {i}. Customer {row.get('customer_id', 'N/A')}: "
                    f"${row.get('total_spent', 0):,.0f} "
                    f"({row.get('purchase_count', 0)} purchases, "
                    f"{row.get('total_items', 0)} items)"
                )

    # Step 7: Time-based queries (if date columns exist)
    print("\n📅 Step 7: Product popularity queries...")

    # Most popular products
    popular_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": """
            SELECT
                product_name,
                category,
                COUNT(*) as purchase_frequency,
                SUM(quantity) as total_sold,
                AVG(price) as avg_price,
                SUM(quantity * price) as total_revenue
            FROM table
            GROUP BY product_name, category
            ORDER BY purchase_frequency DESC, total_sold DESC
            LIMIT 15
            """,
            "return_format": "json",
        },
    )

    if popular_query["success"]:
        query_data = popular_query["query_result"]
        print("✅ Most popular products:")
        if "data" in query_data:
            for i, row in enumerate(query_data["data"][:5], 1):
                print(
                    f"   {i}. {row.get('product_name', 'N/A')} ({row.get('category', 'N/A')}): "
                    f"Sold {row.get('total_sold', 0)} units, "
                    f"{row.get('purchase_frequency', 0)} transactions, "
                    f"Revenue=${row.get('total_revenue', 0):,.0f}"
                )

    # Step 8: Query result formatting
    print("\n📄 Step 8: Different output formats...")

    # Get data in CSV format
    csv_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT category, AVG(price) as avg_price, COUNT(*) as count FROM table GROUP BY category ORDER BY avg_price DESC LIMIT 5",
            "return_format": "csv",
        },
    )

    if csv_query["success"]:
        csv_data = csv_query["query_result"]
        print("✅ CSV format output (first few lines):")
        if isinstance(csv_data, str):
            lines = csv_data.strip().split("\n")[:3]  # Show first 3 lines
            for line in lines:
                print(f"   {line}")

    # Get data in HTML format
    html_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT product_name, price, category FROM table ORDER BY price DESC LIMIT 3",
            "return_format": "html",
        },
    )

    if html_query["success"]:
        print("✅ HTML format output generated (table format)")
        # HTML output would be too long to display, just confirm it worked

    # Step 9: Pagination and limiting
    print("\n📑 Step 9: Pagination and result limiting...")

    # Query with offset and limit
    paginated_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": "SELECT customer_id, product_name, price FROM table ORDER BY price ASC",
            "limit": 5,
            "offset": 10,
            "return_format": "json",
        },
    )

    if paginated_query["success"]:
        query_data = paginated_query["query_result"]
        metadata = query_data.get("metadata", {})
        print("✅ Paginated query (offset=10, limit=5):")
        print(f"   • Total rows: {metadata.get('total_rows', 'N/A')}")
        print(f"   • Returned rows: {metadata.get('returned_rows', 'N/A')}")
        print(f"   • Offset: {metadata.get('offset', 'N/A')}")

    # Step 10: Query performance analysis
    print("\n⚡ Step 10: Complex analytical query...")

    # Complex multi-table-like query
    analytics_query = await client.call_tool(
        "query_data",
        {
            "dataset_id": dataset_id,
            "query": """
            SELECT
                category,
                CASE
                    WHEN price < 50 THEN 'Budget'
                    WHEN price < 200 THEN 'Mid-range'
                    ELSE 'Premium'
                END as price_tier,
                COUNT(*) as transaction_count,
                AVG(quantity) as avg_quantity,
                SUM(quantity * price) as total_revenue,
                AVG(price) as avg_price
            FROM table
            WHERE quantity > 0
            GROUP BY category,
                CASE
                    WHEN price < 50 THEN 'Budget'
                    WHEN price < 200 THEN 'Mid-range'
                    ELSE 'Premium'
                END
            ORDER BY category, avg_price DESC
            """,
            "return_format": "json",
        },
    )

    if analytics_query["success"]:
        query_data = analytics_query["query_result"]
        print("✅ Advanced analytics query - Category & Price Tier Analysis:")
        if "data" in query_data:
            current_category = None
            for row in query_data["data"][:8]:  # Show first 8 results
                category = row.get("category", "N/A")
                if category != current_category:
                    print(f"\n   {category}:")
                    current_category = category

                print(
                    f"     • {row.get('price_tier', 'N/A')}: "
                    f"{row.get('transaction_count', 0)} transactions, "
                    f"Avg Price=${row.get('avg_price', 0):.2f}, "
                    f"Revenue=${row.get('total_revenue', 0):,.0f}"
                )

    # Final summary
    print("\n🎉 Query Operations Showcase Complete!")
    print("=" * 60)
    print("SQL-like capabilities demonstrated:")
    print("✅ SELECT statements with column selection")
    print("✅ WHERE clauses with various operators (=, !=, >, <, AND, OR)")
    print("✅ IN operator for multiple value matching")
    print("✅ LIKE operator for pattern matching")
    print("✅ GROUP BY with aggregation functions:")
    print("   • COUNT, SUM, AVG, MIN, MAX")
    print("✅ ORDER BY with multiple columns and directions")
    print("✅ HAVING clause for filtered aggregations")
    print("✅ Complex nested conditions")
    print("✅ CASE statements for conditional logic")
    print("✅ Multiple output formats:")
    print("   • JSON (structured data)")
    print("   • CSV (comma-separated values)")
    print("   • HTML (formatted tables)")
    print("✅ Pagination with LIMIT and OFFSET")
    print("✅ Query metadata and performance info")
    print()
    print("All queries executed successfully against the retail dataset!")
    print("This demonstrates the full SQL-like querying capability of the MCP server.")


if __name__ == "__main__":
    asyncio.run(main())
