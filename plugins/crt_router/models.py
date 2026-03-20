# -*- coding: utf-8 -*-
"""Location: ./plugins/crt_router/models.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Pydantic models for the CRT Router calibration artifact and result schemas.

Schema overview
---------------
CalibrationArtifact   — top-level "model file" serialised to / from JSON.
  ├── primes            list of prime moduli used for residue computation.
  ├── difficulty_bins   ordered bins for classifying prompt difficulty.
  └── tools             per-tool calibration data (embeddings, priors, rates).

ToolRelevanceScore    — a single ranked result returned by CRTRouter.rank_tools(),
                        including full explainability breakdown.
"""

# Standard
from typing import Dict, List, Optional

# Third-Party
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_prime(n: int) -> bool:
    """Return True if *n* is a prime number."""
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(n**0.5) + 1, 2):
        if n % i == 0:
            return False
    return True


# ---------------------------------------------------------------------------
# Difficulty classification
# ---------------------------------------------------------------------------


class DifficultyBin(BaseModel):
    """A single difficulty classification bin.

    Bins partition the normalised difficulty score space [0, 1].  Each bin
    has a half-open interval [min_score, max_score] and a human-readable label.
    """

    bin_id: int = Field(..., ge=0, description="Zero-indexed bin identifier")
    label: str = Field(..., min_length=1, description="Human-readable label (e.g. 'easy', 'medium', 'hard')")
    min_score: float = Field(..., ge=0.0, le=1.0, description="Inclusive lower bound of this bin")
    max_score: float = Field(..., ge=0.0, le=1.0, description="Inclusive upper bound of this bin")

    @model_validator(mode="after")
    def min_must_not_exceed_max(self) -> "DifficultyBin":
        if self.min_score > self.max_score:
            raise ValueError(
                f"DifficultyBin {self.bin_id}: min_score ({self.min_score}) "
                f"must not exceed max_score ({self.max_score})"
            )
        return self


# ---------------------------------------------------------------------------
# Per-tool calibration
# ---------------------------------------------------------------------------


class ToolCalibration(BaseModel):
    """Calibration data for a single tool.

    Attributes
    ----------
    tool_name:
        Unique tool identifier.
    reference_embedding:
        Pre-computed embedding vector that represents this tool.
        Typically the embedding of the tool's name + description.
    prior:
        Prior probability weight P(tool).  Used as a multiplicative factor
        in the Bayesian posterior fusion.  Does not need to sum to 1 across
        tools — normalisation happens at ranking time.
    success_rates:
        Historical success rate per difficulty bin_id.
        Keys are bin_id integers; values are rates in [0, 1].
        Missing bins default to 0.5 at inference time.
    """

    tool_name: str = Field(..., min_length=1, description="Unique tool identifier")
    reference_embedding: List[float] = Field(
        ...,
        min_length=1,
        description="Pre-computed reference embedding vector for this tool",
    )
    prior: float = Field(
        default=1.0,
        gt=0.0,
        description="Prior probability weight P(tool); must be strictly positive",
    )
    success_rates: Dict[int, float] = Field(
        default_factory=dict,
        description="Success rate per difficulty bin_id {bin_id: rate in [0, 1]}",
    )

    @field_validator("success_rates", mode="before")
    @classmethod
    def coerce_string_keys_to_int(cls, v: object) -> Dict[int, float]:
        """JSON serialises dict keys as strings — coerce them back to int."""
        if isinstance(v, dict):
            return {int(k): float(val) for k, val in v.items()}
        return v  # type: ignore[return-value]

    @field_validator("success_rates", mode="after")
    @classmethod
    def validate_rates_in_range(cls, v: Dict[int, float]) -> Dict[int, float]:
        for bin_id, rate in v.items():
            if not 0.0 <= rate <= 1.0:
                raise ValueError(f"success_rates[{bin_id}] = {rate} is not in [0, 1]")
        return v


