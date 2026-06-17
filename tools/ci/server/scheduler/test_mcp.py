import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "local", "mcp"))
import db


class TestMcp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "ci.db")
        db.init(self.path)
        self.tid = db.enqueue(self.path, "r", "main")
        os.environ["CI_DB_PATH"] = self.path
        import importlib
        import ci_control_server
        importlib.reload(ci_control_server)
        self.mcp = ci_control_server

    def test_tools_list_has_task_tools(self):
        resp = self.mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertEqual(names, {"get_task_status", "list_tasks", "get_task_log"})

    def test_get_task_status(self):
        resp = self.mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                "params": {"name": "get_task_status",
                                           "arguments": {"task_id": self.tid}}})
        self.assertIn("queued", resp["result"]["content"][0]["text"])

    def test_list_tasks(self):
        resp = self.mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                "params": {"name": "list_tasks", "arguments": {}}})
        self.assertIn("main", resp["result"]["content"][0]["text"])

    def test_unknown_method_error(self):
        resp = self.mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})
        self.assertEqual(resp["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
