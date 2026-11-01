#!/usr/bin/env python3
"""Count the token owner's commits, including forks, without publishing repo data."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORIES_QUERY = """
query($after: String) {
  viewer {
    id
    login
    repositories(first: 100, after: $after,
      affiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
      nodes {
        isFork
        isPrivate
        defaultBranchRef { target { ... on Commit { id } } }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

HISTORY_QUERY = """
query($tip: ID!, $author: ID!, $since: GitTimestamp!,
      $until: GitTimestamp!, $after: String) {
  node(id: $tip) {
    ... on Commit {
      history(first: 100, after: $after, author: {id: $author},
              since: $since, until: $until) {
        nodes { oid committedDate }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


class StatsError(Exception):
    """An error safe to display in public workflow logs."""


class GitHub:
    def __init__(self, token):
        self.token = token

    def __call__(self, query, variables):
        request = Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "fork-inclusive-commit-card",
            },
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=30) as response:
                    payload = json.load(response)
                break
            except HTTPError as error:
                if error.code not in (502, 503, 504) or attempt == 2:
                    raise StatsError(f"GitHub request failed (HTTP {error.code}).") from None
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise StatsError("GitHub request failed after three attempts.") from None
            time.sleep(2 ** attempt)
        # Never accept partial data or print API errors, which can contain private names.
        if payload.get("errors") or not payload.get("data"):
            raise StatsError("GitHub returned incomplete data; the card was not updated.")
        return payload["data"]


def next_cursor(connection):
    page = connection["pageInfo"]
    if not page["hasNextPage"]:
        return None
    if not page["endCursor"]:
        raise StatsError("GitHub returned an invalid pagination cursor.")
    return page["endCursor"]


def repositories(api, username, require_private):
    after = None
    result = []
    while True:
        viewer = api(REPOSITORIES_QUERY, {"after": after})["viewer"]
        if viewer["login"].casefold() != username.casefold():
            raise StatsError("The stats token must belong to the profile owner.")
        connection = viewer["repositories"]
        result.extend(connection["nodes"])
        after = next_cursor(connection)
        if after is None:
            break
    if require_private and not any(repo["isPrivate"] for repo in result):
        raise StatsError("No private repositories are visible; check the stats token's access.")
    return viewer["id"], result


def timestamp(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def commit_ids(api, repo, author, since, until):
    branch = repo["defaultBranchRef"]
    if branch is None:  # Empty repositories have no default branch.
        return set()
    tip = branch["target"]["id"]
    after = None
    result = set()
    while True:
        data = api(HISTORY_QUERY, {
            "tip": tip, "author": author, "since": timestamp(since),
            "until": timestamp(until), "after": after,
        })
        if not data.get("node") or "history" not in data["node"]:
            raise StatsError("A repository snapshot became unavailable; the card was not updated.")
        connection = data["node"]["history"]
        for commit in connection["nodes"]:
            committed_at = datetime.fromisoformat(commit["committedDate"].replace("Z", "+00:00"))
            if since <= committed_at <= until:
                result.add(commit["oid"])
        after = next_cursor(connection)
        if after is None:
            return result


def count_commits(api, username, now, require_private=True):
    author, repos = repositories(api, username, require_private)
    since = now - timedelta(days=365)
    all_commits = set()
    fork_commits = set()
    private_commits = set()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = pool.map(lambda repo: commit_ids(api, repo, author, since, now), repos)
        for repo, commits in zip(repos, results):
            all_commits.update(commits)
            if repo["isFork"]:
                fork_commits.update(commits)
            if repo["isPrivate"]:
                private_commits.update(commits)
    return {
        "total": len(all_commits), "forks": len(fork_commits),
        "private": len(private_commits), "since": since.date().isoformat(),
        "until": now.date().isoformat(),
    }


def render_card(stats):
    total = f'{stats["total"]:,}'
    forks = f'{stats["forks"]:,}'
    description = escape(
        f'{total} unique commits authored by me, including {forks} found in forks. '
        f'Last 365 days ({stats["since"]} to {stats["until"]}), by commit date, '
        'on default branches. Includes accessible public and private repositories. '
        'Shared commit hashes are counted once.'
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="495" height="195" viewBox="0 0 495 195" role="img" aria-labelledby="title desc">
  <title id="title">My commits, including forks</title>
  <desc id="desc">{description}</desc>
  <rect width="495" height="195" rx="5" fill="#0D1117"/>
  <g font-family="Segoe UI, Ubuntu, sans-serif">
    <text x="25" y="35" fill="#70a5fd" font-size="18" font-weight="600">My commits, including forks</text>
    <text x="25" y="89" fill="#38bdae" font-size="36" font-weight="700">{total}</text>
    <text x="25" y="115" fill="#38bdae" font-size="14">unique commits in the past 365 days</text>
    <text x="25" y="142" fill="#bf91f3" font-size="14">{forks} also found in fork repositories</text>
    <text x="25" y="168" fill="#a9b1d6" font-size="11">Public + private · Default branches · Shared hashes counted once</text>
    <text x="25" y="185" fill="#a9b1d6" font-size="10">Updated {stats["until"]} UTC</text>
  </g>
</svg>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--output", type=Path, default=Path("profile/commits.svg"))
    parser.add_argument("--require-private", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise StatsError("GH_TOKEN is required; use a stats token with private repository access.")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stats = count_commits(GitHub(token), args.username, now, args.require_private)
    # Only aggregate counts leave the process; no repo names, emails or commit hashes.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".svg.tmp")
    temporary.write_text(render_card(stats), encoding="utf-8")
    temporary.replace(args.output)
    print(f'Generated card: {stats["total"]} unique commits; {stats["forks"]} found in forks; '
          f'{stats["private"]} found in private repositories.')


if __name__ == "__main__":
    try:
        main()
    except StatsError as error:
        print(f"Commit card: {error}", file=sys.stderr)
        sys.exit(1)
