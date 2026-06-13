#!/usr/bin/env python3
"""
GitHub History Chart Generator
===============================

Generates a line chart showing the number of open issues and PRs
at the end of each Tuesday throughout the year.

This script uses the GitHub Issues and Pull Requests APIs to fetch all items once,
then reconstructs the historical state at each Tuesday by checking timestamps.
This approach avoids Search API rate limits and provides complete data.

Requirements
------------
- Python 3.7+
- matplotlib (install with: pip install matplotlib)
- requests (usually pre-installed)
- GitHub personal access token (recommended for higher rate limits)

GitHub Token Setup
------------------
To avoid rate limits, you need a GitHub personal access token:

1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Give it a descriptive name (e.g., "GitHub History Chart")
4. Select scopes: "public_repo" (for public repositories)
5. Click "Generate token" and copy the token

Set the token as an environment variable:
    export GITHUB_TOKEN="your_token_here"

Or if you have GitHub CLI installed:
    export GITHUB_TOKEN=$(gh auth token)

Usage Examples
--------------
Basic usage (current year, default repo):
    python scripts/github_history_chart.py

Specify a year:
    python scripts/github_history_chart.py --year 2025

Since a specific date:
    python scripts/github_history_chart.py --since 2025-06-01
    python scripts/github_history_chart.py --since 2025-06-01T00:00:00
    python scripts/github_history_chart.py --since "June 1, 2025"

Different repository:
    python scripts/github_history_chart.py --repo owner/repo --year 2025

Custom output file:
    python scripts/github_history_chart.py --output my_chart.png

With explicit token:
    python scripts/github_history_chart.py --token ghp_xxxxxxxxxxxx

Full example:
    GITHUB_TOKEN=$(gh auth token) python scripts/github_history_chart.py \\
        --repo IBM/mcp-context-forge \\
        --since 2025-01-01 \\
        --output github_history_2025.png

Command-line Options
--------------------
Run with --help to see all options:
    python scripts/github_history_chart.py --help

Output
------
The script generates:
1. A PNG chart showing two lines with separate y-axes:
   - Blue line (left axis): Open Issues over time
   - Purple line (right axis): Open PRs (excluding drafts) over time
2. Console output with:
   - Progress updates during data fetching
   - Summary statistics (averages, peaks)

Rate Limits
-----------
Without authentication: 60 requests/hour
With authentication: 5,000 requests/hour

This script typically makes 20-30 API requests for a repository with
thousands of issues/PRs, well within authenticated limits.

Author: Generated for IBM/mcp-context-forge project
License: Apache-2.0
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

import requests

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except ImportError:
    print("=" * 70)
    print("ERROR: matplotlib is required but not installed")
    print("=" * 70)
    print()
    print("Install it with:")
    print("  pip install matplotlib")
    print()
    print("Or if using a virtual environment:")
    print("  .venv/bin/pip install matplotlib")
    print()
    sys.exit(1)


def parse_date(date_string: str) -> datetime:
    """
    Parse a date string in various formats.

    Supported formats:
    - YYYY-MM-DD (ISO 8601)
    - YYYY-MM-DDTHH:MM:SS (ISO 8601 with time)
    - YYYY/MM/DD
    - MM/DD/YYYY
    - Month DD, YYYY (e.g., "June 1, 2025")

    Args:
        date_string: Date string to parse

    Returns:
        datetime object

    Raises:
        ValueError: If date string cannot be parsed
    """
    formats = [
        "%Y-%m-%d",  # 2025-06-01
        "%Y-%m-%dT%H:%M:%S",  # 2025-06-01T00:00:00
        "%Y/%m/%d",  # 2025/06/01
        "%m/%d/%Y",  # 06/01/2025
        "%B %d, %Y",  # June 1, 2025
        "%b %d, %Y",  # Jun 1, 2025
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue

    raise ValueError(f"Unable to parse date: {date_string}. Supported formats: YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, YYYY/MM/DD, MM/DD/YYYY, 'Month DD, YYYY'")


def get_tuesdays_in_year(year: int) -> List[datetime]:
    """
    Get all Tuesdays in the given year, up to and including the next Tuesday after today.

    If the current date is in the specified year, the analysis stops at the next
    Tuesday after today (inclusive). This ensures we capture the current week's state
    without projecting into the future.

    Args:
        year: The year to get Tuesdays for

    Returns:
        List of datetime objects representing end of each Tuesday (23:59:59)
    """
    tuesdays = []
    now = datetime.now()

    # Start from January 1st
    current = datetime(year, 1, 1)

    # Find the first Tuesday
    days_until_tuesday = (1 - current.weekday()) % 7  # Tuesday is weekday 1
    if days_until_tuesday > 0:
        current += timedelta(days=days_until_tuesday)

    # Calculate the next Tuesday after today (for current year only)
    if year == now.year:
        # Find next Tuesday after today
        days_until_next_tuesday = (1 - now.weekday()) % 7
        if days_until_next_tuesday == 0:
            days_until_next_tuesday = 7  # If today is Tuesday, get next Tuesday
        next_tuesday = now + timedelta(days=days_until_next_tuesday)
        end_date = next_tuesday.replace(hour=23, minute=59, second=59)
    else:
        # For past/future years, include all Tuesdays in the year
        end_date = datetime(year, 12, 31, 23, 59, 59)

    # Collect all Tuesdays up to end_date
    while current.year == year and current <= end_date:
        # Set to end of day (23:59:59)
        tuesday_end = current.replace(hour=23, minute=59, second=59)
        tuesdays.append(tuesday_end)
        current += timedelta(days=7)

    return tuesdays


def get_tuesdays_since_date(since_date: datetime) -> List[datetime]:
    """
    Get all Tuesdays from a start date to the next Tuesday after today (inclusive).

    The analysis includes the current date by stopping at the next Tuesday after today.
    This ensures we capture the current week's state without projecting into the future.

    Args:
        since_date: Start date (inclusive)

    Returns:
        List of datetime objects representing end of each Tuesday (23:59:59)
    """
    now = datetime.now()

    # Calculate the next Tuesday after today
    days_until_next_tuesday = (1 - now.weekday()) % 7
    if days_until_next_tuesday == 0:
        days_until_next_tuesday = 7  # If today is Tuesday, get next Tuesday
    next_tuesday = now + timedelta(days=days_until_next_tuesday)
    end_date = next_tuesday.replace(hour=23, minute=59, second=59)

    tuesdays = []
    current = since_date

    # Find the first Tuesday on or after since_date
    days_until_tuesday = (1 - current.weekday()) % 7  # Tuesday is weekday 1
    if days_until_tuesday > 0:
        current += timedelta(days=days_until_tuesday)

    # Collect all Tuesdays until end_date (next Tuesday after today)
    while current <= end_date:
        # Set to end of day (23:59:59)
        tuesday_end = current.replace(hour=23, minute=59, second=59)
        tuesdays.append(tuesday_end)
        current += timedelta(days=7)

    return tuesdays


def fetch_all_issues(repo: str, token: str = None, state: str = "all") -> List[Dict]:
    """
    Fetch all issues (not PRs) from a repository.

    Uses pagination to fetch all issues. GitHub's Issues API returns
    both issues and PRs, so we filter out PRs by checking for the
    'pull_request' key.

    Args:
        repo: Repository in format "owner/repo"
        token: GitHub personal access token (optional but recommended)
        state: Issue state - "open", "closed", or "all"

    Returns:
        List of issue dictionaries from GitHub API
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    base_url = f"https://api.github.com/repos/{repo}/issues"
    issues = []
    page = 1

    print(f"Fetching all {state} issues...")

    while True:
        params = {
            "state": state,
            "per_page": 100,  # Maximum allowed by GitHub API
            "page": page,
        }

        try:
            response = requests.get(base_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            page_issues = response.json()

            if not page_issues:
                break

            # Filter out PRs (they have a 'pull_request' key)
            page_issues = [issue for issue in page_issues if "pull_request" not in issue]
            issues.extend(page_issues)

            print(f"  Fetched page {page}: {len(page_issues)} issues (total: {len(issues)})")
            page += 1

        except requests.exceptions.RequestException as e:
            print(f"Error fetching issues page {page}: {e}")
            break

    print(f"Total issues fetched: {len(issues)}")
    return issues


def fetch_all_prs(repo: str, token: str = None, state: str = "all") -> List[Dict]:
    """
    Fetch all pull requests from a repository.

    Uses the dedicated Pull Requests API endpoint which only returns PRs.

    Args:
        repo: Repository in format "owner/repo"
        token: GitHub personal access token (optional but recommended)
        state: PR state - "open", "closed", or "all"

    Returns:
        List of PR dictionaries from GitHub API
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    base_url = f"https://api.github.com/repos/{repo}/pulls"
    prs = []
    page = 1

    print(f"Fetching all {state} pull requests...")

    while True:
        params = {
            "state": state,
            "per_page": 100,  # Maximum allowed by GitHub API
            "page": page,
        }

        try:
            response = requests.get(base_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            page_prs = response.json()

            if not page_prs:
                break

            prs.extend(page_prs)
            print(f"  Fetched page {page}: {len(page_prs)} PRs (total: {len(prs)})")
            page += 1

        except requests.exceptions.RequestException as e:
            print(f"Error fetching PRs page {page}: {e}")
            break

    print(f"Total PRs fetched: {len(prs)}")
    return prs


def count_open_at_date(items: List[Dict], target_date: datetime, exclude_drafts: bool = False) -> int:
    """
    Count how many items were open at a specific date.

    An item is considered "open" at a date if:
    - It was created before or on that date
    - It was not closed before or on that date (or is still open)
    - It is not a draft (if exclude_drafts is True)

    Args:
        items: List of issues or PRs from GitHub API
        target_date: Date to check (datetime object)
        exclude_drafts: If True, exclude draft PRs from the count

    Returns:
        Count of items that were open at the target date
    """
    count = 0

    for item in items:
        # Parse created_at timestamp
        created_at = datetime.strptime(item["created_at"], "%Y-%m-%dT%H:%M:%SZ")

        # Skip if not created yet at target date
        if created_at > target_date:
            continue

        # Check if closed before target date
        if item["closed_at"]:
            closed_at = datetime.strptime(item["closed_at"], "%Y-%m-%dT%H:%M:%SZ")
            # Skip if already closed at target date
            if closed_at <= target_date:
                continue

        # Exclude drafts if requested (only applies to PRs)
        if exclude_drafts and item.get("draft", False):
            continue

        count += 1

    return count


def create_chart(
    dates: List[datetime],
    issues_counts: List[int],
    prs_counts: List[int],
    output_file: str,
    repo: str,
    time_range: str,
) -> None:
    """
    Create and save a line chart with dual y-axes.

    Issues are plotted on the left y-axis (blue) and PRs on the right y-axis (purple).
    This allows each metric to have its own scale for better visualization.

    Args:
        dates: List of Tuesday dates
        issues_counts: List of issue counts for each date
        prs_counts: List of PR counts for each date
        output_file: Path to save the PNG chart
        repo: Repository name for chart title
        time_range: Description of time range (e.g., "2026" or "Since 2025-06-01")
    """
    fig, ax1 = plt.subplots(figsize=(14, 7))

    # Plot issues on left y-axis (ax1)
    color_issues = "#2E86AB"
    ax1.set_xlabel("Date (Tuesdays)", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Open Issues", fontsize=12, fontweight="bold", color=color_issues)
    line1 = ax1.plot(dates, issues_counts, marker="o", linewidth=2, markersize=4, label="Open Issues", color=color_issues)
    ax1.tick_params(axis="y", labelcolor=color_issues)
    ax1.grid(True, alpha=0.3, linestyle="--")

    # Create second y-axis for PRs
    ax2 = ax1.twinx()
    color_prs = "#A23B72"
    ax2.set_ylabel("Open PRs (non-draft)", fontsize=12, fontweight="bold", color=color_prs)
    line2 = ax2.plot(dates, prs_counts, marker="s", linewidth=2, markersize=4, label="Open PRs (non-draft)", color=color_prs)
    ax2.tick_params(axis="y", labelcolor=color_prs)

    # Title
    ax1.set_title(f"GitHub Repository Activity - {repo}\nOpen Issues and PRs at End of Each Tuesday ({time_range})", fontsize=14, fontweight="bold", pad=20)

    # Format x-axis to show dates nicely
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.xticks(rotation=45, ha="right")

    # Combined legend
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left", fontsize=11, framealpha=0.9)

    # Tight layout
    fig.tight_layout()

    # Save with high DPI for quality
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    print(f"Chart saved to: {output_file}")


def print_usage_hint():
    """Print a helpful usage hint when no token is provided."""
    print("=" * 70)
    print("TIP: Get a GitHub token for higher rate limits")
    print("=" * 70)
    print()
    print("Without a token: 60 requests/hour")
    print("With a token:    5,000 requests/hour")
    print()
    print("To get a token:")
    print("  1. Visit: https://github.com/settings/tokens")
    print("  2. Generate a new token (classic)")
    print("  3. Select 'public_repo' scope")
    print("  4. Copy the token")
    print()
    print("Then run:")
    print("  export GITHUB_TOKEN='your_token_here'")
    print()
    print("Or if you have GitHub CLI:")
    print("  export GITHUB_TOKEN=$(gh auth token)")
    print()
    print("=" * 70)
    print()


def main():
    """Main function - entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Generate a chart of GitHub issues and PRs history for each Tuesday",
        epilog="""
Examples:
  # Current year (default) - stops at next Tuesday after today
  %(prog)s

  # Specific year - stops at next Tuesday after today if current year
  %(prog)s --year 2025

  # Since a specific date - stops at next Tuesday after today
  %(prog)s --since 2025-06-01
  %(prog)s --since "June 1, 2025"

  # Different repository
  %(prog)s --repo owner/repo --year 2025 --output chart.png

  # With GitHub token
  GITHUB_TOKEN=$(gh auth token) %(prog)s --year 2026

Note: Analysis always includes the current date by stopping at the next
      Tuesday after today. This captures the current week's state without
      projecting into the future.

For more information, see the script docstring or visit:
  https://github.com/IBM/mcp-context-forge
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Create mutually exclusive group for year vs since
    time_group = parser.add_mutually_exclusive_group()
    time_group.add_argument("--year", type=int, help="Year to analyze (default: current year if --since not specified). Analysis stops at next Tuesday after today.")
    time_group.add_argument(
        "--since", type=str, help="Start date for analysis (formats: YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, YYYY/MM/DD, MM/DD/YYYY, 'Month DD, YYYY'). Analysis stops at next Tuesday after today."
    )

    parser.add_argument("--repo", type=str, default="IBM/mcp-context-forge", help="Repository in format owner/repo (default: IBM/mcp-context-forge)")
    parser.add_argument("--token", type=str, default=os.environ.get("GITHUB_TOKEN"), help="GitHub personal access token (default: from GITHUB_TOKEN env var)")
    parser.add_argument("--output", type=str, default="github_history.png", help="Output PNG file path (default: github_history.png)")

    args = parser.parse_args()

    # Print header
    print()
    print("=" * 70)
    print("GitHub History Chart Generator")
    print("=" * 70)
    print()

    # Warn if no token provided
    if not args.token:
        print_usage_hint()

    print(f"Analyzing repository: {args.repo}")

    # Determine time range and get Tuesdays
    now = datetime.now()
    if args.since:
        try:
            since_date = parse_date(args.since)
            tuesdays = get_tuesdays_since_date(since_date)
            time_range = f"Since {since_date.strftime('%Y-%m-%d')}"
            print(f"Time range: Since {since_date.strftime('%Y-%m-%d')} (through next Tuesday after today)")
        except ValueError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
    else:
        year = args.year if args.year else now.year
        tuesdays = get_tuesdays_in_year(year)
        if year == now.year:
            time_range = f"{year} (through next Tuesday after today)"
            print(f"Year: {year} (through next Tuesday after today)")
        else:
            time_range = str(year)
            print(f"Year: {year}")

    print(f"Output file: {args.output}")
    print()

    # Fetch all issues and PRs once
    try:
        all_issues = fetch_all_issues(args.repo, args.token, state="all")
        all_prs = fetch_all_prs(args.repo, args.token, state="all")
    except Exception as e:
        print()
        print(f"ERROR: Failed to fetch data from GitHub: {e}")
        print()
        print("Common issues:")
        print("  - Invalid repository name (use format: owner/repo)")
        print("  - Repository is private (requires token with appropriate scope)")
        print("  - Network connectivity issues")
        print("  - Rate limit exceeded (use a GitHub token)")
        print()
        sys.exit(1)

    print()

    print(f"Found {len(tuesdays)} Tuesdays in the specified range")
    if tuesdays:
        print(f"Date range: {tuesdays[0].strftime('%Y-%m-%d')} to {tuesdays[-1].strftime('%Y-%m-%d')}")
    print()

    # Count open items for each Tuesday
    issues_counts = []
    prs_counts = []

    print("Calculating open counts for each Tuesday...")
    for i, tuesday in enumerate(tuesdays, 1):
        issues_count = count_open_at_date(all_issues, tuesday)
        prs_count = count_open_at_date(all_prs, tuesday, exclude_drafts=True)

        issues_counts.append(issues_count)
        prs_counts.append(prs_count)

        print(f"  Tuesday {i}/{len(tuesdays)} ({tuesday.strftime('%Y-%m-%d')}): " f"Issues: {issues_count}, PRs: {prs_count}")

    print()
    print("Creating chart...")
    create_chart(tuesdays, issues_counts, prs_counts, args.output, args.repo, time_range)

    # Print summary statistics
    print()
    print("=" * 70)
    print("Summary Statistics")
    print("=" * 70)
    print(f"  Average open issues: {sum(issues_counts) / len(issues_counts):.1f}")
    print(f"  Average open PRs:    {sum(prs_counts) / len(prs_counts):.1f}")
    print(f"  Max open issues:     {max(issues_counts)} " f"(on {tuesdays[issues_counts.index(max(issues_counts))].strftime('%Y-%m-%d')})")
    print(f"  Max open PRs:        {max(prs_counts)} " f"(on {tuesdays[prs_counts.index(max(prs_counts))].strftime('%Y-%m-%d')})")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
