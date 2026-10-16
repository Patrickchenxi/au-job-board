"""Synthetic loopback contract for update endpoints; never launches a pipeline."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jobs import panel


class FakeUpdates:
    def __init__(self):
        self.calls = 0
        self.next = {"state": "running", "accepted": True}

    def preview(self):
        return {"ok": True, "queries": ["fictional engineer"], "sources": []}

    def status(self):
        return {"state": "idle", "error": None}

    def start(self):
        self.calls += 1
        return self.next


class UpdateHTTPTests(unittest.TestCase):
    def setUp(self):
        self.manager = FakeUpdates()
        handler = type("SyntheticHandler", (panel.Handler,), {"config": {}})
        self.server = panel.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server.update_manager = self.manager
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = "127.0.0.1:%s" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path, method="GET", body=None, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            client.request(method, path, body=body, headers=headers or {})
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def post(self, body="{}", headers=None):
        return self.request("/api/update", "POST", body,
                            {"Content-Type": "application/json", **(headers or {})})

    def test_status_and_preview_never_open_database(self):
        with patch.object(panel.database, "connect", side_effect=AssertionError("DB opened")):
            code, state = self.request("/api/update-state")
            self.assertEqual((code, state["state"]), (200, "idle"))
            code, preview = self.request("/api/update-config")
            self.assertEqual(preview["queries"], ["fictional engineer"])
            self.assertEqual(code, 200)
        self.assertEqual(self.manager.calls, 0)

    def test_start_and_conflicting_attempt(self):
        code, state = self.post(headers={"Origin": "http://" + self.host})
        self.assertEqual((code, state["accepted"]), (202, True))
        self.manager.next = {"state": "running", "accepted": False}
        self.assertEqual(self.post()[0], 409)
        self.manager.next = {"state": "busy", "accepted": False}
        self.assertEqual(self.post()[0], 409)
        self.manager.next = {"state": "error", "error": "config_invalid", "accepted": False}
        self.assertEqual(self.post()[0], 400)

    def test_foreign_origin_and_rebound_host_cannot_launch(self):
        for headers in ({"Origin": "https://example.invalid"}, {"Origin": "null"},
                        {"Host": "example.invalid:%s" % self.server.server_port,
                         "Origin": "http://example.invalid:%s" % self.server.server_port},
                        {"Host": "127.0.0.1:bad"}, {"Origin": "http://" + self.host + "/bad"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.post(headers=headers)[0], 403)
        self.assertEqual(self.manager.calls, 0)

    def test_browser_form_or_invalid_body_cannot_launch(self):
        for body in ("[]", "null", '{"command":"fetch"}', "not json", " " * 4097):
            with self.subTest(body=body[:30]):
                self.assertEqual(self.post(body)[0], 400)
        self.assertEqual(self.post(headers={"Content-Type": "text/plain"})[0], 400)
        self.assertEqual(self.manager.calls, 0)

    def test_demo_has_no_runner_and_no_fallback(self):
        self.server.RequestHandlerClass.config = {"demo": {"id": "synthetic"}}
        del self.server.update_manager
        with patch.object(panel.database, "connect", side_effect=AssertionError("DB opened")):
            code, preview = self.request("/api/update-config")
            self.assertEqual((code, preview["error"]), (200, "demo_disabled"))
            self.assertEqual(self.request("/api/update-state")[1]["state"], "disabled")
            self.assertEqual(self.post()[0], 503)
        self.assertEqual(self.manager.calls, 0)


if __name__ == "__main__":
    unittest.main()
