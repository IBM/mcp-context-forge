# -*- coding: utf-8 -*-
"""
Statistical hypothesis testing functionality.
"""

# Standard
import logging
from typing import Any
import warnings

# Third-Party
import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=RuntimeWarning)


class HypothesisTests:
    """Provides statistical hypothesis testing capabilities."""

    def __init__(self):
        """Initialize the hypothesis testing module."""

    def perform_test(
        self,
        df: pd.DataFrame,
        test_type: str,
        columns: list[str],
        groupby_column: str | None = None,
        hypothesis: str | None = None,
        alpha: float = 0.05,
        alternative: str = "two-sided",
    ) -> dict[str, Any]:
        """
        Perform statistical hypothesis test.

        Args:
            df: DataFrame containing the data
            test_type: Type of test (t_test, chi_square, anova, regression)
            columns: Columns to test
            groupby_column: Column for grouping (if applicable)
            hypothesis: Hypothesis statement
            alpha: Significance level
            alternative: Alternative hypothesis direction

        Returns:
            Dictionary containing test results
        """
        logger.info(f"Performing {test_type} test on columns {columns}")

        test_methods = {
            "t_test": self._perform_t_test,
            "chi_square": self._perform_chi_square,
            "anova": self._perform_anova,
            "regression": self._perform_regression,
            "mann_whitney": self._perform_mann_whitney,
            "wilcoxon": self._perform_wilcoxon,
            "kruskal_wallis": self._perform_kruskal_wallis,
        }

        if test_type not in test_methods:
            raise ValueError(f"Unsupported test type: {test_type}")

        return test_methods[test_type](df, columns, groupby_column, hypothesis, alpha, alternative)

    def _perform_t_test(
        self,
        df: pd.DataFrame,
        columns: list[str],
        groupby_column: str | None,
        hypothesis: str | None,
        alpha: float,
        alternative: str,
    ) -> dict[str, Any]:
        """Perform t-test (one-sample, two-sample, or paired)."""
        if len(columns) != 1:
            raise ValueError("T-test requires exactly one numeric column")

        column = columns[0]
        data = df[column].dropna()

        if groupby_column:
            # Two-sample t-test
            groups = df.groupby(groupby_column)[column].apply(lambda x: x.dropna())
            group_names = list(groups.index)

            if len(group_names) != 2:
                raise ValueError("Two-sample t-test requires exactly 2 groups")

            group1 = groups.iloc[0]
            group2 = groups.iloc[1]

            # Perform independent t-test
            statistic, p_value = stats.ttest_ind(group1, group2, alternative=alternative)

            # Effect size (Cohen's d)
            pooled_std = np.sqrt(((len(group1) - 1) * group1.var() + (len(group2) - 1) * group2.var()) / (len(group1) + len(group2) - 2))
            cohens_d = (group1.mean() - group2.mean()) / pooled_std

            result = {
                "test_type": "Two-sample t-test",
                "statistic": float(statistic),
                "p_value": float(p_value),
                "degrees_of_freedom": len(group1) + len(group2) - 2,
                "effect_size": float(cohens_d),
                "effect_size_interpretation": self._interpret_cohens_d(cohens_d),
                "group1_stats": {
                    "name": str(group_names[0]),
                    "n": len(group1),
                    "mean": float(group1.mean()),
                    "std": float(group1.std()),
                },
                "group2_stats": {
                    "name": str(group_names[1]),
                    "n": len(group2),
                    "mean": float(group2.mean()),
                    "std": float(group2.std()),
                },
            }
        else:
            # One-sample t-test (against population mean of 0)
            statistic, p_value = stats.ttest_1samp(data, 0, alternative=alternative)

            result = {
                "test_type": "One-sample t-test",
                "statistic": float(statistic),
                "p_value": float(p_value),
                "degrees_of_freedom": len(data) - 1,
                "sample_stats": {
                    "n": len(data),
                    "mean": float(data.mean()),
                    "std": float(data.std()),
                },
            }

        # Add common interpretation
        result.update(
            {
                "alpha": alpha,
                "alternative": alternative,
                "significant": p_value < alpha,
                "conclusion": ("Reject null hypothesis" if p_value < alpha else "Fail to reject null hypothesis"),
                "interpretation": self._interpret_p_value(p_value, alpha),
            }
        )

        return result

    def _perform_chi_square(
        self,
        df: pd.DataFrame,
        columns: list[str],
        groupby_column: str | None,
        hypothesis: str | None,
        alpha: float,
        alternative: str,
    ) -> dict[str, Any]:
        """Perform chi-square test of independence."""
        if len(columns) != 2:
            raise ValueError("Chi-square test requires exactly two categorical columns")

        col1, col2 = columns

        # Create contingency table
        contingency_table = pd.crosstab(df[col1], df[col2])

        # Perform chi-square test
        chi2, p_value, dof, expected = stats.chi2_contingency(contingency_table)

        # Cramér's V (effect size)
        n = contingency_table.sum().sum()
        cramers_v = np.sqrt(chi2 / (n * (min(contingency_table.shape) - 1)))

        result = {
            "test_type": "Chi-square test of independence",
            "statistic": float(chi2),
            "p_value": float(p_value),
            "degrees_of_freedom": dof,
            "effect_size": float(cramers_v),
            "effect_size_interpretation": self._interpret_cramers_v(cramers_v),
            "contingency_table": contingency_table.to_dict(),
            "expected_frequencies": pd.DataFrame(
                expected,
                index=contingency_table.index,
                columns=contingency_table.columns,
            ).to_dict(),
            "alpha": alpha,
            "significant": p_value < alpha,
            "conclusion": ("Variables are dependent" if p_value < alpha else "Variables are independent"),
            "interpretation": self._interpret_p_value(p_value, alpha),
        }

        return result

    def _perform_anova(
        self,
        df: pd.DataFrame,
        columns: list[str],
        groupby_column: str | None,
        hypothesis: str | None,
        alpha: float,
        alternative: str,
    ) -> dict[str, Any]:
        """Perform one-way ANOVA."""
        if len(columns) != 1:
            raise ValueError("ANOVA requires exactly one numeric column")
        if not groupby_column:
            raise ValueError("ANOVA requires a groupby column")

        column = columns[0]
        groups = [group[column].dropna() for name, group in df.groupby(groupby_column)]

        if len(groups) < 2:
            raise ValueError("ANOVA requires at least 2 groups")

        # Perform one-way ANOVA
        statistic, p_value = stats.f_oneway(*groups)

        # Calculate group statistics
        group_stats = []
        for i, (name, group) in enumerate(df.groupby(groupby_column)):
            group_data = group[column].dropna()
            group_stats.append(
                {
                    "name": str(name),
                    "n": len(group_data),
                    "mean": float(group_data.mean()),
                    "std": float(group_data.std()),
                    "variance": float(group_data.var()),
                }
            )

        # Effect size (eta-squared)
        overall_mean = df[column].mean()
        ss_between = sum([len(group) * (group.mean() - overall_mean) ** 2 for group in groups])
        ss_total = sum([(x - overall_mean) ** 2 for group in groups for x in group])
        eta_squared = ss_between / ss_total if ss_total > 0 else 0

        result = {
            "test_type": "One-way ANOVA",
            "statistic": float(statistic),
            "p_value": float(p_value),
            "degrees_of_freedom": {
                "between": len(groups) - 1,
                "within": sum(len(group) for group in groups) - len(groups),
            },
            "effect_size": float(eta_squared),
            "effect_size_interpretation": self._interpret_eta_squared(eta_squared),
            "group_stats": group_stats,
            "alpha": alpha,
            "significant": p_value < alpha,
            "conclusion": ("At least one group mean differs" if p_value < alpha else "No significant difference between groups"),
            "interpretation": self._interpret_p_value(p_value, alpha),
        }

        return result

    def _perform_regression(
        self,
        df: pd.DataFrame,
        columns: list[str],
        groupby_column: str | None,
        hypothesis: str | None,
        alpha: float,
        alternative: str,
    ) -> dict[str, Any]:
        """Perform simple linear regression analysis."""
        if len(columns) != 2:
            raise ValueError("Simple regression requires exactly two numeric columns")

        x_col, y_col = columns

        # Remove rows with missing values
        clean_df = df[[x_col, y_col]].dropna()
        if len(clean_df) < 3:
            raise ValueError("Insufficient data for regression analysis")

        x = clean_df[x_col]
        y = clean_df[y_col]

        # Perform linear regression
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

        # Additional statistics
        y_pred = slope * x + intercept
        residuals = y - y_pred

        # R-squared
        r_squared = r_value**2

        # Adjusted R-squared
        n = len(clean_df)
        adj_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - 2)

        # F-statistic for overall model
        np.mean(residuals**2)
        f_stat = r_squared * (n - 2) / (1 - r_squared) if r_squared < 1 else float("inf")

        result = {
            "test_type": "Simple Linear Regression",
            "slope": float(slope),
            "intercept": float(intercept),
            "r_value": float(r_value),
            "r_squared": float(r_squared),
            "adjusted_r_squared": float(adj_r_squared),
            "p_value": float(p_value),
            "standard_error": float(std_err),
            "f_statistic": float(f_stat),
            "degrees_of_freedom": n - 2,
            "residual_stats": {
                "mean": float(residuals.mean()),
                "std": float(residuals.std()),
                "min": float(residuals.min()),
                "max": float(residuals.max()),
            },
            "alpha": alpha,
            "significant": p_value < alpha,
            "conclusion": (f"Significant relationship between {x_col} and {y_col}" if p_value < alpha else "No significant relationship"),
            "interpretation": self._interpret_p_value(p_value, alpha),
        }

        return result

    def _perform_mann_whitney(
        self,
        df: pd.DataFrame,
        columns: list[str],
        groupby_column: str | None,
        hypothesis: str | None,
        alpha: float,
        alternative: str,
    ) -> dict[str, Any]:
        """Perform Mann-Whitney U test (non-parametric alternative to t-test)."""
        if len(columns) != 1:
            raise ValueError("Mann-Whitney test requires exactly one numeric column")
        if not groupby_column:
            raise ValueError("Mann-Whitney test requires a groupby column")

        column = columns[0]
        groups = df.groupby(groupby_column)[column].apply(lambda x: x.dropna())

        if len(groups) != 2:
            raise ValueError("Mann-Whitney test requires exactly 2 groups")

        group1 = groups.iloc[0]
        group2 = groups.iloc[1]

        # Perform Mann-Whitney U test
        statistic, p_value = stats.mannwhitneyu(group1, group2, alternative=alternative)

        result = {
            "test_type": "Mann-Whitney U test",
            "statistic": float(statistic),
            "p_value": float(p_value),
            "group1_stats": {
                "name": str(groups.index[0]),
                "n": len(group1),
                "median": float(group1.median()),
                "mean_rank": float(stats.rankdata(np.concatenate([group1, group2]))[: len(group1)].mean()),
            },
            "group2_stats": {
                "name": str(groups.index[1]),
                "n": len(group2),
                "median": float(group2.median()),
                "mean_rank": float(stats.rankdata(np.concatenate([group1, group2]))[len(group1) :].mean()),
            },
            "alpha": alpha,
            "alternative": alternative,
            "significant": p_value < alpha,
            "conclusion": ("Groups have different distributions" if p_value < alpha else "Groups have similar distributions"),
            "interpretation": self._interpret_p_value(p_value, alpha),
        }

        return result

    def _perform_wilcoxon(
        self,
        df: pd.DataFrame,
        columns: list[str],
        groupby_column: str | None,
        hypothesis: str | None,
        alpha: float,
        alternative: str,
    ) -> dict[str, Any]:
        """Perform Wilcoxon signed-rank test."""
        if len(columns) != 2:
            raise ValueError("Wilcoxon test requires exactly two numeric columns")

        col1, col2 = columns
        data1 = df[col1].dropna()
        data2 = df[col2].dropna()

        # Ensure same length
        min_len = min(len(data1), len(data2))
        data1 = data1.iloc[:min_len]
        data2 = data2.iloc[:min_len]

        # Perform Wilcoxon signed-rank test
        statistic, p_value = stats.wilcoxon(data1, data2, alternative=alternative)

        result = {
            "test_type": "Wilcoxon signed-rank test",
            "statistic": float(statistic),
            "p_value": float(p_value),
            "n_pairs": min_len,
            "alpha": alpha,
            "alternative": alternative,
            "significant": p_value < alpha,
            "conclusion": ("Significant difference between paired samples" if p_value < alpha else "No significant difference"),
            "interpretation": self._interpret_p_value(p_value, alpha),
        }

        return result

    def _perform_kruskal_wallis(
        self,
        df: pd.DataFrame,
        columns: list[str],
        groupby_column: str | None,
        hypothesis: str | None,
        alpha: float,
        alternative: str,
    ) -> dict[str, Any]:
        """Perform Kruskal-Wallis test (non-parametric alternative to ANOVA)."""
        if len(columns) != 1:
            raise ValueError("Kruskal-Wallis test requires exactly one numeric column")
        if not groupby_column:
            raise ValueError("Kruskal-Wallis test requires a groupby column")

        column = columns[0]
        groups = [group[column].dropna() for name, group in df.groupby(groupby_column)]

        if len(groups) < 2:
            raise ValueError("Kruskal-Wallis test requires at least 2 groups")

        # Perform Kruskal-Wallis test
        statistic, p_value = stats.kruskal(*groups)

        result = {
            "test_type": "Kruskal-Wallis test",
            "statistic": float(statistic),
            "p_value": float(p_value),
            "degrees_of_freedom": len(groups) - 1,
            "alpha": alpha,
            "significant": p_value < alpha,
            "conclusion": ("At least one group differs" if p_value < alpha else "No significant difference between groups"),
            "interpretation": self._interpret_p_value(p_value, alpha),
        }

        return result

    def _interpret_p_value(self, p_value: float, alpha: float) -> str:
        """Interpret p-value in context."""
        if p_value < 0.001:
            return "Very strong evidence against null hypothesis"
        elif p_value < 0.01:
            return "Strong evidence against null hypothesis"
        elif p_value < alpha:
            return "Moderate evidence against null hypothesis"
        elif p_value < 0.1:
            return "Weak evidence against null hypothesis"
        else:
            return "Insufficient evidence against null hypothesis"

    def _interpret_cohens_d(self, d: float) -> str:
        """Interpret Cohen's d effect size."""
        abs_d = abs(d)
        if abs_d < 0.2:
            return "negligible"
        elif abs_d < 0.5:
            return "small"
        elif abs_d < 0.8:
            return "medium"
        else:
            return "large"

    def _interpret_cramers_v(self, v: float) -> str:
        """Interpret Cramér's V effect size."""
        if v < 0.1:
            return "negligible"
        elif v < 0.3:
            return "small"
        elif v < 0.5:
            return "medium"
        else:
            return "large"

    def _interpret_eta_squared(self, eta_sq: float) -> str:
        """Interpret eta-squared effect size."""
        if eta_sq < 0.01:
            return "negligible"
        elif eta_sq < 0.06:
            return "small"
        elif eta_sq < 0.14:
            return "medium"
        else:
            return "large"
