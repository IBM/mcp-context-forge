# MCP Data Analysis Server

A comprehensive Model Context Protocol (MCP) server providing advanced data analysis, statistical testing, visualization, and transformation capabilities. This server enables AI applications to perform sophisticated data science workflows through a standardized interface.

## 🚀 Features

### Core Capabilities
- **Multi-format Data Loading**: CSV, JSON, Parquet, SQL, Excel
- **Statistical Analysis**: Descriptive statistics, hypothesis testing, correlation analysis
- **Data Visualization**: Multiple plot types with matplotlib, seaborn, and plotly
- **Time Series Analysis**: Trend detection, seasonality analysis, forecasting
- **Data Transformation**: Cleaning, scaling, encoding, feature engineering
- **SQL-like Querying**: Pandas-based query engine with familiar syntax
- **Dataset Management**: In-memory caching with automatic eviction

### Statistical Tests Supported
- T-tests (one-sample, two-sample, paired)
- Chi-square test of independence
- ANOVA (Analysis of Variance)
- Linear regression analysis
- Mann-Whitney U test (non-parametric)
- Wilcoxon signed-rank test
- Kruskal-Wallis test

### Visualization Types
- Histograms and distribution plots
- Scatter plots with correlation analysis
- Box plots and violin plots
- Heatmaps (correlation matrices)
- Line plots and time series
- Bar charts and count plots
- Pair plots for multivariate analysis
- Interactive plots with Plotly (optional)

## 📦 Installation

### Prerequisites
- Python 3.11+
- pip or conda package manager

### Install Dependencies
```bash
cd mcp-servers/python/data_analysis_server
pip install -r requirements.txt
```

### Development Installation
```bash
pip install -e .[dev]
```

## 🔧 Configuration

Copy and modify the configuration file:
```bash
cp config.yaml my_config.yaml
```

Key configuration options:
- `max_datasets`: Maximum number of datasets to keep in memory (default: 100)
- `max_memory_mb`: Maximum memory usage in MB (default: 1024)
- `plot_output_dir`: Directory for saving visualizations (default: "./plots")
- `max_query_results`: Maximum rows returned by queries (default: 10000)

## 🏃‍♂️ Usage

### Running the Server

```bash
# Run with default configuration
python -m data_analysis_server.server

# Run with custom configuration
python -m data_analysis_server.server --config my_config.yaml
```

### MCP Tools Available

#### 1. `load_dataset`
Load data from various sources and formats.

```json
{
  "source": "./data/sales.csv",
  "format": "csv",
  "dataset_id": "sales_data",
  "sample_size": 1000,
  "cache_data": true
}
```

#### 2. `analyze_dataset`
Perform comprehensive dataset analysis.

```json
{
  "dataset_id": "sales_data",
  "analysis_type": "exploratory",
  "include_distributions": true,
  "include_correlations": true,
  "include_outliers": true
}
```

#### 3. `statistical_test`
Perform statistical hypothesis testing.

```json
{
  "dataset_id": "sales_data",
  "test_type": "t_test",
  "columns": ["revenue"],
  "groupby_column": "region",
  "alpha": 0.05
}
```

#### 4. `create_visualization`
Generate statistical plots and charts.

```json
{
  "dataset_id": "sales_data",
  "plot_type": "scatter",
  "x_column": "price",
  "y_column": "quantity_sold",
  "color_column": "product_category",
  "title": "Price vs Quantity by Category"
}
```

#### 5. `transform_data`
Apply data transformations and cleaning.

```json
{
  "dataset_id": "sales_data",
  "operations": [
    {"type": "drop_na", "columns": ["price", "quantity"]},
    {"type": "scale", "columns": ["price"], "method": "standard"},
    {"type": "encode_categorical", "columns": ["category"], "method": "one_hot"}
  ]
}
```

#### 6. `time_series_analysis`
Analyze time series patterns and trends.

```json
{
  "dataset_id": "stock_data",
  "time_column": "date",
  "value_columns": ["close_price"],
  "operations": ["trend", "seasonal", "forecast"],
  "forecast_periods": 30
}
```

#### 7. `query_data`
Execute SQL-like queries on datasets.

