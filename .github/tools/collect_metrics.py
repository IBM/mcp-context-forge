"""Collects various metrics from a GitHub repository using the GitHub API.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Trevor Grant

Metrics include:
- Standard repository attributes (stars, forks, issues, etc.)
- New forks and contributors in the last period
- Traffic data (views, clones, referrers, paths)
- Issues and pull requests opened/closed in the last period
- Comments on issues and pull requests in the last period
- Discussions metrics via GraphQL
Outputs the collected metrics to a Parquet file.

This is uploaded to the GitHub AI Alliance repository for metrics collection.
"""

import os
import sys
import pandas as pd
from github import (
    Github,
    GithubException,
    UnknownObjectException,
)  # Added UnknownObjectException
from datetime import datetime, timedelta, timezone  # Added timezone
import time
import requests
import json


# --- GraphQL Helper ---
def run_graphql_query(token, query, variables=None):
    """Runs a GraphQL query against the GitHub API."""
    graphql_url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    try:
        response = requests.post(
            graphql_url, headers=headers, json=payload, timeout=30
        )  # Added timeout
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        json_response = response.json()

        # Check for GraphQL-specific errors
        if "errors" in json_response:
            error_details = json.dumps(json_response["errors"], indent=2)
            # Consider logging this instead of printing if it gets noisy
            print(f"GraphQL query failed with errors:\n{error_details}")
            # Decide how to handle: return None, raise exception, etc.
            # Returning None might be suitable for metrics collection
            return None

        return json_response.get("data")

    except requests.exceptions.RequestException as e:
        print(f"Error during GraphQL request: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding GraphQL JSON response: {e}")
        return None


# --- Configuration ---
token = os.getenv("GITHUB_TOKEN")
repo_name = os.getenv("GITHUB_REPOSITORY")  # Format: 'owner/repo'
lookback_days = 1  # Define the period for "new" items (e.g., last 1 day)
output_filename = f"github_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
max_retries = 3  # Retries for API calls that might need time

# --- Input Validation ---
if not token:
    print("Error: GITHUB_TOKEN environment variable not set.")
    sys.exit(1)
if not repo_name:
    print("Error: GITHUB_REPOSITORY environment variable not set.")
    sys.exit(1)

print(f"Starting metrics collection for repository: {repo_name}")
print(f"Lookback period for 'new' items: {lookback_days} day(s)")

# --- GitHub API Connection ---
try:
    g = Github(token, retry=5, timeout=15)  # Added retry and timeout to Github object
    repo = g.get_repo(repo_name)
    print("Successfully connected to GitHub API.")
except GithubException as e:
    print(f"Error connecting to GitHub API or getting repository: {e}")
    sys.exit(1)

# --- Define Cutoff Time (UTC) ---
# Use timezone-aware datetime object for 'since' parameter
cutoff_datetime_aware = datetime.now(timezone.utc) - timedelta(days=lookback_days)
# Use naive datetime for simple comparisons if needed (e.g., fork creation)
cutoff_datetime_naive = datetime.utcnow() - timedelta(days=lookback_days)
print(f"Calculating 'new' items since: {cutoff_datetime_aware}")


# --- Data Collection ---
metrics = {}
metrics["timestamp_utc"] = datetime.now(timezone.utc)  # Store timezone-aware timestamp
metrics["repository_name"] = repo.full_name

print("\nFetching standard repository metrics...")
try:
    # Standard Attributes
    metrics["stars"] = repo.stargazers_count
    metrics["watchers"] = repo.subscribers_count
    metrics["forks_total"] = repo.forks_count  # Renamed for clarity
    metrics["open_issues_total"] = repo.open_issues_count  # Renamed for clarity
    metrics["network_count"] = repo.network_count
    metrics["size_kb"] = repo.size
    metrics["language"] = repo.language
    metrics["created_at_utc"] = repo.created_at
    metrics["pushed_at_utc"] = repo.pushed_at
    metrics["archived"] = repo.archived
    metrics["disabled"] = repo.disabled
    metrics["has_issues"] = repo.has_issues
    metrics["has_projects"] = repo.has_projects
    metrics["has_wiki"] = repo.has_wiki
    metrics["has_pages"] = repo.has_pages
    metrics["has_downloads"] = repo.has_downloads
    metrics["has_discussions"] = repo.has_discussions  # Added check for discussions
    metrics["license"] = repo.get_license().license.spdx_id if repo.license else None

    # List Counts
    metrics["contributors_count_total"] = repo.get_contributors().totalCount
    metrics["releases_count_total"] = repo.get_releases().totalCount

