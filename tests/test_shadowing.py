"""A repo file named like a standard module (email.py, json.py) must not break braid running inside that repo."""
import tempfile
import unittest
from pathlib import Path

from helpers import braid, sh

SHADOW = 'raise SystemExit("the repo\'s own module was imported instead of Python\'s")\n'


class RepoWithStdlibNames(unittest.TestCase):
    def test_hooks_merge_driver_and_commands_still_work(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "proj"
            repo.mkdir()
            sh("git", "init", "-q", "-b", "main", cwd=repo)
            for name in ("email.py", "json.py", "subprocess.py"):
                (repo / name).write_text(SHADOW)
            (repo / "m.py").write_text("def a():\n    return 1\n")
            sh("git", "add", ".", cwd=repo)
            sh("git", "commit", "-qm", "base", cwd=repo)
            braid("init", cwd=repo)
            braid("start", "--no-launch", "--no-daemon", "Task One", "Task Two", cwd=repo)
            for wt, fn in (("task-one", "b"), ("task-two", "c")):
                path = repo.parent / "proj.agents" / wt
                with open(path / "m.py", "a") as f:
                    f.write(f"\n\ndef {fn}():\n    return 2\n")
                sh("git", "commit", "-qam", fn, cwd=path)  # runs braid's pre-commit hook inside the repo
            r = braid("check", cwd=repo)  # dry-run merges go through braid's merge driver
            self.assertNotIn("instead of Python", r.stdout + r.stderr)
            self.assertIn("task-one", braid("agents", cwd=repo).stdout)


if __name__ == "__main__":
    unittest.main()
