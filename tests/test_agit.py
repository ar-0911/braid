import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agit import predict  # noqa: E402
from agit.mcp_server import Server  # noqa: E402
from agit.store import Store, paths_overlap  # noqa: E402

ENV = {**os.environ, "PYTHONPATH": str(ROOT), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def sh(*args, cwd, check=True):
    return subprocess.run(args, cwd=cwd, env=ENV, capture_output=True, text=True, check=check)


def agit(*args, cwd, check=True):
    return sh(sys.executable, "-m", "agit", *args, cwd=cwd, check=check)


BASE_SRC = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"


class AgitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "proj"
        self.repo.mkdir()
        sh("git", "init", "-q", "-b", "main", cwd=self.repo)
        (self.repo / "m.py").write_text(BASE_SRC)
        (self.repo / "other.py").write_text("x = 1\n")
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-qm", "base", cwd=self.repo)
        agit("init", cwd=self.repo)
        agit("run", "Task One", "Task Two", cwd=self.repo)
        self.wt1 = self.repo.parent / "proj.agents" / "task-one"
        self.wt2 = self.repo.parent / "proj.agents" / "task-two"

    def tearDown(self):
        self.tmp.cleanup()

    def edit(self, wt, old, new, path="m.py"):
        f = wt / path
        f.write_text(f.read_text().replace(old, new))

    def test_run_creates_worktrees_and_agents(self):
        self.assertTrue(self.wt1.is_dir() and self.wt2.is_dir())
        names = [a["name"] for a in Store(self.repo).agents()]
        self.assertEqual(names, ["task-one", "task-two"])
        cfg = json.loads((self.repo / ".git/agit/mcp/task-one.json").read_text())
        self.assertEqual(cfg["mcpServers"]["agit"]["env"]["AGIT_AGENT"], "task-one")

    def test_predicts_conflict_in_uncommitted_work(self):
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.wt2, "return 1", "return 100")
        r = agit("check", cwd=self.repo, check=False)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CONFLICT  task-one <-> task-two: m.py", r.stdout)
        # the agents' real index and files are untouched
        self.assertEqual(sh("git", "status", "--porcelain", cwd=self.wt1).stdout.strip(), "M m.py")
        self.assertIn("Predicted conflict", Store(self.repo).notes()[-1]["text"])

    def test_same_file_different_functions_is_overlap_not_conflict(self):
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.wt2, "return 2", "return 20")
        r = agit("check", cwd=self.repo)
        self.assertIn("OVERLAP   task-one <-> task-two: m.py", r.stdout)

    def test_disjoint_files_no_risk(self):
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.wt2, "x = 1", "x = 2", path="other.py")
        r = agit("check", cwd=self.repo)
        self.assertIn("no conflicts predicted", r.stdout)

    def test_conflict_with_moved_base_branch(self):
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.repo, "return 1", "return 5")
        sh("git", "commit", "-qam", "main moves", cwd=self.repo)
        r = agit("check", cwd=self.repo, check=False)
        self.assertIn("CONFLICT  task-one <-> @main: m.py", r.stdout)

    def test_hard_lease_blocks_other_agents_commit(self):
        s = Store(self.repo)
        ok, _ = s.acquire_lease("task-one", "m.py", "hard")
        self.assertTrue(ok)
        self.assertFalse(s.acquire_lease("task-two", "m.py", "soft")[0])
        self.edit(self.wt2, "return 2", "return 20")
        sh("git", "add", "m.py", cwd=self.wt2)
        r = sh("git", "commit", "-m", "x", cwd=self.wt2, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("hard-leased by task-one", r.stderr)
        # the lease holder can still commit
        self.edit(self.wt1, "return 1", "return 10")
        sh("git", "commit", "-qam", "mine", cwd=self.wt1)

    def test_paths_overlap(self):
        self.assertTrue(paths_overlap("src/auth", "src/auth/session.py"))
        self.assertTrue(paths_overlap("src/*.py", "src/a.py"))
        self.assertFalse(paths_overlap("src/auth", "src/authz.py"))

    def test_mcp_server_protocol_and_tools(self):
        proc = subprocess.run(
            [sys.executable, "-m", "agit", "mcp"], cwd=self.wt1, capture_output=True, text=True,
            env={**ENV, "AGIT_AGENT": "task-one", "AGIT_REPO": str(self.repo)},
            input="\n".join(json.dumps(m) for m in [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "declare_intent", "arguments": {"paths": ["m.py"], "description": "edit a()"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "peers", "arguments": {}}},
            ]) + "\n")
        resps = [json.loads(l) for l in proc.stdout.splitlines()]
        self.assertEqual([r["id"] for r in resps], [1, 2, 3, 4])
        self.assertEqual(resps[0]["result"]["serverInfo"]["name"], "agit")
        self.assertIn("risks", [t["name"] for t in resps[1]["result"]["tools"]])
        peers = json.loads(resps[3]["result"]["content"][0]["text"])
        self.assertEqual([p["name"] for p in peers], ["task-two"])

    def test_agents_see_each_other_through_server(self):
        one, two = Server(self.repo, "task-one"), Server(self.repo, "task-two")
        one.call("declare_intent", {"paths": ["m.py"], "description": "rewrite a()"})
        one.call("post_note", {"topic": "api", "text": "a() now returns 10"})
        peer = two.call("peers", {})[0]
        self.assertEqual(peer["intents"][0]["description"], "rewrite a()")
        self.assertEqual(two.call("read_notes", {})[-1]["text"], "a() now returns 10")
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.wt2, "return 1", "return 100")
        risks = two.call("risks", {})
        self.assertEqual(risks[0]["severity"], "conflict")


if __name__ == "__main__":
    unittest.main()
