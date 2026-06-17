import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "webhook"))
import db


class TestReceiver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "ci.db")
        db.init(self.path)
        os.environ["WEBHOOK_SECRET"] = "s3cret"
        os.environ["CI_DB_PATH"] = self.path
        import importlib
        import receiver
        importlib.reload(receiver)
        self.httpd = receiver.build_server("127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()

    def _req(self, method, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        return c.getresponse()

    def test_valid_auth_enqueues(self):
        r = self._req("POST", "/", {"X-Auth-Token": "s3cret"},
                      json.dumps({"repo": "git@h:r.git", "ref": "main"}))
        self.assertEqual(r.status, 202)
        self.assertEqual(len(db.list_tasks(self.path)), 1)

    def test_bad_auth_401_no_enqueue(self):
        r = self._req("POST", "/", {"X-Auth-Token": "wrong"},
                      json.dumps({"repo": "r", "ref": "main"}))
        self.assertEqual(r.status, 401)
        self.assertEqual(len(db.list_tasks(self.path)), 0)

    def test_missing_repo_400(self):
        r = self._req("POST", "/", {"X-Auth-Token": "s3cret"}, json.dumps({"ref": "main"}))
        self.assertEqual(r.status, 400)

    def test_get_status_after_enqueue(self):
        tid = db.enqueue(self.path, "r", "main")
        r = self._req("GET", "/tasks/%d" % tid, {"X-Auth-Token": "s3cret"})
        self.assertEqual(r.status, 200)
        self.assertIn("queued", r.read().decode("utf-8"))

    def test_get_unauth_401(self):
        r = self._req("GET", "/tasks/1", {})
        self.assertEqual(r.status, 401)

    def test_get_unknown_task_404(self):
        r = self._req("GET", "/tasks/999", {"X-Auth-Token": "s3cret"})
        self.assertEqual(r.status, 404)


if __name__ == "__main__":
    unittest.main()
