# -*- coding: utf-8 -*-
"""Location: ./plugins/crt_router/semantic_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

CRT Inference Engine for Semantic Tool Selection.

Algorithm overview
------------------
The Chinese Remainder Theorem (CRT) residue approach works as follows:

  1. **Quantise** the floating-point embedding into an integer vector:
         q_int[i] = round(embedding[i] * scale)

  2. **Compute residues** for each prime p_k using a seeded deterministic
     projection (avoids collisions from simply summing the quantised values):
         residue_k = |dot(w_k, q_int mod p_k)| mod p_k
     where w_k is a fixed pseudo-random integer weight vector seeded by p_k.

  3. **CRT score** — weighted fraction of residues that match between query
     and tool.  Larger primes contribute more weight because a residue match
     mod a large prime is stronger evidence of similarity:
         crt_score = sum(p_k / total_p  if  r_query_k == r_tool_k) for k

  4. **Posterior fusion** — Bayesian combination of cosine similarity and CRT
     score, weighted by calibrated priors and per-difficulty success rates:
         likelihood = alpha * cos_sim + beta * crt_score
         posterior  = prior * success_rate(difficulty_bin) * likelihood

  5. **Normalise & rank** — divide each posterior by the maximum, apply the
     threshold, truncate to top-k, and assign final integer ranks.

All computation is strictly numerical — no LLM calls, no external API calls.
"""

# Standard
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Third-Party
import numpy as np

# First-Party
from plugins.crt_router.models import (
    CalibrationArtifact,
    ToolCalibration,
    ToolRelevanceScore,
)

logger = logging.getLogger(__name__)

# Default primes used when constructing a router without a calibration file.
DEFAULT_PRIMES: List[int] = [7, 11, 13, 17, 19, 23]