except GithubException as e:
    print(f"Warning: Could not fetch some standard metrics: {e}")
    # Initialize potentially missed metrics
    standard_keys = [
        "stars",
        "watchers",
        "forks_total",
        "open_issues_total",
        "network_count",
        "size_kb",
        "language",
        "created_at_utc",
        "pushed_at_utc",
        "archived",
        "disabled",
        "has_issues",
        "has_projects",
        "has_wiki",
        "has_pages",
        "has_downloads",
        "has_discussions",
        "license",
        "contributors_count_total",
        "releases_count_total",
    ]
    for key in standard_keys:
        if key not in metrics:
            metrics[key] = None


# --- Calculated Metrics: "New" Forks (Last Period) ---
print(f"\nCalculating new forks in the last {lookback_days} day(s)...")
new_forks_count = 0
try:
    # Iterate through forks - PaginatedList handles pagination
    for fork in repo.get_forks():
        # Compare naive UTC datetimes
        if fork.created_at.replace(tzinfo=None) >= cutoff_datetime_naive:
            new_forks_count += 1
        else:
            # Forks are sorted newest first, so we can stop early
            break
    metrics["forks_new_last_period"] = new_forks_count
    print(f"Found {new_forks_count} new forks.")
except GithubException as e:
    print(f"Warning: Could not calculate new forks: {e}")
    metrics["forks_new_last_period"] = None


# --- Calculated Metrics: "New" Contributors (Approximation using stats) ---
# Stays the same as the previously corrected version - using weekly stats approximation
print(f"\nCalculating recent contributor additions (weekly stats)...")
recent_contributor_adds = 0
retries = 0
stats_contributors = None
while retries < max_retries:
    try:
        stats_contributors = repo.get_stats_contributors()
        if stats_contributors is not None:
            break
        else:
            print(
                f"Contributor stats not available yet (Attempt {retries+1}/{max_retries}). Waiting 30 seconds..."
            )
            time.sleep(30)
            retries += 1
    except GithubException as e:
        if e.status == 202:
            print(
                f"Contributor stats computing (Attempt {retries+1}/{max_retries}). Waiting 30 seconds..."
            )
            time.sleep(30)
            retries += 1
        elif e.status == 404:
            print(f"Warning: Contributor stats API 404: {e}")
            stats_contributors = []  # Treat as empty
            break
        else:
            print(f"Warning: Could not fetch contributor stats: {e}")
            stats_contributors = None
            break

if stats_contributors is not None:
    cutoff_date_stats_naive = (
        cutoff_datetime_naive  # Use naive for comparison consistency
    )
    print(
        f"Cutoff date for contributor stats: {cutoff_date_stats_naive} UTC (comparing week start)"
    )
    for stat in stats_contributors:
        if not hasattr(stat, "weeks") or not stat.weeks:
            continue
        for week_stat in stat.weeks:
            if not hasattr(week_stat, "w"):
                continue
            week_start_time = week_stat.w
            if isinstance(week_start_time, datetime):
                naive_week_start = week_start_time.replace(tzinfo=None)
                if naive_week_start >= cutoff_date_stats_naive:
                    if hasattr(week_stat, "a") and isinstance(week_stat.a, int):
                        recent_contributor_adds += week_stat.a
            else:
                print(
                    f"Warning: Unexpected type for week_stat.w: {type(week_start_time)}. Skipping."
                )
    metrics["contributors_additions_recent_weeks"] = (
        recent_contributor_adds  # Changed name slightly
    )
    print(
        f"Found {recent_contributor_adds} contributor additions (approx) based on recent weekly stats."
    )
else:
    metrics["contributors_additions_recent_weeks"] = None
    if retries == max_retries:
        print("Warning: Contributor stats could not be retrieved.")


# --- Traffic Data (Last Day if available) ---
print("\nFetching traffic data (views and clones)...")

# Define the target date (yesterday in UTC)
target_traffic_date_naive = (datetime.utcnow() - timedelta(days=1)).date()
print(f"Targeting traffic data for date: {target_traffic_date_naive}")

# Initialize metrics for the target date
metrics["traffic_views_last_day_total"] = None
metrics["traffic_views_last_day_unique"] = None
metrics["traffic_clones_last_day_total"] = None
metrics["traffic_clones_last_day_unique"] = None

