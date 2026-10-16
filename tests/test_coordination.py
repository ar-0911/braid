import json
import subprocess
import sys
import unittest

from helpers import ENV, RepoCase, braid, sh
from braid.mcp_server import Server
from braid.store import paths_overlap


class Init(RepoCase):
    agents = ()

    def test_git_merge_uses_code_aware_driver(self):
        sh("git", "checkout", "-qb", "x", cwd=self.repo)
        self.edit(self.repo, "return 1", "return 10")
        self.commit(self.repo)
        sh("git", "checkout", "-q", "main", cwd=self.repo)
        self.edit(self.repo, "\n\ndef b():\n    return 2\n", "\n\ndef b():\n    return 2\n\n\ndef c():\n    return 3\n")
        self.commit(self.repo)
        # plain git would conflict here only if lines touched; force a same-region case: append at end in both
        sh("git", "checkout", "-qb", "y", "main~1", cwd=self.repo)
        self.edit(self.repo, "\n\ndef b():\n    return 2\n", "\n\ndef b():\n    return 2\n\n\ndef d():\n    return 4\n")
        self.commit(self.repo)
        r = sh("git", "merge", "-q", "--no-edit", "main", cwd=self.repo, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.repo / "m.py").read_text()
        self.assertIn("def c():", text)
        self.assertIn("def d():", text)

    def test_git_passthrough(self):
        r = braid("log", "--oneline", cwd=self.repo)
        self.assertIn("base", r.stdout)

    def test_init_creates_repo_in_plain_folder(self):
        d = self.repo.parent / "fresh"
        d.mkdir()
        braid("init", cwd=d)
        self.assertEqual(sh("git", "log", "--format=%s", cwd=d).stdout.strip(), "Initial commit")

    def test_doctor_runs(self):
        r = braid("doctor", cwd=self.repo)
        self.assertIn("merge driver configured", r.stdout)


class Prediction(RepoCase):
    def test_conflict_in_uncommitted_work(self):
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.wt2, "return 1", "return 100")
        r = braid("check", cwd=self.repo, check=False)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CONFLICT  task-one <-> task-two: m.py", r.stdout)
        self.assertEqual(sh("git", "status", "--porcelain", cwd=self.wt1).stdout.strip(), "M m.py")
        notes = self.store.notes(for_agent="task-one")
        self.assertIn("Predicted conflict with task-two", notes[-1]["text"])

    def test_both_append_same_file_is_only_overlap(self):
        self.edit(self.wt1, "return 2\n", "return 2\n\n\ndef c():\n    return 3\n")
        self.edit(self.wt2, "return 2\n", "return 2\n\n\ndef d():\n    return 4\n")
        r = braid("check", cwd=self.repo)
        self.assertIn("OVERLAP   task-one <-> task-two: m.py", r.stdout)

    def test_disjoint_files(self):
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.wt2, "x = 1", "x = 2", path="other.py")
        self.assertIn("no conflicts predicted", braid("check", cwd=self.repo).stdout)

    def test_conflict_with_moved_base(self):
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.repo, "return 1", "return 5")
        self.commit(self.repo)
        r = braid("check", cwd=self.repo, check=False)
        self.assertIn("CONFLICT  task-one <-> @main: m.py", r.stdout)


class Leases(RepoCase):
    def test_hard_lease_blocks_other_agents_commit(self):
        ok, _ = self.store.acquire_lease("task-one", "m.py", "hard")
        self.assertTrue(ok)
        self.assertFalse(self.store.acquire_lease("task-two", "m.py")[0])
        self.edit(self.wt2, "return 2", "return 20")
        r = sh("git", "commit", "-qam", "x", cwd=self.wt2, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("owned by task-one", r.stderr)
        self.edit(self.wt1, "return 1", "return 10")
        self.commit(self.wt1)  # the owner can commit

    def test_paths_overlap(self):
        self.assertTrue(paths_overlap("src/auth", "src/auth/session.py"))
        self.assertTrue(paths_overlap("src/*.py", "src/a.py"))
        self.assertFalse(paths_overlap("src/auth", "src/authz.py"))


class Mcp(RepoCase):
    def test_protocol_over_stdio(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "declare_intent", "arguments": {"paths": ["m.py"], "description": "edit a()"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "peers", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
        ]
        proc = subprocess.run([sys.executable, "-m", "braid", "mcp"], cwd=self.wt1, capture_output=True, text=True,
                              env={**ENV, "BRAID_AGENT": "task-one", "BRAID_REPO": str(self.repo)},
                              input="\n".join(json.dumps(m) for m in msgs) + "\n")
        resps = [json.loads(l) for l in proc.stdout.splitlines()]
        self.assertEqual([r["id"] for r in resps], [1, 2, 3, 4, 5])
        self.assertEqual(resps[0]["result"]["serverInfo"]["name"], "braid")
        names = {t["name"] for t in resps[1]["result"]["tools"]}
        self.assertTrue({"risks", "review", "vote", "sync", "ready_to_land"} <= names)
        self.assertEqual([p["name"] for p in json.loads(resps[3]["result"]["content"][0]["text"])], ["task-two"])
        self.assertTrue(resps[4]["result"]["isError"])

    def test_agents_cooperate_through_tools(self):
        one, two = Server(self.repo, "task-one"), Server(self.repo, "task-two")
        one.call("declare_intent", {"paths": ["m.py"], "description": "rewrite a()"})
        one.call("post_note", {"topic": "api", "text": "a() now returns 10"})
        one.call("post_note", {"topic": "dm", "text": "only for two", "to": "task-two"})
        peer = two.call("peers", {})[0]
        self.assertEqual(peer["intents"][0]["description"], "rewrite a()")
        self.assertEqual([n["text"] for n in two.call("read_notes", {})][-2:], ["a() now returns 10", "only for two"])
        self.edit(self.wt1, "return 1", "return 10")
        self.edit(self.wt2, "return 1", "return 100")
        self.assertEqual(two.call("risks", {})[0]["severity"], "conflict")

    def test_ready_and_review_flow(self):
        one, two = Server(self.repo, "task-one"), Server(self.repo, "task-two")
        self.edit(self.wt1, "return 1", "return 10")
        self.assertFalse(one.call("ready_to_land", {"summary": "s"})["ok"])  # uncommitted
        self.commit(self.wt1)
        self.assertTrue(one.call("ready_to_land", {"summary": "a returns 10"})["ok"])
        pending = two.call("pending_reviews", {})
        self.assertEqual(pending[0]["agent"], "task-one")
        self.assertIn("return 10", two.call("show_diff", {"agent": "task-one"}))
        with self.assertRaises(ValueError):
            one.call("review", {"agent": "task-one", "verdict": "approve", "comment": "me"})
        two.call("review", {"agent": "task-one", "verdict": "changes", "comment": "add a test"})
        self.assertEqual(self.store.agent("task-one")["status"], "active")
        self.assertEqual(two.call("pending_reviews", {}), "nothing waiting for review")


if __name__ == "__main__":
    unittest.main()
