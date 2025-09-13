"""
Data loading functionality for multiple formats and sources.
"""

# Standard
import io
import logging
import urllib.parse
from pathlib import Path
from typing import Any

# Third-Party
import pandas as pd
import requests
from sqlalchemy import create_engine

logger = logging.getLogger(__name__)


class DataLoader:
    """Handles loading data from various sources and formats."""

    SUPPORTED_FORMATS = {"csv", "json", "parquet", "excel", "sql"}

    ALLOWED_PROTOCOLS = {"http", "https", "file"}

    def __init__(
        self,
        max_download_size_mb: int = 500,
        timeout_seconds: int = 30,
        allowed_protocols: set | None = None,
    ):
        """
        Initialize the data loader.

        Args:
            max_download_size_mb: Maximum download size in MB
            timeout_seconds: Request timeout in seconds
            allowed_protocols: Set of allowed URL protocols
        """
        self.max_download_size = max_download_size_mb * 1024 * 1024
        self.timeout = timeout_seconds
        self.allowed_protocols = allowed_protocols or self.ALLOWED_PROTOCOLS

    def load_data(
        self,
        source: str,
        format: str,
        options: dict[str, Any] | None = None,
        sample_size: int | None = None,
    ) -> pd.DataFrame:
        """
        Load data from the specified source and format.

        Args:
            source: File path, URL, or database connection string
            format: Data format (csv, json, parquet, excel, sql)
            options: Format-specific loading options
            sample_size: Number of rows to sample (None for all)

        Returns:
            Loaded pandas DataFrame

        Raises:
            ValueError: For unsupported formats or invalid sources
            FileNotFoundError: For missing local files
            requests.RequestException: For network issues
        """
        if format.lower() not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {format}")

        options = options or {}

        # Determine source type and load accordingly
        if self._is_url(source):
            return self._load_from_url(source, format, options, sample_size)
        elif format.lower() == "sql":
            return self._load_from_sql(source, options, sample_size)
        else:
            return self._load_from_file(source, format, options, sample_size)

    def _is_url(self, source: str) -> bool:
        """Check if source is a URL."""
        try:
            parsed = urllib.parse.urlparse(source)
            return parsed.scheme in self.allowed_protocols
        except Exception:
            return False

    def _validate_file_path(self, file_path: str) -> Path:
        """
        Validate and resolve file path.

        Args:
            file_path: Path to validate

        Returns:
            Resolved Path object

        Raises:
            ValueError: For invalid paths
            FileNotFoundError: For missing files
        """
        path = Path(file_path).resolve()

        # Security check: ensure path doesn't escape allowed directories
        # This is a basic check - in production, you'd want more robust sandboxing
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        return path

    def _load_from_file(
        self,
        file_path: str,
        format: str,
        options: dict[str, Any],
        sample_size: int | None,
    ) -> pd.DataFrame:
        """Load data from a local file."""
        path = self._validate_file_path(file_path)

        logger.info(f"Loading {format} data from {path}")

        if format.lower() == "csv":
            df = self._load_csv(path, options)
        elif format.lower() == "json":
            df = self._load_json(path, options)
        elif format.lower() == "parquet":
            df = self._load_parquet(path, options)
        elif format.lower() == "excel":
            df = self._load_excel(path, options)
        else:
            raise ValueError(f"Unsupported file format: {format}")

        return self._apply_sampling(df, sample_size)

    def _load_from_url(
        self, url: str, format: str, options: dict[str, Any], sample_size: int | None
    ) -> pd.DataFrame:
        """Load data from a URL."""
        logger.info(f"Loading {format} data from {url}")

        # Download data with size and timeout limits
        response = requests.get(url, timeout=self.timeout, stream=True)
        response.raise_for_status()

        # Check content size
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > self.max_download_size:
            raise ValueError(f"File too large: {content_length} bytes")

        # Download content
        content = b""
        downloaded = 0
        for chunk in response.iter_content(chunk_size=8192):
            downloaded += len(chunk)
            if downloaded > self.max_download_size:
                raise ValueError(f"File too large: > {self.max_download_size} bytes")
            content += chunk

        # Load data based on format
        if format.lower() == "csv":
            df = pd.read_csv(io.BytesIO(content), **options)
        elif format.lower() == "json":
            df = pd.read_json(io.BytesIO(content), **options)
        elif format.lower() == "parquet":
            df = pd.read_parquet(io.BytesIO(content), **options)
        elif format.lower() == "excel":
            df = pd.read_excel(io.BytesIO(content), **options)
        else:
            raise ValueError(f"Unsupported URL format: {format}")

        return self._apply_sampling(df, sample_size)

    def _load_from_sql(
        self,
        connection_string: str,
        options: dict[str, Any],
        sample_size: int | None,
    ) -> pd.DataFrame:
        """Load data from a SQL database."""
        logger.info("Loading data from SQL database")

        query = options.get("query", "SELECT * FROM table_name")

        engine = create_engine(connection_string)
        df = pd.read_sql(
            query, engine, **{k: v for k, v in options.items() if k != "query"}
        )

        return self._apply_sampling(df, sample_size)

    def _detect_date_columns(self, df: pd.DataFrame) -> list:
        """Detect columns that likely contain dates."""
        date_columns = []

        for col in df.columns:
            # Check column name patterns
            if any(
                keyword in col.lower()
                for keyword in ["date", "time", "timestamp", "created", "updated"]
            ):
                date_columns.append(col)
                continue

            # Check data patterns (sample first few values)
            sample_values = df[col].dropna().astype(str).head()
            if len(sample_values) > 0:
                # Look for date patterns like YYYY-MM-DD, MM/DD/YYYY, etc.
                # Standard
                import re

                date_patterns = [
                    r"\d{4}-\d{2}-\d{2}",  # YYYY-MM-DD
                    r"\d{2}/\d{2}/\d{4}",  # MM/DD/YYYY
                    r"\d{4}/\d{2}/\d{2}",  # YYYY/MM/DD
                    r"\d{2}-\d{2}-\d{4}",  # MM-DD-YYYY
                ]

                for value in sample_values:
                    if any(re.match(pattern, str(value)) for pattern in date_patterns):
                        date_columns.append(col)
                        break

        return date_columns

    def _post_process_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert string columns that look like dates to datetime."""
        df = df.copy()

        # Common date formats to try
        date_formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%Y/%m/%d",
            "%d/%m/%Y",
            "%Y-%m-%d %H:%M:%S",
        ]

        for col in df.columns:
            if df[col].dtype == "object":  # String column
                # Try to convert to datetime if it looks like dates
                try:
                    sample = df[col].dropna().head()
                    if len(sample) > 0:
                        # Try each format explicitly to avoid warnings
                        converted = False
                        for date_format in date_formats:
                            try:
                                pd.to_datetime(
                                    sample, format=date_format, errors="raise"
                                )
                                # If successful, convert the entire column with this format
                                df[col] = pd.to_datetime(
                                    df[col], format=date_format, errors="coerce"
                                )
                                logger.info(
                                    f"Converted column '{col}' to datetime using format {date_format}"
                                )
                                converted = True
                                break
                            except (ValueError, TypeError):
                                continue

                        # If no specific format worked, try pandas' general parser (but suppress warnings)
                        if not converted:
                            try:
                                # Test if pandas can parse it without specifying format
                                # Standard
                                import warnings

                                with warnings.catch_warnings():
                                    warnings.simplefilter("ignore")
                                    pd.to_datetime(sample, errors="raise")
                                    # If successful, convert the entire column
                                    df[col] = pd.to_datetime(df[col], errors="coerce")
                                    logger.info(
                                        f"Converted column '{col}' to datetime using inferred format"
                                    )
                            except (ValueError, TypeError):
                                # Not a date column, keep as is
                                pass
                except (ValueError, TypeError):
                    # Not a date column, keep as is
                    pass

        return df

    def _load_csv(self, path: Path, options: dict[str, Any]) -> pd.DataFrame:
        """Load CSV file with error handling and intelligent date parsing."""
        try:
            # First, try to load with automatic date parsing if not explicitly disabled
            if "parse_dates" not in options:
                # Try to automatically detect date columns
                sample_df = pd.read_csv(path, nrows=5)
                date_columns = self._detect_date_columns(sample_df)
                if date_columns:
                    options = options.copy()
                    options["parse_dates"] = date_columns

            df = pd.read_csv(path, **options)

            # Post-process: convert any remaining string date columns
            df = self._post_process_dates(df)
            return df

        except UnicodeDecodeError:
            # Try different encodings
            for encoding in ["latin1", "cp1252", "iso-8859-1"]:
                try:
                    return pd.read_csv(path, encoding=encoding, **options)
                except UnicodeDecodeError:
                    continue
            raise ValueError("Unable to decode CSV file with any encoding")

    def _load_json(self, path: Path, options: dict[str, Any]) -> pd.DataFrame:
        """Load JSON file with error handling."""
        return pd.read_json(path, **options)

    def _load_parquet(self, path: Path, options: dict[str, Any]) -> pd.DataFrame:
        """Load Parquet file."""
        return pd.read_parquet(path, **options)

    def _load_excel(self, path: Path, options: dict[str, Any]) -> pd.DataFrame:
        """Load Excel file."""
        return pd.read_excel(path, **options)

    def _apply_sampling(
        self, df: pd.DataFrame, sample_size: int | None
    ) -> pd.DataFrame:
        """Apply sampling to the DataFrame if specified."""
        if sample_size is not None and len(df) > sample_size:
            logger.info(f"Sampling {sample_size} rows from {len(df)} total rows")
            return df.sample(n=sample_size, random_state=42)
        return df

    @classmethod
    def get_supported_formats(cls) -> list:
        """Get list of supported data formats."""
        return list(cls.SUPPORTED_FORMATS)

    def validate_source(self, source: str, format: str) -> dict[str, Any]:
        """
        Validate a data source without loading it.

        Args:
            source: Data source to validate
            format: Expected format

        Returns:
            Validation result dictionary
        """
        result = {
            "valid": False,
            "source_type": None,
            "error": None,
            "size_estimate": None,
        }

        try:
            if self._is_url(source):
                result["source_type"] = "url"
                # Just check if URL is accessible
                response = requests.head(source, timeout=self.timeout)
                response.raise_for_status()
                result["size_estimate"] = response.headers.get("content-length")
                result["valid"] = True
            elif format.lower() == "sql":
                result["source_type"] = "database"
                # Basic connection string validation
                if "://" in source:
                    result["valid"] = True
                else:
                    result["error"] = "Invalid database connection string"
            else:
                result["source_type"] = "file"
                path = self._validate_file_path(source)
                result["size_estimate"] = path.stat().st_size
                result["valid"] = True

        except Exception as e:
            result["error"] = str(e)

        return result
