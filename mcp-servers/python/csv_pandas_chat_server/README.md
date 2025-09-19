# CSV Pandas Chat MCP Server

> Author: Mihai Criveti

A secure MCP server for analyzing CSV data using natural language queries. Integrates with OpenAI models to generate and execute safe pandas code for data analysis. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **Natural Language Queries**: Ask questions about your CSV data in plain English
- **Secure Code Execution**: Safe pandas code generation and execution with multiple security layers
- **Multiple Data Sources**: Support CSV content, URLs, and local files
- **Comprehensive Analysis**: Get detailed information and automated analysis of CSV data
- **OpenAI Integration**: Uses OpenAI models (GPT-3.5-turbo, GPT-4, etc.) for intelligent code generation
- **Security First**: Multiple layers of input validation, code sanitization, and execution sandboxing
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Security Measures

1. **Input Validation**: Sanitizes user queries and validates all inputs
2. **Code Sanitization**: Blocks dangerous operations and restricts to safe pandas/numpy functions
3. **Execution Sandboxing**: Restricted execution environment with timeout protection
4. **File Size Limits**: Prevents resource exhaustion with configurable size limits
5. **Memory Management**: Monitors and restricts dataframe memory usage
6. **Safe Imports**: Only allows pre-approved libraries (pandas, numpy)

## Tools

- `chat_with_csv` - Chat with CSV data using natural language queries
- `get_csv_info` - Get comprehensive information about CSV data structure
- `analyze_csv` - Perform automated analysis (basic, detailed, statistical)

## Requirements

- **Python 3.11+**
- **OpenAI API Key**: Required for AI-powered code generation
- **Dependencies**: pandas, numpy, requests, openai, pydantic, MCP

## Installation

```bash
# Install in development mode
make dev-install

# Or install normally
make install
```

## Configuration

Set environment variables for customization:

```bash
export OPENAI_API_KEY="your-openai-api-key"
export CSV_CHAT_MAX_INPUT_LENGTH=1000        # Max query length
export CSV_CHAT_MAX_FILE_SIZE=20971520       # Max file size (20MB)
export CSV_CHAT_MAX_DATAFRAME_ROWS=100000    # Max dataframe rows
export CSV_CHAT_MAX_DATAFRAME_COLS=100       # Max dataframe columns
export CSV_CHAT_EXECUTION_TIMEOUT=30         # Code execution timeout (seconds)
export CSV_CHAT_MAX_RETRIES=3                # Max retries for code generation
```

## Usage

### Running the FastMCP Server

```bash
# Start the server
make dev

# Or directly
python -m csv_pandas_chat_server.server_fastmcp
```

### HTTP Bridge

Expose the server over HTTP for REST API access:

```bash
make serve-http
```

### MCP Client Configuration

```json
{
  "mcpServers": {
    "csv-pandas-chat": {
      "command": "python",
      "args": ["-m", "csv_pandas_chat_server.server_fastmcp"],
      "cwd": "/path/to/csv_pandas_chat_server"
    }
  }
}
```

## Examples

### Chat with CSV Data

```python
{
  "name": "chat_with_csv",
  "arguments": {
    "query": "What are the top 5 products by sales?",
    "csv_content": "product,sales,region\nWidget A,1000,North\nWidget B,1500,South\nGadget X,800,East",
    "openai_api_key": "your-api-key",
    "model": "gpt-3.5-turbo"
  }
}
```

### Analyze CSV from URL

```python
{
  "name": "analyze_csv",
  "arguments": {
    "file_url": "https://example.com/data.csv",
    "analysis_type": "detailed"
  }
}
```

### Get CSV Information

```python
{
  "name": "get_csv_info",
  "arguments": {
    "file_path": "./sales_data.csv"
  }
}
```

### Complex Query Examples

#### Sales Analysis
```python
{
  "name": "chat_with_csv",
  "arguments": {
    "query": "Calculate the monthly growth rate for each product category and show which category has the highest average growth",
    "file_path": "./monthly_sales.csv"
  }
}
```

