import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["BRAID_HOME"] = tempfile.mkdtemp(prefix="braid-home-")  # never read the real ~/.config/braid
ENV = {**os.environ, "PYTHONPATH": str(ROOT), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "NO_COLOR": "1"}
os.environ.update({k: ENV[k] for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                                       "GIT_COMMITTER_EMAIL")})

BASE_SRC = "import os\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 2\n"


def sh(*args, cwd, check=True, env=None):
    return subprocess.run(args, cwd=cwd, env=env or ENV, capture_output=True, text=True, check=check)


def braid(*args, cwd, check=True):
    r = sh(sys.executable, "-m", "braid", *args, cwd=cwd, check=False)
    if check and r.returncode != 0:
        raise AssertionError(f"braid {' '.join(args)} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


class RepoCase(unittest.TestCase):
    """A fresh repo with braid initialised and two agents (no processes) on top."""
    agents = ("Task One", "Task Two")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "proj"
        self.repo.mkdir()
        sh("git", "init", "-q", "-b", "main", cwd=self.repo)
        (self.repo / "m.py").write_text(BASE_SRC)
        (self.repo / "other.py").write_text("x = 1\n")
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-qm", "base", cwd=self.repo)
        braid("init", cwd=self.repo)
        if self.agents:
            braid("start", "--no-launch", "--no-daemon", *self.agents, cwd=self.repo)
        self.wt1 = self.repo.parent / "proj.agents" / "task-one"
        self.wt2 = self.repo.parent / "proj.agents" / "task-two"
        from braid.store import Store
        self.store = Store(self.repo)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def edit(self, wt, old, new, path="m.py"):
        f = Path(wt) / path
        text = f.read_text()
        assert old in text, (old, text)
        f.write_text(text.replace(old, new))

    def commit(self, wt, msg="work"):
        sh("git", "commit", "-qam", msg, cwd=wt)

    def show(self, ref, path="m.py"):
        return sh("git", "show", f"{ref}:{path}", cwd=self.repo).stdout
