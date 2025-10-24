# -*- coding: utf-8 -*-
"""Progress tracking utilities with rich display."""

import sys
import time
from contextlib import contextmanager
from typing import Dict, Optional

from rich.console import Console, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
    MofNCompleteColumn,
    TaskProgressColumn,
)
from rich.table import Table
from rich.layout import Layout
from rich.text import Text
from collections import deque


class ProgressTracker:
    """Track progress of data generation with rich display and statistics."""

    def __init__(self, total: int, desc: str, unit: str = "records"):
        """Initialize progress tracker.

        Args:
            total: Total number of items to process
            desc: Description of the operation
            unit: Unit name for progress display
        """
        self.total = total
        self.desc = desc
        self.unit = unit
        self.start_time = time.time()
        self.current = 0
        self.task_id = None
        self.progress = None

    def __enter__(self):
        """Context manager entry."""
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(complete_style="green", finished_style="bold green"),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("[cyan]{task.fields[rate]}/s"),
        )
        self.task_id = self.progress.add_task(
            self.desc,
            total=self.total,
            rate="0"
        )
        self.progress.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.progress:
            self.progress.stop()

    def update(self, n: int = 1, **kwargs):
        """Update progress by n items.

        Args:
            n: Number of items to add to progress
            **kwargs: Additional fields to update
        """
        if self.progress and self.task_id is not None:
            self.current += n
            rate = self.get_rate()
            self.progress.update(
                self.task_id,
                advance=n,
                rate=f"{rate:,.0f}",
                **kwargs
            )

    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds.

        Returns:
            Elapsed time
        """
        return time.time() - self.start_time

    def get_rate(self) -> float:
        """Get processing rate (items per second).

        Returns:
            Items per second
        """
        elapsed = self.get_elapsed_time()
        if elapsed > 0:
            return self.current / elapsed
        return 0.0


class MultiProgressTracker:
    """Track multiple progress bars simultaneously with rich live display."""

    def __init__(self, console: Optional[Console] = None, max_log_lines: int = 3):
        """Initialize multi-progress tracker.

        Args:
            console: Rich console instance (creates new if None)
            max_log_lines: Maximum number of log lines to display (default: 3)
        """
        self.console = console or Console()
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description:30}"),
            BarColumn(complete_style="green", finished_style="bold green"),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            TextColumn("[cyan]{task.fields[rate]}/s"),
            expand=False,
        )
        self.tasks: Dict[str, int] = {}
        self.stats: Dict[str, Dict] = {}
        self.live: Optional[Live] = None
        self.layout = Layout()
        self.start_time = time.time()
        self.total_records = 0
        self.total_completed = 0
        self.max_log_lines = max_log_lines
        self.log_buffer: deque = deque(maxlen=max_log_lines)
        self.show_logs = True
        self.is_interactive = sys.stdout.isatty()
        self.last_status_print = 0

    def add_task(self, name: str, total: int, desc: str):
        """Add a new progress task.

        Args:
            name: Unique name for the task
            total: Total items
            desc: Description
        """
        task_id = self.progress.add_task(
            desc,
            total=total,
            rate="0",
            visible=False
        )
        self.tasks[name] = task_id
        self.stats[name] = {
            "total": total,
            "completed": 0,
            "start_time": None,
            "end_time": None,
            "rate": 0.0,
        }
        self.total_records += total

    def start_task(self, name: str):
        """Start a task and make it visible.

        Args:
            name: Task name
        """
        if name in self.tasks:
            self.progress.update(self.tasks[name], visible=True)
            self.stats[name]["start_time"] = time.time()

            # For non-interactive terminals, print start message
            if not self.is_interactive:
                total = self.stats[name]["total"]
                self.console.print(f"[yellow]⚡[/yellow] Starting [cyan]{name}[/cyan]: {total:,} records")

    def update(self, name: str, n: int = 1):
        """Update a specific task.

        Args:
            name: Task name
            n: Number of items
        """
        if name in self.tasks:
            task_id = self.tasks[name]
            self.stats[name]["completed"] += n
            self.total_completed += n

            # Calculate rate
            elapsed = time.time() - (self.stats[name]["start_time"] or time.time())
            if elapsed > 0:
                rate = self.stats[name]["completed"] / elapsed
                self.stats[name]["rate"] = rate
            else:
                rate = 0.0

            self.progress.update(
                task_id,
                advance=n,
                rate=f"{rate:,.0f}"
            )

    def complete_task(self, name: str):
        """Mark a task as complete.

        Args:
            name: Task name
        """
        if name in self.tasks:
            # Ensure completed count matches total
            total = self.stats[name]["total"]
            current_completed = self.stats[name].get("completed", 0)

            # Update total_completed with any remaining records
            remaining = total - current_completed
            if remaining > 0:
                self.total_completed += remaining

            self.stats[name]["completed"] = total  # Always set to total when completing
            self.stats[name]["end_time"] = time.time()
            self.progress.update(self.tasks[name], completed=total)

            # For non-interactive terminals, print completion message
            if not self.is_interactive:
                rate = self.stats[name].get("rate", 0)
                self.console.print(f"[green]✓[/green] Completed [cyan]{name}[/cyan]: {total:,} records ([cyan]{rate:,.0f}/s[/cyan])")

    def log(self, message: str, style: str = "dim"):
        """Add a log message to the scrolling log panel.

        Args:
            message: Log message to display
            style: Rich style for the message
        """
        timestamp = time.strftime("%H:%M:%S")
        styled_message = f"[dim]{timestamp}[/dim] {message}"
        self.log_buffer.append((styled_message, style))

    def _make_log_panel(self) -> RenderableType:
        """Create scrolling log panel.

        Returns:
            Rich renderable with recent log messages
        """
        if not self.log_buffer:
            return Text("No log messages yet...", style="dim italic")

        # Create a group of text objects to render markup properly
        from rich.console import Group
        log_lines = []
        for message, style in self.log_buffer:
            # Use console.render_str to properly parse markup
            log_lines.append(Text.from_markup(message))

        return Group(*log_lines)

    def _make_stats_table(self) -> Table:
        """Create overall statistics table.

        Returns:
            Rich table with overall statistics
        """
        table = Table(show_header=False, box=None, padding=(0, 1), collapse_padding=True)
        table.add_column("Metric", style="bold cyan", no_wrap=True, width=18)
        table.add_column("Value", style="bold white")

        elapsed = time.time() - self.start_time
        overall_rate = self.total_completed / elapsed if elapsed > 0 else 0

        table.add_row("Total Records", f"{self.total_records:,}")
        table.add_row("Completed", f"[green]{self.total_completed:,}[/green]")
        table.add_row("Remaining", f"[yellow]{self.total_records - self.total_completed:,}[/yellow]")
        table.add_row("Overall Rate", f"[cyan]{overall_rate:,.0f} records/s[/cyan]")
        table.add_row("Elapsed Time", f"{elapsed:.1f}s")

        if overall_rate > 0 and self.total_completed < self.total_records:
            eta = (self.total_records - self.total_completed) / overall_rate
            table.add_row("ETA", f"[magenta]{eta:.1f}s[/magenta]")

        return table

    def _make_generator_status_table(self) -> Table:
        """Create detailed generator status table.

        Returns:
            Rich table with per-generator status
        """
        table = Table(show_header=True, box=None, padding=(0, 1), expand=True, show_lines=False)
        table.add_column("Generator", style="bold", no_wrap=True, width=30)
        table.add_column("Status", style="bold", width=13)
        table.add_column("Progress", justify="right", width=20)
        table.add_column("Rate", justify="right", width=13)

        # Categorize generators
        completed = []
        in_progress = []
        pending = []

        for name in self.tasks.keys():
            if name not in self.stats:
                continue  # Skip if stats not initialized

            task_info = self.stats[name]
            total = task_info.get("total", 0)
            current = task_info.get("completed", 0)

            if current >= total and total > 0:
                status = "completed"
                completed.append((name, task_info))
            elif current > 0:
                status = "in_progress"
                in_progress.append((name, task_info))
            else:
                status = "pending"
                pending.append((name, task_info))

        # Add summary row with counts
        total_generators = len(self.tasks)
        table.add_row(
            f"[bold]Summary: {total_generators} generators[/bold]",
            f"[green]✓ {len(completed)}[/green] [yellow]⚡ {len(in_progress)}[/yellow] [dim]⏳ {len(pending)}[/dim]",
            "",
            "",
        )

        # Only add section separator if there are generators to show
        if completed or in_progress or pending:
            table.add_section()

        # Show in-progress generators first
        for name, info in in_progress:
            rate = info.get("rate", 0)
            current = info.get("completed", 0)
            total = info.get("total", 0)
            pct = (current / total * 100) if total > 0 else 0

            table.add_row(
                name,
                "[yellow]⚡ Active[/yellow]",
                f"[yellow]{current:,}/{total:,} ({pct:.0f}%)[/yellow]",
                f"[cyan]{rate:,.0f}/s[/cyan]"
            )

        # Show completed generators
        for name, info in completed:
            rate = info.get("rate", 0)
            total = info.get("total", 0)
            current = info.get("completed", 0)

            table.add_row(
                name,
                "[green]✓ Done[/green]",
                f"[green]{current:,}/{total:,} (100%)[/green]",
                f"[dim]{rate:,.0f}/s[/dim]"
            )

        # Show pending generators
        for name, info in pending:
            total = info.get("total", 0)

            table.add_row(
                name,
                "[dim]⏳ Pending[/dim]",
                f"[dim]0/{total:,} (0%)[/dim]",
                "[dim]—[/dim]"
            )

        return table

    def _make_layout(self) -> Layout:
        """Create layout with progress and stats.

        Returns:
            Rich layout
        """
        layout = Layout()

        if self.show_logs:
            # Compact layout: stats(7) + generators(flex) + progress(8) + logs(5)
            layout.split_column(
                Layout(name="stats", size=7),
                Layout(name="generators"),  # Takes remaining space
                Layout(name="progress", size=8),
                Layout(name="logs", size=self.max_log_lines + 2),  # Compact: 3 logs + 2 for border
            )
        else:
            layout.split_column(
                Layout(name="stats", size=7),
                Layout(name="generators"),  # Takes remaining space
                Layout(name="progress", size=8),
            )

        # Overall stats panel
        stats_table = self._make_stats_table()
        layout["stats"].update(
            Panel(
                stats_table,
                title="[bold]Overall Statistics[/bold]",
                border_style="cyan",
            )
        )

        # Generator status table
        generator_table = self._make_generator_status_table()
        layout["generators"].update(
            Panel(
                generator_table,
                title="[bold]Generator Status (Detailed)[/bold]",
                border_style="blue",
            )
        )

        # Progress bars (only show active ones)
        layout["progress"].update(self.progress)

        # Log panel (if enabled)
        if self.show_logs:
            log_panel = self._make_log_panel()
            layout["logs"].update(
                Panel(
                    log_panel,
                    title="[bold]Activity Log[/bold]",
                    border_style="green",
                )
            )

        return layout

    @contextmanager
    def live_display(self):
        """Context manager for live display.

        Yields:
            Self for chaining
        """
        try:
            if self.is_interactive:
                # Use Rich Live display for interactive terminals
                with Live(
                    self._make_layout(),
                    console=self.console,
                    refresh_per_second=10,  # Increased from 4 to 10 for more responsive updates
                    transient=False,
                    auto_refresh=True,  # Force auto-refresh
                ) as live:
                    self.live = live
                    yield self
            else:
                # For non-interactive terminals (piped output), use simple console prints
                self.console.print("[bold cyan]Starting data generation...[/bold cyan]")
                self.console.print(f"[dim]Total generators: {len(self.tasks)}[/dim]")
                self.console.print(f"[dim]Total records: {self.total_records:,}[/dim]")
                self.console.print()
                yield self
                # Print final summary
                self.console.print()
                self._print_final_summary()
        finally:
            self.live = None

    def refresh(self):
        """Refresh the live display."""
        if self.live:
            self.live.update(self._make_layout())
        elif not self.is_interactive:
            # For non-interactive terminals, print periodic status updates
            current_time = time.time()
            if current_time - self.last_status_print >= 5.0:  # Print every 5 seconds
                self._print_status_update()
                self.last_status_print = current_time

    def _print_status_update(self):
        """Print a status update to console (for non-interactive terminals)."""
        # Count generators by status
        completed_count = 0
        in_progress_count = 0
        pending_count = 0

        for name in self.tasks.keys():
            if name not in self.stats:
                continue
            task_info = self.stats[name]
            total = task_info.get("total", 0)
            current = task_info.get("completed", 0)

            if current >= total and total > 0:
                completed_count += 1
            elif current > 0:
                in_progress_count += 1
            else:
                pending_count += 1

        elapsed = time.time() - self.start_time
        overall_rate = self.total_completed / elapsed if elapsed > 0 else 0
        pct = (self.total_completed / self.total_records * 100) if self.total_records > 0 else 0

        self.console.print(
            f"[cyan]Progress:[/cyan] {self.total_completed:,}/{self.total_records:,} ({pct:.1f}%) | "
            f"[green]✓ {completed_count}[/green] [yellow]⚡ {in_progress_count}[/yellow] [dim]⏳ {pending_count}[/dim] | "
            f"[cyan]{overall_rate:,.0f} rec/s[/cyan]"
        )

    def _print_final_summary(self):
        """Print final summary for non-interactive terminals."""
        elapsed = time.time() - self.start_time
        overall_rate = self.total_completed / elapsed if elapsed > 0 else 0

        self.console.print("[bold green]Generation Complete![/bold green]")
        self.console.print(f"Total Records: {self.total_completed:,}/{self.total_records:,}")
        self.console.print(f"Duration: {elapsed:.2f}s")
        self.console.print(f"Overall Rate: {overall_rate:,.0f} records/s")
        self.console.print()

        # Print generator breakdown
        table = Table(show_header=True, box=None, padding=(0, 1))
        table.add_column("Generator", style="cyan", no_wrap=True)
        table.add_column("Records", justify="right", style="green")
        table.add_column("Rate", justify="right", style="yellow")

        for name in self.tasks.keys():
            if name not in self.stats:
                continue
            task_info = self.stats[name]
            total = task_info.get("total", 0)
            rate = task_info.get("rate", 0)
            table.add_row(name, f"{total:,}", f"{rate:,.0f}/s")

        self.console.print(table)

    def close_all(self):
        """Close all progress trackers."""
        for name in self.tasks:
            self.complete_task(name)
        if self.live:
            self.live.stop()


class SimpleProgressTracker:
    """Simple progress tracker for single operations."""

    def __init__(self, console: Optional[Console] = None):
        """Initialize simple progress tracker.

        Args:
            console: Rich console instance
        """
        self.console = console or Console()
        self.start_time = time.time()

    def print_step(self, message: str, style: str = "bold blue"):
        """Print a step message.

        Args:
            message: Message to print
            style: Rich style string
        """
        self.console.print(f"[{style}]→[/{style}] {message}")

    def print_success(self, message: str):
        """Print success message.

        Args:
            message: Message to print
        """
        self.console.print(f"[bold green]✓[/bold green] {message}")

    def print_error(self, message: str):
        """Print error message.

        Args:
            message: Message to print
        """
        self.console.print(f"[bold red]✗[/bold red] {message}")

    def print_warning(self, message: str):
        """Print warning message.

        Args:
            message: Message to print
        """
        self.console.print(f"[bold yellow]⚠[/bold yellow] {message}")

    def print_info(self, message: str):
        """Print info message.

        Args:
            message: Message to print
        """
        self.console.print(f"[cyan]ℹ[/cyan] {message}")

    def print_stats(self, stats: Dict):
        """Print statistics in a formatted table.

        Args:
            stats: Dictionary of statistics
        """
        table = Table(show_header=True, box=None)
        table.add_column("Generator", style="cyan", no_wrap=True)
        table.add_column("Generated", justify="right", style="green")
        table.add_column("Inserted", justify="right", style="yellow")
        table.add_column("Time", justify="right", style="blue")
        table.add_column("Rate", justify="right", style="magenta")

        for name, data in stats.items():
            if isinstance(data, dict):
                generated = data.get("generated", 0)
                inserted = data.get("inserted", 0)
                duration = data.get("duration", 0)
                rate = generated / duration if duration > 0 else 0

                table.add_row(
                    name,
                    f"{generated:,}",
                    f"{inserted:,}",
                    f"{duration:.2f}s",
                    f"{rate:,.0f}/s"
                )

        self.console.print(table)

    def print_summary(self, total_records: int, duration: float, profile: str):
        """Print final summary.

        Args:
            total_records: Total records generated
            duration: Total duration in seconds
            profile: Profile name
        """
        rate = total_records / duration if duration > 0 else 0

        panel = Panel(
            f"[bold]Profile:[/bold] {profile}\n"
            f"[bold]Total Records:[/bold] {total_records:,}\n"
            f"[bold]Duration:[/bold] {duration:.2f}s\n"
            f"[bold]Rate:[/bold] {rate:,.2f} records/second",
            title="[bold green]Generation Complete[/bold green]",
            border_style="green",
        )
        self.console.print(panel)
