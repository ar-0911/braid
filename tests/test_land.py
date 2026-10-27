import os
import shlex
import sys
import time
import unittest
from pathlib import Path

from helpers import BASE_SRC, ENV, RepoCase, braid, sh
from braid import land
from braid.mcp_server import Server

FAKES = Path(__file__).resolve().parent / "fakes"


def resolver(mode="both"):
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKES / 'resolver.py'))} {mode}"


class Landing(RepoCase):
    def setUp(self):
        super().setUp()
        self.store.set_cfg("review.required", "no")
        self.one, self.two = Server(self.repo, "task-one"), Server(self.repo, "task-two")

    def ready(self, srv, wt, old, new, path="m.py"):
        self.edit(wt, old, new, path)
        self.commit(wt, f"{srv.agent}: {new.strip()[:20]}")
        self.assertTrue(srv.call("ready_to_land", {"summary": "done"})["ok"])

    def test_lands_onto_checked_out_main(self):
        self.ready(self.one, self.wt1, "return 1", "return 10")
        r = braid("land", cwd=self.repo)
        self.assertIn("landed  task-one", r.stdout)
        self.assertIn("return 10", (self.repo / "m.py").read_text())  # main worktree updated, not just the ref
        self.assertTrue(sh("git", "status", "--porcelain", cwd=self.repo).stdout == "")
        self.assertEqual(self.store.agent("task-one")["status"], "landed")
        msg = sh("git", "log", "-1", "--format=%B", "main", cwd=self.repo).stdout
        self.assertIn("Braid-Agent: task-one", msg)

    def test_two_agents_same_file_different_functions_land_cleanly(self):
        self.ready(self.one, self.wt1, "return 2\n", "return 2\n\n\ndef c():\n    return 3\n")
        self.ready(self.two, self.wt2, "return 2\n", "return 2\n\n\ndef d():\n    return 4\n")
        r = braid("land", cwd=self.repo)
        self.assertEqual(r.stdout.count("landed  "), 2, r.stdout)
        text = self.show("main")
        self.assertIn("def c()", text)
        self.assertIn("def d()", text)

    def test_real_conflict_resolved_by_resolver_with_consensus(self):
        self.store.set_cfg("resolve.command", resolver("both"))
        self.ready(self.one, self.wt1, "return 1", "return 10")
        self.ready(self.two, self.wt2, "return 1", "return 100")
        r = braid("land", cwd=self.repo)
        self.assertEqual(r.stdout.count("landed  "), 2, r.stdout + r.stderr)
        d = self.store.decisions()[0]
        self.assertEqual((d["status"], d["agent"], d["parties"]), ("accepted", "task-two", ["task-one"]))
        self.assertIn("kept both sides", d["detail"])
        self.assertIn("return 10\n    return 100", self.show("main"))
        # both sides were told
        self.assertTrue(any("Decision #" in n["text"] for n in self.store.notes(for_agent="task-one")))

    def test_resolver_that_cannot_resolve_escalates_and_blocks(self):
        self.store.set_cfg("resolve.command", resolver("fail"))
        self.ready(self.one, self.wt1, "return 1", "return 10")
        self.ready(self.two, self.wt2, "return 1", "return 100")
        r = braid("land", cwd=self.repo, check=False)
        self.assertIn("landed  task-one", r.stdout)
        self.assertIn("blocked  task-two", r.stdout)
        self.assertEqual(self.store.agent("task-two")["status"], "blocked")
        self.assertEqual(self.store.decisions()[0]["status"], "escalated")
        # the blocked agent fixes it itself with sync, as the note tells it to
        ok, msg, files = land.sync(self.store, "task-two")
        self.assertEqual(files, ["m.py"])
        (self.wt2 / "m.py").write_text(self.show("main").replace("return 10", "return 110"))
        sh("git", "add", "m.py", cwd=self.wt2)
        sh("git", "commit", "-qm", "resolve", cwd=self.wt2)
        self.two.call("read_notes", {})  # it read why it was blocked
        self.assertTrue(self.two.call("ready_to_land", {"summary": "resolved"})["ok"])
        r = braid("land", cwd=self.repo)
        self.assertIn("landed  task-two", r.stdout)
        self.assertIn("return 110", self.show("main"))

    def test_tests_gate_rejects_broken_resolution(self):
        self.store.set_cfg("resolve.command", resolver("break"))
        self.store.set_cfg("test.command", f"{shlex.quote(sys.executable)} m.py")
        self.ready(self.one, self.wt1, "return 1", "return 10")
        self.ready(self.two, self.wt2, "return 1", "return 100")
        r = braid("land", cwd=self.repo, check=False)
        self.assertIn("landed  task-one", r.stdout)
        self.assertIn("tests fail", r.stdout)
        self.assertEqual(self.store.decisions()[0]["status"], "rejected")
        self.assertNotIn("broken", self.show("main"))

    def test_objection_rejects_resolution(self):
        self.store.set_cfg("resolve.command", resolver("both"))
        self.store.set_cfg("consensus.window", "2")
        self.ready(self.one, self.wt1, "return 1", "return 10")
        land.land(self.store, "task-one")
        self.ready(self.two, self.wt2, "return 1", "return 100")
        import threading
        def object_soon():
            one = Server(self.repo, "task-one")  # sqlite connections are per thread
            for _ in range(50):
                ds = one.store.decisions(status="proposed")
                if ds:
                    one.call("vote", {"decision_id": ds[0]["id"], "vote": "object", "reason": "drops my fix"})
                    return
                time.sleep(0.05)
        t = threading.Thread(target=object_soon)
        t.start()
        r = land.land(self.store, "task-two")
        t.join()
        self.assertFalse(r.ok)
        self.assertIn("task-one objected: drops my fix", r.message)
        self.assertNotIn("return 100", self.show("main"))

    def test_uncommitted_work_waits(self):
        self.ready(self.one, self.wt1, "return 1", "return 10")
        self.edit(self.wt1, "x = 1", "x = 2", path="other.py")
        r = land.land(self.store, "task-one")
        self.assertTrue(r.waiting)
        self.assertIn("uncommitted", r.message)

    def test_sync_brings_landed_work_into_other_agent(self):
        self.ready(self.one, self.wt1, "x = 1", "x = 2", path="other.py")
        land.land(self.store, "task-one")
        self.edit(self.wt2, "return 1", "return 7")  # uncommitted work survives sync
        ok, _, _ = self.two.call("sync", {}).values()
        self.assertTrue(ok)
        self.assertEqual((self.wt2 / "other.py").read_text(), "x = 2\n")
        self.assertIn("return 7", (self.wt2 / "m.py").read_text())

    def test_push_to_remote(self):
        remote = self.repo.parent / "remote.git"
        sh("git", "init", "-q", "--bare", str(remote), cwd=self.repo)
        sh("git", "remote", "add", "origin", str(remote), cwd=self.repo)
        self.ready(self.one, self.wt1, "return 1", "return 10")
        r = braid("ship", cwd=self.repo)
        self.assertIn("pushed", r.stdout)
        self.assertEqual(sh("git", "rev-parse", "main", cwd=remote).stdout, sh("git", "rev-parse", "main",
                                                                               cwd=self.repo).stdout)


