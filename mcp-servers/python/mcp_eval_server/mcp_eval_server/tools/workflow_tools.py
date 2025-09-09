# -*- coding: utf-8 -*-
"""MCP tools for evaluation workflow management."""

# Standard
import asyncio
from datetime import datetime, timezone
import statistics
from typing import Any, Dict, List, Optional
import uuid

# Local
from .agent_tools import AgentTools
from .judge_tools import JudgeTools
from .prompt_tools import PromptTools
from .quality_tools import QualityTools


class WorkflowTools:
    """Tools for evaluation workflow and suite management."""

    def __init__(self, judge_tools: Optional[JudgeTools] = None, prompt_tools: Optional[PromptTools] = None, agent_tools: Optional[AgentTools] = None, quality_tools: Optional[QualityTools] = None):
        """Initialize workflow tools.

        Args:
            judge_tools: Judge tools instance
            prompt_tools: Prompt tools instance
            agent_tools: Agent tools instance
            quality_tools: Quality tools instance
        """
        self.judge_tools = judge_tools or JudgeTools()
        self.prompt_tools = prompt_tools or PromptTools(self.judge_tools)
        self.agent_tools = agent_tools or AgentTools(self.judge_tools)
        self.quality_tools = quality_tools or QualityTools(self.judge_tools)

        # In-memory storage for evaluation suites and results
        self.evaluation_suites = {}
        self.evaluation_results = {}

    async def create_evaluation_suite(
        self,
        suite_name: str,
        evaluation_steps: List[Dict[str, Any]],
        success_thresholds: Dict[str, float],
        weights: Optional[Dict[str, float]] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Define comprehensive evaluation pipeline.

        Args:
            suite_name: Identifier for the suite
            evaluation_steps: List of evaluation tools to run
            success_thresholds: Pass/fail criteria
            weights: Importance of each metric
            description: Optional description

        Returns:
            Suite configuration with unique ID

        Raises:
            ValueError: If unknown evaluation tool specified in steps
        """
        suite_id = str(uuid.uuid4())

        # Validate evaluation steps
        valid_tools = self._get_valid_tools()
        for step in evaluation_steps:
            tool = step.get("tool")
            if tool not in valid_tools:
                raise ValueError(f"Unknown evaluation tool: {tool}")

        # Set default weights if not provided
        if weights is None:
            weights = {step["tool"]: step.get("weight", 1.0) for step in evaluation_steps}

        # Normalize weights
        total_weight = sum(weights.values())
        if total_weight > 0:
            weights = {k: v / total_weight for k, v in weights.items()}

        suite_config = {
            "suite_id": suite_id,
            "name": suite_name,
            "description": description or f"Evaluation suite: {suite_name}",
            "evaluation_steps": evaluation_steps,
            "success_thresholds": success_thresholds,
            "weights": weights,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "version": "1.0",
        }

        self.evaluation_suites[suite_id] = suite_config

        return {"suite_id": suite_id, "configuration": suite_config, "total_steps": len(evaluation_steps), "estimated_duration": self._estimate_duration(evaluation_steps)}

    def _get_valid_tools(self) -> List[str]:
        """Get list of valid evaluation tools.

        Returns:
            List[str]: List of supported tool identifiers.
        """
        return [
            # Judge tools
            "judge.evaluate_response",
            "judge.pairwise_comparison",
            "judge.rank_responses",
            "judge.evaluate_with_reference",
            # Prompt tools
            "prompt.evaluate_clarity",
            "prompt.test_consistency",
            "prompt.measure_completeness",
            "prompt.assess_relevance",
            # Agent tools
            "agent.evaluate_tool_use",
            "agent.measure_task_completion",
            "agent.analyze_reasoning",
            "agent.benchmark_performance",
            # Quality tools
            "quality.evaluate_factuality",
            "quality.measure_coherence",
            "quality.assess_toxicity",
        ]

    def _estimate_duration(self, evaluation_steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Estimate evaluation duration.

        Args:
            evaluation_steps: List of evaluation steps to estimate duration for.

        Returns:
            Dict[str, Any]: Duration estimates in seconds and minutes, plus complexity rating.
        """

        # Duration estimates in seconds
        tool_durations = {
            "judge.evaluate_response": 5,
            "judge.pairwise_comparison": 8,
            "judge.rank_responses": 15,
            "judge.evaluate_with_reference": 6,
            "prompt.evaluate_clarity": 3,
            "prompt.test_consistency": 10,
            "prompt.measure_completeness": 4,
            "prompt.assess_relevance": 5,
            "agent.evaluate_tool_use": 2,
            "agent.measure_task_completion": 4,
            "agent.analyze_reasoning": 7,
            "agent.benchmark_performance": 20,
            "quality.evaluate_factuality": 6,
            "quality.measure_coherence": 3,
            "quality.assess_toxicity": 2,
        }

        total_seconds = sum(tool_durations.get(step.get("tool"), 5) for step in evaluation_steps)

        return {"estimated_seconds": total_seconds, "estimated_minutes": round(total_seconds / 60, 1), "complexity": "low" if total_seconds < 30 else "medium" if total_seconds < 120 else "high"}

    async def run_evaluation(
        self,
        suite_id: str,
        test_data: Dict[str, Any],
        parallel_execution: bool = True,
        save_results: bool = True,
        max_concurrent: int = 3,
    ) -> Dict[str, Any]:
        """Execute evaluation suite on data.

        Args:
            suite_id: Which suite to run
            test_data: Inputs to evaluate
            parallel_execution: Run concurrently
            save_results: Persistence options
            max_concurrent: Maximum concurrent evaluations

        Returns:
            Evaluation results

        Raises:
            ValueError: If evaluation suite not found
        """
        if suite_id not in self.evaluation_suites:
            raise ValueError(f"Evaluation suite not found: {suite_id}")

        suite_config = self.evaluation_suites[suite_id]
        evaluation_steps = suite_config["evaluation_steps"]

        start_time = datetime.now(tz=timezone.utc)
        results_id = str(uuid.uuid4())

        # Run evaluation steps
        if parallel_execution:
            step_results = await self._run_steps_parallel(evaluation_steps, test_data, max_concurrent)
        else:
            step_results = await self._run_steps_sequential(evaluation_steps, test_data)

        end_time = datetime.now(tz=timezone.utc)
        duration = (end_time - start_time).total_seconds()

        # Calculate overall score
        overall_score = self._calculate_overall_score(step_results, suite_config["weights"])

        # Check success criteria
        pass_fail_status = self._check_success_criteria(step_results, suite_config["success_thresholds"])

        # Generate detailed report
        detailed_results = {
            "results_id": results_id,
            "suite_id": suite_id,
            "suite_name": suite_config["name"],
            "test_data_summary": self._summarize_test_data(test_data),
            "step_results": step_results,
            "overall_score": overall_score,
            "pass_fail_status": pass_fail_status,
            "execution_info": {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
                "parallel_execution": parallel_execution,
                "max_concurrent": max_concurrent,
            },
            "summary": self._generate_result_summary(step_results, overall_score, pass_fail_status),
        }

        # Save results if requested
        if save_results:
            self.evaluation_results[results_id] = detailed_results

        return detailed_results

    async def _run_steps_parallel(self, steps: List[Dict[str, Any]], test_data: Dict[str, Any], max_concurrent: int) -> List[Dict[str, Any]]:
        """Run evaluation steps in parallel.

        Args:
            steps: List of evaluation steps to execute.
            test_data: Test data to pass to each step.
            max_concurrent: Maximum number of concurrent executions.

        Returns:
            List[Dict[str, Any]]: List of step execution results.
        """

        semaphore = asyncio.Semaphore(max_concurrent)

        async def run_single_step(step: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                return await self._execute_evaluation_step(step, test_data)

        tasks = [run_single_step(step) for step in steps]
        return await asyncio.gather(*tasks)

    async def _run_steps_sequential(self, steps: List[Dict[str, Any]], test_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Run evaluation steps sequentially.

        Args:
            steps: List of evaluation steps to execute.
            test_data: Test data to pass to each step.

        Returns:
            List[Dict[str, Any]]: List of step execution results.
        """

        results = []
        for step in steps:
            result = await self._execute_evaluation_step(step, test_data)
            results.append(result)

        return results

    async def _execute_evaluation_step(self, step: Dict[str, Any], test_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single evaluation step.

        Args:
            step: Evaluation step configuration
            test_data: Data to evaluate

        Returns:
            Step execution result

        Raises:
            ValueError: If unknown tool type specified
        """

        tool = step["tool"]
        params = step.get("parameters", {})

        # Merge test_data with step parameters
        combined_params = {**test_data, **params}

        start_time = datetime.now(tz=timezone.utc)

        try:
            # Route to appropriate tool
            if tool.startswith("judge."):
                result = await self._execute_judge_tool(tool, combined_params)
            elif tool.startswith("prompt."):
                result = await self._execute_prompt_tool(tool, combined_params)
            elif tool.startswith("agent."):
                result = await self._execute_agent_tool(tool, combined_params)
            elif tool.startswith("quality."):
                result = await self._execute_quality_tool(tool, combined_params)
            else:
                raise ValueError(f"Unknown tool type: {tool}")

            success = True
            error = None

        except Exception as e:
            result = {"error": str(e)}
            success = False
            error = str(e)

        end_time = datetime.now(tz=timezone.utc)
        duration = (end_time - start_time).total_seconds()

        return {"tool": tool, "success": success, "result": result, "error": error, "execution_time": duration, "parameters_used": combined_params, "weight": step.get("weight", 1.0)}

    async def _execute_judge_tool(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute judge tool.

        Args:
            tool: Judge tool identifier
            params: Tool parameters

        Returns:
            Tool execution result

        Raises:
            ValueError: If unknown judge tool specified
        """

        if tool == "judge.evaluate_response":
            return await self.judge_tools.evaluate_response(**params)
        if tool == "judge.pairwise_comparison":
            return await self.judge_tools.pairwise_comparison(**params)
        if tool == "judge.rank_responses":
            return await self.judge_tools.rank_responses(**params)
        if tool == "judge.evaluate_with_reference":
            return await self.judge_tools.evaluate_with_reference(**params)
        raise ValueError(f"Unknown judge tool: {tool}")

    async def _execute_prompt_tool(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute prompt tool.

        Args:
            tool: Prompt tool identifier
            params: Tool parameters

        Returns:
            Tool execution result

        Raises:
            ValueError: If unknown prompt tool specified
        """

        if tool == "prompt.evaluate_clarity":
            return await self.prompt_tools.evaluate_clarity(**params)
        if tool == "prompt.test_consistency":
            return await self.prompt_tools.test_consistency(**params)
        if tool == "prompt.measure_completeness":
            return await self.prompt_tools.measure_completeness(**params)
        if tool == "prompt.assess_relevance":
            return await self.prompt_tools.assess_relevance(**params)
        raise ValueError(f"Unknown prompt tool: {tool}")

    async def _execute_agent_tool(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agent tool.

        Args:
            tool: Agent tool identifier
            params: Tool parameters

        Returns:
            Tool execution result

        Raises:
            ValueError: If unknown agent tool specified
        """

        if tool == "agent.evaluate_tool_use":
            return await self.agent_tools.evaluate_tool_use(**params)
        if tool == "agent.measure_task_completion":
            return await self.agent_tools.measure_task_completion(**params)
        if tool == "agent.analyze_reasoning":
            return await self.agent_tools.analyze_reasoning(**params)
        if tool == "agent.benchmark_performance":
            return await self.agent_tools.benchmark_performance(**params)
        raise ValueError(f"Unknown agent tool: {tool}")

    async def _execute_quality_tool(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute quality tool.

        Args:
            tool: Quality tool identifier
            params: Tool parameters

        Returns:
            Tool execution result

        Raises:
            ValueError: If unknown quality tool specified
        """

        if tool == "quality.evaluate_factuality":
            return await self.quality_tools.evaluate_factuality(**params)
        if tool == "quality.measure_coherence":
            return await self.quality_tools.measure_coherence(**params)
        if tool == "quality.assess_toxicity":
            return await self.quality_tools.assess_toxicity(**params)
        raise ValueError(f"Unknown quality tool: {tool}")

    def _calculate_overall_score(self, step_results: List[Dict[str, Any]], weights: Dict[str, float]) -> float:
        """Calculate weighted overall score.

        Args:
            step_results: List of step execution results.
            weights: Weight dictionary for different tools.

        Returns:
            float: Weighted overall score between 0.0 and 1.0.
        """

        total_weighted_score = 0.0
        total_weight = 0.0

        for step_result in step_results:
            if not step_result["success"]:
                continue  # Skip failed steps

            tool = step_result["tool"]
            weight = weights.get(tool, step_result.get("weight", 1.0))

            # Extract score from result
            score = self._extract_score_from_result(step_result["result"])

            total_weighted_score += score * weight
            total_weight += weight

        return total_weighted_score / total_weight if total_weight > 0 else 0.0

    def _extract_score_from_result(self, result: Dict[str, Any]) -> float:
        """Extract numeric score from evaluation result.

        Args:
            result: Evaluation result dictionary.

        Returns:
            float: Extracted numeric score, defaulting to 0.5 if not found.
        """

        # Try common score field names
        score_fields = ["overall_score", "score", "clarity_score", "coherence_score", "factuality_score", "completion_rate", "accuracy", "efficiency"]

        for field in score_fields:
            if field in result:
                score = result[field]
                if isinstance(score, (int, float)):
                    return float(score)

        # If no direct score, try to calculate from sub-scores
        if "scores" in result and isinstance(result["scores"], dict):
            scores = [v for v in result["scores"].values() if isinstance(v, (int, float))]
            if scores:
                return statistics.mean(scores) / 5.0  # Normalize assuming 1-5 scale

        # Default fallback
        return 0.5

    def _check_success_criteria(self, step_results: List[Dict[str, Any]], thresholds: Dict[str, float]) -> Dict[str, Any]:
        """Check if evaluation meets success criteria.

        Args:
            step_results: List of step execution results.
            thresholds: Success threshold values for different criteria.

        Returns:
            Dict[str, Any]: Pass/fail status with detailed breakdown.
        """

        passed_criteria = {}
        failed_criteria = {}

        for criterion, threshold in thresholds.items():
            if criterion == "overall":
                # Check overall score
                overall_score = self._calculate_overall_score(step_results, {step["tool"]: 1.0 for step in step_results})
                passed = overall_score >= threshold
            else:
                # Check specific tool result
                tool_result = next((step for step in step_results if step["tool"] == criterion), None)
                if tool_result and tool_result["success"]:
                    score = self._extract_score_from_result(tool_result["result"])
                    passed = score >= threshold
                else:
                    passed = False

            if passed:
                passed_criteria[criterion] = threshold
            else:
                failed_criteria[criterion] = threshold

        all_passed = len(failed_criteria) == 0

        return {"passed": all_passed, "passed_criteria": passed_criteria, "failed_criteria": failed_criteria, "success_rate": len(passed_criteria) / len(thresholds) if thresholds else 1.0}

    def _summarize_test_data(self, test_data: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize test data for reporting.

        Args:
            test_data: Test data dictionary to summarize.

        Returns:
            Dict[str, Any]: Summary of test data with type and size information.
        """

        summary = {}

        for key, value in test_data.items():
            if isinstance(value, str):
                summary[key] = {"type": "string", "length": len(value), "preview": value[:100] + "..." if len(value) > 100 else value}
            elif isinstance(value, list):
                summary[key] = {"type": "list", "length": len(value), "item_types": list(set(type(item).__name__ for item in value))}
            elif isinstance(value, dict):
                summary[key] = {"type": "dict", "keys": len(value), "key_names": list(value.keys())[:10]}  # First 10 keys
            else:
                summary[key] = {"type": type(value).__name__, "value": str(value)[:100]}

        return summary

    def _generate_result_summary(self, step_results: List[Dict[str, Any]], overall_score: float, pass_fail_status: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a summary of evaluation results.

        Args:
            step_results: List of step execution results.
            overall_score: Calculated overall score.
            pass_fail_status: Pass/fail status information.

        Returns:
            Dict[str, Any]: Comprehensive summary of evaluation performance.
        """

        successful_steps = [step for step in step_results if step["success"]]
        failed_steps = [step for step in step_results if not step["success"]]

        total_time = sum(step["execution_time"] for step in step_results)

        # Performance analysis
        slowest_step = max(step_results, key=lambda x: x["execution_time"])
        fastest_step = min(step_results, key=lambda x: x["execution_time"])

        return {
            "overall_score": overall_score,
            "passed": pass_fail_status["passed"],
            "success_rate": pass_fail_status["success_rate"],
            "total_steps": len(step_results),
            "successful_steps": len(successful_steps),
            "failed_steps": len(failed_steps),
            "total_execution_time": total_time,
            "average_step_time": total_time / len(step_results) if step_results else 0,
            "slowest_step": {"tool": slowest_step["tool"], "time": slowest_step["execution_time"]},
            "fastest_step": {"tool": fastest_step["tool"], "time": fastest_step["execution_time"]},
            "performance_grade": self._get_performance_grade(overall_score, pass_fail_status["success_rate"]),
        }

    def _get_performance_grade(self, overall_score: float, success_rate: float) -> str:
        """Get letter grade for performance.

        Args:
            overall_score: Overall evaluation score.
            success_rate: Success rate of evaluation criteria.

        Returns:
            str: Letter grade (A, B, C, D, or F) based on combined score.
        """

        combined_score = (overall_score + success_rate) / 2

        if combined_score >= 0.9:
            return "A"
        if combined_score >= 0.8:
            return "B"
        if combined_score >= 0.7:
            return "C"
        if combined_score >= 0.6:
            return "D"
        return "F"

    async def compare_evaluations(
        self,
        evaluation_ids: List[str],
        comparison_type: str = "improvement",
        significance_test: bool = True,
    ) -> Dict[str, Any]:
        """Compare results across multiple evaluation runs.

        Args:
            evaluation_ids: Results to compare
            comparison_type: Type of comparison ('regression', 'improvement', 'a_b')
            significance_test: Whether to run statistical validation

        Returns:
            Comparison analysis

        Raises:
            ValueError: If fewer than 2 evaluations provided or evaluation not found
        """
        if len(evaluation_ids) < 2:
            raise ValueError("Need at least 2 evaluations to compare")

        # Retrieve evaluation results
        evaluations = []
        for eval_id in evaluation_ids:
            if eval_id not in self.evaluation_results:
                raise ValueError(f"Evaluation result not found: {eval_id}")
            evaluations.append(self.evaluation_results[eval_id])

        # Create comparison matrix
        comparison_matrix = self._create_comparison_matrix(evaluations)

        # Perform statistical analysis
        statistical_analysis = {}
        if significance_test:
            statistical_analysis = self._perform_statistical_analysis(evaluations, comparison_type)

        # Trend analysis
        trend_analysis = self._analyze_trends(evaluations, comparison_type)

        # Generate recommendations
        recommendations = self._generate_comparison_recommendations(comparison_matrix, trend_analysis, statistical_analysis)

        return {
            "comparison_matrix": comparison_matrix,
            "statistical_significance": statistical_analysis,
            "trend_analysis": trend_analysis,
            "recommendations": recommendations,
            "comparison_type": comparison_type,
            "evaluations_compared": len(evaluation_ids),
            "comparison_summary": self._summarize_comparison(comparison_matrix, trend_analysis),
        }

    def _create_comparison_matrix(self, evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create side-by-side comparison matrix.

        Args:
            evaluations: List of evaluation results to compare.

        Returns:
            Dict[str, Any]: Comparison matrix with scores, times, and step comparisons.
        """

        matrix = {
            "evaluation_ids": [eval_data["results_id"] for eval_data in evaluations],
            "suite_names": [eval_data["suite_name"] for eval_data in evaluations],
            "overall_scores": [eval_data["overall_score"] for eval_data in evaluations],
            "pass_fail_status": [eval_data["pass_fail_status"]["passed"] for eval_data in evaluations],
            "execution_times": [eval_data["execution_info"]["duration_seconds"] for eval_data in evaluations],
            "step_comparisons": {},
        }

        # Compare individual steps
        all_tools = set()
        for evaluation in evaluations:
            for step in evaluation["step_results"]:
                all_tools.add(step["tool"])

        for tool in all_tools:
            tool_scores = []
            for evaluation in evaluations:
                step_result = next((step for step in evaluation["step_results"] if step["tool"] == tool), None)
                if step_result and step_result["success"]:
                    score = self._extract_score_from_result(step_result["result"])
                    tool_scores.append(score)
                else:
                    tool_scores.append(None)

            matrix["step_comparisons"][tool] = tool_scores

        return matrix

    def _perform_statistical_analysis(self, evaluations: List[Dict[str, Any]], comparison_type: str) -> Dict[str, Any]:  # pylint: disable=unused-argument
        """Perform statistical significance testing.

        Args:
            evaluations: List of evaluation results to analyze.
            comparison_type: Type of comparison being performed.

        Returns:
            Dict[str, Any]: Statistical analysis results including significance and p-values.
        """

        scores = [eval_data["overall_score"] for eval_data in evaluations]

        if len(scores) != 2:
            return {"note": "Statistical testing requires exactly 2 evaluations"}

        score1, score2 = scores
        difference = score2 - score1

        # Simple significance test (in real implementation, use proper statistical tests)
        # Assuming normal distribution and known variance

        # Mock significance calculation
        abs_difference = abs(difference)

        if abs_difference > 0.1:
            significance = "high"
            p_value = 0.01
        elif abs_difference > 0.05:
            significance = "medium"
            p_value = 0.05
        else:
            significance = "low"
            p_value = 0.2

        return {
            "difference": difference,
            "absolute_difference": abs_difference,
            "significance_level": significance,
            "p_value": p_value,
            "is_significant": p_value < 0.05,
            "interpretation": self._interpret_significance(difference, significance),
        }

    def _interpret_significance(self, difference: float, significance: str) -> str:
        """Interpret statistical significance results.

        Args:
            difference: Numerical difference between scores.
            significance: Significance level ('low', 'medium', 'high').

        Returns:
            str: Human-readable interpretation of statistical results.
        """

        if significance == "low":
            return "No statistically significant difference detected"

        direction = "improvement" if difference > 0 else "regression"

        if significance == "high":
            return f"Statistically significant {direction} detected"
        return f"Moderate {direction} detected"

    def _analyze_trends(self, evaluations: List[Dict[str, Any]], comparison_type: str) -> Dict[str, Any]:  # pylint: disable=unused-argument
        """Analyze performance trends over time.

        Args:
            evaluations: List of evaluation results to analyze.
            comparison_type: Type of comparison being performed.

        Returns:
            Dict[str, Any]: Trend analysis including direction, volatility, and consistency.
        """

        # Sort by timestamp
        sorted_evals = sorted(evaluations, key=lambda x: x["execution_info"]["start_time"])

        scores = [eval_data["overall_score"] for eval_data in sorted_evals]
        timestamps = [eval_data["execution_info"]["start_time"] for eval_data in sorted_evals]

        # Calculate trend
        if len(scores) < 2:
            trend_direction = "stable"
        else:
            first_score = scores[0]
            last_score = scores[-1]

            if last_score > first_score + 0.05:
                trend_direction = "improving"
            elif last_score < first_score - 0.05:
                trend_direction = "declining"
            else:
                trend_direction = "stable"

        # Calculate volatility
        if len(scores) > 1:
            volatility = statistics.stdev(scores)
        else:
            volatility = 0.0

        return {
            "trend_direction": trend_direction,
            "score_range": {"min": min(scores), "max": max(scores)},
            "volatility": volatility,
            "consistency": "high" if volatility < 0.1 else "medium" if volatility < 0.2 else "low",
            "scores_over_time": list(zip(timestamps, scores)),
        }

    def _generate_comparison_recommendations(self, comparison_matrix: Dict[str, Any], trend_analysis: Dict[str, Any], statistical_analysis: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on comparison.

        Args:
            comparison_matrix: Matrix of comparison results.
            trend_analysis: Trend analysis results.
            statistical_analysis: Statistical significance analysis.

        Returns:
            List[str]: List of recommendation messages based on comparison analysis.
        """

        recommendations = []

        # Overall score recommendations
        scores = comparison_matrix["overall_scores"]
        if len(scores) >= 2:
            latest_score = scores[-1]
            previous_score = scores[-2]

            if latest_score > previous_score + 0.05:
                recommendations.append("Performance improvement detected - maintain current approach")
            elif latest_score < previous_score - 0.05:
                recommendations.append("Performance decline detected - investigate changes")

        # Trend recommendations
        if trend_analysis["trend_direction"] == "improving":
            recommendations.append("Positive trend - continue current optimization strategy")
        elif trend_analysis["trend_direction"] == "declining":
            recommendations.append("Negative trend - review recent changes and interventions")

        # Consistency recommendations
        if trend_analysis["consistency"] == "low":
            recommendations.append("High volatility detected - focus on improving consistency")
        elif trend_analysis["consistency"] == "high":
            recommendations.append("Good consistency maintained - results are reliable")

        # Statistical significance recommendations
        if statistical_analysis.get("is_significant"):
            recommendations.append("Statistically significant changes detected - validate with additional testing")

        return recommendations

    def _summarize_comparison(self, comparison_matrix: Dict[str, Any], trend_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize comparison results.

        Args:
            comparison_matrix: Matrix of comparison results.
            trend_analysis: Trend analysis results.

        Returns:
            Dict[str, Any]: Summary of comparison including best/worst performance and trends.
        """

        scores = comparison_matrix["overall_scores"]

        return {
            "best_performance": max(scores),
            "worst_performance": min(scores),
            "average_performance": statistics.mean(scores),
            "performance_range": max(scores) - min(scores),
            "trend": trend_analysis["trend_direction"],
            "consistency": trend_analysis["consistency"],
            "total_evaluations": len(scores),
        }

    def get_evaluation_suite(self, suite_id: str) -> Optional[Dict[str, Any]]:
        """Get evaluation suite configuration.

        Args:
            suite_id: Unique identifier for the evaluation suite.

        Returns:
            Optional[Dict[str, Any]]: Suite configuration if found, None otherwise.
        """
        return self.evaluation_suites.get(suite_id)

    def get_evaluation_result(self, results_id: str) -> Optional[Dict[str, Any]]:
        """Get evaluation results.

        Args:
            results_id: Unique identifier for the evaluation results.

        Returns:
            Optional[Dict[str, Any]]: Evaluation results if found, None otherwise.
        """
        return self.evaluation_results.get(results_id)

    def list_evaluation_suites(self) -> List[Dict[str, Any]]:
        """List all evaluation suites.

        Returns:
            List[Dict[str, Any]]: List of suite summaries with basic information.
        """
        return [
            {"suite_id": suite_id, "name": config["name"], "description": config["description"], "created_at": config["created_at"], "steps": len(config["evaluation_steps"])}
            for suite_id, config in self.evaluation_suites.items()
        ]

    def list_evaluation_results(self) -> List[Dict[str, Any]]:
        """List all evaluation results.

        Returns:
            List[Dict[str, Any]]: List of result summaries with basic information.
        """
        return [
            {
                "results_id": results_id,
                "suite_name": result["suite_name"],
                "overall_score": result["overall_score"],
                "passed": result["pass_fail_status"]["passed"],
                "execution_time": result["execution_info"]["start_time"],
            }
            for results_id, result in self.evaluation_results.items()
        ]
