# -*- coding: utf-8 -*-
"""
Pytest configuration and shared fixtures for tests.
"""

# Standard
from pathlib import Path
import tempfile

# Third-Party
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_dataframe():
    """Create a sample DataFrame for testing."""
    np.random.seed(42)
    return pd.DataFrame(
        {
            "id": range(1, 101),
            "name": [f"Person_{i}" for i in range(1, 101)],
            "age": np.random.randint(18, 80, 100),
            "income": np.random.normal(50000, 15000, 100),
            "category": np.random.choice(["A", "B", "C"], 100),
            "score": np.random.uniform(0, 100, 100),
            "date": pd.date_range("2023-01-01", periods=100, freq="D"),
            "active": np.random.choice([True, False], 100),
        }
    )


@pytest.fixture
def sample_csv_file(sample_dataframe):
    """Create a temporary CSV file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        sample_dataframe.to_csv(f.name, index=False)
        yield f.name
    Path(f.name).unlink()


@pytest.fixture
def sample_json_file(sample_dataframe):
    """Create a temporary JSON file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        sample_dataframe.to_json(f.name, orient="records")
        yield f.name
    Path(f.name).unlink()


@pytest.fixture
def time_series_dataframe():
    """Create a sample time series DataFrame."""
    dates = pd.date_range("2023-01-01", periods=365, freq="D")
    np.random.seed(42)

    # Create trend component
    trend = np.linspace(100, 120, 365)

    # Create seasonal component (yearly)
    seasonal = 10 * np.sin(2 * np.pi * np.arange(365) / 365)

    # Create noise
    noise = np.random.normal(0, 5, 365)

    # Combine components
    values = trend + seasonal + noise

    return pd.DataFrame(
        {
            "date": dates,
            "value": values,
            "category": np.random.choice(["A", "B", "C"], 365),
        }
    )


@pytest.fixture
def stock_dataframe():
    """Create a sample stock price DataFrame."""
    dates = pd.date_range("2023-01-01", periods=252, freq="B")  # Business days
    np.random.seed(42)

    symbols = ["AAPL", "GOOGL", "MSFT", "TSLA"]
    data = []

    for symbol in symbols:
        # Generate random walk for stock prices
        returns = np.random.normal(0.001, 0.02, len(dates))
        prices = 100 * np.cumprod(1 + returns)

        for i, (date, price) in enumerate(zip(dates, prices, strict=False)):
            # Add some randomness to high/low
            high = price * np.random.uniform(1.01, 1.05)
            low = price * np.random.uniform(0.95, 0.99)
            open_price = price * np.random.uniform(0.98, 1.02)
            volume = np.random.randint(1000000, 10000000)

            data.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": price,
                    "volume": volume,
                }
            )

    return pd.DataFrame(data)


@pytest.fixture
def temp_directory():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def config_dict():
    """Return a test configuration dictionary."""
    return {
        "max_datasets": 10,
        "max_memory_mb": 100,
        "max_download_size_mb": 50,
        "timeout_seconds": 10,
        "plot_output_dir": "./test_plots",
        "plot_style": "default",
        "max_query_results": 1000,
    }