class CRTRouter:
    """Deterministic semantic tool router using CRT residue arithmetic.

    Parameters
    ----------
    calibration:
        A fully validated :class:`CalibrationArtifact` instance.  Residues
        for all calibrated tools are pre-computed in ``__init__`` so that
        repeated ``rank_tools`` calls pay zero initialisation overhead.

    Examples
    --------
    Build from pre-computed tool embeddings (no calibration file needed)::

        router = CRTRouter.from_tool_embeddings(
            {"weather_api": [0.1, 0.9, ...], "db_query": [0.8, 0.2, ...]}
        )
        scores = router.rank_tools(prompt_embedding=query_vec, k=5)

    Load from a persisted JSON calibration file::

        router = CRTRouter.from_json("calibration.json")
        scores = router.rank_tools(prompt_embedding=query_vec, k=10, threshold=0.2)
    """

    def __init__(self, calibration: CalibrationArtifact) -> None:
        self._calibration = calibration
        self._primes: List[int] = calibration.primes
        self._alpha: float = calibration.alpha
        self._beta: float = calibration.beta
        self._scale: float = calibration.quantization_scale

        # Pre-compute CRT residues for every calibrated tool so rank_tools()
        # only needs to compute them once for the query at inference time.
        self._tool_residues: Dict[str, List[int]] = {
            name: self._compute_residues(tc.reference_embedding)
            for name, tc in calibration.tools.items()
        }

        logger.info(
            "CRTRouter initialised: %d tools, primes=%s, alpha=%.2f, beta=%.2f",
            len(calibration.tools),
            self._primes,
            self._alpha,
            self._beta,
        )

    # ------------------------------------------------------------------
    # Factory constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "CRTRouter":
        """Load a :class:`CalibrationArtifact` from a JSON file and return a router.

        Parameters
        ----------
        path:
            Filesystem path to the calibration JSON file.

        Raises
        ------
        FileNotFoundError:
            If *path* does not exist.
        ValueError:
            If the file content is not valid JSON or fails Pydantic validation.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Calibration file not found: {path}")
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in calibration file {path}: {exc}") from exc

        artifact = CalibrationArtifact.model_validate(data)
        return cls(artifact)

    @classmethod
    def from_tool_embeddings(
        cls,
        tool_embeddings: Dict[str, List[float]],
        primes: Optional[List[int]] = None,
        alpha: float = 0.6,
        beta: float = 0.4,
        quantization_scale: float = 1000.0,
    ) -> "CRTRouter":
        """Build a router directly from a ``{tool_name: embedding}`` mapping.

        Useful for bootstrapping without a pre-computed calibration file.
        All tools receive a uniform prior and no difficulty-based weighting.

        Parameters
        ----------
        tool_embeddings:
            Mapping of tool names to their reference embedding vectors.
        primes:
            Prime moduli to use.  Defaults to :data:`DEFAULT_PRIMES`.
        alpha:
            Cosine-similarity weight.
        beta:
            CRT-residue score weight.
        quantization_scale:
            Scale factor for float→int quantization.
        """
        primes = primes or DEFAULT_PRIMES
        n = len(tool_embeddings)
        uniform_prior = 1.0 / max(n, 1)

        tools = {
            name: ToolCalibration(
                tool_name=name,
                reference_embedding=emb,
                prior=uniform_prior,
                success_rates={},
            )
            for name, emb in tool_embeddings.items()
        }

        artifact = CalibrationArtifact(
            primes=primes,
            alpha=alpha,
            beta=beta,
            quantization_scale=quantization_scale,
            tools=tools,
        )
        return cls(artifact)

    # ------------------------------------------------------------------
    # Public inference API
    # ------------------------------------------------------------------

    def rank_tools(
        self,
        prompt_embedding: List[float],
        available_tools: Optional[List[str]] = None,
        k: int = 10,
        threshold: float = 0.0,
    ) -> List[ToolRelevanceScore]:
        """Rank calibrated tools by relevance to a query embedding.

        This method is **synchronous and deterministic** — given the same
        inputs it always produces the same output with no external calls.

        Parameters
        ----------
        prompt_embedding:
            Pre-computed embedding vector for the natural-language query.
            The caller is responsible for generating this (e.g. via
            :meth:`EmbeddingService.embed_query`).
        available_tools:
            Optional whitelist of tool names to rank.  Tools not present in
            the calibration artifact are silently skipped.  Pass ``None`` to
            rank every calibrated tool.
        k:
            Maximum number of results to return (must be ≥ 1).
        threshold:
            Minimum normalised relevance score in [0.0, 1.0].  Results with
            ``relevance_score < threshold`` are excluded.

        Returns
        -------
        List[ToolRelevanceScore]
            Tools sorted by ``relevance_score`` descending, at most *k*
            items, all with ``relevance_score >= threshold``.  Each item
            contains a full explainability breakdown.

        Raises
        ------
        ValueError:
            If *prompt_embedding* is empty, *k* < 1, or *threshold* outside
            [0.0, 1.0].
        """
        if not prompt_embedding:
            raise ValueError("prompt_embedding must be non-empty")
        if k < 1:
            raise ValueError(f"k must be at least 1, got {k}")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be in [0.0, 1.0], got {threshold}")

        # Resolve which tools to consider.
        if available_tools is not None:
            # Deduplicate while preserving order, skip uncalibrated names.
            seen: set = set()
            tool_names: List[str] = []
            for name in available_tools:
                if name not in seen:
                    seen.add(name)
                    if name in self._calibration.tools:
                        tool_names.append(name)
                    else:
                        logger.debug("Tool %r not in calibration — skipping", name)
        else:
            tool_names = list(self._calibration.tools.keys())

        if not tool_names:
            logger.warning("No calibrated tools available for ranking")
            return []

        # Classify prompt difficulty (deterministic, no external calls).
        difficulty_bin = self._classify_difficulty(prompt_embedding)

        # Compute query residues once for this call.
        query_residues = self._compute_residues(prompt_embedding)

        # Score every candidate tool.
        raw: List[Dict[str, Any]] = []
        for name in tool_names:
            tool_cal = self._calibration.tools[name]

            cos_sim = self._cosine_similarity(prompt_embedding, tool_cal.reference_embedding)
            tool_residues = self._tool_residues.get(name) or self._compute_residues(tool_cal.reference_embedding)
            crt_score = self._compute_crt_score(query_residues, tool_residues)
            posterior = self._fuse_posteriors(
                tool_cal=tool_cal,
                cos_sim=cos_sim,
                crt_score=crt_score,
                difficulty_bin=difficulty_bin,
            )

            raw.append(
                {
                    "tool_name": name,
                    "cosine_similarity": cos_sim,
                    "crt_score": crt_score,
                    "posterior_score": posterior,
                    "difficulty_bin": difficulty_bin,
                    "prior": tool_cal.prior,
                }
            )

        # Normalise posteriors to [0, 1].
        max_posterior = max((e["posterior_score"] for e in raw), default=1.0)
        if max_posterior <= 0.0:
            max_posterior = 1.0

        # Collect candidates with their normalised relevance score as plain dicts;
        # ToolRelevanceScore requires rank >= 1 so we only construct it once we
        # know the final rank after sorting and truncation.
        candidates: List[Dict[str, Any]] = []
        for entry in raw:
            relevance = entry["posterior_score"] / max_posterior
            relevance = max(0.0, min(1.0, relevance))
            if relevance >= threshold:
                candidates.append({**entry, "relevance_score": relevance})

        # Sort descending by relevance, truncate to k, then assign ranks.
        candidates.sort(key=lambda c: c["relevance_score"], reverse=True)
        candidates = candidates[:k]

        results: List[ToolRelevanceScore] = [
            ToolRelevanceScore(
                tool_name=c["tool_name"],
                rank=i + 1,
                relevance_score=c["relevance_score"],
                cosine_similarity=c["cosine_similarity"],
                crt_score=c["crt_score"],
                posterior_score=c["posterior_score"],
                difficulty_bin=c["difficulty_bin"],
                prior=c["prior"],
            )
            for i, c in enumerate(candidates)
        ]

        logger.debug(
            "rank_tools: %d tools scored, %d returned (k=%d, threshold=%.3f)",
            len(raw),
            len(results),
            k,
            threshold,
        )
        return results

    # ------------------------------------------------------------------
    # Core numerical primitives
    # ------------------------------------------------------------------

    def _compute_residues(self, embedding: List[float]) -> List[int]:
        """Compute a CRT residue vector for *embedding*.

        For each prime ``p_k`` a deterministic integer projection is computed
        using a seeded pseudo-random weight vector, giving one residue per
        prime.  The seed is ``p_k * 31 + k`` — a simple but collision-resistant
        choice that is cheap to reproduce.

        Parameters
        ----------
        embedding:
            Float embedding vector (any length ≥ 1).

        Returns
        -------
        List[int]
            One integer residue in ``[0, p_k)`` per prime.
        """
        vec = np.asarray(embedding, dtype=np.float64)
        dim = len(vec)
        quantized = np.round(vec * self._scale).astype(np.int64)

        residues: List[int] = []
        for k, prime in enumerate(self._primes):
            rng = np.random.RandomState(seed=prime * 31 + k)
            weights = rng.randint(1, prime, size=dim, dtype=np.int64)
            # Work modulo prime before the dot product to prevent overflow.
            dot = int(np.dot(weights, quantized % prime))
            residues.append(abs(dot) % prime)

        return residues

    def _compute_crt_score(
        self,
        query_residues: List[int],
        tool_residues: List[int],
    ) -> float:
        """Compute a CRT-based similarity score in [0, 1].

        For each prime p_k, a residue match (query_residue == tool_residue)
        contributes ``p_k / total_p`` to the score.  Larger primes carry more
        weight because a coincidental match modulo a large prime is much less
        likely than modulo a small prime.

        Parameters
        ----------
        query_residues:
            Residues for the query embedding.
        tool_residues:
            Pre-computed residues for a tool's reference embedding.

        Returns
        -------
        float
            Score in [0.0, 1.0].
        """
        if not query_residues or not tool_residues:
            return 0.0

        total_weight = sum(self._primes) or 1
        score = 0.0
        for prime, qr, tr in zip(self._primes, query_residues, tool_residues):
            if qr == tr:
                score += prime / total_weight
        return float(score)

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Cosine similarity between two vectors, clamped to [0, 1].

        Returns 0.0 whenever either vector is the zero vector (undefined
        cosine similarity is treated as no match).
        """
        a = np.asarray(vec_a, dtype=np.float64)
        b = np.asarray(vec_b, dtype=np.float64)
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        raw = float(np.dot(a, b) / (norm_a * norm_b))
        return max(0.0, min(1.0, raw))

    def _classify_difficulty(self, embedding: List[float]) -> int:
        """Map an embedding to a difficulty bin ID.

        Uses the L2 norm of the embedding as a proxy for prompt richness /
        difficulty.  The norm is normalised to [0, 1] via tanh so that the
        classification is always bounded regardless of embedding scale.

        Falls back to bin 0 when no bins are defined in the calibration.

        Parameters
        ----------
        embedding:
            Query embedding vector.

        Returns
        -------
        int
            Bin ID of the matched difficulty bin.
        """
        if not self._calibration.difficulty_bins:
            return 0

        norm = float(np.linalg.norm(np.asarray(embedding, dtype=np.float64)))
        normalised = math.tanh(norm)

        for bin_def in sorted(self._calibration.difficulty_bins, key=lambda b: b.bin_id):
            if bin_def.min_score <= normalised <= bin_def.max_score:
                return bin_def.bin_id

        # Embedding magnitude beyond all bin boundaries → assign last bin.
        last_bin = max(self._calibration.difficulty_bins, key=lambda b: b.bin_id)
        return last_bin.bin_id

    def _fuse_posteriors(
        self,
        tool_cal: ToolCalibration,
        cos_sim: float,
        crt_score: float,
        difficulty_bin: int,
    ) -> float:
        """Compute the unnormalised Bayesian posterior for one tool.

        ``posterior = prior × success_rate(bin) × (α·cos_sim + β·crt_score)``

        When no success_rate has been calibrated for *difficulty_bin*, a
        neutral rate of 0.5 is assumed (neither promoting nor demoting the tool).

        Parameters
        ----------
        tool_cal:
            Calibration entry for the tool being scored.
        cos_sim:
            Cosine similarity between query and tool reference embedding.
        crt_score:
            CRT residue match score.
        difficulty_bin:
            Difficulty bin ID for the current query.

        Returns
        -------
        float
            Unnormalised posterior (≥ 0).
        """
        success_rate = tool_cal.success_rates.get(difficulty_bin, 0.5)
        likelihood = self._alpha * cos_sim + self._beta * crt_score
        return tool_cal.prior * success_rate * likelihood

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_json(self, path: Union[str, Path]) -> None:
        """Persist the calibration artifact to *path* as JSON.

        Parent directories are created if they do not exist.

        Parameters
        ----------
        path:
            Target file path (``*.json`` recommended).
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(self._calibration.model_dump(), fh, indent=2)
        logger.info("CRT calibration artifact saved to %s", path)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def calibration(self) -> CalibrationArtifact:
        """The loaded :class:`CalibrationArtifact` (read-only view)."""
        return self._calibration

    @property
    def tool_names(self) -> List[str]:
        """Names of all tools present in the calibration artifact."""
        return list(self._calibration.tools.keys())

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"CRTRouter(tools={len(self._calibration.tools)}, "
            f"primes={self._primes}, alpha={self._alpha}, beta={self._beta})"
        )
