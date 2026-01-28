# MCP Data Analysis Server - Examples

This directory contains comprehensive examples demonstrating the full capabilities of the MCP Data Analysis Server. These examples showcase real-world use cases and complete data science workflows.

## 🚀 Quick Start

### Running Examples Directly
```bash
# Start with the basic sales analysis
python examples/sales_analysis.py

# Statistical analysis with customer data
python examples/statistical_analysis_example.py

# Complete data transformation pipeline
python examples/data_transformation_example.py

# Comprehensive visualization showcase
python examples/visualization_showcase_example.py

# Advanced SQL-like querying
python examples/query_operations_example.py

# Time series analysis and forecasting
python examples/time_series_example.py

# Complete end-to-end workflow (recommended)
python examples/comprehensive_workflow_example.py
```

## 📊 Available Examples

### 1. **Sales Analysis** (`sales_analysis.py`)
*Basic introduction to MCP capabilities*

- **Focus**: Core MCP tool demonstration
- **Dataset**: Sales transaction data
- **Capabilities Shown**:
  - Dataset loading and caching
  - Basic exploratory data analysis
  - Simple visualizations (scatter, bar charts)
  - SQL-like queries
  - Statistical summaries

**Best for**: First-time users wanting to understand basic MCP functionality

---

### 2. **Time Series Analysis** (`time_series_example.py`)
*Temporal data analysis and forecasting*

- **Focus**: Time-based data analysis
- **Dataset**: Stock market or time-series data
- **Capabilities Shown**:
  - Time series data loading
  - Trend and seasonality analysis
  - Stationarity testing
  - Forecasting with confidence intervals
  - Time series visualizations
  - Temporal pattern recognition

**Best for**: Financial analysis, forecasting, temporal pattern analysis

---

### 3. **Statistical Analysis** (`statistical_analysis_example.py`) ⭐
*Comprehensive statistical testing and analysis*

- **Focus**: Statistical hypothesis testing
- **Dataset**: Customer behavior data
- **Capabilities Shown**:
  - T-tests (one-sample, two-sample)
  - ANOVA (one-way, two-way)
  - Chi-square tests for independence
  - Correlation analysis
  - Distribution testing
  - Effect size calculations
  - Statistical significance interpretation

**Best for**: Research, A/B testing, experimental design, hypothesis validation

---

### 4. **Data Transformation** (`data_transformation_example.py`) ⭐
*Complete data preprocessing and feature engineering*

- **Focus**: Data cleaning and transformation pipeline
- **Dataset**: Raw employee data
- **Capabilities Shown**:
  - Missing value handling (mean, median, mode imputation)
  - Duplicate removal
  - Outlier detection and removal (IQR, Z-score)
  - Feature engineering (derived features, binning)
  - Categorical encoding (one-hot, label encoding)
  - Data scaling and normalization
  - Type conversions and column operations

**Best for**: Data preprocessing, ML pipeline preparation, data quality improvement

---

### 5. **Visualization Showcase** (`visualization_showcase_example.py`) ⭐
*Comprehensive visualization capabilities*

- **Focus**: All visualization types and formats
- **Dataset**: Marketing campaign data
- **Capabilities Shown**:
  - **Static plots** (matplotlib/seaborn): scatter, bar, histogram, box, heatmap, line
  - **Interactive plots** (plotly): 3D scatter, interactive dashboards
  - Faceted/multi-panel visualizations
  - Color mapping and styling
  - Multiple export formats (PNG, HTML)
  - Dashboard-style layouts

**Best for**: Business reporting, presentations, interactive dashboards

---

### 6. **Query Operations** (`query_operations_example.py`) ⭐
*Advanced SQL-like querying capabilities*

- **Focus**: Complex data querying and analytics
- **Dataset**: Retail transaction data
- **Capabilities Shown**:
  - SELECT with column selection
  - WHERE clauses (=, !=, >, <, IN, LIKE, NULL checks)
  - GROUP BY with aggregations (COUNT, SUM, AVG, MIN, MAX, STD)
  - ORDER BY with multiple columns
  - HAVING clauses
  - Complex nested conditions
  - CASE statements
  - Pagination (LIMIT, OFFSET)
  - Multiple output formats (JSON, CSV, HTML)

**Best for**: Business intelligence, data exploration, report generation

---

### 7. **Comprehensive Workflow** (`comprehensive_workflow_example.py`) ⭐⭐⭐
*Complete end-to-end data science pipeline*

