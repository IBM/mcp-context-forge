"""Decide whether a secrets-baseline-only commit can skip full CI."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

ALLOWED_FILE = ".secrets.baseline"


def append(path: str | None, line: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")


def api_json(path: str, query: dict[str, str] | None = None) -> dict:
    url = f"{os.environ['GITHUB_API_URL']}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def finish(run_full_ci: bool, reason: str) -> None:
    append(os.environ["GITHUB_OUTPUT"], f"run-full-ci={str(run_full_ci).lower()}")
    append(os.environ["GITHUB_OUTPUT"], f"reason={reason}")
    append(os.environ.get("GITHUB_STEP_SUMMARY"), "### Full CI decision")
    append(os.environ.get("GITHUB_STEP_SUMMARY"), reason)
    print(reason)
    sys.exit(0)


def is_baseline_only(files: list[dict]) -> bool:
    return len(files) == 1 and files[0].get("filename") == ALLOWED_FILE and files[0].get("status") == "modified"


def previous_success(repo: str, workflow_file: str, sha: str, event_name: str, default_branch: str) -> bool:
    query = {"event": event_name, "head_sha": sha, "status": "success", "per_page": "10"}
    if event_name == "push":
        query["branch"] = default_branch
        query["exclude_pull_requests"] = "true"
    data = api_json(f"/repos/{repo}/actions/workflows/{workflow_file}/runs", query)
    return any(run.get("event") == event_name and run.get("head_sha") == sha and (event_name != "push" or run.get("head_branch") == default_branch) for run in data.get("workflow_runs", []))


def main() -> None:
    event = json.loads(os.environ["EVENT_JSON"])
    event_name = os.environ["EVENT_NAME"]
    default_branch = event.get("repository", {}).get("default_branch") or "main"

    if event_name not in {"pull_request", "push"}:
        finish(True, f"event {event_name} is not eligible for secrets-baseline-only skipping")
    if event_name == "push" and os.environ["GITHUB_REF_TYPE_VALUE"] == "tag":
        finish(True, "tag refs are not eligible for secrets-baseline-only skipping")

    if event_name == "pull_request":
        target_sha = event.get("pull_request", {}).get("head", {}).get("sha") or os.environ["GITHUB_SHA_VALUE"]
        commit_repo = event.get("pull_request", {}).get("head", {}).get("repo", {}).get("full_name") or os.environ["GITHUB_REPOSITORY_NAME"]
    else:
        target_sha = event.get("after") or os.environ["GITHUB_SHA_VALUE"]
        commit_repo = os.environ["GITHUB_REPOSITORY_NAME"]

    try:
        commit = api_json(f"/repos/{commit_repo}/commits/{target_sha}")
        changed_files = commit.get("files", [])
        parents = commit.get("parents", [])
        previous_sha = parents[0]["sha"] if parents else ""
    except Exception as exc:
        finish(True, f"could not inspect latest commit; run full CI: {exc}")

    if not changed_files:
        finish(True, "latest commit changed no files; run full CI")
    if not is_baseline_only(changed_files):
        finish(True, "latest commit is not secrets-baseline-only; run full CI")
    if not previous_sha:
        finish(True, "could not resolve previous commit; run full CI")

    workflow_file = os.environ["WORKFLOW_FILE"]
    try:
        if previous_success(os.environ["GITHUB_REPOSITORY_NAME"], workflow_file, previous_sha, event_name, default_branch):
            finish(False, f"latest commit changes only {ALLOWED_FILE}; previous {workflow_file} {event_name} run passed on {previous_sha}; skip full CI")
    except Exception as exc:
        finish(True, f"could not verify previous workflow success; run full CI: {exc}")

    finish(True, f"latest commit changes only {ALLOWED_FILE}, but no successful previous {workflow_file} {event_name} run was found for {previous_sha}; run full CI")


if __name__ == "__main__":
    main()
