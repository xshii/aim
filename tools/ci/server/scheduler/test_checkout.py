import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import checkout


def _git(args, cwd):
    subprocess.check_call(["git"] + args, cwd=cwd,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class TestCheckout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.origin = os.path.join(self.tmp, "origin")
        os.makedirs(self.origin)
        _git(["init", "-q"], self.origin)
        _git(["config", "user.email", "t@t"], self.origin)
        _git(["config", "user.name", "t"], self.origin)
        with open(os.path.join(self.origin, "hello.txt"), "w") as f:
            f.write("hi")
        _git(["add", "."], self.origin)
        _git(["commit", "-q", "-m", "init"], self.origin)

    def test_checkout_default_branch(self):
        dest = os.path.join(self.tmp, "ws")
        checkout.checkout(self.origin, "HEAD", dest, git_auth="ssh", ssh_key="")
        self.assertTrue(os.path.isfile(os.path.join(dest, "hello.txt")))

    def test_checkout_overwrites_existing_dest(self):
        dest = os.path.join(self.tmp, "ws")
        os.makedirs(dest)
        with open(os.path.join(dest, "stale.txt"), "w") as f:
            f.write("old")
        checkout.checkout(self.origin, "HEAD", dest, git_auth="ssh", ssh_key="")
        self.assertFalse(os.path.exists(os.path.join(dest, "stale.txt")))


if __name__ == "__main__":
    unittest.main()
