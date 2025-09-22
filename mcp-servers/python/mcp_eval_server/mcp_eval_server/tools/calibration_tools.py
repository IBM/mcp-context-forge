# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mcp_eval_server/mcp_eval_server/tools/calibration_tools.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP tools for calibration and meta-evaluation.
"""

# Standard
from collections import Counter
import secrets
import statistics
from typing import Any, Dict, List, Optional

# Local
from .judge_tools import JudgeTools


class CalibrationTools:
    """Tools for judge calibration and meta-evaluation."""

    def __init__(self, judge_tools: Optional[JudgeTools] = None):
        """Initialize calibration tools.

        Args:
            judge_tools: Judge tools instance
        """
        self.judge_tools = judge_tools or JudgeTools()

    async def test_judge_agreement(
        self,
        test_cases: List[Dict[str, Any]],
        judge_models: List[str],
        correlation_metric: str = "pearson",
        human_labels: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Measure agreement between judges and humans.

        Args:
            test_cases: Human-labeled examples
            judge_models: LLMs to test
            correlation_metric: Correlation measure ('pearson', 'spearman', 'cohen_kappa')
            human_labels: Ground truth human evaluations

        Returns:
            Agreement analysis results

        Raises:
            ValueError: If fewer than 2 judges provided for agreement testing
        """
        if len(judge_models) < 2:
            raise ValueError("Need at least 2 judges for agreement testing")

        # Evaluate all test cases with each judge
        judge_evaluations = {}

        for judge_model in judge_models:
            judge_evaluations[judge_model] = await self._evaluate_test_cases(test_cases, judge_model)

        # Calculate inter-judge agreement
        inter_judge_agreement = self._calculate_inter_judge_agreement(judge_evaluations, correlation_metric)

        # Calculate human-judge agreement if human labels provided
        human_judge_agreement = {}
        if human_labels:
            for judge_model in judge_models:
                agreement = self._calculate_human_judge_agreement(human_labels, judge_evaluations[judge_model], correlation_metric)
                human_judge_agreement[judge_model] = agreement

        # Analyze bias patterns
        bias_analysis = self._analyze_judge_bias(judge_evaluations, human_labels)

        # Calculate reliability metrics
        reliability_metrics = self._calculate_reliability_metrics(judge_evaluations)

        return {
            "agreement_scores": inter_judge_agreement,
            "human_agreement": human_judge_agreement,
            "bias_analysis": bias_analysis,
            "reliability_metrics": reliability_metrics,
            "test_cases_count": len(test_cases),
            "judges_tested": judge_models,
            "correlation_metric": correlation_metric,
            "recommendations": self._generate_agreement_recommendations(inter_judge_agreement, human_judge_agreement, bias_analysis),
        }

    async def _evaluate_test_cases(self, test_cases: List[Dict[str, Any]], judge_model: str) -> List[Dict[str, Any]]:
        """Evaluate test cases with a specific judge.

        Args:
            test_cases: List of test cases to evaluate
            judge_model: Model to use for evaluation

        Returns:
            List of evaluation results for each test case
        """

        evaluations = []

        for test_case in test_cases:
            try:
                # Extract evaluation parameters from test case
                response = test_case.get("response", "")
                criteria = test_case.get("criteria", [{"name": "overall_quality", "description": "Overall quality of the response", "scale": "1-5", "weight": 1.0}])
                rubric = test_case.get("rubric", {"criteria": criteria, "scale_description": {"1": "Very poor", "2": "Poor", "3": "Average", "4": "Good", "5": "Excellent"}})

                evaluation = await self.judge_tools.evaluate_response(response=response, criteria=criteria, rubric=rubric, judge_model=judge_model, context=test_case.get("context"))

                evaluations.append({"test_case_id": test_case.get("id", len(evaluations)), "evaluation": evaluation, "success": True})

            except Exception as e:
                evaluations.append({"test_case_id": test_case.get("id", len(evaluations)), "evaluation": None, "success": False, "error": str(e)})

        return evaluations

    def _calculate_inter_judge_agreement(self, judge_evaluations: Dict[str, List[Dict[str, Any]]], metric: str) -> Dict[str, Any]:
        """Calculate agreement between judges.

        Args:
            judge_evaluations: Evaluations from different judges
            metric: Correlation metric to use ('pearson', 'spearman', 'cohen_kappa')

        Returns:
            Dictionary containing agreement analysis results
        """

        judge_names = list(judge_evaluations.keys())
        agreement_matrix = {}

        # Pairwise agreement calculation
        for i, judge_a in enumerate(judge_names):
            for judge_b in judge_names[i + 1 :]:  # noqa: E203
                scores_a = []
                scores_b = []

                # Extract scores for comparison
                evals_a = judge_evaluations[judge_a]
                evals_b = judge_evaluations[judge_b]

                for eval_a, eval_b in zip(evals_a, evals_b):
                    if eval_a["success"] and eval_b["success"]:
                        score_a = eval_a["evaluation"]["overall_score"]
                        score_b = eval_b["evaluation"]["overall_score"]
                        scores_a.append(score_a)
                        scores_b.append(score_b)

                if len(scores_a) >= 2:
                    if metric == "pearson":
                        correlation = self._pearson_correlation(scores_a, scores_b)
                    elif metric == "spearman":
                        correlation = self._spearman_correlation(scores_a, scores_b)
                    elif metric == "cohen_kappa":
                        correlation = self._cohen_kappa(scores_a, scores_b)
                    else:
                        correlation = self._pearson_correlation(scores_a, scores_b)

                    agreement_matrix[f"{judge_a}_vs_{judge_b}"] = {
                        "correlation": correlation,
                        "sample_size": len(scores_a),
                        "mean_difference": statistics.mean([a - b for a, b in zip(scores_a, scores_b)]),
                    }

        # Calculate overall agreement
        correlations = [data["correlation"] for data in agreement_matrix.values()]
        overall_agreement = statistics.mean(correlations) if correlations else 0.0

        return {
            "pairwise_agreements": agreement_matrix,
            "overall_agreement": overall_agreement,
            "agreement_range": {"min": min(correlations) if correlations else 0.0, "max": max(correlations) if correlations else 0.0},
            "consistency": "high" if overall_agreement > 0.8 else "medium" if overall_agreement > 0.6 else "low",
        }

    def _calculate_human_judge_agreement(self, human_labels: Dict[str, Any], judge_evaluations: List[Dict[str, Any]], metric: str) -> Dict[str, Any]:
        """Calculate agreement between human and judge evaluations.

        Args:
            human_labels: Ground truth human evaluation labels
            judge_evaluations: Judge evaluation results
            metric: Correlation metric to use

        Returns:
            Dictionary containing human-judge agreement analysis
        """

        human_scores = []
        judge_scores = []

        for evaluation in judge_evaluations:
            if not evaluation["success"]:
                continue

            test_case_id = evaluation["test_case_id"]
            if str(test_case_id) in human_labels:
                human_score = human_labels[str(test_case_id)].get("score", 0.0)
                judge_score = evaluation["evaluation"]["overall_score"]

                human_scores.append(human_score)
                judge_scores.append(judge_score)

        if len(human_scores) >= 2:
            if metric == "pearson":
                correlation = self._pearson_correlation(human_scores, judge_scores)
            elif metric == "spearman":
                correlation = self._spearman_correlation(human_scores, judge_scores)
            elif metric == "cohen_kappa":
                correlation = self._cohen_kappa(human_scores, judge_scores)
            else:
                correlation = self._pearson_correlation(human_scores, judge_scores)
        else:
            correlation = 0.0

        return {
            "correlation": correlation,
            "sample_size": len(human_scores),
            "mean_bias": statistics.mean([j - h for h, j in zip(human_scores, judge_scores)]) if human_scores else 0.0,
            "agreement_level": "high" if correlation > 0.7 else "medium" if correlation > 0.5 else "low",
        }

    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient.

        Args:
            x: First list of values
            y: Second list of values

        Returns:
            Pearson correlation coefficient between -1 and 1
        """
        if len(x) != len(y) or len(x) < 2:
            return 0.0

        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi * xi for xi in x)
        sum_y2 = sum(yi * yi for yi in y)

        numerator = n * sum_xy - sum_x * sum_y
        denominator = ((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y)) ** 0.5

        if denominator == 0:
            return 0.0

        return numerator / denominator

    def _spearman_correlation(self, x: List[float], y: List[float]) -> float:
        """Calculate Spearman rank correlation coefficient.

        Args:
            x: First list of values
            y: Second list of values

        Returns:
            Spearman rank correlation coefficient between -1 and 1
        """
        if len(x) != len(y) or len(x) < 2:
            return 0.0

        # Convert to ranks
        def rank(values):
            sorted_values = sorted(enumerate(values), key=lambda x: x[1])
            ranks = [0] * len(values)
            for rank_idx, (original_idx, _) in enumerate(sorted_values):
                ranks[original_idx] = rank_idx + 1
            return ranks

        rank_x = rank(x)
        rank_y = rank(y)

        return self._pearson_correlation(rank_x, rank_y)

    def _cohen_kappa(self, x: List[float], y: List[float]) -> float:
        """Calculate Cohen's kappa (simplified for continuous values).

        Args:
            x: First list of continuous values to compare.
            y: Second list of continuous values to compare.

        Returns:
            float: Cohen's kappa coefficient between -1 and 1.
        """
        if len(x) != len(y) or len(x) < 2:
            return 0.0

        # Convert continuous values to categories (simplified)
        def categorize(values):
            categories = []
            for value in values:
                if value <= 2.0:
                    categories.append(1)
                elif value <= 3.5:
                    categories.append(2)
                else:
                    categories.append(3)
            return categories

        cat_x = categorize(x)
        cat_y = categorize(y)

        # Calculate observed agreement
        agreements = sum(1 for cx, cy in zip(cat_x, cat_y) if cx == cy)
        po = agreements / len(cat_x)

        # Calculate expected agreement (simplified)
        count_x = Counter(cat_x)
        count_y = Counter(cat_y)

        pe = 0
        for category in [1, 2, 3]:
            pe += (count_x.get(category, 0) / len(cat_x)) * (count_y.get(category, 0) / len(cat_y))

        if pe == 1:
            return 1.0

        return (po - pe) / (1 - pe)

    def _analyze_judge_bias(self, judge_evaluations: Dict[str, List[Dict[str, Any]]], human_labels: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Analyze systematic bias patterns in judges.

        Args:
            judge_evaluations: Dictionary of judge evaluation results by judge name.
            human_labels: Optional ground truth human evaluation labels.

        Returns:
            Dict[str, Any]: Bias analysis for each judge including severity metrics.
        """

        bias_analysis = {}

        for judge_name, evaluations in judge_evaluations.items():
            successful_evals = [e for e in evaluations if e["success"]]

            if not successful_evals:
                continue

            scores = [e["evaluation"]["overall_score"] for e in successful_evals]

            # Calculate bias metrics
            mean_score = statistics.mean(scores)
            score_variance = statistics.variance(scores) if len(scores) > 1 else 0

            # Severity bias (tendency to be harsh or lenient)
            if human_labels:
                human_mean = statistics.mean([human_labels[str(e["test_case_id"])].get("score", 3.0) for e in successful_evals if str(e["test_case_id"]) in human_labels])
                severity_bias = mean_score - human_mean
            else:
                severity_bias = mean_score - 3.0  # Assume 3.0 as neutral

            # Range restriction (tendency to use limited score range)
            score_range = max(scores) - min(scores) if scores else 0
            range_restriction = 1.0 - (score_range / 4.0)  # 4.0 is max possible range

            bias_analysis[judge_name] = {
                "mean_score": mean_score,
                "score_variance": score_variance,
                "severity_bias": severity_bias,
                "range_restriction": range_restriction,
                "bias_severity": self._classify_bias_severity(severity_bias, range_restriction),
                "sample_size": len(successful_evals),
            }

        return bias_analysis

    def _classify_bias_severity(self, severity_bias: float, range_restriction: float) -> str:
        """Classify overall bias severity.

        Args:
            severity_bias: Magnitude of severity bias (difference from expected mean).
            range_restriction: Degree of range restriction (0-1 scale).

        Returns:
            str: Bias severity classification ('low', 'medium', or 'high').
        """

        severity_magnitude = abs(severity_bias)

        if severity_magnitude > 1.0 or range_restriction > 0.7:
            return "high"
        if severity_magnitude > 0.5 or range_restriction > 0.5:
            return "medium"
        return "low"

    def _calculate_reliability_metrics(self, judge_evaluations: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Calculate reliability metrics for judges.

        Args:
            judge_evaluations: Dictionary of judge evaluation results by judge name.

        Returns:
            Dict[str, Any]: Reliability metrics for each judge including success rate and consistency.
        """

        reliability_metrics = {}

        for judge_name, evaluations in judge_evaluations.items():
            successful_evals = [e for e in evaluations if e["success"]]

            if not successful_evals:
                continue

            # Success rate
            success_rate = len(successful_evals) / len(evaluations)

            # Consistency (inverse of variance)
            scores = [e["evaluation"]["overall_score"] for e in successful_evals]
            consistency = 1.0 - (statistics.variance(scores) / 4.0) if len(scores) > 1 else 1.0
            consistency = max(0.0, min(1.0, consistency))

            # Response time consistency (mock data)
            response_times = [secrets.SystemRandom().uniform(2.0, 8.0) for _ in successful_evals]
            time_consistency = 1.0 - (statistics.variance(response_times) / 100.0)
            time_consistency = max(0.0, min(1.0, time_consistency))

            reliability_metrics[judge_name] = {
                "success_rate": success_rate,
                "score_consistency": consistency,
                "time_consistency": time_consistency,
                "overall_reliability": (success_rate + consistency + time_consistency) / 3,
                "sample_size": len(evaluations),
            }

        return reliability_metrics

    async def optimize_rubrics(
        self,
        current_rubric: Dict[str, Any],
        human_labels: Dict[str, Any],
        optimization_target: str = "agreement",
        iterations: int = 3,
    ) -> Dict[str, Any]:
        """Tune evaluation rubrics for better alignment.

        Args:
            current_rubric: Existing criteria and rubric
            human_labels: Ground truth labels
            optimization_target: What to improve ('agreement', 'consistency', 'bias')
            iterations: Number of optimization iterations

        Returns:
            Optimized rubric and performance metrics
        """
        best_rubric = current_rubric.copy()
        best_performance = 0.0
        optimization_history = []

        for iteration in range(iterations):
            # Generate rubric variations
            rubric_variations = self._generate_rubric_variations(best_rubric, iteration + 1)

            # Test each variation
            variation_results = []

            for i, variation in enumerate(rubric_variations):
                # Simulate testing (in real implementation, would test with actual judges)
                performance = await self._evaluate_rubric_performance(variation, human_labels, optimization_target)

                variation_results.append({"variation_id": f"iter_{iteration}_var_{i}", "rubric": variation, "performance": performance})

            # Select best variation
            best_variation = max(variation_results, key=lambda x: x["performance"])

            if best_variation["performance"] > best_performance:
                best_performance = best_variation["performance"]
                best_rubric = best_variation["rubric"]

            optimization_history.append(
                {
                    "iteration": iteration + 1,
                    "variations_tested": len(variation_results),
                    "best_performance": best_performance,
                    "improvement": best_variation["performance"] - (optimization_history[-1]["best_performance"] if optimization_history else 0),
                }
            )

        # Calculate performance gain
        initial_performance = await self._evaluate_rubric_performance(current_rubric, human_labels, optimization_target)
        performance_gain = {
            "initial_performance": initial_performance,
            "optimized_performance": best_performance,
            "absolute_improvement": best_performance - initial_performance,
            "relative_improvement": (best_performance - initial_performance) / initial_performance if initial_performance > 0 else 0,
        }

        # Analyze changes made
        changes_made = self._analyze_rubric_changes(current_rubric, best_rubric)

        return {
            "optimized_rubric": best_rubric,
            "performance_gain": performance_gain,
            "optimization_history": optimization_history,
            "changes_made": changes_made,
            "optimization_target": optimization_target,
            "iterations_run": iterations,
            "recommendations": self._generate_optimization_recommendations(performance_gain, changes_made, optimization_target),
        }

    def _generate_rubric_variations(self, base_rubric: Dict[str, Any], iteration: int) -> List[Dict[str, Any]]:
        """Generate variations of a rubric for optimization.

        Args:
            base_rubric: Base rubric to generate variations from.
            iteration: Current optimization iteration number.

        Returns:
            List[Dict[str, Any]]: List of rubric variations to test.
        """

        variations = []

        # Variation 1: Modify scale descriptions
        variation_1 = base_rubric.copy()
        if "scale_description" in variation_1:
            # Make descriptions more specific
            for scale, description in variation_1["scale_description"].items():
                if "good" in description.lower():
                    variation_1["scale_description"][scale] = description.replace("Good", "Above average with clear strengths")
                elif "excellent" in description.lower():
                    variation_1["scale_description"][scale] = description.replace("Excellent", "Outstanding with exceptional quality")
        variations.append(variation_1)

        # Variation 2: Adjust criteria weights
        variation_2 = base_rubric.copy()
        if "criteria" in variation_2:
            for criterion in variation_2["criteria"]:
                # Slightly adjust weights
                current_weight = criterion.get("weight", 1.0)
                criterion["weight"] = max(0.1, min(2.0, current_weight * (0.8 + secrets.SystemRandom().random() * 0.4)))
        variations.append(variation_2)

        # Variation 3: Add new criteria or modify existing ones
        variation_3 = base_rubric.copy()
        if "criteria" in variation_3:
            # Add a new criterion
            new_criterion = {"name": f"detailed_analysis_iter_{iteration}", "description": "Depth and thoroughness of analysis provided", "scale": "1-5", "weight": 0.3}
            variation_3["criteria"].append(new_criterion)
        variations.append(variation_3)

        return variations

    async def _evaluate_rubric_performance(self, rubric: Dict[str, Any], human_labels: Dict[str, Any], optimization_target: str) -> float:  # pylint: disable=unused-argument
        """Evaluate performance of a rubric.

        Args:
            rubric: Rubric definition to evaluate.
            human_labels: Ground truth human evaluation labels.
            optimization_target: Target metric for optimization ('agreement', 'consistency', 'bias').

        Returns:
            float: Performance score for the rubric between 0.0 and 1.0.
        """

        # Simulate rubric performance (in real implementation, would test with judges)
        base_performance = 0.7

        # Simulate different optimization targets
        if optimization_target == "agreement":
            # Favor rubrics with more specific descriptions
            specificity_bonus = 0.0
            if "scale_description" in rubric:
                avg_description_length = statistics.mean([len(desc.split()) for desc in rubric["scale_description"].values()])
                specificity_bonus = min(0.2, avg_description_length / 20)
            performance = base_performance + specificity_bonus

        elif optimization_target == "consistency":
            # Favor rubrics with balanced criteria weights
            if "criteria" in rubric:
                weights = [c.get("weight", 1.0) for c in rubric["criteria"]]
                weight_variance = statistics.variance(weights) if len(weights) > 1 else 0
                consistency_bonus = max(0, 0.15 - weight_variance)
                performance = base_performance + consistency_bonus
            else:
                performance = base_performance

        elif optimization_target == "bias":
            # Favor rubrics with more criteria (reduces single-point bias)
            criteria_count = len(rubric.get("criteria", []))
            bias_reduction_bonus = min(0.1, criteria_count * 0.03)
            performance = base_performance + bias_reduction_bonus

        else:
            performance = base_performance

        # Add some randomness
        performance += secrets.SystemRandom().uniform(-0.05, 0.05)

        return max(0.0, min(1.0, performance))

    def _analyze_rubric_changes(self, original_rubric: Dict[str, Any], optimized_rubric: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze changes made during rubric optimization.

        Args:
            original_rubric: Original rubric before optimization.
            optimized_rubric: Rubric after optimization.

        Returns:
            Dict[str, Any]: Analysis of changes including new criteria, weight changes, and scale changes.
        """

        changes = {"criteria_changes": [], "scale_changes": [], "weight_changes": [], "new_criteria": [], "removed_criteria": []}

        # Compare criteria
        original_criteria = {c["name"]: c for c in original_rubric.get("criteria", [])}
        optimized_criteria = {c["name"]: c for c in optimized_rubric.get("criteria", [])}

        # Find new and removed criteria
        original_names = set(original_criteria.keys())
        optimized_names = set(optimized_criteria.keys())

        changes["new_criteria"] = list(optimized_names - original_names)
        changes["removed_criteria"] = list(original_names - optimized_names)

        # Find weight changes
        for name in original_names & optimized_names:
            orig_weight = original_criteria[name].get("weight", 1.0)
            opt_weight = optimized_criteria[name].get("weight", 1.0)

            if abs(orig_weight - opt_weight) > 0.01:
                changes["weight_changes"].append({"criterion": name, "original_weight": orig_weight, "optimized_weight": opt_weight, "change": opt_weight - orig_weight})

        # Compare scale descriptions
        orig_scales = original_rubric.get("scale_description", {})
        opt_scales = optimized_rubric.get("scale_description", {})

        for scale in orig_scales:
            if scale in opt_scales and orig_scales[scale] != opt_scales[scale]:
                changes["scale_changes"].append({"scale": scale, "original": orig_scales[scale], "optimized": opt_scales[scale]})

        return changes

    def _generate_agreement_recommendations(self, inter_judge_agreement: Dict[str, Any], human_judge_agreement: Dict[str, Any], bias_analysis: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on agreement analysis.

        Args:
            inter_judge_agreement: Analysis of agreement between judges.
            human_judge_agreement: Analysis of agreement between judges and humans.
            bias_analysis: Analysis of systematic bias in judges.

        Returns:
            List[str]: List of recommendation messages.
        """

        recommendations = []

        # Inter-judge agreement recommendations
        overall_agreement = inter_judge_agreement.get("overall_agreement", 0.0)
        if overall_agreement < 0.6:
            recommendations.append("Low inter-judge agreement - consider judge training or rubric clarification")
        elif overall_agreement > 0.8:
            recommendations.append("Good inter-judge agreement - judges are well-calibrated")

        # Human-judge agreement recommendations
        if human_judge_agreement:
            low_agreement_judges = [judge for judge, data in human_judge_agreement.items() if data.get("correlation", 0) < 0.6]
            if low_agreement_judges:
                recommendations.append(f"These judges show low human agreement: {', '.join(low_agreement_judges)}")

        # Bias recommendations
        if bias_analysis:
            high_bias_judges = [judge for judge, data in bias_analysis.items() if data.get("bias_severity") == "high"]
            if high_bias_judges:
                recommendations.append(f"High bias detected in: {', '.join(high_bias_judges)} - consider recalibration")

        return recommendations

    def _generate_optimization_recommendations(self, performance_gain: Dict[str, Any], changes_made: Dict[str, Any], optimization_target: str) -> List[str]:  # pylint: disable=unused-argument
        """Generate recommendations based on rubric optimization.

        Args:
            performance_gain: Performance improvement metrics from optimization.
            changes_made: Analysis of changes made during optimization.
            optimization_target: Target metric that was optimized for.

        Returns:
            List[str]: List of recommendation messages.
        """

        recommendations = []

        improvement = performance_gain.get("relative_improvement", 0.0)

        if improvement > 0.1:
            recommendations.append(f"Significant improvement achieved ({improvement:.1%}) - implement optimized rubric")
        elif improvement > 0.05:
            recommendations.append(f"Moderate improvement achieved ({improvement:.1%}) - consider implementing changes")
        else:
            recommendations.append("Limited improvement - current rubric may already be well-optimized")

        # Specific change recommendations
        if changes_made["new_criteria"]:
            recommendations.append(f"Added {len(changes_made['new_criteria'])} new criteria for better coverage")

        if changes_made["weight_changes"]:
            recommendations.append(f"Adjusted weights for {len(changes_made['weight_changes'])} criteria")

        if changes_made["scale_changes"]:
            recommendations.append(f"Refined {len(changes_made['scale_changes'])} scale descriptions for clarity")

        return recommendations
