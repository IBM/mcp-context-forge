# -*- coding: utf-8 -*-
"""MCP tools for prompt evaluation."""

# Standard
import re
import statistics
from typing import Any, Dict, List, Optional

# Third-Party
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Local
from .judge_tools import JudgeTools


class PromptTools:
    """Tools for prompt evaluation and analysis."""

    def __init__(self, judge_tools: Optional[JudgeTools] = None):
        """Initialize prompt tools.

        Args:
            judge_tools: Judge tools instance for LLM evaluations
        """
        self.judge_tools = judge_tools or JudgeTools()

    async def evaluate_clarity(
        self,
        prompt_text: str,
        target_model: str = "general",
        domain_context: Optional[str] = None,
        judge_model: str = "gpt-4",
    ) -> Dict[str, Any]:
        """Assess prompt clarity using multiple metrics.

        Args:
            prompt_text: The prompt to evaluate
            target_model: Model the prompt is designed for
            domain_context: Optional domain-specific requirements
            judge_model: Judge model for evaluation

        Returns:
            Clarity evaluation result
        """
        # Rule-based clarity metrics
        rule_metrics = self._analyze_clarity_rules(prompt_text)

        # LLM-based evaluation
        criteria = [
            {"name": "instruction_clarity", "description": "How clear and unambiguous are the instructions", "scale": "1-5", "weight": 0.3},
            {"name": "language_precision", "description": "Appropriateness and precision of vocabulary used", "scale": "1-5", "weight": 0.25},
            {"name": "task_specificity", "description": "How well-defined and specific the task is", "scale": "1-5", "weight": 0.25},
            {"name": "format_clarity", "description": "Quality of output format specification", "scale": "1-5", "weight": 0.2},
        ]

        rubric = {
            "criteria": criteria,
            "scale_description": {
                "1": "Very unclear, ambiguous, confusing",
                "2": "Unclear with multiple interpretations",
                "3": "Moderately clear with some ambiguity",
                "4": "Clear with minor ambiguities",
                "5": "Very clear, precise, unambiguous",
            },
        }

        context = f"Target model: {target_model}"
        if domain_context:
            context += f"\nDomain context: {domain_context}"

        llm_evaluation = await self.judge_tools.evaluate_response(response=prompt_text, criteria=criteria, rubric=rubric, judge_model=judge_model, context=context)

        # Combine rule-based and LLM metrics
        clarity_score = (rule_metrics["clarity_score"] + llm_evaluation["overall_score"]) / 2

        return {
            "clarity_score": clarity_score,
            "rule_based_metrics": rule_metrics,
            "llm_evaluation": llm_evaluation,
            "ambiguity_points": rule_metrics["ambiguity_points"],
            "language_precision": llm_evaluation["scores"].get("language_precision", 0),
            "instruction_specificity": llm_evaluation["scores"].get("task_specificity", 0),
            "format_clarity": llm_evaluation["scores"].get("format_clarity", 0),
            "recommendations": self._generate_clarity_recommendations(rule_metrics, llm_evaluation),
        }

    def _analyze_clarity_rules(self, prompt_text: str) -> Dict[str, Any]:
        """Analyze prompt clarity using rule-based metrics.

        Args:
            prompt_text: The prompt text to analyze for clarity issues.

        Returns:
            Dict[str, Any]: Clarity analysis including score, ambiguity points, and metrics.
        """
        clarity_score = 5.0
        ambiguity_points = []

        # Check for vague terms
        vague_terms = ["some", "many", "few", "several", "various", "might", "could", "maybe", "perhaps"]
        for term in vague_terms:
            if re.search(r"\b" + term + r"\b", prompt_text, re.IGNORECASE):
                clarity_score -= 0.2
                ambiguity_points.append(f"Contains vague term: '{term}'")

        # Check for ambiguous pronouns
        pronouns = ["it", "this", "that", "they", "them"]
        pronoun_count = sum(len(re.findall(r"\b" + pronoun + r"\b", prompt_text, re.IGNORECASE)) for pronoun in pronouns)
        if pronoun_count > 3:
            clarity_score -= 0.3
            ambiguity_points.append(f"High pronoun usage ({pronoun_count}) may cause confusion")

        # Check for question clarity
        questions = re.findall(r"[?]", prompt_text)
        if len(questions) > 3:
            clarity_score -= 0.2
            ambiguity_points.append("Multiple questions may confuse the task")

        # Check for contradictory instructions
        contradictory_patterns = [(r"\bbut\b", r"\bhowever\b"), (r"\bdon\'t\b", r"\bdo\b"), (r"\bavoid\b", r"\binclude\b")]
        for pattern1, pattern2 in contradictory_patterns:
            if re.search(pattern1, prompt_text, re.IGNORECASE) and re.search(pattern2, prompt_text, re.IGNORECASE):
                clarity_score -= 0.3
                ambiguity_points.append("Potentially contradictory instructions detected")

        # Check for sufficient detail
        word_count = len(prompt_text.split())
        if word_count < 10:
            clarity_score -= 0.5
            ambiguity_points.append("Prompt may be too brief for clear instructions")
        elif word_count > 200:
            clarity_score -= 0.2
            ambiguity_points.append("Prompt may be too verbose, affecting clarity")

        # Check for format specifications
        format_indicators = ["format", "structure", "example", "template", "json", "xml", "list", "table"]
        has_format = any(re.search(r"\b" + indicator + r"\b", prompt_text, re.IGNORECASE) for indicator in format_indicators)
        if not has_format:
            clarity_score -= 0.2
            ambiguity_points.append("No clear output format specification")

        return {
            "clarity_score": max(1.0, min(5.0, clarity_score)),
            "ambiguity_points": ambiguity_points,
            "word_count": word_count,
            "question_count": len(questions),
            "pronoun_count": pronoun_count,
            "has_format_spec": has_format,
        }

    async def test_consistency(
        self,
        prompt: str,  # pylint: disable=unused-argument
        test_inputs: List[str],
        num_runs: int = 3,
        temperature_range: Optional[List[float]] = None,
        judge_model: str = "gpt-4",  # pylint: disable=unused-argument
    ) -> Dict[str, Any]:
        """Test prompt consistency across multiple runs.

        Args:
            prompt: Prompt template
            test_inputs: List of input variations
            num_runs: Repetitions per input
            temperature_range: Test different temperatures
            judge_model: Judge model for evaluation

        Returns:
            Consistency analysis result
        """
        if temperature_range is None:
            temperature_range = [0.1, 0.5, 0.9]

        all_outputs = []
        consistency_data = {}

        for temp in temperature_range:
            temp_outputs = []

            for test_input in test_inputs:
                # Simulate multiple runs (in real implementation, would call target model)
                run_outputs = []
                for run in range(num_runs):
                    # Placeholder: In real implementation, call target model here
                    # For now, simulate with slight variations
                    simulated_output = f"Response to '{test_input}' (run {run + 1}, temp {temp})"
                    run_outputs.append(simulated_output)

                temp_outputs.extend(run_outputs)
                consistency_data[f"input_{test_inputs.index(test_input)}_temp_{temp}"] = run_outputs

            all_outputs.extend(temp_outputs)

        # Analyze consistency
        consistency_metrics = await self._analyze_consistency(all_outputs, consistency_data, judge_model)

        return {
            "consistency_score": consistency_metrics["overall_consistency"],
            "variance_analysis": consistency_metrics["variance_analysis"],
            "outliers": consistency_metrics["outliers"],
            "stability_report": consistency_metrics["stability_report"],
            "temperature_effects": consistency_metrics["temperature_effects"],
            "input_sensitivity": consistency_metrics["input_sensitivity"],
        }

    async def _analyze_consistency(self, all_outputs: List[str], consistency_data: Dict[str, List[str]], judge_model: str) -> Dict[str, Any]:  # pylint: disable=unused-argument
        """Analyze consistency of outputs.

        Args:
            all_outputs: List of all generated outputs to analyze.
            consistency_data: Organized output data by input and temperature.
            judge_model: Judge model for evaluation (currently unused).

        Returns:
            Dict[str, Any]: Consistency analysis with scores, variance, and outlier detection.
        """

        # Basic length consistency
        lengths = [len(output) for output in all_outputs]
        length_variance = statistics.variance(lengths) if len(lengths) > 1 else 0

        # Semantic consistency (simplified)
        # In real implementation, would use embeddings to measure semantic similarity
        unique_outputs = set(all_outputs)
        uniqueness_ratio = len(unique_outputs) / len(all_outputs)

        # Identify outliers (very different lengths)
        mean_length = statistics.mean(lengths)
        std_length = statistics.stdev(lengths) if len(lengths) > 1 else 0
        outliers = []

        for i, output in enumerate(all_outputs):
            if abs(len(output) - mean_length) > 2 * std_length:
                outliers.append({"index": i, "output": output[:100] + "..." if len(output) > 100 else output, "length": len(output), "deviation": abs(len(output) - mean_length)})

        # Calculate consistency score
        length_consistency = max(0, 1 - (length_variance / (mean_length**2)))
        semantic_consistency = 1 - uniqueness_ratio  # Lower uniqueness = higher consistency
        overall_consistency = (length_consistency + semantic_consistency) / 2

        return {
            "overall_consistency": overall_consistency,
            "variance_analysis": {"length_variance": length_variance, "mean_length": mean_length, "std_length": std_length, "uniqueness_ratio": uniqueness_ratio},
            "outliers": outliers,
            "stability_report": f"Generated {len(all_outputs)} outputs with {len(unique_outputs)} unique variations",
            "temperature_effects": "Analysis would require actual model calls",
            "input_sensitivity": "Analysis would require actual model calls",
        }

    async def measure_completeness(
        self,
        prompt: str,  # pylint: disable=unused-argument
        expected_components: List[str],
        test_samples: Optional[List[str]] = None,
        judge_model: str = "gpt-4",  # pylint: disable=unused-argument
    ) -> Dict[str, Any]:
        """Evaluate if prompt generates complete responses.

        Args:
            prompt: The prompt text
            expected_components: List of required elements
            test_samples: Sample outputs to analyze
            judge_model: Judge model for evaluation

        Returns:
            Completeness evaluation result
        """
        if not test_samples:
            # Generate mock samples for demonstration
            test_samples = ["Sample response 1 with some components", "More detailed sample response 2 covering multiple aspects", "Brief sample 3"]

        # Analyze each sample for component coverage
        component_coverage = {}
        for component in expected_components:
            component_coverage[component] = 0

        sample_analyses = []

        for i, sample in enumerate(test_samples):
            sample_components = []
            for component in expected_components:
                # Simple keyword matching (in real implementation, use semantic matching)
                if any(keyword.lower() in sample.lower() for keyword in component.split()):
                    sample_components.append(component)
                    component_coverage[component] += 1

            coverage_ratio = len(sample_components) / len(expected_components)
            sample_analyses.append({"sample_index": i, "covered_components": sample_components, "coverage_ratio": coverage_ratio, "sample_length": len(sample)})

        # Calculate overall completeness
        total_samples = len(test_samples)
        completeness_scores = {}

        for component, count in component_coverage.items():
            completeness_scores[component] = count / total_samples

        overall_completeness = sum(completeness_scores.values()) / len(completeness_scores)

        # Identify frequently missing components
        missing_components = [comp for comp, score in completeness_scores.items() if score < 0.5]

        # Generate coverage heatmap data
        coverage_heatmap = {
            "components": expected_components,
            "coverage_rates": [completeness_scores[comp] for comp in expected_components],
            "sample_coverage": [[1 if comp in analysis["covered_components"] else 0 for comp in expected_components] for analysis in sample_analyses],
        }

        return {
            "completeness_score": overall_completeness,
            "component_scores": completeness_scores,
            "missing_components": missing_components,
            "coverage_heatmap": coverage_heatmap,
            "sample_analyses": sample_analyses,
            "recommendations": self._generate_completeness_recommendations(missing_components, completeness_scores),
        }

    async def assess_relevance(
        self,
        prompt: str,
        outputs: List[str],
        embedding_model: str = "tfidf",  # pylint: disable=unused-argument
        relevance_threshold: float = 0.7,
        judge_model: str = "gpt-4",
    ) -> Dict[str, Any]:
        """Measure semantic alignment between prompt and outputs.

        Args:
            prompt: Input prompt
            outputs: Generated responses
            embedding_model: Model for semantic similarity
            relevance_threshold: Minimum acceptable score
            judge_model: Judge model for evaluation

        Returns:
            Relevance assessment result
        """
        # Use TF-IDF vectorizer for semantic similarity
        vectorizer = TfidfVectorizer(max_features=5000, stop_words="english", ngram_range=(1, 2), lowercase=True)

        relevance_scores = []
        semantic_analyses = []

        # Calculate semantic similarity for all outputs
        try:
            # Prepare texts for vectorization
            all_texts = [prompt] + outputs
            tfidf_matrix = vectorizer.fit_transform(all_texts)

            # Calculate similarity between prompt and each output
            prompt_vector = tfidf_matrix[0:1]

            for i, output in enumerate(outputs):
                output_vector = tfidf_matrix[i + 1 : i + 2]  # noqa: E203
                relevance_score = cosine_similarity(prompt_vector, output_vector)[0][0]
                relevance_scores.append(relevance_score)

                semantic_analyses.append(
                    {
                        "output_index": i,
                        "relevance_score": relevance_score,
                        "is_relevant": relevance_score >= relevance_threshold,
                        "output_preview": output[:100] + "..." if len(output) > 100 else output,
                    }
                )

        except Exception:
            # Fallback to simple word overlap
            prompt_words = set(prompt.lower().split())

            for i, output in enumerate(outputs):
                output_words = set(output.lower().split())
                if not prompt_words:
                    relevance_score = 0.0
                else:
                    overlap = len(prompt_words & output_words)
                    relevance_score = overlap / len(prompt_words)

                relevance_scores.append(relevance_score)
                semantic_analyses.append(
                    {
                        "output_index": i,
                        "relevance_score": relevance_score,
                        "is_relevant": relevance_score >= relevance_threshold,
                        "output_preview": output[:100] + "..." if len(output) > 100 else output,
                    }
                )

        # Calculate overall metrics
        avg_relevance = statistics.mean(relevance_scores)
        relevant_count = sum(1 for score in relevance_scores if score >= relevance_threshold)
        on_topic_percentage = (relevant_count / len(outputs)) * 100

        # Identify semantic drift
        min_score = min(relevance_scores)
        max_score = max(relevance_scores)
        semantic_drift = max_score - min_score

        # LLM-based evaluation for additional insights
        criteria = [{"name": "topic_adherence", "description": "How well the response stays on the intended topic", "scale": "1-5", "weight": 1.0}]

        rubric = {
            "criteria": criteria,
            "scale_description": {
                "1": "Completely off-topic",
                "2": "Mostly off-topic with some relevance",
                "3": "Moderately relevant",
                "4": "Mostly relevant with minor deviations",
                "5": "Highly relevant and on-topic",
            },
        }

        # Evaluate a sample output for qualitative insights
        if outputs:
            sample_evaluation = await self.judge_tools.evaluate_response(response=outputs[0], criteria=criteria, rubric=rubric, judge_model=judge_model, context=f"Original prompt: {prompt}")
        else:
            sample_evaluation = {"scores": {"topic_adherence": 0}, "reasoning": {"topic_adherence": "No outputs to evaluate"}}

        return {
            "relevance_scores": relevance_scores,
            "average_relevance": avg_relevance,
            "semantic_drift": semantic_drift,
            "topic_adherence": on_topic_percentage,
            "threshold_compliance": {"threshold": relevance_threshold, "compliant_outputs": relevant_count, "compliance_rate": on_topic_percentage / 100},
            "semantic_analyses": semantic_analyses,
            "llm_insights": sample_evaluation,
            "recommendations": self._generate_relevance_recommendations(avg_relevance, semantic_drift, on_topic_percentage),
        }

    def _generate_clarity_recommendations(self, rule_metrics: Dict[str, Any], llm_evaluation: Dict[str, Any]) -> List[str]:
        """Generate recommendations for improving prompt clarity.

        Args:
            rule_metrics: Rule-based clarity analysis results.
            llm_evaluation: LLM-based evaluation results.

        Returns:
            List[str]: List of recommendation messages for clarity improvement.
        """
        recommendations = []

        if rule_metrics["clarity_score"] < 3.0:
            recommendations.append("Consider rewriting with more specific, concrete language")

        if rule_metrics["word_count"] < 10:
            recommendations.append("Add more detailed instructions and context")
        elif rule_metrics["word_count"] > 200:
            recommendations.append("Consider breaking into shorter, focused instructions")

        if not rule_metrics["has_format_spec"]:
            recommendations.append("Add clear output format specifications")

        if llm_evaluation["scores"].get("instruction_clarity", 5) < 3:
            recommendations.append("Clarify the main task and expected actions")

        if llm_evaluation["scores"].get("language_precision", 5) < 3:
            recommendations.append("Use more precise and domain-appropriate vocabulary")

        return recommendations

    def _generate_completeness_recommendations(self, missing_components: List[str], component_scores: Dict[str, float]) -> List[str]:
        """Generate recommendations for improving prompt completeness.

        Args:
            missing_components: List of components that are frequently missing.
            component_scores: Coverage scores for each expected component.

        Returns:
            List[str]: List of recommendation messages for completeness improvement.
        """
        recommendations = []

        if missing_components:
            recommendations.append(f"Explicitly request these often-missing components: {', '.join(missing_components)}")

        low_scoring = [comp for comp, score in component_scores.items() if score < 0.3]
        if low_scoring:
            recommendations.append(f"Provide examples or templates for: {', '.join(low_scoring)}")

        if len(missing_components) > len(component_scores) * 0.5:
            recommendations.append("Consider breaking the prompt into multiple focused sub-prompts")

        return recommendations

    def _generate_relevance_recommendations(self, avg_relevance: float, semantic_drift: float, on_topic_percentage: float) -> List[str]:
        """Generate recommendations for improving prompt relevance.

        Args:
            avg_relevance: Average relevance score across all outputs.
            semantic_drift: Measure of variability in semantic relevance.
            on_topic_percentage: Percentage of outputs that meet relevance threshold.

        Returns:
            List[str]: List of recommendation messages for relevance improvement.
        """
        recommendations = []

        if avg_relevance < 0.6:
            recommendations.append("Make the prompt more specific to reduce irrelevant responses")

        if semantic_drift > 0.4:
            recommendations.append("Add constraints to reduce variability in response relevance")

        if on_topic_percentage < 70:
            recommendations.append("Include explicit instructions to stay on topic")
            recommendations.append("Provide clear examples of desired vs. undesired responses")

        if avg_relevance > 0.9 and semantic_drift < 0.1:
            recommendations.append("Prompt appears highly effective - consider using as template")

        return recommendations
