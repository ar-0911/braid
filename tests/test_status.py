"""`braid status` outside a braid repo still acts like git, but says why there are no agents."""
import tempfile
import unittest
from pathlib import Path

from helpers import RepoCase, braid, sh


class NotABraidRepo(unittest.TestCase):
    def test_plain_repo_explains_and_agents_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            sh("git", "init", "-q", "-b", "main", cwd=d)
            r = braid("status", cwd=d)
            self.assertIn("No commits yet", r.stdout)  # git's own output, unchanged
            self.assertIn("braid init", r.stderr)
            r = braid("agents", cwd=d, check=False)
            self.assertEqual(r.returncode, 1)
            self.assertIn("braid init", r.stderr)
            self.assertFalse((Path(d) / ".git" / "braid").exists())  # nothing was set up behind their back


class BraidRepo(RepoCase):
    def test_git_flags_pass_through_with_a_pointer(self):
        r = braid("status", "-s", cwd=self.repo)
        self.assertIn("git flag", r.stderr)
        self.assertIn("braid agents", r.stderr)

    def test_agents_shows_only_braid(self):
        out = braid("agents", cwd=self.repo).stdout
        self.assertIn("task-one", out)
        self.assertNotIn("## main", out)


if __name__ == "__main__":
    unittest.main()
