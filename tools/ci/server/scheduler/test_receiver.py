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
        self.httpd.server_close()

    def _req(self, method, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read().decode("utf-8")
        c.close()
        return r.status, data

    # --- POST 触发：必须 X-Auth ---
    def test_post_valid_auth_enqueues(self):
        st, _ = self._req("POST", "/", {"X-Devcloud-Token": "s3cret"},
                          json.dumps({"repo": "git@h:r.git", "ref": "main"}))
        self.assertEqual(st, 202)
        self.assertEqual(len(db.list_tasks(self.path)), 1)

    def test_post_bad_auth_401_no_enqueue(self):
        st, _ = self._req("POST", "/", {"X-Devcloud-Token": "wrong"},
                          json.dumps({"repo": "r", "ref": "main"}))
        self.assertEqual(st, 401)
        self.assertEqual(len(db.list_tasks(self.path)), 0)

    def test_post_no_auth_401(self):
        st, _ = self._req("POST", "/", {}, json.dumps({"repo": "r", "ref": "main"}))
        self.assertEqual(st, 401)

    def test_post_no_repo_ignored_200(self):
        # 非 push 事件 / 无 repo：确认收到但忽略（200，不入队、不触发重试）。
        st, _ = self._req("POST", "/", {"X-Devcloud-Token": "s3cret"}, json.dumps({"ref": "main"}))
        self.assertEqual(st, 200)
        self.assertEqual(len(db.list_tasks(self.path)), 0)

    def test_idempotent_dedup(self):
        p = json.dumps({"project": {"git_ssh_url": "git@h:r.git"}, "checkout_sha": "deadbeef"})
        h = {"X-Devcloud-Token": "s3cret"}
        st1, _ = self._req("POST", "/", h, p)
        st2, b2 = self._req("POST", "/", h, p)
        self.assertEqual(st1, 202)
        self.assertEqual(st2, 200)               # 第二次幂等命中
        self.assertIn("duplicate", b2)
        self.assertEqual(len(db.list_tasks(self.path)), 1)   # 只 1 个任务

    # --- GET 网页/日志：内网只读，不强制认证 ---
    def test_get_list_no_auth_ok(self):
        db.enqueue(self.path, "r", "main")
        st, body = self._req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn("CI 评测任务", body)

    def test_get_detail_shows_state(self):
        tid = db.enqueue(self.path, "r", "main")
        st, body = self._req("GET", "/tasks/%d" % tid)
        self.assertEqual(st, 200)
        self.assertIn("queued", body)

    def test_get_unknown_task_404(self):
        st, _ = self._req("GET", "/tasks/999")
        self.assertEqual(st, 404)

    def test_post_devcloud_push_payload(self):
        payload = {
            "object_kind": "push",
            "checkout_sha": "0123456789012345678901234567890123456789",
            "ref": "refs/heads/master",
            "project": {"git_ssh_url": "git@h:ns/repo.git",
                        "git_http_url": "https://h/ns/repo.git"},
        }
        st, _ = self._req("POST", "/", {"X-Devcloud-Token": "s3cret"}, json.dumps(payload))
        self.assertEqual(st, 202)
        t = db.list_tasks(self.path)[0]
        self.assertEqual(t["repo"], "git@h:ns/repo.git")   # git_auth 默认 ssh
        self.assertEqual(t["ref"], "0123456789012345678901234567890123456789")


if __name__ == "__main__":
    unittest.main()
