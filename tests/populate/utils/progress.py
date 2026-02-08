# -*- coding: utf-8 -*-
"""Progress tracking utilities for REST API population."""

# Standard
from collections import deque
from contextlib import contextmanager
import sys
import time
from typing import Dict, Optional

# Third-Party
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text


class MultiProgressTracker:
    """Track multiple async population tasks with rich live display."""

    def __init__(self, console: Optional[Console] = None, max_log_lines: int = 5):
        self.console = console or Console()
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description:30}"),
            BarColumn(complete_style="green", finished_style="bold green"),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TextColumn("[dim]|[/dim]"),
            TimeElapsedColumn(),
            TextColumn("[dim]|[/dim]"),
            TimeRemainingColumn(),
            TextColumn("[cyan]{task.fields[rate]}/s"),
            expand=False,
        )
        self.tasks: Dict[str, int] = {}
        self.stats: Dict[str, Dict] = {}
        self.live: Optional[Live] = None
        self.start_time = time.time()
        self.total_records = 0
        self.total_completed = 0
        self.total_errors = 0
        self.max_log_lines = max_log_lines
        self.log_buffer: deque = deque(maxlen=max_log_lines)
        self.is_interactive = sys.stdout.isatty()

    def add_task(self, name: str, total: int, desc: str):
        task_id = self.progress.add_task(desc, total=total, rate="0", visible=False)
        self.tasks[name] = task_id
        self.stats[name] = {
            "total": total,
            "completed": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
            "rate": 0.0,
        }
        self.total_records += total

    def start_task(self, name: str):
        if name in self.tasks:
            self.progress.update(self.tasks[name], visible=True)
            self.stats[name]["start_time"] = time.time()
            if not self.is_interactive:
                total = self.stats[name]["total"]
                self.console.print(f"[yellow]>[/yellow] Starting [cyan]{name}[/cyan]: {total:,} requests")

    def update(self, name: str, n: int = 1, errors: int = 0):
        if name in self.tasks:
            self.stats[name]["completed"] += n
            self.stats[name]["errors"] += errors
            self.total_completed += n
            self.total_errors += errors

            elapsed = time.time() - (self.stats[name]["start_time"] or time.time())
            if elapsed > 0:
                rate = self.stats[name]["completed"] / elapsed
                self.stats[name]["rate"] = rate
            else:
                rate = 0.0

            self.progress.update(self.tasks[name], advance=n, rate=f"{rate:,.0f}")

    def complete_task(self, name: str):
        if name in self.tasks:
            total = self.stats[name]["total"]
            current = self.stats[name].get("completed", 0)
            remaining = total - current
            if remaining > 0:
                self.total_completed += remaining
            self.stats[name]["completed"] = total
            self.stats[name]["end_time"] = time.time()
            self.progress.update(self.tasks[name], completed=total)

            if not self.is_interactive:
                rate = self.stats[name].get("rate", 0)
                errors = self.stats[name].get("errors", 0)
                err_str = f" ([red]{errors} errors[/red])" if errors else ""
                self.console.print(f"[green]v[/green] Completed [cyan]{name}[/cyan]: {total:,} records ([cyan]{rate:,.0f}/s[/cyan]){err_str}")

    def log(self, message: str, style: str = ""):
        timestamp = time.strftime("%H:%M:%S")
        styled_message = f"[dim]{timestamp}[/dim] {message}"
        self.log_buffer.append((styled_message, style))

    def _make_log_panel(self) -> RenderableType:
        # Always render exactly max_log_lines to prevent layout height changes
        lines: list[RenderableType] = []
        for msg, _ in self.log_buffer:
            lines.append(Text.from_markup(msg))
        while len(lines) < self.max_log_lines:
            lines.append(Text(""))
        return Group(*lines)

    def _make_stats_table(self) -> Table:
        table = Table(show_header=False, box=None, padding=(0, 1), collapse_padding=True)
        table.add_column("Metric", style="bold cyan", no_wrap=True, width=18)
        table.add_column("Value", style="bold white")

        elapsed = time.time() - self.start_time
        overall_rate = self.total_completed / elapsed if elapsed > 0 else 0

        table.add_row("Total Requests", f"{self.total_records:,}")
        table.add_row("Completed", f"[green]{self.total_completed:,}[/green]")
        table.add_row("Errors", f"[red]{self.total_errors:,}[/red]" if self.total_errors else "[dim]0[/dim]")
        table.add_row("Remaining", f"[yellow]{self.total_records - self.total_completed:,}[/yellow]")
        table.add_row("Overall Rate", f"[cyan]{overall_rate:,.0f} req/s[/cyan]")
        table.add_row("Elapsed", f"{elapsed:.1f}s")

        if overall_rate > 0 and self.total_completed < self.total_records:
            eta = (self.total_records - self.total_completed) / overall_rate
            table.add_row("ETA", f"[magenta]{eta:.1f}s[/magenta]")

        return table

    def _make_populator_status_table(self) -> Table:
        table = Table(show_header=True, box=None, padding=(0, 1), expand=True, show_lines=False)
        table.add_column("Populator", style="bold", no_wrap=True, width=30)
        table.add_column("Status", style="bold", width=13)
        table.add_column("Progress", justify="right", width=22)
        table.add_column("Rate", justify="right", width=13)

        completed, in_progress, pending = [], [], []

        for name in self.tasks:
            if name not in self.stats:
                continue
            info = self.stats[name]
            total = info.get("total", 0)
            current = info.get("completed", 0)

            if current >= total and total > 0:
                completed.append((name, info))
            elif current > 0:
                in_progress.append((name, info))
            else:
                pending.append((name, info))

        table.add_row(
            f"[bold]Summary: {len(self.tasks)} populators[/bold]",
            f"[green]v {len(completed)}[/green] [yellow]> {len(in_progress)}[/yellow] [dim]~ {len(pending)}[/dim]",
            "",
            "",
        )
        if completed or in_progress or pending:
            table.add_section()

        for name, info in in_progress:
            rate = info.get("rate", 0)
            current = info.get("completed", 0)
            total = info.get("total", 0)
            errors = info.get("errors", 0)
            pct = (current / total * 100) if total > 0 else 0
            err_str = f" [red]+{errors}err[/red]" if errors else ""

            table.add_row(name, "[yellow]> Active[/yellow]", f"[yellow]{current:,}/{total:,} ({pct:.0f}%){err_str}[/yellow]", f"[cyan]{rate:,.0f}/s[/cyan]")

        for name, info in completed:
            rate = info.get("rate", 0)
            total = info.get("total", 0)
            errors = info.get("errors", 0)
            err_str = f" [red]+{errors}err[/red]" if errors else ""
            table.add_row(name, "[green]v Done[/green]", f"[green]{total:,}/{total:,}{err_str}[/green]", f"[dim]{rate:,.0f}/s[/dim]")

        for name, info in pending:
            total = info.get("total", 0)
            table.add_row(name, "[dim]~ Pending[/dim]", f"[dim]0/{total:,} (0%)[/dim]", "[dim]-[/dim]")

        return table

    def _make_layout(self) -> RenderableType:
        # Use a simple Group instead of Layout to avoid height calculation issues
        # that cause the terminal to jump around
        return Group(
            Panel(self._make_stats_table(), title="[bold]Overall Statistics[/bold]", border_style="cyan"),
            Panel(self._make_populator_status_table(), title="[bold]Populator Status[/bold]", border_style="blue"),
            self.progress,
            Panel(self._make_log_panel(), title="[bold]Activity Log[/bold]", border_style="green"),
        )

    @contextmanager
    def live_display(self):
        try:
            if self.is_interactive:
                with Live(self._make_layout(), console=self.console, refresh_per_second=4, transient=False, auto_refresh=True, vertical_overflow="visible") as live:
                    self.live = live
                    yield self
            else:
                self.console.print("[bold cyan]Starting REST API population...[/bold cyan]")
                self.console.print(f"[dim]Total populators: {len(self.tasks)}[/dim]")
                self.console.print(f"[dim]Total requests: {self.total_records:,}[/dim]\n")
                yield self
                self._print_final_summary()
        finally:
            self.live = None

    def refresh(self):
        if self.live:
            self.live.update(self._make_layout())

    def set_results(self, results: Dict[str, Dict]):
        """Update stats with actual populator results for accurate final display."""
        self._actual_results = results

    def _print_final_summary(self):
        elapsed = time.time() - self.start_time
        actual = getattr(self, "_actual_results", {})

        # Use actual results if available
        if actual:
            total_created = sum(r.get("created", 0) for r in actual.values())
            total_errors = sum(r.get("errors", 0) for r in actual.values())
        else:
            total_created = self.total_completed
            total_errors = self.total_errors

        overall_rate = total_created / elapsed if elapsed > 0 else 0

        self.console.print(f"\n[bold green]Population Complete![/bold green]")
        self.console.print(f"Total Created: {total_created:,}/{self.total_records:,}")
        self.console.print(f"Errors: {total_errors:,}")
        self.console.print(f"Duration: {elapsed:.2f}s")
        self.console.print(f"Overall Rate: {overall_rate:,.0f} req/s\n")

        table = Table(show_header=True, box=None, padding=(0, 1))
        table.add_column("Populator", style="cyan", no_wrap=True)
        table.add_column("Created", justify="right", style="green")
        table.add_column("Errors", justify="right", style="red")
        table.add_column("Rate", justify="right", style="yellow")

        for name in self.tasks:
            if name in actual:
                created = actual[name].get("created", 0)
                errors = actual[name].get("errors", 0)
                duration = actual[name].get("duration", 0)
                rate = created / duration if duration > 0 else 0
            else:
                info = self.stats.get(name, {})
                created = info.get("completed", 0)
                errors = info.get("errors", 0)
                rate = info.get("rate", 0)
            table.add_row(name, f"{created:,}", f"{errors:,}", f"{rate:,.0f}/s")

        self.console.print(table)