# --- Process Views ---
found_view_data_for_target = False
try:
    views_traffic_obj = repo.get_views_traffic(per="day")
    # Check if the object and the 'views' list exist and are not empty
    if (
        views_traffic_obj
        and hasattr(views_traffic_obj, "views")
        and views_traffic_obj.views
    ):
        # Iterate through the list of daily view data
        for view_entry in views_traffic_obj.views:
            # Check if the entry has a timestamp and it's a datetime object
            if hasattr(view_entry, "timestamp") and isinstance(
                view_entry.timestamp, datetime
            ):
                # Compare the date part of the timestamp with our target date
                if view_entry.timestamp.date() == target_traffic_date_naive:
                    # Found the data for yesterday!
                    metrics["traffic_views_last_day_total"] = getattr(
                        view_entry, "count", None
                    )  # Use getattr for safety
                    metrics["traffic_views_last_day_unique"] = getattr(
                        view_entry, "uniques", None
                    )
                    print(
                        f"Found views for {target_traffic_date_naive}: Total={metrics['traffic_views_last_day_total']}, Unique={metrics['traffic_views_last_day_unique']}"
                    )
                    found_view_data_for_target = True
                    break  # Stop searching once found
            else:
                print(
                    f"Warning: Skipping view entry with missing or invalid timestamp: {view_entry}"
                )

        # After checking all entries, if we didn't find the target date
        if not found_view_data_for_target:
            print(
                f"Warning: No view data found specifically for target date {target_traffic_date_naive}. Metrics remain None."
            )
            # metrics['traffic_views_last_day_total'] = 0 # Alternative: default to 0 if preferred
            # metrics['traffic_views_last_day_unique'] = 0

    else:
        print(
            "Warning: No daily view data list available or attribute 'views' missing."
        )
        # Metrics remain None as initialized

except GithubException as e:
    print(f"Warning: Could not fetch views traffic data: {e}")
    # Metrics remain None
except Exception as e:  # Catch other potential errors during processing
    print(f"Warning: Error processing view data: {e}")
    # Metrics remain None


# --- Process Clones ---
found_clone_data_for_target = False
try:
    clones_traffic_obj = repo.get_clones_traffic(per="day")
    # Check if the object and the 'clones' list exist and are not empty
    if (
        clones_traffic_obj
        and hasattr(clones_traffic_obj, "clones")
        and clones_traffic_obj.clones
    ):
        # Iterate through the list of daily clone data
        for clone_entry in clones_traffic_obj.clones:
            # Check if the entry has a timestamp and it's a datetime object
            if hasattr(clone_entry, "timestamp") and isinstance(
                clone_entry.timestamp, datetime
            ):
                # Compare the date part of the timestamp with our target date
                if clone_entry.timestamp.date() == target_traffic_date_naive:
                    # Found the data for yesterday!
                    metrics["traffic_clones_last_day_total"] = getattr(
                        clone_entry, "count", None
                    )  # Use getattr for safety
                    metrics["traffic_clones_last_day_unique"] = getattr(
                        clone_entry, "uniques", None
                    )
                    print(
                        f"Found clones for {target_traffic_date_naive}: Total={metrics['traffic_clones_last_day_total']}, Unique={metrics['traffic_clones_last_day_unique']}"
                    )
                    found_clone_data_for_target = True
                    break  # Stop searching once found
            else:
                print(
                    f"Warning: Skipping clone entry with missing or invalid timestamp: {clone_entry}"
                )

        # After checking all entries, if we didn't find the target date
        if not found_clone_data_for_target:
            print(
                f"Warning: No clone data found specifically for target date {target_traffic_date_naive}. Metrics remain None."
            )
            # metrics['traffic_clones_last_day_total'] = 0 # Alternative: default to 0
            # metrics['traffic_clones_last_day_unique'] = 0

    else:
        print(
            "Warning: No daily clone data list available or attribute 'clones' missing."
        )
        # Metrics remain None as initialized

except GithubException as e:
    print(f"Warning: Could not fetch clones traffic data: {e}")
    # Metrics remain None
except Exception as e:  # Catch other potential errors during processing
    print(f"Warning: Error processing clone data: {e}")
    # Metrics remain None


