# Python Data Analysis Server

## Overview

A comprehensive MCP server providing advanced data analysis, statistical testing, visualization, and transformation capabilities. This server enables AI applications to perform sophisticated data science workflows through a standardized interface.

**Key Features:**

- 📊 Multi-format data loading (CSV, JSON, Parquet, SQL, Excel)
- 📈 Statistical analysis and hypothesis testing
- 📉 Rich visualization with matplotlib, seaborn, and plotly
- ⏰ Time series analysis and forecasting
- 🔄 Data transformation and feature engineering
- 🔍 SQL-like querying with pandas
- 💾 Smart dataset caching with automatic eviction

## Quick Start

### Installation

```bash
# Navigate to the server directory
cd mcp-servers/python/data_analysis_server

# Install dependencies
pip install -r requirements.txt

# Or install in development mode
pip install -e .[dev]
```

### Running the Server

```bash
# Run with default configuration
python -m data_analysis_server.server

# Run with custom configuration
python -m data_analysis_server.server --config my_config.yaml
```

### Integration with MCP Gateway

```bash
# Register with MCP Gateway
curl -X POST http://localhost:4444/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "data-analysis-server",
    "transport": "stdio",
    "command": "python -m data_analysis_server.server",
    "description": "Advanced data analysis and visualization server"
  }'
```

## Available Tools

### Data Management

#### load_dataset
Load data from various sources and formats.

```json
{
  "tool": "load_dataset",
  "arguments": {
    "source": "./data/sales.csv",
    "format": "csv",
    "dataset_id": "sales_data",
    "sample_size": 1000,
    "cache_data": true
  }
}
```

Supported formats:

- CSV, TSV
- JSON, JSONL
- Parquet
- Excel (xlsx, xls)
- SQL databases

#### list_datasets
List all currently loaded datasets.

```json
{
  "tool": "list_datasets"
}
```

### Statistical Analysis

#### analyze_dataset
Perform comprehensive dataset analysis.

```json
{
  "tool": "analyze_dataset",
  "arguments": {
    "dataset_id": "sales_data",
    "analysis_type": "exploratory",
    "include_distributions": true,
    "include_correlations": true
  }
}
```

Analysis types:

- `exploratory` - Full EDA with summary statistics
- `descriptive` - Basic statistics only
- `correlation` - Correlation analysis
- `distribution` - Distribution analysis

#### statistical_test
Perform various statistical tests.

```json
{
  "tool": "statistical_test",
  "arguments": {
    "dataset_id": "sales_data",
    "test_type": "t_test",
    "column": "revenue",
    "group_column": "region",
    "alpha": 0.05
  }
}
```

Supported tests:

- **Parametric**: t-test, ANOVA, linear regression
- **Non-parametric**: Mann-Whitney U, Wilcoxon, Kruskal-Wallis
- **Correlation**: Pearson, Spearman, Chi-square

### Data Visualization

#### create_visualization
Generate various types of plots.

```json
{
  "tool": "create_visualization",
  "arguments": {
    "dataset_id": "sales_data",
    "plot_type": "scatter",
    "x": "advertising_spend",
    "y": "revenue",
    "hue": "product_category",
    "title": "Revenue vs Advertising Spend",
    "save_path": "./plots/revenue_analysis.png"
  }
}
```

Plot types:

- **Distribution**: histogram, kde, box, violin
- **Relationship**: scatter, line, regression
- **Categorical**: bar, count, swarm, strip
- **Matrix**: heatmap, pair plot
- **Time Series**: line, area, seasonal decomposition

#### create_interactive_plot
Generate interactive Plotly visualizations.

```json
{
  "tool": "create_interactive_plot",
  "arguments": {
    "dataset_id": "sales_data",
    "plot_type": "3d_scatter",
    "x": "price",
    "y": "quantity",
    "z": "revenue",
    "color": "region",
    "save_html": true
  }
}
```

### Time Series Analysis

#### time_series_analysis
Perform time series decomposition and analysis.

```json
{
  "tool": "time_series_analysis",
  "arguments": {
    "dataset_id": "sales_data",
    "date_column": "date",
    "value_column": "daily_revenue",
    "frequency": "D",
    "decomposition_type": "additive",
    "include_forecast": true,
    "forecast_periods": 30
  }
}
```

Features:

- Trend detection
- Seasonality analysis
- Stationarity testing
- ARIMA forecasting
- Seasonal decomposition

### Data Transformation

#### transform_data
Apply various transformations to datasets.

```json
{
  "tool": "transform_data",
  "arguments": {
    "dataset_id": "sales_data",
    "transformations": [
      {"type": "scale", "columns": ["price", "quantity"], "method": "standard"},
      {"type": "encode", "columns": ["category"], "method": "onehot"},
      {"type": "impute", "columns": ["rating"], "method": "mean"}
    ],
    "save_as": "sales_data_transformed"
  }
}
```

Transformations:

- **Scaling**: standard, minmax, robust, normalizer
- **Encoding**: label, onehot, ordinal, target
- **Imputation**: mean, median, mode, forward fill
- **Feature Engineering**: polynomial, binning, interaction

#### clean_data
Automated data cleaning operations.

```json
{
  "tool": "clean_data",
  "arguments": {
    "dataset_id": "sales_data",
    "remove_duplicates": true,
    "handle_missing": "drop",
    "remove_outliers": true,
    "outlier_method": "iqr",
    "save_as": "sales_data_clean"
  }
}
```

### Data Querying