class SemanticLanding(RepoCase):
    """A rename on one side and a new call to the old name on the other merge cleanly as text. With no tests
    to catch it, only the semantic check in the landing queue stops the second one from landing broken code."""
    agents = ()

    def setUp(self):
        super().setUp()
        (self.repo / "m.py").write_text(BASE_SRC + "\n\ndef load_items():\n    return []\n")
        sh("git", "commit", "-qam", "add load_items", cwd=self.repo)
        braid("start", "--no-launch", "--no-daemon", "Task One", "Task Two", cwd=self.repo)
        self.store.set_cfg("review.required", "no")
        self.renamer, self.caller = Server(self.repo, "task-one"), Server(self.repo, "task-two")

    def make_ready(self, first):
        # both are ready before either lands, so ready_to_land's own check can't see the clash
        self.edit(self.wt2, "x = 1\n", "from m import load_items\n\nx = load_items()\n", "other.py")
        self.commit(self.wt2, "use load_items")
        self.assertTrue(self.caller.call("ready_to_land", {"summary": "new caller"})["ok"])
        self.edit(self.wt1, "def load_items():", "def fetch_items():")
        self.commit(self.wt1, "rename load_items")
        self.assertTrue(self.renamer.call("ready_to_land", {"summary": "rename"})["ok"])
        self.store.update_agent(first, ready_at=0)

    def test_rename_landed_first_blocks_new_caller(self):
        self.make_ready("task-one")
        r = braid("land", cwd=self.repo, check=False)
        self.assertIn("landed  task-one", r.stdout)
        self.assertIn("blocked  task-two", r.stdout)
        self.assertIn("other.py uses load_items()", r.stdout)
        self.assertNotIn("load_items", self.show("main", "other.py"))
        self.assertEqual(self.store.agent("task-two")["status"], "blocked")
        self.assertTrue(any("other.py uses load_items()" in n["text"] for n in self.store.notes(for_agent="task-two")))

    def test_new_caller_landed_first_blocks_rename(self):
        self.make_ready("task-two")
        r = braid("land", cwd=self.repo, check=False)
        self.assertIn("landed  task-two", r.stdout)
        self.assertIn("blocked  task-one", r.stdout)
        self.assertIn("other.py uses load_items()", r.stdout)
        self.assertIn("def load_items():", self.show("main"))

    def test_fixed_caller_lands(self):
        self.make_ready("task-one")
        braid("land", cwd=self.repo, check=False)
        land.sync(self.store, "task-two")
        self.edit(self.wt2, "load_items", "fetch_items", "other.py")
        self.commit(self.wt2, "follow the rename")
        self.caller.call("read_notes", {})
        self.assertTrue(self.caller.call("ready_to_land", {"summary": "fixed"})["ok"])
        r = braid("land", cwd=self.repo)
        self.assertIn("landed  task-two", r.stdout)

    def test_can_be_turned_off(self):
        self.store.set_cfg("land.semantic", "false")
        self.make_ready("task-one")
        r = braid("land", cwd=self.repo)
        self.assertEqual(r.stdout.count("landed  "), 2, r.stdout)