# --- Referrers and Popular Content Data (Last 14 days) ---
print("\nFetching top referrers data (last 14 days)...")
top_referrers_data = []  # Initialize empty list
try:
    top_referrers_list = repo.get_top_referrers()
    # Iterate through the PaginatedList of Referrer objects
    for r in top_referrers_list:
        # Extract relevant data into a dictionary
        # Use getattr for safety in case attributes are missing unexpectedly
        referrer_dict = {
            "referrer": getattr(r, "referrer", None),
            "count": getattr(r, "count", None),
            "uniques": getattr(r, "uniques", None),
        }
        top_referrers_data.append(referrer_dict)

    metrics["traffic_top_referrers_data"] = (
        top_referrers_data  # Store the list of dicts
    )
    print(f"Fetched {len(top_referrers_data)} top referrer entries.")

except GithubException as e:
    print(f"Warning: Could not fetch top referrers: {e}")
    metrics["traffic_top_referrers_data"] = None  # Set to None on API error
except Exception as e:  # Catch potential errors during processing the list
    print(f"Warning: Error processing referrer data: {e}")
    metrics["traffic_top_referrers_data"] = None


print("\nFetching top paths data (last 14 days)...")
top_paths_data = []  # Initialize empty list
try:
    top_paths_list = repo.get_top_paths()
    # Iterate through the PaginatedList of Path objects
    for p in top_paths_list:
        # Extract relevant data into a dictionary
        path_dict = {
            "path": getattr(p, "path", None),
            "title": getattr(p, "title", None),  # Title might not always exist
            "count": getattr(p, "count", None),
            "uniques": getattr(p, "uniques", None),
        }
        top_paths_data.append(path_dict)

    metrics["traffic_top_paths_data"] = top_paths_data  # Store the list of dicts
    print(f"Fetched {len(top_paths_data)} top path entries.")

except GithubException as e:
    print(f"Warning: Could not fetch top paths: {e}")
    metrics["traffic_top_paths_data"] = None  # Set to None on API error
except Exception as e:  # Catch potential errors during processing the list
    print(f"Warning: Error processing path data: {e}")
    metrics["traffic_top_paths_data"] = None


# --- Issues Opened/Closed Last Period ---
print(f"\nCalculating Issues opened/closed in the last {lookback_days} day(s)...")
issues_opened_count = 0
issues_closed_count = 0
issues_comments_count = 0
try:
    # Issues opened: Use 'since' which filters by creation time
    opened_issues = repo.get_issues(
        state="all", sort="created", since=cutoff_datetime_aware
    )
    for issue in opened_issues:
        # Double check creation time (though 'since' should handle it)
        # Note: get_issues() returns PRs as well. We need to filter later if needed.
        # For now, count all items returned by get_issues as potential "issues" opened.
        issues_opened_count += 1

    # Issues closed: Need to check closed_at time
    # Get recently updated closed issues/PRs
    recently_updated_closed_items = repo.get_issues(
        state="closed", sort="updated", direction="desc", since=cutoff_datetime_aware
    )
    for item in recently_updated_closed_items:
        if item.closed_at and item.closed_at >= cutoff_datetime_aware:
            # Check if it's actually an Issue (not a PR)
            # An item is a PR if it has the 'pull_request' attribute
            if not hasattr(item, "pull_request") or not item.pull_request:
                issues_closed_count += 1

    metrics["issues_opened_last_period"] = issues_opened_count
    metrics["issues_closed_last_period"] = issues_closed_count
    print(f"Found: Opened={issues_opened_count}, Closed={issues_closed_count}")

except GithubException as e:
    print(f"Warning: Could not calculate issue metrics: {e}")
    metrics["issues_opened_last_period"] = None
    metrics["issues_closed_last_period"] = None

# --- Pull Requests Opened/Closed Last Period ---
print(f"\nCalculating PRs opened/closed in the last {lookback_days} day(s)...")
prs_opened_count = 0
prs_closed_count = 0  # Includes merged PRs
prs_merged_count = 0
try:
    # PRs opened: Use 'since' on pulls endpoint
    opened_pulls = repo.get_pulls(
        state="all", sort="created", direction="desc", base=repo.default_branch
    )  # Filter by base branch if desired
    # Iterate and filter by date - 'since' might not exist for pulls in PyGithub < 2.0 or work as expected
    for pr in opened_pulls:
        if pr.created_at >= cutoff_datetime_aware:
            prs_opened_count += 1
        else:
            break  # Since sorted by created desc

    # PRs closed/merged: Check closed_at/merged_at
    # Get recently updated closed PRs
    recently_updated_closed_pulls = repo.get_pulls(
        state="closed", sort="updated", direction="desc"
    )  # , since=cutoff_datetime_aware) # since might not work well here
    for pr in recently_updated_closed_pulls:
        # Stop checking if PRs updated date is older than cutoff
        if pr.updated_at < cutoff_datetime_aware:
            break

        if pr.closed_at and pr.closed_at >= cutoff_datetime_aware:
            prs_closed_count += 1
            if pr.merged_at and pr.merged_at >= cutoff_datetime_aware:
                prs_merged_count += 1

    metrics["prs_opened_last_period"] = prs_opened_count
    metrics["prs_closed_last_period"] = prs_closed_count
    metrics["prs_merged_last_period"] = prs_merged_count
    print(
        f"Found: Opened={prs_opened_count}, Closed={prs_closed_count}, Merged={prs_merged_count}"
    )

