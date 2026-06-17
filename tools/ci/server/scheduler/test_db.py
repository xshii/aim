import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import db


class TestDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "ci.db")
        db.init(self.path)

    def test_enqueue_then_claim_then_finish(self):
        tid = db.enqueue(self.path, "git@host:repo.git", "main")
        self.assertEqual(db.get(self.path, tid)["state"], "queued")
        row = db.claim(self.path)
        self.assertEqual(row["id"], tid)
        self.assertEqual(db.get(self.path, tid)["state"], "running")
        db.finish(self.path, tid, "passed", 0, "/var/log/1.log")
        self.assertEqual(db.get(self.path, tid)["state"], "passed")

    def test_claim_empty_returns_none(self):
        self.assertIsNone(db.claim(self.path))

    def test_claim_fifo_and_single(self):
        a = db.enqueue(self.path, "r", "1")
        b = db.enqueue(self.path, "r", "2")
        self.assertEqual(db.claim(self.path)["id"], a)
        self.assertEqual(db.claim(self.path)["id"], b)
        self.assertIsNone(db.claim(self.path))

    def test_reset_stale_marks_running_as_error(self):
        tid = db.enqueue(self.path, "r", "1")
        db.claim(self.path)
        self.assertEqual(db.reset_stale(self.path), 1)
        self.assertEqual(db.get(self.path, tid)["state"], "error")


if __name__ == "__main__":
    unittest.main()