- **Focus**: Full workflow demonstration using ALL MCP capabilities
- **Dataset**: Business sales data
- **Capabilities Shown**:
  - **Phase 1**: Data loading and exploration
  - **Phase 2**: Data cleaning and preprocessing
  - **Phase 3**: Statistical analysis and hypothesis testing
  - **Phase 4**: Time series analysis (when applicable)
  - **Phase 5**: Advanced querying and business intelligence
  - **Phase 6**: Comprehensive visualization dashboard
  - **Phase 7**: Results export and reporting

**Best for**: Complete data science projects, enterprise workflows, comprehensive analysis

---

## 🎯 Example Usage Matrix

| Use Case | Example to Run | Key Tools Used |
|----------|----------------|----------------|
| **Quick Demo** | `sales_analysis.py` | load_dataset, analyze_dataset, create_visualization |
| **Statistical Research** | `statistical_analysis_example.py` | statistical_test, analyze_dataset |
| **Data Cleaning** | `data_transformation_example.py` | transform_data |
| **Business Dashboards** | `visualization_showcase_example.py` | create_visualization |
| **Data Exploration** | `query_operations_example.py` | query_data |
| **Time Series Forecasting** | `time_series_example.py` | time_series_analysis |
| **Complete Project** | `comprehensive_workflow_example.py` | **All 7 MCP Tools** |

## 📋 Prerequisites

### Required Data Files
The examples expect sample data files in the `../sample_data/` directory:
- `sales_data.csv` - Sales transactions
- `customer_data.json` - Customer information
- `employee_data.csv` - Employee records
- `marketing_data.csv` - Marketing campaigns
- `retail_transactions.csv` - Retail data
- `stock_data.csv` - Time series data

### Server Setup
1. Ensure the MCP Data Analysis Server is running
2. Install required dependencies:
```bash
pip install -r requirements.txt
```

## 🔧 MCP Tools Demonstrated

All examples use these 7 core MCP tools:

1. **`load_dataset`** - Load data from various sources (CSV, JSON, URLs)
2. **`analyze_dataset`** - Comprehensive statistical analysis
3. **`transform_data`** - Data cleaning and feature engineering
4. **`statistical_test`** - Hypothesis testing (t-test, ANOVA, chi-square, etc.)
5. **`time_series_analysis`** - Temporal analysis and forecasting
6. **`query_data`** - SQL-like querying with complex analytics
7. **`create_visualization`** - Static and interactive plotting

## 🎨 Visualization Outputs

Examples generate visualizations in `./plots/` directory:
- **Static plots**: PNG format (matplotlib/seaborn)
- **Interactive plots**: HTML format (plotly)
- **Dashboard layouts**: Multi-panel visualizations
- **Professional styling**: Publication-ready graphics

## 📊 Query Capabilities

The query examples demonstrate:
- **Basic SQL**: SELECT, FROM, WHERE, ORDER BY
- **Aggregations**: GROUP BY with COUNT, SUM, AVG, MIN, MAX
- **Advanced**: HAVING, CASE statements, complex conditions
- **Pagination**: LIMIT and OFFSET
- **Output formats**: JSON, CSV, HTML

## 🧪 Statistical Tests

Statistical examples include:
- **T-tests**: One-sample, two-sample, paired
- **ANOVA**: One-way, two-way analysis of variance
- **Chi-square**: Independence and goodness-of-fit tests
- **Correlation**: Pearson, Spearman correlation analysis
- **Distribution**: Normality tests, distribution fitting

## 🔄 Data Transformations

Transformation examples show:
- **Cleaning**: Missing values, duplicates, outliers
- **Engineering**: New features, binning, encoding
- **Scaling**: Standard, min-max, robust scaling
- **Operations**: Rename, drop, type conversion

## 📈 Business Use Cases

These examples demonstrate solutions for:
- **Sales Analytics**: Revenue analysis, customer segmentation
- **Marketing**: Campaign performance, ROI analysis
- **HR Analytics**: Employee performance, compensation analysis
- **Financial**: Time series forecasting, risk analysis
- **Retail**: Inventory analysis, customer behavior
- **Research**: Hypothesis testing, experimental design

## 🚀 Getting Started Recommendation

**New users**: Start with `sales_analysis.py` for basic concepts

**Data Scientists**: Jump to `comprehensive_workflow_example.py` for complete pipeline

**Specific needs**: Use the matrix above to find the most relevant example

## 📞 Support

For questions or issues with examples:
1. Check the main project README
2. Review the MCP server logs
3. Ensure sample data files are properly formatted

---

*These examples demonstrate the full power of the MCP Data Analysis Server for professional data science and business analytics workflows.*