except GithubException as e:
    print(f"Warning: Could not calculate PR metrics: {e}")
    metrics["prs_opened_last_period"] = None
    metrics["prs_closed_last_period"] = None
    metrics["prs_merged_last_period"] = None


# --- Comments (Issues, PRs) Last Period ---
print(f"\nCalculating Issue/PR Comments in the last {lookback_days} day(s)...")
issue_comments_last_period = 0
pr_comments_last_period = 0  # Includes review comments and general PR comments

try:
    # General Issue/PR comments (use issues endpoint)
    all_comments = repo.get_issues_comments(
        sort="created", direction="desc", since=cutoff_datetime_aware
    )
    for comment in all_comments:
        # Check creation date again just to be sure
        if comment.created_at >= cutoff_datetime_aware:
            # Differentiate based on URL
            if "/pull/" in comment.html_url:
                pr_comments_last_period += 1
            else:
                issue_comments_last_period += 1
        else:
            # Since comments are sorted desc, we can stop
            break

    # PR Review Comments
    review_comments = repo.get_pulls_comments(
        sort="created", direction="desc", since=cutoff_datetime_aware
    )
    for comment in review_comments:
        if comment.created_at >= cutoff_datetime_aware:
            pr_comments_last_period += 1
        else:
            break

    metrics["issue_comments_last_period"] = issue_comments_last_period
    metrics["pr_comments_last_period"] = pr_comments_last_period  # Combined count
    print(
        f"Found: Issue Comments={issue_comments_last_period}, PR Comments={pr_comments_last_period}"
    )

except GithubException as e:
    print(f"Warning: Could not calculate comment metrics: {e}")
    metrics["issue_comments_last_period"] = None
    metrics["pr_comments_last_period"] = None


# --- Discussions Metrics (via GraphQL) ---
print(
    f"\nCalculating Discussion Metrics for the last {lookback_days} day(s) via GraphQL..."
)

# Initialize metrics
metrics["discussions_opened_last_period"] = None
metrics["discussions_comments_last_period"] = None  # Still challenging

# Check if discussions are enabled first
if metrics.get("has_discussions"):
    # Format the cutoff date as an ISO 8601 string for GraphQL
    since_iso_string = cutoff_datetime_aware.isoformat()

    # --- Query for Discussions Opened ---
    # Use the search API via GraphQL for efficient filtering by creation date
    search_query_string = (
        f"repo:{repo_name} type:discussion is:open created:>={since_iso_string}"
    )
    # Also count closed ones created in the period? Add another query or adjust logic if needed.
    # This query counts currently 'open' discussions created since the cutoff.

    discussions_search_query = """  
    query($searchQuery: String!) {  
      search(query: $searchQuery, type: DISCUSSION, first: 0) {  
        discussionCount  
      }  
    }  
    """
    variables = {"searchQuery": search_query_string}

    print(
        f"Running GraphQL search for new discussions with query: '{search_query_string}'"
    )
    graphql_data_disc = run_graphql_query(token, discussions_search_query, variables)

    if graphql_data_disc and "search" in graphql_data_disc:
        try:
            metrics["discussions_opened_last_period"] = graphql_data_disc["search"][
                "discussionCount"
            ]
            print(
                f"Found via GraphQL Search: Discussions Opened={metrics['discussions_opened_last_period']}"
            )
        except (KeyError, TypeError) as e:
            print(
                f"Warning: Could not extract discussion count from GraphQL response: {e}. Response: {graphql_data_disc}"
            )
    else:
        print("Warning: Failed to get discussion count via GraphQL search.")

    # --- Query for Discussion Comments ---
    # NOTE: Getting an exact count of *all* comments across *all* discussions created
    # within a specific time window using a single, efficient GraphQL query is difficult.
    # The search API doesn't seem to support filtering for `type:discussioncomment` directly.
    # A possible (but potentially slow and complex) alternative would be:
    # 1. Fetch discussions UPDATED since the cutoff date.
    # 2. For each discussion, fetch comments created since the cutoff date (requires pagination per discussion).
    # This approach can lead to many API calls and is not implemented here for efficiency.
    # We will leave `discussions_comments_last_period` as None.

    print(
        "Note: Fetching discussion *comment* counts for the period is complex with GraphQL Search and not implemented."
    )
    metrics["discussions_comments_last_period"] = None  # Explicitly set to None

