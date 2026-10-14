import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import profiles_davfs as profiles


def profile(number, label="Documents"):
    return {"id": f"lib{number}", "accountId": f"acct{number}", "name": label,
            "url": f"http://127.0.0.1:{8790 + number}/", "mountPoint": f"/fixture/mount{number}",
            "stateDir": f"/fixture/state{number}", "envFile": f"/fixture/env{number}"}


class AggregationTests(unittest.TestCase):
    def test_same_paths_are_source_qualified_and_one_failure_is_partial(self):
        libraries = [profile(1), profile(2), profile(3)]
        def fetch(library, action, value):
            if library["id"] == "lib3":
                return {"ok": False, "error": "Access denied"}
            return {"ok": True, "ready": True, "results": [
                {"path": "/Report.docx", "name": "Report.docx", "isDir": False}]}
        with patch.object(profiles, "fetch", side_effect=fetch):
            response = profiles.aggregate(libraries, "search", "Report")
        self.assertTrue(response["partial"])
        self.assertEqual([entry["path"] for entry in response["results"]],
                         ["/@lib1/Report.docx", "/@lib2/Report.docx"])
        self.assertEqual(response["results"][0]["mountPoint"], "/fixture/mount1")

    def test_exact_aggregate_and_per_library_limits(self):
        libraries = [profile(number) for number in range(6)]
        def fetch(library, action, value):
            return {"ok": True, "ready": True, "truncated": True, "results": [
                {"path": f"/Report{number}", "name": f"Report{number}", "isDir": False}
                for number in range(105)]}
        with patch.object(profiles, "fetch", side_effect=fetch):
            response = profiles.aggregate(libraries, "search", "Report")
        self.assertEqual(len(response["results"]), 500)
        self.assertTrue(response["truncated"])
        self.assertLessEqual(max(sum(entry["profileId"] == library["id"] for entry in response["results"])
                                 for library in libraries), 100)
        with patch.object(profiles, "fetch") as fetcher:
            self.assertEqual(profiles.aggregate(libraries, "search", "r")["results"], [])
            fetcher.assert_not_called()

    def test_unified_roots_and_profile_specific_tree(self):
        libraries = [profile(1), profile(2)]
        root = profiles.aggregate(libraries, "tree", "/")
        self.assertEqual([entry["path"] for entry in root["children"]], ["/@lib1", "/@lib2"])
        with patch.object(profiles, "fetch", return_value={
            "ok": True, "path": "/Docs", "isDir": True,
            "children": [{"path": "/Docs/Sub", "name": "Sub", "isDir": True}],
        }) as fetcher:
            tree = profiles.aggregate(libraries, "tree", "/@lib2/Docs")
        self.assertEqual(tree["children"][0]["path"], "/@lib2/Docs/Sub")
        fetcher.assert_called_once_with(libraries[1], "tree", "/Docs")

    def test_removed_profiles_cannot_route_to_another_mount(self):
        with self.assertRaises(ValueError):
            profiles.aggregate([profile(1)], "tree", "/@lib2/Docs")

    def test_registry_rejects_duplicate_and_nonlocal_endpoints(self):
        with tempfile.TemporaryDirectory() as root:
            filename = Path(root) / "profiles.json"
            for libraries in ([profile(1), profile(1)],
                              [dict(profile(1), url="https://example.com/")],
                              [profile(1), dict(profile(2), url="http://localhost:8791/")],
                              [dict(profile(1), enabled=False), dict(profile(2), mountPoint="/fixture/mount1/child")],
                              [profile(1), dict(profile(2), mountPoint="/fixture/mount1/child")]):
                filename.write_text(json.dumps({"version": 1, "libraries": libraries}))
                with self.assertRaises(ValueError):
                    profiles.load_profiles(filename)


if __name__ == "__main__":
    unittest.main()
