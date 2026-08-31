# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/judges/rule_judge.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Rule-based judge for deterministic evaluations.
"""

# Standard
import re
from typing import Any, Dict, List, Optional

# Third-Party
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import textstat

# Local
from .base_judge import (
    BaseJudge,
    EvaluationCriteria,
    EvaluationResult,
    EvaluationRubric,
    PairwiseResult,
    RankingResult,
    ReferenceEvaluationResult,
)


class RuleBasedJudge(BaseJudge):
    """Judge implementation using rule-based metrics."""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize rule-based judge.

        Args:
            config: Configuration dictionary
        """
        super().__init__(config)

        # Initialize TF-IDF vectorizer for semantic similarity
        self.vectorizer = TfidfVectorizer(max_features=10000, stop_words="english", ngram_range=(1, 2), lowercase=True)

    async def evaluate_response(
        self,
        response: str,
        criteria: List[EvaluationCriteria],
        rubric: EvaluationRubric,
        context: Optional[str] = None,
        use_cot: bool = True,  # pylint: disable=unused-argument
    ) -> EvaluationResult:
        """Evaluate response using rule-based metrics.

        Args:
            response: Text response to evaluate
            criteria: List of evaluation criteria
            rubric: Detailed scoring rubric
            context: Optional context for evaluation
            use_cot: Whether to use chain-of-thought reasoning (not used in rule-based)

        Returns:
            EvaluationResult with scores and reasoning for each criterion
        """

        scores = {}
        reasoning = {}

        for criterion in criteria:
            score, reason = await self._evaluate_criterion(response, criterion, context)
            scores[criterion.name] = score
            reasoning[criterion.name] = reason

        overall_score = self._calculate_overall_score(scores, criteria)

        return EvaluationResult(
            scores=scores,
            reasoning=reasoning,
            overall_score=overall_score,
            confidence=0.9,  # High confidence for rule-based metrics
            metadata={"model": "rule-based", "metrics_used": list(scores.keys())},
        )

    async def _evaluate_criterion(self, response: str, criterion: EvaluationCriteria, context: Optional[str] = None) -> tuple[float, str]:
        """Evaluate a single criterion.

        Args:
            response: Text response to evaluate
            criterion: Single evaluation criterion to assess
            context: Optional context for evaluation

        Returns:
            Tuple of (score, reasoning) for the criterion
        """

        criterion_name = criterion.name.lower()

        if "length" in criterion_name:
            return self._evaluate_length(response, criterion)
        if "readability" in criterion_name:
            return self._evaluate_readability(response, criterion)
        if "grammar" in criterion_name or "spelling" in criterion_name:
            return self._evaluate_grammar_spelling(response, criterion)
        if "structure" in criterion_name or "format" in criterion_name:
            return self._evaluate_structure(response, criterion)
        if "keyword" in criterion_name or "term" in criterion_name:
            return self._evaluate_keywords(response, criterion, context)
        if "sentiment" in criterion_name:
            return self._evaluate_sentiment(response, criterion)
        if "completeness" in criterion_name:
            return self._evaluate_completeness(response, criterion, context)
        # Default to basic quality metrics
        return self._evaluate_basic_quality(response, criterion)

    def _evaluate_length(self, response: str, criterion: EvaluationCriteria) -> tuple[float, str]:  # pylint: disable=unused-argument
        """Evaluate response length.

        Args:
            response: Text response to evaluate
            criterion: Length evaluation criterion

        Returns:
            Tuple of (score, reasoning) for length evaluation
        """
        word_count = len(response.split())
        char_count = len(response)

        # Simple heuristic: ideal range is 50-500 words
        if 50 <= word_count <= 500:
            score = 5.0
            reason = f"Good length: {word_count} words, {char_count} characters"
        elif word_count < 50:
            score = max(1.0, 5.0 * (word_count / 50))
            reason = f"Too short: {word_count} words (recommended: 50+ words)"
        else:  # > 500
            score = max(1.0, 5.0 * (500 / word_count))
            reason = f"Too long: {word_count} words (recommended: <500 words)"

        return score, reason

    def _evaluate_readability(self, response: str, criterion: EvaluationCriteria) -> tuple[float, str]:  # pylint: disable=unused-argument
        """Evaluate readability using Flesch reading ease.

        Args:
            response: Text response to evaluate
            criterion: Readability evaluation criterion

        Returns:
            Tuple of (score, reasoning) for readability evaluation
        """
        try:
            # Try to use textstat flesch reading ease with fallback
            if hasattr(textstat, "flesch_reading_ease"):
                flesch_score = textstat.flesch_reading_ease(response)
            else:
                # Implement simple readability scoring
                flesch_score = self._calculate_simple_readability(response)

            # Convert Flesch score to 1-5 scale
            # 90-100: Very Easy (5), 80-90: Easy (4), 70-80: Fairly Easy (3)
            # 60-70: Standard (3), 50-60: Fairly Difficult (2), 0-50: Difficult (1)
            if flesch_score >= 80:
                score = 5.0
                level = "Easy"
            elif flesch_score >= 70:
                score = 4.0
                level = "Fairly Easy"
            elif flesch_score >= 50:
                score = 3.0
                level = "Standard"
            elif flesch_score >= 30:
                score = 2.0
                level = "Fairly Difficult"
            else:
                score = 1.0
                level = "Difficult"

            reason = f"Readability: {flesch_score:.1f} ({level})"
            return score, reason

        except Exception as e:
            return 3.0, f"Could not calculate readability: {str(e)}"

    def _calculate_simple_readability(self, text: str) -> float:
        """Calculate simple readability score based on sentence and word length.

        Args:
            text: Text to analyze for readability

        Returns:
            Simple readability score (0-100, higher is more readable)
        """
        if not text.strip():
            return 50.0

        # Count sentences (simple approximation)
        sentences = len([s for s in re.split(r"[.!?]+", text) if s.strip()])
        if sentences == 0:
            sentences = 1

        # Count words
        words = len(text.split())
        if words == 0:
            return 50.0

        # Count syllables (very simple approximation)
        syllables = 0
        for word in text.split():
            word = word.lower().strip('.,!?";')
            if word:
                # Simple syllable counting: count vowel groups
                vowel_count = len(re.findall(r"[aeiouAEIOU]+", word))
                syllables += max(1, vowel_count)

        # Simple Flesch approximation
        avg_sentence_length = words / sentences
        avg_syllables_per_word = syllables / words

        # Simplified Flesch formula approximation
        readability = 206.835 - (1.015 * avg_sentence_length) - (84.6 * avg_syllables_per_word)

        # Clamp to reasonable range
        return max(0.0, min(100.0, readability))

    def _evaluate_grammar_spelling(self, response: str, criterion: EvaluationCriteria) -> tuple[float, str]:  # pylint: disable=unused-argument
        """Basic grammar and spelling evaluation.

        Args:
            response: Text response to evaluate
            criterion: Grammar/spelling evaluation criterion

        Returns:
            Tuple of (score, reasoning) for grammar and spelling evaluation
        """

        issues = []

        # Check for common grammar issues
        if re.search(r"\s+[.!?]", response):
            issues.append("spaces before punctuation")

        if re.search(r"[.!?][a-z]", response):
            issues.append("missing spaces after punctuation")

        # Check for repeated punctuation
        if re.search(r"[.!?]{2,}", response):
            issues.append("repeated punctuation")

        # Check capitalization at sentence start
        sentences = re.split(r"[.!?]+", response)
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and not sentence[0].isupper():
                issues.append("capitalization errors")
                break

        # Score based on issues found
        if not issues:
            score = 5.0
            reason = "No obvious grammar or spelling issues detected"
        elif len(issues) == 1:
            score = 4.0
            reason = f"Minor issue: {issues[0]}"
        elif len(issues) <= 3:
            score = 3.0
            reason = f"Some issues: {', '.join(issues)}"
        else:
            score = 2.0
            reason = f"Multiple issues: {', '.join(issues[:3])}..."

        return score, reason

    def _evaluate_structure(self, response: str, criterion: EvaluationCriteria) -> tuple[float, str]:  # pylint: disable=unused-argument
        """Evaluate response structure and formatting.

        Args:
            response: Text response to evaluate
            criterion: Structure evaluation criterion

        Returns:
            Tuple of (score, reasoning) for structure evaluation
        """

        structure_score = 0
        reasons = []

        # Check for paragraphs
        paragraphs = response.split("\n\n")
        if len(paragraphs) > 1:
            structure_score += 1
            reasons.append("has multiple paragraphs")

        # Check for lists or bullet points
        if re.search(r"^\s*[-*•]\s+", response, re.MULTILINE):
            structure_score += 1
            reasons.append("uses bullet points")

        # Check for numbered lists
        if re.search(r"^\s*\d+\.\s+", response, re.MULTILINE):
            structure_score += 1
            reasons.append("uses numbered lists")

        # Check for headings (simple heuristic)
        if re.search(r"^[A-Z][^.!?]*:?\s*$", response, re.MULTILINE):
            structure_score += 1
            reasons.append("has section headings")

        # Check for logical flow (sentences that connect)
        sentences = re.split(r"[.!?]+", response)
        if len(sentences) >= 3:
            structure_score += 1
            reasons.append("has multiple sentences")

        # Convert to 1-5 scale
        score = min(5.0, max(1.0, 1.0 + structure_score))
        reason = f"Structure: {', '.join(reasons) if reasons else 'basic structure'}"

        return score, reason

    def _evaluate_keywords(self, response: str, criterion: EvaluationCriteria, context: Optional[str] = None) -> tuple[float, str]:  # pylint: disable=unused-argument
        """Evaluate presence of relevant keywords.

        Args:
            response: Text response to evaluate
            criterion: Keyword evaluation criterion
            context: Optional context containing relevant keywords

        Returns:
            Tuple of (score, reasoning) for keyword evaluation
        """

        if not context:
            return 3.0, "No context provided for keyword evaluation"

        # Extract potential keywords from context (simple approach)
        context_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", context.lower()))
        response_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", response.lower()))

        # Remove common stop words
        stop_words = {"the", "and", "but", "for", "are", "with", "this", "that", "from", "they", "have", "been", "said", "each", "which", "will", "there", "could", "would", "should"}
        context_keywords = context_words - stop_words
        response_keywords = response_words - stop_words

        # Calculate overlap
        overlap = len(context_keywords & response_keywords)
        total_context_keywords = len(context_keywords)

        if total_context_keywords == 0:
            return 3.0, "No meaningful keywords found in context"

        overlap_ratio = overlap / total_context_keywords
        score = 1.0 + 4.0 * overlap_ratio

        return score, f"Keyword overlap: {overlap}/{total_context_keywords} ({overlap_ratio:.1%})"

    def _evaluate_sentiment(self, response: str, criterion: EvaluationCriteria) -> tuple[float, str]:  # pylint: disable=unused-argument
        """Basic sentiment evaluation.

        Args:
            response: Text response to evaluate
            criterion: Sentiment evaluation criterion

        Returns:
            Tuple of (score, reasoning) for sentiment evaluation
        """

        # Simple word-based sentiment analysis
        positive_words = {"good", "great", "excellent", "wonderful", "amazing", "fantastic", "helpful", "useful", "beneficial"}
        negative_words = {"bad", "terrible", "awful", "horrible", "useless", "harmful", "wrong", "error", "problem"}

        words = set(response.lower().split())
        positive_count = len(words & positive_words)
        negative_count = len(words & negative_words)

        if positive_count > negative_count:
            score = 4.0 + min(1.0, (positive_count - negative_count) * 0.2)
            sentiment = "positive"
        elif negative_count > positive_count:
            score = 2.0 - min(1.0, (negative_count - positive_count) * 0.2)
            sentiment = "negative"
        else:
            score = 3.0
            sentiment = "neutral"

        return score, f"Sentiment: {sentiment} (+{positive_count}/-{negative_count})"

    def _evaluate_completeness(self, response: str, criterion: EvaluationCriteria, context: Optional[str] = None) -> tuple[float, str]:  # pylint: disable=unused-argument
        """Evaluate response completeness.

        Args:
            response: Text response to evaluate
            criterion: Completeness evaluation criterion
            context: Optional context for evaluation

        Returns:
            Tuple of (score, reasoning) for completeness evaluation
        """

        # Basic completeness metrics
        word_count = len(response.split())
        sentence_count = len(re.split(r"[.!?]+", response))

        # Heuristics for completeness
        completeness_score = 0
        reasons = []

        if word_count >= 20:
            completeness_score += 1
            reasons.append("adequate length")

        if sentence_count >= 2:
            completeness_score += 1
            reasons.append("multiple sentences")

        if "?" in response or re.search(r"\b(how|what|why|when|where|who)\b", response.lower()):
            completeness_score += 1
            reasons.append("addresses questions")

        if re.search(r"\b(therefore|because|since|due to|as a result)\b", response.lower()):
            completeness_score += 1
            reasons.append("provides explanations")

        if re.search(r"\b(example|instance|such as|for example)\b", response.lower()):
            completeness_score += 1
            reasons.append("includes examples")

        score = min(5.0, max(1.0, 1.0 + completeness_score))
        reason = f"Completeness: {', '.join(reasons) if reasons else 'basic response'}"

        return score, reason

    def _evaluate_basic_quality(self, response: str, criterion: EvaluationCriteria) -> tuple[float, str]:  # pylint: disable=unused-argument
        """Basic quality evaluation combining multiple factors.

        Args:
            response: Text response to evaluate
            criterion: Quality evaluation criterion

        Returns:
            Tuple of (score, reasoning) for basic quality evaluation
        """

        # Combine length, readability, and structure
        length_score, _ = self._evaluate_length(response, criterion)
        readability_score, _ = self._evaluate_readability(response, criterion)
        structure_score, _ = self._evaluate_structure(response, criterion)

        overall_score = (length_score + readability_score + structure_score) / 3

        return overall_score, "Combined quality score based on length, readability, and structure"

    async def pairwise_comparison(
        self,
        response_a: str,
        response_b: str,
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        position_bias_mitigation: bool = True,  # pylint: disable=unused-argument
    ) -> PairwiseResult:
        """Compare two responses using rule-based metrics.

        Args:
            response_a: First response to compare
            response_b: Second response to compare
            criteria: List of evaluation criteria
            context: Optional context for evaluation
            position_bias_mitigation: Whether to mitigate position bias (not used in rule-based)

        Returns:
            PairwiseResult indicating which response is better
        """

        # Evaluate both responses
        rubric = EvaluationRubric(criteria=criteria)
        eval_a = await self.evaluate_response(response_a, criteria, rubric, context)
        eval_b = await self.evaluate_response(response_b, criteria, rubric, context)

        # Determine winner
        if eval_a.overall_score > eval_b.overall_score:
            winner = "A"
            margin = (eval_a.overall_score - eval_b.overall_score) / 5.0
        elif eval_b.overall_score > eval_a.overall_score:
            winner = "B"
            margin = (eval_b.overall_score - eval_a.overall_score) / 5.0
        else:
            winner = "tie"
            margin = 0.0

        # Criterion-level comparison
        criterion_scores = {}
        for criterion in criteria:
            score_a = eval_a.scores.get(criterion.name, 0)
            score_b = eval_b.scores.get(criterion.name, 0)

            if score_a > score_b:
                criterion_scores[criterion.name] = "A"
            elif score_b > score_a:
                criterion_scores[criterion.name] = "B"
            else:
                criterion_scores[criterion.name] = "tie"

        reasoning = f"Response A score: {eval_a.overall_score:.2f}, Response B score: {eval_b.overall_score:.2f}"

        return PairwiseResult(winner=winner, confidence_score=0.9, reasoning=reasoning, criterion_scores=criterion_scores, margin=margin)  # High confidence for rule-based

    async def rank_responses(
        self,
        responses: List[str],
        criteria: List[EvaluationCriteria],
        context: Optional[str] = None,
        ranking_method: str = "scoring",  # pylint: disable=unused-argument
    ) -> RankingResult:
        """Rank responses using rule-based scoring.

        Args:
            responses: List of response strings to rank
            criteria: List of evaluation criteria
            context: Optional context for evaluation
            ranking_method: Method for ranking (only "scoring" supported)

        Returns:
            RankingResult with responses ranked by rule-based scores
        """

        rubric = EvaluationRubric(criteria=criteria)

        # Evaluate all responses
        evaluations = []
        for i, response in enumerate(responses):
            evaluation = await self.evaluate_response(response, criteria, rubric, context)
            evaluations.append(evaluation)

        # Sort by overall score
        ranked_results = []
        for i, evaluation in enumerate(evaluations):
            ranked_results.append({"response_index": i, "response": responses[i], "score": evaluation.overall_score, "reasoning": f"Rule-based score: {evaluation.overall_score:.2f}"})

        ranked_results.sort(key=lambda x: x["score"], reverse=True)

        return RankingResult(rankings=ranked_results, consistency_score=1.0, reasoning="Ranked by rule-based scoring")  # Deterministic, perfectly consistent

    async def evaluate_with_reference(
        self,
        response: str,
        reference: str,
        evaluation_type: str = "factuality",
        tolerance: str = "moderate",
    ) -> ReferenceEvaluationResult:
        """Evaluate response against reference using rule-based metrics.

        Args:
            response: Response text to evaluate
            reference: Reference text to compare against
            evaluation_type: Type of evaluation ("factuality", "completeness", etc.)
            tolerance: Tolerance level for evaluation

        Returns:
            ReferenceEvaluationResult with similarity score and analysis
        """

        # Semantic similarity using TF-IDF
        try:
            # Fit and transform both texts
            tfidf_matrix = self.vectorizer.fit_transform([response, reference])

            # Calculate cosine similarity
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        except Exception:
            # Fallback to simple word overlap if TF-IDF fails
            response_words = set(response.lower().split())
            reference_words = set(reference.lower().split())
            if not reference_words:
                similarity = 0.0
            else:
                overlap = len(response_words & reference_words)
                similarity = overlap / len(reference_words)

        # Basic keyword overlap
        response_words = set(response.lower().split())
        reference_words = set(reference.lower().split())

        common_words = response_words & reference_words
        missing_words = reference_words - response_words
        extra_words = response_words - reference_words

        # Simple factual error detection (very basic)
        factual_errors = []
        if len(response.split()) < len(reference.split()) * 0.3:
            factual_errors.append("Response too short compared to reference")

        return ReferenceEvaluationResult(
            similarity_score=float(similarity),
            missing_elements=list(missing_words)[:10],  # Limit to first 10
            extra_elements=list(extra_words)[:10],
            factual_errors=factual_errors,
            reasoning=f"Semantic similarity: {similarity:.3f}, Word overlap: {len(common_words)}/{len(reference_words)}",
        )