class ReviewGate(RepoCase):
    def test_auto_mode_waits_for_live_peer_then_lands_after_approval(self):
        store = self.store
        one, two = Server(self.repo, "task-one"), Server(self.repo, "task-two")
        self.edit(self.wt1, "return 1", "return 10")
        self.commit(self.wt1)
        one.call("ready_to_land", {"summary": "ten"})
        r = land.land(store, "task-one")
        self.assertTrue(r.waiting)
        self.assertIn("waiting for a review from a peer (task-two)", r.message)
        two.call("review", {"agent": "task-one", "verdict": "approve", "comment": "lgtm"})
        r = land.land(store, "task-one")
        self.assertTrue(r.ok, r.message)
        self.assertIn("Reviewed-by: task-two", sh("git", "log", "-1", "--format=%B", "main", cwd=self.repo).stdout)

    def test_new_commits_need_new_review(self):
        self.store.set_cfg("review.required", "yes")
        one, two = Server(self.repo, "task-one"), Server(self.repo, "task-two")
        self.edit(self.wt1, "return 1", "return 10")
        self.commit(self.wt1)
        two.call("review", {"agent": "task-one", "verdict": "approve", "comment": "ok"})
        self.edit(self.wt1, "return 10", "return 11")
        self.commit(self.wt1)
        one.call("ready_to_land", {"summary": "eleven"})
        self.assertFalse(land.land(self.store, "task-one").ok)

    def test_auto_reviewer_command(self):
        self.store.set_cfg("review.command", "echo 'fine'; echo 'VERDICT: approve'")
        self.edit(self.wt1, "return 1", "return 10")
        self.commit(self.wt1)
        Server(self.repo, "task-one").call("ready_to_land", {"summary": "x"})
        self.assertTrue(land.land(self.store, "task-one").ok)
        self.assertEqual(self.store.reviews("task-one")[0]["reviewer"], "auto-reviewer")


class AutoResume(RepoCase):
    def test_daemon_relaunches_agent_that_stopped_with_feedback(self):
        from braid import cli
        marker = self.repo.parent / "resumed.txt"
        self.store.set_cfg("agent.command", f"echo {{name}} >> {shlex.quote(str(marker))}")
        dead = __import__("subprocess").Popen(["true"])
        dead.wait()
        self.store.update_agent("task-one", pid=dead.pid)
        self.edit(self.wt1, "return 1", "return 10")
        self.commit(self.wt1)
        Server(self.repo, "task-two").call("review", {"agent": "task-one", "verdict": "changes", "comment": "no"})
        self.store.update_agent("task-two", pid=dead.pid, status="paused")  # stopped by the user: left alone
        for _ in range(4):  # the fake agent exits at once without fixing anything, so it is retried up to the limit
            cli.tick(self.store, auto_land=False)
            time.sleep(0.3)
        self.assertEqual(marker.read_text().split(), ["task-one", "task-one"])
        self.assertIn("requested changes", self.store.events_for("task-one", "resume"))


class EndToEnd(RepoCase):
    """`braid start` launches real processes (fake agents); the daemon predicts, reviews gate, resolves, lands."""
    agents = ()

    def test_full_run(self):
        braid("settings", "resolve.command", resolver("both"), cwd=self.repo)
        braid("settings", "test.command", f"{shlex.quote(sys.executable)} -c 'import m'", cwd=self.repo)
        braid("settings", "watch.interval", "0.5", cwd=self.repo)
        braid("settings", "agent.command", f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKES / 'agent.py'))}",
              cwd=self.repo)
        import json
        env = {**ENV,
               "BRAID_FAKE_LOGIN": json.dumps({"file": "m.py", "desc": "add login",
                                               "append": "\n\ndef login():\n    return 'in'\n"}),
               "BRAID_FAKE_EXPORT": json.dumps({"file": "m.py", "desc": "add export",
                                                "append": "\n\ndef export():\n    return 'csv'\n"})}
        r = sh(sys.executable, "-m", "braid", "start", "--name", "login", "login", cwd=self.repo, env=env)
        r2 = sh(sys.executable, "-m", "braid", "start", "--name", "export", "export", cwd=self.repo, env=env)
        try:
            deadline = time.time() + 60
            while time.time() < deadline:
                statuses = {a["name"]: a["status"] for a in self.store.agents()}
                if statuses and all(s == "landed" for s in statuses.values()):
                    break
                time.sleep(0.5)
            log = braid("feed", "-n", "100", cwd=self.repo).stdout
            self.assertEqual(statuses, {"login": "landed", "export": "landed"}, log)
            main = self.show("main")
            self.assertIn("def login()", main)
            self.assertIn("def export()", main)
            self.assertIn("landed on main", log)
            status = braid("status", cwd=self.repo).stdout
            self.assertIn("landed", status)
        finally:
            braid("stop", "--all", cwd=self.repo, check=False)


if __name__ == "__main__":
    unittest.main()
