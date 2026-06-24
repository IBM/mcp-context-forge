import yaml
from pathlib import Path
from typing import Any, Dict, List

class ConfigurationError(Exception):
    """Custom exception for configuration-related errors."""
    pass

# Define the top-level keys required in the configuration file.
REQUIRED_KEYS: List[str] = ["providers", "default_provider"]

def load_config(config_path: Path) -> Dict[str, Any]:
    """
    Loads and validates the configuration from a YAML file.

    This function ensures that the configuration file exists, is valid YAML,
    and contains all the necessary top-level keys.

    Args:
        config_path: The path to the configuration file.

    Returns:
        A dictionary containing the loaded configuration.

    Raises:
        ConfigurationError: If the config file is not found, is invalid,
                            or is missing required keys.
    """
    if not config_path.is_file():
        raise ConfigurationError(f"Configuration file not found at: {config_path}")

    try:
        with config_path.open('r') as f:
            config_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Error parsing configuration file at {config_path}: {e}") from e

    if not isinstance(config_data, dict):
        raise ConfigurationError(
            f"The configuration file at {config_path} is not a valid format. "
            "The top level should be a YAML object (a set of key-value pairs)."
        )

    # Check for missing required keys and raise a helpful error.
    for key in REQUIRED_KEYS:
        if key not in config_data:
            raise ConfigurationError(
                f"Configuration error: The required key '{key}' is missing from your config file. "
                f"Please add it to {config_path} to continue."
            )

    return config_data