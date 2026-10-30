#!/usr/bin/env python3
"""Resolve the review thread that contains a [claude-fixed] reply.

Used by .github/workflows/resolve-threads.yml, which checks out main and runs
this file from main. GraphQL runs only through `gh api graphql` with
GITHUB_TOKEN. The workflow skips unless the new comment is a reply by
aureviaeu starting with [claude-fixed]. [claude-declined] does not resolve;
the owner leaves that thread open and resolves it manually if they accept
the reasoning. This script repeats those checks. Threads are scanned in
pages, at most 100. An already-resolved thread is a no-op.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Callable

MAX_THREADS = 100
THREAD_PAGE = 50
COMMENT_PAGE = 100
MAX_EXTRA_COMMENT_PAGES = 20

FIXED_PREFIX = "[claude-fixed]"

THREADS_QUERY = f"""
query($owner: String!, $repo: String!, $number: Int!, $after: String) {{
  repository(owner: $owner, name: $repo) {{
    pullRequest(number: $number) {{
      reviewThreads(first: {THREAD_PAGE}, after: $after) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{
          id
          isResolved
          comments(first: {COMMENT_PAGE}) {{
            pageInfo {{ hasNextPage endCursor }}
            nodes {{ databaseId }}
          }}
        }}
      }}
    }}
  }}
}}
""".strip()

COMMENTS_QUERY = f"""
query($id: ID!, $after: String!) {{
  node(id: $id) {{
    ... on PullRequestReviewThread {{
      comments(first: {COMMENT_PAGE}, after: $after) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ databaseId }}
      }}
    }}
  }}
}}
""".strip()

RESOLVE_MUTATION = """
mutation($id: ID!) {
  resolveReviewThread(input: {threadId: $id}) {
    thread { id isResolved }
  }
}
""".strip()

GraphQL = Callable[[str, dict[str, Any]], dict[str, Any]]


def should_handle(author: str, body: str, in_reply_to: str) -> bool:
    """True when aureviaeu replied with [claude-fixed]. [claude-declined] stays open."""
    if author != "aureviaeu":
        return False
    if in_reply_to.strip() in ("", "0", "null", "None"):
        return False
    return body.startswith(FIXED_PREFIX)


def _page_info(connection: dict[str, Any]) -> tuple[bool, str | None]:
    info = connection.get("pageInfo") or {}
    has_next = bool(info.get("hasNextPage"))
    cursor = info.get("endCursor")
    if not cursor:
        has_next = False
    return has_next, cursor


def _comment_ids(connection: dict[str, Any]) -> list[int]:
    found: list[int] = []
    for node in connection.get("nodes") or []:
        database_id = node.get("databaseId")
        if isinstance(database_id, int):
            found.append(database_id)
    return found


def thread_contains(client: GraphQL, thread: dict[str, Any], comment_id: int) -> bool:
    """Whether comment_id is in this thread, paging comments after the first page."""
    comments = thread.get("comments") or {}
    if comment_id in _comment_ids(comments):
        return True
    has_next, cursor = _page_info(comments)
    seen_cursors: set[str] = set()
    for _ in range(MAX_EXTRA_COMMENT_PAGES):
        if not has_next or not cursor or cursor in seen_cursors:
            return False
        seen_cursors.add(cursor)
        data = client(COMMENTS_QUERY, {"id": thread["id"], "after": cursor})
        connection = (data.get("node") or {}).get("comments") or {}
        if comment_id in _comment_ids(connection):
            return True
        has_next, cursor = _page_info(connection)
    return False


def locate_thread(
    client: GraphQL,
    owner: str,
    repo: str,
    number: int,
    comment_id: int,
) -> tuple[str, bool] | None:
    """Return (thread id, isResolved) for comment_id within the first 100 threads."""
    scanned = 0
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while scanned < MAX_THREADS:
        data = client(
            THREADS_QUERY,
            {"owner": owner, "repo": repo, "number": number, "after": cursor},
        )
        pull_request = (data.get("repository") or {}).get("pullRequest")
        if not pull_request:
            raise RuntimeError(f"Pull request {owner}/{repo}#{number} was not found")
        connection = pull_request.get("reviewThreads") or {}
        nodes = connection.get("nodes") or []
        if not nodes:
            return None
        for thread in nodes:
            if scanned >= MAX_THREADS:
                break
            scanned += 1
            if not thread:
                continue
            if thread_contains(client, thread, comment_id):
                print(f"Matched comment {comment_id} after scanning {scanned} thread(s).")
                return thread["id"], bool(thread.get("isResolved"))
        has_next, next_cursor = _page_info(connection)
        if not has_next or not next_cursor or next_cursor in seen_cursors or scanned >= MAX_THREADS:
            print(f"Scanned {scanned} thread(s); comment {comment_id} was not among the first {MAX_THREADS}.")
            return None
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return None


def resolve_thread(client: GraphQL, thread_id: str) -> None:
    data = client(RESOLVE_MUTATION, {"id": thread_id})
    thread = (data.get("resolveReviewThread") or {}).get("thread") or {}
    if not thread.get("isResolved"):
        raise RuntimeError(f"resolveReviewThread did not resolve {thread_id}")


def gh_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Call `gh api graphql`. None becomes a JSON null via -F key=null."""
    command = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is None:
            command.extend(["-F", f"{key}=null"])
        elif isinstance(value, int) and not isinstance(value, bool):
            command.extend(["-F", f"{key}={value}"])
        else:
            command.extend(["-f", f"{key}={value}"])
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        lowered = detail.lower()
        if "already resolved" in lowered:
            print("Thread already resolved; nothing to do.")
            return {"resolveReviewThread": {"thread": {"id": variables.get("id"), "isResolved": True}}}
        raise RuntimeError(detail or f"gh api graphql exited {completed.returncode}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"gh api graphql returned non-JSON: {completed.stdout[:500]}") from error
    errors = payload.get("errors") or []
    if errors:
        detail = "; ".join(str(item.get("message", item)) for item in errors)
        if "already resolved" in detail.lower():
            print("Thread already resolved; nothing to do.")
            return {"resolveReviewThread": {"thread": {"id": variables.get("id"), "isResolved": True}}}
        raise RuntimeError(detail)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("gh api graphql response did not include data")
    return data


def main() -> int:
    author = os.environ.get("COMMENT_AUTHOR", "")
    body = os.environ.get("COMMENT_BODY", "")
    in_reply_to = os.environ.get("IN_REPLY_TO_ID", "")
    if not should_handle(author, body, in_reply_to):
        print("Skip: comment is not an aureviaeu reply starting with [claude-fixed].")
        return 0

    owner = os.environ["REPO_OWNER"]
    repo = os.environ["REPO_NAME"]
    number = int(os.environ["PR_NUMBER"])
    comment_id = int(os.environ["COMMENT_ID"])

    try:
        located = locate_thread(gh_graphql, owner, repo, number, comment_id)
    except RuntimeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if located is None:
        print(
            f"FAIL: comment {comment_id} was not found on {owner}/{repo}#{number}.",
            file=sys.stderr,
        )
        return 1

    thread_id, is_resolved = located
    if is_resolved:
        print(f"Thread {thread_id} is already resolved; nothing to do.")
        return 0

    try:
        resolve_thread(gh_graphql, thread_id)
    except RuntimeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"Resolved thread {thread_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
