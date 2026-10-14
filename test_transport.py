import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from profiles_davfs import aggregate, fetch
from tree_davfs import request_json


class LocalTransportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization")))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/_status")
                    self.end_headers()
                    return
                if self.path == "/error":
                    self.send_response(502)
                    self.end_headers()
                    self.wfile.write(b"Conditional access requires sign-in; private-token")
                    return
                if self.path == "/large":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"x" * (2 * 1024 * 1024 + 1))
                    return
                if self.path.startswith("/_search?"):
                    data = {"ok": True, "ready": True, "results": [{"path": "/Report.pdf", "name": "Report.pdf"}]}
                elif self.path.startswith("/_tree?"):
                    data = {"ok": True, "path": "/Docs", "children": [{"path": "/Docs/Sub", "name": "Sub", "isDir": True}]}
                elif self.path.startswith("/_libraries"):
                    data = {"ok": True, "libraries": [{"id": "b!fixture", "name": "Documents"}]}
                elif self.path == "/_status":
                    data = {"ok": True, "present": True, "crawlComplete": True, "totalDirs": 1, "totalFiles": 1}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_actual_helper_routes_each_action_without_evaluating_unrelated_discovery_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "env"
            env.write_text('ONEDRIVE_BASIC_AUTH_SECRET="fixture-secret"\n')
            profile = {"id": "work", "name": "Work", "url": self.url,
                       "envFile": str(env), "mountPoint": "/fixture/work"}
            status = aggregate([profile], "status", "/")
            self.assertEqual(status["totalFiles"], 1)
            search = aggregate([profile], "search", "Report")
            self.assertEqual(search["results"][0]["path"], "/@work/Report.pdf")
            tree = aggregate([profile], "tree", "/@work/Docs")
            self.assertEqual(tree["children"][0]["path"], "/@work/Docs/Sub")
            self.assertEqual(fetch(profile, "libraries", "site:fixture-site")["libraries"][0]["id"], "b!fixture")
            expected = "Basic " + base64.b64encode(b"daemon:fixture-secret").decode()
            self.assertTrue(all(auth == expected for _, auth in self.requests))

    def test_redirects_cannot_forward_local_credentials(self):
        result = request_json(self.url + "redirect", "fixture-secret")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 302)
        self.assertEqual(len(self.requests), 1)

    def test_loopback_authentication_bypasses_environment_http_proxies(self):
        with patch.dict("os.environ", {"http_proxy": self.url, "HTTP_PROXY": self.url,
                                     "no_proxy": "", "NO_PROXY": ""}):
            self.assertTrue(request_json(self.url + "_status", "fixture-secret")["ok"])
        self.assertEqual(self.requests[0][0], "/_status")

    def test_errors_are_classified_without_private_payloads(self):
        result = request_json(self.url + "error", "fixture-secret")
        self.assertIn("Conditional access", result["error"])
        self.assertNotIn("private", json.dumps(result))
        self.assertFalse(request_json(self.url + "large", "fixture-secret")["ok"])
        self.assertFalse(request_json("https://example.invalid/", "fixture-secret")["ok"])


if __name__ == "__main__":
    unittest.main()
