# -*- coding: utf-8 -*-
import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_core import ValidationError

logger = logging.getLogger(__name__)
CONFIG_PATH = Path(__file__).parent / "config.yaml"


class QRGenerationConfig(BaseModel):
    default_size: int = Field(default=10)
    default_border: int = Field(default=4)
    default_error_correction: Literal["L", "M", "Q", "H"] = Field(default="M")
    max_data_length: int = Field(default=4296)
    supported_formats: list[str] = Field(default_factory=lambda: ["png", "svg", "ascii"])


class OutputConfig(BaseModel):
    default_directory: str = Field(default="./output/")
    max_batch_size: int = Field(default=100)
    enable_zip_export: bool = Field(default=True)


class DecodingConfig(BaseModel):
    preprocessing_enabled: bool = Field(default=True)
    max_image_size: str = Field(default="10MB")
    supported_image_formats: list[str] = Field(
        default_factory=lambda: ["png", "jpg", "jpeg", "gif", "bmp", "tiff"]
    )


class PerformanceConfig(BaseModel):
    max_concurrent_requests: int = Field(default=10)


class ConfigModel(BaseModel):
    qr_generation: QRGenerationConfig = Field(default_factory=QRGenerationConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    decoding: DecodingConfig = Field(default_factory=DecodingConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)


def load_config() -> ConfigModel:
    if not CONFIG_PATH.exists():
        logger.info("No config at %s; using defaults", CONFIG_PATH)
        return ConfigModel()

    try:
        with open(CONFIG_PATH) as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read YAML config %s: %s", CONFIG_PATH, e)
        raise

    try:
        cfg = ConfigModel(**raw)
        logger.info("Loaded configuration from %s", CONFIG_PATH)
        return cfg
    except ValidationError as exc:
        logger.error("Invalid configuration in %s: %s", CONFIG_PATH, exc)
        raise


# Load once at import time (intentional)
config = load_config()
