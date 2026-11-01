from datetime import datetime, timedelta, timezone
import io
import json
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from generate_commit_card import (
    GitHub, HISTORY_QUERY, REPOSITORIES_QUERY, StatsError, count_commits, render_card,
)


NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


def connection(nodes, cursor=None):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}}


def repository(tip, fork=False, private=False):
    return {
        "isFork": fork, "isPrivate": private,
        "defaultBranchRef": {"target": {"id": tip}} if tip else None,
    }


def commit(oid, when=NOW):
    return {"oid": oid, "committedDate": when.isoformat()}


class CommitCardTests(unittest.TestCase):
    def test_pagination_forks_private_repositories_and_shared_hashes(self):
        calls = []
        repo_pages = {
            None: connection([repository("own"), repository(None)], "repos-page-2"),
            "repos-page-2": connection([repository("fork", fork=True), repository("secret", private=True)]),
        }
        histories = {
            ("own", None): connection([commit("shared")], "commits-page-2"),
            ("own", "commits-page-2"): connection([commit("own-only")]),
            ("fork", None): connection([commit("shared"), commit("fork-only")]),
            ("secret", None): connection([commit("private-only"), commit("shared")]),
        }

        def api(query, variables):
            calls.append((query, variables))
            if query == REPOSITORIES_QUERY:
                return {"viewer": {"id": "author-id", "login": "losogudok",
                                   "repositories": repo_pages[variables["after"]]}}
            self.assertEqual(query, HISTORY_QUERY)
            self.assertEqual(variables["author"], "author-id")
            self.assertEqual(variables["since"], "2025-11-02T00:00:00Z")
            self.assertEqual(variables["until"], "2026-11-02T00:00:00Z")
            page = histories[(variables["tip"], variables["after"])]
            return {"node": {"history": page}}

        stats = count_commits(api, "losogudok", NOW)
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["forks"], 2)
        self.assertEqual(stats["private"], 2)
        self.assertEqual(len(calls), 6)  # Includes both pagination paths; skips the empty repo.

    def test_exact_window_excludes_old_and_future_commits(self):
        def api(query, variables):
            if query == REPOSITORIES_QUERY:
                return {"viewer": {"id": "author-id", "login": "losogudok",
                                   "repositories": connection([repository("tip", private=True)])}}
            return {"node": {"history": connection([
                commit("start", NOW - timedelta(days=365)), commit("end"),
                commit("old", NOW - timedelta(days=365, seconds=1)),
                commit("future", NOW + timedelta(seconds=1)),
            ])}}

        self.assertEqual(count_commits(api, "losogudok", NOW)["total"], 2)

    def test_wrong_owner_or_missing_private_access_fails(self):
        for login, repos, message in [
            ("someone-else", [repository("tip", private=True)], "profile owner"),
            ("losogudok", [repository("tip")], "No private repositories"),
        ]:
            with self.subTest(login=login, repos=repos):
                def api(query, variables):
                    return {"viewer": {"id": "id", "login": login, "repositories": connection(repos)}}
                with self.assertRaisesRegex(StatsError, message):
                    count_commits(api, "losogudok", NOW)

    def test_api_partial_errors_fail_without_disclosing_private_data(self):
        payload = {"data": {"viewer": {}}, "errors": [{"message": "private-repo-name"}]}
        with patch("generate_commit_card.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaises(StatsError) as raised:
                GitHub("secret-token")("query", {})
        self.assertNotIn("private-repo-name", str(raised.exception))
        self.assertNotIn("secret-token", str(raised.exception))

    def test_missing_history_fails_instead_of_publishing_an_undercount(self):
        def api(query, variables):
            if query == REPOSITORIES_QUERY:
                return {"viewer": {"id": "id", "login": "losogudok",
                                   "repositories": connection([repository("gone", private=True)])}}
            return {"node": None}

        with self.assertRaisesRegex(StatsError, "snapshot became unavailable"):
            count_commits(api, "losogudok", NOW)

    def test_card_has_accessible_scope_and_no_repository_details(self):
        svg = render_card({"total": 1234, "forks": 456, "private": 100,
                           "since": "2025-11-02", "until": "2026-11-02"})
        root = ET.fromstring(svg)
        text = " ".join(root.itertext())
        self.assertIn("1,234", text)
        self.assertIn("456", text)
        self.assertIn("Shared commit hashes are counted once", text)
        self.assertIn("on default branches", text)
        self.assertEqual(root.attrib["aria-labelledby"], "title desc")


if __name__ == "__main__":
    unittest.main()
