# -*- coding: utf-8 -*-
"""
Data visualization functionality using matplotlib, seaborn, and plotly.
"""

# Standard
import logging
from pathlib import Path
from typing import Any

# Third-Party
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# Optional plotly import
try:
    # Third-Party
    import plotly.express as px

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

logger = logging.getLogger(__name__)


class DataVisualizer:
    """Provides comprehensive data visualization capabilities."""

    SUPPORTED_PLOT_TYPES = {
        "histogram",
        "scatter",
        "box",
        "heatmap",
        "line",
        "bar",
        "violin",
        "pair",
        "time_series",
        "distribution",
        "correlation",
    }

    SUPPORTED_FORMATS = {"png", "svg", "pdf", "html", "jpeg"}

    def __init__(
        self,
        output_dir: str = "./plots",
        default_style: str = "seaborn-v0_8",
        default_figsize: tuple[int, int] = (10, 6),
        default_dpi: int = 300,
    ):
        """
        Initialize the data visualizer.

        Args:
            output_dir: Directory to save plots
            default_style: Default matplotlib style
            default_figsize: Default figure size
            default_dpi: Default DPI for saved images
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.default_style = default_style
        self.default_figsize = default_figsize
        self.default_dpi = default_dpi

        # Set up matplotlib and seaborn styles
        self._setup_styles()

    def create_visualization(
        self,
        df: pd.DataFrame,
        plot_type: str,
        x_column: str | None = None,
        y_column: str | None = None,
        color_column: str | None = None,
        facet_column: str | None = None,
        title: str | None = None,
        save_format: str = "png",
        interactive: bool = False,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Create a visualization based on the specified parameters.

        Args:
            df: DataFrame containing the data
            plot_type: Type of plot to create
            x_column: Column for x-axis
            y_column: Column for y-axis (if applicable)
            color_column: Column for color grouping
            facet_column: Column for faceting/subplots
            title: Plot title
            save_format: Format to save the plot
            interactive: Whether to create an interactive plot
            **kwargs: Additional plot-specific parameters

        Returns:
            Dictionary containing plot information and file path
        """
        logger.info(f"Creating {plot_type} visualization")

        if plot_type not in self.SUPPORTED_PLOT_TYPES:
            raise ValueError(f"Unsupported plot type: {plot_type}")

        if save_format not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {save_format}")

        # Validate x_column requirement based on plot type
        if plot_type != "heatmap" and x_column is None:
            raise ValueError(f"x_column is required for plot type: {plot_type}")

        # Use interactive plotting if requested and available
        if interactive and PLOTLY_AVAILABLE and save_format == "html":
            return self._create_interactive_plot(
                df,
                plot_type,
                x_column,
                y_column,
                color_column,
                facet_column,
                title,
                **kwargs,
            )
        else:
            return self._create_static_plot(
                df,
                plot_type,
                x_column,
                y_column,
                color_column,
                facet_column,
                title,
                save_format,
                **kwargs,
            )

    def _setup_styles(self):
        """Setup matplotlib and seaborn styles."""
        try:
            # Set matplotlib style
            available_styles = plt.style.available
            if self.default_style in available_styles:
                plt.style.use(self.default_style)
            else:
                plt.style.use("default")

            # Set seaborn style
            sns.set_style("whitegrid")
            sns.set_palette("husl")

        except Exception as e:
            logger.warning(f"Could not set style: {e}")

    def _create_static_plot(
        self,
        df: pd.DataFrame,
        plot_type: str,
        x_column: str,
        y_column: str | None,
        color_column: str | None,
        facet_column: str | None,
        title: str | None,
        save_format: str,
        **kwargs,
    ) -> dict[str, Any]:
        """Create a static plot using matplotlib/seaborn."""

        plot_methods = {
            "histogram": self._plot_histogram,
            "scatter": self._plot_scatter,
            "box": self._plot_box,
            "heatmap": self._plot_heatmap,
            "line": self._plot_line,
            "bar": self._plot_bar,
            "violin": self._plot_violin,
            "pair": self._plot_pairplot,
            "time_series": self._plot_time_series,
            "distribution": self._plot_distribution,
            "correlation": self._plot_correlation,
        }

        if plot_type not in plot_methods:
            raise ValueError(f"Plot method not implemented: {plot_type}")

        # Create the plot
        fig, ax, plot_info = plot_methods[plot_type](
            df, x_column, y_column, color_column, facet_column, title, **kwargs
        )

        # Save the plot
        filename = self._generate_filename(plot_type, save_format)
        file_path = self.output_dir / filename

        try:
            fig.savefig(
                file_path, format=save_format, dpi=self.default_dpi, bbox_inches="tight"
            )
            plt.close(fig)

            result = {
                "plot_type": plot_type,
                "file_path": str(file_path),
                "filename": filename,
                "format": save_format,
                "title": title,
                "success": True,
                "interactive": False,
                "metadata": plot_info,
            }

        except Exception as e:
            plt.close(fig)
            result = {"plot_type": plot_type, "success": False, "error": str(e)}

        return result

    def _create_interactive_plot(
        self,
        df: pd.DataFrame,
        plot_type: str,
        x_column: str,
        y_column: str | None,
        color_column: str | None,
        facet_column: str | None,
        title: str | None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create an interactive plot using plotly."""
        if not PLOTLY_AVAILABLE:
            raise ImportError("Plotly not available for interactive plots")

        interactive_methods = {
            "histogram": self._plotly_histogram,
            "scatter": self._plotly_scatter,
            "box": self._plotly_box,
            "line": self._plotly_line,
            "bar": self._plotly_bar,
            "heatmap": self._plotly_heatmap,
            "time_series": self._plotly_time_series,
        }

        if plot_type not in interactive_methods:
            # Fall back to static plot
            return self._create_static_plot(
                df,
                plot_type,
                x_column,
                y_column,
                color_column,
                facet_column,
                title,
                "html",
                **kwargs,
            )

        try:
            fig, plot_info = interactive_methods[plot_type](
                df, x_column, y_column, color_column, facet_column, title, **kwargs
            )

            # Save the interactive plot
            filename = self._generate_filename(plot_type, "html")
            file_path = self.output_dir / filename

            fig.write_html(str(file_path))

            return {
                "plot_type": plot_type,
                "file_path": str(file_path),
                "filename": filename,
                "format": "html",
                "title": title,
                "success": True,
                "interactive": True,
                "metadata": plot_info,
            }

        except Exception as e:
            return {"plot_type": plot_type, "success": False, "error": str(e)}

    def _plot_histogram(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create histogram plot."""
        figsize = kwargs.get("figsize", self.default_figsize)
        bins = kwargs.get("bins", 30)
        alpha = kwargs.get("alpha", 0.7)

        if facet_column and facet_column in df.columns:
            # Create subplots for each facet
            unique_facets = df[facet_column].unique()
            n_facets = len(unique_facets)
            cols = min(3, n_facets)
            rows = (n_facets + cols - 1) // cols

            fig, axes = plt.subplots(
                rows, cols, figsize=(figsize[0] * cols, figsize[1] * rows)
            )
            axes = axes.flatten() if n_facets > 1 else [axes]

            for i, facet in enumerate(unique_facets):
                if i < len(axes):
                    facet_data = df[df[facet_column] == facet][x_column].dropna()
                    axes[i].hist(facet_data, bins=bins, alpha=alpha, edgecolor="black")
                    axes[i].set_title(f"{facet}")
                    axes[i].set_xlabel(x_column)
                    axes[i].set_ylabel("Frequency")

            # Hide empty subplots
            for i in range(len(unique_facets), len(axes)):
                axes[i].set_visible(False)

        else:
            fig, ax = plt.subplots(figsize=figsize)

            if color_column and color_column in df.columns:
                for group in df[color_column].unique():
                    group_data = df[df[color_column] == group][x_column].dropna()
                    ax.hist(
                        group_data,
                        bins=bins,
                        alpha=alpha,
                        label=str(group),
                        edgecolor="black",
                    )
                ax.legend()
            else:
                ax.hist(
                    df[x_column].dropna(), bins=bins, alpha=alpha, edgecolor="black"
                )

            ax.set_xlabel(x_column)
            ax.set_ylabel("Frequency")
            axes = ax

        if title:
            fig.suptitle(title, fontsize=14)
        else:
            fig.suptitle(f"Histogram of {x_column}", fontsize=14)

        plt.tight_layout()

        plot_info = {
            "x_column": x_column,
            "data_points": len(df[x_column].dropna()),
            "bins": bins,
        }

        return fig, axes, plot_info

    def _plot_scatter(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create scatter plot."""
        if not y_column:
            raise ValueError("Scatter plot requires y_column")

        figsize = kwargs.get("figsize", self.default_figsize)
        alpha = kwargs.get("alpha", 0.7)

        fig, ax = plt.subplots(figsize=figsize)

        if color_column and color_column in df.columns:
            # Check if color column is numeric or categorical
            if pd.api.types.is_numeric_dtype(df[color_column]):
                # Numeric data - use directly
                scatter = ax.scatter(
                    df[x_column],
                    df[y_column],
                    c=df[color_column],
                    alpha=alpha,
                    cmap="viridis",
                )
                plt.colorbar(scatter, ax=ax, label=color_column)
            else:
                # Categorical data - use seaborn for better handling
                unique_categories = df[color_column].unique()
                colors = plt.cm.tab10(np.linspace(0, 1, len(unique_categories)))
                for i, category in enumerate(unique_categories):
                    mask = df[color_column] == category
                    ax.scatter(
                        df[mask][x_column],
                        df[mask][y_column],
                        c=[colors[i]],
                        alpha=alpha,
                        label=category,
                    )
                ax.legend(title=color_column)
        else:
            ax.scatter(df[x_column], df[y_column], alpha=alpha)

        ax.set_xlabel(x_column)
        ax.set_ylabel(y_column)

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f"{y_column} vs {x_column}")

        # Add correlation coefficient if both columns are numeric
        if df[x_column].dtype in ["float64", "int64"] and df[y_column].dtype in [
            "float64",
            "int64",
        ]:
            corr = df[[x_column, y_column]].corr().iloc[0, 1]
            ax.text(
                0.05,
                0.95,
                f"r = {corr:.3f}",
                transform=ax.transAxes,
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
            )

        plt.tight_layout()

        plot_info = {
            "x_column": x_column,
            "y_column": y_column,
            "data_points": len(df[[x_column, y_column]].dropna()),
            "correlation": corr if "corr" in locals() else None,
        }

        return fig, ax, plot_info

    def _plot_box(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create box plot."""
        figsize = kwargs.get("figsize", self.default_figsize)

        fig, ax = plt.subplots(figsize=figsize)

        if y_column:
            # Box plot with grouping
            if color_column and color_column in df.columns:
                sns.boxplot(data=df, x=x_column, y=y_column, hue=color_column, ax=ax)
            else:
                sns.boxplot(data=df, x=x_column, y=y_column, ax=ax)
        else:
            # Simple box plot of single variable
            if color_column and color_column in df.columns:
                sns.boxplot(data=df, x=color_column, y=x_column, ax=ax)
            else:
                sns.boxplot(data=df, y=x_column, ax=ax)

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f"Box Plot of {x_column}")

        plt.tight_layout()

        plot_info = {
            "x_column": x_column,
            "y_column": y_column,
            "data_points": len(df[x_column].dropna()),
        }

        return fig, ax, plot_info

    def _plot_heatmap(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create heatmap (correlation matrix)."""
        figsize = kwargs.get("figsize", (8, 8))

        # Use numeric columns only
        numeric_df = df.select_dtypes(include=[np.number])

        if numeric_df.empty:
            raise ValueError("No numeric columns found for heatmap")

        correlation_matrix = numeric_df.corr()

        fig, ax = plt.subplots(figsize=figsize)

        sns.heatmap(
            correlation_matrix,
            annot=True,
            cmap="coolwarm",
            center=0,
            square=True,
            linewidths=0.5,
            ax=ax,
        )

        if title:
            ax.set_title(title)
        else:
            ax.set_title("Correlation Heatmap")

        plt.tight_layout()

        plot_info = {
            "variables": list(numeric_df.columns),
            "matrix_size": correlation_matrix.shape,
        }

        return fig, ax, plot_info

    def _plot_line(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create line plot."""
        if not y_column:
            raise ValueError("Line plot requires y_column")

        figsize = kwargs.get("figsize", self.default_figsize)

        fig, ax = plt.subplots(figsize=figsize)

        if color_column and color_column in df.columns:
            for group in df[color_column].unique():
                group_data = df[df[color_column] == group].sort_values(x_column)
                ax.plot(
                    group_data[x_column],
                    group_data[y_column],
                    label=str(group),
                    marker="o",
                )
            ax.legend()
        else:
            sorted_df = df.sort_values(x_column)
            ax.plot(sorted_df[x_column], sorted_df[y_column], marker="o")

        ax.set_xlabel(x_column)
        ax.set_ylabel(y_column)

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f"{y_column} over {x_column}")

        plt.tight_layout()

        plot_info = {
            "x_column": x_column,
            "y_column": y_column,
            "data_points": len(df[[x_column, y_column]].dropna()),
        }

        return fig, ax, plot_info

    def _plot_bar(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create bar plot."""
        figsize = kwargs.get("figsize", self.default_figsize)

        fig, ax = plt.subplots(figsize=figsize)

        if y_column:
            # Grouped bar chart
            if color_column and color_column in df.columns:
                sns.barplot(data=df, x=x_column, y=y_column, hue=color_column, ax=ax)
            else:
                sns.barplot(data=df, x=x_column, y=y_column, ax=ax)
        else:
            # Count plot
            if color_column and color_column in df.columns:
                sns.countplot(data=df, x=x_column, hue=color_column, ax=ax)
            else:
                sns.countplot(data=df, x=x_column, ax=ax)

        # Rotate x-axis labels if they're long
        if len(str(df[x_column].iloc[0])) > 10:
            plt.xticks(rotation=45, ha="right")

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f"Bar Plot of {x_column}")

        plt.tight_layout()

        plot_info = {
            "x_column": x_column,
            "y_column": y_column,
            "categories": df[x_column].nunique(),
        }

        return fig, ax, plot_info

    def _plot_violin(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create violin plot."""
        figsize = kwargs.get("figsize", self.default_figsize)

        fig, ax = plt.subplots(figsize=figsize)

        if y_column:
            if color_column and color_column in df.columns:
                sns.violinplot(data=df, x=x_column, y=y_column, hue=color_column, ax=ax)
            else:
                sns.violinplot(data=df, x=x_column, y=y_column, ax=ax)
        else:
            sns.violinplot(data=df, y=x_column, ax=ax)

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f"Violin Plot of {x_column}")

        plt.tight_layout()

        plot_info = {
            "x_column": x_column,
            "y_column": y_column,
            "data_points": len(df[x_column].dropna()),
        }

        return fig, ax, plot_info

    def _plot_pairplot(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create pair plot."""
        numeric_cols = df.select_dtypes(include=[np.number]).columns[
            :5
        ]  # Limit to 5 columns

        if len(numeric_cols) < 2:
            raise ValueError("Need at least 2 numeric columns for pair plot")

        if color_column and color_column in df.columns:
            g = sns.pairplot(df[list(numeric_cols) + [color_column]], hue=color_column)
        else:
            g = sns.pairplot(df[numeric_cols])

        if title:
            g.fig.suptitle(title, y=1.02)
        else:
            g.fig.suptitle("Pair Plot", y=1.02)

        plot_info = {"variables": list(numeric_cols), "data_points": len(df)}

        return g.fig, g.axes, plot_info

    def _plot_time_series(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create time series plot."""
        if not y_column:
            raise ValueError("Time series plot requires y_column")

        figsize = kwargs.get("figsize", self.default_figsize)

        # Convert x_column to datetime if it's not already
        df_copy = df.copy()
        df_copy[x_column] = pd.to_datetime(df_copy[x_column])
        df_copy = df_copy.sort_values(x_column)

        fig, ax = plt.subplots(figsize=figsize)

        if color_column and color_column in df.columns:
            for group in df_copy[color_column].unique():
                group_data = df_copy[df_copy[color_column] == group]
                ax.plot(
                    group_data[x_column],
                    group_data[y_column],
                    label=str(group),
                    marker=".",
                )
            ax.legend()
        else:
            ax.plot(df_copy[x_column], df_copy[y_column], marker=".")

        ax.set_xlabel(x_column)
        ax.set_ylabel(y_column)

        # Format x-axis dates
        plt.xticks(rotation=45)

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f"{y_column} Time Series")

        plt.tight_layout()

        plot_info = {
            "x_column": x_column,
            "y_column": y_column,
            "time_range": {
                "start": str(df_copy[x_column].min()),
                "end": str(df_copy[x_column].max()),
            },
            "data_points": len(df_copy),
        }

        return fig, ax, plot_info

    def _plot_distribution(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create distribution plot."""
        figsize = kwargs.get("figsize", self.default_figsize)

        fig, ax = plt.subplots(figsize=figsize)

        if color_column and color_column in df.columns:
            for group in df[color_column].unique():
                group_data = df[df[color_column] == group][x_column].dropna()
                sns.distplot(group_data, label=str(group), ax=ax, hist=False)
            ax.legend()
        else:
            sns.distplot(df[x_column].dropna(), ax=ax)

        if title:
            ax.set_title(title)
        else:
            ax.set_title(f"Distribution of {x_column}")

        plt.tight_layout()

        plot_info = {"x_column": x_column, "data_points": len(df[x_column].dropna())}

        return fig, ax, plot_info

    def _plot_correlation(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ) -> tuple[plt.Figure, plt.Axes, dict]:
        """Create correlation plot (same as heatmap)."""
        return self._plot_heatmap(
            df, x_column, y_column, color_column, facet_column, title, **kwargs
        )

    def _generate_filename(self, plot_type: str, format: str) -> str:
        """Generate a unique filename for the plot."""
        # Standard
        import time

        timestamp = int(time.time())
        return f"{plot_type}_{timestamp}.{format}"

    # Plotly interactive plot methods (simplified)
    def _plotly_histogram(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ):
        """Create interactive histogram with plotly."""
        fig = px.histogram(
            df,
            x=x_column,
            color=color_column,
            facet_col=facet_column,
            title=title or f"Histogram of {x_column}",
        )
        plot_info = {"x_column": x_column, "interactive": True}
        return fig, plot_info

    def _plotly_scatter(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ):
        """Create interactive scatter plot with plotly."""
        fig = px.scatter(
            df,
            x=x_column,
            y=y_column,
            color=color_column,
            facet_col=facet_column,
            title=title or f"{y_column} vs {x_column}",
        )
        plot_info = {"x_column": x_column, "y_column": y_column, "interactive": True}
        return fig, plot_info

    def _plotly_box(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ):
        """Create interactive box plot with plotly."""
        fig = px.box(
            df,
            x=x_column,
            y=y_column,
            color=color_column,
            title=title or f"Box Plot of {x_column}",
        )
        plot_info = {"x_column": x_column, "y_column": y_column, "interactive": True}
        return fig, plot_info

    def _plotly_line(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ):
        """Create interactive line plot with plotly."""
        fig = px.line(
            df,
            x=x_column,
            y=y_column,
            color=color_column,
            title=title or f"{y_column} over {x_column}",
        )
        plot_info = {"x_column": x_column, "y_column": y_column, "interactive": True}
        return fig, plot_info

    def _plotly_bar(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ):
        """Create interactive bar plot with plotly."""
        fig = px.bar(
            df,
            x=x_column,
            y=y_column,
            color=color_column,
            title=title or f"Bar Plot of {x_column}",
        )
        plot_info = {"x_column": x_column, "y_column": y_column, "interactive": True}
        return fig, plot_info

    def _plotly_heatmap(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ):
        """Create interactive heatmap with plotly."""
        numeric_df = df.select_dtypes(include=[np.number])
        correlation_matrix = numeric_df.corr()

        fig = px.imshow(
            correlation_matrix,
            title=title or "Correlation Heatmap",
            color_continuous_scale="RdBu_r",
        )
        plot_info = {"variables": list(numeric_df.columns), "interactive": True}
        return fig, plot_info

    def _plotly_time_series(
        self, df, x_column, y_column, color_column, facet_column, title, **kwargs
    ):
        """Create interactive time series plot with plotly."""
        df_copy = df.copy()
        df_copy[x_column] = pd.to_datetime(df_copy[x_column])

        fig = px.line(
            df_copy,
            x=x_column,
            y=y_column,
            color=color_column,
            title=title or f"{y_column} Time Series",
        )
        plot_info = {"x_column": x_column, "y_column": y_column, "interactive": True}
        return fig, plot_info
