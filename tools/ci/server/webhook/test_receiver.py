#!/usr/bin/env python3
# implements: FR-14, FR-19
"""webhook 适配器单测（python3 标准库 unittest，mock Jenkins，无需真 Jenkins）。
覆盖：payload 解析、Jenkins buildWithParameters URL 构造、X-Devcloud-Token 校验(401/202)。
  python3 server/webhook/test_receiver.py"""
import json
import os
import sys
import threading
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import receiver  # noqa: E402


class FakeResp:
    def __init__(self, status, body=b"", location=""):
        self.status = status
        self._body = body
        self.headers = {"Location": location}

    def read(self):
        return self._body


class FakeOpener:
    """假 Jenkins：crumb GET 返回 crumb json；buildWithParameters POST 记录并返回 201。"""
    def __init__(self):
        self.build_req = None

    def open(self, req, timeout=None):
        if "/crumbIssuer/" in req.full_url:
            return FakeResp(200, json.dumps(
                {"crumbRequestField": "Jenkins-Crumb", "crumb": "abc123"}).encode())
        self.build_req = req
        return FakeResp(201, location="http://127.0.0.1:8080/queue/item/1/")


class ParseTest(unittest.TestCase):
    def test_devcloud_push_payload(self):
        receiver.GIT_AUTH = "ssh"
        body = json.dumps({
            "project": {"git_ssh_url": "git@host:g/qsort.git",
                        "git_http_url": "http://host/g/qsort.git"},
            "checkout_sha": "deadbeef",
            "ref": "refs/heads/feature/x",
        })
        repo, sha, branch = receiver._parse(body)
        self.assertEqual(repo, "git@host:g/qsort.git")
        self.assertEqual(sha, "deadbeef")
        self.assertEqual(branch, "feature/x")

    def test_http_auth_picks_http_url(self):
        receiver.GIT_AUTH = "http"
        body = json.dumps({"project": {"git_ssh_url": "git@h:g.git",
                                       "git_http_url": "http://h/g.git"}})
        repo, _, branch = receiver._parse(body)
        self.assertEqual(repo, "http://h/g.git")
        self.assertEqual(branch, "main")          # 无 ref → 默认 main
        receiver.GIT_AUTH = "ssh"

    def test_bare_payload_for_manual_curl(self):
        repo, sha, branch = receiver._parse('{"repo":"r","sha":"s","branch":"dev"}')
        self.assertEqual((repo, sha, branch), ("r", "s", "dev"))


class TriggerUrlTest(unittest.TestCase):
    def test_build_with_parameters_url(self):
        fake = FakeOpener()
        receiver.JOB = "qsort-eval"
        status, loc = receiver.trigger_build("git@h:g.git", "deadbeef", "main", opener=fake)
        self.assertEqual(status, 201)
        self.assertTrue(loc.endswith("/queue/item/1/"))
        url = fake.build_req.full_url
        self.assertIn("/job/qsort-eval/buildWithParameters?", url)
        self.assertIn("GIT_URL=git%40h%3Ag.git", url)
        self.assertIn("GIT_SHA=deadbeef", url)
        self.assertIn("BRANCH=main", url)
        # 带上了 crumb 头（同会话取得）
        self.assertEqual(fake.build_req.headers.get("Jenkins-crumb"), "abc123")


class TokenAuthTest(unittest.TestCase):
    """起真实 HTTP server（localhost 临时端口），mock 掉 trigger_build，验证 401/202。"""
    def setUp(self):
        from http.server import HTTPServer
        receiver.SECRET = "s3cret"
        self._triggered = []
        self._orig_trigger = receiver.trigger_build       # 还原，防污染其它用例
        receiver.trigger_build = lambda repo, sha, branch, opener=None: (  # noqa: E731
            self._triggered.append((repo, sha, branch)), (201, "loc"))[1]
        self.httpd = HTTPServer(("127.0.0.1", 0), receiver.Handler)
        self.port = self.httpd.server_address[1]
        self.t = threading.Thread(target=self.httpd.handle_request)  # 服务一次即可
        self.t.start()

    def tearDown(self):
        receiver.trigger_build = self._orig_trigger
        self.httpd.server_close()

    def _post(self, headers):
        body = json.dumps({"repo": "r", "sha": "s", "branch": "main"}).encode()
        req = urllib.request.Request("http://127.0.0.1:%d/" % self.port,
                                     data=body, headers=headers, method="POST")
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_bad_token_401(self):
        code = self._post({receiver.AUTH_HEADER: "wrong"})
        self.assertEqual(code, 401)
        self.assertEqual(self._triggered, [])

    def test_good_token_202_triggers(self):
        code = self._post({receiver.AUTH_HEADER: "s3cret"})
        self.assertEqual(code, 202)
        self.assertEqual(self._triggered, [("r", "s", "main")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