#### Data Quality Check
```python
{
  "name": "chat_with_csv",
  "arguments": {
    "query": "Find all rows with missing values and show the percentage of missing data for each column",
    "csv_content": "name,age,city,salary\nJohn,25,NYC,50000\nJane,,Boston,\nBob,30,LA,60000"
  }
}
```

#### Statistical Analysis
```python
{
  "name": "chat_with_csv",
  "arguments": {
    "query": "Calculate correlation between price and sales volume, and identify any outliers",
    "file_url": "https://example.com/product_data.csv"
  }
}
```

## Response Format

### Successful Chat Response
```json
{
  "success": true,
  "invocation_id": "uuid-here",
  "query": "What are the top 5 products by sales?",
  "explanation": "This code sorts the dataframe by sales column in descending order and selects the top 5 rows",
  "generated_code": "result = df.nlargest(5, 'sales')[['product', 'sales']]",
  "result": "   product  sales\n0  Widget B   1500\n1  Widget A   1000\n2  Gadget X    800",
  "dataframe_shape": [3, 3]
}
```

### CSV Info Response
```json
{
  "success": true,
  "shape": [1000, 5],
  "columns": ["product", "sales", "region", "date", "category"],
  "dtypes": {"product": "object", "sales": "int64", "region": "object"},
  "missing_values": {"product": 0, "sales": 2, "region": 0},
  "sample_data": [{"product": "Widget A", "sales": 1000, "region": "North"}],
  "numeric_summary": {"sales": {"mean": 1200.5, "std": 450.2}},
  "unique_value_counts": {"region": 4, "category": 8}
}
```

## Supported Query Types

- **Filtering**: "Show all products with sales > 1000"
- **Aggregation**: "Calculate average sales by region"
- **Sorting**: "Sort by date and show top 10"
- **Grouping**: "Group by category and sum sales"
- **Statistical**: "Calculate correlation between price and quantity"
- **Data Quality**: "Find missing values and duplicates"
- **Transformations**: "Create a new column with profit margin"
- **Visualization Data**: "Prepare data for a bar chart of sales by month"

## Safety Features

### Input Sanitization
- Removes potentially harmful characters
- Validates query length and complexity
- Checks for injection attempts

### Code Generation Safety
- Uses OpenAI with specific prompts to generate safe pandas code
- Validates generated code against security rules
- Blocks dangerous operations and imports

### Execution Environment
- Restricted global namespace with only safe functions
- Timeout protection to prevent infinite loops
- Memory usage monitoring
- Copy of dataframe to prevent modification

### Error Handling
- Graceful handling of all error conditions
- Detailed logging for debugging
- Generic error messages to users to prevent information leakage

## FastMCP Advantages

The FastMCP implementation provides:

1. **Type-Safe Parameters**: Automatic validation using Pydantic Field constraints
2. **Pattern Validation**: Ensures analysis_type is one of "basic", "detailed", or "statistical"
3. **Cleaner Code**: Decorator-based tool definitions (`@mcp.tool`)
4. **Better Error Handling**: Built-in exception management
5. **Automatic Schema Generation**: No manual JSON schema definitions

## Development

```bash
# Format code
make format

# Run tests
make test

# Lint code
make lint
```

## Testing

The server includes comprehensive tests covering:
- Tool listing and validation
- CSV loading from various sources
- Code generation and execution
- Security measures and edge cases
- Error handling scenarios

## Performance Considerations

- Configurable limits for file size and dataframe dimensions
- Efficient memory usage with data copying only when necessary
- Timeout protection for both AI calls and code execution
- Streaming file downloads with size checking

## Limitations

- Requires OpenAI API key for natural language processing
- Limited to pandas and numpy operations for security
- File size and dataframe size restrictions for performance
- Code execution timeout to prevent long-running operations

## Security Recommendations

1. **Run in isolated container** with read-only filesystem
2. **Set strict resource limits** for CPU and memory
3. **Monitor execution logs** for suspicious activity
4. **Use dedicated OpenAI API key** with usage limits
5. **Regularly update dependencies** for security patches