# ---------------------------------------------------------------------------
# Top-level calibration artifact
# ---------------------------------------------------------------------------


class CalibrationArtifact(BaseModel):
    """Full CRT calibration artifact — the serialisable 'model file'.

    Attributes
    ----------
    version:
        Schema version string for forward-compatibility checks.
    primes:
        Non-empty list of prime moduli used for CRT residue computation.
        All entries must be prime numbers.
    alpha:
        Weight of the cosine-similarity component in the relevance fusion.
        Must be in [0, 1].
    beta:
        Weight of the CRT-residue component in the relevance fusion.
        Must be in [0, 1].
    quantization_scale:
        Multiplier used to convert float embeddings to integers before
        modular arithmetic.  Default 1 000.
    difficulty_bins:
        Ordered list of difficulty bins.  May be empty (disables difficulty
        weighting — all prompts use the default success_rate of 0.5).
    tools:
        Per-tool calibration data, keyed by tool_name.
    created_at:
        ISO-8601 timestamp of when this artifact was generated.
    """

    version: str = Field(default="1.0", description="Schema version")
    primes: List[int] = Field(
        ...,
        min_length=1,
        description="Prime moduli for CRT residue computation — all entries must be prime",
    )
    alpha: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Cosine-similarity weight in [0, 1]",
    )
    beta: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="CRT-residue score weight in [0, 1]",
    )
    quantization_scale: float = Field(
        default=1000.0,
        gt=0.0,
        description="Scale factor for float→int quantization",
    )
    difficulty_bins: List[DifficultyBin] = Field(
        default_factory=list,
        description="Ordered difficulty-classification bins",
    )
    tools: Dict[str, ToolCalibration] = Field(
        default_factory=dict,
        description="Per-tool calibration data keyed by tool_name",
    )
    created_at: str = Field(
        default="",
        description="ISO-8601 creation timestamp (informational only)",
    )

    @field_validator("primes")
    @classmethod
    def all_entries_must_be_prime(cls, v: List[int]) -> List[int]:
        for p in v:
            if not _is_prime(p):
                raise ValueError(
                    f"{p} is not a prime number. "
                    "All entries in 'primes' must be prime integers."
                )
        return v


# ---------------------------------------------------------------------------
# Inference result
# ---------------------------------------------------------------------------


class ToolRelevanceScore(BaseModel):
    """A single tool's relevance score with full explainability breakdown.

    Returned by :meth:`CRTRouter.rank_tools` for each tool that meets the
    score threshold.

    Attributes
    ----------
    tool_name:
        Tool identifier, matching the key used in CalibrationArtifact.tools.
    rank:
        Final rank (1 = most relevant).
    relevance_score:
        Normalised final relevance score in [0, 1].  This is the value used
        for sorting and threshold filtering.
    cosine_similarity:
        Raw cosine similarity between the query embedding and the tool's
        reference embedding, clamped to [0, 1].
    crt_score:
        CRT residue match score in [0, 1] — weighted fraction of prime moduli
        for which the query and tool residues are identical.
    posterior_score:
        Unnormalised Bayesian posterior before normalisation.  Higher values
        indicate stronger prior × likelihood signal.
    difficulty_bin:
        Difficulty bin ID assigned to the query at inference time.
    prior:
        Tool's prior probability weight from calibration.
    """

    tool_name: str = Field(..., description="Tool identifier")
    rank: int = Field(..., ge=1, description="Final rank (1 = most relevant)")
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="Normalised relevance score in [0, 1]")
    cosine_similarity: float = Field(..., ge=0.0, le=1.0, description="Cosine similarity to query embedding")
    crt_score: float = Field(..., ge=0.0, le=1.0, description="CRT residue match score in [0, 1]")
    posterior_score: float = Field(..., ge=0.0, description="Unnormalised Bayesian posterior")
    difficulty_bin: int = Field(..., ge=0, description="Difficulty bin ID assigned to the query")
    prior: float = Field(..., gt=0.0, description="Tool prior probability weight")
