#!/usr/bin/env python3
"""
Closes open Jira tasks that have been open for more than 2 days.

Required environment variables:
  JIRA_BASE_URL   - e.g. https://yourcompany.atlassian.net
  JIRA_EMAIL      - Jira account email
  JIRA_API_TOKEN  - Jira API token (https://id.atlassian.com/manage-profile/security/api-tokens)

Optional:
  JIRA_PROJECT_KEY - Limit to a specific project (e.g. LTM). If unset, all projects are scanned.
  DRY_RUN          - Set to "true" to log what would be closed without actually closing.
"""

import os
import sys
import requests
from requests.auth import HTTPBasicAuth

JIRA_BASE_URL = os.environ["JIRA_BASE_URL"].rstrip("/")
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_API_TOKEN = os.environ["JIRA_API_TOKEN"]
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

AUTH = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

CLOSE_TRANSITION_NAMES = {"done", "closed", "close", "resolve", "resolved", "complete", "completed"}


def jira_get(path, params=None):
    url = f"{JIRA_BASE_URL}/rest/api/3/{path}"
    resp = requests.get(url, headers=HEADERS, auth=AUTH, params=params)
    resp.raise_for_status()
    return resp.json()


def jira_post(path, payload):
    url = f"{JIRA_BASE_URL}/rest/api/3/{path}"
    resp = requests.post(url, json=payload, headers=HEADERS, auth=AUTH)
    resp.raise_for_status()
    return resp


def get_open_issues_older_than_2_days():
    project_clause = f"project = {JIRA_PROJECT_KEY} AND " if JIRA_PROJECT_KEY else ""
    jql = f"{project_clause}statusCategory != Done AND created <= -2d ORDER BY created ASC"

    issues = []
    start = 0
    page_size = 100

    while True:
        data = jira_get("search", params={
            "jql": jql,
            "startAt": start,
            "maxResults": page_size,
            "fields": "summary,status,created",
        })
        issues.extend(data["issues"])
        start += page_size
        if start >= data["total"]:
            break

    return issues


def get_close_transition_id(issue_key):
    data = jira_get(f"issue/{issue_key}/transitions")
    for t in data.get("transitions", []):
        if t["name"].lower() in CLOSE_TRANSITION_NAMES:
            return t["id"]
    # Fall back to any transition that moves to a "Done" category
    for t in data.get("transitions", []):
        if t.get("to", {}).get("statusCategory", {}).get("key") == "done":
            return t["id"]
    return None


def close_issue(issue_key, transition_id):
    jira_post(f"issue/{issue_key}/transitions", {"transition": {"id": transition_id}})


def main():
    print(f"Fetching open Jira issues older than 2 days (dry_run={DRY_RUN})...")
    issues = get_open_issues_older_than_2_days()
    print(f"Found {len(issues)} issue(s) to close.")

    closed = 0
    skipped = 0

    for issue in issues:
        key = issue["key"]
        summary = issue["fields"]["summary"]
        created = issue["fields"]["created"]

        transition_id = get_close_transition_id(key)
        if transition_id is None:
            print(f"  SKIP {key} — no close transition available | {summary}")
            skipped += 1
            continue

        if DRY_RUN:
            print(f"  DRY-RUN would close {key} (created {created}) | {summary}")
        else:
            close_issue(key, transition_id)
            print(f"  CLOSED {key} (created {created}) | {summary}")
        closed += 1

    print(f"\nDone. Closed: {closed}, Skipped (no transition): {skipped}")
    if skipped > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
