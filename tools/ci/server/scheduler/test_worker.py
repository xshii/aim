import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import db
import worker


def _cfg(tmp, path):
    return worker.Cfg(db_path=path, workspace_dir=tmp, log_dir=tmp,
                      git_auth="ssh", ssh_key="", http_token="")


class TestWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "ci.db")
        db.init(self.path)

    def test_run_one_passed(self):
        tid = db.enqueue(self.path, "r", "main")
        worker.run_one(_cfg(self.tmp, self.path), do_checkout=lambda *a, **k: None,
                       run_pipeline=lambda ws, log: 0)
        self.assertEqual(db.get(self.path, tid)["state"], "passed")

    def test_run_one_failed_on_nonzero(self):
        tid = db.enqueue(self.path, "r", "main")
        worker.run_one(_cfg(self.tmp, self.path), do_checkout=lambda *a, **k: None,
                       run_pipeline=lambda ws, log: 1)
        self.assertEqual(db.get(self.path, tid)["state"], "failed")

    def test_run_one_error_on_checkout_raise(self):
        tid = db.enqueue(self.path, "r", "main")

        def boom(*a, **k):
            raise RuntimeError("clone failed")

        worker.run_one(_cfg(self.tmp, self.path), do_checkout=boom,
                       run_pipeline=lambda ws, log: 0)
        self.assertEqual(db.get(self.path, tid)["state"], "error")

    def test_run_one_no_task_returns_false(self):
        self.assertFalse(worker.run_one(_cfg(self.tmp, self.path),
                                        do_checkout=lambda *a, **k: None,
                                        run_pipeline=lambda ws, log: 0))


if __name__ == "__main__":
    unittest.main()
