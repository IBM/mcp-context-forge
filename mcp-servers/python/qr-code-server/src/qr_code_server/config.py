import logging
from pydantic import BaseModel, Field
from typing import List
from pydantic_core import ValidationError
import yaml
from pathlib import Path


logger = logging.getLogger(__name__)
CONFIG_PATH = Path(__file__).parent / "config.yaml"


class QRGenerationConfig(BaseModel):
    default_size: int = Field(default=10)
    default_border: int = Field(default=4)
    default_error_correction: str = Field(default="M")
    max_data_length: int = Field(default=4296)
    supported_formats: List[str] = Field(default_factory=lambda: ["png", "svg", "ascii"])


class OutputConfig(BaseModel):
    default_directory: str = Field(default="./output/")
    max_batch_size: int = Field(default=100)
    enable_zip_export: bool = Field(default=True)


class DecodingConfig(BaseModel):
    preprocessing_enabled: bool = Field(default=True)
    max_image_size: str = Field(default="10MB")
    supported_image_formats: List[str] = Field(default_factory=lambda: ["png", "jpg", "jpeg", "gif", "bmp", "tiff"])


class PerformanceConfig(BaseModel):
    cache_generated_codes: bool = Field(default=False)
    max_concurrent_requests: int = Field(default=10)


class ConfigModel(BaseModel):
    qr_generation: QRGenerationConfig
    output: OutputConfig
    decoding: DecodingConfig
    performance: PerformanceConfig


def load_config() -> ConfigModel:

    if not CONFIG_PATH.exists():
        logger.info("No config at %s; using defaults", CONFIG_PATH)
        return ConfigModel()
    try:
        with open(CONFIG_PATH, "r") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read YAML config %s: %s", CONFIG_PATH, e)
        raise

    try:
        cfg = ConfigModel(**raw)
        logger.info("Loaded configuration from %s", CONFIG_PATH)
    except ValidationError as exc:
        logger.error("Invalid configuration in %s: %s", CONFIG_PATH, exc)
        raise

    return cfg
