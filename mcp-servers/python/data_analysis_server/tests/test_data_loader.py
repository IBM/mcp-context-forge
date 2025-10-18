# -*- coding: utf-8 -*-
"""
Unit tests for DataLoader module.
"""

# Standard
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

# Third-Party
from data_analysis_server.core.data_loader import DataLoader


class TestDataLoader:
    """Test suite for DataLoader class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.loader = DataLoader()

    def test_initialization(self):
        """Test DataLoader initialization."""
        assert self.loader.max_download_size == 500 * 1024 * 1024
        assert self.loader.timeout == 30
        assert self.loader.allowed_protocols == {"http", "https", "file"}

    def test_custom_initialization(self):
        """Test DataLoader with custom parameters."""
        loader = DataLoader(
            max_download_size_mb=100, timeout_seconds=10, allowed_protocols={"https"}
        )
        assert loader.max_download_size == 100 * 1024 * 1024
        assert loader.timeout == 10
        assert loader.allowed_protocols == {"https"}

    def test_is_url(self):
        """Test URL detection."""
        assert self.loader._is_url("https://example.com/data.csv")
        assert self.loader._is_url("http://example.com/data.csv")
        assert self.loader._is_url("file:///path/to/file.csv")
        assert not self.loader._is_url("/path/to/file.csv")
        assert not self.loader._is_url("data.csv")

    def test_get_supported_formats(self):
        """Test getting supported formats."""
        formats = DataLoader.get_supported_formats()
        expected = ["csv", "json", "parquet", "sql", "excel"]
        for fmt in expected:
            assert fmt in formats

    def test_load_csv_data(self):
        """Test loading CSV data."""
        # Create temporary CSV file
        csv_data = """name,age,city
Alice,25,New York
Bob,30,London
Carol,35,Paris"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_data)
            temp_path = f.name

        try:
            df = self.loader.load_data(temp_path, "csv")

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 3
            assert list(df.columns) == ["name", "age", "city"]
            assert df["name"].iloc[0] == "Alice"
            assert df["age"].iloc[1] == 30
        finally:
            Path(temp_path).unlink()

    def test_load_json_data(self):
        """Test loading JSON data."""
        json_data = [
            {"name": "Alice", "age": 25, "city": "New York"},
            {"name": "Bob", "age": 30, "city": "London"},
            {"name": "Carol", "age": 35, "city": "Paris"},
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(json_data, f)
            temp_path = f.name

        try:
            df = self.loader.load_data(temp_path, "json")

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 3
            assert list(df.columns) == ["name", "age", "city"]
            assert df["name"].iloc[0] == "Alice"
        finally:
            Path(temp_path).unlink()

    def test_load_data_with_sampling(self):
        """Test data loading with sampling."""
        # Create larger CSV data
        csv_data = "id,value\n" + "\n".join([f"{i},{i * 10}" for i in range(100)])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_data)
            temp_path = f.name

        try:
            df = self.loader.load_data(temp_path, "csv", sample_size=10)

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 10
            assert list(df.columns) == ["id", "value"]
        finally:
            Path(temp_path).unlink()

    def test_load_data_with_options(self):
        """Test data loading with format options."""
        csv_data = "name;age;city\nAlice;25;New York\nBob;30;London"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_data)
            temp_path = f.name

        try:
            df = self.loader.load_data(temp_path, "csv", options={"sep": ";"})

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 2
            assert list(df.columns) == ["name", "age", "city"]
        finally:
            Path(temp_path).unlink()

    def test_validate_file_path(self):
        """Test file path validation."""
        # Test with non-existent file
        with pytest.raises(FileNotFoundError):
            self.loader._validate_file_path("/non/existent/file.csv")

        # Test with existing file
        with tempfile.NamedTemporaryFile() as f:
            path = self.loader._validate_file_path(f.name)
            assert path.exists()

    def test_validate_source(self):
        """Test source validation."""
        # Test file validation
        with tempfile.NamedTemporaryFile(suffix=".csv") as f:
            result = self.loader.validate_source(f.name, "csv")
            assert result["valid"] is True
            assert result["source_type"] == "file"
            assert result["size_estimate"] is not None

        # Test non-existent file
        result = self.loader.validate_source("/non/existent/file.csv", "csv")
        assert result["valid"] is False
        assert "error" in result

    def test_unsupported_format(self):
        """Test handling of unsupported formats."""
        with tempfile.NamedTemporaryFile() as f:
            with pytest.raises(ValueError, match="Unsupported format"):
                self.loader.load_data(f.name, "unsupported_format")

    @patch("requests.get")
    def test_load_from_url(self, mock_get):
        """Test loading data from URL."""
        # Mock successful HTTP response
        mock_response = mock_get.return_value
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"content-length": "100"}
        mock_response.iter_content.return_value = [b"name,age\nAlice,25\nBob,30"]

        with patch("pandas.read_csv") as mock_read_csv:
            mock_read_csv.return_value = pd.DataFrame(
                {"name": ["Alice", "Bob"], "age": [25, 30]}
            )

            df = self.loader.load_data("https://example.com/data.csv", "csv")

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 2
            mock_get.assert_called_once()
            mock_read_csv.assert_called_once()

    @patch("requests.get")
    def test_load_from_url_size_limit(self, mock_get):
        """Test URL loading with size limit exceeded."""
        mock_response = mock_get.return_value
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"content-length": str(600 * 1024 * 1024)}  # 600MB

        with pytest.raises(ValueError, match="File too large"):
            self.loader.load_data("https://example.com/data.csv", "csv")

    def test_apply_sampling(self):
        """Test sampling functionality."""
        df = pd.DataFrame({"col1": range(100), "col2": range(100, 200)})

        # Test with sample size smaller than data
        sampled = self.loader._apply_sampling(df, 10)
        assert len(sampled) == 10

        # Test with sample size larger than data
        sampled = self.loader._apply_sampling(df, 200)
        assert len(sampled) == 100  # Should return all data

        # Test with no sampling
        sampled = self.loader._apply_sampling(df, None)
        assert len(sampled) == 100