```json
{
  "dataset_id": "sales_data",
  "query": "SELECT product_category, AVG(revenue) as avg_revenue FROM table GROUP BY product_category ORDER BY avg_revenue DESC",
  "limit": 10
}
```

## 📊 Examples

### Basic Data Analysis Workflow

```python
# 1. Load data
await mcp_client.call_tool("load_dataset", {
    "source": "./data/sales.csv",
    "format": "csv",
    "dataset_id": "sales"
})

# 2. Analyze the dataset
analysis = await mcp_client.call_tool("analyze_dataset", {
    "dataset_id": "sales",
    "analysis_type": "exploratory"
})

# 3. Create visualization
viz = await mcp_client.call_tool("create_visualization", {
    "dataset_id": "sales",
    "plot_type": "histogram",
    "x_column": "revenue"
})

# 4. Perform statistical test
test = await mcp_client.call_tool("statistical_test", {
    "dataset_id": "sales",
    "test_type": "anova",
    "columns": ["revenue"],
    "groupby_column": "region"
})
```

See the `examples/` directory for complete workflows:
- `sales_analysis.py` - Comprehensive sales data analysis
- `time_series_example.py` - Stock price time series analysis
- `statistical_testing.py` - Various statistical tests demonstration

## 🧪 Testing

Run the test suite:
```bash
pytest tests/ -v --cov=data_analysis_server
```

Run specific test categories:
```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# Performance tests
pytest tests/performance/ -v
```

## 🔒 Security Features

- **Data source validation**: URL and file path sanitization
- **Query complexity limits**: Prevents resource exhaustion
- **Memory usage monitoring**: Automatic dataset eviction
- **Safe evaluation**: Sandboxed transformation operations
- **Audit logging**: Track all data operations

## 📈 Performance Optimization

- **Chunked processing**: Handle large datasets efficiently
- **Parallel processing**: Utilize multiple CPU cores
- **Smart caching**: LRU eviction with memory limits
- **Lazy loading**: Load data on-demand
- **Vectorized operations**: NumPy and Pandas optimizations

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Install development dependencies (`pip install -e .[dev]`)
4. Make your changes and add tests
5. Run the test suite (`pytest`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Development Guidelines
- Follow PEP 8 style guidelines
- Add type hints to all functions
- Write comprehensive tests for new features
- Update documentation for API changes
- Use meaningful commit messages

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

- **Documentation**: [Link to documentation]
- **Issues**: [GitHub Issues]
- **Discussions**: [GitHub Discussions]

## 🙏 Acknowledgments

- Built on the [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol)
- Powered by scientific Python ecosystem:
  - [Pandas](https://pandas.pydata.org/) for data manipulation
  - [NumPy](https://numpy.org/) for numerical computing
  - [SciPy](https://scipy.org/) for scientific computing
  - [Matplotlib](https://matplotlib.org/) & [Seaborn](https://seaborn.pydata.org/) for visualization
  - [Scikit-learn](https://scikit-learn.org/) for machine learning
  - [Plotly](https://plotly.com/) for interactive visualizations

## 🚧 Roadmap

### Upcoming Features
- [ ] **Machine Learning Integration**
  - Automated model selection and training
  - Cross-validation and hyperparameter tuning
  - Feature importance analysis

- [ ] **Advanced Time Series**
  - ARIMA and seasonal ARIMA models
  - Exponential smoothing methods
  - Change point detection

- [ ] **Enhanced Visualizations**
  - Dashboard generation
  - Custom plot templates
  - 3D visualizations

- [ ] **Data Quality Assessment**
  - Automated data quality scoring
  - Anomaly detection algorithms
  - Data profiling reports

- [ ] **Export Capabilities**
  - Report generation (PDF, HTML)
  - Model persistence and loading
  - Integration with cloud storage

### Performance Improvements
- [ ] **Streaming Processing**
  - Support for large files that don't fit in memory
  - Incremental data processing
  - Real-time analysis capabilities

- [ ] **Distributed Computing**
  - Dask integration for parallel processing
  - Cluster deployment support
  - Horizontal scaling capabilities