#### query_data
Execute SQL-like queries on datasets using pandas.

```json
{
  "tool": "query_data",
  "arguments": {
    "dataset_id": "sales_data",
    "query": "SELECT region, AVG(revenue) as avg_revenue FROM data WHERE date > '2024-01-01' GROUP BY region ORDER BY avg_revenue DESC",
    "limit": 100
  }
}
```

Supported SQL features:

- SELECT with column aliases
- WHERE clauses with complex conditions
- GROUP BY with aggregations
- ORDER BY (ASC/DESC)
- JOINs between datasets
- LIMIT and OFFSET

#### filter_data
Apply filters to create dataset subsets.

```json
{
  "tool": "filter_data",
  "arguments": {
    "dataset_id": "sales_data",
    "filters": [
      {"column": "revenue", "operator": ">", "value": 1000},
      {"column": "region", "operator": "in", "value": ["North", "South"]}
    ],
    "save_as": "high_revenue_sales"
  }
}
```

## Configuration

Create a `config.yaml` file:

```yaml
server:
  max_datasets: 100
  max_memory_mb: 1024
  cache_ttl_seconds: 3600

visualization:
  plot_output_dir: "./plots"
  default_dpi: 100
  default_figsize: [10, 6]
  style: "seaborn"

analysis:
  max_query_results: 10000
  default_sample_size: 5000
  confidence_level: 0.95

logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

### Environment Variables

- `DATA_ANALYSIS_CONFIG`: Path to configuration file
- `DATA_ANALYSIS_CACHE_DIR`: Directory for cached datasets
- `DATA_ANALYSIS_PLOT_DIR`: Directory for saved visualizations
- `DATA_ANALYSIS_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

## Advanced Usage

### Working with Large Datasets

```python
# Use sampling for large datasets
{
  "tool": "load_dataset",
  "arguments": {
    "source": "large_data.parquet",
    "format": "parquet",
    "dataset_id": "large_data",
    "sample_size": 10000,
    "sampling_method": "stratified",
    "stratify_column": "category"
  }
}
```

### Custom Statistical Models

```python
# Linear regression with multiple features
{
  "tool": "statistical_test",
  "arguments": {
    "dataset_id": "sales_data",
    "test_type": "linear_regression",
    "dependent": "revenue",
    "independent": ["price", "advertising", "season"],
    "include_intercept": true,
    "return_coefficients": true
  }
}
```

### Advanced Visualizations

```python
# Complex multi-panel visualization
{
  "tool": "create_visualization",
  "arguments": {
    "dataset_id": "sales_data",
    "plot_type": "pair_plot",
    "variables": ["revenue", "cost", "profit", "units"],
    "hue": "product_line",
    "diag_kind": "kde",
    "corner": true
  }
}
```

## Example Workflows

### Complete EDA Pipeline

```bash
# 1. Load data
{
  "tool": "load_dataset",
  "arguments": {
    "source": "sales_2024.csv",
    "dataset_id": "sales"
  }
}

# 2. Clean data
{
  "tool": "clean_data",
  "arguments": {
    "dataset_id": "sales",
    "remove_duplicates": true,
    "handle_missing": "impute"
  }
}

# 3. Exploratory analysis
{
  "tool": "analyze_dataset",
  "arguments": {
    "dataset_id": "sales",
    "analysis_type": "exploratory"
  }
}

# 4. Visualize distributions
{
  "tool": "create_visualization",
  "arguments": {
    "dataset_id": "sales",
    "plot_type": "histogram",
    "column": "revenue",
    "bins": 30
  }
}

# 5. Statistical testing
{
  "tool": "statistical_test",
  "arguments": {
    "dataset_id": "sales",
    "test_type": "anova",
    "column": "revenue",
    "group_column": "region"
  }
}
```

### Time Series Forecasting

```bash
# Load and prepare time series data
{
  "tool": "load_dataset",
  "arguments": {
    "source": "daily_sales.csv",
    "dataset_id": "timeseries"
  }
}

# Perform time series analysis
{
  "tool": "time_series_analysis",
  "arguments": {
    "dataset_id": "timeseries",
    "date_column": "date",
    "value_column": "sales",
    "frequency": "D",
    "include_forecast": true,
    "forecast_periods": 90
  }
}
```

## Performance Considerations

- **Dataset Caching**: Frequently accessed datasets are kept in memory
- **Lazy Loading**: Large files are loaded on-demand
- **Query Optimization**: SQL queries are converted to efficient pandas operations
- **Memory Management**: Automatic eviction of least-recently-used datasets
- **Parallel Processing**: Multi-core support for heavy computations

## Troubleshooting

### Common Issues

**Out of Memory:**
```yaml
# Reduce memory usage in config.yaml
server:
  max_memory_mb: 512
  max_datasets: 10
```

**Slow Queries:**
```python
# Use sampling for large datasets
{
  "tool": "query_data",
  "arguments": {
    "dataset_id": "large_data",
    "query": "SELECT * FROM data TABLESAMPLE(10 PERCENT)"
  }
}
```

**Missing Dependencies:**
```bash
# Install optional dependencies
pip install plotly  # For interactive plots
pip install xlrd    # For old Excel files
pip install sqlalchemy  # For SQL databases
```

## Related Resources

- [Pandas Documentation](https://pandas.pydata.org/docs/)
- [Seaborn Gallery](https://seaborn.pydata.org/examples/index.html)
- [Plotly Documentation](https://plotly.com/python/)
- [Statsmodels](https://www.statsmodels.org/)