else:
    print(
        "Discussions feature not enabled for this repository. Skipping GraphQL calls."
    )
    # Ensure metrics are None if discussions are disabled
    metrics["discussions_opened_last_period"] = None
    metrics["discussions_comments_last_period"] = None

# --- Final Data Preparation ---
# Convert datetime objects to string or ensure pyarrow handles them
for key, value in metrics.items():
    if isinstance(value, datetime):
        # Ensure timezone-aware datetimes are handled correctly by pyarrow
        # Or convert to ISO format string with timezone
        if value.tzinfo is None:
            # Optional: Make naive datetimes timezone-aware (assuming UTC) before writing
            # metrics[key] = value.replace(tzinfo=timezone.utc)
            pass  # Keep naive UTC as is
        # else: keep timezone-aware datetimes as is
        # Alternatively, convert all to ISO strings:
        # metrics[key] = value.isoformat()


# Create DataFrame - Note the list around the dictionary for a single row
try:
    df = pd.DataFrame([metrics])

    # Define specific data types (especially nullable integers)
    # Adjust based on the actual metrics collected
    dtype_mapping = {
        "stars": pd.Int64Dtype(),
        "watchers": pd.Int64Dtype(),
        "forks_total": pd.Int64Dtype(),
        "open_issues_total": pd.Int64Dtype(),
        "network_count": pd.Int64Dtype(),
        "size_kb": pd.Int64Dtype(),
        "contributors_count_total": pd.Int64Dtype(),
        "releases_count_total": pd.Int64Dtype(),
        "forks_new_last_period": pd.Int64Dtype(),
        "contributors_additions_recent_weeks": pd.Int64Dtype(),
        "traffic_views_last_day_total": pd.Int64Dtype(),
        "traffic_views_last_day_unique": pd.Int64Dtype(),
        "traffic_clones_last_day_total": pd.Int64Dtype(),
        "traffic_clones_last_day_unique": pd.Int64Dtype(),
        # 'traffic_referrers_top_count': pd.Int64Dtype(), 'traffic_popular_paths_top_count': pd.Int64Dtype(),
        "issues_opened_last_period": pd.Int64Dtype(),
        "issues_closed_last_period": pd.Int64Dtype(),
        "prs_opened_last_period": pd.Int64Dtype(),
        "prs_closed_last_period": pd.Int64Dtype(),
        "prs_merged_last_period": pd.Int64Dtype(),
        "issue_comments_last_period": pd.Int64Dtype(),
        "pr_comments_last_period": pd.Int64Dtype(),
        "discussions_opened_last_period": pd.Int64Dtype(),
        "discussions_comments_last_period": pd.Int64Dtype(),
        # Add others as needed, boolean types usually fine, string types usually fine
    }
    # Filter out any keys from mapping that don't exist in the DataFrame (e.g., due to API errors)
    valid_dtype_mapping = {k: v for k, v in dtype_mapping.items() if k in df.columns}
    df = df.astype(valid_dtype_mapping)

    print("\n--- Collected Metrics ---")
    # Print columns horizontally for better readability if many columns
    pd.set_option("display.max_columns", None)  # Show all columns
    pd.set_option("display.width", 1000)  # Adjust width as needed
    print(df)

    # --- Write to Parquet ---
    print(f"\nWriting metrics to {output_filename}...")
    df.to_parquet(
        output_filename,
        engine="pyarrow",
        index=False,
        coerce_timestamps="us",
        allow_truncated_timestamps=False,
    )
    print("Successfully wrote Parquet file.")

except Exception as e:
    print(f"Error creating DataFrame or writing Parquet file: {e}")
    import traceback

    traceback.print_exc()  # Print full traceback for debugging
    sys.exit(1)

print("\nScript finished successfully.")
